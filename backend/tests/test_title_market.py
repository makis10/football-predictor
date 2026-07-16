"""
Best-effort title-market fetch + projection snapshot helpers.

The market fetch must DEGRADE, never raise: The Odds API offers league winner
outrights only while a season is live and only on some plans, so off-season it
must quietly return None and let the projection show model-only.
"""
import backend.app.ml.title_market as tm
from scripts.snapshot_projections import _primary_prob


def test_no_key_for_league_returns_none(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "dummy")
    # BrazilSerieA has no entry in TITLE_MARKET_KEYS → nothing to fetch.
    assert "BrazilSerieA" not in tm.TITLE_MARKET_KEYS
    assert tm.fetch_title_market("BrazilSerieA") is None


def test_no_api_key_returns_none(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    assert tm.fetch_title_market("EPL") is None


def test_network_failure_degrades_to_none(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "dummy")

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr("requests.get", _boom)
    assert tm.fetch_title_market("EPL") is None


def test_primary_prob_handles_both_projection_shapes():
    # Domestic projection team carries p_title; European one carries p_champion.
    assert _primary_prob({"p_title": 0.31}) == 0.31
    assert _primary_prob({"p_champion": 0.12}) == 0.12
    assert _primary_prob({}) == 0.0
