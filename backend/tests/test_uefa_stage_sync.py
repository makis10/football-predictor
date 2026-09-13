"""UEFA stage labels must follow the feed onto rows other jobs wrote or settled.

The league-phase table and every qualification projection accept only rows
whose stage reads "League Stage - N". upsert_fixtures sees only upcoming
fixtures and fetch_european_fixtures.update_results only rows still waiting
for a score, so a stage that changed on a row football-data.org had already
settled (9 of the 18 CL League Stage 1 rows, 2026-09-08..10) was never
corrected. sync_stages keys the correction on the API-Football fixture id.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models.match import Match
from scripts.fetch_european_fixtures import sync_stages


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Match.__table__])
    with Session(engine) as session:
        yield session


def _feed(rnd="League Stage - 1", fid=900001, d=date(2026, 9, 9)):
    return {"league": "CL", "home_team": "Arsenal", "away_team": "Bayern Munich",
            "match_date": d, "round": rnd, "api_fixture_id": fid}


def _row(db, **kw):
    fields = dict(league="CL", season="2026", home_team="Arsenal",
                  away_team="Bayern Munich", match_date=date(2026, 9, 9))
    fields.update(kw)
    m = Match(**fields)
    db.add(m)
    db.commit()
    return m


def test_a_settled_row_takes_the_feeds_stage_by_its_id(db):
    m = _row(db, round="Group Stage", api_fixture_id=900001,
             home_goals=2, away_goals=1, result="H")
    assert sync_stages(db, [_feed()]) == 1
    db.refresh(m)
    assert m.round == "League Stage - 1"


def test_a_row_without_the_feed_id_is_matched_on_its_pairing_and_adopts_it(db):
    """A row written by another source carries no feed id; a day's drift is
    timezone noise between feeds."""
    m = _row(db, round=None, match_date=date(2026, 9, 10))
    assert sync_stages(db, [_feed()]) == 1
    db.refresh(m)
    assert (m.round, m.api_fixture_id) == ("League Stage - 1", 900001)


def test_an_ambiguous_pairing_is_left_alone(db):
    rows = [_row(db, round=None, match_date=date(2026, 9, 8)),
            _row(db, round=None, match_date=date(2026, 9, 10))]
    assert sync_stages(db, [_feed()]) == 0
    for m in rows:
        db.refresh(m)
        assert (m.round, m.api_fixture_id) == (None, None)


def test_a_feed_without_a_stage_changes_nothing(db):
    m = _row(db, round="League Stage - 1", api_fixture_id=900001)
    assert sync_stages(db, [_feed(rnd=None)]) == 0
    db.refresh(m)
    assert m.round == "League Stage - 1"
