"""add last_seen_at to users (activity tracking)

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-20

last_login_at/login_count only move on a real sign-in; with long JWT sessions a
user logs in once and stays, so they're a poor proxy for "active use". last_seen_at
is bumped (throttled) on any authenticated request — the accurate "last active".
Backfilled from last_login_at so existing users aren't shown as never-seen.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET last_seen_at = last_login_at WHERE last_seen_at IS NULL")


def downgrade() -> None:
    op.drop_column("users", "last_seen_at")
