"""
Pydantic response models for the /stats accuracy-tracking endpoint.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict


class AccuracySlice(BaseModel):
    total: int
    result_correct: int
    goals_correct: int
    both_correct: int
    result_accuracy: float   # 0-1
    goals_accuracy: float    # 0-1
    both_accuracy: float     # 0-1

    # What the same rows would have scored with no model at all.
    #
    # 2026-09-07: the page shipped accuracies with nothing to compare them to,
    # so the frontend invented a threshold and painted anything above 57% green.
    # The always-OVER base rate on the same rows is 57.06%, so "O/U 58%" was
    # rendering GREEN for an edge of +1.3pp that is not distinguishable from a
    # constant (McNemar z = 1.10), while "1x2 50%" rendered YELLOW for +5.7pp
    # over always-HOME that is real (z = 5.18). The colours inverted the truth.
    #
    # These are measured on the slice itself, not assumed: the most common
    # actual result for 1x2, and the actual over-2.5 rate for goals. A reader
    # can subtract them, and so can the accent function.
    result_baseline: float = 0.0   # share of the most common actual result
    goals_baseline: float = 0.0    # actual over-2.5 rate on these rows

    # How many of these rows are national-team predictions rather than club
    # ones. The two models are different pipelines with very different records
    # (national result accuracy 61.1% against the club model's 48.4%), and they
    # are pooled here so a rolling window is not empty every time the clubs are
    # off-season.
    #
    # 2026-09-07: pooling them silently moved the site-wide headline from 48%
    # to 50%, and produced one row — "pure-model, 2026-06-17 to 2026-07-10,
    # 68.8%, n=80" — in which 79 of the 80 matches were internationals, read by
    # a visitor as the market-independent club model's score. The mix is now
    # part of the payload, so any slice can say what it is made of.
    national_total: int = 0


class RollingAccuracy(BaseModel):
    last_7d: AccuracySlice
    last_30d: AccuracySlice
    all_time: AccuracySlice


class LeagueBreakdown(BaseModel):
    league: str
    total: int
    result_correct: int
    goals_correct: int
    both_correct: int
    result_accuracy: float
    goals_accuracy: float
    both_accuracy: float


class ConfidenceBreakdown(BaseModel):
    confidence: str          # high / medium / low
    total: int
    result_correct: int
    result_accuracy: float


class PredictedOutcomeBreakdown(BaseModel):
    predicted: str           # H / D / A / OVER / UNDER
    total: int
    correct: int
    accuracy: float


class DrawStats(BaseModel):
    total_draws: int
    predicted_draws: int     # matches where draw_prob was highest
    correctly_predicted: int
    recall: float            # what fraction of actual draws did we predict as draw?
    precision: float         # of our draw predictions, how many were actually draws?


class BTTSStats(BaseModel):
    total_gg: int            # actual GG matches (both teams scored)
    total_ng: int            # actual NG matches
    predicted_gg: int        # matches predicted GG (btts_prob >= 0.5)
    predicted_ng: int        # matches predicted NG
    correctly_predicted_gg: int
    correctly_predicted_ng: int
    gg_recall: float         # of actual GG, how many did we predict as GG?
    ng_recall: float         # of actual NG, how many did we predict as NG?
    gg_precision: float      # of GG predictions, how many were correct?
    overall_accuracy: float  # total correct / total

    # Always-GG on the same rows. BTTS overall_accuracy has been BELOW this for
    # its whole recorded history (53.9% against 54.8%), which the card could not
    # show because it had no baseline to show it against.
    gg_baseline: float = 0.0

    # Discrimination, which a reliability diagram cannot express.
    #
    # A perfectly calibrated constant plots as a perfect diagonal. Our BTTS
    # probability is very nearly that: AUC 0.5143 on 1,908 rows, 78.7% of all
    # values inside [0.50, 0.60), Brier resolution 0.00097 — 0.39% of the
    # uncertainty in the outcome. The chart said "well calibrated" and a reader
    # reasonably heard "good", so the number that separates those two claims now
    # travels with it. 0.5 is a coin.
    auc: Optional[float] = None
    # Brier resolution: how much of the outcome variance the forecast explains.
    # 0 means every match got the same answer.
    resolution: Optional[float] = None


class TopPicksStats(BaseModel):
    """
    Accuracy stats for the 'Top AI Picks' shown on the homepage:
    top 3 per day, sorted by confidence DESC then max result-prob DESC.
    Mirrors exactly the TopPicks.tsx component logic applied to completed matches.
    """
    total: int                   # total top-pick slots across all completed days (≤ 3/day)
    correct: int                 # how many top picks were correct
    accuracy: float              # correct / total

    # by market type (the highest-prob outcome for each top pick)
    result_picks: int            # top picks where H/D/A was highest
    result_correct: int
    result_accuracy: float
    goals_picks: int             # top picks where O/U 2.5 was highest
    goals_correct: int
    goals_accuracy: float

    avg_pick_prob: float         # mean probability of the top-pick outcome
    vs_overall_accuracy: float   # accuracy delta vs all-time overall accuracy


class CalibrationBucket(BaseModel):
    bucket_min: float        # e.g. 0.40
    bucket_max: float        # e.g. 0.50
    predicted_prob: float    # mean predicted over_2_5_prob in bucket
    actual_rate: float       # fraction that were actually over 2.5
    count: int


class ModelVersionStats(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_version: str
    total: int
    result_accuracy: float
    goals_accuracy: float


class ROIStats(BaseModel):
    """Return-on-investment for flat €10 stake on every model prediction."""
    stake_per_bet: float = 10.0

    # Strategy ROI: bet ONLY the EV-suggested market at its quoted odds.
    # This is the actual value strategy. The per-market blocks below are a
    # "bet everything" model-health baseline — they pay the bookmaker margin
    # on every match by construction and are expected to be ≈ −vig.
    strategy_bets: int = 0
    strategy_staked: float = 0.0
    strategy_return: float = 0.0
    strategy_pnl: float = 0.0
    strategy_roi_pct: float = 0.0

    # Result market (1x2): bet on model's top pick (H / D / A)
    result_bets: int                 # matches where bookmaker odds were available
    result_staked: float             # total € staked
    result_return: float             # total € returned
    result_pnl: float                # net P&L (return - staked)
    result_roi_pct: float            # (pnl / staked) * 100

    # Goals market (O/U 2.5): bet on OVER when model predicts OVER
    goals_bets: int
    goals_staked: float
    goals_return: float
    goals_pnl: float
    goals_roi_pct: float

    # BTTS (GG/NG): bet GG when btts_prob >= 0.5
    btts_bets: int = 0
    btts_staked: float = 0.0
    btts_return: float = 0.0
    btts_pnl: float = 0.0
    btts_roi_pct: float = 0.0

    # Combined (result + goals + btts bets together)
    total_bets: int
    total_staked: float
    total_return: float
    total_pnl: float
    total_roi_pct: float

    # ── Fair-value ROI (vig removed) ────────────────────────────────────────
    # Same bets, but priced at the de-vigged "fair" odds rather than the
    # bookmaker's quoted odds. Measures pure model skill vs the market's TRUE
    # belief, independent of the bookmaker commission. ≈ 0% means the model is
    # as sharp as the fair market line; the gap to the quoted-odds ROI above is
    # exactly the vig you pay. NOT an achievable return (you cannot bet at fair
    # odds anywhere) — it is a model-quality metric.
    #
    # Result & BTTS are de-vigged exactly (all outcome odds stored). O/U uses an
    # assumed 4% two-way overround (under-2.5 odds are not stored).
    fair_available: bool = False
    result_pnl_fair: float = 0.0
    result_roi_fair_pct: float = 0.0
    goals_pnl_fair: float = 0.0
    goals_roi_fair_pct: float = 0.0
    btts_pnl_fair: float = 0.0
    btts_roi_fair_pct: float = 0.0
    total_pnl_fair: float = 0.0
    total_roi_fair_pct: float = 0.0
    goals_fair_is_estimated: bool = True   # O/U fair uses assumed overround


class EVDataPoint(BaseModel):
    """One date in the cumulative EV / P&L time series.

    EV uses the PURE model probability vs the market price (anchoring + the
    50/50 market-shrinkage were removed 2026-06-17; MARKET_SHRINKAGE=0)."""
    date: str                # ISO date "YYYY-MM-DD"
    daily_ev: float          # expected value added this day (€10 stake)
    daily_pnl: float         # actual P&L this day (quoted odds)
    daily_pnl_fair: float = 0.0     # actual P&L this day at de-vigged fair odds
    cumulative_ev: float     # running total EV
    cumulative_pnl: float    # running total P&L (quoted odds)
    cumulative_pnl_fair: float = 0.0  # running total P&L at fair odds (vig removed)


class CLVStats(BaseModel):
    """Closing-line value of the suggested bets.

    CLV% = (odds at suggestion / closing odds − 1) × 100. Consistently positive
    CLV is the fastest statistically-reliable evidence of real edge."""
    bets: int                # suggested bets with a closing snapshot available
    avg_clv_pct: float       # mean CLV across those bets
    beat_close_pct: float    # % of bets that beat the closing line


class ResultCalibration(BaseModel):
    """Per-outcome (H/D/A) calibration buckets for the 1×2 result market."""
    home: list[CalibrationBucket]
    draw: list[CalibrationBucket]
    away: list[CalibrationBucket]


class InjuryAdjustmentStats(BaseModel):
    """Raw vs injury-adjusted accuracy, on the SAME settled matches (only those
    where a significant adjustment was actually served). Measures whether the
    serve-time injury layer helps or hurts — before this, its effect was
    completely unmeasured. Forward-only: adjustments are persisted from
    2026-07-10 on."""
    matches: int
    raw_result_accuracy:  float
    adj_result_accuracy:  float
    raw_goals_accuracy:   float
    adj_goals_accuracy:   float


class RegimeSlice(BaseModel):
    """Accuracy for one model-methodology era. Settled predictions are never
    rewritten, so match_date deterministically assigns each row to the regime
    that produced it — per-regime numbers don't mix methodologies."""
    regime:    str                # short label, e.g. "anchored", "pure-model"
    from_date: Optional[str]      # ISO start (None = beginning of data)
    to_date:   Optional[str]      # ISO end   (None = ongoing)
    stats:     AccuracySlice


