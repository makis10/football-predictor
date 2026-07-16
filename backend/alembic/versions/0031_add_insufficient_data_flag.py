"""add insufficient_data flag to predictions

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-16

Fixtures whose BOTH teams are absent from our training history (e.g. UEFA
qualifying-round minnows from leagues we don't ingest — Derry City, Qarabag,
Ferencváros, …) get a pure-defaults feature vector, so every such match yields
the IDENTICAL prediction (52/25/23, OVER). Storing them unflagged made the
listing look broken. This boolean marks them so the UI shows an "insufficient
data" note instead of fake percentages, and stats can exclude them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "predictions",
        sa.Column("insufficient_data", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("predictions", "insufficient_data")
