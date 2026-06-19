"""
Value-bet ticket ledger — insert-once recording of suggestions.

The opening-line attack: a suggestion is most valuable the FIRST time the
model flags it, while the line is still soft. record_ticket() writes that
moment immutably; the 15:00 closing-line refresh and weekly --force recomputes
may change the stored prediction, but the ticket (market + quoted odds) is
never modified. CLV is then measured ticket-odds vs the closing snapshot.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.app.models.value_bet import ValueBet


def record_ticket(
    db,
    *,
    source: str,                      # "club" | "national"
    market: str,
    odds: float,
    match_id: Optional[int] = None,
    national_prediction_id: Optional[int] = None,
    ev: Optional[float] = None,
    model_prob: Optional[float] = None,
    market_prob: Optional[float] = None,
) -> bool:
    """
    Insert a ticket if this (source, match, market) wasn't flagged before.
    Returns True when a new ticket was written, False when it already existed.
    Never raises on conflict — safe inside larger transactions.
    """
    if not odds or odds <= 1.0:
        return False
    stmt = (
        pg_insert(ValueBet)
        .values(
            source=source,
            match_id=match_id,
            national_prediction_id=national_prediction_id,
            market=market,
            odds=float(odds),
            ev=ev,
            model_prob=model_prob,
            market_prob=market_prob,
        )
        .on_conflict_do_nothing(constraint="uq_value_bets_ticket")
    )
    result = db.execute(stmt)
    return bool(result.rowcount)
