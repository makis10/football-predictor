#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Daily maintenance script for football-predictor.
# Runs inside the backend container via docker compose exec.
#
# Daily order (every day):
#   1. update_results.py          — write final scores for domestic + CL (football-data.org)
#   2. update_european_results.py — write final scores for GreekSL / EL / ECL (The Odds API)
#   3. fetch_upcoming.py          — refresh fixture schedule (next 60 days)
#   4. fetch_greek_fixtures.py    — refresh Greek SL fixtures (The Odds API)
#   5. fetch_european_fixtures.py — refresh CL/EL/ECL fixtures
#   6. compute_predictions.py     — ML predictions for any new fixtures
#   7. backfill_bm_odds.py        — fill bm_odds from CSVs for completed matches missing them
#   8. clear stats cache          — so dashboard reflects latest results immediately
#
# Weekly extra (every Monday):
#   9.  download_data.py --refresh-current         — re-download current season CSVs
#   10. download_xg_apifootball.py --force         — refresh CL/EL/ECL xG for current season
#   11. python -m backend.app.ml.train             — retrain models on fresh data
#   12. compute_predictions.py --force             — recompute all predictions
#   13. backfill_bm_odds.py                        — backfill any newly available odds
#   14. clear stats cache
#
# Triggered by launchd every morning at 06:00.
# Logs go to ~/Library/Logs/football-predictor/daily.log
# ──────────────────────────────────────────────────────────────────────────────

set -uo pipefail  # removed -e so one failed step doesn't abort the rest

# launchd's minimal PATH lacks Docker Desktop's /usr/local/bin — without this
# every `docker` call fails ("command not found") and the daily run is a silent
# no-op (the root cause of stale results / predictions never auto-updating).
export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/football-predictor"
LOG="$LOG_DIR/daily.log"

# Load ADMIN_API_KEY (needed for the now-protected /stats/cache/clear endpoint).
# shellcheck disable=SC1091
[ -f "$PROJ_DIR/.env" ] && set -a && . "$PROJ_DIR/.env" && set +a
_ADMIN_HDR=(-H "X-Admin-Key: ${ADMIN_API_KEY:-}")

mkdir -p "$LOG_DIR"

echo "" >> "$LOG"
echo "══════════════════════════════════════════" >> "$LOG"
echo " $(date '+%Y-%m-%d %H:%M:%S')  Daily run" >> "$LOG"
echo "══════════════════════════════════════════" >> "$LOG"

cd "$PROJ_DIR"

# Load env vars from .env so API keys are available on the host too
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a

# ── 0. Back up the database BEFORE any mutation ──────────────────────────────
# ── Wait for Docker to be ready ──────────────────────────────────────────────
# Guards against launchd firing this job on wake before Docker Desktop is up.
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/wait_docker.sh"
echo "" >> "$LOG"
wait_for_docker "$LOG" || exit 1

# A daily snapshot of everything that can't be regenerated (users, bets, the
# value ledger, settled results) — taken first so today's --force/retrain can
# never leave us without a restore point.
echo "" >> "$LOG"
echo "[0] Backing up database …" | tee -a "$LOG"
bash "$PROJ_DIR/scripts/backup_db.sh" 2>&1 | tee -a "$LOG" || echo "  [warn] backup failed — continuing" | tee -a "$LOG"

# ── 1. Update domestic + CL results (football-data.org) ──────────────────────
echo "[1/6] Updating domestic + CL match results …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/update_results.py --days-back 7 \
    2>&1 | tee -a "$LOG"

# ── 2. Update GreekSL / EL / ECL results (The Odds API) ──────────────────────
echo "" >> "$LOG"
echo "[2/6] Updating GreekSL / EL / ECL match results …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/update_european_results.py \
        --key "${ODDS_API_KEY:-}" \
        --days-from 3 \
    2>&1 | tee -a "$LOG"

# ── 3. Refresh upcoming fixtures (top-5 leagues via football-data.org) ────────
echo "" >> "$LOG"
echo "[3/6] Refreshing upcoming fixtures (top-5 leagues) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_upcoming.py \
        --key "${FOOTBALLDATA_API_KEY:-}" \
        --days 60 \
        --no-predictions \
    2>&1 | tee -a "$LOG"

# ── 4. Refresh Greek SL fixtures (The Odds API — 1 req per run) ──────────────
echo "" >> "$LOG"
echo "[4/6] Refreshing Greek SL fixtures …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_greek_fixtures.py \
        --key "${ODDS_API_KEY:-}" \
        --no-predictions \
    2>&1 | tee -a "$LOG"

