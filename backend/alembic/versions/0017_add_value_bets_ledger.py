"""add value_bets ledger

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-10

Immutable ticket ledger for the value strategy. Every suggestion is recorded
ONCE, at the odds quoted the first time it appears (early/opening line attack);
later recomputes (e.g. the 15:00 closing-line refresh) never modify a ticket.
CLV is then measured ticket-odds vs closing line — the fastest statistically
reliable proof of real edge.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "value_bets",
        sa.Column("id",          sa.Integer(),    primary_key=True, autoincrement=True),
        # Exactly one of the two references is set, depending on source.
        sa.Column("source",      sa.String(10),   nullable=False),   # "club" | "national"
        sa.Column("match_id",    sa.Integer(),    sa.ForeignKey("matches.id", ondelete="CASCADE"), nullable=True),
        sa.Column("national_prediction_id", sa.Integer(),
                  sa.ForeignKey("national_predictions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("market",      sa.String(20),   nullable=False),   # "Home Win" / "Draw" / ...
        sa.Column("odds",        sa.Float(),      nullable=False),   # quoted odds on the ticket
        sa.Column("ev",          sa.Float(),      nullable=True),    # shrunk EV at flag time
        sa.Column("model_prob",  sa.Float(),      nullable=True),
        sa.Column("market_prob", sa.Float(),      nullable=True),    # de-vig fair prob at flag time
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.func.now()),
        # NULLS NOT DISTINCT: match_id is NULL for national tickets (and vice
        # versa) — χωρίς αυτό τα NULLs δεν συγκρίνονται ίσα και το unique
        # constraint αφήνει duplicates (PG15+ feature).
        sa.UniqueConstraint("source", "match_id", "national_prediction_id", "market",
                            name="uq_value_bets_ticket",
                            postgresql_nulls_not_distinct=True),
    )


def downgrade() -> None:
    op.drop_table("value_bets")
