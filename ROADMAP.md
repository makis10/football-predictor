# Football Predictor — Product Roadmap

> Στόχος: μετάβαση από στατιστικό dashboard σε ολοκληρωμένη AI πλατφόρμα αξίας για pro bettors & B2B.

---

## ✅ Ήδη υλοποιημένο

### ML & Predictions
- XGBoost + LightGBM + MLP soft-vote ensemble (result + O/U) με isotonic calibration
- Draw specialist classifier **ενεργός** με auto-tuned blend α (Brier sweep στο calibration set) — τα Draw suggestions είναι το πιο κερδοφόρο tracked market (+36.6% ROI)
- Pi-Ratings, Poisson, rolling stats, H2H, European fatigue, EWMA, league position, odds movement, referee/card & suspension features — **144 features total**
- **Market-anchored EV gate (2026-06)**: τα suggestions απαιτούν θετικό EV στη market-shrunk πιθανότητα `p′ = (model+market)/2` + kill-switch μόνο σε Home Win/Draw (tracked: Away −29%, GG −33%, Over −24% → disabled)
- **Market-anchored predictions (2026-06)**: τα stored/served probabilities = 0.7·market + 0.3·model όταν υπάρχουν odds — measured: model argmax 49.3% vs market favourite 50.9% (στις διαφωνίες η αγορά σωστή 43.9% vs 33.3%). Το value gate κρατά τα pre-anchor model probs.
- **Strategy vs Baseline ROI**: ο tracker δείχνει χωριστά το ROI των suggested bets (στρατηγική) από το bet-σε-όλα baseline (≈ −γκανιότα by construction)
- **CLV tracking**: μέση απόδοση suggestion vs closing line από `odds_history` — το πιο γρήγορο αξιόπιστο σήμα πραγματικού edge
- **Rolling recalibration** (`scripts/recalibrate.py`): δεύτερο isotonic stage από τα αποθηκευμένα out-of-sample predictions των τελευταίων 365 ημερών — μηνιαίο + μετά από κάθε retrain
- **Reschedule-aware fixture upsert** (`scripts/fixture_upsert.py`): αναβολές ενημερώνουν τη γραμμή in-place (ίδιο id — διατηρούνται predictions/tracking) αντί να μένουν stale "pending"
- Live bookmaker odds injection στο `compute_predictions.py` (Pinnacle fair probs ως features #1 και #2)
- Injury adjustment (serve-time, rule-based, ±14pp max) με shared in-process TTL cache
- Dynamic confidence label (composite formula: result certainty + goals certainty — ποτέ stale από DB)
- Listing card consistency fix (injury-adjusted values + dynamic confidence σε κάθε request)
- Bookmaker odds αποθήκευση στη DB κατά prediction (`bm_home_odds`, `bm_draw_odds`, `bm_away_odds`, `bm_over_odds`)
- **Value Badge**: `suggested_market` + `ev_score` υπολογίζονται στο `compute_predictions.py`, αποθηκεύονται στη DB, εμφανίζονται ως ⚡ badge στις κάρτες
- **Redis caching**: όλα τα in-process dicts αντικαταστάθηκαν με Redis (injuries 30min, analysis 30min, postmortem 24h, stats 6h, league_odds 30min) — fallback σε no-op αν Redis unavailable
- **Odds History**: `odds_history` πίνακας, polling κάθε 3h via launchd, delta arrows ↑/↓ στο Match Details
- **Pi-Rating decay fix**: season-boundary decay (×0.85) εφαρμόζεται πλέον και κατά το inference (train/inference consistency fix)
- **BTTS EV fix**: `_compute_ev()` περιλαμβάνει GG/NG markets σε `suggested_market` / `ev_score` — έλλειπε από το batch pipeline
- **EWMA momentum features** (×6): exponentially weighted goals/points (α=0.3) — πιο πρόσφατα ματς έχουν 3× μεγαλύτερο βάρος
- **League position features** (×3): normalized rank στον τρέχοντα πίνακα βαθμολογίας — NaN για τα πρώτα 2 ματς κάθε σεζόν
- **Odds movement / steam features** (×6): `odds_drift_*` + `is_steam_home/away` από `odds_history` snapshots
- **Dixon-Coles ρ correction**: τα Poisson probabilities διορθώνονται για low-score outcomes (ρ=−0.13) — ήδη ενσωματωμένο στο `poisson.py`
- **Closing-line refresh** (`--force-today`): launchd job στις 15:00 επαναπροβλέπει σημερινά ματς με closing-line odds
- **Pi-Rating Bayesian optimization** script: `scripts/optimize_pi_params.py` με `scipy.differential_evolution` για εύρεση βέλτιστων PI_C/K/BASE/DECAY

### Εθνικές ομάδες (International)
- Ξεχωριστό pipeline (XGBoost+LightGBM, custom Elo K=15–60 ανά tier, 44 features) από το martj42 dataset (49k+ διεθνή ματς από το 1872)
- Draw specialist + isotonic calibration + blend — test accuracy 59.7% (2024+, out-of-sample)
- `national_predictions` πίνακας, `/national` API + σελίδα, 72 WC 2026 + φιλικά predictions
- Bookmaker odds + EV από The Odds API για διοργανώσεις με coverage (WC/EURO/Copa/AFCON/NL/qualifiers) — τα φιλικά δεν έχουν odds source
- **Monte Carlo World Cup simulator** (`scripts/simulate_wc.py`): 20k tournament sims (official R32 template, best-thirds matching), winner/finalist probabilities + σύγκριση με τη sharp αγορά "WC Winner" — σελίδα `/national/world-cup`
- Πλήρες daily/weekly cron wiring (dataset refresh, friendlies re-inject, predictions, odds+EV, actuals, retrain, sim)

### AI & Chatbot
- Claude → **Groq migration** (Llama 3.3 70B, zero cost, <1s latency)
- **Floating AI chatbot** σε όλες τις σελίδες (Groq, context-aware, ελληνική γλώσσα, conversation history)
- Quick-prompt chips, typing indicator, auto-scroll, Enter = send / Shift+Enter = newline
- Match analysis (bookmaker comparison + EV + injuries) με Groq αντί Claude Sonnet

### UI / UX
- **Top 3 AI Picks** section στην αρχική σελίδα (ranking βάσει confidence + max probability)
- **Stats & Accuracy dashboard** (rolling windows / per-league / per-confidence / calibration)
- **ROI Tracker** (flat €10 stake simulation, result market + goals market, αναλυτικό breakdown)
- **Cumulative EV vs P&L Chart** (pure SVG, dual-line, hover interaction — zero npm dependencies)
- Batch prediction engine με live odds injection
- Kickoff times σε Europe/Athens timezone (SSR + browser ταυτόσημα)
- Recent results pagination (sliding 7-day window)
- League filter στην αρχική (Top Picks κρύβεται όταν υπάρχει filter)

---

## 🟡 Phase 1 — "Wow Factor" UI (Προτεραιότητα υψηλή)

### ✅ 1.2 · Value Badge στις κάρτες αγώνων `[Home page]`

⚡ badge απευθείας στην κάρτα όταν υπάρχει positive EV. `ev_score` + `suggested_market` υπολογίζονται στο `compute_predictions.py` και αποθηκεύονται στη DB. 37/39 upcoming matches εμφανίζουν badge.

**Πολυπλοκότητα:** 🟢 Χαμηλή &nbsp;|&nbsp; **Impact:** 🔥🔥🔥

---

### ✅ 1.4 · AI Post-Mortem `[Recent Results page]`

Κουμπί "Γιατί χάθηκε;" στα λάθος predictions. Το LLM (Groq) εξηγεί πιθανούς λόγους με βάση post-match stats: *"Το μοντέλο προέβλεψε Under 2.5, αλλά κόκκινη κάρτα στο 15' άλλαξε τη ροή του αγώνα."* Real match events (goals/cards/penalties με λεπτό + παίκτη) από API-Football, Redis-cached 24h.

**Τεχνική πρόκληση:** Χρειάζεται post-match stats από API-Football (τρώει credits). Το Groq call είναι trivial.

**Πολυπλοκότητα:** 🟠 Μέτρια-Υψηλή &nbsp;|&nbsp; **Impact:** 🔥🔥

---

### ✅ 1.5 · Odds Movement `[Match Details page]`

Βελάκια δίπλα στις αποδόσεις (↑ drifted out · ↓ steam move) στο Bookmaker Comparison panel. `odds_history` πίνακας, polling κάθε 3 ώρες via launchd, delta computation στο `/predictions/{id}/analysis` response.

**Πολυπλοκότητα:** 🔴 Υψηλή &nbsp;|&nbsp; **Impact:** 🔥🔥🔥 (για pro κοινό)

---

## 🔵 Phase 2 — Analytics Depth (Για data-driven παρουσίαση)

### ✅ 2.1 · Interactive League Filter στα Stats `[Stats page]`

Click σε "Serie A" → όλα τα γραφήματα (Calibration, Confidence breakdown, Predicted outcomes, ROI, EV chart) φιλτράρουν για Ιταλία μόνο. Πολύ ισχυρό για B2B demo.

**Υλοποιημένο:** `LeagueFilter` component, `league` query param στο `/stats` endpoint, per-league Redis cache.

**Πολυπλοκότητα:** 🟡 Μέτρια &nbsp;|&nbsp; **Impact:** 🔥🔥

---

### ✅ 2.3 · Odds Filter `[Home page]`

"Δείξε μόνο αγώνες με απόδοση > 1.80" — απαραίτητο για value bettors που δεν παίζουν "μικρά" σημεία. Τώρα που έχουμε τις αποδόσεις αποθηκευμένες, η query είναι τετριμμένη.

**Υλοποιημένο:** `OddsFilter` component, `min_odds` query param στο `GET /matches`, options [Any, 1.50+, 1.70+, 1.90+, 2.20+, 2.50+].

**Πολυπλοκότητα:** 🟢 Χαμηλή &nbsp;|&nbsp; **Impact:** 🔥🔥

---

## 🔴 Phase 3 — Platform & B2B Features

### 3.1 · User Dashboard & Portfolio (SaaS)

Λογαριασμός χρήστη, "Track" αγώνων, προσωπικό ROI ιστορικό, notifications. Μετάβαση σε SaaS model.

**Απαιτεί:** Authentication (NextAuth / Clerk), user DB schema, subscription logic.

**Πολυπλοκότητα:** 🔴 Πολύ Υψηλή &nbsp;|&nbsp; **Impact:** 🔥🔥🔥 (για SaaS)

---

### 3.2 · Live In-Play Predictions

Value bets κατά τη διάρκεια αγώνα (ημίχρονο κ.λπ.). Το 70% του τζίρου των στοιχηματικών είναι live — **το μεγαλύτερο B2B selling point**.

**Απαιτεί:** Real-time data pipeline, model re-inference στα 45', WebSocket frontend, live odds feed.

**Πολυπλοκότητα:** 🔴 Εξαιρετικά Υψηλή &nbsp;|&nbsp; **Impact:** 🔥🔥🔥🔥🔥

---

## Προτεινόμενη σειρά υλοποίησης

| # | Feature | Status | Πολυπλοκότητα | Impact |
|---|---|---|---|---|
| 1 | Top 3 Picks section (1.1) | ✅ Done | 🟢 Χαμηλή | 🔥🔥🔥 |
| 2 | ROI Tracker + store odds (1.3) | ✅ Done | 🟡 Μέτρια | 🔥🔥🔥 |
| 3 | Cumulative EV Graph (2.2) | ✅ Done | 🟡 Μέτρια | 🔥🔥🔥🔥 |
| 4 | Value Badge στις κάρτες (1.2) | ✅ Done | 🟢 Χαμηλή | 🔥🔥🔥 |
| 5 | Odds Filter (2.3) | ✅ Done | 🟢 Χαμηλή | 🔥🔥 |
| 6 | Interactive Stats filters (2.1) | ✅ Done | 🟡 Μέτρια | 🔥🔥 |
| 7 | AI Post-Mortem (1.4) | ✅ Done | 🟠 Μέτρια-Υψηλή | 🔥🔥 |
| 8 | Odds Movement (1.5) | ✅ Done | 🔴 Υψηλή | 🔥🔥🔥 |
| 9 | User Dashboard / SaaS (3.1) | 🔲 | 🔴 Πολύ Υψηλή | 🔥🔥🔥 |
| 10 | Live In-Play (3.2) | 🔲 | 🔴 Εξαιρετικά Υψηλή | 🔥🔥🔥🔥🔥 |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 App Router · Tailwind CSS · TypeScript |
| Backend | FastAPI · Python 3.11 · SQLAlchemy · Alembic |
| ML | XGBoost · scikit-learn · pandas · NumPy |
| Database | PostgreSQL 16 |
| Cache | Redis 7 (128MB LRU) — injuries 30min, analysis 30min, postmortem 24h, stats 6h |
| AI / LLM | Groq (Llama 3.3 70B) — zero cost, <1s latency |
| Odds Data | The Odds API (20k req/month) + odds_history polling every 3h |
| Fixture Data | football-data.org (free tier) |
| Injury Data | API-Football / api-sports.io (100 req/day free) |
| xG Data | understat.com (scraped) |
| Infrastructure | Docker Compose · Cloudflare tunnel (aitipster.net) · macOS launchd (4 services: tunnel, daily@06:00, odds-poll@3h, prematch@15:00) |
