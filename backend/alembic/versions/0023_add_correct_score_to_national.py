"""add correct-score predictions to national_predictions

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-14

Most-likely scoreline + top-N correct scores (JSON) from a Dixon-Coles Poisson
over the Elo-derived λ_home/λ_away — the "Πιθανά Σκορ" market.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("national_predictions", sa.Column("most_likely_score", sa.String(10), nullable=True))
    op.add_column("national_predictions", sa.Column("top_scores", sa.Text(), nullable=True))  # JSON


def downgrade() -> None:
    op.drop_column("national_predictions", "top_scores")
    op.drop_column("national_predictions", "most_likely_score")
