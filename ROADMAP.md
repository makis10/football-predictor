# Football Predictor — Product Roadmap

> Στόχος (αναθεωρημένος 2026-07): διαφανές, δημόσιο AI predictions showcase — έντιμη
> αξιολόγηση (fair-value/de-vig, CLV, dynamic gate με promotion **και** demotion) αντί
> για υποσχέσεις κέρδους. Το B2B/pro-bettor positioning αποσύρθηκε: το tracked record
> του νέου μοντέλου δεν τεκμηριώνει πωλήσιμο edge, και το project λειτουργεί πλέον ως
> portfolio-grade πλατφόρμα (public content, SEO, ops αυτοματισμοί).

---

## ✅ Ήδη υλοποιημένο

### ML & Predictions
- XGBoost + LightGBM + MLP soft-vote ensemble (result + O/U)· **matrix/Dirichlet scaling** για το 1×2 (αντικατέστησε το one-vs-rest isotonic, 2026-09-03), isotonic για τα γκολ
- Draw specialist classifier **απενεργοποιημένος (α=0, 2026-09-03)** — κατατάσσει τις ισοπαλίες χειρότερα από το ίδιο το result model (AUC 0,5280 vs 0,5402)· η επιλογή του α γίνεται πλέον με one-standard-error rule — τα Draw suggestions ήταν το πιο κερδοφόρο tracked market στο ΠΑΛΙΟ μοντέλο (+36.6% ROI)· post-cutoff (2026-06-17) record 0/16, −100% → **demoted 2026-07-06** (βλ. dynamic gate)
- Pi-Ratings, Poisson, rolling stats, H2H, European fatigue, EWMA, league position, referee/card & suspension features — **134 market-independent features** (τα 11 market/odds/steam columns εξακολουθούν να υπολογίζονται αλλά **εξαιρούνται από κάθε trained model** μετά το market-independence cutoff της 2026-06-17· βλ. `RESULT_FEATURE_COLS = FEATURE_COLS − MARKET_DERIVED_COLS`)
- **Market-anchored EV gate (2026-06)**: τα suggestions απαιτούν θετικό EV στη market-shrunk πιθανότητα `p′ = (model+market)/2` + kill-switch μόνο σε Home Win/Draw (tracked: Away −29%, GG −33%, Over −24% → disabled)
- **Dynamic value gate + demotion (2026-06/07, national)**: κάθε qualifying market shadow-tracked στο `value_bets` ledger· promotion σε headline με n ≥ 30 settled & ROI ≥ 0. Base markets (Home/Draw) **υποβιβάζονται** αυτόματα: early στα n ≥ 15 με ROI ≤ −20% (μόνο ξεκάθαροι bleeders), και με το ίδιο ROI floor στα n ≥ 30. Ένας κοινός κανόνας (`_market_is_proven`) για live gate + `/admin/market-record` — status badges στο `/admin/markets`
- **~~Market-anchored predictions (2026-06)~~ → αποσύρθηκε 2026-06-17**: για μια περίοδο τα served probs ήταν 0.7·market + 0.3·model, αλλά αυτό απλώς αντέγραφε την αγορά (κρύβοντας την πραγματική model performance) — καταργήθηκε. **Τα stored/served probabilities είναι πλέον καθαρά model outputs (market-independent).** Η αγορά χρησιμοποιείται μόνο για (α) το EV value-gate και (β) side-by-side σύγκριση στο UI — ποτέ blended μέσα στις σερβιρισμένες πιθανότητες.
- **Strategy vs Baseline ROI**: ο tracker δείχνει χωριστά το ROI των suggested bets (στρατηγική) από το bet-σε-όλα baseline (≈ −γκανιότα by construction)
- **CLV tracking**: μέση απόδοση suggestion vs closing line από `odds_history` — το πιο γρήγορο αξιόπιστο σήμα πραγματικού edge
- ~~**Rolling recalibration** (`scripts/recalibrate.py`)~~ → **αφαιρέθηκε 2026-09-03**: έκανε fit στις *served* (anchored) στήλες και διόρθωνε *unanchored* πιθανότητες. Έχανε και μόνο του (O/U log-loss 0,6853 με, 0,6831 χωρίς). Βλ. Phase 8.8
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
- **Ops**: ημερήσια `pg_dump` backups με rotation, dead-man's-switch heartbeats σε κάθε cron pipeline, per-IP rate limiting στα LLM endpoints, self-hosted umami analytics, GitHub Actions CI (pytest + tsc + vitest + build), 7 launchd services (tunnel, daily, odds-poll, prematch, results-poll)
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

