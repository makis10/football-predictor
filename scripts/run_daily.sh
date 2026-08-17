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
#   5b. fetch_club_friendlies.py  — refresh club friendlies + their results (API-Football)
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

# Guard against launchd's missed-run coalescing firing this alongside another
# instance of itself (or prematch/results-poll) against the same DB/CSVs.
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/_lock.sh"
acquire_lock "run_daily" || exit 0

echo "" >> "$LOG"
echo "══════════════════════════════════════════" >> "$LOG"
echo " $(date '+%Y-%m-%d %H:%M:%S')  Daily run" >> "$LOG"
echo "══════════════════════════════════════════" >> "$LOG"

# Where THIS run starts in the log — the phantom-team alert at the end scans
# only from here, so yesterday's (already handled) warnings can't re-fire it.
# tr strips macOS wc's leading padding, which breaks `tail -n +N`.
RUN_START_LINE=$(wc -l < "$LOG" | tr -d ' ')

cd "$PROJ_DIR"

# Set to 1 whenever a step below fails, so the heartbeat doesn't report
# healthy after a run where the real pipeline silently no-op'd.
#
# _fail also records WHICH step broke. Half the runs in July 2026 ended
# "one or more steps failed" with no way to tell which one without re-reading
# 3,000 log lines by hand, so each call site passes $LINENO and the run summary
# prints the step headers those lines belong to.
overall_failed=0
failed_lines=""
_fail() {
    overall_failed=1
    failed_lines="${failed_lines}${failed_lines:+ }$1"
}

# Load env vars from .env so API keys are available on the host too
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a

# ── Wait for Docker to be ready ──────────────────────────────────────────────
# MUST come before anything that shells into a container. launchd fires this on
# wake, when Docker Desktop is often still starting: on 2026-07-31 the
# pre-flight below ran first, got "failed to connect to the docker API", and
# set API_FOOTBALL_OK=0 — disabling every API-Football step for the whole run
# — while the very next line waited for the daemon and found it ready.
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/wait_docker.sh"
echo "" >> "$LOG"
wait_for_docker "$LOG" || exit 1

# ── API-Football pre-flight ──────────────────────────────────────────────────
# The account is IP-whitelisted and this connection has a dynamic IP. When it
# rotates, every API-Football call returns {"errors":{"Ip":...}} with HTTP 200 —
# callers just warn and continue, so the run "succeeds" having fetched nothing.
# That went unnoticed for 5 days in July 2026, and retrying ~7,400 doomed calls
# stretched this script from ~15 min to 4+ hours.
#
# Check once, up front: exit 2 means the IP is blocked, so skip every
# API-Football step (they cannot succeed) but still run the rest — results from
# The Odds API, predictions, projections and cache warming all work without it.
API_FOOTBALL_OK=1
echo "" >> "$LOG"
echo "[0/9] API-Football pre-flight …" | tee -a "$LOG"
docker compose exec -T backend python scripts/preflight_api_football.py 2>&1 | tee -a "$LOG"
_preflight_rc=${PIPESTATUS[0]}
if [ "$_preflight_rc" -ne 0 ]; then
    API_FOOTBALL_OK=0
    _fail $LINENO
    echo "  [skip] API-Football steps disabled for this run (pre-flight rc=$_preflight_rc)." | tee -a "$LOG"
fi

# ── Live-tournament gate ─────────────────────────────────────────────────────
# World Cup 2026 ended 2026-07-19. The WC-specific steps below (API-Football
# result overlay, squads, availability, Monte Carlo sim) only make sense while a
# tournament is actually being played — left on they burn API quota and CPU
# re-simulating a finished bracket, and overwrite the frozen artifacts in
# backend/data/models/national/archive/wc2026/.
#
# The generic national steps (dataset refresh, retrain, Elo snapshot, squad
# strength, predictions) keep running — they serve every future tournament.
#
# Set WC_ACTIVE=1 in .env when the next national-team tournament starts.
WC_ACTIVE="${WC_ACTIVE:-0}"

# ── 0. Back up the database BEFORE any mutation ──────────────────────────────
# A daily snapshot of everything that can't be regenerated (users, bets, the
# value ledger, settled results) — taken first so today's --force/retrain can
# never leave us without a restore point.
echo "" >> "$LOG"
echo "[0] Backing up database …" | tee -a "$LOG"
bash "$PROJ_DIR/scripts/backup_db.sh" 2>&1 | tee -a "$LOG" || echo "  [warn] backup failed — continuing" | tee -a "$LOG"

# Restore the dump we just took into a scratch database and count the rows.
# backup_db.sh only checks the file is not suspiciously small, which a truncated
# or mid-migration dump passes. This is the difference between having backups
# and knowing you have backups.
bash "$PROJ_DIR/scripts/verify_backup.sh" 2>&1 | tee -a "$LOG" \
    || send_alert "Football Predictor: backup NOT restorable" \
         "The nightly dump could not be restored into a scratch database, or came back short. Everything that cannot be regenerated — accounts, tracked bets, the value-bet ledger — is currently unprotected." \
         urgent "rotating_light" "$LOG"

