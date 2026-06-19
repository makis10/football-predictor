"""add BTTS classifier prediction columns to predictions

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-08

Adds ML-model BTTS probability and prediction (GG/NG) from the dedicated
BTTS classifier, replacing the Poisson-based estimate that was ~50% accurate.
NULL for predictions computed before this migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("btts_prob",       sa.Float(),      nullable=True))
    op.add_column("predictions", sa.Column("btts_prediction", sa.String(10),   nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "btts_prediction")
    op.drop_column("predictions", "btts_prob")
