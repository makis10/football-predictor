"""add BTTS metrics to training_runs

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("training_runs", sa.Column("btts_test_accuracy",  sa.Float(), nullable=True))
    op.add_column("training_runs", sa.Column("btts_gg_recall",      sa.Float(), nullable=True))
    op.add_column("training_runs", sa.Column("btts_ng_recall",      sa.Float(), nullable=True))
    op.add_column("training_runs", sa.Column("btts_gg_precision",   sa.Float(), nullable=True))
    op.add_column("training_runs", sa.Column("btts_ng_precision",   sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("training_runs", "btts_ng_precision")
    op.drop_column("training_runs", "btts_gg_precision")
    op.drop_column("training_runs", "btts_ng_recall")
    op.drop_column("training_runs", "btts_gg_recall")
    op.drop_column("training_runs", "btts_test_accuracy")
