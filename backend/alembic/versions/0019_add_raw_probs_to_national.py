"""add raw (pre-anchor) probabilities to national_predictions

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-14

Stores the pure international-model probabilities separately from the served
ones. The served home/draw/away/over columns are anchored toward the de-vig
bookmaker market (measured: the raw model argmax trails the market favourite,
and over-rates CONCACAF/underdogs — e.g. USA 4-1 Paraguay was predicted as an
away win). Keeping raw_* lets the odds job re-anchor from a stable base every
run instead of compounding the blend.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("national_predictions", sa.Column("raw_home_prob", sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("raw_draw_prob", sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("raw_away_prob", sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("raw_over_prob", sa.Float(), nullable=True))
    op.add_column("national_predictions",
                  sa.Column("market_anchored", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    op.drop_column("national_predictions", "market_anchored")
    op.drop_column("national_predictions", "raw_over_prob")
    op.drop_column("national_predictions", "raw_away_prob")
    op.drop_column("national_predictions", "raw_draw_prob")
    op.drop_column("national_predictions", "raw_home_prob")
