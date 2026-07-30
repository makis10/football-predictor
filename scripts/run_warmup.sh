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

# Never let two warm-ups race the same fixtures.
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/_lock.sh"
acquire_lock "run_warmup" || exit 0

# Locks are per-name, so acquire_lock above does NOT keep this off the daily
# job's toes. Stand aside explicitly while daily or prematch is running: they
# saturate the API-Football per-minute limit, and a warm-up that lands in that
# window just burns credits on 429s (20/60 fixtures failed on 2026-07-20 and
# again on 2026-07-29). Warming runs every ~50 min, so skipping one is free —
# the next cycle picks the fixtures up.
for _busy in run_daily run_prematch; do
    if lock_held "$_busy"; then
        echo "── $(date '+%Y-%m-%d %H:%M:%S') skipped — $_busy in progress" >> "$LOG"
        exit 0
    fi
done

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
