# Changelog

Notable changes to Football Predictor. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); dates are `YYYY-MM-DD`.
History before this file was introduced lives in `git log`.

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