# ── 1. Update domestic + CL results (football-data.org) ──────────────────────
echo "[1/6] Updating domestic + CL match results …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/update_results.py --days-back 7 \
    2>&1 | tee -a "$LOG" || _fail $LINENO

# ── 2. Update GreekSL / EL / ECL results (The Odds API) ──────────────────────
echo "" >> "$LOG"
echo "[2/6] Updating GreekSL / EL / ECL match results …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/update_european_results.py \
        --key "${ODDS_API_KEY:-}" \
        --days-from 3 \
    2>&1 | tee -a "$LOG" || _fail $LINENO

# ── 3. Refresh upcoming fixtures (top-5 leagues via football-data.org) ────────
echo "" >> "$LOG"
echo "[3/6] Refreshing upcoming fixtures (top-5 leagues) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_upcoming.py \
        --key "${FOOTBALLDATA_API_KEY:-}" \
        --days 60 \
        --no-predictions \
    2>&1 | tee -a "$LOG" || _fail $LINENO

# ── 4. Refresh Greek SL fixtures (The Odds API — 1 req per run) ──────────────
echo "" >> "$LOG"
echo "[4/6] Refreshing Greek SL fixtures …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_greek_fixtures.py \
        --key "${ODDS_API_KEY:-}" \
        --no-predictions \
    2>&1 | tee -a "$LOG" || _fail $LINENO

# ── 4b. Greek SL fixtures from API-Football (league 197) ─────────────────────
# The Odds API's Greek key goes inactive out of season, leaving the Super League
# with no upcoming fixtures — and therefore no long-term projection — between
# seasons. API-Football publishes the new-season schedule weeks earlier, so this
# lights up the projection sooner. Greece is our primary market. Non-fatal.
echo "" >> "$LOG"
echo "[4b/6] Refreshing Greek SL fixtures (API-Football) …" | tee -a "$LOG"
if [ "$API_FOOTBALL_OK" -eq 1 ]; then
docker compose exec -T backend \
    python scripts/fetch_greek_apifootball.py --days-ahead 120 --days-back 5 \
    2>&1 | tee -a "$LOG" || echo "  [warn] Greek API-Football fetch failed — continuing" | tee -a "$LOG"
else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

# ── 4c. The twelve expansion leagues (API-Football) ──────────────────────────
# Belgium, Turkey, Scotland, Denmark, Sweden, Norway, Poland, Austria,
# Switzerland, Romania, Ireland, Finland. Their HISTORY comes from
# football-data.co.uk, but that publishes played matches only — the schedule has
# to come from here, and football-data.org's free tier doesn't carry them.
# Added 2026-07-30 so UEFA qualifying ties stop reading "Insufficient data".
echo "" >> "$LOG"
echo "[4c/6] Refreshing expansion-league fixtures (API-Football) …" | tee -a "$LOG"
if [ "$API_FOOTBALL_OK" -eq 1 ]; then
docker compose exec -T backend \
    python scripts/fetch_domestic_apifootball.py --days-ahead 120 --days-back 5 \
    2>&1 | tee -a "$LOG" || echo "  [warn] expansion-league fetch failed — continuing" | tee -a "$LOG"
else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

# ── 4c2. History-only leagues (API-Football) ─────────────────────────────────
# Second tiers of leagues we price, plus ~30 foreign top flights. Their clubs
# reach us as promoted sides and European qualifiers; without a record they
# render "no history — no prediction". Only the CURRENT season is re-fetched
# (past ones are immutable and skipped), so this is ~42 requests a day.
echo "" >> "$LOG"
echo "[4c2/6] Refreshing history-only league seasons …" | tee -a "$LOG"
if [ "$API_FOOTBALL_OK" -eq 1 ]; then
docker compose exec -T backend \
    python scripts/import_history_apifootball.py \
    2>&1 | tee -a "$LOG" || echo "  [warn] history import failed — continuing" | tee -a "$LOG"
else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

# ── 5. Refresh European fixtures (CL/EL/ECL, incl. qualifiers — API-Football) ─
# Ingest-only: upcoming ties are inserted and finished ones get their score.
# Predictions come from step 6 (compute_predictions.py), the single canonical
# path — it calibrates, runs the draw/BTTS specialists and stores the Poisson λ.
echo "" >> "$LOG"
echo "[5/6] Refreshing European fixtures (CL/EL/ECL) …" | tee -a "$LOG"
if [ "$API_FOOTBALL_OK" -eq 1 ]; then
docker compose exec -T backend \
    python scripts/fetch_european_fixtures.py \
        --days-ahead 21 --days-back 5 \
    2>&1 | tee -a "$LOG" || _fail $LINENO
else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

