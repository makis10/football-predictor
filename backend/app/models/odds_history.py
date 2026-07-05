from __future__ import annotations

from datetime import datetime
from typing import Optional as _Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class OddsHistory(Base):
    """One odds snapshot per poll cycle per match (every 3 hours)."""
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
