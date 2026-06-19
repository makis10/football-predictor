"""add kickoff_time column to matches

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-17

Adds an optional TIME column that stores the scheduled kick-off hour/minute
for each match.  NULL for historical fixtures that were imported before the
column existed — the frontend falls back to showing just the date in that
case.  Used both for UI display (the card shows the kickoff time instead of
the date, since the date is already in the day-header) and for hiding the
live Claude analysis panel once a match has been under way for 2+ hours.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("kickoff_time", sa.Time(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("matches", "kickoff_time")