# ── 5b. Refresh club friendlies (API-Football league 667) ────────────────────
# Fetches upcoming club friendlies AND fills results for played ones — no other
# results-updater covers league "ClubFriendly". Predictions come from step 6
# (compute_predictions.py forces confidence "low" for ClubFriendly).
echo "" >> "$LOG"
echo "[5b/6] Refreshing club friendlies …" | tee -a "$LOG"
if [ "$API_FOOTBALL_OK" -eq 1 ]; then
docker compose exec -T backend \
    python scripts/fetch_club_friendlies.py \
        --days-ahead 14 \
        --days-back 7 \
        --no-predictions \
    2>&1 | tee -a "$LOG" || _fail $LINENO
else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

# ── 5c. Refresh ClubElo cold-start snapshot ──────────────────────────────────
# Daily ClubElo rating pull → clubelo.json. compute_predictions seeds a real Elo
# (mapped onto our scale) for cold-start teams with no CSV history — promoted
# sides, lower-division cup/friendly opponents, European-qualifier minnows —
# instead of the flat 1500 default. Non-fatal: a failed/stale pull just disables
# seeding (falls back to 1500), so it must not flip the pipeline health signal.
echo "" >> "$LOG"
echo "[5c/6] Refreshing ClubElo cold-start ratings …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_clubelo.py \
    2>&1 | tee -a "$LOG" || echo "  [warn] ClubElo fetch failed — cold-start seeding disabled this run" | tee -a "$LOG"

# ── 5d. Reconcile fixtures duplicated by club-name drift ─────────────────────
# Two feeds spelling one club differently write two rows for the same match
# (two predictions, two cards, split Elo). Adding an alias fixes future
# ingests; this merges what was already written. Safe by construction — it
# refuses any group where more than one row carries a result.
#
# Placed AFTER every fixture-ingestion step and BEFORE predictions. It used
# to sit at 4d, so a duplicate written by the European or friendlies fetch
# below survived the whole day and got priced twice — "Jagiellonia v
# Rangers" and "Jagiellonia v Ranger's" each had their own card.
echo "" >> "$LOG"
echo "[5d/6] Reconciling duplicate fixtures …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/dedupe_fixtures.py --apply \
    2>&1 | tee -a "$LOG" || echo "  [warn] fixture dedupe failed — continuing" | tee -a "$LOG"

# ── 6. Compute any missing predictions ───────────────────────────────────────
echo "" >> "$LOG"
echo "[6/6] Computing missing predictions …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/compute_predictions.py \
    2>&1 | tee -a "$LOG" || _fail $LINENO

echo "" >> "$LOG"
echo "[7/9] Backfilling bm_odds from CSVs …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/backfill_bm_odds.py \
    2>&1 | tee -a "$LOG" || _fail $LINENO

# ── 8. Pre-warm injury cache for new fixtures (next 3 days, skips existing) ───
echo "" >> "$LOG"
echo "[8/9] Pre-warming injury cache for new fixtures …" | tee -a "$LOG"
if [ "$API_FOOTBALL_OK" -eq 1 ]; then
docker compose exec -T backend \
    python scripts/warmup_injuries.py --days 3 \
    2>&1 | tee -a "$LOG" || _fail $LINENO
else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

# ── Club player/team props (parity with the national match pages) ────────────
# Ingest club team stats (corners / cards) then per-player match stats for both
# sides of every UPCOMING club fixture. Elo + all club props (corners / cards /
# per-player scorer·SoT·assist) are computed LIVE at request time from these
# tables, so no compute step follows. Budget-capped (Pro = 7500/day); fixtures
# already in the tables are skipped, so the daily cost is only the new games.
# Non-fatal: a club-stats API hiccup shouldn't flip the pipeline health signal.
echo "" >> "$LOG"
echo "[8b/9] Ingesting club team + player stats (props source) …" | tee -a "$LOG"
if [ "$API_FOOTBALL_OK" -eq 1 ]; then
# Current squads FIRST — cheap (~1 request per team with an upcoming fixture)
# and correctness-critical. player_match_stats is a match log, not a roster, so
# without this a transferred player keeps showing in his old club's props, and
# during a transfer window no new match data can ever correct it.
# Deliberately ahead of the two heavy ingests below (1200 + 2000 requests): a
# stale roster produces WRONG output, while a day of missing match stats only
# delays data.
# Weekly refresh: the script self-skips while the file is fresh, so this line
# runs daily but only spends quota once a week. --max-age-days 6, not 7, so a
# run firing slightly early can't skip itself into a 2-week gap.
# Cap sits above the team count so a run is never silently truncated; the script
# fetches soonest-fixture-first and says so when it does truncate.
docker compose exec -T backend \
    python scripts/fetch_club_squads.py --days-ahead 7 --max-age-days 6 --max-requests 700 \
    2>&1 | tee -a "$LOG" || echo "  [warn] club squads incomplete — some rosters may be stale" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_club_team_stats.py --days-ahead 7 --last 8 --max-requests 1200 \
    2>&1 | tee -a "$LOG" || echo "  [warn] club team stats failed — continuing" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_club_player_stats.py --days-ahead 7 --last 8 --max-requests 2000 \
    2>&1 | tee -a "$LOG" || echo "  [warn] club player stats failed — continuing" | tee -a "$LOG"
