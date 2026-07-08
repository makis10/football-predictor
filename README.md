# Football Match Predictor

A full-stack machine-learning application that predicts football match outcomes (Win / Draw / Loss), goal totals (Over / Under 2.5), BTTS, correct scores and player props for **13 club competitions + international football** (World Cup 2026 with a live Monte-Carlo tournament simulation) — with bookmaker comparison, AI analysis, transparent accuracy/ROI tracking, and an AI chatbot assistant.

Built with **XGBoost + Pi-Ratings + Poisson expected-goals** (clubs) and a **talent-adjusted Elo** engine (national teams), **FastAPI**, **Next.js 16 / React 19**, **PostgreSQL**, **Redis**, and **Groq (GPT-OSS-120B)** — fully containerised with Docker Compose. Club feature set: **133 features, fully market-independent** (no bookmaker inputs — the market is only used as a benchmark).

**Live URL:** [https://aitipster.net](https://aitipster.net)

### Engineering highlights

- **Market-independent modelling** — bookmaker odds were removed from the feature set entirely (2026-06); value is measured *against* the de-vigged market, never borrowed from it.
- **Data-driven value gate** — suggested markets must earn promotion from a shadow-tracked, settled ticket ledger (n ≥ 30, ROI ≥ 0) instead of a hardcoded allowlist; base markets are held to the same record and **auto-demote** when they bleed (early at n ≥ 15 with ROI ≤ −20%, or by the standard floor at full sample).
- **Honest evaluation** — CLV vs closing line, fair-value (de-vig) ROI, calibration plots, and a methodology-cutoff banner when metrics blend model generations.
- **Ops** — daily `pg_dump` backups with rotation, dead-man's-switch heartbeats on every cron pipeline, per-IP rate limiting on LLM endpoints, self-hosted umami analytics, GitHub Actions CI (pytest + tsc + vitest + build).
- **Resilient data plumbing** — volunteer dataset (martj42) for 150 years of history with an authoritative API-Football overlay for live-tournament scores & penalty shoot-outs.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Prerequisites](#prerequisites)
3. [Quick Start — Docker](#quick-start--docker)
4. [Environment Variables](#environment-variables)
5. [Downloading Data](#downloading-data)
6. [Training the Model](#training-the-model)
7. [National Teams (International)](#national-teams-international)
8. [Seeding the Database](#seeding-the-database)
9. [Live Fixtures & Daily Automation](#live-fixtures--daily-automation)
10. [Public Tunnel (Cloudflare)](#public-tunnel-cloudflare)
11. [API Reference](#api-reference)
12. [Model Deep-Dive](#model-deep-dive)
13. [Adjusting & Improving the Model](#adjusting--improving-the-model)
14. [Project Structure](#project-structure)
15. [Troubleshooting](#troubleshooting)

---

## Architecture

```
Internet
    │
    ▼
Cloudflare tunnel (aitipster.net)
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│                      Docker Compose                         │
│                                                             │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────────┐  │
│  │ Next.js  │───▶│   FastAPI    │───▶│    PostgreSQL     │  │
│  │  :3000   │    │   :8000      │    │     :5432         │  │
│  └──────────┘    └──────┬───────┘    └───────────────────┘  │
│                         │            ┌───────────────────┐  │
│                         └───────────▶│      Redis        │  │
│                                      │      :6379        │  │
│                                      └───────────────────┘  │
│       │                 │                                   │
│  /api/proxy/*    ┌──────▼──────────────────────┐            │
│  (browser proxy) │  ML Layer                   │            │
│                  │  XGBoost + Pi-Ratings       │            │
│                  │  + Poisson EG model         │            │
│                  │  model_result.pkl           │            │
│                  │  model_goals.pkl            │            │
│                  └──────┬──────────────────────┘            │
│                         │                                   │
│                  ┌──────▼──────────────────────┐            │
│                  │  External APIs              │            │
│                  │  • The Odds API (bookmakers)│            │
│                  │  • Groq API (GPT-OSS-120B) │            │
│                  │  • football-data.org        │            │
│                  │  • API-Football (injuries)  │            │
│                  └─────────────────────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

- **Frontend** — Next.js 16 App Router, dark-themed Tailwind UI. Server components fetch data via internal `BACKEND_URL`; a `/api/proxy/*` catch-all route proxies browser-side calls so visitors only need one public URL. All times are rendered in **Europe/Athens** timezone (stored UTC in DB, converted at display time) so SSR and browser output match identically regardless of visitor location.
- **Backend** — FastAPI REST API. Predictions are computed on-demand by the ML layer and cached in PostgreSQL. The `/predictions/{id}/analysis` endpoint fetches live bookmaker odds, injury data, and generates a Groq AI analysis in Greek. The `/predictions/{id}/postmortem` endpoint generates an AI post-mortem using real match events (goals/cards/penalties with minute+player) fetched from API-Football. The `/chat` endpoint powers a context-aware AI chatbot with full conversation history.
- **ML** — Four XGBoost models (result, goals, draw specialist, BTTS classifier) trained on **133 features**, with Pi-Ratings and a Poisson expected-goals model as key feature sources. Draw probabilities are blended with a dedicated draw-specialist classifier (auto-tuned α=0.45 via Brier score sweep). BTTS predictions come from a dedicated XGBClassifier with isotonic calibration and an auto-tuned decision threshold (macro F1 sweep on calibration set; currently 0.52), replacing the previous Poisson-only estimate. Position-aware injury/suspension adjustments applied at inference time using API-Football data. Model files (`.pkl`) are mounted into the backend container.
- **Database** — PostgreSQL 16. Schema managed by Alembic migrations (0001–0014). Kick-off times stored as UTC `TIME` columns; bookmaker odds stored at prediction time for ROI/EV tracking; `odds_history` table stores snapshots every 3h for odds movement arrows (↑/↓).
- **Redis** — Caching layer (128MB, LRU eviction). Replaces all in-process Python dicts. Keys: `injuries:{match_id}` 30min, `squad_positions:{team_id}` 24h, `analysis:{fingerprint}` 30min, `postmortem:{match_id}` 24h, `stats:global` 6h, `league_odds:{league}` 30min, `match_events:{fixture_id}` 24h, `chat:context` 30min. Graceful fallback to no-op if Redis unavailable.
- **Tunnel** — Cloudflare Tunnel serving the custom domain aitipster.net, managed by macOS launchd (auto-restarts on crash/reboot).

---

## Prerequisites

| Tool           | Version | Notes                                    |
| -------------- | ------- | ---------------------------------------- |
| Docker Desktop | ≥ 4.x   | Includes Compose V2                      |
| Python         | 3.11+   | Only needed for training / local dev     |
| Node.js        | 20 LTS  | Only needed for local frontend dev       |
| cloudflared    | latest  | `brew install cloudflared` — for the public tunnel (aitipster.net) |

---

## Quick Start — Docker

### 1. Clone and configure

```bash
git clone <repo-url>
cd football-predictor
cp .env.example .env   # then fill in your API keys (see Environment Variables)
```

### 2. Ensure trained models exist

```
backend/data/models/model_result.pkl        # Win / Draw / Loss classifier
backend/data/models/model_goals.pkl         # Over / Under 2.5 classifier
backend/data/models/model_draw_clf.pkl      # Draw specialist binary classifier
backend/data/models/model_btts_clf.pkl      # BTTS (GG/NG) dedicated classifier
backend/data/models/calibrator_result.pkl   # Isotonic calibrator for result model
backend/data/models/calibrator_goals.pkl    # Isotonic calibrator for goals model
backend/data/models/calibrator_draw_clf.pkl # Isotonic calibrator for draw specialist
backend/data/models/calibrator_btts_clf.pkl # Isotonic calibrator for BTTS classifier
backend/data/models/draw_alpha.json         # Auto-tuned draw-blend weight (α=0.45)
backend/data/models/btts_threshold.json     # Auto-tuned BTTS decision threshold (macro F1 sweep; currently 0.52)
```

If missing, see [Training the Model](#training-the-model).

### 3. Build and start

```bash
docker compose up -d --build --remove-orphans
```

| Container  | URL                                            | Description  |
| ---------- | ---------------------------------------------- | ------------ |
| `frontend` | [http://localhost:3000](http://localhost:3000) | Next.js UI   |
| `backend`  | [http://localhost:8000](http://localhost:8000) | FastAPI + ML |
| `db`       | localhost:5432                                 | PostgreSQL   |
| `redis`    | localhost:6379                                 | Redis cache  |
| `adminer`  | [http://localhost:8080](http://localhost:8080) | DB browser   |

### 4. Seed the database

```bash
# Historical match data from CSVs
docker compose exec backend python scripts/seed_db.py --no-predictions

# Live upcoming fixtures — top-5 leagues + Championship + PrimeiraLiga + Eredivisie + CL
docker compose exec backend python scripts/fetch_upcoming.py --days 60 --no-predictions

# Greek Super League fixtures (The Odds API)
docker compose exec backend python scripts/fetch_greek_fixtures.py --no-predictions

# UEFA CL / EL / ECL fixtures
docker compose exec backend python scripts/fetch_european_fixtures.py --no-predictions

# Club friendlies — fixtures + results (API-Football league 667)
docker compose exec backend python scripts/fetch_club_friendlies.py --no-predictions

# ML predictions + bookmaker odds for all upcoming fixtures
docker compose exec backend python scripts/compute_predictions.py

# Pre-warm injury cache (so list page shows adjusted predictions immediately)
docker compose exec backend python scripts/warmup_injuries.py --days 3
```

### 5. Open the app

Visit [http://localhost:3000](http://localhost:3000) — or the public URL if the tunnel is running.

---

## Environment Variables

All variables live in `.env` at the repo root (gitignored). The backend container loads this file directly via `env_file`.

```env
# ── Database ──────────────────────────────────────────────
DATABASE_URL=postgresql://user:password@db:5432/football_db
POSTGRES_USER=user
POSTGRES_PASSWORD=password
POSTGRES_DB=football_db

# ── ML / API ──────────────────────────────────────────────
MODEL_VERSION=1.0.0

# football-data.org — free tier, fixtures + results for top-5 + CL + Championship + PPL + DED
# https://www.football-data.org/client/register
FOOTBALLDATA_API_KEY=your_key_here

# The Odds API — live bookmaker odds (20,000 req/month paid plan)
# https://the-odds-api.com
ODDS_API_KEY=your_key_here

# Groq — AI chat + match analysis (GPT-OSS-120B, free tier: 14,400 req/day)
# https://console.groq.com
GROQ_API_KEY=your_key_here

# API-Football (api-sports.io) — injuries & suspensions per match
# https://www.api-football.com/  (free tier: 100 req/day)
API_SPORTS_KEY=your_key_here

# ── Frontend ──────────────────────────────────────────────
NEXT_PUBLIC_API_URL=http://localhost:8000

# ── Public URL (Cloudflare tunnel serves aitipster.net → localhost:3000) ──
NEXTAUTH_URL=https://aitipster.net
NEXT_PUBLIC_SITE_URL=https://aitipster.net
ALLOWED_DEV_ORIGINS=aitipster.net,www.aitipster.net
```

### Frontend URL resolution

| Context              | Variable used          | Value                                   |
| -------------------- | ---------------------- | --------------------------------------- |
| Next.js SSR (server) | `BACKEND_URL`          | `http://backend:8000` (internal Docker) |
| Browser (client)     | hardcoded `/api/proxy` | Next.js proxy route → backend           |

Visitors only ever connect to the frontend URL — no direct backend exposure needed.

> **Important:** After changing `.env`, always recreate containers (not just restart) so Docker picks up the new values:
> ```bash
> docker compose up -d --force-recreate backend
> ```

---

## Downloading Data

### Historical match data (football-data.co.uk)

CSVs are saved to `backend/data/raw/`.

```bash
python scripts/download_data.py
```

Downloads seasons **2010/11 → 2025/26** for all supported leagues. Already-downloaded files are skipped.

### xG data (understat.com)

Expected goals (xG) per match for the top-5 European leagues, 2014/15 onwards. Saves one CSV per league-season to `backend/data/xg/`.

```bash
# Download all seasons (run once, takes ~5 minutes)
docker compose exec backend python scripts/download_xg.py

# Refresh current season only
docker compose exec backend python scripts/download_xg.py --season 2025
```

Leagues covered: EPL, La Liga, Serie A, Bundesliga, Ligue 1 (no xG data for GreekSL, Championship, PrimeiraLiga, Eredivisie, or UEFA competitions — those features are imputed with the training median).

### Supported leagues

| Code           | League                      | Fixture source                    | CSV code |
| -------------- | --------------------------- | --------------------------------- | -------- |
| `EPL`          | English Premier League      | football-data.org (`PL`)          | `E0`     |
| `Championship` | English Championship        | football-data.org (`ELC`)         | `E1`     |
| `LaLiga`       | Spanish La Liga             | football-data.org (`PD`)          | `SP1`    |
| `SerieA`       | Italian Serie A             | football-data.org (`SA`)          | `I1`     |
| `Bundesliga`   | German Bundesliga           | football-data.org (`BL1`)         | `D1`     |
| `Ligue1`       | French Ligue 1              | football-data.org (`FL1`)         | `F1`     |
| `PrimeiraLiga` | Portuguese Primeira Liga    | football-data.org (`PPL`)         | `P1`     |
| `Eredivisie`   | Dutch Eredivisie            | football-data.org (`DED`)         | `N1`     |
| `GreekSL`      | Greek Super League          | The Odds API                      | —        |
| `CL`           | UEFA Champions League       | football-data.org (`CL`)          | —        |
| `EL`           | UEFA Europa League          | The Odds API                      | —        |
| `ECL`          | UEFA Conference League      | The Odds API                      | —        |

> **Note on European predictions:** The ML models were trained on domestic league data. Predictions for CL/EL/ECL use each team's domestic Elo and Pi-Rating stats, which are meaningful for teams in our six leagues. Teams from other leagues (Porto, Sporting CP, etc.) receive neutral default features — treat those predictions with more caution.

> **Note on Championship / PrimeiraLiga / Eredivisie:** Added to fetch_upcoming.py and download_data.py. Historical CSVs available from football-data.co.uk. Training and model accuracy stats reflect only the original six domestic leagues.

---

## Training the Model

Training runs inside the backend container (all dependencies are there):

```bash
docker compose exec backend python -m backend.app.ml.train
```

Or from the host with Python 3.11+:

```bash
pip install -r backend/requirements.txt
python -m backend.app.ml.train
```

### What it does

1. Loads all CSVs from `backend/data/raw/`
2. Loads xG data from `backend/data/xg/` and merges onto training data by date + team name
3. Engineers **133 features** per match (rolling stats, EWMA momentum, shots, xG, Elo, **Pi-Ratings**, **Poisson EG model**, H2H, European congestion, referee stats, league position, draw-balance features). **No market/odds features** — removed 2026-06 so the model is fully market-independent; bookmaker odds are only used downstream as the value benchmark.
4. Excludes 2020/21 COVID season (no crowds → distorted home advantage)
5. Applies **exponential time decay** weights (3-year half-life) so recent seasons matter more
6. Combined with **balanced class weights** (draws get ~1.8× more weight than home wins)
7. Three-way time split: **XGBoost train** ≤ 2024-07-01, **isotonic calibration** 2024-07-01 → 2025-07-01, **test** 2025-07-01 → 2026-05-01 (2025/26 YTD)
8. Trains four XGBoost classifiers using `tree_method='hist'` and `nthread=-1` (all CPU cores)
9. Auto-tunes draw-blend α via Brier score sweep (0.05–0.45) on the calibration set; saves best value to `draw_alpha.json` (currently α=0.45)
10. Auto-tunes BTTS decision threshold via macro F1 sweep (0.30–0.75) on the calibration set; saves best value to `btts_threshold.json` (currently 0.52) — balances GG and NG recall equally
11. Saves all models and calibrators to `backend/data/models/`

### Current accuracy (test set — 2025/26 season YTD)

| Model                  | Accuracy  | Baseline (random) | Notes                                                    |
| ---------------------- | --------- | ----------------- | -------------------------------------------------------- |
| Result (W/D/L)         | **53.1%** | ~46%              | Calibrated; draw recall ~29%                             |
| Goals (O/U 2.5)        | **54.7%** | ~50%              | xG + time decay (market-independent)                     |
| BTTS (GG/NG)           | **52.9%** | ~50%              | Dedicated XGBClassifier + isotonic calibration + macro F1 threshold (0.52) |

> Test set is 2025/26 YTD (from 2025-07-01); calibration set is 2024/25 season (used for isotonic calibrators + draw α tuning + BTTS threshold sweep).
> The table above is a snapshot — live metrics for every weekly retrain are on `/admin/training`, and realised accuracy/ROI/CLV on `/stats`. A second-stage rolling recalibration (`scripts/recalibrate.py`, monthly + after each retrain) corrects drift against the last 365 days of stored out-of-sample predictions.

> **Training improvements (cumulative):**
> - **Market independence (2026-06)**: all bookmaker-derived features (incl. Pinnacle closing lines) were REMOVED so predictions are 100% our own signal; the de-vigged market is now only the benchmark that value/EV is measured against.
> - **xG from understat**: Expected goals are more stable than actual goals — ~16,500 matches matched from 2014/15 for the top-5 leagues.
> - **Time decay** (3-year half-life): Down-weights 2010–2015 data where squad quality, tactics, and market efficiency differ from today.
> - **Pi-Ratings** (Constantinou & Fenton 2012): Goal-based attack/defense ratings split by home/away context. Update by goal margin rather than win/loss — richer signal than Elo alone.
> - **Poisson expected-goals model** (Dixon & Coles 1997): Season-specific attack/defense strengths, normalised to league average. Provides `λ_home`, `λ_away`, and outcome probabilities from the full score-matrix distribution (including BTTS). Complements Pi-Ratings because Poisson resets per season while Pi-Ratings accumulate across seasons.
> - **Referee features**: `ref_home_win_rate`, `ref_draw_rate`, `ref_cards_per_game` per referee from historical EPL data (other leagues don't have Referee in the CSVs; XGBoost handles the NaN natively).
> - **Parallel training**: `tree_method='hist', nthread=-1` — uses all CPU cores. `hist` is equivalent to `exact` for accuracy; the older `exact` method was single-threaded.
> - **Train/test split**: three-way split — XGBoost trains on ≤ 2023/24, isotonic calibration + draw-α tuning on 2024/25, test on 2025/26 YTD.
>
> - **EWMA momentum features**: exponentially weighted goals/points (α=0.3) alongside flat rolling windows — recent matches carry proportionally more weight.
> - **League position feature**: normalized rank in current-season table (`h_league_pos_norm`, `a_league_pos_norm`, `league_pos_diff`) built from running standings; NaN for the first 2 matches of a new season.
> - **Odds movement (steam) features**: `odds_drift_*` and `is_steam_home/away` injected at inference from `odds_history` snapshots; always 0.0 in training (reserved for future retraining once historical odds data is available in training CSVs).
> - **Pi-Rating decay**: season-boundary decay (×0.85) now applied at inference as well as training, eliminating a train/inference mismatch.
> - **Dixon-Coles ρ correction** on Poisson probabilities: low-score outcomes (0-0, 1-0, 0-1, 1-1) corrected with τ(i,j) factor (ρ=−0.13). Already baked into `poisson_btts`, `poisson_home_win`, `poisson_draw`, etc.
> - **BTTS EV in batch predictions**: `_compute_ev()` now includes GG/NG markets in `suggested_market` / `ev_score` — was previously missing from `compute_predictions.py`.
> - **Dedicated BTTS classifier**: dedicated `XGBClassifier` (40 goal-oriented features) with isotonic calibration replaces the previous Poisson-only BTTS estimate. Accuracy: 52.4% vs 50.1% Poisson baseline.
> - **Draw specialist enabled + auto-tuned α**: draw-specialist binary classifier is now blended into result probabilities. Blend weight α is auto-tuned each training run via Brier score sweep on the calibration set (currently α=0.45). Previous value: hardcoded 0.20.
> - **BTTS macro F1 threshold sweep**: BTTS decision threshold auto-tuned each training run by sweeping 0.30–0.75 and maximising macro F1 (mean of GG F1 and NG F1) on the calibration set. Saves result to `btts_threshold.json` (currently 0.52). Previous: fixed 0.50, then briefly fixed 0.67 (NG-only F1, collapsed GG recall to 2%).
> - **Separate GOALS_FEATURE_COLS**: draw-balance features (6) are excluded from the goals model feature set — they add noise to O/U prediction and caused a regression when shared.
>
> **Inference improvements (do not affect benchmarks):**
> - **Live odds at prediction time**: `compute_predictions.py` fetches live bookmaker odds (one call per league via The Odds API) and injects them as `market_home_prob` / `market_away_prob` — the two most important features by XGBoost importance (8.7% and 8.4%). Previously these were set to static defaults.
> - **Closing-line refresh** (`--force-today`): re-fetches predictions for today's unstarted matches using closing-line odds, which are ~20–30% sharper than opening odds. Automated at 15:00 via `com.football-predictor.prematch`.
> - **Position-aware injury adjustment**: At detail-page time, API-Football provides current injury/suspension lists enriched with player positions from `/players/squads` (cached 24h). Probabilities are adjusted at serve-time only (raw DB values kept clean for accuracy tracking):
>   - **Attacker injured** → team scores less → over_2_5 ↓
>   - **Defender / Goalkeeper injured** → opponent scores more → over_2_5 ↑
>   - **Midfielder injured** → mild mixed effect
>   - **Diminishing returns**: 1st absence = 100% weight, 2nd = 65%, 3rd+ = 40% (bench players matter less)
>   - **Severity**: Suspended = 1.1×, Injured = 1.0×, Questionable = 0.35×
>   - Win probability cap: ±13% per team maximum
> - **Injury cache pre-warming**: `warmup_injuries.py` runs daily (next 3 days, new fixtures only) so the match list shows injury-adjusted predictions from first page load — not just after a detail-page visit.
> - **Dynamic confidence**: Confidence label (`high` / `medium` / `low`) is always recomputed from a composite formula combining result certainty and goals certainty — never stored stale in the DB.
> - **CL bookmaker odds**: Champions League now covered by The Odds API (`soccer_uefa_champs_league`) — fully participates in EV analysis and bet suggestions.

After retraining, restart the backend to load new models:

```bash
docker compose restart backend
```

---

## National Teams (International)

A separate prediction pipeline for international matches (World Cup, EURO,
Copa América, AFCON, Nations League, qualifiers, friendlies). Independent of
the club pipeline: its own dataset, features, models, DB table and API.

**Data** — [martj42/international_results](https://github.com/martj42/international_results)
(49k+ internationals since 1872, refreshed daily). Upcoming friendlies that the
dataset doesn't pre-publish are kept in `scripts/upcoming_friendlies.csv` and
re-injected after every refresh.

**Features (44)** — custom Elo (K=15–60 by tournament tier, +100 home adv.),
rolling form/goals windows (competitive-only variants), H2H, rest days,
tournament tier; separate draw-specialist feature set.

**Models** — XGBoost + LightGBM soft-vote (result / O-U 2.5 / BTTS) + draw
classifier with isotonic calibration and auto-tuned blend α. Trained < 2023,
calibrated on 2023, tested on 2024+ (out-of-sample): **59.7% result accuracy**.

**Odds & value** — bookmaker odds + EV from The Odds API for covered
tournaments (WC, EURO, Copa, AFCON, NL, qualifiers). Friendlies have no odds
source, so their odds columns stay NULL.

**Dynamic value gate (promotion + demotion)** — every market that clears the
EV/sanity filters is shadow-tracked in the `value_bets` ledger; only *proven*
markets become headline suggestions, the rest surface as "watch" (unproven).
The rule (`_market_is_proven`, shared by the live gate and `/admin/market-record`
so they can never disagree), measured on post-cutoff (2026-06-17) settled
tickets at opening odds:

- **Promotion** (non-base): n ≥ 30 settled **and** ROI ≥ 0%.
- **Demotion** (base = Home Win, Draw): start trusted, but demote to watch
  early at n ≥ 15 with ROI ≤ −20% (clear bleeders only — small-sample noise
  survives), and face the same ROI ≥ 0% floor as everyone once n ≥ 30.
  Stateless: a demoted market re-enters as soon as its cumulative record
  recovers. (First real casualty: Draw, demoted 2026-07-06 at 0/16, −100%.)

Proven set is cached 30 min in Redis (`proven_markets:national`) — flush after
changing gate constants. Status per market: `/admin/markets`.

```bash
# Refresh dataset → re-inject friendlies → predict → odds/EV → fill actuals
docker compose exec backend python scripts/fetch_international_data.py --force
docker compose exec backend python scripts/add_upcoming_national.py
docker compose exec backend python scripts/predict_national.py --save-db
docker compose exec backend python scripts/fetch_national_odds.py
docker compose exec backend python scripts/update_national_results.py

# Retrain national models (weekly in cron)
docker compose exec backend python scripts/train_national.py

# Backfill historical out-of-sample predictions (2024+ only — leakage-guarded)
docker compose exec backend python scripts/backfill_national_predictions.py

# Monte Carlo World Cup simulation (winner/finalist odds + market compare)
docker compose exec backend python scripts/simulate_wc.py --sims 20000 --save-json
```

**API** — `GET /national/predictions` (filters: tournament/from/to/confidence),
`GET /national/predictions/{id}`, `GET /national/stats`,
`GET /national/training-metrics`, `GET /national/wc-simulation`.

**Frontend** — `/national` (Upcoming + Results tabs), `/national/world-cup`
(Monte Carlo simulation page). International fixtures also merge into the home
"All Leagues" view and the CSV/JSON export.

All of the above runs automatically from `run_daily.sh` (see next sections).

---

## Seeding the Database

```bash
# Inside Docker (recommended)
docker compose exec backend python scripts/seed_db.py --no-predictions

# Specific seasons only
docker compose exec backend python scripts/seed_db.py --seasons 2324 2425 --no-predictions
```

Idempotent — safe to re-run.

---

## Live Fixtures & Daily Automation

### Fetch upcoming fixtures

Pulls real fixture schedules from football-data.org (next 60 days) for EPL, Championship, La Liga, Serie A, Bundesliga, Ligue 1, Primeira Liga, Eredivisie, and Champions League — including UTC kick-off times. Always use `--no-predictions` and run `compute_predictions.py` separately for speed:

```bash
docker compose exec backend python scripts/fetch_upcoming.py --days 60 --no-predictions
docker compose exec backend python scripts/compute_predictions.py
```

> **TBD fixtures**: CL knockout matches before the semi-finals are played have "TBD" teams — these are automatically skipped (null team name check).

### Fetch European fixtures (CL / EL / ECL)

CL fixtures come from football-data.org (`CL` competition code). EL and ECL come from The Odds API:

```bash
docker compose exec backend python scripts/fetch_european_fixtures.py --no-predictions
```

> **Note**: Always re-run `fetch_european_fixtures.py` and `fetch_greek_fixtures.py` after running `fetch_upcoming.py`, because `fetch_upcoming.py` clears all upcoming fixtures before re-inserting (including EL/ECL/GreekSL). Use `--keep-existing` to skip the clear step.

### Fetch Greek Super League fixtures

football-data.org doesn't cover Greek SL on the free tier. A dedicated script uses The Odds API:

```bash
docker compose exec backend python scripts/fetch_greek_fixtures.py --no-predictions
```

### Fetch club friendlies

Pre-season / exhibition club games (e.g. Olympiakos–Lyon). None of the regular
sources carries them, so a dedicated script pulls API-Football's "Friendlies
Clubs" league (id 667) and stores them under league code `ClubFriendly`:

```bash
docker compose exec backend python scripts/fetch_club_friendlies.py
docker compose exec backend python scripts/fetch_club_friendlies.py --days-ahead 21 --allow-unknown
```

- Team names are resolved against our training data (static map → slug →
  alias → difflib); fixtures whose teams we have no history for are skipped
  by default (`--allow-unknown` keeps 1-known-side fixtures with neutral
  default features, european-pipeline style).
- The same run fills final scores for played friendlies — `update_results.py`
  / `update_european_results.py` don't cover them.
- Predictions use the shared cross-league path; **confidence is forced
  `low`** for `ClubFriendly` (both at compute and serve time via
  `confidence_for()`), and The Odds API has no friendlies key, so odds/EV
  columns stay NULL — friendlies never become value-bet suggestions.

### Back-fill kick-off times for existing fixtures

One-off script that queries The Odds API `/events` endpoint and populates `kickoff_time` for any upcoming match still missing it:

```bash
docker compose exec backend python scripts/backfill_kickoff_times.py
```

Safe to re-run — only updates rows where `kickoff_time IS NULL`. The Odds API only surfaces events within ~2 weeks, so further-out fixtures are populated automatically as their matchday approaches via the daily automation.

### Update past results

Fetches final scores for recently played matches and updates the DB.

**Domestic leagues + Champions League** (football-data.org):

```bash
docker compose exec backend python scripts/update_results.py --days-back 7
```

**Greek Super League + Europa League + Conference League** (The Odds API):

```bash
docker compose exec backend python scripts/update_european_results.py --days-from 3
```

Both scripts are idempotent and are run automatically by the daily job.

### Compute predictions (batch)

Fast batch mode — builds team state once from 32k history rows, then computes all upcoming fixtures in O(1) each (~25 seconds for 250 matches). Also fetches live bookmaker odds and stores them in the predictions table for ROI/EV tracking:

```bash
docker compose exec backend python scripts/compute_predictions.py

# After retraining models — delete old predictions and recompute all:
docker compose exec backend python scripts/compute_predictions.py --force

# Refresh today's unstarted matches with closing-line odds (~2h before kick-off):
docker compose exec backend python scripts/compute_predictions.py --force-today
```

> **`--force-today`** deletes and recomputes predictions only for today's matches that have not yet kicked off (grace window: kick-off within the last 30 minutes is treated as "in progress" and left untouched). Run this 1-2h before kick-off to use sharper closing-line odds. Automated by the `com.football-predictor.prematch` launchd job at 15:00 daily.

### Pre-warm injury cache

Fetches injury/suspension data from API-Football for all upcoming matches (next N days) and stores in Redis. Without this, injury-adjusted predictions only appear in the match list after a user has visited the detail page. Skips matches already in cache (use `--force` to refresh all):

```bash
docker compose exec backend python scripts/warmup_injuries.py --days 3
docker compose exec backend python scripts/warmup_injuries.py --days 7 --force
```

API-Football free tier: 100 req/day. Only leagues with injury support (EPL, LaLiga, SerieA, Bundesliga, Ligue1, CL, EL, ECL, GreekSL) actually consume quota — ~20–30 calls for a 3-day window.

### Daily automation (macOS launchd)

Two launchd jobs are defined in `launchd/` and installed via the install script:

| Job                                  | Schedule                                 | What it does                                                                                                                                                                                                                                                  |
| ------------------------------------ | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `com.football-predictor.daily`       | Every day at **06:00** (+ on login/wake) | Runs `run_daily.sh`: domestic+CL results → EL/ECL/GreekSL results → top-5+CL+ELC+PPL+DED fixtures → Greek SL → CL/EL/ECL → compute predictions → backfill bm_odds → **warm injury cache** (next 3 days, new fixtures only) → clear stats cache. Every Monday also refreshes CSVs, retrains models, and force-recomputes all predictions. |
| `com.football-predictor.prematch`    | Every day at **15:00**                   | Runs `compute_predictions.py --force-today` — refreshes predictions for today's unstarted matches using closing-line odds (~2h before typical evening kick-offs, the sharpest market signal).                                                                  |
| `com.football-predictor.odds-poll`   | Every **3 hours**                        | Snapshots current bookmaker odds into the `odds_history` table. Powers odds movement arrows (↑/↓) on match detail pages, and feeds `odds_drift_*` / `is_steam_*` ML features at prediction time.                                                              |
| `com.football-predictor.cloudflared` | Always (KeepAlive)                       | Keeps the Cloudflare tunnel (aitipster.net) alive across reboots.                                                                                                                                                                                             |

Logs: `~/Library/Logs/football-predictor/`

> **macOS TCC note:** The launchd daily job calls a wrapper at `~/bin/football-predictor-daily.sh` rather than the script inside `~/Documents/` directly. This avoids the `Operation not permitted` error macOS imposes when `launchd` tries to access files inside protected folders without Full Disk Access.

To install on a new machine:

```bash
# Substitutes __PROJ_DIR__, __LOG_DIR__, __NGROK_DOMAIN__ from .env, then loads
bash launchd/install.sh

# To remove:
bash launchd/uninstall.sh
```

To manually trigger the daily run:

```bash
launchctl start com.football-predictor.daily
# or directly:
bash scripts/run_daily.sh
```

---

## Public Tunnel (Cloudflare)

The app is served at **[https://aitipster.net](https://aitipster.net)** via a **Cloudflare Tunnel** (free) — a custom domain with Cloudflare's edge (DNS, TLS, DDoS protection) in front, forwarding to `localhost:3000` on this machine.

The tunnel is managed by launchd (`com.football-predictor.cloudflared`) — it starts at login and restarts automatically if it crashes. Full setup guide: [`launchd/CLOUDFLARED_SETUP.md`](launchd/CLOUDFLARED_SETUP.md).

### Setup on a new machine

```bash
brew install cloudflared
cloudflared tunnel login                                # authorise the aitipster.net zone
cloudflared tunnel create aitipster                     # creds → ~/.cloudflared/
cloudflared tunnel route dns aitipster aitipster.net
cloudflared tunnel route dns aitipster www.aitipster.net
bash launchd/install.sh                                 # installs tunnel + cron services
```

### Check tunnel status

```bash
launchctl list | grep football-predictor
cloudflared tunnel list
curl -I https://aitipster.net
```

---

## API Reference

Interactive Swagger docs: **[http://localhost:8000/docs](http://localhost:8000/docs)**

### `GET /matches`

Returns paginated matches with optional embedded predictions.

| Parameter             | Type   | Default | Description                                                                                                    |
| --------------------- | ------ | ------- | -------------------------------------------------------------------------------------------------------------- |
| `league`              | string | —       | `EPL`, `LaLiga`, `SerieA`, `Bundesliga`, `Ligue1`, `GreekSL`, `CL`, `EL`, `ECL`, `Championship`, `PrimeiraLiga`, `Eredivisie` |
| `limit`               | int    | 40      | Results per page                                                                                               |
| `offset`              | int    | 0       | Pagination offset                                                                                              |
| `status`              | string | —       | `upcoming` or `past`                                                                                           |
| `include_predictions` | bool   | false   | Embed prediction data in each match (avoids N+1 fetches)                                                       |
| `days_back`           | int    | —       | With `status=past`: limit to matches played in the last N days (1–90)                                          |
| `days_offset`         | int    | 0       | Shift the `days_back` window back by N days — used for pagination                                              |
| `days_ahead`          | int    | —       | With `status=upcoming`: limit to fixtures in the next N days (1–30). Homepage uses 3.                          |
| `min_odds`            | float  | —       | Filter upcoming matches to those where the top-outcome bookmaker odds ≥ this value                             |
| `min_confidence`      | string | —       | Filter upcoming matches by confidence level: `high`, `medium` (includes high), or omit for all                 |

> **Upcoming filter:** `status=upcoming` excludes matches more than **2 hours past their kick-off time** (using the stored UTC `kickoff_time`). A match automatically disappears from the upcoming list and appears in past results roughly when it ends, even before the score is scraped.

> **Injury-adjusted predictions in the list view:** Embedded predictions apply cached injury adjustments from Redis (populated by `warmup_injuries.py` or a prior detail-page visit). If no cache entry exists, raw DB values are shown. The list view never triggers a fresh API-Football call.

**Match object** (with `include_predictions=true`):

```json
{
  "id": 1,
  "league": "EPL",
  "match_date": "2026-04-20",
  "kickoff_time": "14:00:00",
  "home_team": "Arsenal",
  "away_team": "Chelsea",
  "home_goals": null,
  "away_goals": null,
  "result": null,
  "prediction": {
    "home_win_prob": 0.47,
    "draw_prob": 0.28,
    "away_win_prob": 0.25,
    "over_2_5_prob": 0.61,
    "goals_prediction": "OVER",
    "confidence": "medium",
    "model_version": "1.0.0"
  }
}
```

### `GET /matches/export`

Export upcoming fixtures + predictions as CSV or JSON (max 500 rows). Supports all the same filter parameters as `GET /matches` plus `format=csv` (default) or `format=json`.

```
GET /matches/export?status=upcoming&min_confidence=high&format=csv
GET /matches/export?league=EPL&status=upcoming&format=json
```

### `GET /matches/{id}`

Single match by ID.

### `GET /predictions/{match_id}`

Compute or return cached prediction. If no prediction exists in the DB, runs ML inference on-demand and caches it.

**Response:**

```json
{
  "match_id": 1,
  "home_team": "Arsenal",
  "away_team": "Chelsea",
  "win_probabilities": { "home_win": 0.43, "draw": 0.29, "away_win": 0.28 },
  "goals": { "over_2_5_probability": 0.61, "prediction": "OVER" },
  "btts_prob": 0.52,
  "confidence": "medium",
  "model_version": "1.0.0"
}
```

> `btts_prob` — **Both Teams To Score** probability from the dedicated BTTS XGBClassifier (isotonic-calibrated). Falls back to Poisson score-matrix (`P(home ≥ 1 AND away ≥ 1)`) when the classifier model file is unavailable.

> Returned probabilities are **injury-adjusted** at serve-time (raw DB values are never overwritten). The confidence label and goals prediction are always recomputed from the displayed (adjusted) values.

### `GET /predictions/{match_id}/analysis`

Fetches live bookmaker odds from The Odds API, compares with ML model, fetches injury/suspension data from API-Football, and returns a **Groq GPT-OSS-120B** analysis in Greek. Cached in Redis for 30 minutes per match (cache key includes a model-probability fingerprint — auto-busts on retrain).

> **CL matches**: now fully supported — uses The Odds API `soccer_uefa_champs_league` sport key.

> **Not called for finished matches.** The frontend checks whether the match ended (kick-off time + 2 hours) and suppresses the analysis panel entirely.

**Response:**

```json
{
  "model": {
    "home_win": 0.47, "draw": 0.28, "away_win": 0.25,
    "over_2_5": 0.49, "btts": 0.52
  },
  "bookmakers": {
    "fair_probs": {
      "home_win": 0.45, "draw": 0.26, "away_win": 0.29,
      "over_2_5": 0.54, "under_2_5": 0.46,
      "btts_yes": 0.62, "btts_no": 0.38
    },
    "raw_odds": {
      "home_win": 2.10, "draw": 3.69, "away_win": 3.30,
      "over_2_5": 1.75, "under_2_5": 2.10,
      "btts_yes": 1.55, "btts_no": 2.45
    },
    "bookmakers": ["Bet365", "Unibet", "..."],
    "num_bookmakers": 24
  },
  "injuries": {
    "home": [{ "name": "Saka", "type": "Injured", "reason": "Muscle", "position": "Attacker" }],
    "away": [{ "name": "Reece James", "type": "Suspended", "reason": "Yellow Cards", "position": "Defender" }]
  },
  "analysis": "Το μοντέλο συμφωνεί σε μεγάλο βαθμό με τους bookmakers για νίκη γηπεδούχου...",
  "suggested_market": "Away Win @ 3.30",
  "has_odds_data": true,
  "has_injury_data": true
}
```

> `injuries[].position` — enriched from API-Football `/players/squads` (cached 24h). Values: `"Attacker"`, `"Midfielder"`, `"Defender"`, `"Goalkeeper"`, or `null` if not found in squad list.

> `injuries[].type` — normalised from API-Football's raw values (`"Missing Fixture"` → `"Injured"`, reason containing "Cards"/"Suspension" → `"Suspended"`, reason containing "doubt"/"questionable" → `"Questionable"`).

#### Suggested market — Expected Value logic

```
EV = model_probability × bookmaker_decimal_odds − 1
```

**Two-tier EV filter:**
- **≥ 5% EV** required when suggesting the model's own top-probability outcome. Bookmakers rarely misprice clear favourites, so we require a stronger edge.
- **≥ 3% EV** required for any alternative/contrarian market.

**Longshot filter:** markets where bookmakers imply a probability below **10%** are excluded regardless of EV.

**Fallback**: if Groq returns no suggestion (e.g. "None" / "N/A"), the endpoint falls back to the deterministic EV winner computed directly from the probability table.

### `POST /chat`

AI chatbot endpoint. Accepts a user message and optional conversation history; returns a Greek-language response from **Groq GPT-OSS-120B** with full awareness of upcoming fixtures and predictions.

**Request:**

```json
{
  "message": "δώσε μου 3 σημεία EPL με υψηλό confidence",
  "history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

**Response:**

```json
{
  "reply": "Για σήμερα, οι κορυφαίες προτάσεις για την Premier League είναι..."
}
```

The system prompt includes upcoming fixtures for the **next 3 days** (reduced from 7 to cut token usage ~60%) with probabilities and confidence levels, cached in Redis for 30 minutes. Up to 10 previous turns of history are passed so the conversation is stateful. The endpoint is available at `/api/proxy/chat` from the browser (via the Next.js proxy).

### `GET /stats`

Model accuracy and ROI tracking dashboard data. Cached in-process for 6 hours.

**Response includes:**
- Rolling accuracy windows (all-time, last 30d, last 7d) — result + O/U + both correct
- Per-league breakdown
- Per-confidence-level breakdown (high/medium/low)
- Per-predicted-outcome breakdown (H/D/A/OVER/UNDER)
- Draw specialist stats (recall + precision)
- BTTS (GG/NG) stats — recall, precision, accuracy + calibration buckets
- Top AI Picks accuracy (top 3/day, mirrors the homepage picks)
- `roi` — flat €10 stake ROI tracker (result + goals + BTTS markets), `null` until bookmaker odds are stored. Includes **fair-value (vig-removed) ROI** fields (`*_roi_fair_pct`, `total_roi_fair_pct`, `fair_available`)
- `ev_series` — daily cumulative EV vs P&L time series for the chart, including `cumulative_pnl_fair` (de-vigged P&L line)
- `clv` — closing-line value of suggested bets (beat-close %, avg CLV%)
- Calibration buckets (O/U + result + BTTS probability bins vs actual frequency)
- Per-model-version breakdown

---

## Model Deep-Dive

### Four classifiers

| Model                  | Task              | Algorithm              | Features              | Output                         |
| ---------------------- | ----------------- | ---------------------- | --------------------- | ------------------------------ |
| `model_result.pkl`     | Match outcome     | XGBoost multi-class    | 124 (RESULT_FEATURE_COLS) | 0=Home Win, 1=Draw, 2=Away Win |
| `model_goals.pkl`      | Goal total        | XGBoost binary         | 118 (GOALS_FEATURE_COLS)  | 1=Over 2.5, 0=Under 2.5        |
| `model_draw_clf.pkl`   | Draw specialist   | XGBoost binary         | 124 (RESULT_FEATURE_COLS) | 1=Draw, 0=Not Draw (blended into result probs with α=`draw_alpha.json`) |
| `model_btts_clf.pkl`   | Both Teams Score  | XGBoost binary         | 40 (BTTS_FEATURE_COLS)    | 1=GG (both score), 0=NG        |

### Feature set (133 features)

**Rolling windows** (5 and 10 matches) per team — 42 features:
- Goals scored / conceded (all venues + venue-split)
- Form (points per game), goal difference, total goals, Over 2.5 rate
- Shots on target for / against

**xG rolling windows** (5 and 10 matches) — 8 features:
- `h_xg_scored_5/10`, `h_xg_conceded_5/10`, `a_xg_scored_5/10`, `a_xg_conceded_5/10`
- Source: understat.com, EPL/LaLiga/SerieA/Bundesliga/Ligue1, from 2014/15
- NaN for GreekSL + pre-2014/15 seasons — imputed with training median at inference

**Market features — intentionally NONE (removed 2026-06):**
- `market_home/draw/away/over_prob` used to be the top features by XGBoost gain, which meant the model was largely repackaging the bookmaker's opinion.
- They are now excluded from every feature list (`MARKET_DERIVED_COLS` in `features.py`), so predictions are 100% independent signal; de-vigged market odds are used **only** as the benchmark for EV/value.

**Elo ratings** (K=32, start=1500) — 4 features:
- `h_elo`, `a_elo`, `elo_diff`, `elo_home_win_prob`

**Pi-Ratings** (Constantinou & Fenton 2012) — 10 features:
- 4 ratings per team: `home_att`, `home_def`, `away_att`, `away_def`
- Updated after every match by *goal error* (actual − expected goals)
- Features: `h_pi_att`, `h_pi_def`, `a_pi_att`, `a_pi_def`, `pi_att_diff`, `pi_def_diff`, `pi_exp_home`, `pi_exp_away`, `pi_exp_diff`, `pi_exp_total`
- Cumulative across seasons — captures long-term team strength trajectory

**Poisson expected-goals model** (Dixon & Coles 1997) — 9 features:
- Season-specific attack/defense strengths, normalised to league average per season
- `poisson_lambda_home`, `poisson_lambda_away` — expected goals for each team
- `poisson_home_win`, `poisson_draw`, `poisson_away_win` — outcome probs from score matrix
- `poisson_over_2_5` — P(total goals > 2.5)
- `poisson_btts` — P(both teams score ≥ 1) — also surfaced as `btts_prob` in the prediction API
- Complements Pi-Ratings: Poisson resets each season (current form), Pi-Ratings accumulate across seasons (long-term quality)

**European congestion** — 6 features:
- Whether each team played a European match in the previous 4 days
- Home/away nature and result of that match

**Head-to-head** (last 5 meetings) — 3 features:
- `h2h_home_wins`, `h2h_away_wins`, `h2h_draws`

**Referee features** — 3 features (EPL only):
- `ref_home_win_rate`, `ref_draw_rate`, `ref_cards_per_game`
- Minimum 20 observed matches before stats are used; NaN otherwise

**League one-hot** — 6 features: `league_EPL`, `league_LaLiga`, `league_SerieA`, `league_Bundesliga`, `league_Ligue1`, `league_GreekSL`

**Derived expected goals** — 6 features: `expected_home_goals_5/10`, `expected_away_goals_5/10`, `expected_goals_5/10`

**EWMA momentum** — 6 features:
- `h_ewma_scored`, `h_ewma_conceded`, `a_ewma_scored`, `a_ewma_conceded`, `h_ewma_form`, `a_ewma_form`
- Exponentially weighted moving average (α=0.3, ~3.3-match effective window)
- Complements flat rolling averages: recent matches carry ~3× more weight than 10-match-old matches
- NaN for a team's very first match — XGBoost handles natively

**League position** — 3 features:
- `h_league_pos_norm`, `a_league_pos_norm` — normalized rank in current season table (0.05 = 1st of 20, 1.0 = last)
- `league_pos_diff` — h_pos − a_pos (positive = home team ranked worse than away)
- Computed from rolling season standings; NaN for first 2 matches of a season (< 3 teams in table)

**Odds movement / steam** — 6 features:
- `odds_drift_home/draw/away/over` — current raw odds − earliest stored odds (negative = shortened = steam)
- `is_steam_home`, `is_steam_away` — binary flag when drift < −0.15 (sharp-money signal)
- Populated at inference from the `odds_history` table (polled every 3h); always 0 in training

**Draw-balance features** — 6 features (result model only; excluded from goals model):
- `goals_asymmetry_5` — |h_goals_scored_5 − a_goals_scored_5|: high asymmetry → unlikely draw
- `combined_draw_tendency` — geometric mean of h/a draw rates over last 5 matches
- `pi_closeness` — 1/(1 + |pi_att_diff| + |pi_def_diff|): teams closer in Pi-Rating → more draws
- `market_draw_edge` — market_draw_prob − poisson_draw: market overweights draws vs model
- `low_total_xg` — binary flag when pi_exp_total < 2.0 (low-scoring game expected)
- `elo_closeness` — 1/(1 + |elo_diff|): evenly-matched teams → more draws

### Sample weighting

Two sources of weight are multiplied together during training:

- **Class balance** (`compute_sample_weight("balanced")`): draws (~25% of matches) receive ~1.8× more weight than home wins. This ensures draw patterns are learned rather than ignored.
- **Time decay** (3-year half-life, `exp(-k × days_old)`): a match played 3 years before the training cutoff gets weight 0.5; one played 6 years ago gets 0.25. Modern matches dominate.

### COVID exclusion

The 2020/21 season is excluded from training — matches behind closed doors removed the home-crowd advantage signal.

### Position-aware injury adjustment (serve-time only)

The raw XGBoost probabilities are never modified in the DB. At serve-time, API-Football injury data is applied with position-aware logic:

| Position   | Effect on over_2_5 | Reason |
| ---------- | ------------------- | ------ |
| Attacker   | ↓ (−70% of impact)  | Team scores fewer goals |
| Midfielder | ↓ (−25% of impact)  | Mild dual effect |
| Defender   | ↑ (+55% of impact)  | Opponent gets easier chances |
| Goalkeeper | ↑ (+65% of impact)  | Weakened keeping |

Diminishing returns: 1st absence = 100%, 2nd = 65%, 3rd+ = 40% (squad depth assumed).
Win probability cap per team: 13% maximum shift.
Bookmaker odds already partially price in injuries, so the adjustment is intentionally conservative.

---

## Frontend Pages

| Page              | URL             | Description                                                                                                                                                      |
| ----------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Upcoming fixtures | `/`             | Next 3 days of fixtures with ML predictions. **Top 3 AI Picks** section at the top. **⚡ Value Badge** on each card when positive EV exists (market + EV% in tooltip). Filter by league, confidence level (Any / High only / Medium+), and minimum bookmaker odds. **Export** picks as CSV or JSON. Kick-off time in Athens time. Matches auto-disappear 2h after kick-off. |
| Recent results    | `/recent`       | Past 7 days of results with prediction accuracy. 🟢 Green = both correct, 🟡 Amber = one correct, 🔴 Red = both wrong. **"Γιατί χάθηκε;"** AI post-mortem button on wrong predictions — generates event-based analysis (goals/cards/penalties) via Groq. Paginated — 7 days per page. |
| Match detail      | `/matches/:id`  | Full prediction breakdown + live bookmaker odds + AI analysis in Greek (Groq GPT-OSS-120B). **Odds movement arrows ↑/↓** next to each bookmaker odd (polled every 3h). EV table shows which market offers most value. Injury list shows player name, status, and position. Hidden for finished matches. |
| Stats & Accuracy  | `/stats`        | Model accuracy dashboard: rolling windows, per-league/confidence/outcome breakdowns, draw specialist stats, **ROI Tracker** (flat €10 stake simulation), **Cumulative EV vs P&L chart**, O/U calibration, model version history. |
| AI Chatbot        | All pages       | Floating chat button (bottom-right). Context-aware Groq assistant in Greek — knows upcoming fixtures (next 3 days) and probabilities. Full conversation history, quick-prompt chips. Context cached 30 min in Redis. |

### Timezone handling

All dates and kick-off times throughout the app are displayed in **Europe/Athens** (EET/EEST). The backend stores UTC times; the frontend converts them at render time using `timeZone: "Europe/Athens"` in `toLocaleDateString` / `toLocaleTimeString`. This ensures SSR output and browser output are always identical, regardless of where the visitor is located.

### ROI Tracker & EV Chart

The Stats page shows simulated ROI for flat €10-per-prediction betting (result market + Over 2.5 market + GG/BTTS). Data accumulates automatically as matches complete — `compute_predictions.py` stores bookmaker odds at prediction time in the `predictions` table (`bm_home_odds`, `bm_draw_odds`, `bm_away_odds`, `bm_over_odds`, `bm_btts_yes_odds`, `bm_btts_no_odds`). Matches predicted before this feature was added show placeholders; all new predictions contribute to the tracker going forward.

#### Fair-value ROI (vig removed)

The headline metric is **Fair-value ROI** — the same simulated bets priced at the *de-vigged* "fair" odds instead of the bookmaker's quoted odds. This isolates pure model skill from the bookmaker commission:

- **Fair odds** = `quoted_odds × Σ(implied probabilities)` (multiplicative de-vig over the full market).
- **Result (1×2)** and **BTTS (GG/NG)** are de-vigged exactly — all outcome odds are stored.
- **O/U 2.5** uses an assumed 4% two-way overround (`GOALS_OVERROUND = 1.04` in `stats.py`) because under-2.5 odds are not stored; this market is flagged with `*`.

A Fair-value ROI **≈ 0%** means the model's probabilities are *as accurate as the fair market line* — the entire negative quoted-odds ROI is the bookmaker vig, not a model error. It is **not an achievable return** (you cannot bet at fair odds anywhere); it is a model-quality metric. The EV chart plots a third **amber "Fair P&L"** line alongside actual P&L — the gap between them is exactly the cumulative vig paid.

Backend fields: `ROIStats.{fair_available, result_roi_fair_pct, goals_roi_fair_pct, btts_roi_fair_pct, total_roi_fair_pct, *_pnl_fair, goals_fair_is_estimated}` and `EVDataPoint.{daily_pnl_fair, cumulative_pnl_fair}`.

> **Note:** `POST /stats/cache/clear` is admin-protected. To force-refresh the cached stats during development, run `docker compose exec redis redis-cli DEL stats:global` (or wait for the 6h TTL).

---

## Adjusting & Improving the Model

### Change the train/test split

In `backend/app/ml/train.py`:

```python
CAL_CUTOFF   = pd.Timestamp("2024-07-01")   # end of 2023/24 → XGBoost training cutoff
TRAIN_CUTOFF = pd.Timestamp("2025-07-01")   # end of 2024/25 → calibration cutoff
TEST_CUTOFF  = pd.Timestamp("2026-05-01")   # 2025/26 YTD → test
```

XGBoost trains on rows before `CAL_CUTOFF`. The 2024/25 season (`CAL_CUTOFF` → `TRAIN_CUTOFF`) is used as a held-out calibration set for isotonic calibrators and draw-α tuning. The 2025/26 YTD rows (`TRAIN_CUTOFF` → `TEST_CUTOFF`) are the test set.

### Tune XGBoost hyperparameters

Result model key parameters:

```python
XGBClassifier(
    n_estimators=800,        # more trees = slower but potentially more accurate
    max_depth=4,             # deeper trees → more complex patterns
    learning_rate=0.03,
    subsample=0.75,
    colsample_bytree=0.7,
    min_child_weight=5,
    tree_method="hist",      # parallel training (all CPU cores)
    nthread=-1,
    early_stopping_rounds=50,
)
```

### Add new features

1. Compute the feature inside `build_features()` in `features.py` — must only use data from **before** the current row (no leakage).
2. Also add it to `build_team_snapshot()` and `compute_match_features()` in `features.py` (used by batch prediction).
3. Add the column name to `FEATURE_COLS`.
4. Add a fallback value in the `DEFAULTS` dict in `scripts/compute_predictions.py` and the `fillna()` dict in `predict.py`.
5. Retrain.

---

## Project Structure

```
football-predictor/
│
├── backend/
│   ├── Dockerfile
│   ├── entrypoint.sh                  # runs Alembic migrations then uvicorn
│   ├── requirements.txt               # includes groq>=0.13.0
│   ├── alembic/                       # DB migrations (0001–0014)
│   │   └── versions/
│   │       ├── 0001_initial_schema.py
│   │       ├── 0002_add_kickoff_time.py
│   │       ├── 0003_add_bm_odds_to_predictions.py    # bm_home/draw/away/over_odds
│   │       ├── 0004_add_ev_score_suggested_market.py # suggested_market, ev_score
│   │       ├── 0005_add_odds_history.py              # odds_history table (movement arrows)
│   │       ├── 0006_add_poisson_lambdas.py           # poisson_lambda_home/away
│   │       ├── 0007_add_users_tables.py
│   │       ├── 0008_add_is_admin_to_users.py
│   │       ├── 0009_add_raw_probs_to_predictions.py  # raw_home/draw/away/over_prob
│   │       ├── 0010_add_training_runs.py
│   │       ├── 0011_add_btts_metrics_to_training_runs.py
│   │       ├── 0012_add_btts_odds_to_predictions.py  # bm_btts_yes/no_odds
│   │       ├── 0013_add_btts_prediction_to_predictions.py  # btts_prob, btts_prediction
│   │       └── 0014_add_login_tracking_to_users.py        # last_login_at, login_count
│   └── app/
│       ├── main.py                    # FastAPI app + router registration
│       ├── database.py                # SQLAlchemy engine + SessionLocal
│       ├── cache.py                   # Redis wrapper (CACHE_MISS sentinel, graceful fallback)
│       ├── models/
│       │   ├── match.py               # Match ORM (incl. kickoff_time UTC TIME column)
│       │   ├── prediction.py          # Prediction ORM (bm_odds, suggested_market, ev_score)
│       │   └── odds_history.py        # OddsHistory ORM (match_id FK CASCADE, fetched_at)
│       ├── schemas/
│       │   ├── match.py               # PredictionEmbed (flat, for N+1 fix)
│       │   ├── prediction.py          # PredictionResponse, AnalysisResponse, InjuredPlayer (w/ position)
│       │   └── stats.py               # StatsResponse, ROIStats, EVDataPoint, CalibrationBucket, …
│       ├── routers/
│       │   ├── matches.py             # GET /matches + /export — injury-adjusted via Redis cache
│       │   ├── predictions.py         # GET /predictions/{id}, /analysis, /postmortem
│       │   ├── stats.py               # GET /stats — accuracy, ROI, EV series, calibration
│       │   └── chat.py                # POST /chat — Groq GPT-OSS-120B (3-day context, Redis cached)
│       └── ml/
│           ├── features.py            # build_features, build_team_snapshot, FEATURE_COLS (124)
│           ├── train.py               # XGBoost training (tree_method=hist, nthread=-1, 4 models)
│           ├── predict.py             # predict_match(), draw blend, BTTS inference, _ml_confidence()
│           ├── calibration.py         # fit_calibrators() — isotonic for result/goals/draw/BTTS
│           ├── btts_classifier.py     # fit/predict/load BTTS XGBClassifier + isotonic calibrator
│           ├── draw_classifier.py     # fit/predict/load draw specialist classifier
│           ├── pipeline.py            # end-to-end predict pipeline helper
│           ├── poisson.py             # Poisson EG model (Dixon & Coles 1997)
│           ├── european.py            # European competition congestion features
│           ├── injury_adjustment.py   # Position-aware serve-time prob shift (Attacker/Defender/GK/Mid)
│           └── odds_analysis_service.py  # The Odds API + Groq (Greek) + API-Football injuries w/ squad positions
│
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── page.tsx               # Upcoming fixtures (Top 3 Picks + league/confidence/odds filters + export)
│       │   ├── recent/                # Past results — 🟢/🟡/🔴 per prediction (7 days/page)
│       │   ├── matches/[id]/          # Match detail + bookmaker odds + AI analysis + injury positions
│       │   ├── stats/
│       │   │   └── page.tsx           # Stats dashboard (accuracy + ROI + EV + calibration)
│       │   └── api/proxy/[...path]/   # Next.js proxy → backend (single public URL, forwards body)
│       ├── components/
│       │   ├── MatchCard.tsx          # Upcoming match card (kick-off time in Athens time)
│       │   ├── TopPicks.tsx           # Top 3 AI Picks section (confidence + max prob ranking)
│       │   ├── ChatBox.tsx            # Floating AI chatbot (Groq, Greek, conversation history)
│       │   ├── RecentResultCard.tsx   # Recent result card (green/amber/red accuracy)
│       │   ├── LeagueFilter.tsx       # League selector
│       │   ├── ConfidenceFilter.tsx   # Confidence filter (Any / High only / Medium+)
│       │   ├── ExportButton.tsx       # Export picks (CSV / JSON)
│       │   ├── MatchAnalysis.tsx      # Bookmaker odds + EV table + Groq AI panel + injury positions
│       │   └── stats/
│       │       ├── StatCard.tsx       # Metric card with accent colours
│       │       ├── AccuracyBar.tsx    # Horizontal bar (label + fill%)
│       │       ├── LeagueTable.tsx    # Per-league accuracy table
│       │       ├── CalibrationChart.tsx  # O/U calibration chart (pure SVG)
│       │       ├── ROICard.tsx        # ROI Tracker (result + goals market breakdown)
│       │       └── EVChart.tsx        # Cumulative EV vs P&L dual-line chart (pure SVG, no deps)
│       └── lib/
│           └── api.ts                 # Typed API client; sendChat(); buildExportUrl(); LEAGUES (14)
│
├── scripts/
│   ├── download_data.py               # Fetch CSVs (E0 E1 SP1 I1 D1 F1 P1 N1 + European)
│   ├── download_xg.py                 # Fetch xG data from understat.com
│   ├── seed_db.py                     # CSV → PostgreSQL
│   ├── fetch_upcoming.py              # Live fixtures from football-data.org (PL ELC PD SA BL1 FL1 PPL DED CL)
│   ├── fetch_greek_fixtures.py        # Greek SL fixtures + kickoff_time via The Odds API
│   ├── fetch_european_fixtures.py     # CL/EL/ECL fixtures + kickoff_time
│   ├── fetch_club_friendlies.py       # Club friendlies (API-Football 667) + results + low-conf predictions
│   ├── backfill_kickoff_times.py      # One-off: populate kickoff_time for existing NULL rows
│   ├── update_results.py              # Update past match scores (domestic + CL)
│   ├── update_european_results.py     # Update EL/ECL/GreekSL scores via The Odds API
│   ├── compute_predictions.py         # Batch ML predictions + live odds injection + bm_odds storage
│   ├── warmup_injuries.py             # Pre-warm Redis injury cache (next N days, skips existing)
│   ├── optimize_pi_params.py          # Bayesian optimization of PI_C/K/BASE/DECAY via scipy differential_evolution
│   └── run_daily.sh                   # Daily: results → fixtures → predictions → warm injuries → clear cache
│
├── launchd/
│   ├── com.football-predictor.cloudflared.plist  # Cloudflare tunnel (KeepAlive)
│   ├── com.football-predictor.daily.plist   # Daily refresh at 06:00 (RunAtLoad=true)
│   ├── CLOUDFLARED_SETUP.md                 # One-time tunnel setup guide
│   ├── install.sh                           # Substitute placeholders + load services
│   └── uninstall.sh                         # Unload + remove services
│
├── ~/bin/football-predictor-daily.sh  # macOS TCC wrapper (outside ~/Documents/)
│
├── docker-compose.yml
├── .env                               # All secrets (gitignored)
├── ROADMAP.md
└── README.md
```

---

## Troubleshooting

### aitipster.net not reachable (Cloudflare error 530/1033)

530 means Cloudflare can't reach the tunnel — cloudflared isn't running on this machine:

```bash
launchctl list | grep football-predictor
cloudflared tunnel list        # "aitipster" should show an active connection
# If not running:
launchctl load ~/Library/LaunchAgents/com.football-predictor.cloudflared.plist
tail -20 ~/Library/Logs/football-predictor/tunnel-stderr.log
```

### "No CSV files found" when seeding

```bash
python scripts/download_data.py
```

### Backend fails to start — "could not connect to server"

```bash
docker compose logs db
docker compose logs backend
```

### Predictions are stale / missing for new fixtures

```bash
docker compose exec backend python scripts/compute_predictions.py

# After retraining — force-recompute all predictions with new model:
docker compose exec backend python scripts/compute_predictions.py --force
```

### Match list shows different Over/Under than detail page

The list view applies injury adjustments from Redis cache. If the cache is empty (e.g. after restart), visit the detail page once to trigger the API-Football fetch, or run the warmup:

```bash
docker compose exec backend python scripts/warmup_injuries.py --days 3
```

### ROI Tracker shows placeholder / no data

ROI data accumulates from matches predicted **after** the bookmaker odds columns were added (migration 0003). To start collecting data immediately, run:

```bash
docker compose exec backend python scripts/compute_predictions.py --force
```

This re-stores predictions with current odds. ROI will then appear as those matches complete.

### Environment variable not picked up after .env change

`docker compose restart` does **not** reload `.env` — the values are baked at container creation. Always use:

```bash
docker compose up -d --force-recreate backend
```

If the image itself needs to be rebuilt (new code, new package):

```bash
docker compose build backend && docker compose up -d --force-recreate backend
```

### No European (CL / EL / ECL) matches showing

```bash
docker compose exec backend python scripts/fetch_european_fixtures.py
```

### No Greek Super League matches showing

```bash
docker compose exec backend python scripts/fetch_greek_fixtures.py
```

### Fixtures missing kick-off times

```bash
docker compose exec backend python scripts/backfill_kickoff_times.py
```

### Chatbot returns "GROQ_API_KEY not configured"

The `GROQ_API_KEY` must be in `.env` and the backend container must be recreated (not just restarted) to pick it up:

```bash
docker compose up -d --force-recreate backend
```

Verify the key is loaded:

```bash
docker compose exec backend env | grep GROQ
```

### launchd daily job fails with "Operation not permitted"

This is a macOS TCC issue. The fix is already applied: the launchd plist calls `~/bin/football-predictor-daily.sh` (outside `~/Documents/`) which then calls the real script. If the wrapper is missing:

```bash
mkdir -p ~/bin
echo '#!/bin/bash
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
exec /bin/bash /Users/makis/Documents/Work/football-predictor/scripts/run_daily.sh' > ~/bin/football-predictor-daily.sh
chmod +x ~/bin/football-predictor-daily.sh
launchctl unload ~/Library/LaunchAgents/com.football-predictor.daily.plist
launchctl load  ~/Library/LaunchAgents/com.football-predictor.daily.plist
```

### Past match results not updating

```bash
# Domestic leagues + Champions League
docker compose exec backend python scripts/update_results.py --days-back 14

# Greek Super League + Europa League + Conference League
docker compose exec backend python scripts/update_european_results.py --days-from 7
```

### Check daily automation logs

```bash
tail -50 ~/Library/Logs/football-predictor/daily.log
tail -20 ~/Library/Logs/football-predictor/daily-stderr.log
```

### Model files missing after rebuild

Models are stored on the host at `backend/data/models/` and mounted as a volume. Retrain if missing:

```bash
docker compose exec backend python -m backend.app.ml.train
docker compose restart backend
```

### Adminer login

| Field    | Value         |
| -------- | ------------- |
| System   | PostgreSQL    |
| Server   | `db`          |
| Username | (from `.env`) |
| Password | (from `.env`) |
| Database | (from `.env`) |
