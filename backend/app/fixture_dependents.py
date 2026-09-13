"""What a fixture row owes the rows that point at it before it is deleted.

Two pipeline paths delete fixture rows, and each settles its dependents first:

  fixture_upsert.prune_vanished — the feed stopped listing an unplayed fixture
    (cancelled, or moved beyond recognition). A user's open bet on it is void,
    as a bookmaker settles a match that is not played; the bet itself survives
    with its match_id nulled (user_bets → matches ON DELETE SET NULL, migration
    0037). Bookmarks and ticket legs cascade away with the row.

  dedupe_fixtures — the same fixture stored twice under two spellings. The bet,
    the bookmark and the accumulator leg belong to the fixture, not to the
    spelling, so they move onto the surviving row. Deleted with the duplicate,
    a leg voided a published ticket that was in fact still live.
"""
from __future__ import annotations

from sqlalchemy import delete, select, update

from backend.app.models.ticket import TicketLeg
from backend.app.models.user import TrackedMatch, UserBet

_BULK = {"synchronize_session": False}


def void_open_bets(db, match_ids) -> int:
    """Settle every unsettled bet on these fixtures as void (stake returned).

    `match_ids` is anything `in_()` accepts: a list, or a SELECT of ids.
    """
    res = db.execute(
        update(UserBet)
        .where(UserBet.match_id.in_(match_ids), UserBet.outcome.is_(None))
        .values(outcome="void", profit=0.0)
        .execution_options(**_BULK)
    )
    return res.rowcount or 0


def move_dependents(db, from_id: int, to_id: int) -> None:
    """Re-point bets, bookmarks and ticket legs from a duplicate fixture row
    onto the row that survives it."""
    db.execute(update(UserBet).where(UserBet.match_id == from_id)
               .values(match_id=to_id).execution_options(**_BULK))
    db.execute(update(TicketLeg).where(TicketLeg.match_id == from_id)
               .values(match_id=to_id).execution_options(**_BULK))
    # (user, match) is unique: a user who bookmarked both rows keeps one.
    both = select(TrackedMatch.user_id).where(TrackedMatch.match_id == to_id)
    db.execute(delete(TrackedMatch)
               .where(TrackedMatch.match_id == from_id, TrackedMatch.user_id.in_(both))
               .execution_options(**_BULK))
    db.execute(update(TrackedMatch).where(TrackedMatch.match_id == from_id)
               .values(match_id=to_id).execution_options(**_BULK))