## 🟣 Phase 5 — Parity, βαθμολογίες & μακροχρόνιες προγνώσεις (2026-07)

### ✅ 5.1 · Club ↔ National parity στη σελίδα αγώνα — υλοποιημένο 2026-07-09

Τα δύο match-detail layouts ήταν διαφορετικά και τα club matches δεν είχαν Elo,
expected cards/corners, στατιστικά παικτών. Πλέον **ίδιο layout και στα δύο**, με
όλα τα national-only sections να υπολογίζονται **live** για τα club (καμία
persistence, κανένα nightly step): `club_elo.py` (Elo από τον πίνακα matches),
`club_props.py` (corners/cards από `team_match_stats`), `club_player_props.py`
(scorer/SoT/assist, reuse του national engine· λ από `poisson_lambda_*`).
Ingestion: `fetch_club_team_stats.py` + `fetch_club_player_stats.py` (budget-capped,
idempotent, wired στο daily). Migration 0028 (`yellow_cards`/`red_cards`).

**Πολυπλοκότητα:** 🔴 Υψηλή &nbsp;|&nbsp; **Impact:** 🔥🔥🔥

---

### ✅ 5.2 · Βαθμολογίες με ζώνες — υλοποιημένο 2026-07-15

Πίνακας βαθμολογίας ανά διοργάνωση, **παραγόμενος από τα αποθηκευμένα
αποτελέσματα** (κανένας νέος πίνακας, καμία κλήση API). Οι ζώνες αλλάζουν νόημα
ανά πρωτάθλημα (Champions League / Άνοδος / Libertadores / Ευρώπη) — μέγεθος από
`LEAGUE_STAKES`, σημασία από `TOP_ZONE_LABEL`. Οι ευρωπαϊκές έχουν το format 2024:
**1-8 απευθείας 16άδα · 9-24 play-off · 25-36 εκτός**.
⚠ Τα season labels στη DB ήταν ασυνεπή (`2025/2026` από CSV vs `2025/26` από API
για την ΙΔΙΑ σεζόν) — `_canon_season()` αλλιώς ο πίνακας διχοτομείται.

**Πολυπλοκότητα:** 🟡 Μέτρια &nbsp;|&nbsp; **Impact:** 🔥🔥🔥

---

### ✅ 5.3 · Μακροχρόνιες προγνώσεις (Monte Carlo) — υλοποιημένο 2026-07-15

Πιθανότητες **τίτλου / Ευρώπης / υποβιβασμού** ανά πρωτάθλημα και
**κατάκτησης / τελικού / 16άδας** για τις ευρωπαϊκές, 10k sims από το τρέχον Elo.
Σελίδα `/projections` (φίλτρα κατηγορίας) + nav link.
Δύο σχεδιαστικές αποφάσεις που κρατούν την πρόγνωση έντιμη:
- **Τα υπόλοιπα ματς παράγονται** ως πλήρες διπλό round-robin μείον τα παιγμένα —
  τραβάμε fixtures μόνο 60 μέρες μπροστά, οπότε η DB έχει 37 από τους 380 αγώνες
  της Premier· προσομοίωση αυτών δεν απαντά σε τίποτα.
- **Οι ευρωπαϊκές δεν προβλέπονται στα προκριματικά**: πριν την κλήρωση του league
  phase οι 36 ομάδες δεν υπάρχουν. Ανάβει μόνο του (~Σεπτέμβρης).
Το **GreekSL προσομοιώνει και τα play-offs** (όμιλοι θέσεων 1-4/5-8/9-14 με
μεταφορά βαθμών) — ο τίτλος βγαίνει από τον championship όμιλο, όχι από τη σειρά
της κανονικής περιόδου.

