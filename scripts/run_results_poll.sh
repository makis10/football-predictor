#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Frequent result filler — runs every 2 hours via launchd.
#
# During live tournaments (World Cup, EURO…) national matches finish at all
# hours, including overnight US/Mexico kick-offs. The 06:00 daily + 15:00
# prematch jobs leave a long overnight gap where settled games sit "pending".
# This light job closes that gap: it only fills actual results (martj42 dataset
# + The Odds API live-scores fallback) and clears the stats cache. No odds, no
# predictions, no API quota beyond the scores endpoint.
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# launchd runs with a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin) that lacks
# Docker Desktop's /usr/local/bin — without this every `docker` call fails with
# "command not found" and the whole job is a silent no-op.
export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/football-predictor"
LOG="$LOG_DIR/results-poll.log"
mkdir -p "$LOG_DIR"

cd "$PROJ_DIR"
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a
_ADMIN_HDR=(-H "X-Admin-Key: ${ADMIN_API_KEY:-}")

echo "── $(date '+%Y-%m-%d %H:%M:%S') results poll ──" >> "$LOG"

# National results (dataset + live-scores fallback)
docker compose exec -T backend \
    python scripts/update_national_results.py \
    >> "$LOG" 2>&1

# Club results too — cheap no-op out of season, useful once leagues resume.
docker compose exec -T backend \
    python scripts/update_results.py --days-back 2 \
    >> "$LOG" 2>&1 || true

# API-Football authoritative overlay for the live tournament — fresh final
# scores + penalty winners into results.csv / shootouts.csv, so a team that lost
# (incl. on penalties → a draw in results.csv) drops out of the World Cup
# champion list within the 2-hour poll window, not at the next daily run.
docker compose exec -T backend \
    python scripts/fetch_wc_results.py \
    >> "$LOG" 2>&1 || true

# Refresh the dashboard so newly-settled matches appear immediately.
curl -s -X POST "${_ADMIN_HDR[@]}" http://localhost:8000/stats/cache/clear >> "$LOG" 2>&1 || true

echo "   done $(date '+%H:%M:%S')" >> "$LOG"
