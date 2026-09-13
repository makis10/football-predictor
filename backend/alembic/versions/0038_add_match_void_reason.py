"""record why a fixture has no gradable result

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-13

API-Football closes a fixture five ways that are not a played match: AWD
(awarded), WO (walkover), CANC (cancelled), ABD (abandoned) and PST
(postponed). The club writers read the first two as ordinary finished results,
so an awarded 3-0 was graded against our 1×2, Over 2.5 and BTTS calls and
settled every accumulator leg on it — no bookmaker settles a match that was not
played. The other three were ignored, so a fixture abandoned on its day stayed
unsettled for ever: still "running" on any slip that carried it, and listed
every morning among the fixtures stuck without a result.

`void_reason` is NULL for a real match and otherwise one of "awarded",
"walkover", "cancelled", "abandoned". An awarded match keeps the score it was
awarded — the league table counts it — but no grading path reads a row whose
void_reason is set.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("void_reason", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "void_reason")
