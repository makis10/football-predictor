# Changelog

Notable changes to Football Predictor. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); dates are `YYYY-MM-DD`.
History before this file was introduced lives in `git log`.

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
