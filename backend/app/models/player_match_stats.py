from __future__ import annotations

from datetime import datetime
from typing import Optional as _Opt

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class PlayerMatchStats(Base):
    """Per-player, per-fixture stats from API-Football (/fixtures/players)."""
    __tablename__ = "player_match_stats"
    __table_args__ = (
        UniqueConstraint("fixture_id", "player_id", name="uq_player_match_stats"),
    )

    id:          Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id:  Mapped[int] = mapped_column(Integer, index=True)
    match_date:  Mapped[str] = mapped_column(String(10), index=True)
    league_id:   Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    team:        Mapped[str] = mapped_column(String(100), index=True)
    opponent:    Mapped[_Opt[str]] = mapped_column(String(100), nullable=True)
    is_home:     Mapped[_Opt[bool]] = mapped_column(Boolean, nullable=True)
    player_id:   Mapped[int] = mapped_column(Integer, index=True)
    player_name: Mapped[str] = mapped_column(String(120))
    position:    Mapped[_Opt[str]] = mapped_column(String(20), nullable=True)
    minutes:     Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    goals:       Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    assists:     Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    shots_total: Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    shots_on:    Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    key_passes:  Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    yellow:      Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    red:         Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    rating:      Mapped[_Opt[float]] = mapped_column(Float, nullable=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