**Πολυπλοκότητα:** 🔴 Υψηλή &nbsp;|&nbsp; **Impact:** 🔥🔥🔥

---

### 🟡 5.4 · Πρόγνωση vs αγορά — μερικώς (υποδομή έτοιμη, αγορά απούσα)

`title_market.py` τραβά de-vigged bookmaker outright ανά διοργάνωση και το
`snapshot_projections.py` γράφει ημερήσιο στιγμιότυπο (μοντέλο + αγορά) →
γράφημα εξέλιξης. **⚠ Το The Odds API δεν προσφέρει league-title outrights στο
τρέχον plan** (τα base keys γυρίζουν 422 σε `markets=outrights`), οπότε σήμερα
εμφανίζεται μόνο η γραμμή του μοντέλου. Ανάβει μόνη της αν/όταν δοθεί η αγορά.

**Πολυπλοκότητα:** 🟢 Χαμηλή &nbsp;|&nbsp; **Impact:** 🔥🔥 (όταν υπάρξει feed)

---

### ✅ 5.5 · Name guard σε όλους τους fetchers — υλοποιημένο 2026-07-15/27

Το επαναλαμβανόμενο **phantom-team bug** (ίδιος σύλλογος με δύο ονόματα → Elo
1500, σπασμένη βαθμολογία) χτύπησε τέσσερις φορές: Leverkusen/Milan, η φουρνιά
του Championship, η ευρωπαϊκή εισροή 2026/27 και οι ελληνικές ομάδες σε τρία
feeds. Πλέον: **ένα** κοινό alias table (`COMMON_ALIASES`) που κληρονομούν όλοι
οι fetchers, `warn_unknown_teams()` που φωνάζει σε κάθε daily run (+ macOS
notification), και canonicalization των CSV ονομάτων στο `load_raw_csvs`.

**Πολυπλοκότητα:** 🟡 Μέτρια &nbsp;|&nbsp; **Impact:** 🔥🔥🔥 (data integrity)

---

### ✅ 5.6 · Δίγλωσσο UI (EN/EL) — υλοποιημένο 2026-07

Πλήρες i18n με `locale` cookie ώστε server και client να αποδίδουν το ίδιο (χωρίς
hydration mismatch): `lib/i18n.ts` (632 κλειδιά), `getServerT()` για server
components, `useT()` για client, flag toggle στο header. Αντικατέστησε την παλιά
σύμβαση «αγγλικά labels / ελληνικές προτάσεις» (`frontend/LANGUAGE.md`).

**Πολυπλοκότητα:** 🟡 Μέτρια &nbsp;|&nbsp; **Impact:** 🔥🔥

---

### ✅ 5.7 · Cache warm-up (latency + κόστος LLM) — υλοποιημένο 2026-07-15/27

Κρύο `/analysis` = ~5.8s, ζεστό = ~0.01s. `warmup_analysis.py` (launchd/50min) +
`warmup_standings.py` (daily) προθερμαίνουν ό,τι είναι ακριβό.
⚠ Το warm-up **χτυπά τα πραγματικά endpoints**: το cache key φτιάχνεται από τις
πιθανότητες όπως τις στρογγυλοποιεί το endpoint (μετά το injury adjustment), οπότε
ανακατασκευή τους σε script θα έφτιαχνε κλειδί που δεν διαβάζει κανείς.
Το Groq narrative έχει **δικό του 24ωρο cache** — αλλιώς το ωριαίο warm-up
ξεπερνούσε το ημερήσιο όριο tokens (~1.2M vs 200k).

**Πολυπλοκότητα:** 🟡 Μέτρια &nbsp;|&nbsp; **Impact:** 🔥🔥🔥 (UX + κόστος)

---

## 🟤 Phase 6 — Ταυτότητα συλλόγων & odds seam (2026-08)

Δεν ήταν σχεδιασμένη φάση. Ξεκίνησε από μία ερώτηση — «γιατί κάποιοι αγώνες δεν
έχουν αποδόσεις;» — και αποκάλυψε ότι το **όνομα ομάδας** ήταν αδύναμο σημείο σε
όλο το pipeline: Elo, φόρμα, ids, fixtures και αποδόσεις κλειδώνουν πάνω σε ένα
σκέτο string που τέσσερα feeds το γράφουν τέσσερις διαφορετικούς τρόπους.

