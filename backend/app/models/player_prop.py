from __future__ import annotations

from datetime import datetime
from typing import Optional as _Opt

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class PlayerProp(Base):
    """Per-fixture player-prop probabilities for a national-team match."""
    __tablename__ = "player_props"
    __table_args__ = (
        UniqueConstraint("national_prediction_id", "player_id", name="uq_player_props"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    national_prediction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("national_predictions.id", ondelete="CASCADE"), index=True)
    match_date:  Mapped[str] = mapped_column(String(10), index=True)
    team:        Mapped[str] = mapped_column(String(100))
    opponent:    Mapped[_Opt[str]] = mapped_column(String(100), nullable=True)
    player_id:   Mapped[int] = mapped_column(Integer)
    player_name: Mapped[str] = mapped_column(String(120))
    exp_minutes: Mapped[_Opt[float]] = mapped_column(Float, nullable=True)
    exp_goals:   Mapped[_Opt[float]] = mapped_column(Float, nullable=True)
    p_score:     Mapped[_Opt[float]] = mapped_column(Float, nullable=True)
    p_sot_1:     Mapped[_Opt[float]] = mapped_column(Float, nullable=True)
    p_sot_2:     Mapped[_Opt[float]] = mapped_column(Float, nullable=True)
    p_assist:    Mapped[_Opt[float]] = mapped_column(Float, nullable=True)
    updated_at:  Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
