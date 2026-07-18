# Football Predictor — Product Roadmap

> Στόχος (αναθεωρημένος 2026-07): διαφανές, δημόσιο AI predictions showcase — έντιμη
> αξιολόγηση (fair-value/de-vig, CLV, dynamic gate με promotion **και** demotion) αντί
> για υποσχέσεις κέρδους. Το B2B/pro-bettor positioning αποσύρθηκε: το tracked record
> του νέου μοντέλου δεν τεκμηριώνει πωλήσιμο edge, και το project λειτουργεί πλέον ως
> portfolio-grade πλατφόρμα (public content, SEO, ops αυτοματισμοί).

---

## ✅ Ήδη υλοποιημένο

### ML & Predictions
- XGBoost + LightGBM + MLP soft-vote ensemble (result + O/U) με isotonic calibration
- Draw specialist classifier **ενεργός** με auto-tuned blend α (Brier sweep στο calibration set) — τα Draw suggestions ήταν το πιο κερδοφόρο tracked market στο ΠΑΛΙΟ μοντέλο (+36.6% ROI)· post-cutoff (2026-06-17) record 0/16, −100% → **demoted 2026-07-06** (βλ. dynamic gate)
- Pi-Ratings, Poisson, rolling stats, H2H, European fatigue, EWMA, league position, referee/card & suspension features — **134 market-independent features** (τα 11 market/odds/steam columns εξακολουθούν να υπολογίζονται αλλά **εξαιρούνται από κάθε trained model** μετά το market-independence cutoff της 2026-06-17· βλ. `RESULT_FEATURE_COLS = FEATURE_COLS − MARKET_DERIVED_COLS`)
- **Market-anchored EV gate (2026-06)**: τα suggestions απαιτούν θετικό EV στη market-shrunk πιθανότητα `p′ = (model+market)/2` + kill-switch μόνο σε Home Win/Draw (tracked: Away −29%, GG −33%, Over −24% → disabled)
- **Dynamic value gate + demotion (2026-06/07, national)**: κάθε qualifying market shadow-tracked στο `value_bets` ledger· promotion σε headline με n ≥ 30 settled & ROI ≥ 0. Base markets (Home/Draw) **υποβιβάζονται** αυτόματα: early στα n ≥ 15 με ROI ≤ −20% (μόνο ξεκάθαροι bleeders), και με το ίδιο ROI floor στα n ≥ 30. Ένας κοινός κανόνας (`_market_is_proven`) για live gate + `/admin/market-record` — status badges στο `/admin/markets`
- **~~Market-anchored predictions (2026-06)~~ → αποσύρθηκε 2026-06-17**: για μια περίοδο τα served probs ήταν 0.7·market + 0.3·model, αλλά αυτό απλώς αντέγραφε την αγορά (κρύβοντας την πραγματική model performance) — καταργήθηκε. **Τα stored/served probabilities είναι πλέον καθαρά model outputs (market-independent).** Η αγορά χρησιμοποιείται μόνο για (α) το EV value-gate και (β) side-by-side σύγκριση στο UI — ποτέ blended μέσα στις σερβιρισμένες πιθανότητες.
- **Strategy vs Baseline ROI**: ο tracker δείχνει χωριστά το ROI των suggested bets (στρατηγική) από το bet-σε-όλα baseline (≈ −γκανιότα by construction)
- **CLV tracking**: μέση απόδοση suggestion vs closing line από `odds_history` — το πιο γρήγορο αξιόπιστο σήμα πραγματικού edge
- **Rolling recalibration** (`scripts/recalibrate.py`): δεύτερο isotonic stage από τα αποθηκευμένα out-of-sample predictions των τελευταίων 365 ημερών — μηνιαίο + μετά από κάθε retrain
- **Reschedule-aware fixture upsert** (`scripts/fixture_upsert.py`): αναβολές ενημερώνουν τη γραμμή in-place (ίδιο id — διατηρούνται predictions/tracking) αντί να μένουν stale "pending"
- Live bookmaker odds injection στο `compute_predictions.py` — de-vig fair probs για EV/value-gate + UI comparison (**όχι** πλέον model features· ήταν features #1/#2 πριν το 2026-06-17 cutoff)
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
- **Odds movement / steam signals** (×6): `odds_drift_*` + `is_steam_home/away` από `odds_history` snapshots — υπολογίζονται & εμφανίζονται στο Match Details ως ↑/↓ βελάκια, αλλά **εξαιρούνται από το trained model** (market-independent cutoff 2026-06-17)
- **Dixon-Coles ρ correction**: τα Poisson probabilities διορθώνονται για low-score outcomes (ρ=−0.13) — ήδη ενσωματωμένο στο `poisson.py`
- **Closing-line refresh** (`--force-today`): launchd job στις 15:00 επαναπροβλέπει σημερινά ματς με closing-line odds
- **Pi-Rating Bayesian optimization** script: `scripts/optimize_pi_params.py` με `scipy.differential_evolution` για εύρεση βέλτιστων PI_C/K/BASE/DECAY

### Εθνικές ομάδες (International)
- Ξεχωριστό pipeline (XGBoost+LightGBM, custom Elo K=15–60 ανά tier, 49 features) από το martj42 dataset (49k+ διεθνή ματς από το 1872)
- Draw specialist + isotonic calibration + **Elo three-way blend** (fitted σε held-out replay, `blend.json`) — honest held-out result accuracy **61.7%** (n=786, log-loss 0.834)
- `national_predictions` πίνακας, `/national` API + σελίδα, 72 WC 2026 + φιλικά predictions
- Bookmaker odds + EV από The Odds API για διοργανώσεις με coverage (WC/EURO/Copa/AFCON/NL/qualifiers) — τα φιλικά δεν έχουν odds source
- **Monte Carlo World Cup simulator** (`scripts/simulate_wc.py`): 20k tournament sims (official R32 template → πραγματικό bracket μόλις ξεκινούν τα knockouts, best-thirds matching), **conditioned σε όλα τα played group + KO αποτελέσματα** (συγκλίνει deterministic στον τελικό), winner/finalist probs + Golden Boot (squad + availability filtered) + σύγκριση με sharp αγορά — σελίδα `/national/world-cup`, χρονική εξέλιξη odds στο `/national/wc-champion-history`
- Πλήρες daily/weekly cron wiring (dataset refresh, friendlies re-inject, predictions, odds+EV, actuals, retrain, sim)

### Platform, Ops & Showcase (2026-06/07)
- **Public showcase**: όλο το content δημόσιο (gated μόνο personal/admin), SEO live (`robots.ts`, `sitemap.ts`, OpenGraph images), rebrand σε **aitipster.net** (Cloudflare tunnel), prod build μέσω `deploy_frontend.sh`
- **User platform**: NextAuth (Google) login/register/profile, tracked matches (`my-matches`), προσωπικό bet log + ROI (`user_bets`, `my-roi`, `LogBetButton`), in-app `NotificationBell`, feedback
- **Admin suite**: `/admin` (users, market record με promotion/demotion status, feedback)
- **Ops**: ημερήσια `pg_dump` backups με rotation, dead-man's-switch heartbeats σε κάθε cron pipeline, per-IP rate limiting στα LLM endpoints, self-hosted umami analytics, GitHub Actions CI (pytest + tsc + vitest + build), 5 launchd services (tunnel, daily, odds-poll, prematch, results-poll)
- **Email/newsletter**: one-off ενημέρωση χρηστών (rebrand + WC record) μέσω Gmail BCC — αν γίνει τακτικό, θέλει ESP (Resend/SendGrid) με domain auth

### AI & Chatbot
- Claude → **Groq migration** (zero cost, <1s latency) — μοντέλο πλέον **openai/gpt-oss-120b** (το llama-3.3-70b αποσύρεται στο GroqCloud 2026-08-16)
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

### ✅ 3.1 · User Dashboard & Portfolio — υλοποιημένο (χωρίς SaaS)

Λογαριασμός χρήστη (NextAuth/Google), "Track" αγώνων (`tracked_matches` + my-matches),
προσωπικό bet log & ROI (`user_bets` + my-roi), in-app notifications, profile, feedback.
**112 εγγεγραμμένοι χρήστες** (2026-07).

**⛔ Κομμένο — subscription/paid tier:** χωρίς αποδεδειγμένο edge δεν υπάρχει έντιμο
προϊόν συνδρομής. Το platform μένει δωρεάν showcase.

---

### ⛔ 3.2 · Live In-Play Predictions — αποσύρθηκε

Χτίστηκε πάνω στην υπόθεση «B2B selling point» που δεν ισχύει πια: το fair-value
(de-vig) reframe έδειξε ότι το tracked «κέρδος» ήταν vig/anti-selection, όχι edge.
Εξαιρετικά υψηλή πολυπλοκότητα (real-time pipeline, re-inference, WebSockets, live
odds feed) για μηδενική τεκμηριωμένη αξία. Ξαναεξετάζεται μόνο αν κάποιο market
αποδείξει βιώσιμο post-cutoff ROI σε βάθος ολόκληρης σεζόν.

---

## 🟢 Phase 4 — Gate hardening & επόμενα (μετά τις αλλαγές 2026-07)

### ✅ 4.1 · Rolling-window demotion recovery — υλοποιημένο 2026-07-18

Το demotion rule ήταν cumulative-since-cutoff: το Draw (0/16, −100%) δεν ξαναγυρνούσε
ποτέ, όσο κι αν βελτιωνόταν. Πλέον το `proven_markets` αξιολογεί μόνο τα πιο πρόσφατα
`PROVEN_ROLLING_WINDOW=40` settled tickets ανά market (`_window_market_records`), οπότε
τα παλιά αποτελέσματα «γερνάνε» έξω από το παράθυρο και ένα demoted market ανακάμπτει
στη φρέσκια φόρμα του (verified: 25 πρόσφατα winning Draw tickets → re-promote). Το
`/admin/market-record` δείχνει το ίδιο window. Χωρίς νέο table — window aggregation στο query.

**Πολυπλοκότητα:** 🟡 Μέτρια &nbsp;|&nbsp; **Impact:** 🔥🔥 (μακροπρόθεσμη ορθότητα gate)

---

### ✅ 4.2 · Dynamic gate + demotion στο club pipeline — υλοποιημένο 2026-07-18

Το promotion/demotion τρέχει πλέον και στο club path (`proven_markets(db, "club")` —
join `value_bets`↔`matches`, ίδιος `_market_is_proven` + rolling window). Το
`compute_predictions` περνά το δυναμικό set στο `_best_ev_market` και shadow-tracks
**κάθε** qualifying market (proven + watch) όπως το national, ώστε τα unproven markets
να μαζεύουν record για προβιβασμό (verified: 30 winning Over 2.5 tickets → promote).
Admin visibility: `/admin/market-record?source=club` + National/Club toggle στο `/admin/markets`.

**Πολυπλοκότητα:** 🟡 Μέτρια &nbsp;|&nbsp; **Impact:** 🔥🔥🔥 (το club είναι ο κύριος όγκος)

---

### ✅ 4.3 · Promotion/demotion alerting — υλοποιημένο 2026-07-18

Όταν αλλάζει το proven set, `backend/app/ml/gate_alerts.py` κάνει diff έναντι durable
state (`backend/data/gate_state.json` — όχι το 30-λεπτο cache) και εκπέμπει alert:
log πάντα + webhook POST στο `GATE_ALERT_URL` (Discord/Slack/ntfy· no-op όταν unset).
Καλείται και για τα δύο sources μέσα από τα cron pipelines (`fetch_national_odds`,
`compute_predictions`). Πρώτη εκτέλεση = σιωπηλό seed (τίποτα να συγκριθεί).

**Πολυπλοκότητα:** 🟢 Χαμηλή &nbsp;|&nbsp; **Impact:** 🔥

---

### ✅ 4.4 · Post-WC μετάβαση — υλοποιημένο 2026-07-18

Τελικός WC 2026-07-19 → το national pipeline αδρανεί μέχρι τα φθινοπωρινά παράθυρα.
Υλοποιημένα:
- **WC record showcase** (μόνιμο): `/national/wc-review` (DB-computed: result acc, O/U, high-conf slice, highlights) + `/national/wc-champion-history` (JSONL snapshots, model vs sharp market) — banner στην αρχική. Δυναμικό, όχι static snapshot → μένει έντιμο.
- **Phantom-upcoming fix**: το `load_results` πλέον κάνει floor τα NA-score rows σε date ≥ today−2d, ώστε past-dated «ghost» φιλικά (που η πηγή δεν κατέγραψε ποτέ score) να μη re-predict-άρονται κάθε run· janitor στο `update_national_results.py` σβήνει unsettleable predictions > 10 ημερών.
- **Clean-skip σε 0 upcoming**: `predict_national` / `fetch_national_odds` / `update_national_results` / `simulate_wc` επιστρέφουν exit 0 στο κενό διάστημα → κανένα ψευδές heartbeat failure.
- **WC sim freeze**: το `simulate_wc` conditions σε όλα τα played group + knockout αποτελέσματα → μετά τον τελικό συγκλίνει deterministic στον πραγματικό πρωταθλητή.

**Εκκρεμεί (club season prep, Αύγουστος):** fixtures Αυγούστου + retrain με τελικά 25/26 δεδομένα (το 4.2 dynamic club gate έγινε ήδη).

**Πολυπλοκότητα:** 🟢 Χαμηλή &nbsp;|&nbsp; **Impact:** 🔥🔥 (αποφεύγει σιωπηλά κενά)

---

### ✅ 4.5 · ClubElo cold-start fallback — υλοποιημένο 2026-07-18

Ομάδες χωρίς CSV history (promoted, lower-division cup/friendly opponents, qualifier
minnows) έπαιρναν flat Elo 1500 (μέση ομάδα). Το `scripts/fetch_clubelo.py` τραβά
ημερήσιο ClubElo snapshot (~600 clubs → `clubelo.json`) και το `compute_predictions`
(`backend/app/ml/clubelo.py`) σπέρνει πραγματικό Elo για cold-start ομάδες, **mapped
στη δική μας κλίμακα** μέσω linear fit στο overlap (a·clubelo+b, clamped στο range μας)
για αποφυγή out-of-distribution. Το `insufficient_data` μένει True (λείπουν form/xG) —
μόνο το Elo-diff feature βελτιώνεται (verified: Bodø/Glimt vs Arsenal win-prob 0.057→0.123).

**Πολυπλοκότητα:** 🟡 Μέτρια &nbsp;|&nbsp; **Impact:** 🔥🔥

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
| 9 | User Dashboard (3.1, χωρίς SaaS) | ✅ Done | 🔴 Πολύ Υψηλή | 🔥🔥🔥 |
| 10 | Live In-Play (3.2) | ⛔ Αποσύρθηκε | 🔴 Εξαιρετικά Υψηλή | — |
| 11 | Club dynamic gate (4.2) | ✅ Done (2026-07-18) | 🟡 Μέτρια | 🔥🔥🔥 |
| 12 | Post-WC μετάβαση (4.4) | ✅ Done (2026-07-18) | 🟢 Χαμηλή | 🔥🔥 |
| 13 | Rolling-window recovery (4.1) | ✅ Done (2026-07-18) | 🟡 Μέτρια | 🔥🔥 |
| 14 | Gate alerting (4.3) | ✅ Done (2026-07-18) | 🟢 Χαμηλή | 🔥 |
| 15 | ClubElo cold-start fallback | ✅ Done (2026-07-18) | 🟡 Μέτρια | 🔥🔥 |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 App Router · Tailwind CSS · TypeScript |
| Backend | FastAPI · Python 3.13 · SQLAlchemy · Alembic |
| ML | XGBoost · LightGBM · scikit-learn · pandas · NumPy |
| Database | PostgreSQL 16 |
| Cache | Redis 7 (128MB LRU) — injuries 30min, analysis 30min, postmortem 24h, stats 6h, proven_markets 30min |
| AI / LLM | Groq (openai/gpt-oss-120b) — zero cost, <1s latency |
| Odds Data | The Odds API (20k req/month) + odds_history polling every 3h |
| Fixture Data | football-data.org (free tier) · martj42 (international) + API-Football overlay |
| Injury Data | API-Football / api-sports.io (100 req/day free) |
| xG Data | understat.com (scraped) |
| Analytics | self-hosted umami |
| Infrastructure | Docker Compose · Cloudflare tunnel (aitipster.net) · macOS launchd (5 services: tunnel, daily@06:00, odds-poll@3h, prematch@15:00, results-poll) · GitHub Actions CI |
