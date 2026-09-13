"""A match that was not played is not graded (migration 0038).

API-Football closes a fixture four ways that are not a played match: AWD
(awarded), WO (walkover), CANC (cancelled) and ABD (abandoned). The club writers
read the first two as ordinary results, so an awarded 3-0 was graded against our
calls and settled accumulator legs; the other two were ignored, so a fixture
abandoned on its day stayed unsettled for ever. matches.void_reason records it:
an awarded match keeps its score for the table, and no grading path reads it.

Offline: in-memory SQLite, no network.
"""
from __future__ import annotations

from datetime import date, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models.match import Match
from backend.app.models.ticket import Ticket, TicketLeg
from scripts._feed_scores import api_football_void_reason

ROOT = Path(__file__).resolve().parents[2]
TODAY = date.today()


def _af(status, goals=(None, None), fulltime=(None, None)):
    return {"fixture": {"status": {"short": status}},
            "goals": {"home": goals[0], "away": goals[1]},
            "score": {"fulltime": {"home": fulltime[0], "away": fulltime[1]}}}


@pytest.mark.parametrize("status, reason", [
    ("AWD", "awarded"), ("WO", "walkover"), ("CANC", "cancelled"), ("ABD", "abandoned"),
    ("FT", None), ("AET", None), ("PEN", None), ("PST", None), ("NS", None),
])
def test_only_unplayed_statuses_carry_a_void_reason(status, reason):
    assert api_football_void_reason(_af(status)) == reason


@pytest.mark.parametrize("entry, expected", [
    (_af("FT", (2, 1), (2, 1)), ("settle", 2, 1, None)),
    (_af("AET", (2, 1), (1, 1)), ("settle", 1, 1, None)),        # 90 minutes
    (_af("AWD", (3, 0)), ("award", 3, 0, "awarded")),
    (_af("CANC"), ("void", None, None, "cancelled")),
    (_af("ABD", (1, 0)), ("void", None, None, "abandoned")),     # a part-played score is no result
    (_af("PST"), ("leave", None, None, None)),
])
def test_the_resolver_reads_each_status_as_the_bookmaker_would(entry, expected):
    from scripts.resolve_stranded_fixtures import classify

    assert classify(entry) == expected


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Match.__table__, Ticket.__table__,
                                             TicketLeg.__table__])
    with Session(engine) as session:
        yield session


def _match(db, i, **kw):
    m = Match(match_date=TODAY - timedelta(days=1), kickoff_time=time(19, 0), league="EPL",
              season="2026/27", home_team=f"H{i}", away_team=f"A{i}", **kw)
    db.add(m)
    db.flush()
    return m


def test_a_slip_with_an_awarded_leg_is_void_not_graded(db):
    from scripts.generate_tickets import settle_open_tickets

    played = _match(db, 1, home_goals=2, away_goals=0, result="H")
    awarded = _match(db, 2, home_goals=3, away_goals=0, result="H", void_reason="awarded")
    t = Ticket(generated_for=TODAY - timedelta(days=2), profile="double", total_odds=3.0,
               combined_prob=.3, num_legs=2, horizon_days=3)
    db.add(t)
    db.flush()
    for m in (played, awarded):
        db.add(TicketLeg(ticket_id=t.id, match_id=m.id, market="1X", prob=.7,
                         odds=1.7, estimated=False))
    db.commit()
    tid = t.id

    settle_open_tickets(db)

    assert db.scalar(select(Ticket.outcome).where(Ticket.id == tid)) == "void"


@pytest.mark.parametrize("rel, needle, n", [
    ("backend/app/routers/stats.py", "Match.void_reason.is_(None)", 1),
    ("backend/app/routers/matches.py", "Match.void_reason.is_(None)", 2),
    ("backend/app/ml/european_blend.py", "void_reason IS NULL", 1),
    ("backend/app/ml/odds_analysis_service.py", "m.void_reason IS NULL", 1),
    ("scripts/settle_stale_fixtures.py", "Match.void_reason.is_(None)", 1),
])
def test_every_grading_read_skips_unplayed_matches(rel, needle, n):
    assert (ROOT / rel).read_text().count(needle) >= n, rel


@pytest.mark.parametrize("rel", [
    "scripts/fetch_european_fixtures.py", "scripts/fetch_greek_apifootball.py",
    "scripts/fetch_club_friendlies.py", "scripts/fetch_domestic_apifootball.py",
])
def test_every_api_football_club_writer_records_an_awarded_result(rel):
    src = (ROOT / rel).read_text()
    assert 'base["void_reason"] = api_football_void_reason(entry)' in src \
        or '"void_reason":    api_football_void_reason(entry)' in src, rel
    assert 'void_reason=f.get("void_reason")' in src or 'row.void_reason = f.get("void_reason")' in src, rel
