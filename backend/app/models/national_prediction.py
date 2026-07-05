from __future__ import annotations

from datetime import datetime
from typing import Optional as _Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class NationalPrediction(Base):
    """
    Predictions for international / national team matches.

    Separate table from club predictions — different feature set,
    different model, different tournaments.
    """
    __tablename__ = "national_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Match identity
    match_date:  Mapped[str]  = mapped_column(String(10), index=True)    # YYYY-MM-DD (local)
    # Full UTC kick-off instant (from The Odds API). Kept separate from
    # match_date because US/Mexico evening games cross midnight in UTC.
    kickoff_utc: Mapped[_Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    home_team:   Mapped[str]  = mapped_column(String(100), index=True)
    away_team:   Mapped[str]  = mapped_column(String(100), index=True)
    tournament:  Mapped[str]  = mapped_column(String(200))
    neutral:     Mapped[bool] = mapped_column(Boolean, default=True)

    # Result probabilities — SERVED values (anchored toward the market when odds
    # are available; equal to raw_* for friendlies / no-odds tournaments).
    home_win_prob: Mapped[float] = mapped_column(Float)
    draw_prob:     Mapped[float] = mapped_column(Float)
    away_win_prob: Mapped[float] = mapped_column(Float)

    # Predicted outcome (argmax of the served probabilities)
    prediction:  Mapped[str]  = mapped_column(String(5))    # "H" / "D" / "A"
    confidence:  Mapped[str]  = mapped_column(String(10))   # HIGH / MEDIUM / LOW

    # Goals / BTTS
    over_2_5_prob: Mapped[float]                = mapped_column(Float)
    btts_prob:     Mapped[_Optional[float]]     = mapped_column(Float, nullable=True)

    # Pure international-model probabilities (pre-anchor) — stable base the odds
    # job re-anchors from, and the source for the EV value gate.
    raw_home_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    raw_draw_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    raw_away_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    raw_over_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    market_anchored: Mapped[bool] = mapped_column(Boolean, default=False)

    # Bookmaker odds (The Odds API) + value-bet signal. NULL for friendlies and
    # any tournament The Odds API doesn't cover.
    bm_home_odds:     Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    bm_draw_odds:     Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    bm_away_odds:     Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    bm_over_odds:     Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    bm_btts_yes_odds: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    bm_btts_no_odds:  Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    num_bookmakers:   Mapped[_Optional[int]]   = mapped_column(Integer, nullable=True)
    ev_score:         Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    suggested_market: Mapped[_Optional[str]]   = mapped_column(String(50), nullable=True)

    # Elo ratings at prediction time (for context / display)
    h_elo: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    a_elo: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)

    # Expected yellow+red cards per team (recency-weighted, from player stats)
    exp_home_cards: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    exp_away_cards: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)

    # Expected corners per team (recency-weighted, from team_match_stats) + a
    # Poisson P(total corners over 9.5).
    exp_home_corners:      Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    exp_away_corners:      Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    corners_over_9_5_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)

    # Correct-score market (Dixon-Coles Poisson over Elo λ)
    most_likely_score: Mapped[_Optional[str]] = mapped_column(String(10), nullable=True)
    top_scores:        Mapped[_Optional[str]] = mapped_column(Text, nullable=True)  # JSON list

    # Actual result (filled in after match is played)
    actual_result:    Mapped[_Optional[str]]   = mapped_column(String(5),  nullable=True)  # "H"/"D"/"A"
    actual_home_goals: Mapped[_Optional[int]]  = mapped_column(Integer,    nullable=True)
    actual_away_goals: Mapped[_Optional[int]]  = mapped_column(Integer,    nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
