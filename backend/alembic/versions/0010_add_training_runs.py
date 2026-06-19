"""add training_runs table

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-04

Stores per-run training metrics so the admin dashboard can show a
historical view of model health after each weekly retrain.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "training_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("model_version", sa.String(20), nullable=True),

        # Data split sizes
        sa.Column("n_train", sa.Integer(), nullable=True),
        sa.Column("n_cal",   sa.Integer(), nullable=True),
        sa.Column("n_test",  sa.Integer(), nullable=True),
        sa.Column("cal_cutoff",   sa.Date(), nullable=True),
        sa.Column("train_cutoff", sa.Date(), nullable=True),
        sa.Column("test_cutoff",  sa.Date(), nullable=True),

        # Result model (H/D/A) — evaluated on test set
        sa.Column("result_test_accuracy",   sa.Float(), nullable=True),
        sa.Column("result_home_recall",     sa.Float(), nullable=True),
        sa.Column("result_draw_recall",     sa.Float(), nullable=True),
        sa.Column("result_away_recall",     sa.Float(), nullable=True),
        sa.Column("result_home_precision",  sa.Float(), nullable=True),
        sa.Column("result_draw_precision",  sa.Float(), nullable=True),
        sa.Column("result_away_precision",  sa.Float(), nullable=True),

        # Goals model (O/U 2.5) — evaluated on test set
        sa.Column("goals_test_accuracy",  sa.Float(), nullable=True),
        sa.Column("goals_over_recall",    sa.Float(), nullable=True),
        sa.Column("goals_under_recall",   sa.Float(), nullable=True),
        sa.Column("goals_over_precision", sa.Float(), nullable=True),

        # Draw specialist calibration
        sa.Column("draw_raw_mean",    sa.Float(), nullable=True),
        sa.Column("draw_cal_mean",    sa.Float(), nullable=True),
        sa.Column("draw_actual_rate", sa.Float(), nullable=True),

        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("training_runs")
