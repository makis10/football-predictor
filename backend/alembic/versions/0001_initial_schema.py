"""initial schema

Revision ID: 0001
Revises:
Create Date: 2025-04-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("league", sa.String(50), nullable=False),
        sa.Column("season", sa.String(10), nullable=False),
        sa.Column("match_date", sa.Date(), nullable=False),
        sa.Column("home_team", sa.String(100), nullable=False),
        sa.Column("away_team", sa.String(100), nullable=False),
        sa.Column("home_goals", sa.Integer(), nullable=True),
        sa.Column("away_goals", sa.Integer(), nullable=True),
        sa.Column("result", sa.String(1), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_matches_id",         "matches", ["id"])
    op.create_index("ix_matches_league",      "matches", ["league"])
    op.create_index("ix_matches_match_date",  "matches", ["match_date"])
    op.create_index("ix_matches_home_team",   "matches", ["home_team"])
    op.create_index("ix_matches_away_team",   "matches", ["away_team"])

    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("home_win_prob", sa.Float(), nullable=False),
        sa.Column("draw_prob", sa.Float(), nullable=False),
        sa.Column("away_win_prob", sa.Float(), nullable=False),
        sa.Column("over_2_5_prob", sa.Float(), nullable=False),
        sa.Column("goals_prediction", sa.String(10), nullable=False),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("confidence", sa.String(10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id"),
    )
    op.create_index("ix_predictions_id",       "predictions", ["id"])
    op.create_index("ix_predictions_match_id", "predictions", ["match_id"])


def downgrade() -> None:
    op.drop_table("predictions")
    op.drop_table("matches")