### ✅ 6.1 · Κανόνας ταυτότητας + καθημερινό audit — υλοποιήθηκε 2026-08-02→08

- `scripts/audit_team_identity.py`: **μία ομάδα ή δύο;** έπαιξαν μεταξύ τους →
  δύο· άλλη χώρα → δύο· πλήρης σεζόν η καθεμία στον ίδιο πίνακα → δύο· ίδια
  σεζόν, άλλη κατηγορία → δύο· αλλιώς μία με δύο γραφές.
- **143 συγχωνεύσεις** στο `_CSV_TEAM_CANON` — κάθε σύλλογος που ανέβηκε ή έπεσε
  κατηγορία από το 2015 ήταν καταχωρημένος δύο φορές, με το Elo και τη φόρμα του
  κομμένα **ακριβώς** στην αλλαγή κατηγορίας.
- **34 look-alikes** στο `KNOWN_DISTINCT` — χρεοκοπημένος σύλλογος και ο διάδοχός
  του μοιάζουν πανομοιότυποι με feed split· κρίνονται με ιστορία συλλόγου, όχι
  με τον κανόνα.
- **7 ονόματα που κρατούσαν δύο συλλόγους** (Arsenal, Olympiakos, Aris, Altay,
  Flamurtari, Iskra, Rudar) — μετονομασία της μη-προβλεπόμενης πλευράς στην πηγή.
- Τρέχει **καθημερινά** στο `run_daily.sh`: κάθε νέο import ξαναδημιουργεί τα
  splits, οπότε είναι συντήρηση, όχι μία φορά.

### ✅ 6.2 · Odds seam — υλοποιήθηκε 2026-08-07

- `scripts/check_odds_seam.py`: **ονομάζει** τους συλλόγους που το feed γράφει
  αλλιώς, αντί για σκέτο ποσοστό. Χρησιμοποιεί το δωρεάν `/events`, μηδέν quota.
- Ξεχωρίζει τρεις αιτίες που απ' έξω φαίνονται ίδιες: δεν υπάρχει αγορά · δεν
  άνοιξαν ακόμα οι μπουκ · αστοχία ονόματος (η μόνη ενεργήσιμη).
- Άστοχα ονόματα **27 → 1**· κάλυψη αποδόσεων 49% → **59%**.

### ✅ 6.3 · Επίπεδο εμφάνισης — υλοποιήθηκε 2026-08-03

- `app/display_names.py`: 145 σωστές δημόσιες γραφές (Göztepe, Beşiktaş,
  VfB Stuttgart, Rayo Vallecano), **μονόδρομες** και **μόνο στην άκρη του API**.
- Το αποθηκευμένο string μένει ό,τι έχει το training data — μετονομασία του
  κλειδιού θα σήμαινε ταυτόχρονη επανεγγραφή 800 CSV, id cache και fixtures.

### ✅ 6.4 · Δίχτυα ασφαλείας — υλοποιήθηκαν 2026-08-04→08

- Backend suite **176 → 243**. Κεντρική αναλλοίωτη: *κανένας από τους συλλόγους
  που κρατάμε δεν επιτρέπεται να ταιριάξει με άλλον* — επαληθευμένη ότι **δεν
  είναι κούφια** (απενεργοποίηση του guard → 5 αποτυχίες).
- `test_llm_calls.py`: κάθε κλήση Groq περνά `reasoning_effort`, `max_tokens ≥
  600`, και δεν διαβάζει `.content.strip()` κατευθείαν — 91 από 184 αναλύσεις
  έβγαιναν κενές και αποθηκεύονταν για μια μέρα.
- `dedupe_fixtures.py` κλειδώνει στην **αναμετρηση**, όχι στο ζεύγος με σειρά.
- `migrate_team_names_db.py`: μετά από κάθε merge — fixture rows, accent folds,
  cached API ids.

### 🔜 6.5 · Τι μένει

