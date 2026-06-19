"""add poisson_lambda_home and poisson_lambda_away to predictions

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-01

Stores the two Poisson λ parameters at prediction time so that the
analysis endpoint can derive extended stats (O/U 1.5, O/U 3.5, correct
scores, combo markets) at serve-time without re-running the full feature
pipeline.

NULL for predictions computed before this migration (gracefully handled
by the API — extended Poisson stats section is hidden when NULL).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("poisson_lambda_home", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("poisson_lambda_away", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "poisson_lambda_away")
    op.drop_column("predictions", "poisson_lambda_home")