# ── 5. Refresh European fixtures (CL from CSVs, EL/ECL from Odds API) ────────
echo "" >> "$LOG"
echo "[5/6] Refreshing European fixtures (CL/EL/ECL) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_european_fixtures.py \
        --odds-key "${ODDS_API_KEY:-}" \
        --no-predictions \
    2>&1 | tee -a "$LOG"

# ── 6. Compute any missing predictions ───────────────────────────────────────
echo "" >> "$LOG"
echo "[6/6] Computing missing predictions …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/compute_predictions.py \
    2>&1 | tee -a "$LOG"

echo "" >> "$LOG"
echo "[7/9] Backfilling bm_odds from CSVs …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/backfill_bm_odds.py \
    2>&1 | tee -a "$LOG"

# ── 8. Pre-warm injury cache for new fixtures (next 3 days, skips existing) ───
echo "" >> "$LOG"
echo "[8/9] Pre-warming injury cache for new fixtures …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/warmup_injuries.py --days 3 \
    2>&1 | tee -a "$LOG"

# ── National teams (international fixtures) ───────────────────────────────────
# a. Refresh martj42 dataset (newly-played scores appear here once played)
# b. Re-inject manually-added upcoming friendlies (dedup keeps played versions)
# c. Regenerate predictions for all upcoming internationals (upsert)
# d. Fetch bookmaker odds + value-bet EV (tournaments The Odds API covers)
# e. Fill actual results for internationals that have now been played
# f. Re-run the World Cup Monte Carlo simulation (champion/finalist odds)
echo "" >> "$LOG"
echo "[national 1/7] Refreshing international dataset (martj42) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_international_data.py --force \
    2>&1 | tee -a "$LOG"

# Sync DB-known results into results.csv first — martj42 lags ~1 day, so this
# ensures the retrain/snapshot below see yesterday's matches (true self-correct).
echo "" >> "$LOG"
echo "[national 1b/7] Syncing settled results into dataset …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/sync_results_to_dataset.py \
    2>&1 | tee -a "$LOG"

# API-Football is the source of truth for the LIVE tournament — fresher and more
# accurate than martj42 (which lags ~1 day and rarely records penalty winners
# quickly). Overlay its final scores + shoot-out winners onto results.csv /
# shootouts.csv. MUST run after the martj42 --force above (which would otherwise
# clobber it) and before the retrain/snapshot/sim so everything sees the truth.
echo "" >> "$LOG"
echo "[national 1c/7] Overlaying live WC results from API-Football …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_wc_results.py \
    2>&1 | tee -a "$LOG"

# Daily full retrain — during a live tournament the model self-corrects every
# day on the freshly-downloaded results. (User-requested over snapshot-only.)
# Rebuilds models + the Elo/form snapshot together.
echo "" >> "$LOG"
echo "[national 2/7] Daily national retrain …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/train_national.py \
    2>&1 | tee -a "$LOG"

echo "" >> "$LOG"
echo "[national 3/7] Re-injecting manual upcoming friendlies …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/add_upcoming_national.py \
    2>&1 | tee -a "$LOG"

# Safety net: if the retrain step failed (pipeline continues on error), refresh
# the Elo/form snapshot alone so predictions still reflect the latest results.
echo "" >> "$LOG"
echo "[national 4/7] Refreshing Elo snapshot (safety) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/refresh_national_snapshot.py \
    2>&1 | tee -a "$LOG"

# Squad-strength (talent-adjusted Elo): which leagues each called-up player
# plays in → per-team strength used to de-bias the confederation-siloed Elo at
# inference. Squads change slowly, so --max-age-days 6 makes this run ~weekly
# (≈1300 API-Football calls when it does). MUST precede predict (step 5) so the
# fresh squad_strength.json feeds the talent adjustment.
echo "" >> "$LOG"
echo "[national 4b/7] Refreshing squad strength (weekly) …" | tee -a "$LOG"
# Club season = year it started (European seasons start in July; before July
# we're still in the previous season, e.g. June 2026 → 2025/26 → season 2025).
SQUAD_SEASON=$(date +%Y); [ "$(date +%m)" -lt 7 ] && SQUAD_SEASON=$((SQUAD_SEASON - 1))
docker compose exec -T backend \
    python scripts/fetch_squad_strength.py --season "$SQUAD_SEASON" --max-age-days 6 --max-requests 1700 \
    2>&1 | tee -a "$LOG"

echo "" >> "$LOG"
echo "[national 5/7] Generating international predictions …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/predict_national.py --save-db \
    2>&1 | tee -a "$LOG"