class MethodologyInfo(BaseModel):
    """Honesty flag: the model changed on the cutoff date (market features +
    anchoring removed → market-independent). Predictions settled BEFORE the
    cutoff were served by the prior anchored model, so all-time accuracy/ROI
    below mixes two methodologies. The UI surfaces this so the numbers aren't
    read as if they all reflect the current model."""
    cutoff: str                  # ISO date the current (market-independent) model began
    settled_before: int          # settled predictions from the prior (anchored) model
    settled_after: int           # settled predictions from the current model
    regimes: list[RegimeSlice] = []   # per-era accuracy (no methodology mixing)


class StatsResponse(BaseModel):
    methodology: Optional[MethodologyInfo] = None
    rolling: RollingAccuracy
    top_picks: Optional[TopPicksStats] = None          # None when no suggested_market data yet
    by_league: list[LeagueBreakdown]
    by_confidence: list[ConfidenceBreakdown]                    # CLUB only
    by_confidence_national: list[ConfidenceBreakdown] = []      # national (different label semantics)
    by_predicted_outcome: list[PredictedOutcomeBreakdown]
    draw_stats: DrawStats
    btts_stats: Optional[BTTSStats] = None           # None when no lambda data yet
    calibration: list[CalibrationBucket]              # O/U probability buckets
    btts_calibration: list[CalibrationBucket] = []   # BTTS probability buckets
    # Discrimination for the O/U forecast, so its reliability diagram carries
    # the same health warning as the BTTS one. A calibrated constant draws a
    # perfect diagonal on both; only these numbers separate it from a forecast.
    goals_auc: Optional[float] = None
    goals_resolution: Optional[float] = None
    result_calibration: Optional[ResultCalibration] = None  # 1×2 calibration
    by_model_version: list[ModelVersionStats]
    roi: Optional[ROIStats] = None          # None when no bm odds stored yet
    clv: Optional[CLVStats] = None          # None until suggested bets have closing snapshots
    ev_series: list[EVDataPoint] = []       # empty until bm odds are stored
    injury_adjustment: Optional[InjuryAdjustmentStats] = None   # None until adjusted rows settle
    computed_at: str                        # ISO timestamp
