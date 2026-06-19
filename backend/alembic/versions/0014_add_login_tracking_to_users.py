"""add last_login_at and login_count to users

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-09

Tracks when each user last logged in and how many times they have logged in total.
Updated on every successful auth (OAuth + credentials).
NULL last_login_at for users who registered but never logged in after this migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("login_count",   sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "login_count")
    op.drop_column("users", "last_login_at")
