from __future__ import annotations

from datetime import datetime
from typing import Optional as _Opt

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class TeamMatchStats(Base):
    """Per-team, per-fixture stats from API-Football (/fixtures/statistics)."""
    __tablename__ = "team_match_stats"
    __table_args__ = (
        UniqueConstraint("fixture_id", "team", name="uq_team_match_stats"),
    )

    id:          Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id:  Mapped[int] = mapped_column(Integer, index=True)
    match_date:  Mapped[str] = mapped_column(String(10), index=True)
    league_id:   Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    team:        Mapped[str] = mapped_column(String(100), index=True)
    opponent:    Mapped[_Opt[str]] = mapped_column(String(100), nullable=True)
    is_home:     Mapped[_Opt[bool]] = mapped_column(Boolean, nullable=True)
    corners:     Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    possession:  Mapped[_Opt[float]] = mapped_column(Float, nullable=True)   # percent 0–100
    shots_total: Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    shots_on:    Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    fouls:       Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