else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

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
    2>&1 | tee -a "$LOG" || _fail $LINENO

# Sync DB-known results into results.csv first — martj42 lags ~1 day, so this
# ensures the retrain/snapshot below see yesterday's matches (true self-correct).
echo "" >> "$LOG"
echo "[national 1b/7] Syncing settled results into dataset …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/sync_results_to_dataset.py \
    2>&1 | tee -a "$LOG" || _fail $LINENO

# API-Football is the source of truth for the LIVE tournament — fresher and more
# accurate than martj42 (which lags ~1 day and rarely records penalty winners
# quickly). Overlay its final scores + shoot-out winners onto results.csv /
# shootouts.csv. MUST run after the martj42 --force above (which would otherwise
# clobber it) and before the retrain/snapshot/sim so everything sees the truth.
if [ "$WC_ACTIVE" = "1" ]; then
    echo "" >> "$LOG"
    echo "[national 1c/7] Overlaying live WC results from API-Football …" | tee -a "$LOG"
    if [ "$API_FOOTBALL_OK" -eq 1 ]; then
    docker compose exec -T backend \
        python scripts/fetch_wc_results.py \
        2>&1 | tee -a "$LOG" || _fail $LINENO
    else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi
fi

# Daily full retrain — during a live tournament the model self-corrects every
# day on the freshly-downloaded results. (User-requested over snapshot-only.)
# Rebuilds models + the Elo/form snapshot together.
echo "" >> "$LOG"
echo "[national 2/7] Daily national retrain …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/train_national.py \
    2>&1 | tee -a "$LOG" || _fail $LINENO

# Re-fit the serve-path Elo blend against the fresh models (blend.json). Keeps
# ELO_BLEND_W + elo_three_way constants evidence-based instead of hand-picked;
# predict (step 5) reads the file.
echo "" >> "$LOG"
echo "[national 2b/7] Fitting Elo-blend on held-out replay …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fit_national_blend.py \
    2>&1 | tee -a "$LOG" || _fail $LINENO

echo "" >> "$LOG"
echo "[national 3/7] Re-injecting manual upcoming friendlies …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/add_upcoming_national.py \
    2>&1 | tee -a "$LOG" || _fail $LINENO

# Safety net: if the retrain step failed (pipeline continues on error), refresh
# the Elo/form snapshot alone so predictions still reflect the latest results.
echo "" >> "$LOG"
echo "[national 4/7] Refreshing Elo snapshot (safety) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/refresh_national_snapshot.py \
    2>&1 | tee -a "$LOG" || _fail $LINENO

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
if [ "$API_FOOTBALL_OK" -eq 1 ]; then
docker compose exec -T backend \
    python scripts/fetch_squad_strength.py --season "$SQUAD_SEASON" --max-age-days 6 --max-requests 1700 \
    2>&1 | tee -a "$LOG" || _fail $LINENO
else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

echo "" >> "$LOG"
echo "[national 5/7] Generating international predictions …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/predict_national.py --save-db \
    2>&1 | tee -a "$LOG" || _fail $LINENO

echo "" >> "$LOG"
echo "[national 6/7] Fetching bookmaker odds + EV for internationals …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/fetch_national_odds.py \
    2>&1 | tee -a "$LOG" || _fail $LINENO

echo "" >> "$LOG"
echo "[national 7/7] Filling actual international results …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/update_national_results.py \
    2>&1 | tee -a "$LOG" || _fail $LINENO

# Ingest player stats for recently-played WC matches (anytime scorer / SoT /
# assists / cards props + settlement actuals). --last 5; finished fixtures
# already in player_match_stats are skipped. Budget must cover ALL ~48 WC teams
# (400 was too small during the tournament → Mexico/SK etc. went un-ingested,
# leaving "what we caught" blank). Pro plan = 7500/day, so 2500 is safe.
echo "" >> "$LOG"
echo "[national 7a/7] Ingesting player match stats (API-Football) …" | tee -a "$LOG"
if [ "$API_FOOTBALL_OK" -eq 1 ]; then
docker compose exec -T backend \
    python scripts/fetch_player_stats.py --wc-only --last 5 --max-requests 2500 \
    2>&1 | tee -a "$LOG" || _fail $LINENO
else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

# Ingest team match stats (corners / shots / possession) from /fixtures/statistics
# — corners aren't in /fixtures/players, so this is a separate cheap pull.
echo "" >> "$LOG"
echo "[national 7a1/7] Ingesting team match stats (API-Football) …" | tee -a "$LOG"
if [ "$API_FOOTBALL_OK" -eq 1 ]; then
docker compose exec -T backend \
    python scripts/fetch_match_statistics.py --wc-only --last 5 --max-requests 1500 \
    2>&1 | tee -a "$LOG" || _fail $LINENO
else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

