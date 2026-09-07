"""store the market's own probability beside ours on tickets and legs

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-07

The ticket card prints a chance of landing next to a payout, and a reader
multiplies them. Built from model probabilities that product was quoting an
average expected value of +64.4% — and +192% on the longshot rung — for a
product that has returned -23.43% over 114 settled slips. Nothing in tickets.py
ever compares a probability to a price, so there was no mechanism by which a
slip could be positive; the +64% was two numbers with opposite biases
multiplied together.

`tickets.combined_prob` now holds the de-vigged MARKET product, which makes the
arithmetic honest by construction: for L real-priced legs it equals
overround^-L, about -22% at the measured 1.0616 margin. `tickets.model_prob`
keeps our own product so the page can show both and the ledger keeps its audit
trail, and `ticket_legs.fair_prob` keeps the per-leg market probability that
built it.

No backfill. Historic slips were generated under the old definition and their
stored combined_prob is what was actually shown to a reader on the day; the
record endpoint compares outcomes to it. Rewriting them would edit the evidence
this change exists because of. model_prob and fair_prob stay NULL on those rows
and every reader falls back.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("model_prob", sa.Float(), nullable=True))
    op.add_column("ticket_legs", sa.Column("fair_prob", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("ticket_legs", "fair_prob")
    op.drop_column("tickets", "model_prob")
