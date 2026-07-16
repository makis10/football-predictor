"""add competition round (phase) to matches

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-14

UEFA competitions are not one thing: a CL season is a July→August qualifying
knockout, then a 36-team single-table league phase, then a knockout bracket.
`matches` only stored league/season, so every one of those fixtures looked
identical — there was no way to build a league-phase table (a qualifying tie
would have been counted into it) or to know which stage a title projection
should start from.

API-Football already returns the stage as `league.round` ("1st Qualifying
Round", "League Phase - 3", "Round of 16"…). This stores it. Nullable: domestic
league rows don't need it and stay NULL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("round", sa.String(length=60), nullable=True))
    op.create_index("ix_matches_round", "matches", ["round"])


def downgrade() -> None:
    op.drop_index("ix_matches_round", table_name="matches")
    op.drop_column("matches", "round")
