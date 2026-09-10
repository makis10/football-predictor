# Changelog

Notable changes to Football Predictor. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); dates are `YYYY-MM-DD`.
History before this file was introduced lives in `git log`.

## 2026-09-10

The home line dropped on 2026-09-09 (the tunnel logged "network is unreachable"
at 07:42) and came back on a new address. API-Football's whitelist refused it.
The 06:00 run on 2026-09-10 caught that at its pre-flight, pushed the alert
naming the address, and skipped every API-Football step; the whitelist was
updated around 10:00. What follows is why the refusal had been quiet everywhere
else, and why whitelisting is now the only manual step.

### Fixed

- **An IP refusal was logged and forgotten everywhere but the daily
  pre-flight.** It is answered HTTP 200 with `{"errors": {"Ip": ...}}`, and
  every fetcher treated it as one more per-league "API error". The odds poll's
  UEFA pairing refresh logged it 167 times between 2026-08-01 and 2026-09-10
  and exited 0 each time; nobody was told. `get_with_retry` now raises
  `IpNotWhitelisted` — `SystemExit(2)`, the pre-flight's own code, which the
  fetchers' `except Exception` cannot swallow — on the first such reply,
  without retrying. Scripts that call `requests.get` themselves go through
  `raise_for_api_football_errors`, which also gives `fetch_odds_apifootball.py`
  the daily-cap exit it never had: it read both refusals as "no market" for
  every fixture and reported a clean run.
- **`run_daily.sh` reads exit 2 from any step as a block**, so a line that
  drops mid-run switches the remaining API-Football steps off and fails the run
  instead of logging its way through them.
- **The odds poll and the World Cup result overlay run the pre-flight first.**
  A test now fails when any scheduled job other than the daily run reaches an
  API-Football script before a pre-flight.
- **`download_xg_apifootball.py` did its whole job at import time.** Its
  argument parsing and download loop sat at module level, so an `import` — a
  routine import check on this very day — started the full 2021–2025 download
  and spent 751 requests before it was killed (it wrote nothing). The body is
  now `main()`, and a test flags module-level loops or argv parsing in every
  API-Football script.
- **The "backup NOT restorable" alert could never fire.** `run_daily.sh` called
  `send_alert` at step 0 but sourced `_alert.sh` only in its alerting section,
  ~700 lines later, so that failure path would have printed "command not found"
  and pushed nothing. It is sourced at the top now, and a test checks that
  every script sources it before its first call.
- **A slow Docker start at 06:00 could cost the whole day.** The once-a-day
  stamp was written before `wait_for_docker`; a run that aborted there marked
  the day as done, and the plist's KeepAlive retry — there for exactly that
  case — then skipped itself. The stamp is written once Docker is ready.
- **The pre-match refresh ran twice on 2026-08-31, 09-01 and 09-07.** Its plist
  carried `KeepAlive {SuccessfulExit: false}`, which launchd treats as
  RunAtLoad: it fired at login (08-31 09:19, 09-07 08:54) and restarted a
  failed run (09-01 15:00 → 15:07), each time deleting and recomputing the
  day's predictions. KeepAlive is removed and the agent reloaded; the script
  also has its own once-a-day stamp, written after Docker is ready. A test pins
  the KeepAlive policy of every plist.
- **/recent listed each page's boundary day twice, and dropped the oldest days
  of a busy week.** Every past-matches window reached one day too far at both
  ends (`>= today-(K+N)`, `<= today-K`), so pages were eight days long and
  overlapped by one — the same formula written out three times in
  `routers/matches.py`. And the page asked for club matches in one request
  capped at 200 rows: 2–8 August holds 222, so 22 matches from 2 August never
  appeared and the page's accuracy summary was computed without them.
  `_past_window` now returns exactly N days with no overlap; the page computes
  one Athens-day window (`lib/recentWindow.ts`) and pages through
  `date_from`/`date_to` until a short page comes back. National results use the
  endpoint's 500-row maximum (the busiest window so far held 174). `?page=abc`
  falls back to page 1 instead of rendering "Could not reach the API".

### Added

- **`scripts/run_af_recovery.sh`** replays exactly what a blocked daily run
  skipped: every step `run_daily.sh` keeps behind the API-Football guard, with
  the same arguments, then dedupe, predictions, the ticket check (it builds only
  a day that has none) and the completeness report. It spends no Odds API
  credits. A test fails when a guarded daily step is missing from it or runs
  with different arguments.
- **`run_watchdog.sh` watches the public address.** Whenever the address is not
  the one API-Football last accepted it asks `/status`, which is free against
  the quota; a refusal pushes one urgent alert per address, carrying the
  address to paste. When the daily run left `.af-recovery-pending` and `/status`
  answers again, it starts the recovery in its own session.

## 2026-09-07

A follow-up audit of the 2026-09-03 work (13 agents: six adversarial verifiers
re-deriving every headline number, six tracing mechanisms, one synthesising).
Half the alarming findings did not survive verification and are recorded below in
corrected form. What did survive was not a modelling failure at all — the model
is roughly where an honest football model sits — but a set of numbers the site
was showing that it could not support, and one live claim that was impossible.

### Fixed

