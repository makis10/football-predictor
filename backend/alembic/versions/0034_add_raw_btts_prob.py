"""add raw_btts_prob to predictions

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-07

Every headline probability keeps an unanchored twin so the EV / value gate can
measure model-against-market instead of market-against-itself. 1x2 has
raw_home/draw/away_prob and Over 2.5 has raw_over_prob; BTTS never got one,
because BTTS was never anchored.

Anchoring it without this column would have been a silent regression rather than
an improvement: backend/app/routers/predictions.py hands btts_prob straight into
run_comparison, and odds_analysis_service computes GG/NG expected value as
`prob * that same book's decimal odds - 1`. Feed it an anchored probability and
every GG/NG edge collapses to roughly minus the margin — about -0.06 at the
measured 1.0613 overround — so the gate quietly stops surfacing goals bets at
all. That is the exact failure the comment beside MARKET_ANCHOR_WEIGHT warns
about, and BTTS was the one market with no raw column to protect it.

Nullable with no backfill: rows written before this migration have no unanchored
BTTS to recover, and inventing one would poison the very ledger the column
exists to keep honest. The readers fall back to btts_prob, which for those rows
IS the unanchored number.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("raw_btts_prob", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "raw_btts_prob")
