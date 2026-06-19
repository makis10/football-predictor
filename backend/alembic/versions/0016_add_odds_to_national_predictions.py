"""add bookmaker odds + EV to national_predictions

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-02

National-team predictions now carry bookmaker odds (from The Odds API) and a
value-bet signal (ev_score + suggested_market), mirroring the club predictions
table. Odds are available for tournaments The Odds API covers (World Cup, EURO,
Copa América, AFCON, Nations League, qualifiers); friendlies have no odds source
so these columns stay NULL for them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("national_predictions", sa.Column("bm_home_odds",     sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("bm_draw_odds",     sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("bm_away_odds",     sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("bm_over_odds",     sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("bm_btts_yes_odds", sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("bm_btts_no_odds",  sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("num_bookmakers",   sa.Integer(), nullable=True))
    op.add_column("national_predictions", sa.Column("ev_score",         sa.Float(), nullable=True))
    op.add_column("national_predictions", sa.Column("suggested_market", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("national_predictions", "suggested_market")
    op.drop_column("national_predictions", "ev_score")
    op.drop_column("national_predictions", "num_bookmakers")
    op.drop_column("national_predictions", "bm_btts_no_odds")
    op.drop_column("national_predictions", "bm_btts_yes_odds")
    op.drop_column("national_predictions", "bm_over_odds")
    op.drop_column("national_predictions", "bm_away_odds")
    op.drop_column("national_predictions", "bm_draw_odds")
    op.drop_column("national_predictions", "bm_home_odds")