- **Four fixtures were live asserting a 0% chance of Under 2.5.** Bayern v Union
  Berlin, PSV v Heerenveen, Bayern v RB Leipzig, PSV v Willem II, all published
  with `over_2_5_prob = 1.0` and confidence `high`. The model believed none of
  it: their raw outputs were 0.78–0.81. It had already fired twice on settled
  rows — Club Brugge 1-0 Cercle Brugge at p_over = 1.0, and Heerenveen 0-0 Ajax
  at p_btts = 1.0, which alone supplied 0.0366 of a 0.0406 log-loss gap that an
  earlier reading of this audit had blamed on the BTTS model.

  Three links, each of which alone would have prevented it:

  1. `IsotonicRegression` fitted on binary labels puts every member of a PAVA
     block at the block's own mean, so a terminal block whose handful of points
     all went over is worth exactly 1.0. The live goals artefact read
     `0.7468–0.7684 → 0.8333` (five of six) and `0.7698–0.8259 → 1.0000`.
  2. `fit_lambdas_to_probs` rejects `p_over ∈ {0, 1}` and returns `None`, and
     `finalise_probabilities` does `if proj:` — so the coherence projection
     **disabled itself on exactly the impossible values**. A number 1e-4 away was
     repaired; 1.0 sailed through. The guard ran in the breakable direction.
  3. No write path clamped.

  `backend/app/ml/prob_bounds.py` now holds all three guards. `SmoothedIsotonic`
  shrinks each PAVA block toward the base rate with a pseudo-count, so a block
  cannot claim more certainty than its sample supports; `FIT_EPS` stops the
  endpoints regardless; `PROB_EPS` clamps at serving time inside
  `project_probs_coherent`, which is where all three writers converge —
  including `scripts/predict_national.py`, which bypasses
  `finalise_probabilities` entirely and would have missed a guard placed
  upstream.

  Measured walk-forward on 1,460 held-out settled matches (expanding window,
  five folds): uncalibrated raw 0.6776, base-rate constant 0.6826, plain isotonic
  0.6806 — *worse than not calibrating at all* — bounded 0.6759, smoothed 0.6722.
  Smoothed beats plain by 0.0085 at P(better) = 0.903, which does **not** clear
  this project's 0.95 bar and is therefore not claimed as a performance win. The
  argument is that plain isotonic served 1.0000 for a model belief of 0.78 and
  this serves 0.8279. After the retrain the goals calibrator's range is
  0.3495–0.8610 and the BTTS calibrator's 0.2680–0.7257; nothing saturates.

- **`raw_*` meant "unanchored" everywhere except in the column, where it meant
  "uncalibrated".** Those columns held the bare XGBoost outputs. The batch ledger
  fed the value gate `pre_anchor` (calibrated, coherent, unanchored) while the
  API's gate at `routers/predictions.py` read the columns, so the same gate
  computed expected value from two different quantities depending on which path
  answered. Both now store and read the coherent pre-anchor probability.

- **The ticket card printed a chance and a payout whose product implied +64.4%
  expected value** (+192% on longshot) for a product that has returned −23.43%
  over 114 settled slips. Nothing in `tickets.py` compares a probability to a
  price, so no slip could be positive-EV; the +64% was two numbers with opposite
  biases multiplied together — our probabilities, which run high on the legs an
  argmax selects, against real prices carrying a 6.16% margin each.
  `combined_prob` is now the de-vigged market product, so for L real-priced legs
  it equals `overround^-L` by construction. Our own product is stored as
  `model_prob` and shown beside it, where nothing multiplies it. Measured on the
  same 114 slips: model product 24.14% average against 15.79% actual (mean
  absolute error 8.35pp); de-vigged product 14.42% against 15.79% (1.37pp).

- **The public copy misstated the market blend by 28 percentage points.** The
  first paragraph of `/stats` said "43% our model, 57% the bookmakers' line";
  commit 212738e had raised `MARKET_ANCHOR_WEIGHT` to 0.85 three days earlier and
  updated neither the docstring nor the string. The consistency test that should
  have caught it pinned the literal `"57%"` — precisely why it did not. It now
  derives both percentages from the constant, in both languages, and names the
  numbers to write when it fails.

- **The colour coding inverted the truth.** `accentForAccuracy` painted green at
  ≥ 0.57; the always-OVER base rate on the same rows is 0.5706. So "O/U 58%"
  rendered GREEN for +1.3pp that is indistinguishable from a constant (McNemar
  z = 1.10) while "1×2 50%" rendered YELLOW for +5.7pp over always-HOME that is
  real (z = 5.18). Every accuracy figure now travels with the baseline measured
  on its own rows, and the accent follows accuracy-minus-baseline. BTTS turns
  red, correctly: 54.3% against always-GG's 54.7%.

- **National rows inflated the club headline** from 48.40% to 49.68%, and one
  model-history row read "pure-model, 68.8%, n=80" of which 79 were
  internationals. Every slice now reports `national_total`. `/national/stats` had
  no date filter, so the International view advertised 2,632 tracked predictions
  of which 2,424 (92.1%) were backfilled replays — the club endpoint excludes
  exactly those rows and says so in a comment this one had inherited without the
  filter.

- **"Top AI Picks +18% vs overall"** compared a one-outcome hit rate against a
  three-way 1×2 accuracy. The picks' own average stated probability is 66.31% and
  they landed 67.29% (z = 0.40). The card now compares a forecast with what it
  forecast: +1.1pp.

- **The BTTS calibration chart was the only quality evidence offered for a market
  with AUC 0.5143**, 78.7% of every probability inside [0.50, 0.60), and Brier
  skill −0.0064 against a constant. A perfectly calibrated constant plots as a
  perfect diagonal, so "calibrated" and "useful" rendered identically. Both
  charts now print AUC and Brier resolution, and say plainly when a forecast is
  not separating matches. The "bubble size = sample count" legend was false for
  five of six points — the radius saturates at n ≥ 127 — and now describes what
  it does.