| # | Θέμα | Κατάσταση |
|---|---|---|
| 1 | **7 σύλλογοι χωρίς props** (`Kasimpasa`, `Stoke`, `Odense`, `Oud-Heverlee Leuven`, `SJK`, `TPS`, `Waasland-Beveren`, `Widzew Lodz`) — το API-Football δεν τους δένει με το όνομά μας· θέλουν `NAME_OVERRIDES` ένα-ένα | 🟡 Ανοιχτό |
| 2 | **Δυναμική IP** — το API-Football είναι IP-whitelisted και η IP αλλάζει· το pre-flight το πιάνει και στέλνει ntfy alert, αλλά το whitelist είναι χειροκίνητο | 🟡 Ανοιχτό (μετριασμένο) |
| 3 | **`caffeinate`** — ο Mac κοιμάται στις 06:00 και το launchd μεταθέτει το daily· 30 λεπτά δουλειάς γίνονται 3,5 ώρες σε σπασμένα κομμάτια | ⛔ Απορρίφθηκε από τον χρήστη |
| 4 | **Rotation στα logs του tunnel** — 11 MB stderr, 7 MB stdout, χωρίς rotation | 🟡 Ανοιχτό (ακίνδυνο) |
| 5 | **Off-machine backups** — ο μόνος εναπομείνας κίνδυνος ολικής απώλειας | 🟡 Ανοιχτό |

---

---

## 🔵 Phase 7 — Δύο πηγές, αγκύρωση & πραγματικό κόστος (2026-08→09)

Η φάση ξεκίνησε από μία διακοπή: στις **13 Αυγούστου** τελείωσαν τα credits του
Odds API και για **δεκαοκτώ μέρες** κανένας αγώνας δεν είχε τιμή γραφείου —
άρα ούτε EV, ούτε value gate, ούτε δελτία. Ό,τι ακολούθησε είναι συνέπειες
αυτού, και των μετρήσεων που έγιναν επειδή δεν είχαμε άλλη επιλογή.

### ✅ 7.1 · Δεύτερη πηγή αποδόσεων — υλοποιήθηκε 2026-08-19

`scripts/fetch_odds_apifootball.py`, migration `0033` (`matches.api_fixture_id`).
Το `/odds` του API-Football κλειδώνει σε fixture id και δεν επιστρέφει ονόματα,
οπότε χωρίς το id δεν υπήρχε τίποτα να ταιριάξει. **Pinnacle πρώτο, όχι η
μεγαλύτερη απόδοση** — το max ανά εταιρία φουσκώνει κάθε πληρωμή απέναντι σε
τιμή που καμία μόνη εταιρία δεν δίνει για ολόκληρο το δελτίο.
Κάλυψη **0% → 84%** την ίδια μέρα, **94%** σήμερα.

### ✅ 7.2 · Μετρητής credits — υλοποιήθηκε 2026-08-19

`backend/app/odds_budget.py` + `scripts/odds_budget_report.py`, στο daily.
Χτίστηκε επειδή το ερώτημα «να αγοράσουμε μεγαλύτερο πλάνο;» είχε απαντηθεί
**τρεις φορές με εκτίμηση**. Οι αρνημένες κλήσεις αναφέρονται χωριστά από τις
χρεωμένες — αλλιώς μια διακοπή διαβάζεται ως υπέρβαση.

### ✅ 7.3 · Αγκύρωση στην αγορά, w=0.57 — υλοποιήθηκε 2026-09-01

`scripts/compare_anchoring.py` σε κάθε κριμένο αγώνα με raw πιθανότητες **και**
de-vigged 1×2: **51,7% → 54,6%**, μονότονα προς την αγορά, χωρίς εσωτερικό
βέλτιστο. Το EV/value gate διαβάζει τις `raw_*` στήλες — αγκυρωμένη πιθανότητα
συγκρινόμενη με την αγορά είναι η αγορά με τον εαυτό της. Δηλωμένο στο `/stats`
**πάνω** από τα νούμερα ακρίβειας.

### ✅ 7.4 · Cross-league Elo για τις ευρωπαϊκές — υλοποιήθηκε 2026-09-01

