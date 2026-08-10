"""add accumulator tickets + bm_under_odds

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-10

Two things, both needed by the new Tickets page:

1. `tickets` / `ticket_legs` — suggested accumulators, frozen at generation
   time so they can be graded afterwards. Rebuilding them per request would
   make any claimed hit rate meaningless.

2. `predictions.bm_under_odds` — the Under 2.5 price. `_parse_game_odds`
   already reads it off the feed, but `_lookup_odds` dropped it on the floor,
   so Under 2.5 was the one common market with no real price. Without it the
   mid-priced ticket bands are almost entirely our own fair odds. Backfills as
   NULL for existing rows; those legs stay flagged estimated until the next
   prediction refresh fills them in.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "predictions",
        sa.Column("bm_under_odds", sa.Float(), nullable=True),
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generated_for", sa.Date(), nullable=False),
        sa.Column("profile", sa.String(length=20), nullable=False),
        sa.Column("total_odds", sa.Float(), nullable=False),
        sa.Column("combined_prob", sa.Float(), nullable=False),
        sa.Column("num_legs", sa.Integer(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("outcome", sa.String(length=10), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("generated_for", "profile", name="uq_tickets_day_profile"),
    )
    op.create_index("ix_tickets_generated_for", "tickets", ["generated_for"])
    op.create_index("ix_tickets_outcome", "tickets", ["outcome"])

    op.create_table(
        "ticket_legs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(),
                  sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_id", sa.Integer(),
                  sa.ForeignKey("matches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("market", sa.String(length=10), nullable=False),
        sa.Column("prob", sa.Float(), nullable=False),
        sa.Column("odds", sa.Float(), nullable=False),
        sa.Column("estimated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("won", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_ticket_legs_ticket_id", "ticket_legs", ["ticket_id"])
    op.create_index("ix_ticket_legs_match_id", "ticket_legs", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_ticket_legs_match_id", table_name="ticket_legs")
    op.drop_index("ix_ticket_legs_ticket_id", table_name="ticket_legs")
    op.drop_table("ticket_legs")
    op.drop_index("ix_tickets_outcome", table_name="tickets")
    op.drop_index("ix_tickets_generated_for", table_name="tickets")
    op.drop_table("tickets")
    op.drop_column("predictions", "bm_under_odds")
