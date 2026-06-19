"""add raw XGBoost probabilities to predictions

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-04

Stores the pre-calibration XGBoost raw probabilities alongside the
calibrated ones. Enables post-hoc analysis of where calibration adds or
removes signal, and helps diagnose future model regressions faster.

NULL for predictions computed before this migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("raw_home_prob", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("raw_draw_prob", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("raw_away_prob", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("raw_over_prob", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "raw_over_prob")
    op.drop_column("predictions", "raw_away_prob")
    op.drop_column("predictions", "raw_draw_prob")
    op.drop_column("predictions", "raw_home_prob")