`backend/app/ml/clubelo_ratings.py`. Το δικό μας Elo έβαζε το Λίνκολν
Γιβραλτάρ (1847) πάνω από τη Γιουβέντους (1837), γιατί κάθε πρωτάθλημα είναι
κλειστή δεξαμενή. Ταίριασμα **μέσα στην ομοσπονδία** — κάλυψη **66% → 95%**.
Ομάδες εκτός ClubElo μοιράζονται μία χαμηλή τιμή αντί να καταταχθούν με τη
μετρική που ήταν λάθος εξαρχής.

### ✅ 7.5 · Δελτία: βαθμονόμηση & gating — υλοποιήθηκε 2026-08-19→09-01

Σε **469** κριμένα σκέλη, η αστοχία δεν είναι οι μεγάλες αποδόσεις — είναι η
**ισοπαλία**: `1X −9,9μ`, `X2 −14,2μ`, ενώ το `12` που την αποκλείει είναι
**+6,7μ** και τα γκολ σχεδόν τέλεια. Το `longshot` (0/13) ξαναχτίστηκε πάνω
στις βαθμονομημένες αγορές. Δελτία και μακροχρόνιες πίσω από login, με την
κούρσα τίτλου δημόσια για το SEO· το κριμένο ρεκόρ μένει πάντα ανοιχτό.

### ✅ 7.6 · Το quota δεν είναι κρασάρισμα — υλοποιήθηκε 2026-08-25

Exit code **4** (`QuotaExhausted`). Πριν, τρία υγιή βήματα έβγαιναν με 1 και
σήμαιναν συναγερμό για κατάσταση που περνάει μόνη της. Και δύο fetchers έβγαιναν
με **0 λέγοντας «0 fixtures»**, με τα φιλικά να δίνουν μετά αυτή την άδεια λίστα
στο `prune_vanished` — το incident της 9/8 από άλλη πόρτα.

### 🔜 7.7 · Τι μένει από τη φάση

| # | Θέμα | Κατάσταση |
|---|---|---|
| 1 | **Καθαρό 24ωρο μέτρησης credits** — δύο διορθώσεις cache (BTTS, league odds) χρειάζονται μια πλήρη μέρα για να επιβεβαιωθούν· η προβολή λέει 13.620/μήνα σε όριο 20.000 | 🟡 Εκκρεμεί μέτρηση |
| 2 | **5 σύλλογοι εκτός ClubElo** (`Ararat-Armenia`, `Inter Club d'Escaldes`, `OFI Crete`, `PAEEK`, `Torreense`) — δεν υπάρχουν upstream, κανένα alias δεν τους φτιάχνει | 🟡 Ανοιχτό (ανυπέρβλητο) |
| 3 | **Το παλιό κλειδί στο git history** — έφυγε από τα αρχεία, μένει στο `1d88897`· το κλειδί περιστράφηκε, οπότε είναι ακίνδυνο, αλλά ο καθαρισμός θέλει force-push σε δημόσιο repo | 🟡 Ανοιχτό (μετριασμένο) |
| 4 | **Ακρίβεια & ρεκόρ δελτίων μετά τις αλλαγές** — 6 σκέλη και 10 αγώνες έχουν κριθεί από τότε· θέλει 2-3 βδομάδες | 🟡 Εκκρεμεί μέτρηση |

---

## 🟠 Phase 8 — Ο έλεγχος του μοντέλου (2026-09-03)

Ξεκίνησε από μία ερώτηση — «μπορούμε να ανεβάσουμε τα ποσοστά στις ισοπαλίες;»
— και η απάντηση ήταν μέτρηση, όχι γνώμη: **όχι ουσιαστικά**. Στις 2.984 test
γραμμές με πραγματική γραμμή Pinnacle, το draw AUC της αγοράς είναι 0,5690 και
το δικό μας 0,5645 — **στο 97% της ικανότητας ολόκληρης της sharp αγοράς**. Το
ίδιο το Pinnacle βάζει ισοπαλία με argmax 1 φορά στις 2.984. Πλήρες σκεπτικό στο
`docs/MODEL_AUDIT_2026-09-03.md`.

Αυτό που βρήκε ο έλεγχος ήταν κάτι άλλο: **μία παραδοχή, εφτά φορές.** Κάθε μία
ήταν σωστή τον Ιούνιο του 2026 με έξι πρωταθλήματα Αυγούστου–Μαΐου, και καμία
δεν ξανακοιτάχτηκε στα 27. Καμία δεν έβγαλε ποτέ exception.

