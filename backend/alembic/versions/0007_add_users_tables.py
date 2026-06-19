"""Add users, tracked_matches, and user_bets tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id",               sa.Integer(),    primary_key=True),
        sa.Column("email",            sa.String(255),  nullable=False, unique=True),
        sa.Column("name",             sa.String(255),  nullable=True),
        sa.Column("image",            sa.Text(),       nullable=True),
        sa.Column("hashed_password",  sa.Text(),       nullable=True),   # NULL for OAuth-only users
        sa.Column("provider",         sa.String(50),   nullable=True),   # "google" | "credentials" | NULL
        sa.Column("provider_id",      sa.Text(),       nullable=True),   # Google sub ID
        sa.Column(
            "preferred_leagues",
            sa.Text(),
            nullable=True,
            comment="JSON array of league strings",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── tracked_matches ───────────────────────────────────────────────────────
    op.create_table(
        "tracked_matches",
        sa.Column("id",           sa.Integer(), primary_key=True),
        sa.Column("user_id",      sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_id",     sa.Integer(), sa.ForeignKey("predictions.match_id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "tracked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "match_id", name="uq_tracked_matches_user_match"),
    )
    op.create_index("ix_tracked_matches_user_id", "tracked_matches", ["user_id"])

    # ── user_bets ─────────────────────────────────────────────────────────────
    op.create_table(
        "user_bets",
        sa.Column("id",           sa.Integer(),     primary_key=True),
        sa.Column("user_id",      sa.Integer(),     sa.ForeignKey("users.id",       ondelete="CASCADE"), nullable=False),
        sa.Column("match_id",     sa.Integer(),     sa.ForeignKey("predictions.match_id", ondelete="CASCADE"), nullable=False),
        sa.Column("market",       sa.String(50),    nullable=False),    # e.g. "home_win", "over_2_5"
        sa.Column("odds",         sa.Float(),       nullable=False),
        sa.Column("stake",        sa.Float(),       nullable=False, server_default="1.0"),
        sa.Column("outcome",      sa.String(20),    nullable=True),     # "win" | "loss" | "void" | NULL=pending
        sa.Column("profit",       sa.Float(),       nullable=True),     # set when outcome known
        sa.Column(
            "placed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_user_bets_user_id", "user_bets", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_bets")
    op.drop_table("tracked_matches")
    op.drop_table("users")
