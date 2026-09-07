"""add under_odds to odds_history

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-07

Over/Under 2.5 is now anchored to the de-vigged line (predict.anchor_binary_to_
market), and de-vigging a two-way market needs both sides. The batch path has
them — compute_predictions reads bm_over_odds/bm_under_odds off the fixture's
own price. The API's cache-miss path had only odds_history, which stored the
over and dropped the under.

This costs nothing. The Odds API returns the totals market as a pair in the same
response the poll already pays for; `under_2_5` was parsed and discarded. BTTS
is deliberately NOT added here: it is an additional market billed one request
PER GAME, which is the ~1,100 credits/day the poll's docstring records cutting.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("odds_history", sa.Column("under_odds", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("odds_history", "under_odds")