- **`btts_prediction` was written by three paths and read by none.** Both display
  surfaces decided for themselves with a hardcoded `>= 0.5` while `train.py`
  re-swept the threshold every retrain and wrote 0.47 to a file nothing read. The
  column is now served through `PredictionResponse` and both surfaces use it;
  `/stats` reads the same threshold, which moves the displayed BTTS accuracy from
  53.88% to 54.27%.

### Changed

- **Over/Under 2.5 and BTTS are now anchored to the de-vigged line at w=0.85**,
  the same weight and the same function as 1×2. They were the only headline
  probabilities in the stack with no market content, and the only two that
  measure at chance: Over 2.5 AUC 0.5222 [0.4505, 0.5955] and BTTS 0.5020
  [0.4547, 0.5502], against the market's 0.5851 and 0.5607. A sweep from w=0.00
  to 1.00 in 0.05 steps found no interior optimum in either market — log-loss
  falls monotonically to the boundary, because a blend of one informative signal
  with an uninformative one is monotone in the informative one's weight. w=0.85
  is the same presentation trade the 1×2 weight records, deliberately the same
  constant so the codebase has one anchor weight rather than three that drift.
  Over 2.5 on the measured window: log-loss 0.6841 → 0.6673, accuracy 0.5581 →
  0.5969, AUC 0.5222 → 0.5811. Coverage is not the obstacle: of upcoming fixtures
  already carrying a 1×2 line, 98.4% carry a two-sided O/U line and 94.4% a BTTS
  pair.

- **`raw_btts_prob` (migration 0034) exists for one line.** Anchoring BTTS
  without it would have been a silent regression rather than an improvement:
  `odds_analysis_service` computes GG/NG expected value as
  `prob × that same book's odds − 1`, so an anchored probability sends every
  GG/NG edge to roughly minus the margin (≈ −0.06) and the value gate quietly
  stops surfacing goals bets. BTTS was the one market with no unanchored column
  to protect it.

- **`under_odds` (migration 0035) on `odds_history`**, so the API's cache-miss
  path can de-vig a totals market. Free: the Odds API returns totals as a pair in
  the response the poll already pays for, and the under was being parsed and
  dropped. BTTS is deliberately still not polled — it is billed one request per
  game, which is the ~1,100 credits/day that docstring records cutting.

### Corrected from the 2026-09-07 first reading

Recorded because the wrong versions were believed for several hours and the
reasoning is worth keeping:

- "Over/Under is worse than a constant" — **refuted as stated**. The constant was
  fitted on the very 258 rows it was scored on (that figure *is* the sample
  entropy, unbeatable by construction), and those 258 are not "the settled rows
  with an O/U line" but the window since `bm_under_odds` was added. On all 1,959
  usable settled rows the model beats an honestly-chosen constant by 0.0093 ±
  0.0037 (t = −2.52). What survives: it trails the de-vigged market by 0.0183 ±
  0.0088 with near-zero discrimination.
- "BTTS is anti-informative — the NG signal points the wrong way" — **refuted**.
  The −1.09pp bucket gap has SE 2.47pp (z = −0.44, p = 0.66) and the AUC point
  estimate is *above* 0.50. The correct word is uninformative.
- "BTTS accuracy is 50.77%" — an artefact of pooling six threshold vintages
  frozen into rows by `ON CONFLICT DO NOTHING`. Recomputed at one threshold:
  53.88%, and 54.27% at the threshold the training run actually chose.
- "The market is overconfident on our selected legs too" — **refuted outright**.
  The comparison used raw `1/odds`, which still carries the margin. De-vigged, 1X
  is fair 72.79% against an actual 71.43%; the market is calibrated on exactly
  the legs the ladder picked. The 294 "1X legs" are also 122 distinct fixtures.
- "−23% ROI proves the model is overconfident" — it is the bookmaker's margin, to
  within 0.08pp of a zero-skill benchmark computed slip-by-slip.
- "Served 1×2 reached market parity" — statistically indistinguishable, and
  mostly because it now *is* the market: measured implied weight median 0.948.
  The unanchored model is +0.0125 behind on the same rows.
- The longshot profile was **not** suspended. Its 66 legs under the old shape
  stated 53.4% and landed 24.2%; the 2026-09-01 rebuild to five legs of
  `CALIBRATED_MARKETS` fixed exactly that — its 21 legs since state 58.4% and
  land 52.4%, against a market price of 54.8%. Suspending it would have been a
  decision taken on retired evidence.

## 2026-09-03

A model audit (`docs/MODEL_AUDIT_2026-09-03.md`) asked one question — can the
draw hit rate go up — and answered it with a measurement rather than an opinion:
no, not meaningfully. On the 2,984 test rows carrying a Pinnacle line the sharp
market's own draw AUC is 0.5690 and ours is 0.5645. We are at 97% of what the
whole market manages, Pinnacle's argmax picks a draw once in 2,984 matches, and
every threshold or value rule we tried lowers accuracy or loses money.

What the audit found instead was a set of assumptions that were correct in June
2026, when this had six August-season leagues with full Pinnacle coverage, and
were never revisited at 27. None of them ever raised an error.

### Fixed

