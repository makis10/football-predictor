"""One real match must never end up as two fixture rows.

Both bugs these cover were invisible in the fixture table and only surfaced on
the accumulator page, where the same match appeared as two independent legs and
its probability was multiplied by itself:

  • a postponement moved five ties 10–12 days (Anderlecht–Kortrijk and friends,
    22–23 Aug → 1–3 Sep) — further than the old 5-day reschedule window, so each
    one inserted a second row and abandoned the first on a date it would not be
    played on;

  • two feeds cover GreekSL and disagreed about a date — The Odds API had
    PAOK–Levadiakos on 22 Aug, API-Football (correctly) on the 23rd. Widening
    the window alone would have made this WORSE, not better: the two feeds would
    take turns dragging one row back and forth every day. Hence `authoritative`.
"""
from __future__ import annotations

from datetime import date, time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models.match import Match
from scripts.fixture_upsert import upsert_fixtures


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Match.__table__])
    with Session(engine) as session:
        yield session


def _fixture(match_date, home="Anderlecht", away="Kortrijk", league="Belgium",
             kickoff=time(18, 30)):
    return {"match_date": match_date, "kickoff_time": kickoff, "league": league,
            "home_team": home, "away_team": away, "season": "2026"}


def _rows(db, **where):
    stmt = select(Match)
    for col, val in where.items():
        stmt = stmt.where(getattr(Match, col) == val)
    return db.scalars(stmt.order_by(Match.match_date)).all()


def test_a_twelve_day_postponement_moves_the_row_instead_of_adding_one():
    """The exact shape of the 2026-08-17 duplicates: a European entrant's league
    game refixed into the next midweek, 12 days later."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Match.__table__])
    with Session(engine) as db:
        upsert_fixtures(db, [_fixture(date(2026, 8, 22))])
        original_id = _rows(db)[0].id

        upsert_fixtures(db, [_fixture(date(2026, 9, 3))])

        rows = _rows(db)
        assert len(rows) == 1, "the postponement created a second fixture row"
        assert rows[0].id == original_id, "the row was replaced, not moved"
        assert rows[0].match_date == date(2026, 9, 3)


def test_a_corroborating_feed_never_moves_or_duplicates_a_dated_fixture(db):
    """PAOK–Levadiakos. The Odds API says the 22nd, API-Football says the 23rd,
    and API-Football is the schedule of record for GreekSL."""
    upsert_fixtures(db, [_fixture(date(2026, 8, 23), "PAOK", "Levadeiakos", "GreekSL")])
    authoritative_id = _rows(db)[0].id

    upsert_fixtures(
        db,
        [_fixture(date(2026, 8, 22), "PAOK", "Levadeiakos", "GreekSL")],
        authoritative=False,
    )

    rows = _rows(db)
    assert len(rows) == 1, "the corroborating feed added a second row for one match"
    assert rows[0].id == authoritative_id
    assert rows[0].match_date == date(2026, 8, 23), "a lesser feed overwrote the date"


def test_a_corroborating_feed_still_inserts_a_fixture_nobody_else_has(db):
    """Deferring is about disagreement, not silence. The Odds API is the only
    GreekSL source alive out of season, so it must still be able to add."""
    upsert_fixtures(
        db,
        [_fixture(date(2026, 8, 22), "PAOK", "Levadeiakos", "GreekSL")],
        authoritative=False,
    )
    assert len(_rows(db)) == 1


def test_a_feed_listing_one_pairing_twice_keeps_both_matches(db):
    """The guard against the widened window eating a real fixture. If the source
    itself says these clubs meet twice at the same ground inside the window,
    they are two matches and collapsing them would delete one."""
    upsert_fixtures(db, [
        _fixture(date(2026, 8, 22), league="ClubFriendly"),
        _fixture(date(2026, 8, 29), league="ClubFriendly"),
    ])

    rows = _rows(db)
    assert [r.match_date for r in rows] == [date(2026, 8, 22), date(2026, 8, 29)]


def test_a_played_fixture_is_never_treated_as_a_reschedule(db):
    """A settled result is the record. The second leg of a tie, or the reverse
    fixture, must not overwrite it."""
    upsert_fixtures(db, [_fixture(date(2026, 8, 22))])
    row = _rows(db)[0]
    row.result, row.home_goals, row.away_goals = "H", 2, 0
    db.commit()

    upsert_fixtures(db, [_fixture(date(2026, 9, 3))])

    rows = _rows(db)
    assert len(rows) == 2, "a played match was dragged onto a later date"
    assert rows[0].result == "H"


def test_the_window_covers_the_midweek_refix_leagues_actually_use():
    """Written out rather than imported: a test that reads the constant it is
    checking passes whatever the constant becomes. 12 days is the observed gap
    (22 Aug → 3 Sep) and the reason 5 was not enough."""
    import inspect

    sig = inspect.signature(upsert_fixtures)
    assert sig.parameters["reschedule_window_days"].default >= 12