### ✅ 8.1 · Ο benchmark μετρούσε το μοντέλο με τον εαυτό του

Το `features.py` γεμίζει τα `market_*_prob` με τις **δικές μας Poisson** όταν
λείπει το Pinnacle — σωστό όσο οι αποδόσεις ήταν features #1 και #2, νεκρό μετά
το cutoff της 17/6, **και γι' αυτό αόρατο**. Το `market_was_imputed` έτρεχε ένα
στάδιο αργότερα και μετρούσε 50 imputed γραμμές αντί για 4.443. Το «beat the
bookmaker» τύπωνε νίκη 1,0246 vs 1,0549· η αλήθεια είναι **ήττα** 1,0047 vs
0,9835.

### ✅ 8.2 · Το 25% των δεδομένων χωρίς ταυτότητα πρωταθλήματος

Championship, LeagueOne, Eredivisie, PrimeiraLiga — 24.955 γραμμές με όλα τα
league dummies μηδέν, δηλαδή ίδια κωδικοποίηση με ένα ματς CL. Και οι τρεις
guards διάβαζαν το `ONE_HOT_LEAGUES` προς τη **λάθος κατεύθυνση**.

### ✅ 8.3 · Το εβδομαδιαίο retrain δεν μάθαινε τίποτα

Δώδεκα retrains, **+54 γραμμές training** συνολικά, ενώ το test set μεγάλωσε
κατά 246. Τα cutoffs ήταν σταθερές· τώρα κυλούν με τη σεζόν, με πύλη ωριμότητας
5 μηνών. Δηλωμένο ρητά: το three-way split αφήνει τα δέντρα **2 σεζόν πίσω εκ
κατασκευής**, και η παλαιότητα μετρήθηκε ότι δεν ήταν το πρόβλημα.

### ✅ 8.4 · Calendar-year σεζόν

Δέκα πρωταθλήματα (Βραζιλία ×2, Σουηδία ×2, Νορβηγία, Φινλανδία, Ιρλανδία,
Ισλανδία, Λετονία, Καζακστάν) έπαιρναν Αύγουστο. **27–34%** των Poisson
δεδομένων του Αυγούστου έρχονταν από άλλη σεζόν. Ο μήνας έναρξης **συνάγεται
από το ημερολόγιο κάθε πρωταθλήματος** — όχι λίστα εξαιρέσεων, γιατί λίστα είναι
ακριβώς ό,τι σάπισε τις τέσσερις προηγούμενες φορές.

### ✅ 8.5 · Ευρωπαϊκές: τιμολόγηση με ClubElo — **+4,8 μονάδες**

Το δικό μας Elo σε διασυλλογικούς αγώνες είναι **χειρότερο από το «πάντα
γηπεδούχος»** (44,3% vs 50,7%, n=296). Το `european_blend.py` παίρνει το
home:away split από logistic πάνω στο ClubElo και **κρατά τη δική μας p_draw**
(του ClubElo το draw AUC είναι 0,399 — χειρότερο από τυχαίο). Held-out σε 373
αγώνες: 48,26%/1,0590 → 53,08%/0,9849. Europa League **39,2% → 55,4%**.

### ✅ 8.6 · Δύο serving paths, δύο διαφορετικά μεγέθη

Το `predict_match()` δεν έκανε ούτε coherence ούτε anchoring — 5,3% των
αποθηκευμένων γραμμών με mean p_draw 0,296 έναντι 0,254, ενώ το **83%** από
αυτές είχαν διαθέσιμη γραμμή γραφείου. Πλέον καλούν κοινή
`finalise_probabilities()`.

### ✅ 8.7 · Δελτία: τα σκέλη 1×2 θέλουν πραγματική γραμμή

Σε 532 κριμένα σκέλη, όσα περιείχαν ισοπαλία **χωρίς** τιμή δήλωναν 0,784 και
έβγαλαν 0,661 (ROI −12,8%)· τα ίδια **με** τιμή ήταν στο μηδέν. Δεν είναι
βαθμονόμηση — είναι **επιλογή**: η σκάλα κατατάσσει με πιθανότητα και οι αγώνες
χωρίς αποδόσεις είναι οι εξωτικοί.

