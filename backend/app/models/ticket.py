from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class Ticket(Base):
    """One suggested accumulator, frozen at generation time.

    Frozen on purpose. If the page rebuilt tickets on every request the reader
    would watch legs change under them as odds move, and nothing could ever be
    graded — a "70% hit rate" over slips that were retroactively rewritten is
    not a hit rate. So the daily job writes them once and the endpoint only
    reads. Odds are stored on the leg exactly as offered when the slip was cut.
    """
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("generated_for", "profile", name="uq_tickets_day_profile"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # The day this slip is offered for. One slip per profile per day, so a
    # re-run of the daily job replaces rather than duplicates.
    generated_for: Mapped[date] = mapped_column(Date, index=True)
    profile:       Mapped[str]  = mapped_column(String(20))   # safe/treble/…

    # Denormalised so a settled ticket keeps its original numbers even if the
    # legs are later touched — these are what the reader was actually shown.
    total_odds:    Mapped[float] = mapped_column(Float)
    combined_prob: Mapped[float] = mapped_column(Float)
    num_legs:      Mapped[int]   = mapped_column(Integer)
    # How far ahead we had to look to fill the card, in days. Displayed, so the
    # reader is never surprised by a leg five days out.
    horizon_days:  Mapped[int]   = mapped_column(Integer, server_default="3")

    # NULL while any leg is unsettled; then "won" | "lost".
    outcome:     Mapped[Optional[str]]      = mapped_column(String(10), nullable=True, index=True)
    settled_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    legs: Mapped[list["TicketLeg"]] = relationship(
        "TicketLeg", back_populates="ticket", cascade="all, delete-orphan",
        order_by="TicketLeg.id",
    )


class TicketLeg(Base):
    """One selection on a ticket. Immutable once written."""
    __tablename__ = "ticket_legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("matches.id", ondelete="CASCADE"), index=True)

    market: Mapped[str]   = mapped_column(String(10))   # "1X", "O2.5", "GG", …
    prob:   Mapped[float] = mapped_column(Float)        # our model's number
    odds:   Mapped[float] = mapped_column(Float)        # as offered when cut
    # True when `odds` is our own fair price (1/prob) because no bookmaker
    # market exists for it. Surfaced in the UI — a payout the reader cannot
    # actually get must never be presented as one they can.
    estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # NULL until the match has a result.
    won: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="legs")
