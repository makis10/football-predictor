#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Odds-movement snapshot poller — runs every 3 hours via launchd.
#
# Stores one odds_history row per upcoming match per cycle; the analysis page
# diffs the last two snapshots to draw the "odds moved" arrows and stats derives
# CLV from them. MUST run inside the backend container (like every other job):
# the previous odds-poll.plist ran `.venv/bin/python poll_odds.py` directly on
# the host, but there is no .venv AND DATABASE_URL points at `db:5432` (a
# container-internal hostname), so it failed on every fire (launchd exit 78) and
# odds_history never filled. This wrapper fixes both.
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# launchd's minimal PATH lacks Docker Desktop's bin dirs — without this every
# `docker` call fails "command not found" and the job is a silent no-op.
export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/football-predictor"
LOG="$LOG_DIR/odds-poll.log"
mkdir -p "$LOG_DIR"

# Don't run alongside another instance of this job.
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/_lock.sh"
acquire_lock "run_odds_poll" || exit 0

cd "$PROJ_DIR"
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a

echo "── $(date '+%Y-%m-%d %H:%M:%S') odds poll ──" >> "$LOG"

# Guard against launchd firing on wake before Docker Desktop is up.
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/wait_docker.sh"
wait_for_docker "$LOG" || exit 1

docker compose exec -T backend \
    python scripts/poll_odds.py \
    >> "$LOG" 2>&1
status=$?

echo "   done $(date '+%H:%M:%S') (exit $status)" >> "$LOG"
exit "$status"