- **The benchmark was scoring the model against itself.** `build_features`
  substitutes our own Poisson probabilities when a Pinnacle line is missing —
  right while market columns were features #1 and #2, dead weight after the
  2026-06-17 market-independence cutoff removed them from every model, and
  therefore invisible. It kept feeding the one consumer left. The
  `market_was_imputed` guard was computed one stage too late, downstream of the
  fill, and reported 50 imputed rows out of 7,427 against a real 4,443. So
  "beat the bookmaker or no edge" printed a win of 1.0246 against 1.0549 while
  the truth on rows with a genuine price is a loss: 1.0047 against 0.9835. The
  flag is now recorded before the fallback, and with no flag present the report
  prints no baseline rather than a flattering one.

- **A quarter of the training set had no league identity.** Championship,
  LeagueOne, Eredivisie and PrimeiraLiga were fitted on from the first commit
  and never one-hot encoded — 24,955 rows reaching the model as the same
  nameless league a Champions League tie gets, so a 27.0%-draw division was
  indistinguishable from a 23.6% one. Every existing guard read
  `ONE_HOT_LEAGUES` and checked it against another table; a league absent from
  the list is never iterated. The new test checks the direction that broke.

- **The split boundaries were literals, and the weekly retrain had stopped
  learning.** Twelve consecutive retrains added 54 training rows between them
  (`training_runs` 35→46) while the test set grew by 246 — two seasons invisible
  to the trees, ten minutes of compute every Monday refitting the same data and
  reporting seed noise as a change in accuracy. They now derive from the season
  with a five-month maturity gate, so the report is never handed a 390-row test
  set. Stated plainly in the comments: a three-way split leaves the trees two
  seasons behind whatever we do, and recency was measured not to be the problem.

- **Spring-autumn leagues were told it was August.** Sweden, Norway, Finland,
  Ireland, Iceland, Latvia, Kazakhstan and both Brazilian divisions play March
  to November, so the shared August boundary landed mid-campaign: the Poisson
  state reset, Pi-Ratings took the season decay and the league table emptied
  with a third of the season left. 27-34% of the evidence behind an August-bucket
  Poisson estimate for those leagues came from a different campaign, against 0%
  for an autumn-spring league, and September was labelled week 4 of a new season
  when it is week 37 of the run-in. The start month is now inferred from each
  league's own fixture calendar — not a list of exceptions, because a list is
  what rotted the last four times a league was added. Pi-Rating decay is tracked
  per league accordingly.

- **Serving never merged xG.** All eight xG features were NaN on 100% of served
  fixtures and filled with the training median, while 43% of the rows the model
  was fitted on carried a real value. Over 969 replayed matches that was about
  70% of the whole train/serve divergence: argmax disagreement 4.33% down to
  1.34%. Parity, not performance — the accuracy difference was inside its own
  standard error.

- **Two serving paths, two different quantities.** `predict_match()`, which
  answers a cache miss on `GET /predictions/{id}`, applied neither the coherence
  projection nor market anchoring and carried a comment asserting the opposite
  directive from the batch path — while writing to the same table. 5.3% of
  stored predictions had mean p_draw 0.296 against 0.254 and picked a draw
  outright 14.9% of the time against 0.4%, on rows where 83% had a usable
  bookmaker line that was simply never applied. Both paths now call one
  `finalise_probabilities()`, and the router reads the latest `odds_history` row
  so it anchors identically at no API cost.

- **Atlético Madrid was rated 1309.** The ClubElo alias table said "Atletico"
  and ClubElo writes "Atlético"; matched literally, the entry had never fired,
  so a club sitting in the table at 1881 was dropping to the uncovered floor.
  Same for AZ Alkmaar, Slovan Bratislava and OFI Crete. Alias matching now folds
  accents and case.

### Changed

- **UEFA ties are priced off ClubElo.** On cross-league ties our own Elo is
  worse than backing the home side — as a picker, ClubElo+80 home advantage
  60.5%, always-home 50.7%, our served argmax 49.3%, our Elo+60 44.3% (n=296).
  `european_blend.py` takes the home:away split from a logistic on the ClubElo
  difference and keeps OUR P(draw), because ClubElo's own draw AUC is 0.399 —
  worse than random, since one strength gap cannot express "these two cancel
  out". Held out on 373 ties: 48.26%/1.0590 → 53.08%/0.9849, paired bootstrap
  +4.81pp accuracy, 95% CI [+0.54, +9.12]. Europa League 39.2% → 55.4%.

- **The draw specialist is switched off (α=0).** It ranks draws worse than the
  result model it was built to help and correlates 0.787 with it. It survived at
  0.20, then 0.35, then 0.45 because each successive tuning objective found a
  flat optimum inside the noise — the last sweep spanned 0.08 of one standard
  error. Selection is now a one-standard-error rule, which prefers the simpler
  model unless the specialist clears the noise floor.

- **Matrix (Dirichlet) scaling replaces one-vs-rest isotonic** on the result
  model. OVR is not a 3-class method: each outcome is fitted blind to the others
  and the renormalisation afterwards is unconstrained. Log-loss 1.0174 → 1.0126
  (all rows) and 1.0047 → 1.0022 (rows with a price). Temperature scaling is the
  control and changes nothing, so the gain is from letting the outcomes correct
  each other. The legacy artefact is still readable, so a process that starts
  before the next retrain keeps working.

- **Ticket legs derived from the 1x2 require a real bookmaker line.** Over 532
  settled legs, draw-carrying legs on unpriced fixtures stated 0.784 and returned
  0.661 (ROI −12.8%) while the same legs on priced fixtures sat at zero. Not a
  calibration failure: the ladder ranks by probability and the unpriced fixtures
  are systematically the exotic ones. Goals and BTTS are unaffected.

