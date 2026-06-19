#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Pre-match odds refresh — runs at 15:00 daily via launchd.
#
# Deletes and recomputes predictions for today's unstarted matches so the model
# uses closing-line odds (sharper market signal) rather than the morning odds
# stored by the 06:00 daily job.  Only touches today's fixtures; yesterday's
# completed results and tomorrow's predictions are untouched.
# ──────────────────────────────────────────────────────────────────────────────

set -uo pipefail

# launchd's minimal PATH lacks Docker Desktop's /usr/local/bin — without this
# every `docker` call fails ("command not found") and this job is a silent no-op.
export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/football-predictor"
LOG="$LOG_DIR/prematch.log"

mkdir -p "$LOG_DIR"

echo "" >> "$LOG"
echo "══════════════════════════════════════════" >> "$LOG"
echo " $(date '+%Y-%m-%d %H:%M:%S')  Pre-match odds refresh" >> "$LOG"
echo "══════════════════════════════════════════" >> "$LOG"

cd "$PROJ_DIR"

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a

echo "[1/2] Refreshing today's predictions with closing-line odds …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/compute_predictions.py --force-today \
    2>&1 | tee -a "$LOG"

# Refresh national-team odds + EV for fixtures in the next few days so the
# closing-line value signal stays current near kick-off (World Cup, EURO, etc.).
echo "" >> "$LOG"
echo "[2/3] Refreshing national-team odds + EV (next 4 days) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_national_odds.py --days-ahead 4 \
    2>&1 | tee -a "$LOG"

# Fill national results that finished after the 06:00 daily run (late-night
# US/Mexico games end in the Greek morning; live-scores fallback covers the
# martj42 publication lag).
echo "" >> "$LOG"
echo "[3/3] Filling national results (live-scores fallback) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/update_national_results.py \
    2>&1 | tee -a "$LOG"

echo "" >> "$LOG"
echo "Pre-match refresh complete at $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
