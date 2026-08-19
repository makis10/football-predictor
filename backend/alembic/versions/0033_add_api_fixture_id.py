"""store the API-Football fixture id on matches

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-18

The Odds API plan is 20,000 credits a month and it runs out; when it does the
site has no bookmaker price on any fixture, so no EV, no value gate and no
accumulators — for the 18 days of August after the 13th, nothing.

API-Football is the second source and it is already paid for, already
IP-whitelisted, and running at about two thirds of its daily allowance. Its
/odds endpoint carries 33 bookmakers (Pinnacle, Bet365, William Hill,
Marathonbet…) across the markets we actually price: Match Winner, Goals
Over/Under and Both Teams Score.

The catch is that /odds identifies a match by fixture id and returns no team
names, so there is nothing to match on. We already receive that id on every
fixture we ingest from API-Football and were throwing it away. Storing it turns
the odds lookup into a direct join instead of a second /fixtures call per
league-day purely to recover the mapping.

Nullable: fixtures that came from football-data.org or The Odds API have no
API-Football id, and a NULL simply means "this source cannot price it".
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("api_fixture_id", sa.Integer(), nullable=True))
    op.create_index("ix_matches_api_fixture_id", "matches", ["api_fixture_id"])


def downgrade() -> None:
    op.drop_index("ix_matches_api_fixture_id", table_name="matches")
    op.drop_column("matches", "api_fixture_id")
