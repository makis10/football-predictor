"""add odds_history table

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-24
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "odds_history",
        sa.Column("id",         sa.Integer(),                  nullable=False),
        sa.Column("match_id",   sa.Integer(),                  nullable=False),
        sa.Column("home_odds",  sa.Float(),                    nullable=True),
        sa.Column("draw_odds",  sa.Float(),                    nullable=True),
        sa.Column("away_odds",  sa.Float(),                    nullable=True),
        sa.Column("over_odds",  sa.Float(),                    nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True),    server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_odds_history_id",         "odds_history", ["id"],         unique=False)
    op.create_index("ix_odds_history_match_id",   "odds_history", ["match_id"],   unique=False)
    op.create_index("ix_odds_history_fetched_at", "odds_history", ["fetched_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_odds_history_fetched_at", table_name="odds_history")
    op.drop_index("ix_odds_history_match_id",   table_name="odds_history")
    op.drop_index("ix_odds_history_id",         table_name="odds_history")
    op.drop_table("odds_history")