# Ingest current-season CLUB form per player (/players) — the empirical-Bayes
# prior for the prop rates, so low-cap players regress toward real club form
# instead of a flat league prior. Idempotent: only rows older than 7 days are
# refreshed, so the cost amortises across days (1 request/player, budget-capped).
echo "" >> "$LOG"
echo "[national 7a2/7] Ingesting player club form (API-Football) …" | tee -a "$LOG"
if [ "$API_FOOTBALL_OK" -eq 1 ]; then
docker compose exec -T backend \
    python scripts/fetch_club_form.py --wc-only --max-requests 1500 \
    2>&1 | tee -a "$LOG" || _fail $LINENO
else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

# Recompute player props (anytime scorer / SoT / assist) for upcoming fixtures
# from the freshly-ingested stats + club-form priors + the refreshed Elo snapshot.
echo "" >> "$LOG"
echo "[national 7a3/7] Computing player props …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/compute_player_props.py \
    2>&1 | tee -a "$LOG" || _fail $LINENO

# 5b. Catch never-anticipated fixtures: any match played in the last 3 days
# that has NO prediction row (e.g. friendlies missing from our fixture list)
# gets an honest pre-match replay row (insert-only — live predictions are
# never overwritten). Prevents silent gaps in Recent Results / stats.
echo "" >> "$LOG"
echo "[national 7b/7] Backfilling missed recent fixtures …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/backfill_national_predictions.py \
        --from "$(date -v-3d +%Y-%m-%d)" --skip-existing \
    2>&1 | tee -a "$LOG" || _fail $LINENO

if [ "$WC_ACTIVE" = "1" ]; then
    # Official WC squads for the Golden Boot squad filter. Skips itself when the
    # file is < 7 days old, so it only spends API-Football quota once a week.
    echo "" >> "$LOG"
    echo "[national 7c/7] Refreshing WC squads (weekly) …" | tee -a "$LOG"
    if [ "$API_FOOTBALL_OK" -eq 1 ]; then
    docker compose exec -T backend \
        python scripts/fetch_wc_squads.py --max-age-days 7 \
        2>&1 | tee -a "$LOG" || _fail $LINENO
    else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

    # Sync same-day goals from player_match_stats into goalscorers.csv so the
    # Golden Boot below reflects today's scorers immediately (martj42 lags ~1 day).
    echo "" >> "$LOG"
    echo "[national 7c2/7] Syncing same-day goalscorers …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/sync_goalscorers_to_dataset.py \
        2>&1 | tee -a "$LOG" || _fail $LINENO

    # Player availability (injuries + suspensions) from API-Football /injuries —
    # one cheap request; lets the simulation drop unavailable golden-boot scorers.
    echo "" >> "$LOG"
    echo "[national 7c2/7] Fetching player availability (injuries/suspensions) …" | tee -a "$LOG"
    if [ "$API_FOOTBALL_OK" -eq 1 ]; then
    docker compose exec -T backend \
        python scripts/fetch_availability.py \
        2>&1 | tee -a "$LOG" || _fail $LINENO
    else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

    # World Cup Monte Carlo simulation (champion/finalist/group/golden-boot).
    echo "" >> "$LOG"
    echo "[national 7d/7] Running World Cup Monte Carlo simulation …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/simulate_wc.py --sims 20000 --save-json \
        2>&1 | tee -a "$LOG" || _fail $LINENO
else
    echo "" >> "$LOG"
    echo "[national 7c-7d/7] Skipped — no live tournament (WC_ACTIVE=0)." | tee -a "$LOG"
fi

# ── Monthly rolling recalibration (1st of the month) ─────────────────────────
# Refits the second-stage isotonic correction from the last 365 days of stored
# predictions vs actual results (out-of-sample by construction). Skips itself
# below 300 completed predictions.
if [ "$(date +%d)" = "01" ]; then
    echo "" >> "$LOG"
    echo "[monthly] Rolling recalibration …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/recalibrate.py \
        2>&1 | tee -a "$LOG" || _fail $LINENO
fi

# Settle fixtures the pollers' 7-day window left behind. Costs no API credits —
# it reads the CSVs the model already trains on. Without it a missed result is
# missed for ever: two matches had sat unresolved for 80+ days, silently absent
# from every accuracy figure on /stats.
echo "" >> "$LOG"
echo "[8c/9] Settling stale fixtures from the CSVs …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/settle_stale_fixtures.py \
    2>&1 | tee -a "$LOG" || echo "  [warn] stale-fixture settle failed — continuing" | tee -a "$LOG"

# Cut today's accumulator slips and settle finished ones. Needs no external
# API — it reads predictions already in the DB — so it runs whether or not
# API-Football is reachable. Placed after predictions/odds so the slips are cut
# from today's numbers, and before the cache clear below so the page serves them
# immediately.
echo "" >> "$LOG"
echo "[9a/9] Cutting today's tickets …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/generate_tickets.py --replace \
    2>&1 | tee -a "$LOG" || echo "  [warn] ticket generation failed — the page falls back to the previous day" | tee -a "$LOG"

