# Football Predictor — Handoff Summary (2026-04-25)

## Project Overview

Full-stack football prediction platform. Target: pro bettors + B2B.

**Stack:** Next.js 14 (App Router, Tailwind, TypeScript) · FastAPI + Python 3.11 · PostgreSQL 16 · Redis 7 · Docker Compose · Groq Llama 3.3 70B · macOS launchd

**Live URL:** https://hamster-manger-uplifting.ngrok-free.dev  
**Working dir:** `/Users/makis/Documents/Work/football-predictor`  
**DB credentials:** user/password @ football_db  

---

## ML Model

- Two XGBoost classifiers: `model_result.pkl` (H/D/A, 3-class) + `model_goals.pkl` (O/U 2.5, binary)
- 95 features: rolling stats, xG, Elo, Pi-Ratings, Poisson EG model, Pinnacle odds (features #1/#2), European congestion, H2H, referee stats
- Isotonic calibration (OVR, renormalized). **Draw specialist DISABLED** — it used `scale_pos_weight=3.0` which inflated draw predictions to 37% vs market-implied 25%. The calibrated result model alone correctly matches market draw probabilities (~27% ours vs ~25% market).
- Injury adjustment at inference time (API-Football, ±14pp max)
- `compute_predictions.py --force` recomputes all future predictions

---

## Database Schema (Alembic 0001–0005)

| Table | Key columns |
|---|---|
| `matches` | id, league, match_date, kickoff_time (UTC), home_team, away_team, home_goals, away_goals, result |
| `predictions` | match_id (unique FK), home_win_prob, draw_prob, away_win_prob, over_2_5_prob, goals_prediction, confidence, bm_home/draw/away/over_odds, suggested_market, ev_score |
| `odds_history` | match_id (FK CASCADE), home/draw/away/over_odds, fetched_at |

---

## API Keys Required (.env)

```
ODDS_API_KEY        # The Odds API (20k req/month)
GROQ_API_KEY        # Groq Llama 3.3 70B (100k TPD free)
API_FOOTBALL_KEY    # football-data.org (fixtures + results)
API_SPORTS_KEY      # api-sports.io (injuries, 100 req/day)
REDIS_URL           # redis://redis:6379/0 (Docker internal)
```

---

## Caching (Redis)

`backend/app/cache.py` — thin Redis wrapper with `CACHE_MISS` sentinel (distinguishes miss from cached None).

| Key pattern | TTL | Content |
|---|---|---|
| `injuries:{match_id}` | 30min | API-Football injury list |
| `analysis:{match_id}:{fingerprint}` | 30min | Groq match analysis |
| `postmortem:{match_id}` | 24h | Groq post-mortem text |
| `stats:global` | 6h | StatsResponse JSON |
| `league_odds:{league}` | 30min | The Odds API response |
| `btts:{event_id}` | 30min | BTTS odds |
| `match_events:{fixture_id}` | 24h | API-Football events |
| `api_fixtures:{league}:{date}` | 24h | Fixture ID lookup |

Graceful fallback to no-op if Redis unavailable.

---

## Completed Features

| Feature | Status | Notes |
|---|---|---|
| XGBoost + calibration + 95 features | ✅ | Draw specialist disabled |
| Live odds injection at prediction time | ✅ | Pinnacle fair probs as features #1/#2 |
| Bookmaker odds stored in DB | ✅ | For ROI/EV tracking |
| **Value Badge ⚡** on match cards | ✅ | `ev_score` + `suggested_market` in DB, badge in MatchCard.tsx |
| **AI Post-Mortem** ("Γιατί χάθηκε;") | ✅ | Real match events from API-Football, cached 24h |
| **Odds Movement ↑/↓** | ✅ | `odds_history` table, launchd every 3h, delta arrows in UI |
| **Redis caching** | ✅ | All in-process dicts replaced |
| Top 3 AI Picks section | ✅ | |
| ROI Tracker + EV Chart | ✅ | Flat €10 stake simulation, pure SVG |
| AI chatbot (floating, Greek) | ✅ | Groq, conversation history, quick chips |
| Stats & Accuracy dashboard | ✅ | Rolling windows, per-league, calibration |

---

## Key Files

```
backend/app/cache.py                     # Redis wrapper
backend/app/ml/predict.py                # inference pipeline (draw blend disabled)
backend/app/ml/draw_classifier.py        # draw specialist (DISABLED at inference)
backend/app/ml/calibration.py            # isotonic OVR calibration
backend/app/ml/odds_analysis_service.py  # The Odds API + Groq + fetch_match_events()
backend/app/routers/predictions.py       # /predictions/{id}/analysis + /postmortem
backend/app/routers/matches.py           # GET /matches with include_predictions
backend/app/routers/stats.py             # GET /stats (Redis cached)
backend/app/models/odds_history.py       # OddsHistory ORM
scripts/compute_predictions.py           # batch ML + odds injection + EV computation
scripts/poll_odds.py                     # odds_history polling (called by launchd)
launchd/com.football-predictor.odds-poll.plist  # every 3h: 0,3,6,9,12,15,18,21h
frontend/src/components/MatchCard.tsx    # ⚡ value badge
frontend/src/components/MatchAnalysis.tsx # odds movement arrows + EV panel
frontend/src/lib/api.ts                  # typed API client
```

---

## Pending Roadmap (priority order)

| # | Feature | Complexity | Impact |
|---|---|---|---|
| 1 | **Odds Filter (2.3)** — "show only odds > 1.80" on home page | 🟢 Low | 🔥🔥 |
| 2 | **Interactive Stats filters (2.1)** — click league → filter all charts | 🟡 Medium | 🔥🔥 |
| 3 | **User Dashboard / SaaS (3.1)** — NextAuth, user accounts, track matches | 🔴 Very High | 🔥🔥🔥 |
| 4 | **Live In-Play (3.2)** — excluded for now | 🔴 Extreme | 🔥🔥🔥🔥🔥 |

Next immediate task: **Odds Filter (2.3)** — new filter UI component + `min_odds` query param on `GET /matches` (backend already accepts it in the signature, just needs wiring).

---

## Automation (launchd)

| Job | Schedule | What |
|---|---|---|
| `com.football-predictor.daily` | 06:00 daily | results → fixtures → predictions; Monday: + retrain |
| `com.football-predictor.tunnel` | KeepAlive | ngrok static tunnel |
| `com.football-predictor.odds-poll` | 0,3,6,9,12,15,18,21h | poll odds_history |

Install: `bash launchd/install.sh`

---

## Docker Operations

```bash
# Full rebuild (code change):
docker compose build backend && docker compose up -d --force-recreate backend

# Recompute predictions:
docker compose exec backend python scripts/compute_predictions.py --force

# Clear Redis cache:
docker compose exec redis redis-cli flushdb

# Check logs:
docker compose logs -f backend
```
