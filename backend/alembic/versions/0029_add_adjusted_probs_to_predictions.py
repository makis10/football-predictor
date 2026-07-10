"""add injury-adjusted probability columns to predictions

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-10

The injury-adjustment layer mutates the served 1×2/O-U probabilities at read
time, but only the RAW stored probabilities were ever graded — so the layer's
effect on accuracy was unmeasured (it could be negative and we'd never know).

These nullable columns capture the last injury-adjusted probabilities served
for the match (written by the predictions router when a significant adjustment
applies). /stats grades raw vs adjusted on the same rows. Forward-only: rows
settled before this migration have NULLs (historical adjustments weren't
persisted anywhere).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLS = ["adj_home_win_prob", "adj_draw_prob", "adj_away_win_prob", "adj_over_2_5_prob"]


def upgrade() -> None:
    for col in _COLS:
        op.add_column("predictions", sa.Column(col, sa.Float(), nullable=True))
    op.add_column("predictions",
                  sa.Column("adj_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "adj_updated_at")
    for col in reversed(_COLS):
        op.drop_column("predictions", col)