echo "" >> "$LOG"
echo "[national 6/7] Fetching bookmaker odds + EV for internationals …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_national_odds.py \
    2>&1 | tee -a "$LOG"

echo "" >> "$LOG"
echo "[national 7/7] Filling actual international results …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/update_national_results.py \
    2>&1 | tee -a "$LOG"

# Ingest player stats for recently-played WC matches (anytime scorer / SoT /
# assists / cards props + settlement actuals). --last 5; finished fixtures
# already in player_match_stats are skipped. Budget must cover ALL ~48 WC teams
# (400 was too small during the tournament → Mexico/SK etc. went un-ingested,
# leaving "what we caught" blank). Pro plan = 7500/day, so 2500 is safe.
echo "" >> "$LOG"
echo "[national 7a/7] Ingesting player match stats (API-Football) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_player_stats.py --wc-only --last 5 --max-requests 2500 \
    2>&1 | tee -a "$LOG"

# Ingest team match stats (corners / shots / possession) from /fixtures/statistics
# — corners aren't in /fixtures/players, so this is a separate cheap pull.
echo "" >> "$LOG"
echo "[national 7a1/7] Ingesting team match stats (API-Football) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_match_statistics.py --wc-only --last 5 --max-requests 1500 \
    2>&1 | tee -a "$LOG"

# Ingest current-season CLUB form per player (/players) — the empirical-Bayes
# prior for the prop rates, so low-cap players regress toward real club form
# instead of a flat league prior. Idempotent: only rows older than 7 days are
# refreshed, so the cost amortises across days (1 request/player, budget-capped).
echo "" >> "$LOG"
echo "[national 7a2/7] Ingesting player club form (API-Football) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_club_form.py --wc-only --max-requests 1500 \
    2>&1 | tee -a "$LOG"

# Recompute player props (anytime scorer / SoT / assist) for upcoming fixtures
# from the freshly-ingested stats + club-form priors + the refreshed Elo snapshot.
echo "" >> "$LOG"
echo "[national 7a3/7] Computing player props …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/compute_player_props.py \
    2>&1 | tee -a "$LOG"

# 5b. Catch never-anticipated fixtures: any match played in the last 3 days
# that has NO prediction row (e.g. friendlies missing from our fixture list)
# gets an honest pre-match replay row (insert-only — live predictions are
# never overwritten). Prevents silent gaps in Recent Results / stats.
echo "" >> "$LOG"
echo "[national 7b/7] Backfilling missed recent fixtures …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/backfill_national_predictions.py \
        --from "$(date -v-3d +%Y-%m-%d)" --skip-existing \
    2>&1 | tee -a "$LOG"

# Official WC squads for the Golden Boot squad filter. Skips itself when the
# file is < 7 days old, so it only spends API-Football quota once a week.
echo "" >> "$LOG"
echo "[national 7c/7] Refreshing WC squads (weekly) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_wc_squads.py --max-age-days 7 \
    2>&1 | tee -a "$LOG"

# Sync same-day goals from player_match_stats into goalscorers.csv so the
# Golden Boot below reflects today's scorers immediately (martj42 lags ~1 day).
echo "" >> "$LOG"
echo "[national 7c2/7] Syncing same-day goalscorers …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/sync_goalscorers_to_dataset.py \
    2>&1 | tee -a "$LOG"

# Player availability (injuries + suspensions) from API-Football /injuries —
# one cheap request; lets the simulation drop unavailable golden-boot scorers.
echo "" >> "$LOG"
echo "[national 7c2/7] Fetching player availability (injuries/suspensions) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_availability.py \
    2>&1 | tee -a "$LOG"

# World Cup Monte Carlo simulation (champion/finalist/group/golden-boot).
# Exits cheaply once the tournament is over (no upcoming group fixtures).
echo "" >> "$LOG"
echo "[national 7d/7] Running World Cup Monte Carlo simulation …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/simulate_wc.py --sims 20000 --save-json \
    2>&1 | tee -a "$LOG"

# ── Monthly rolling recalibration (1st of the month) ─────────────────────────
# Refits the second-stage isotonic correction from the last 365 days of stored
# predictions vs actual results (out-of-sample by construction). Skips itself
# below 300 completed predictions.
if [ "$(date +%d)" = "01" ]; then
    echo "" >> "$LOG"
    echo "[monthly] Rolling recalibration …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/recalibrate.py \
        2>&1 | tee -a "$LOG"
fi

echo "" >> "$LOG"
echo "[9/9] Clearing stats cache …" | tee -a "$LOG"
curl -s -X POST "${_ADMIN_HDR[@]}" http://localhost:8000/stats/cache/clear >> "$LOG" 2>&1 || true
echo "" >> "$LOG"
echo "Daily run complete at $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"

