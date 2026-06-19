"""add kickoff_utc to national_predictions

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-10

Full UTC kick-off instant for national matches, captured from The Odds API
event commence_time. Stored as a complete datetime (not a bare time-of-day)
because match_date holds the LOCAL calendar date: US/Mexico evening games
cross midnight in UTC, so date+time from different calendars would render
the wrong moment.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("national_predictions",
                  sa.Column("kickoff_utc", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("national_predictions", "kickoff_utc")
