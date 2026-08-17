"""
Suggested accumulators ("tickets").

Read-only. The slips themselves are cut once a day by scripts/generate_tickets.py
and frozen in the DB — see models/ticket.py for why rebuilding them per request
would make the track record meaningless.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.cache import CACHE_MISS, cache_get, cache_set
from backend.app.database import get_db
from backend.app.display_names import display_name
from backend.app.ml.tickets import PROFILES
from backend.app.models.match import Match
from backend.app.models.ticket import Ticket, TicketLeg
from backend.app.schemas.ticket import (
    ProfileRecord, SettledTicketsResponse, TicketLegOut, TicketOut, TicketsResponse,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])

# Deliberately NOT rate limited, unlike /matches/export and /predictions/*/analysis.
# Those are expensive per call; this one serves a Redis-cached snapshot of five
# rows that the daily job froze this morning. And a per-IP limit here would be
# actively harmful: SSR reaches the backend server-to-server with no
# X-Forwarded-For, so client_ip() falls back to the socket peer and EVERY
# server-rendered page would share one bucket — the site would throttle itself
# under exactly the traffic a limit is supposed to survive.
#
# Short TTL: the slips are frozen, but `outcome` flips as results land and a
# reader refreshing after full time should see it.
_TTL = 300
STAKE = 1.0   # unit stake; the UI multiplies for display


def _leg_out(leg: TicketLeg, match: Match) -> TicketLegOut:
    return TicketLegOut(
        match_id=leg.match_id, market=leg.market, prob=leg.prob, odds=leg.odds,
        estimated=leg.estimated, won=leg.won,
        league=match.league,
        home_team=display_name(match.home_team),
        away_team=display_name(match.away_team),
        match_date=match.match_date, kickoff_time=match.kickoff_time,
        home_goals=match.home_goals, away_goals=match.away_goals,
    )


def _ticket_out(t: Ticket, matches: dict[int, Match]) -> TicketOut:
    return TicketOut(
        id=t.id, profile=t.profile, generated_for=t.generated_for,
        horizon_days=t.horizon_days, total_odds=t.total_odds,
        combined_prob=t.combined_prob, num_legs=t.num_legs, outcome=t.outcome,
        legs=[_leg_out(l, matches[l.match_id]) for l in t.legs
              if l.match_id in matches],
    )


def _load_matches(db: Session, tickets: list[Ticket]) -> dict[int, Match]:
    ids = {l.match_id for t in tickets for l in t.legs}
    if not ids:
        return {}
    return {m.id: m for m in db.scalars(select(Match).where(Match.id.in_(ids))).all()}


def _record(rows: list[Ticket], profile: str) -> ProfileRecord:
    """Settled record. Return is what the stored odds actually paid — no EV,
    no projection: a ticket either landed or it did not."""
    settled = [t for t in rows if t.outcome in ("won", "lost")]
    won = [t for t in settled if t.outcome == "won"]
    staked = STAKE * len(settled)
    returned = sum(STAKE * t.total_odds for t in won)
    return ProfileRecord(
        profile=profile,
        settled=len(settled),
        won=len(won),
        hit_rate=round(len(won) / len(settled), 4) if settled else 0.0,
        staked=round(staked, 2),
        returned=round(returned, 2),
        roi_pct=round((returned - staked) / staked * 100, 2) if staked else 0.0,
    )


@router.get("", response_model=TicketsResponse)
def current_tickets(db: Session = Depends(get_db)):
    """Today's slips, plus the settled record of every profile so far."""
    cached = cache_get("tickets:current")
    if cached is not CACHE_MISS:
        return TicketsResponse(**cached)

    latest_day = db.scalar(select(Ticket.generated_for).order_by(
        Ticket.generated_for.desc()).limit(1))

    tickets: list[Ticket] = []
    if latest_day:
        tickets = list(db.scalars(
            select(Ticket)
            .options(selectinload(Ticket.legs))
            .where(Ticket.generated_for == latest_day)
            .order_by(Ticket.id)
        ).all())

    matches = _load_matches(db, tickets)

    # Track record over every settled slip ever cut, per profile.
    all_settled = list(db.scalars(
        select(Ticket).where(Ticket.outcome.isnot(None))
    ).all())
    per_profile = [
        _record([t for t in all_settled if t.profile == p.key], p.key)
        for p in PROFILES
    ]

    resp = TicketsResponse(
        generated_for=latest_day,
        horizon_days=tickets[0].horizon_days if tickets else None,
        tickets=[_ticket_out(t, matches) for t in tickets],
        profiles_total=len(PROFILES),
        profiles_built=len(tickets),
        record=[r for r in per_profile if r.settled > 0],
        overall=_record(all_settled, "all"),
    )
    cache_set("tickets:current", resp.model_dump(mode="json"), _TTL)
    return resp


@router.get("/history", response_model=SettledTicketsResponse)
def settled_tickets(
    days: int = Query(30, ge=1, le=180),
    offset_days: int = Query(0, ge=0, le=3650,
                             description="Shift the window back by N days, for paging."),
    db: Session = Depends(get_db),
):
    """Every earlier slip, newest first — the receipts behind the record.

    Deliberately NOT limited to settled slips. A card is cut with a horizon of
    up to seven days, so a slip stays open long after the day it was published:
    on 2026-08-12, with three days of slips on file, not one had finished and a
    settled-only filter returned an empty list. That reads as "there is no
    history" when the truth is "they are still running" — and it hides exactly
    what a reader wants mid-week, which is how the open ones are tracking.

    Today's slips are excluded because they are already the top of the page.
    """
    key = f"tickets:history:{days}:{offset_days}"
    cached = cache_get(key)
    if cached is not CACHE_MISS:
        return SettledTicketsResponse(**cached)

    # Paged by DAY, not by row: slips come in fives, so a row offset would cut
    # a day in half and the reader would meet the same date on two pages.
    today = date.today()
    until = today - timedelta(days=offset_days)
    since = until - timedelta(days=days)
    rows = list(db.scalars(
        select(Ticket)
        .options(selectinload(Ticket.legs))
        .where(Ticket.generated_for >= since)
        .where(Ticket.generated_for < until)
        .order_by(Ticket.generated_for.desc(), Ticket.id)
    ).all())
    matches = _load_matches(db, rows)
    resp = SettledTicketsResponse(
        tickets=[_ticket_out(t, matches) for t in rows])
    cache_set(key, resp.model_dump(mode="json"), _TTL)
    return resp
