from __future__ import annotations

from datetime import datetime
from typing import Optional as _Opt

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class PlayerClubForm(Base):
    """Current club-season form per player, from API-Football /players.

    Aggregated across all CLUB competitions for the season (national-team
    competitions — friendlies, World Cup, continental national cups — are
    excluded). Used as the empirical-Bayes shrinkage prior for the
    international player-prop rates: a player with few international caps is
    pulled toward his real club scoring rate instead of a flat league prior.
    """
    __tablename__ = "player_club_form"

    player_id:    Mapped[int] = mapped_column(Integer, primary_key=True)
    player_name:  Mapped[str] = mapped_column(String(120))
    club:         Mapped[_Opt[str]] = mapped_column(String(120), nullable=True)
    season:       Mapped[_Opt[int]] = mapped_column(Integer, nullable=True)

    club_minutes: Mapped[int] = mapped_column(Integer, default=0)
    club_goals:   Mapped[int] = mapped_column(Integer, default=0)
    club_assists: Mapped[int] = mapped_column(Integer, default=0)
    club_sot:     Mapped[int] = mapped_column(Integer, default=0)

    # per-90 rates (None when club minutes are below the reliability floor)
    g90:          Mapped[_Opt[float]] = mapped_column(Float, nullable=True)
    sot90:        Mapped[_Opt[float]] = mapped_column(Float, nullable=True)
    ast90:        Mapped[_Opt[float]] = mapped_column(Float, nullable=True)

    updated_at:   Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
