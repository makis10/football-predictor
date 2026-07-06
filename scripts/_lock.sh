# shellcheck shell=bash
# ──────────────────────────────────────────────────────────────────────────────
# acquire_lock — mkdir-based mutual exclusion for the launchd cron scripts.
#
# launchd's StartCalendarInterval coalesces missed runs after sleep/reboot, so
# run_daily.sh / run_prematch.sh / run_results_poll.sh can end up firing back
# to back against the same DB/CSVs with no ordering guarantee. `mkdir` is
# atomic on every filesystem we run on (unlike a plain `test -f` + `touch`
# check), so it's used here instead of `flock` (not installed on macOS by
# default). Source this file and call `acquire_lock "<name>"` before any
# mutating work; it registers an EXIT trap that releases the lock.
#
# Return: 0 if the lock was acquired, 1 if another instance already holds it
# (caller should exit 0 — this is an expected skip, not a failure).
# ──────────────────────────────────────────────────────────────────────────────
acquire_lock() {
    local name="$1"
    local lockdir="/tmp/football-predictor-locks"
    mkdir -p "$lockdir"
    local lock="$lockdir/$name.lock"

    if mkdir "$lock" 2>/dev/null; then
        echo $$ > "$lock/pid"
        # shellcheck disable=SC2064
        trap "rm -rf '$lock'" EXIT
        return 0
    fi

    local pid
    pid=$(cat "$lock/pid" 2>/dev/null || echo "")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "[lock] another $name run (pid $pid) is already in progress — skipping this run."
        return 1
    fi

    # Stale lock (process no longer running) — reclaim it.
    rm -rf "$lock"
    if mkdir "$lock" 2>/dev/null; then
        echo $$ > "$lock/pid"
        # shellcheck disable=SC2064
        trap "rm -rf '$lock'" EXIT
        return 0
    fi
    return 1
}
