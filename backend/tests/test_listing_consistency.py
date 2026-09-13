"""The listing card and the match page must say the same thing.

Each of these was a card/page disagreement the 2026-09-09 audit found:
  · the card's confidence ignored "no history for either side", so a fixture
    priced from default features could read high on the card and low on its
    page — beside an "unknown teams" note;
  · the card applied a still-cached injury adjustment to finished matches, and
    kept the stored pick and EV beside the adjusted bars;
  · at exactly 50% the card said OVER and the page UNDER;
  · the Medium+/High filter read the stored confidence column instead of the
    confidence the card shows;
  · /matches/export turned an unknown status into a historical export.
"""
from __future__ import annotations

import inspect
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import backend.app.cache as cache
import backend.app.ml.injury_adjustment as inj
from backend.app.routers import matches as M
from backend.app.routers import predictions as P


def _pred(**kw):
    fields = dict(home_win_prob=0.62, draw_prob=0.22, away_win_prob=0.16, over_2_5_prob=0.64,
                  model_version="test", suggested_market="Home Win", ev_score=0.05,
                  insufficient_data=False, goals_prediction="OVER", btts_prob=0.55,
                  btts_prediction="GG", confidence="high")
    fields.update(kw)
    return SimpleNamespace(**fields)


def _call(fn, **kw):
    """Call a FastAPI endpoint function directly, taking Query() defaults."""
    args = {}
    for name, p in inspect.signature(fn).parameters.items():
        if name in kw:
            args[name] = kw[name]
        else:
            args[name] = getattr(p.default, "default", p.default)
    return fn(**args)


def test_no_history_means_low_confidence_on_the_card_too():
    card = M._adjust_prediction_embed(1, _pred(insufficient_data=True), "Bundesliga")
    assert card.confidence == "low"


@pytest.fixture()
def warm_injuries(monkeypatch):
    monkeypatch.setattr(cache, "cache_get", lambda key: {"home": ["x"], "away": []})
    monkeypatch.setattr(inj, "has_significant_injuries", lambda h, a: True)
    monkeypatch.setattr(inj, "adjust_probabilities",
                        lambda hw, d, aw, ov, h, a: (0.30, 0.25, 0.45, 0.55))


def test_a_finished_match_is_not_adjusted(warm_injuries):
    card = M._adjust_prediction_embed(1, _pred(), "Bundesliga", result="H")
    assert (card.home_win_prob, card.suggested_market) == (0.62, "Home Win")


def test_an_adjusted_card_drops_the_pick_computed_before_the_adjustment(warm_injuries):
    card = M._adjust_prediction_embed(1, _pred(), "Bundesliga")
    assert card.away_win_prob == 0.45
    assert (card.suggested_market, card.ev_score) == (None, None)


def test_card_and_page_label_goals_alike_at_exactly_half():
    match = SimpleNamespace(id=1, home_team="A", away_team="B", league="Bundesliga",
                            match_date=date(2026, 9, 20), result=None)
    pred = _pred(over_2_5_prob=0.5, goals_prediction="UNDER")
    page = P._build_response(match, pred)
    card = M._adjust_prediction_embed(1, pred, "Bundesliga")
    assert page.goals.prediction == card.goals_prediction == "OVER"


def test_the_medium_plus_filter_uses_the_confidence_the_card_shows():
    """Stored "low" but served "high" must pass Medium+; stored "high" but
    served "low" (no history) must not."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend.app.database import Base
    from backend.app.models.match import Match
    from backend.app.models.prediction import Prediction

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Match.__table__, Prediction.__table__])
    day = date.today() + timedelta(days=5)
    with Session(engine) as db:
        for i, (stored, insufficient) in enumerate((("low", False), ("high", True))):
            m = Match(match_date=day, league="Bundesliga", season="2026",
                      home_team=f"H{i}", away_team=f"A{i}")
            db.add(m)
            db.flush()
            db.add(Prediction(match_id=m.id, home_win_prob=0.66, draw_prob=0.2,
                              away_win_prob=0.14, over_2_5_prob=0.66,
                              goals_prediction="OVER", confidence=stored,
                              model_version="test", insufficient_data=insufficient))
        db.commit()
        out = _call(M.list_matches, db=db, status="upcoming", min_confidence="medium")
    assert [(r.home_team, r.prediction.confidence) for r in out] == [("H0", "high")]


def test_export_rejects_an_unknown_status(monkeypatch):
    monkeypatch.setattr(M, "rate_limit_check", lambda *a, **k: True)
    monkeypatch.setattr(M, "client_ip", lambda request: "127.0.0.1")
    with pytest.raises(HTTPException) as exc:
        _call(M.export_picks, request=None, status="pst", db=None)
    assert exc.value.status_code == 400