# ── Weekly retrain (Mondays only) ─────────────────────────────────────────────
DAY_OF_WEEK=$(date +%u)   # 1=Mon … 7=Sun
if [ "$DAY_OF_WEEK" -eq 1 ]; then
    echo "" >> "$LOG"
    echo "══════════════════════════════════════════" >> "$LOG"
    echo " $(date '+%Y-%m-%d %H:%M:%S')  Weekly retrain (Monday)" >> "$LOG"
    echo "══════════════════════════════════════════" >> "$LOG"

    # 6b. Deep result backfill — catches matches finalised late (postponements,
    # abandoned/PAUSED games completed days later) that the daily 7-day window
    # missed. football-data.org leagues only: The Odds API scores endpoint
    # caps daysFrom at 3, so GreekSL/EL/ECL cannot be deep-backfilled here.
    echo "[6b/10] Deep result backfill (30 days) …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/update_results.py --days-back 30 \
        2>&1 | tee -a "$LOG"

    # 7. Refresh current-season CSVs so training data is up-to-date
    echo "[7/10] Refreshing current-season CSVs …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/download_data.py --refresh-current \
        2>&1 | tee -a "$LOG"

    # 8a. Refresh understat xG for top-5 leagues (current season)
    echo "" >> "$LOG"
    echo "[8a/10] Refreshing understat xG (top-5 leagues, current season) …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/download_xg.py --season 2025 \
        2>&1 | tee -a "$LOG"

    # 8b. Refresh API-Football xG for remaining leagues (api-sports.io)
    #    --force overwrites so newly-added xG for recent matches is picked up.
    #    Current season = year the season started (e.g. 2025 for 2025-26).
    CURRENT_SEASON=$(date +%Y)
    # European seasons start in July; before July we're still in the previous season
    MONTH=$(date +%m)
    [ "$MONTH" -lt 7 ] && CURRENT_SEASON=$((CURRENT_SEASON - 1))
    echo "" >> "$LOG"
    echo "[8b/10] Refreshing CL/EL/ECL/Eredivisie/PrimeiraLiga/Championship xG for season ${CURRENT_SEASON} …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/download_xg_apifootball.py \
            --leagues CL EL ECL Eredivisie PrimeiraLiga Championship \
            --seasons "${CURRENT_SEASON}" \
            --force \
        2>&1 | tee -a "$LOG"

    # 9. Retrain both models (takes ~2-3 min)
    echo "" >> "$LOG"
    echo "[9/10] Retraining ML models …" | tee -a "$LOG"
    docker compose exec -T backend \
        python -m backend.app.ml.train \
        2>&1 | tee -a "$LOG"

    # 9b. Refit the second-stage rolling calibration against the new models
    echo "" >> "$LOG"
    echo "[9b/10] Refitting rolling recalibration after retrain …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/recalibrate.py \
        2>&1 | tee -a "$LOG"

    # 10. Force-recompute all upcoming predictions with the new models
    echo "" >> "$LOG"
    echo "[10/10] Recomputing all predictions with new models …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/compute_predictions.py --force \
        2>&1 | tee -a "$LOG"

    echo "" >> "$LOG"
    echo "[11/12] Backfilling bm_odds from freshly-downloaded CSVs …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/backfill_bm_odds.py \
        2>&1 | tee -a "$LOG"

    echo "" >> "$LOG"
    echo "[12/12] Clearing stats cache after retrain …" | tee -a "$LOG"
    curl -s -X POST "${_ADMIN_HDR[@]}" http://localhost:8000/stats/cache/clear >> "$LOG" 2>&1 || true

    # NOTE: national-team retrain is no longer here — it runs DAILY in the
    # national block above (self-corrects after every match during tournaments).

    echo "" >> "$LOG"
    echo "Weekly retrain complete at $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
fi

# ── Dead-man's-switch heartbeat ──────────────────────────────────────────────
# Ping a monitor (e.g. healthchecks.io) on successful completion. If launchd
# never fires or the job dies before here, the ping is missed and the monitor
# alerts — this pipeline has silently no-op'd before (docker PATH), so we watch
# it. Set HEARTBEAT_URL in .env to enable; no-op when unset.
if [ -n "${HEARTBEAT_URL:-}" ]; then
    curl -fsS -m 10 --retry 3 "$HEARTBEAT_URL" >> "$LOG" 2>&1 \
        && echo "✓ heartbeat sent" >> "$LOG" \
        || echo "[warn] heartbeat ping failed" >> "$LOG"
fi
