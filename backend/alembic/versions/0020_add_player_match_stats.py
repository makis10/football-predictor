"""add player_match_stats table

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-14

Per-player, per-fixture statistics from API-Football (/fixtures/players) — the
raw material for player-prop models (anytime scorer, shots on target, assists).
Previously unused despite the Pro API plan. One row per (fixture, player).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_match_stats",
        sa.Column("id",          sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column("fixture_id",  sa.Integer(),  nullable=False, index=True),   # API-Football fixture id
        sa.Column("match_date",  sa.String(10), nullable=False, index=True),   # YYYY-MM-DD
        sa.Column("league_id",   sa.Integer(),  nullable=True),
        sa.Column("team",        sa.String(100), nullable=False, index=True),
        sa.Column("opponent",    sa.String(100), nullable=True),
        sa.Column("is_home",     sa.Boolean(),  nullable=True),
        sa.Column("player_id",   sa.Integer(),  nullable=False, index=True),
        sa.Column("player_name", sa.String(120), nullable=False),
        sa.Column("position",    sa.String(20), nullable=True),
        sa.Column("minutes",     sa.Integer(),  nullable=True),
        sa.Column("goals",       sa.Integer(),  nullable=True),
        sa.Column("assists",     sa.Integer(),  nullable=True),
        sa.Column("shots_total", sa.Integer(),  nullable=True),
        sa.Column("shots_on",    sa.Integer(),  nullable=True),
        sa.Column("key_passes",  sa.Integer(),  nullable=True),
        sa.Column("yellow",      sa.Integer(),  nullable=True),
        sa.Column("red",         sa.Integer(),  nullable=True),
        sa.Column("rating",      sa.Float(),    nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("fixture_id", "player_id", name="uq_player_match_stats"),
    )


def downgrade() -> None:
    op.drop_table("player_match_stats")
