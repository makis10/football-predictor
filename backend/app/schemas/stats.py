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


class EVDataPoint(BaseModel):
    """One date in the cumulative EV / P&L time series.

    EV uses the PURE model probability vs the market price (anchoring + the
    50/50 market-shrinkage were removed 2026-06-17; MARKET_SHRINKAGE=0)."""
    date: str                # ISO date "YYYY-MM-DD"
    daily_ev: float          # expected value added this day (€10 stake)
    daily_pnl: float         # actual P&L this day
    cumulative_ev: float     # running total EV
    cumulative_pnl: float    # running total P&L


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


class MethodologyInfo(BaseModel):
    """Honesty flag: the model changed on the cutoff date (market features +
    anchoring removed → market-independent). Predictions settled BEFORE the
    cutoff were served by the prior anchored model, so all-time accuracy/ROI
    below mixes two methodologies. The UI surfaces this so the numbers aren't
    read as if they all reflect the current model."""
    cutoff: str                  # ISO date the current (market-independent) model began
    settled_before: int          # settled predictions from the prior (anchored) model
    settled_after: int           # settled predictions from the current model


class StatsResponse(BaseModel):
    methodology: Optional[MethodologyInfo] = None
    rolling: RollingAccuracy
    top_picks: Optional[TopPicksStats] = None          # None when no suggested_market data yet
    by_league: list[LeagueBreakdown]
    by_confidence: list[ConfidenceBreakdown]
    by_predicted_outcome: list[PredictedOutcomeBreakdown]
    draw_stats: DrawStats
    btts_stats: Optional[BTTSStats] = None           # None when no lambda data yet
    calibration: list[CalibrationBucket]              # O/U probability buckets
    btts_calibration: list[CalibrationBucket] = []   # BTTS probability buckets
    result_calibration: Optional[ResultCalibration] = None  # 1×2 calibration
    by_model_version: list[ModelVersionStats]
    roi: Optional[ROIStats] = None          # None when no bm odds stored yet
    clv: Optional[CLVStats] = None          # None until suggested bets have closing snapshots
    ev_series: list[EVDataPoint] = []       # empty until bm odds are stored
    computed_at: str                        # ISO timestamp
