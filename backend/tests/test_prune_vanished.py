"""A partial feed answer must never be read as a mass cancellation.

`prune_vanished` deletes unplayed fixtures the source feed stopped listing. It
has destroyed real schedules twice:

  • 2026-08-09 — football-data.org returned "0 fixtures" for three leagues while
    answering normally for seven. The caller passed all ten league codes, so
    every unplayed fixture of those three inside 60 days was deleted: 129 real
    matches, one of them kicking off three hours later. Fixed by the two guards
    (nothing-matched, no-leagues) plus a caller that only passes leagues the
    feed actually answered for.

  • 2026-08-17 — the same failure through the gap those guards left. BSA answered
    with **5** fixtures while we held **71** unplayed in the window, so
    BrazilSerieA was, technically, "a league the feed answered for". 66 fixtures
    were deleted — the entire Brazilian schedule out to October. Re-querying the
    identical endpoint by hand minutes later returned 81.

The distinction the guards were missing: a real round of cancellations is one or
two fixtures out of dozens. An answer covering 7% of what we hold is a broken
answer. Guard 3 checks coverage per league and refuses to prune below
MIN_FEED_COVERAGE.

Offline: in-memory SQLite, no network.
"""
from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models.match import Match
from scripts.fixture_upsert import MIN_FEED_COVERAGE, prune_vanished

TODAY = date.today()


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Match.__table__])
    with Session(engine) as session:
        yield session


def _add(db, n, league="BrazilSerieA", *, days_out=5, result=None):
    """n unplayed fixtures for a league, inside the prune window."""
    made = []
    for i in range(n):
        m = Match(match_date=TODAY + timedelta(days=days_out),
                  kickoff_time=time(19, 0), league=league, season="2026",
                  home_team=f"{league} H{i}", away_team=f"{league} A{i}",
                  result=result)
        db.add(m)
        made.append(m)
    db.commit()
    for m in made:
        db.refresh(m)
    return made


def _ids(db, league=None):
    stmt = select(Match.id)
    if league:
        stmt = stmt.where(Match.league == league)
    return set(db.scalars(stmt).all())


# ── the 2026-08-17 incident ──────────────────────────────────────────────────

def test_a_five_of_seventy_one_answer_prunes_nothing(db):
    """The exact numbers from the incident: BSA 5/71."""
    rows = _add(db, 71)
    touched = {m.id for m in rows[:5]}

    deleted = prune_vanished(db, ["BrazilSerieA"], touched)

    assert deleted == 0, f"{deleted} fixtures deleted on a 7% feed answer"
    assert len(_ids(db)) == 71, "the schedule must survive a partial answer"


def test_coverage_is_judged_per_league_not_across_the_run(db):
    """One flaky competition must neither shield nor doom the other nine. The
    2026-08-09 fix already learned this for the zero case; the ratio has to work
    the same way."""
    br = _add(db, 40, "BrazilSerieA")
    epl = _add(db, 10, "EPL")

    # Brazil answered for 2 of 40 (broken); EPL for 9 of 10 (one cancellation).
    touched = {m.id for m in br[:2]} | {m.id for m in epl[:9]}
    deleted = prune_vanished(db, ["BrazilSerieA", "EPL"], touched)

    assert deleted == 1, "the healthy league's single cancellation should prune"
    assert len(_ids(db, "BrazilSerieA")) == 40, "Brazil must be untouched"
    assert len(_ids(db, "EPL")) == 9


# ── genuine cancellations must still work ────────────────────────────────────

def test_a_real_cancellation_is_still_pruned(db):
    """The guard must not turn prune into a no-op: one match dropping out of a
    full round is exactly what this function is for."""
    rows = _add(db, 20, "EPL")
    touched = {m.id for m in rows[:19]}

    assert prune_vanished(db, ["EPL"], touched) == 1
    assert len(_ids(db, "EPL")) == 19


def test_coverage_exactly_at_the_threshold_prunes(db):
    """Boundary: the check is `< MIN_FEED_COVERAGE`, so meeting it is enough.
    Written out so a later `<=` edit fails here rather than in production."""
    rows = _add(db, 10, "EPL")
    keep = int(10 * MIN_FEED_COVERAGE)
    touched = {m.id for m in rows[:keep]}

    assert prune_vanished(db, ["EPL"], touched) == 10 - keep


# ── the threshold itself ─────────────────────────────────────────────────────

def test_threshold_sits_between_the_failure_and_a_real_cancellation():
    """7% was the observed break; a genuine round of cancellations leaves 95%+
    coverage. The threshold has to separate those two and not drift into either."""
    assert 0.07 < MIN_FEED_COVERAGE < 0.95, (
        f"MIN_FEED_COVERAGE={MIN_FEED_COVERAGE} no longer separates a broken "
        "feed answer from a real cancellation"
    )


# ── the older guards must still hold ─────────────────────────────────────────

def test_nothing_matched_prunes_nothing(db):
    """Guard 1, the original landmine: `notin_(empty)` is a no-op, so the WHERE
    collapsed to True and the statement became 'delete everything'."""
    _add(db, 30, "EPL")
    assert prune_vanished(db, ["EPL"], set()) == 0
    assert len(_ids(db)) == 30


def test_no_leagues_prunes_nothing(db):
    rows = _add(db, 5, "EPL")
    assert prune_vanished(db, [], {rows[0].id}) == 0
    assert len(_ids(db)) == 5


# ── scope: what must never be touched, whatever the coverage ─────────────────

def test_played_fixtures_are_never_pruned(db):
    """A result is history. Deleting it would take the prediction with it and
    silently change every accuracy number on the site."""
    played = _add(db, 10, "EPL", result="H")
    unplayed = _add(db, 10, "EPL")
    touched = {m.id for m in unplayed}

    prune_vanished(db, ["EPL"], touched)
    assert _ids(db, "EPL") >= {m.id for m in played}


def test_past_fixtures_are_never_pruned(db):
    """An unsettled fixture from yesterday is waiting for its result, not
    cancelled — this is how a played match loses its score for good."""
    past = _add(db, 6, "EPL", days_out=-2)
    now = _add(db, 6, "EPL", days_out=3)

    prune_vanished(db, ["EPL"], {m.id for m in now})
    assert _ids(db, "EPL") >= {m.id for m in past}


def test_fixtures_beyond_the_horizon_are_never_pruned(db):
    """The feed only covered `horizon_days`; anything past that was never in the
    answer and its absence means nothing."""
    far = _add(db, 8, "EPL", days_out=90)
    near = _add(db, 8, "EPL", days_out=3)

    prune_vanished(db, ["EPL"], {m.id for m in near}, horizon_days=60)
    assert _ids(db, "EPL") >= {m.id for m in far}


def test_other_leagues_are_never_pruned(db):
    """The 2026-08-09 shape: a league this run never fetched must be invisible
    to it."""
    other = _add(db, 12, "GreekSL")
    epl = _add(db, 12, "EPL")

    prune_vanished(db, ["EPL"], {m.id for m in epl})
    assert _ids(db, "GreekSL") == {m.id for m in other}
