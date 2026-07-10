#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Analysis-cache warm-up — runs every 50 minutes via launchd.
#
# The match pages fetch /analysis client-side. Cold, that call costs seconds
# (bookmaker odds + injuries + a Groq narrative); warm, ~0.02 s. Without this
# job the first visitor after every cache expiry stares at a skeleton.
#
# Interval is deliberately just under ANALYSIS_CACHE_TTL (1 h) so an entry is
# re-primed shortly before it expires and the cache is never observed cold.
# Cheap: entries still alive return in ~0.1 s and cost no Groq call, and the
# league odds come from their own cache (one Odds-API request per run).
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# launchd runs with a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin) that lacks
# Docker Desktop's /usr/local/bin — without this every `docker` call fails with
# "command not found" and the whole job is a silent no-op.
export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/football-predictor"
LOG="$LOG_DIR/warmup.log"
mkdir -p "$LOG_DIR"

# Never let two warm-ups (or a warm-up and the daily job) race the same fixtures.
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/_lock.sh"
acquire_lock "run_warmup" || exit 0

cd "$PROJ_DIR"

echo "── $(date '+%Y-%m-%d %H:%M:%S') analysis warm-up ──" >> "$LOG"

# Guard against launchd firing this job on wake before Docker Desktop is up.
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/wait_docker.sh"
wait_for_docker "$LOG" || exit 1

docker compose exec -T backend \
    python scripts/warmup_analysis.py --days 2 \
    >> "$LOG" 2>&1 || echo "  [warn] warm-up failed — pages still work, just cold" >> "$LOG"

echo "   done $(date '+%H:%M:%S')" >> "$LOG"
