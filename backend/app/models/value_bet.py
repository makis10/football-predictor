from __future__ import annotations

from datetime import datetime
from typing import Optional as _Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class ValueBet(Base):
    """
    Immutable ticket in the value-strategy ledger.

    Written ONCE, the first time a suggestion appears — i.e. at the earliest
    (softest) odds we saw. Later prediction recomputes never touch it, so CLV
    (ticket odds vs closing line) measures the opening-line edge honestly.
    """
    __tablename__ = "value_bets"
    __table_args__ = (
        UniqueConstraint("source", "match_id", "national_prediction_id", "market",
                         name="uq_value_bets_ticket"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    source:   Mapped[str] = mapped_column(String(10))   # "club" | "national"
    match_id: Mapped[_Optional[int]] = mapped_column(
        Integer, ForeignKey("matches.id", ondelete="CASCADE"), nullable=True)
    national_prediction_id: Mapped[_Optional[int]] = mapped_column(
        Integer, ForeignKey("national_predictions.id", ondelete="CASCADE"), nullable=True)

    market:      Mapped[str]   = mapped_column(String(20))
    odds:        Mapped[float] = mapped_column(Float)
    ev:          Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    model_prob:  Mapped[_Optional[float]] = mapped_column(Float, nullable=True)
    market_prob: Mapped[_Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
