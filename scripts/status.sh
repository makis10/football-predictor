#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Are the scheduled jobs running, and how did the last one go?
#
# The logs answer this, but only if you already know which of seven files to
# open, which line marks a run boundary, and that "[ok] all steps completed"
# lives 3,000 lines below the header. This prints the answer.
#
#   ./scripts/status.sh            snapshot: what's running, last outcome each
#   ./scripts/status.sh -f         follow the daily run live (step headers only)
#   ./scripts/status.sh -f raw     follow the daily log unfiltered
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

LOG_DIR="$HOME/Library/Logs/football-predictor"
LOCKS="/tmp/football-predictor-locks"

bold=$'\033[1m'; dim=$'\033[2m'; grn=$'\033[32m'; red=$'\033[31m'; ylw=$'\033[33m'; off=$'\033[0m'

# ── follow mode ───────────────────────────────────────────────────────────────
if [ "${1:-}" = "-f" ] || [ "${1:-}" = "--follow" ]; then
    if [ "${2:-}" = "raw" ]; then
        echo "${dim}following $LOG_DIR/daily.log — Ctrl-C to stop${off}"
        exec tail -f "$LOG_DIR/daily.log"
    fi
    echo "${dim}following the daily run — step headers and verdicts only."
    echo "use '-f raw' for everything. Ctrl-C to stop.${off}"
    # --line-buffered or grep sits on the matches until its buffer fills, which
    # is exactly the opposite of what "live" means.
    exec tail -f -n 40 "$LOG_DIR/daily.log" \
        | grep --line-buffered -E '^\[|^DATA (OK|GAPS) — |Daily run|Traceback|not running|BLOCKED'
fi

# ── what is running right now ─────────────────────────────────────────────────
echo "${bold}running now${off}"
running=0
for lock in "$LOCKS"/*.lock; do
    [ -d "$lock" ] || continue
    name=$(basename "$lock" .lock)
    pid=$(cat "$lock/pid" 2>/dev/null || echo "")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        since=$(ps -o lstart= -p "$pid" 2>/dev/null | sed 's/^ *//')
        echo "  ${grn}●${off} $name ${dim}(pid $pid, since ${since:-?})${off}"
        running=1
    else
        # mkdir-based locks survive a hard kill; acquire_lock reclaims them, but
        # a stale one here explains a job that looks "stuck".
        echo "  ${ylw}○${off} $name ${dim}(stale lock, pid $pid gone — will be reclaimed)${off}"
    fi
done
[ "$running" -eq 0 ] && [ ! -d "$LOCKS" ] && echo "  ${dim}nothing running${off}"
[ "$running" -eq 0 ] && [ -d "$LOCKS" ] && \
    ! ls -d "$LOCKS"/*.lock >/dev/null 2>&1 && echo "  ${dim}nothing running${off}"

# ── last outcome per job ──────────────────────────────────────────────────────
echo
echo "${bold}last run${off}"
_last_daily() {
    local log="$LOG_DIR/daily.log"
    [ -f "$log" ] || { echo "  ${dim}daily        no log yet${off}"; return; }
    local start end verdict steps
    start=$(grep -E '  Daily run$' "$log" | tail -1 | sed -E 's/^ *//;s/  Daily run$//')
    # Everything below is scoped to THIS run. Searching the whole file made an
    # in-progress run report the PREVIOUS run's completion time — so it looked
    # finished, and finished several minutes before it started.
    local from
    from=$(grep -n -E '  Daily run$' "$log" | tail -1 | cut -d: -f1)
    end=$(tail -n "+$from" "$log" | grep 'Daily run complete at' | tail -1 | sed -E 's/.*complete at //')
    verdict=$(tail -n "+$from" "$log" | grep -E '^\[ok\] all steps|^\[warn\] one or more steps' | tail -1)
    steps=$(tail -n "+$from" "$log" | sed -n '/failed step(s)/,/^\[/p' | grep '^  •' | sed 's/^  • //' | paste -sd', ' -)
    local mark="${grn}✓${off}"
    case "$verdict" in *"one or more"*) mark="${red}✗${off}";; esac
    if [ -z "$end" ]; then
        mark="${ylw}●${off}"                       # still going, verdict unknown
        end="${ylw}still running…${off}"
    fi
    printf "  %b daily        %s → %s\n" "$mark" "${start:-?}" "$end"
    [ -n "$steps" ] && printf "      ${red}failed:${off} %s\n" "$steps"
    local health
    health=$(tail -n "+$from" "$log" | grep -E '^DATA (OK|GAPS) — ' | tail -1)
    [ -n "$health" ] && printf "      ${dim}data: %s${off}\n" "$health"
    # Heartbeat is the dead-man's switch — its absence is the signal that matters.
    if tail -n "+$from" "$log" | grep -q '✓ heartbeat sent'; then
        printf "      ${grn}heartbeat sent${off}\n"
    elif [ -n "$verdict" ]; then
        printf "      ${ylw}no heartbeat${off} ${dim}(a step failed, or HEARTBEAT_URL unset)${off}\n"
    fi
}
_last_daily

for job in prematch odds-poll results-poll warmup watchdog; do
    log="$LOG_DIR/$job.log"
    if [ -f "$log" ]; then
        when=$(grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}' "$log" | tail -1)
        printf "  ${dim}·${off} %-12s %s\n" "$job" "${when:-—}"
    fi
done

# ── launchd's own view ────────────────────────────────────────────────────────
echo
echo "${bold}launchd${off} ${dim}(● = running now · ✓ = idle, last run clean · ✗ = idle, last run failed)${off}"
# A running job is healthy whatever its last exit code was. cloudflared has
# KeepAlive, so it dies and is restarted whenever the Mac wakes before the
# network is up — one DNS timeout, back in a second — and reporting that stale
# exit code as ✗ made a self-healing job look broken every single day.
launchctl list 2>/dev/null | grep football | while read -r pid exit label; do
    name="${label#com.football-predictor.}"
    if [ "$pid" != "-" ]; then
        mark="${grn}●${off}"; note="${dim}(running)${off}"
        [ "$exit" != "0" ] && note="${dim}(running · restarted after exit $exit)${off}"
    elif [ "$exit" = "0" ]; then
        mark="${grn}✓${off}"; note=""
    else
        mark="${red}✗${off}"; note="${red}last run failed (exit $exit)${off}"
    fi
    printf "  %b %-34s pid=%-6s %b\n" "$mark" "$name" "$pid" "$note"
done

echo
echo "${dim}follow a run live:  ./scripts/status.sh -f${off}"
