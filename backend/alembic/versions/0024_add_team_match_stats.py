"""add team_match_stats table

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-14

Per-team, per-fixture statistics from API-Football (/fixtures/statistics) — the
raw material for team-level props (corners, shots, possession). Corners are NOT
exposed by /fixtures/players, so this is a separate ingestion alongside
player_match_stats. One row per (fixture, team).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "team_match_stats",
        sa.Column("id",          sa.Integer(),   primary_key=True, autoincrement=True),
        sa.Column("fixture_id",  sa.Integer(),   nullable=False, index=True),   # API-Football fixture id
        sa.Column("match_date",  sa.String(10),  nullable=False, index=True),   # YYYY-MM-DD
        sa.Column("league_id",   sa.Integer(),   nullable=True),
        sa.Column("team",        sa.String(100), nullable=False, index=True),
        sa.Column("opponent",    sa.String(100), nullable=True),
        sa.Column("is_home",     sa.Boolean(),   nullable=True),
        sa.Column("corners",     sa.Integer(),   nullable=True),
        sa.Column("possession",  sa.Float(),     nullable=True),                # percent 0–100
        sa.Column("shots_total", sa.Integer(),   nullable=True),
        sa.Column("shots_on",    sa.Integer(),   nullable=True),
        sa.Column("fouls",       sa.Integer(),   nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("fixture_id", "team", name="uq_team_match_stats"),
    )


def downgrade() -> None:
    op.drop_table("team_match_stats")