### Removed

- **The second-stage rolling recalibration.** It fitted one quantity and
  corrected another — `recalibrate.py` read the served columns, market-anchored
  since 496c842, while inference applied the result before anchoring. Two files
  that never mention each other, coupled through a database column whose meaning
  changed under one of them. It was also losing on its own terms: Over/Under
  log-loss 0.6853 with it against 0.6831 without. Restoring it needs the
  post-blend pre-anchor probability to be stored, not reconstructed.

### Measured dead ends

Recorded so nobody spends a week on them: extending the training window, every
time-decay half-life from one year to none, and dropping pre-2015 rows all land
inside the noise; league draw rates do not persist across seasons (corr 0.189,
against 0.698 for goals); no draw decision rule beats argmax.

## 2026-09-02

### Added
- **A second source of bookmaker odds.** The Odds API plan is 20,000 credits a
  month and it ran out on 13 August. For the eighteen days that followed, no
  upcoming fixture carried a price — so no EV, no value gate, and an
  accumulator ladder that built nothing, because every leg would have been our
  own fair odds. API-Football is already paid for and carries the same three
  markets, so `scripts/fetch_odds_apifootball.py` fills whatever the primary
  source missed. Migration `0033` stores its fixture id, because its `/odds`
  endpoint keys on that and returns no team names. Pinnacle first, not the
  longest price: taking the maximum across books overstates every payout we
  quote against a price no single book offers on the whole slip. Coverage went
  0% → 84% on the day, and is 94% now.

- **Market anchoring at w=0.57.** Removed in June to make the model
  market-independent, restored after `scripts/compare_anchoring.py` replayed
  every settled match holding both our raw probabilities and a de-vigged 1×2:
  accuracy climbed monotonically toward the market, 51.7% → 54.6%, with no
  interior optimum where the model added anything. The site is a betting site,
  so the number beside a pick is the most accurate one we can produce.
  The EV / value gate keeps reading the raw columns — an anchored probability
  compared with the market is the market compared with itself. Disclosed on
  `/stats`, above the accuracy figures rather than below them.

- **A credit meter.** `backend/app/odds_budget.py` records every Odds API
  request with its real cost, which is markets × regions and not one per call.
  The daily run prints the burn per caller. Built because the answer to
  "should I buy a bigger plan" had been guessed at three times.

### Fixed
- **One match, two fixture rows — four separate causes.** A postponement moved
  five ties 10–12 days, past the old 5-day reschedule window. Two GreekSL feeds
  disagreed about a date and both rows survived, so an accumulator carried
  PAOK–Levadiakos twice and multiplied one probability by itself. The Odds API
  listed a fixture at its old and new dates in one response, and the
  double-header guard read that as two real matches. And a fixture that moved
  four months left a row no window could reach. The reschedule window is 14
  days, a corroborating feed defers instead of inserting, matching prefers the
  feed id over any name or date, and `dedupe_fixtures` groups by ordered
  pairing regardless of date distance.

- **The European projections ranked Gibraltar above Milan.** `club_elo()` pools
  every league from a shared 1500 start, and the leagues barely play each
  other, so each is a closed pool where a dominant club climbs against
  opponents whose ratings never had a reason to fall — Lincoln Red Imps 1847
  against Juventus 1837. European simulations now use ClubElo, which is
  maintained across all UEFA federations on one scale. Matching is done inside
  a federation, so a bare "Atletico" filed ESP can no longer reach Atlético
  Mineiro. Coverage of the European field: 95%.

- **A spent quota was indistinguishable from a broken pipeline.** API-Football's
  daily cap made three healthy steps exit 1, which paged and suppressed the
  heartbeat about a condition that clears itself at the reset. Quota now has
  its own exit code. Worse, `fetch_european_fixtures` and
  `fetch_club_friendlies` exited **0 reporting "0 fixtures"** on a quota error,
  and friendlies then handed that empty list to `prune_vanished` — the
  2026-08-09 mass-deletion incident through a different door.

- **Two caches shorter than the job that reads them.** The analysis warm-up runs
  every 50 minutes; BTTS and league odds were both cached for 30, so every pass
  re-bought prices we already held. Together they were 2,000+ credits a day
  against a 645 budget.

- **The chat assistant's 504, and its "no data for today".** It answered "no
  data available" while holding 13 KB of that day's fixtures, because nothing
  in the prompt said what the date was. Separately, Groq's tier caps tokens per
  minute, so the second question inside a minute got a 429 with a 53-second
  Retry-After that the SDK slept on while the gateway gave up at 30.

- **Slips still "running" a fortnight later**, because a leg's fixture had been
  postponed out of the window the slip was offered under. Voided now, not left
  open.

- **A live API key in a public test file.** The redaction test used the real
  key as its fixture — copied out of the log it was written to keep keys out
  of. Rotated; a test now refuses any 32-character hex literal in the suite.

### Changed
- **The `longshot` profile, rebuilt after going 0 for 13.** Its legs were priced
  at a stated 53.7% and landed 25.8%. Measured across all 469 settled legs, the
  miscalibration is not about long prices — it is the DRAW: every market
  containing one is overstated (1X −9.9pp, X2 −14.2pp) while `12`, which
  excludes it, is understated, and the goals markets are near-perfect. The
  profile now takes only markets whose stated probability has held up, and gets
  its length from five legs rather than four longer ones.

