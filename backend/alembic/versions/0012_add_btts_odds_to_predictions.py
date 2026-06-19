"""add BTTS bookmaker odds to predictions

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-04

Stores the average bookmaker BTTS (Both Teams To Score) odds at prediction
time so ROI can be tracked for the GG/NG market alongside 1x2 and O/U 2.5.
NULL for predictions computed before this migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("bm_btts_yes_odds", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("bm_btts_no_odds",  sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "bm_btts_no_odds")
    op.drop_column("predictions", "bm_btts_yes_odds")
