"""add national_predictions table

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-16

Stores predictions for international / national team matches
(World Cup, EURO, Copa America, AFCON, etc.).
Separate table from club predictions — different model and feature set.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "national_predictions",
        sa.Column("id",             sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column("match_date",     sa.String(10),    nullable=False, index=True),
        sa.Column("home_team",      sa.String(100),   nullable=False, index=True),
        sa.Column("away_team",      sa.String(100),   nullable=False, index=True),
        sa.Column("tournament",     sa.String(200),   nullable=False),
        sa.Column("neutral",        sa.Boolean(),     nullable=False, server_default="true"),
        sa.Column("home_win_prob",  sa.Float(),       nullable=False),
        sa.Column("draw_prob",      sa.Float(),       nullable=False),
        sa.Column("away_win_prob",  sa.Float(),       nullable=False),
        sa.Column("prediction",     sa.String(5),     nullable=False),
        sa.Column("confidence",     sa.String(10),    nullable=False),
        sa.Column("over_2_5_prob",  sa.Float(),       nullable=False),
        sa.Column("btts_prob",      sa.Float(),       nullable=True),
        sa.Column("h_elo",          sa.Float(),       nullable=True),
        sa.Column("a_elo",          sa.Float(),       nullable=True),
        sa.Column("actual_result",       sa.String(5),  nullable=True),
        sa.Column("actual_home_goals",   sa.Integer(),  nullable=True),
        sa.Column("actual_away_goals",   sa.Integer(),  nullable=True),
        sa.Column("created_at",     sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",     sa.DateTime(timezone=True), server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_index("ix_national_predictions_match_date", table_name="national_predictions", if_exists=True)
    op.drop_index("ix_national_predictions_home_team",  table_name="national_predictions", if_exists=True)
    op.drop_index("ix_national_predictions_away_team",  table_name="national_predictions", if_exists=True)
    op.drop_table("national_predictions")
