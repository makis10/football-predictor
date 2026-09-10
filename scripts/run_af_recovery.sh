#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# API-Football recovery run — replays what a blocked daily run skipped.
#
# The account is IP-whitelisted and this line's address is dynamic. When the
# 06:00 pre-flight finds the address refused (or API-Football unreachable), the
# daily run skips every API-Football step and leaves .af-recovery-pending in the
# log directory, holding the date. Before this script the data then waited for
# the NEXT 06:00 run even once the new address was whitelisted: on 2026-09-10
# the whitelist was fixed around 10:00, and CL/EL/ECL fixtures and results,
# friendlies, the expansion leagues, squads, club stats, injuries and the
# API-Football odds top-up would all have stayed a day old.
#
# run_watchdog.sh checks every 5 minutes and starts this as soon as /status
# answers cleanly, so whitelisting the address is the only manual step. By hand:
#     bash scripts/run_af_recovery.sh                        # today's marker set
#     FORCE_AF_RECOVERY=1 bash scripts/run_af_recovery.sh    # regardless
#
# What it runs: every step run_daily.sh keeps behind the API-Football guard,
# with the same arguments (backend/tests/test_config_consistency.py fails when
# one is missing here), then the steps that consume their output. Nothing else
# is repeated — the rest of the daily run already happened at 06:00. So:
#   · no Odds API credits: no odds fetch, no analysis warm-up (the 50-minute
#     warm-up job owns that), and no warmup_standings / snapshot_projections
#     pair — the snapshot prices title markets on the Odds API, and the warm-up
#     alone would strip that column from today's projection cache;
#   · today's tickets are left alone — generate_tickets without --replace only
#     builds a day that has none;
#   · no national re-prediction: squad strength refreshed here feeds tomorrow's
#     run, because re-predicting internationals means re-pricing them too.
#
# Quota: the blocked daily run spent nothing on API-Football, so a same-day
# replay fits inside the 7,500/day cap. That is why the marker only counts on
# the date it was written — after midnight the next 06:00 run does the job.
#
# One attempt per marker: it is cleared as soon as the pre-flight passes, so a
# step failing for any other reason cannot have the watchdog relaunch this
# every five minutes. Only a fresh IP refusal part-way re-arms it.
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# launchd's minimal PATH lacks Docker Desktop's bin dirs.
export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/football-predictor"
LOG="$LOG_DIR/daily.log"
AF_RECOVERY_MARKER="$LOG_DIR/.af-recovery-pending"
mkdir -p "$LOG_DIR"

today=$(date '+%Y-%m-%d')
if [ "${FORCE_AF_RECOVERY:-0}" != "1" ] \
   && [ "$(cat "$AF_RECOVERY_MARKER" 2>/dev/null)" != "$today" ]; then
    echo "[af-recovery] nothing pending for $today."
    exit 0
fi

# The daily run's own lock: the two must never overlap (same DB, same CSVs,
# same per-minute API allowance).
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/_lock.sh"
acquire_lock "run_daily" || exit 0

cd "$PROJ_DIR"
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a
_ADMIN_HDR=(-H "X-Admin-Key: ${ADMIN_API_KEY:-}")
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/_alert.sh"

echo "" >> "$LOG"
echo "══════════════════════════════════════════" >> "$LOG"
echo " $(date '+%Y-%m-%d %H:%M:%S')  API-Football recovery run" >> "$LOG"
echo "══════════════════════════════════════════" >> "$LOG"

# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/wait_docker.sh"
wait_for_docker "$LOG" || exit 1

echo "[r0] API-Football pre-flight …" | tee -a "$LOG"
docker compose exec -T backend python scripts/preflight_api_football.py 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
if [ "$rc" -ne 0 ]; then
    echo "  [skip] API-Football still unusable (pre-flight rc=$rc) — marker kept." | tee -a "$LOG"
    exit "$rc"
fi
rm -f "$AF_RECOVERY_MARKER"

# Same exit-code contract as run_daily.sh (scripts/_http_retry.py).
AF_BLOCKED_RC=2
AF_QUOTA_RC=4
af_on=1      # cleared by the daily cap or a fresh refusal
blocked=0
failed=""

# af_step <label> python scripts/<x>.py [args…] — one API-Football step.
af_step() {
    local label="$1"; shift
    echo "" >> "$LOG"
    echo "[$label] $2 …" | tee -a "$LOG"
    if [ "$af_on" -ne 1 ]; then
        echo "  [skip] API-Football unavailable for the rest of this run." | tee -a "$LOG"
        return 0
    fi
    docker compose exec -T backend "$@" 2>&1 | tee -a "$LOG"
    local rc=${PIPESTATUS[0]}
    if [ "$rc" -eq "$AF_QUOTA_RC" ]; then
        af_on=0
        echo "  [skip] API-Football out of daily requests — remaining API-Football steps skipped." | tee -a "$LOG"
    elif [ "$rc" -eq "$AF_BLOCKED_RC" ]; then
        af_on=0
        blocked=1
        date '+%Y-%m-%d' > "$AF_RECOVERY_MARKER"
        echo "  [skip] API-Football refused the IP again — marker re-armed." | tee -a "$LOG"
    elif [ "$rc" -ne 0 ]; then
        failed="${failed}${failed:+, }${2#scripts/}"
        echo "  [warn] ${2#scripts/} failed (rc=$rc)" | tee -a "$LOG"
    fi
}

