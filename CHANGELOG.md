# Changelog

Notable changes to Football Predictor. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); dates are `YYYY-MM-DD`.
History before this file was introduced lives in `git log`.

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
