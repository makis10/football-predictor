#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Odds-movement snapshot poller — runs every 8 hours via launchd
# (00:00 / 08:00 / 16:00). Which matches it actually re-prices on a given
# run is decided per match by the tiers in poll_odds.py.
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

# ── 1. Fresh UEFA pairings ────────────────────────────────────────────────────
# During the qualifying rounds a tie's next opponent only exists once the second
# leg is played, and API-Football publishes the new pairing during the day — so
# the 06:00 daily fetch misses it and the site shows a partial round for up to
# 24 h (2026-07-30: we held 4 of 10 CL Q3 ties). Re-fetching here costs 3
# API-Football calls per poll (~24/day against a 7,500 quota).
#
# Narrow window on purpose: this is a freshness top-up, not the backfill path —
# widen --days-back only when recovering from an outage (see run_daily).
docker compose exec -T backend \
    python scripts/fetch_european_fixtures.py --days-ahead 21 --days-back 1 \
    >> "$LOG" 2>&1 || echo "   [warn] European fixture refresh failed — daily run will retry" >> "$LOG"

# ── 2. Odds snapshot ──────────────────────────────────────────────────────────
docker compose exec -T backend \
    python scripts/poll_odds.py \
    >> "$LOG" 2>&1
status=$?

# ── 3. Price what the market just opened ──────────────────────────────────────
# Two jobs in one pass: predictions for fixtures that arrived in step 1, and a
# recompute of any FUTURE prediction that was priced before its market opened
# (bm_* NULL) and now has odds in odds_history — without this the EV / value
# gate and CLV tracking stayed blind until match day. No API cost.
docker compose exec -T backend \
    python scripts/compute_predictions.py --force-missing-odds \
    >> "$LOG" 2>&1 || echo "   [warn] prediction top-up failed" >> "$LOG"

echo "   done $(date '+%H:%M:%S') (exit $status)" >> "$LOG"
exit "$status"