# step <label> python scripts/<x>.py [args…] — a step with no API-Football call.
step() {
    local label="$1"; shift
    echo "" >> "$LOG"
    echo "[$label] $2 …" | tee -a "$LOG"
    docker compose exec -T backend "$@" 2>&1 | tee -a "$LOG"
    local rc=${PIPESTATUS[0]}
    if [ "$rc" -ne 0 ]; then
        failed="${failed}${failed:+, }${2#scripts/}"
        echo "  [warn] ${2#scripts/} failed (rc=$rc)" | tee -a "$LOG"
    fi
}

# ── Fixtures and results (run_daily 4b–5b) ───────────────────────────────────
af_step "4b/6" python scripts/fetch_greek_apifootball.py --days-ahead 120 --days-back 5
af_step "4c/6" python scripts/fetch_domestic_apifootball.py --days-ahead 120 --days-back 5
af_step "4c2/6" python scripts/import_history_apifootball.py
af_step "5/6" python scripts/fetch_european_fixtures.py --days-ahead 120 --days-back 5
af_step "5b/6" python scripts/fetch_club_friendlies.py --days-ahead 14 --days-back 7 --no-predictions

# New rows: merge feed-spelling duplicates, then price them (run_daily 5d, 6).
step "5d/6" python scripts/dedupe_fixtures.py --apply
step "6/6" python scripts/compute_predictions.py

# ── Injuries and the club props sources (run_daily 8, 8b) ────────────────────
af_step "8/9" python scripts/warmup_injuries.py --days 3
af_step "8b/9" python scripts/fetch_club_squads.py --days-ahead 7 --max-age-days 6 --max-requests 700
af_step "8b/9" python scripts/fetch_club_team_stats.py --days-ahead 7 --last 8 --max-requests 1200
af_step "8b/9" python scripts/fetch_club_player_stats.py --days-ahead 7 --last 8 --max-requests 2000

# ── National (run_daily national 1c, 4b, 7a–7a2, 7c) ─────────────────────────
WC_ACTIVE="${WC_ACTIVE:-0}"
SQUAD_SEASON=$(date +%Y); [ "$(date +%m)" -lt 7 ] && SQUAD_SEASON=$((SQUAD_SEASON - 1))
if [ "$WC_ACTIVE" = "1" ]; then
    af_step "national 1c/7" python scripts/fetch_wc_results.py
fi
af_step "national 4b/7" python scripts/fetch_squad_strength.py --season "$SQUAD_SEASON" --max-age-days 6 --max-requests 1700
af_step "national 7a/7" python scripts/fetch_player_stats.py --wc-only --last 5 --max-requests 2500
af_step "national 7a1/7" python scripts/fetch_match_statistics.py --wc-only --last 5 --max-requests 1500
af_step "national 7a2/7" python scripts/fetch_club_form.py --wc-only --max-requests 1500
step "national 7a3/7" python scripts/compute_player_props.py
if [ "$WC_ACTIVE" = "1" ]; then
    af_step "national 7c/7" python scripts/fetch_wc_squads.py --max-age-days 7
    af_step "national 7c2/7" python scripts/fetch_availability.py
fi

# ── API-Football odds for what The Odds API did not price (run_daily 8d) ─────
af_step "8d/9" python scripts/fetch_odds_apifootball.py --days 7

# ── Tickets (only builds a day that has none) and the stats cache ────────────
step "9a/9" python scripts/generate_tickets.py
echo "" >> "$LOG"
echo "[9/9] Clearing stats cache …" | tee -a "$LOG"
curl -s -X POST "${_ADMIN_HDR[@]}" http://localhost:8000/stats/cache/clear >> "$LOG" 2>&1 || true

# ── The completeness report the block suppressed this morning ────────────────
# Exit 1 means "alerts raised", not "broken" — reported, never counted as a
# failed step (same as run_daily.sh).
echo "" >> "$LOG"
echo "[health] Data-completeness check …" | tee -a "$LOG"
docker compose exec -T backend python scripts/check_data_completeness.py --days 7 2>&1 | tee -a "$LOG"
verdict=$(tail -n 600 "$LOG" | grep -E '^DATA (OK|GAPS) — ' | tail -1)

# ── Summary ──────────────────────────────────────────────────────────────────
if [ "$blocked" -eq 1 ]; then
    summary="API-Football refused the IP again part-way; the rest runs once the new address is whitelisted."
    prio=high; tags="rotating_light,soccer"; status=2
elif [ -n "$failed" ]; then
    summary="Replayed, with failed steps: $failed"
    prio=high; tags="warning,soccer"; status=1
else
    summary="Every skipped API-Football step replayed."
    prio=default; tags="white_check_mark,soccer"; status=0
fi
echo "" >> "$LOG"
echo "API-Football recovery finished at $(date '+%Y-%m-%d %H:%M:%S') — $summary" | tee -a "$LOG"
send_alert "Football Predictor: API-Football recovery" \
    "$(printf 'Το API-Football δέχεται ξανά την IP — ξανατρέξαμε ό,τι είχε παραλείψει το σημερινό daily.\n\n%s\n%s' \
         "$summary" "${verdict:-}")" \
    "$prio" "$tags" "$LOG"
exit "$status"
