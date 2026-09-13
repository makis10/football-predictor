"""point users' bets and tracked matches at the fixture, not at its prediction

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-13

user_bets.match_id and tracked_matches.match_id were foreign keys to
predictions(match_id) ON DELETE CASCADE. A prediction is not a durable row:
compute_predictions.py deletes and rewrites it on schedule — every upcoming
fixture on Monday's --force, today's on the 15:00 --force-today, anything that
has since been priced on --force-missing-odds every eight hours. Each of those
deletes cascaded into the users' own rows, so a bet logged on Saturday's match
on Thursday was gone by Saturday: the history on /my-roi and the list on
/my-matches lost it without a trace, and the ROI they print was computed over
whatever had survived.

Both now reference matches(id), the row that lives as long as the fixture does:

- tracked_matches: ON DELETE CASCADE. A bookmark on a fixture that no longer
  exists has nothing left to show.
- user_bets: ON DELETE SET NULL, match_id nullable. A bet is the user's record
  of money staked; it outlives the fixture row. The code that deletes fixtures
  (fixture_upsert.prune_vanished) voids open bets first, and
  dedupe_fixtures moves them onto the surviving twin.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("user_bets_match_id_fkey", "user_bets", type_="foreignkey")
    op.alter_column("user_bets", "match_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key("user_bets_match_id_fkey", "user_bets", "matches",
                          ["match_id"], ["id"], ondelete="SET NULL")

    op.drop_constraint("tracked_matches_match_id_fkey", "tracked_matches", type_="foreignkey")
    op.create_foreign_key("tracked_matches_match_id_fkey", "tracked_matches", "matches",
                          ["match_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    # The old keys demand a prediction for every row. Rows that no longer have
    # one (fixture pruned, or between a delete and a rewrite) cannot satisfy
    # them and are dropped — which is exactly what the old schema did to them.
    op.execute("DELETE FROM user_bets WHERE match_id IS NULL "
               "OR match_id NOT IN (SELECT match_id FROM predictions)")
    op.execute("DELETE FROM tracked_matches "
               "WHERE match_id NOT IN (SELECT match_id FROM predictions)")

    op.drop_constraint("tracked_matches_match_id_fkey", "tracked_matches", type_="foreignkey")
    op.create_foreign_key("tracked_matches_match_id_fkey", "tracked_matches", "predictions",
                          ["match_id"], ["match_id"], ondelete="CASCADE")

    op.drop_constraint("user_bets_match_id_fkey", "user_bets", type_="foreignkey")
    op.alter_column("user_bets", "match_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key("user_bets_match_id_fkey", "user_bets", "predictions",
                          ["match_id"], ["match_id"], ondelete="CASCADE")
