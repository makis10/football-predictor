"""add expected team cards to national_predictions

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-14

Recency-weighted expected yellow+red cards per team for a fixture, aggregated
from player_match_stats. (Corners need the /fixtures/statistics endpoint —
separate ingestion, not included here.)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("national_predictions", sa.Column("exp_home_cards", sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("exp_away_cards", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("national_predictions", "exp_away_cards")
    op.drop_column("national_predictions", "exp_home_cards")
