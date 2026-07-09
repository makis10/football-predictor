"""add yellow/red card columns to team_match_stats

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-08

Team-level cards from API-Football /fixtures/statistics ("Yellow Cards" /
"Red Cards"). This lets us compute expected cards for CLUB fixtures from one
team-stats call, without per-player ingestion — bringing club match pages to
parity with the national ones (which currently derive cards from national
player_match_stats).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("team_match_stats", sa.Column("yellow_cards", sa.Integer(), nullable=True))
    op.add_column("team_match_stats", sa.Column("red_cards", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("team_match_stats", "red_cards")
    op.drop_column("team_match_stats", "yellow_cards")