- **Tickets and long-term projections are members-only**, with the title race
  three teams deep left public so the route keeps its indexable content. The
  settled record stays public everywhere — it is the only evidence a stranger
  has that any of this works.

- **One daily run per day.** The lock prevented overlap, not repetition, and
  launchd coalescing after sleep fired a second full run — enough to exhaust
  the API-Football day on its own, since one run costs 4,400–5,600 of 7,500.

## 2026-08-08

### Fixed
- **One club filed under two names — 143 clubs.** The top-flight CSVs come from
  football-data.co.uk and the imported second tiers from API-Football, and the
  two disagree about almost every club name (`Freiburg`/`SC Freiburg`,
  `Hamburg`/`Hamburger SV`, `Verona`/`Hellas Verona`). Every club promoted or
  relegated since 2015 was therefore filed twice, and its Elo, form and rolling
  features split **exactly at the division change** — the moment they matter
  most. Adding Sweden2/Romania2/Poland2/BrazilSerieB re-created the same split
  one country group later.
  `scripts/audit_team_identity.py` now runs the rule that decides it: two
  spellings are one club unless they played each other, sit in different
  countries, each played a full season in one table, or were in different
  divisions at once. It runs daily beside the completeness check, because
  **ingestion is what introduces new spellings** — this is upkeep, not a
  one-off. 143 merges in `features._CSV_TEAM_CANON`; 34 look-alikes that are
  genuinely separate clubs recorded in `league_registry.KNOWN_DISTINCT` so the
  audit cannot re-propose fusing them.
- **One name holding two clubs — 7 cases.** `Arsenal` was Arsenal FC *and* FC
  Arsenal Dzyarzhynsk of Belarus; `Olympiakos` was Piraeus *and* Nicosia; also
  `Aris`, `Altay`, `Flamurtari`, `Iskra`, `Rudar`. Their results were fused into
  a single rating, and two of them are clubs we serve predictions for. The
  non-predicted side is renamed at the source
  (`league_registry.NAME_DISAMBIGUATION`), so the displayed name is untouched.
  Montenegro's files also label Rudar Pljevlja "Rudar Velenje" for four
  seasons — a source error; NK Rudar Velenje is Slovenian.
- **`_slug` deleted letters.** NFKD splits a letter from a *combining* mark, but
  ł ø đ ħ ß æ œ carry the stroke in the glyph and decompose to nothing, so they
  were dropped outright: "Wisła Kraków" became `wisakrakow`, whose tail is
  `rakow`. It therefore matched **Raków Częstochowa**, and its own fixture
  matched nothing.
- **The odds matcher confused different clubs.** Containment was a raw substring
  test, so "Aris" sat inside "P-aris-FC" and "AEK" inside "AE-K-ifisia FC"; and
  nothing used the fact that we already hold both clubs by name, so Rangers and
  Angers — who meet in the Europa League — scored 0.92 on difflib. Containment
  is now a run of whole words, and a feed name that *is* one of our clubs can no
  longer be fuzzy-matched onto a different one.
- **An empty odds response was cached for the full 30 minutes.** One read
  timeout blanked the bookmaker panel for every fixture in that league with no
  error logged anywhere — the Eredivisie held zero games while the same request
  by hand returned nine. Empty results now expire in 2 minutes.
- **Blank AI analyses, cached for a day.** `gpt-oss-120b` is a reasoning model:
  its hidden chain of thought is billed against `max_tokens` before a word of
  the answer is emitted. At 450 it spent 448 reasoning and returned
  `finish_reason="length"` with `content=""` — a 200 response, so no error path
  fired, and the empty string was cached for 24 hours. 91 of 184 narratives were
  blank. All three Groq call sites now pass `reasoning_effort="low"` with room
  to answer, and an empty completion is treated as a failure.
- **Seven fixtures that never happened**, three of them upcoming and served with
  confident-looking predictions: `Jagiellonia v Angers` (the tie was against
  Rangers), and three ties stored twice with the sides swapped. Deleted after
  checking each against API-Football. `dedupe_fixtures.py` now keys on the tie
  rather than the ordered pair, so a reversed duplicate is caught on the next
  run.
- **Results that could never be written.** `update_results` matches team names
  with `==`, and the fixture feeds write `Velež`, `Žilina`,
  `Atlètic Club d'Escaldes` with their accents while the history importer strips
  them. Those fixtures could not be scored *and* had no history for the model.
  `migrate_team_names_db.py` folds an accented DB name onto the ASCII spelling
  when that spelling is a club we hold.
- **Merged-away names re-created every morning.** `fetch_upcoming.py` and
  `fetch_greek_fixtures.py` each keep a private `TEAM_MAP` and returned its
  value directly, so `canonical()` never saw it — nine entries still named
  clubs that had been merged away, and every Eredivisie fixture came back as
  "NEC Nijmegen". The two results updaters had the same shape, and six of *their*
  entries pointed at clubs the CSVs have never contained, so those finished
  matches settled nothing.
- **Cached API ids orphaned by a merge.** `club_team_ids.json` is keyed by our
  name, so eight clubs lost their id when the name that held it was folded away
  — no cards, corners or player props for any of them. The DB migration moves
  them now.
- **Wrong-country ids, both paths.** The `/teams?search` fallback was made
  country-aware in an earlier pass; the league-roster sweep was not, and it
  looks names up in a map spanning every club we hold — so La Liga's "Athletic
  Club" (Bilbao) was filed against Brazil's Athletic Club of Série B. The club's
  country now falls back to the training data when the fixture league has none,
  which is the case for a club whose only match is a friendly.