echo "" >> "$LOG"
echo "[9/9] Clearing stats cache …" | tee -a "$LOG"
curl -s -X POST "${_ADMIN_HDR[@]}" http://localhost:8000/stats/cache/clear >> "$LOG" 2>&1 || true

# Re-prime the analysis cache. Today's recomputed predictions produce new model
# probabilities, and those probabilities are part of the analysis cache key — so
# every entry warmed before this run is now unreachable. Without this the first
# visitor of the morning pays the cold Groq + odds fetch on every fixture.
# (The 50-minute warm-up job keeps it warm from here on.)
echo "" >> "$LOG"
echo "[9b/9] Warming analysis cache …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/warmup_analysis.py --days 2 \
    2>&1 | tee -a "$LOG" || echo "  [warn] warm-up failed — pages still work, just cold" | tee -a "$LOG"

# League tables + season Monte Carlo (title / Europe / relegation odds). Both
# only change when a result lands, which today's steps have just written — so
# recompute now rather than making the first visitor of the day wait ~2s per
# league for the simulation.
echo "" >> "$LOG"
echo "[9c/9] Warming league tables + season projections …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/warmup_standings.py \
    2>&1 | tee -a "$LOG" || echo "  [warn] standings warm-up failed — pages still work, just cold" | tee -a "$LOG"

# One dated snapshot per competition of the title/champion odds (model + market
# where offered) → the odds-over-time chart on /projections. Re-writes the
# projection cache enriched with the bookmaker column, so it runs AFTER the
# warm-up above.
echo "" >> "$LOG"
echo "[9d/9] Snapshotting projection odds (model vs market) …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/snapshot_projections.py \
    2>&1 | tee -a "$LOG" || echo "  [warn] projection snapshot failed — chart just won't gain a point today" | tee -a "$LOG"

# ── Phantom-team alert ────────────────────────────────────────────────────────
# The name guards print "[warn] N unresolved team(s)" when a DOMESTIC fixture
# names a club missing from the training data — which is how "Bayer Leverkusen"
# and the whole promoted Championship cohort became phantom teams (Elo 1500,
# junk predictions, split league tables). Buried in the log those warnings went
# unseen for days; this surfaces them as a macOS notification the same morning.
# Only THIS run's lines are scanned (tail from RUN_START_LINE). [info] lines
# (cup minnows with no history — expected) don't fire it.
PHANTOM_WARNS=$(tail -n "+$((RUN_START_LINE + 1))" "$LOG" \
    | grep -cE '\[warn\].*(unresolved team|not in the training data)' || true)
if [ "${PHANTOM_WARNS:-0}" -gt 0 ]; then
    echo "[alert] $PHANTOM_WARNS unresolved-team warning(s) this run — check TEAM_MAP" | tee -a "$LOG"
    osascript -e "display notification \"${PHANTOM_WARNS} unresolved team warning(s) — δες daily.log και πρόσθεσε TEAM_MAP entries\" with title \"⚠️ Football Predictor\" sound name \"Basso\"" \
        2>/dev/null || true
fi

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
        2>&1 | tee -a "$LOG" || _fail $LINENO

    # 7. Refresh current-season CSVs so training data is up-to-date
    echo "[7/10] Refreshing current-season CSVs …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/download_data.py --refresh-current \
        2>&1 | tee -a "$LOG" || _fail $LINENO

    # 8a. Refresh understat xG for top-5 leagues (current season)
    echo "" >> "$LOG"
    echo "[8a/10] Refreshing understat xG (top-5 leagues, current season) …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/download_xg.py --season 2025 \
        2>&1 | tee -a "$LOG" || _fail $LINENO

    # 8b. Refresh API-Football xG for remaining leagues (api-sports.io)
    #    --force overwrites so newly-added xG for recent matches is picked up.
    #    Current season = year the season started (e.g. 2025 for 2025-26).
    CURRENT_SEASON=$(date +%Y)
    # European seasons start in July; before July we're still in the previous season
    MONTH=$(date +%m)
    [ "$MONTH" -lt 7 ] && CURRENT_SEASON=$((CURRENT_SEASON - 1))
    echo "" >> "$LOG"
    echo "[8b/10] Refreshing CL/EL/ECL/Eredivisie/PrimeiraLiga/Championship xG for season ${CURRENT_SEASON} …" | tee -a "$LOG"
    if [ "$API_FOOTBALL_OK" -eq 1 ]; then
    docker compose exec -T backend \
        python scripts/download_xg_apifootball.py \
            --leagues CL EL ECL Eredivisie PrimeiraLiga Championship \
            --seasons "${CURRENT_SEASON}" \
            --force \
        2>&1 | tee -a "$LOG" || _fail $LINENO
    else echo "  [skip] API-Football blocked." | tee -a "$LOG"; fi

    # 9. Retrain both models (takes ~2-3 min)
    echo "" >> "$LOG"
    echo "[9/10] Retraining ML models …" | tee -a "$LOG"
    docker compose exec -T backend \
        python -m backend.app.ml.train \
        2>&1 | tee -a "$LOG" || _fail $LINENO

    # 9b. Refit the second-stage rolling calibration against the new models
    echo "" >> "$LOG"
    echo "[9b/10] Refitting rolling recalibration after retrain …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/recalibrate.py \
        2>&1 | tee -a "$LOG" || _fail $LINENO

    # 10. Force-recompute all upcoming predictions with the new models
    echo "" >> "$LOG"
    echo "[10/10] Recomputing all predictions with new models …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/compute_predictions.py --force \
        2>&1 | tee -a "$LOG" || _fail $LINENO

    echo "" >> "$LOG"
    echo "[11/12] Backfilling bm_odds from freshly-downloaded CSVs …" | tee -a "$LOG"
    docker compose exec -T backend \
        python scripts/backfill_bm_odds.py \
        2>&1 | tee -a "$LOG" || _fail $LINENO

    echo "" >> "$LOG"
    echo "[12/12] Clearing stats cache after retrain …" | tee -a "$LOG"
    curl -s -X POST "${_ADMIN_HDR[@]}" http://localhost:8000/stats/cache/clear >> "$LOG" 2>&1 || true

    # NOTE: national-team retrain is no longer here — it runs DAILY in the
    # national block above (self-corrects after every match during tournaments).

    echo "" >> "$LOG"
    echo "Weekly retrain complete at $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
