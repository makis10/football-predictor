"""add ev_score and suggested_market to predictions

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-24

Adds two nullable columns for value-bet tracking:
  - suggested_market: best EV market label at prediction time (e.g. "Home Win @ 2.10")
  - ev_score: model_prob × odds − 1 for that market (e.g. 0.08 = 8% edge)

NULL means no odds were available or no market had positive EV.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("suggested_market", sa.String(50), nullable=True))
    op.add_column("predictions", sa.Column("ev_score", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "ev_score")
    op.drop_column("predictions", "suggested_market")