- **`/stats?league=EPL` rendered the international by-tournament table**, putting
  51 AFC Asian Cup games under a Premier League heading. It belongs to the
  all-leagues view; the International filter has its own copy.
- **`status.sh` reported a healthy job as failed.** cloudflared has `KeepAlive`
  and dies whenever the Mac wakes before the network is up — one DNS timeout,
  restarted a second later. Its stale exit code was rendered as ✗ every day.
  Running-now and last-exit are separate now.
- **Two high-severity frontend advisories.** postcss ≤ 8.5.17 (path traversal
  via `sourceMappingURL` auto-loading) → 8.5.26 across all four copies; sharp
  < 0.35.0 (four libvips CVEs) → 0.35.3, which needed `next` 16.2.12 → 16.3.0
  since 16.2 pins `^0.34.5`.

### Added
- `scripts/audit_team_identity.py` — the identity rule, run daily.
- `scripts/check_odds_seam.py` — names the clubs the odds feed spells
  differently, instead of reporting a bare percentage. Uses The Odds API's free
  `/events` endpoint, so it costs no quota.
- `backend/app/ml/league_registry.py` — country and tier per league,
  `NAME_DISAMBIGUATION`, `KNOWN_DISTINCT`.
- `backend/app/display_names.py` — the club's public spelling, applied only at
  the API edge. The stored string stays exactly what the training data holds;
  145 entries (`Goztep` → Göztepe, `Vfl Bochum` → VfL Bochum).
- `scripts/migrate_team_names_db.py`, `scripts/disambiguate_existing_csvs.py`.
- `backend/tests/test_team_name_mapping.py` (22), `test_odds_matching.py` (43),
  `test_llm_calls.py` (9). The odds suite is built around the invariant that no
  two clubs we hold may ever match each other — verified non-vacuous by
  disabling the guard and watching it fail.

### Changed
- Backend suite 176 → **243 tests**; frontend 50.
- Odds coverage on tracked-league predictions 49% → **59%**; unmatched feed
  names 27 → **1** (Akhisarspor, relegated out of our data in 2019).

## 2026-07-27

### Fixed
- **Phantom teams from the 2026/27 intake (22 clubs).** The new-season fixture
  lists arrived spelled the way each feed spells them — `Braga`, `Schalke`,
  `NEC Nijmegen`, `Sittard`, `Málaga`, `AEK Athens FC`, `Aris Thessalonikis`,
  `Olympiakos Piraeus` … — none matching our CSV names. Each became a club with
  no history: Elo 1500, default features, and the real club's league table split
  in two. The Greek Super League was hit hardest (our primary market): all four
  big clubs had duplicate entries carrying 11–13 upcoming fixtures each.
  Root causes were two: `fetch_greek_apifootball.py` never passed a team map to
  its resolver, and each fetcher kept a **private** alias table, so a spelling
  fixed for one feed stayed broken in the others.
  Aliases now live once in `scripts/team_resolver.py::COMMON_ALIASES` and every
  fetcher inherits them (`build_resolver` merges them; the two dict-based
  `map_team()` fetchers fall back to them). 152 rows backfilled, 3 duplicate
  fixtures dropped, affected predictions recomputed. Regression-tested in
  `backend/tests/test_team_aliases.py`.
- **`OFI` / `OFI Crete` split the same club inside the training data** (127 and
  262 matches under two spellings), so its Elo and rolling form were computed
  from a third of its real history — and the membership guard couldn't see it,
  because both names *were* in the CSVs. `load_raw_csvs()` now canonicalises
  team names at load (`_CSV_TEAM_CANON`), giving one club with 389 matches.
  A repo-wide scan confirmed this was the only genuine split — `Atletico GO`/
  `Atletico-MG`, `Bury`/`Shrewsbury` and `Aves`/`Chaves` are distinct clubs and
  stay apart.
- **Groq daily token limit exhausted every afternoon.** The hourly analysis
  warm-up was on course for ~1.2M tokens/day against a 200k free-tier ceiling,
  so the match analysis degraded to "temporarily unavailable" for the rest of
  the day. The LLM narrative now has its own 24 h cache
  (`groq_narrative:{home}:{away}:{probs}`) *inside* `_get_llm_analysis`, keyed
  on the model probabilities: an expired analysis entry recomputes fresh odds
  and EV but reuses the prose. Failures are cached for 5 minutes only, so a
  rate-limited Groq neither sticks nor gets stampeded. Spend dropped to roughly
  one call per fixture per day.

### Added
- **Name guard in every fixture fetcher.** `warn_unknown_teams()` prints a
  `[warn]` when a domestic fixture names a club missing from the training data
  (`[info]` for cup minnows, where no history is expected), and flags "thin
  duplicates" — a name that *is* in the CSVs but holds far less history than a
  near-identical one. `run_daily.sh` counts this run's warnings and raises a
  macOS notification, so a phantom team surfaces the same morning instead of
  weeks later.

## 2026-07-15

### Added
- **League standings with zones** (`backend/app/ml/standings.py`,
  `GET /standings/{league}`): the table is derived from stored results — no new
  table, no API call. Zone sizes come from `LEAGUE_STAKES`, zone *meaning* from
  `TOP_ZONE_LABEL`, because 4th means Champions League in the Premier League,
  a promotion play-off in the Championship and Libertadores in Brazil. UEFA
  competitions use the 2024 format instead: 1–8 direct to the last 16, 9–24
  play-off, 25–36 out.