fi

# ── Data-completeness healthcheck ────────────────────────────────────────────
# Audits every ingestion seam (team ids, stats coverage, name maps, club form,
# odds match rate) for fixtures in the next 7 days. It exits 1 whenever ANY
# alert is raised — silent "—" panels on match pages have shipped more than once.
#
# Its result is tracked SEPARATELY from overall_failed, because the two answer
# different questions:
#
#   overall_failed  → did the pipeline actually run?      (dead-man's switch)
#   health_alerts   → is the data complete?               (quality signal)
#
# They used to be one flag, and that silently disarmed the dead-man's switch:
# the heartbeat fires only on a fully clean run, so with 12 leagues added in
# July 2026 there was almost always some alert and the ping NEVER went out —
# 0 in the entire log. healthchecks.io would have shown "down" forever while
# the pipeline completed happily in 20 minutes, and would never have told us
# about the one case that matters: the run not happening at all.
echo "" >> "$LOG"
echo "[health] Data-completeness check …" | tee -a "$LOG"
health_alerts=0
# Skipped when API-Football is blocked: the check reads the same API, so every
# gap it reports would be an artefact of the block, not a real data problem.
# Alerting on those buries the one alert that matters (the pre-flight's) under
# dozens of derived ones — which is exactly what happened on 2026-08-09
# ("DATA GAPS — 11 alerts, 35 warnings" on a run whose only fault was the IP).
if [ "$API_FOOTBALL_OK" -eq 1 ]; then
docker compose exec -T backend \
    python scripts/check_data_completeness.py --days 7 \
    2>&1 | tee -a "$LOG" || health_alerts=1
else echo "  [skip] API-Football blocked — gap report would be noise." | tee -a "$LOG"; fi

# Club identity. Ingestion is what introduces new spellings, so this belongs
# next to the completeness check rather than in CI alone: a promoted club
# arriving under the second tier's name splits its Elo the same day, and a name
# already used in another country fuses two clubs' ratings silently. Both are
# invisible in the output — the site keeps serving confident predictions built
# on half a history. Advisory, like the check above: it never fails the run.
echo "" >> "$LOG"
echo "[health] Club-identity audit …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/audit_team_identity.py \
    2>&1 | tee -a "$LOG" || health_alerts=1

# Odds seam. The completeness check reports it as a bare percentage ("only 49%
# of tracked-league predictions matched odds"), which says something is wrong
# but never which club — 27 were unmatched on 2026-08-04 and each one was a
# fixture served with no odds, no EV and no value gate. This names them by
# asking The Odds API's /events endpoint what it calls each side. That endpoint
# returns no prices and costs no quota, so it is safe to run every day.
echo "" >> "$LOG"
echo "[health] Odds-seam check …" | tee -a "$LOG"
docker compose exec -T backend \
    python scripts/check_odds_seam.py \
    2>&1 | tee -a "$LOG" || health_alerts=1

# What the site is actually serving. These six assertions need a populated
# database, so on a CI runner every one of them skips — the job goes green
# without having checked any of them, and "no fixture is stored twice" was
# among them on the very day one match reached the accumulator page twice.
# Here they run against the real data, which is the only place they mean
# anything. Advisory like the rest: it reports, it never fails the run.
echo "" >> "$LOG"
echo "[health] Serving-data assertions …" | tee -a "$LOG"
docker compose exec -T backend \
    python -m pytest backend/tests/test_live_data.py -q -rs \
    2>&1 | tee -a "$LOG" || health_alerts=1

