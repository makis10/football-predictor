"""add bookmaker odds columns to predictions

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-19

Adds four nullable float columns that store the average bookmaker decimal
odds (with vig) at the time the prediction was computed.  These are used for:
  - ROI tracking (how much would you have won/lost betting flat stakes)
  - Cumulative EV chart (model edge * odds, summed over time)

NULL means odds were not available for that match (e.g. league not on
The Odds API, or prediction pre-dates this migration).  All existing rows
remain valid — ROI/EV stats simply skip rows with NULL odds.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("bm_home_odds", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("bm_draw_odds", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("bm_away_odds", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("bm_over_odds", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "bm_over_odds")
    op.drop_column("predictions", "bm_away_odds")
    op.drop_column("predictions", "bm_draw_odds")
    op.drop_column("predictions", "bm_home_odds")
