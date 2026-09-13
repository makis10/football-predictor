"""A match that has kicked off is never priced on request.

GET /predictions/{id} priced any match without a stored prediction. The CSV
history and the half-season backfill hold 6,000+ settled matches with none, and
each has a public page, so a visit wrote a "prediction" made after the result
into the graded record — 15 rows by 2026-09-13 — and ran the full-history
feature build for it: gigabytes a request, the likeliest cause of the backend
worker's out-of-memory kills. Only an upcoming fixture may be priced, one at a
time.

Offline: in-memory SQLite; predict_match is never allowed to run.
"""
from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models.match import Match
from backend.app.models.odds_history import OddsHistory
from backend.app.models.prediction import Prediction
from backend.app.routers import predictions as router


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Match.__table__, Prediction.__table__,
                                             OddsHistory.__table__])
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def _never_price(monkeypatch):
    import backend.app.ml.predict as predict

    def _boom(*_a, **_k):
        raise AssertionError("predict_match ran")
    monkeypatch.setattr(predict, "predict_match", _boom)


def _match(db, days, result=None):
    m = Match(match_date=date.today() + timedelta(days=days), kickoff_time=time(19, 0),
              league="EPL", season="2026/27", home_team="H", away_team="A", result=result,
              home_goals=None if result is None else 1, away_goals=None if result is None else 0)
    db.add(m)
    db.commit()
    return m.id


@pytest.mark.parametrize("days, result", [(-400, "H"), (-1, None), (0, "D")])
def test_a_match_that_has_kicked_off_is_not_priced(db, days, result):
    with pytest.raises(HTTPException) as e:
        router.get_prediction(_match(db, days, result), db)
    assert e.value.status_code == 404


def test_only_one_on_the_fly_prediction_runs_at_a_time(db):
    mid = _match(db, 2)
    assert router._ON_THE_FLY.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as e:
            router.get_prediction(mid, db)
        assert e.value.status_code == 503
    finally:
        router._ON_THE_FLY.release()
