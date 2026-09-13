"""Users' rows outlive the rows the pipeline rewrites under them.

user_bets and tracked_matches were keyed on predictions(match_id) ON DELETE
CASCADE, and compute_predictions deletes and rewrites predictions on schedule
(--force on Mondays, --force-today daily, --force-missing-odds every eight
hours) — a bet logged on Thursday for Saturday's match was gone by Saturday.
Migration 0037 keys both on matches(id), and the two paths that delete fixture
rows settle what points at them first (backend/app/fixture_dependents.py).

Offline: in-memory SQLite with foreign keys enforced.
"""
from __future__ import annotations

from datetime import date, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.fixture_dependents import move_dependents
from backend.app.models.match import Match
from backend.app.models.prediction import Prediction
from backend.app.models.ticket import Ticket, TicketLeg
from backend.app.models.user import TrackedMatch, User, UserBet
from scripts.fixture_upsert import prune_vanished

ROOT = Path(__file__).resolve().parents[2]
TODAY = date.today()
TABLES = [Match, Prediction, User, UserBet, TrackedMatch, Ticket, TicketLeg]


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enforce_keys(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[t.__table__ for t in TABLES])
    with Session(engine) as session:
        yield session


def _fixture(db, i):
    m = Match(match_date=TODAY + timedelta(days=3), kickoff_time=time(19, 0),
              league="EPL", season="2026/27", home_team=f"H{i}", away_team=f"A{i}")
    db.add(m)
    db.flush()
    return m


def _user(db, n):
    u = User(email=f"u{n}@example.test")
    db.add(u)
    db.flush()
    return u


def _bet(db, user, match, outcome=None):
    b = UserBet(user_id=user.id, match_id=match.id, market="home_win", odds=2.0,
                stake=1.0, outcome=outcome, profit=1.0 if outcome == "win" else None)
    db.add(b)
    db.flush()
    return b


def test_rewriting_a_prediction_leaves_the_users_rows_alone(db):
    m = _fixture(db, 1)
    db.add(Prediction(match_id=m.id, home_win_prob=.5, draw_prob=.25, away_win_prob=.25,
                      over_2_5_prob=.5, goals_prediction="OVER", model_version="t",
                      confidence="low", insufficient_data=False))
    u = _user(db, 1)
    _bet(db, u, m)
    db.add(TrackedMatch(user_id=u.id, match_id=m.id))
    db.commit()

    # What compute_predictions --force does to every upcoming fixture.
    db.execute(delete(Prediction).where(Prediction.match_id == m.id))
    db.commit()

    assert db.scalars(select(UserBet.match_id)).all() == [m.id]
    assert db.scalars(select(TrackedMatch.match_id)).all() == [m.id]


def test_a_cancelled_fixture_voids_open_bets_and_keeps_the_record(db):
    fixtures = [_fixture(db, i) for i in range(20)]
    gone, live = fixtures[-1], fixtures[0]
    u = _user(db, 1)
    open_bet, settled, other = _bet(db, u, gone), _bet(db, u, gone, "win"), _bet(db, u, live)
    db.add(TrackedMatch(user_id=u.id, match_id=gone.id))
    db.commit()
    ids = {"open": open_bet.id, "settled": settled.id, "other": other.id}

    assert prune_vanished(db, ["EPL"], {m.id for m in fixtures[:-1]}) == 1

    bets = {b.id: b for b in db.scalars(select(UserBet)).all()}
    assert len(bets) == 3, "a bet must never be deleted with its fixture"
    voided = bets[ids["open"]]
    assert (voided.outcome, voided.profit, voided.match_id) == ("void", 0.0, None)
    assert bets[ids["settled"]].outcome == "win", "a settled bet keeps its result"
    assert bets[ids["other"]].outcome is None and bets[ids["other"]].match_id == live.id
    assert db.scalars(select(TrackedMatch)).all() == []


def test_a_duplicate_hands_its_bets_bookmarks_and_legs_to_the_survivor(db):
    keeper, twin = _fixture(db, 1), _fixture(db, 2)
    a, b = _user(db, 1), _user(db, 2)
    bet = _bet(db, a, twin)
    db.add_all([TrackedMatch(user_id=a.id, match_id=keeper.id),
                TrackedMatch(user_id=a.id, match_id=twin.id),
                TrackedMatch(user_id=b.id, match_id=twin.id)])
    ticket = Ticket(generated_for=TODAY, profile="treble", total_odds=1.4,
                    combined_prob=.7, num_legs=1, horizon_days=3)
    db.add(ticket)
    db.flush()
    leg = TicketLeg(ticket_id=ticket.id, match_id=twin.id, market="1X", prob=.7,
                    odds=1.4, estimated=False)
    db.add(leg)
    db.commit()
    bet_id, leg_id, keeper_id = bet.id, leg.id, keeper.id

    move_dependents(db, twin.id, keeper_id)
    db.delete(twin)
    db.commit()

    assert db.scalar(select(UserBet.match_id).where(UserBet.id == bet_id)) == keeper_id
    assert sorted(db.execute(select(TrackedMatch.user_id, TrackedMatch.match_id)).all()) \
        == [(a.id, keeper_id), (b.id, keeper_id)]
    assert db.scalar(select(TicketLeg.match_id).where(TicketLeg.id == leg_id)) == keeper_id


def _key(col):
    (fk,) = col.foreign_keys
    return fk.target_fullname, fk.ondelete


def test_users_rows_are_keyed_on_the_fixture_not_its_prediction():
    assert _key(UserBet.__table__.c.match_id) == ("matches.id", "SET NULL")
    assert UserBet.__table__.c.match_id.nullable
    assert _key(TrackedMatch.__table__.c.match_id) == ("matches.id", "CASCADE")


def test_migration_0037_writes_the_same_keys():
    src = (ROOT / "backend/alembic/versions/0037_user_rows_reference_matches.py").read_text()
    up = src.split("def upgrade")[1].split("def downgrade")[0]
    assert '"user_bets", "matches"' in up and 'ondelete="SET NULL"' in up
    assert '"tracked_matches", "matches"' in up and 'ondelete="CASCADE"' in up


def test_a_bet_on_a_removed_fixture_still_serialises():
    from backend.app.routers.users import _bet_out

    b = UserBet(id=1, user_id=1, match_id=None, market="draw", odds=3.0, stake=1.0,
                outcome="void", profit=0.0)
    out = _bet_out(b, None)
    assert out.match_id is None and out.home_team is None and out.outcome == "void"
