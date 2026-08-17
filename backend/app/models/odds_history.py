from __future__ import annotations

from datetime import datetime
from typing import Optional as _Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class OddsHistory(Base):
    """One odds snapshot per poll cycle per match.

    Cadence is tiered, not fixed — poll_odds.py re-prices a match every run
    inside 2 days of kickoff, daily inside 5, and every other day beyond that.
    Note there is no BTTS column here: that market costs one request PER GAME
    on The Odds API, so the poller deliberately does not fetch it."""
    __tablename__ = "odds_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("matches.id", ondelete="CASCADE"), index=True
    )

    home_odds: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    draw_odds: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    away_odds: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    over_odds: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    match: Mapped["Match"] = relationship("Match")