### ✅ 8.8 · Αφαιρέθηκαν / αντικαταστάθηκαν

- **Draw specialist → α=0.** Κατατάσσει τις ισοπαλίες **χειρότερα** από το
  μοντέλο που υποτίθεται βοηθά (AUC 0,5280 vs 0,5402). Επέζησε σε 0,20 → 0,35 →
  0,45 επειδή κάθε νέο κριτήριο έβρισκε επίπεδο βέλτιστο μέσα στον θόρυβο. Πλέον
  **one-standard-error rule**.
- **Second-stage recalibration → διαγράφηκε.** Έκανε fit σε anchored στήλες και
  διόρθωνε unanchored. Έχανε και μόνο του (O/U 0,6853 vs 0,6831).
- **Matrix/Dirichlet scaling** αντί για one-vs-rest isotonic: −0,005 log-loss.
- **Aliases ClubElo με τόνους**: η Ατλέτικο Μαδρίτης ήταν στο 1309 (floor) ενώ
  υπήρχε στον πίνακα με 1881.

### 🔜 8.9 · Τι μένει

| # | Θέμα | Κατάσταση |
|---|---|---|
| 1 | **Ιστορικό EL/ECL** από API-Football — ο έντιμος τρόπος αντί για το ClubElo υποκατάστατο. Θέλει νέα league codes, one-hot και retrain· τα ματς έχουν τη μία πλευρά με default features | 🟡 Ανοιχτό (σχεδιαστική απόφαση) |
| 2 | **Cross-fitted calibration** — κερδίζει μια σεζόν και 0,0075 log-loss, με 5× κόστος retrain | 🟡 Ανοιχτό (μετρημένο, δεν πάρθηκε) |
| 3 | **BTTS κατώφλι** — 0,52 με macro-F1 δίνει ισορροπία GG/NG· 0,50 δίνει +2,1 μονάδες ακρίβεια αλλά καταρρέει το NG recall στο 6%. Προϊοντική απόφαση | 🟡 Ανοιχτό |
| 4 | **Ensemble** — ένα σκέτο XGBoost αποδίδει όσο το τετραμελές vote· 3× ταχύτερο retrain, μηδέν διαφορά. Να ξαναμετρηθεί μετά το 8.2 | 🟡 Ανοιχτό |
| 5 | **Odds API budget** — η προβολή λέει 29.688/μήνα σε όριο 20.000, αλλά περιλαμβάνει τα σημερινά force-recomputes. Θέλει καθαρό 24ωρο | 🟡 Εκκρεμεί μέτρηση |

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
| 16 | Club↔National parity (5.1) | ✅ Done (2026-07-09) | 🔴 Υψηλή | 🔥🔥🔥 |
| 17 | Βαθμολογίες + ζώνες (5.2) | ✅ Done (2026-07-15) | 🟡 Μέτρια | 🔥🔥🔥 |
| 18 | Μακροχρόνιες προγνώσεις (5.3) | ✅ Done (2026-07-15) | 🔴 Υψηλή | 🔥🔥🔥 |
| 19 | Πρόγνωση vs αγορά (5.4) | 🟡 Υποδομή έτοιμη — λείπει feed | 🟢 Χαμηλή | 🔥🔥 |
| 20 | Name guard παντού (5.5) | ✅ Done (2026-07-27) | 🟡 Μέτρια | 🔥🔥🔥 |
| 21 | Δίγλωσσο UI (5.6) | ✅ Done (2026-07) | 🟡 Μέτρια | 🔥🔥 |
| 22 | Cache warm-up (5.7) | ✅ Done (2026-07-27) | 🟡 Μέτρια | 🔥🔥🔥 |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16.3 App Router · Tailwind CSS 4 · TypeScript |
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
| Infrastructure | Docker Compose · Cloudflare tunnel (aitipster.net) · macOS launchd (7 services: tunnel, daily@06:00, prematch@15:00, odds-poll@3h, results-poll@2h, warmup@50min, watchdog@5min) · GitHub Actions CI |