- **Season projections** (`GET /standings/{league}/projection`): 10k-run Monte
  Carlo from current Elo giving title / Europe / relegation odds, and for UEFA
  competitions champion / final / last-16 odds. Remaining fixtures are *derived*
  as the full double round-robin minus what has been played — we only ingest
  ~60 days ahead, so simulating the stored fixture list would answer nothing.
  The Greek Super League simulates its play-off phase too (position groups with
  carried points). A UEFA competition returns nothing until its league phase is
  drawn: during qualifying the 36-team field does not exist yet.
- **`/projections` page** + nav link: every projectable competition with
  category filters, plus an odds-over-time chart fed by
  `scripts/snapshot_projections.py` (one dated snapshot per competition per day,
  model probability and the bookmaker outright where one is offered).
- **`matches.round`** (migration 0030): the competition stage. A UEFA season
  stacks a qualifying knockout, a league phase and a spring bracket under one
  league id — without the stage they are indistinguishable and a qualifier would
  be counted into the league-phase table.
- **Greek Super League fixtures from API-Football**
  (`scripts/fetch_greek_apifootball.py`, league 197): The Odds API's Greek key
  goes inactive out of season, which left our primary market with no upcoming
  fixtures — and therefore no projection — between seasons.
- **Analysis cache warm-up** (`scripts/warmup_analysis.py`, launchd every
  50 min): a cold `/analysis` costs ~5.8 s (odds + injuries + LLM), a warm one
  ~0.01 s. The warm-up drives the real HTTP endpoints, because the cache key is
  built from probabilities the endpoint rounds after injury adjustment —
  recomputing them in a script would produce a key nothing ever reads.

### Fixed
- Club player props scanned all 55k rows of `player_match_stats` on every
  request, making each club match page take 2.4 s server-side. `load_player_rates`
  now takes a `teams` filter (2.41 s → 0.02 s; identical output).
- Inverted `TEAM_MAP` entries created phantom clubs for the promoted
  Championship cohort (`Coventry City`, `Hull City`, `Sheffield Wednesday`,
  `Preston NE`, `Lincoln City`, `Derby County`, `Sheffield Utd`) — the map's
  direction is API name → CSV name, and the CSVs use the short form.

## 2026-07-08

### Added
- **Club friendlies** (`scripts/fetch_club_friendlies.py`): pre-season /
  exhibition club games (e.g. Olympiakos–Lyon) now appear in the app under
  the new league code `ClubFriendly`. Source: API-Football "Friendlies
  Clubs" (league 667) — none of the existing fixture sources
  (football-data.org free tier, The Odds API) carries club friendlies.
  Team names are resolved against training-data names (static map → slug →
  alias → difflib, ambiguity-safe); fixtures with unknown teams are skipped
  by default (`--allow-unknown` keeps 1-known-side games). The same run
  fills final scores for played friendlies and prunes cancelled ones.
- `confidence_for()` in `backend/app/ml/predict.py`: league-aware confidence
  wrapper. `ClubFriendly` (`LOW_CONFIDENCE_LEAGUES`) is **always served as
  `low` confidence** — friendlies are heavy-rotation exhibition games the
  training distribution doesn't cover. Wired through every path that
  computes the label: `compute_predictions.py`,
  `fetch_european_fixtures.py`, `predict_match()`, and both serve-time
  recompute sites (`routers/matches.py`, `routers/predictions.py`).
- Daily pipeline step **[5b]** in `run_daily.sh`: refresh club friendlies
  (fixtures + results) before the generic prediction step.
- `ClubFriendly` in `VALID_LEAGUES` (API filter) and in the frontend
  `LEAGUES` list ("Club Friendlies" 🤝).

### Notes
- Friendlies have no odds source (The Odds API has no club-friendlies key),
  so their odds/EV columns stay NULL and they can never become value-bet
  suggestions or ledger tickets.

## 2026-07-06

### Added
- **Base-market demotion in the dynamic value gate** (`_market_is_proven` in
  `backend/app/ml/odds_analysis_service.py`). Base markets (Home Win, Draw)
  are no longer exempt from the record: they demote to "watch" early at
  n ≥ 15 settled with ROI ≤ −20% (`DEMOTE_MIN_SAMPLES`, `DEMOTE_ROI_CEIL`),
  and are held to the standard ROI ≥ 0% floor at n ≥ 30. Stateless — a demoted
  market re-enters when its cumulative post-cutoff record recovers.
- `demoted` field + `demote_min_samples` / `demote_roi_ceil_pct` constants in
  the `/admin/market-record` response.
- Red **demoted** status badge and rule copy on `/admin/markets`.
- 8 new gate tests in `backend/tests/test_dynamic_gate.py` (bleeder demotes
  early, small-sample noise survives, full-sample floor applies to base,
  recovery re-entry, non-base promotion unchanged).

### Changed
- `/admin/market-record` now computes proven/demoted status through the same
  shared rule as the live gate (previously duplicated logic that could drift).

### Effect on live data
- **Draw demoted** on the new-model record (0/16 settled post-cutoff, −100%
  ROI — all three misses in the last WC week were draws we suggested against).
  Headline suggestions now come from the remaining proven set; Draw shows as
  watch until its record recovers. Home Win stays (n = 8, still noise) but
  faces the same rule at n ≥ 15.

## 2026-07-05

### Changed
- Public URL moved to **aitipster.net**, served through a Cloudflare tunnel
  (`feat: move to cloudflare`).
