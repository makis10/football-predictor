"""A de-vig needs the whole book, and the value gate needs our own numbers.

- _parse_game_odds normalised by whatever sides happened to be quoted. A book
  quoting Over 2.5 with no Under — or a 1×2 with no draw — divided one side by
  itself and published a 100% market-implied probability, which also passed
  the value gate's minimum-probability filter trivially.
- A failed national odds fetch was cached for six hours as "no market"; the
  club path caches an empty answer for two minutes.
- The national analysis fed the value gate the served probabilities, where the
  club path uses the unanchored raw_* twins.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import backend.app.ml.odds_analysis_service as svc


def _game(markets):
    return {"home_team": "Home FC", "away_team": "Away FC", "id": "",
            "bookmakers": [{"title": "Book", "markets": markets}]}


H2H = {"key": "h2h", "outcomes": [{"name": "Home FC", "price": 2.0},
                                  {"name": "Draw", "price": 3.4},
                                  {"name": "Away FC", "price": 3.9}]}


def _totals(*sides):
    return {"key": "totals",
            "outcomes": [{"name": n, "price": p, "point": 2.5} for n, p in sides]}


def test_a_whole_book_is_de_vigged_to_one():
    fp = svc._parse_game_odds(_game([H2H, _totals(("Over", 1.9), ("Under", 1.95))]))["fair_probs"]
    assert fp["home_win"] + fp["draw"] + fp["away_win"] == pytest.approx(1.0, abs=1e-3)
    assert fp["over_2_5"] + fp["under_2_5"] == pytest.approx(1.0, abs=1e-3)


def test_one_side_of_a_market_is_not_a_certainty():
    parsed = svc._parse_game_odds(_game([_totals(("Over", 1.9))]))
    assert parsed["fair_probs"].get("over_2_5") is None
    assert parsed["raw_odds"]["over_2_5"] == 1.9        # the price itself is still shown


def test_a_1x2_without_a_draw_price_is_not_de_vigged():
    h2h = {"key": "h2h", "outcomes": [{"name": "Home FC", "price": 1.5},
                                      {"name": "Away FC", "price": 2.5}]}
    fp = svc._parse_game_odds(_game([h2h]))["fair_probs"]
    assert fp.get("home_win") is None and fp.get("away_win") is None


def test_an_implausible_book_is_not_de_vigged():
    """Implied probabilities summing to 1.62 are a data error, not a margin."""
    fp = svc._parse_game_odds(_game([_totals(("Over", 1.1), ("Under", 1.4))]))["fair_probs"]
    assert fp.get("over_2_5") is None


def test_a_failed_national_fetch_is_cached_briefly(monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "ODDS_API_KEY", "test-key")
    monkeypatch.setattr(svc, "cache_get", lambda key: svc.CACHE_MISS)
    monkeypatch.setattr(svc, "cache_set", lambda key, val, ttl: calls.append((key, val, ttl)))

    def _timeout(*a, **k):
        raise RuntimeError("read timed out")

    monkeypatch.setattr(svc.odds_budget, "get", _timeout)
    assert svc._fetch_national_games_cached("soccer_fifa_world_cup") == []
    assert calls == [("league_odds:national:soccer_fifa_world_cup", [], svc.EMPTY_ODDS_TTL)]


def test_the_national_value_gate_reads_our_unanchored_probabilities(monkeypatch):
    import backend.app.rate_limit as rl
    import backend.app.routers.national as N

    seen: dict = {}

    class _Stop(Exception):
        pass

    def _comparison(**kw):
        seen.update(kw["model_probs"])
        raise _Stop

    monkeypatch.setattr(svc, "run_national_comparison", _comparison)
    monkeypatch.setattr(rl, "rate_limit_check", lambda *a, **k: True)
    pred = SimpleNamespace(
        id=1, home_team="A", away_team="B", tournament="Friendly", match_date="2026-10-10",
        home_win_prob=0.60, draw_prob=0.25, away_win_prob=0.15, over_2_5_prob=0.50,
        btts_prob=0.45, raw_home_prob=0.40, raw_draw_prob=0.30, raw_away_prob=0.30,
        raw_over_prob=0.55)

    class _Query:
        def filter(self, *a):
            return self

        def first(self):
            return pred

    db = SimpleNamespace(query=lambda model: _Query())
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
    with pytest.raises(_Stop):
        N.get_national_analysis(1, request=request, db=db)
    assert (seen["home_win"], seen["over_2_5"], seen["btts"]) == (0.40, 0.55, 0.45)
