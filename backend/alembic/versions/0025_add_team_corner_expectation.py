"""add expected team corners to national_predictions

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-14

Recency-weighted expected corners per team for a fixture, aggregated from
team_match_stats, plus a Poisson P(total corners over 9.5). Mirrors the
expected-cards columns added in 0022.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("national_predictions", sa.Column("exp_home_corners", sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("exp_away_corners", sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("corners_over_9_5_prob", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("national_predictions", "corners_over_9_5_prob")
    op.drop_column("national_predictions", "exp_away_corners")
    op.drop_column("national_predictions", "exp_home_corners")
