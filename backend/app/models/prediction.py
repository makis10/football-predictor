from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from typing import Optional as _Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("matches.id", ondelete="CASCADE"), unique=True, index=True
    )

    # Win/Draw/Loss probabilities
    home_win_prob: Mapped[float] = mapped_column(Float)
    draw_prob: Mapped[float] = mapped_column(Float)
    away_win_prob: Mapped[float] = mapped_column(Float)

    # Over/Under 2.5 goals
    over_2_5_prob: Mapped[float] = mapped_column(Float)
    goals_prediction: Mapped[str] = mapped_column(String(10))  # "OVER" / "UNDER"

    model_version: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[str] = mapped_column(String(10))        # high/medium/low

    # Bookmaker average decimal odds (with vig) at prediction time — for ROI/EV tracking.
    # NULL when odds were unavailable (league not on The Odds API, or pre-migration rows).
    bm_home_odds: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    bm_draw_odds: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    bm_away_odds: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    bm_over_odds: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)

    # Poisson λ parameters stored at prediction time — used to derive extended
    # stats (O/U 1.5 / 3.5, correct scores, combo markets) at serve-time.
    # NULL for predictions computed before migration 0006.
    poisson_lambda_home: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    poisson_lambda_away: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)

    # Pre-calibration XGBoost raw probabilities — stored for regression diagnostics.
    # NULL for predictions computed before migration 0009.
    raw_home_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    raw_draw_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    raw_away_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    raw_over_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)

    # Bookmaker average BTTS (Both Teams To Score) odds — for ROI tracking.
    # NULL when odds unavailable or pre-migration rows.
    bm_btts_yes_odds: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    bm_btts_no_odds:  Mapped[_Optional[float]] = mapped_column(Float, nullable=True)

    # BTTS classifier probability and prediction — dedicated XGBClassifier.
    # NULL for predictions computed before migration 0013.
    btts_prob:       Mapped[_Optional[float]] = mapped_column(Float,      nullable=True)
    btts_prediction: Mapped[_Optional[str]]   = mapped_column(String(10), nullable=True)

    # Best value-bet market at prediction time (e.g. "Home Win @ 2.10").
    # NULL when no odds were available or no market had positive EV.
    suggested_market: Mapped[_Optional[str]] = mapped_column(String(50), nullable=True)
    # Expected value of the suggested market: model_prob × odds − 1.
    # e.g. 0.08 means 8% edge. NULL when suggested_market is NULL.
    ev_score: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)

    # Last injury-adjusted probabilities actually SERVED for this match (written
    # by the predictions router when a significant adjustment applies). The raw
    # probs above stay untouched; /stats grades raw vs adjusted side-by-side so
    # the adjustment layer's accuracy impact is finally measurable.
    # NULL = no significant adjustment was ever applied (or pre-migration row).
    adj_home_win_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    adj_draw_prob:     Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    adj_away_win_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    adj_over_2_5_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    adj_updated_at:    Mapped[_Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    match: Mapped["Match"] = relationship("Match", back_populates="prediction")