# ── Run summary ──────────────────────────────────────────────────────────────
# Turn the recorded $LINENO list back into the step headers a human recognises,
# so "one or more steps failed" names them instead of sending anyone log-diving.
_name_steps() {
    local ln
    for ln in $1; do
        # Nearest preceding `echo "[…] …"` line in this script = the step header.
        awk -v target="$ln" '
            NR <= target && /^[[:space:]]*echo "\[/ {
                line = $0
                sub(/^[[:space:]]*echo "/, "", line)
                sub(/ ?…?"( \| tee.*)?$/, "", line)
                found = line
            }
            END { if (found != "") print "  • " found; else print "  • line " target }
        ' "${BASH_SOURCE[0]}"
    done
}

echo "" >> "$LOG"
if [ "$overall_failed" -ne 0 ]; then
    echo "[warn] one or more steps failed — skipping heartbeat so the monitor alerts" >> "$LOG"
    echo "[warn] failed step(s):" >> "$LOG"
    _name_steps "$failed_lines" >> "$LOG"
else
    echo "[ok] all steps completed" >> "$LOG"
fi
# Reported on its own line so a reader (and `grep`) can tell "the run broke"
# apart from "the run was fine, the data has gaps".
if [ "${health_alerts:-0}" -ne 0 ]; then
    echo "[warn] data completeness: alerts raised (does NOT block the heartbeat)" >> "$LOG"
else
    echo "[ok] data completeness: no alerts" >> "$LOG"
fi

# ── Alerting ─────────────────────────────────────────────────────────────────
# THREE independent signals, because they answer different questions:
#
#  1. Run failed  → push alert naming the broken steps (GATE_ALERT_URL, the
#     same sink the gate and pre-flight already use).
#  2. Run succeeded → dead-man's-switch ping. This is the ONLY thing that
#     catches the failures this script can never report itself: launchd not
#     firing, the Mac asleep at 06:00, the job dying before it reaches here.
#     Set HEARTBEAT_URL in .env (healthchecks.io or similar); no-op when unset,
#     in which case run_watchdog.sh's staleness check is the only such cover.
#  3. Data incomplete → its own push, and deliberately NOT tied to (2). A
#     missing club id is worth knowing about; it is not a reason to tell the
#     monitor the pipeline is dead.
# shellcheck disable=SC1091
source "$PROJ_DIR/scripts/_alert.sh"

_health_verdict=$(tail -n "+$((RUN_START_LINE + 1))" "$LOG" \
    | grep -E '^DATA (OK|GAPS) — ' | tail -1)

if [ "$overall_failed" -ne 0 ]; then
    send_alert "Football Predictor: daily run failed" \
        "$(printf 'Run %s\n%s\n\nFailed steps:\n%s' \
             "$(date '+%Y-%m-%d %H:%M')" \
             "${_health_verdict:-health check did not report}" \
             "$(_name_steps "$failed_lines")")" \
        high "rotating_light,soccer" "$LOG"
elif [ -n "${HEARTBEAT_URL:-}" ]; then
    # -o /dev/null: healthchecks.io answers with a bare "OK" that would otherwise
    # be appended mid-line into the log.
    curl -fsS -o /dev/null -m 10 --retry 3 "$HEARTBEAT_URL" 2>> "$LOG" \
        && echo "✓ heartbeat sent" >> "$LOG" \
        || echo "[warn] heartbeat ping failed" >> "$LOG"
fi

# Data-quality push. Fires whether or not the run itself failed — but only once
# a day's worth of noise is worth a notification, so it rides the same "default"
# priority rather than waking anyone up.
if [ "${health_alerts:-0}" -ne 0 ]; then
    echo "[warn] data-completeness alerts raised — see the health section above" >> "$LOG"
    send_alert "Football Predictor: data incomplete" \
        "$(printf '%s\n\nΤο pipeline έτρεξε κανονικά — αυτό αφορά κενά δεδομένων (team ids, stats, ονόματα).' \
             "${_health_verdict:-health check did not report}")" \
        default "mag,soccer" "$LOG"
fi

# ── Log rotation ─────────────────────────────────────────────────────────────
# Last, so nothing above is writing while a file is being truncated. Nothing had
# ever rotated these: daily.log had reached 9.7MB / 100k lines spanning weeks,
# which is how "check today's logs" turned into slicing by line number.
echo "" >> "$LOG"
echo "[maint] Refreshing planner statistics …" | tee -a "$LOG"
# Autovacuum was not keeping up: `matches` had never been analyzed and the
# planner believed it held 173 rows against a real 8,696, which is how a table
# scan gets chosen over an index. Cheap, and it cannot drift again if it runs
# every day.
docker compose exec -T db psql -U "${POSTGRES_USER:-user}" -d "${POSTGRES_DB:-football_db}" \
    -c "ANALYZE;" 2>&1 | tee -a "$LOG" || echo "  [warn] ANALYZE failed" | tee -a "$LOG"

echo "" >> "$LOG"
echo "[rotate] Log rotation …" | tee -a "$LOG"
bash "$PROJ_DIR/scripts/rotate_logs.sh" 2>&1 | tee -a "$LOG" || true
