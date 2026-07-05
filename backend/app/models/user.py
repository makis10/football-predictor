from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from backend.app.database import Base


class User(Base):
    __tablename__ = "users"

    id:               Mapped[int]            = mapped_column(Integer, primary_key=True)
    email:            Mapped[str]            = mapped_column(String(255), nullable=False, unique=True, index=True)
    name:             Mapped[Optional[str]]  = mapped_column(String(255), nullable=True)
    image:            Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
    hashed_password:  Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
    provider:         Mapped[Optional[str]]  = mapped_column(String(50), nullable=True)   # "google" | "credentials"
    provider_id:      Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
    preferred_leagues:Mapped[Optional[str]]  = mapped_column(Text, nullable=True)         # JSON array
    is_admin:         Mapped[bool]           = mapped_column(Boolean, nullable=False, default=False)
    created_at:       Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:       Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    login_count:      Mapped[int]            = mapped_column(Integer, nullable=False, default=0)
    # Bumped (throttled, ~5 min) on any authenticated request — the accurate
    # "last active", unlike last_login_at which only moves on a real sign-in.
    last_seen_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    tracked_matches: Mapped[List[TrackedMatch]] = relationship("TrackedMatch", back_populates="user", cascade="all, delete-orphan")
    bets:            Mapped[List[UserBet]]      = relationship("UserBet",      back_populates="user", cascade="all, delete-orphan")

    def get_preferred_leagues(self) -> List[str]:
        if not self.preferred_leagues:
            return []
        return json.loads(self.preferred_leagues)

    def set_preferred_leagues(self, leagues: List[str]) -> None:
        self.preferred_leagues = json.dumps(leagues)


class TrackedMatch(Base):
    __tablename__ = "tracked_matches"
    __table_args__ = (UniqueConstraint("user_id", "match_id", name="uq_tracked_matches_user_match"),)

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True)
    user_id:    Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    match_id:   Mapped[int]      = mapped_column(Integer, ForeignKey("predictions.match_id", ondelete="CASCADE"), nullable=False)
    tracked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship("User", back_populates="tracked_matches")


class UserBet(Base):
    __tablename__ = "user_bets"

    id:        Mapped[int]            = mapped_column(Integer, primary_key=True)
    user_id:   Mapped[int]            = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    match_id:  Mapped[int]            = mapped_column(Integer, ForeignKey("predictions.match_id", ondelete="CASCADE"), nullable=False)
    market:    Mapped[str]            = mapped_column(String(50), nullable=False)
    odds:      Mapped[float]          = mapped_column(Float, nullable=False)
    stake:     Mapped[float]          = mapped_column(Float, nullable=False, default=1.0)
    outcome:   Mapped[Optional[str]]  = mapped_column(String(20), nullable=True)   # "win" | "loss" | "void" | None
    profit:    Mapped[Optional[float]]= mapped_column(Float, nullable=True)
    placed_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship("User", back_populates="bets")
