"""add player_props table

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-14

Per-fixture player-prop probabilities (anytime scorer, shots on target 1+/2+,
assist) computed from player_match_stats + the match expected-goals model.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_props",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("national_prediction_id", sa.Integer(),
                  sa.ForeignKey("national_predictions.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("match_date",  sa.String(10), nullable=False, index=True),
        sa.Column("team",        sa.String(100), nullable=False),
        sa.Column("opponent",    sa.String(100), nullable=True),
        sa.Column("player_id",   sa.Integer(),  nullable=False),
        sa.Column("player_name", sa.String(120), nullable=False),
        sa.Column("exp_minutes", sa.Float(), nullable=True),
        sa.Column("exp_goals",   sa.Float(), nullable=True),
        sa.Column("p_score",     sa.Float(), nullable=True),
        sa.Column("p_sot_1",     sa.Float(), nullable=True),
        sa.Column("p_sot_2",     sa.Float(), nullable=True),
        sa.Column("p_assist",    sa.Float(), nullable=True),
        sa.Column("updated_at",  sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("national_prediction_id", "player_id",
                            name="uq_player_props"),
    )


def downgrade() -> None:
    op.drop_table("player_props")
