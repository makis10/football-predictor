from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, Integer, String, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base

if TYPE_CHECKING:
    from backend.app.models.prediction import Prediction


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    league: Mapped[str] = mapped_column(String(50), index=True)
    season: Mapped[str] = mapped_column(String(10))
    match_date: Mapped[date] = mapped_column(Date, index=True)
    # Scheduled kick-off time (UTC).  NULL for legacy fixtures imported before
    # this column existed — the frontend handles NULL by falling back to the
    # date-only display and treats the match as "in progress" until the date
    # itself is past.
    kickoff_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    # Competition stage, for cups whose season has several formats stacked in
    # one league id: "1st Qualifying Round" / "League Phase - 3" / "Round of 16".
    # NULL for domestic leagues, which are a single round-robin throughout.
    round: Mapped[Optional[str]] = mapped_column(String(60), nullable=True, index=True)
    home_team: Mapped[str] = mapped_column(String(100), index=True)
    away_team: Mapped[str] = mapped_column(String(100), index=True)

    # Result (null for upcoming / not-yet-played)
    home_goals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    away_goals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)  # H/D/A

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # One-to-one: each match has at most one cached prediction.
    # lazy="noload" means it is NOT fetched by default — use selectinload()
    # explicitly in queries where you need it (see routers/matches.py).
    prediction: Mapped[Optional["Prediction"]] = relationship(
        "Prediction", back_populates="match", uselist=False, lazy="noload"
    )
