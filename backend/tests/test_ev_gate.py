"""Value-bet gate: pure-model EV, kill-switch, team-name matching.

2026-06-17: predictions are market-independent. shrunk_ev uses the PURE model
probability vs the market price (MARKET_SHRINKAGE=0) — the market is the thing
we compare against, not an input. The kill-switch (SUGGESTABLE_MARKETS) is a
per-market risk filter that stays.
"""
from backend.app.ml import odds_analysis_service as svc


def test_shrunk_ev_is_pure_model_ev():
    # MARKET_SHRINKAGE=0 → p' = model = 0.6 ; EV = 0.6*2.2 - 1
    assert svc.MARKET_SHRINKAGE == 0.0
    ev = svc.shrunk_ev(
        "Home Win",
        {"home_win": 0.6, "draw": 0.2, "away_win": 0.2, "over_2_5": 0.5},
        {"home_win": 0.5},
        {"home_win": 2.2},
    )
    assert ev is not None
    assert abs(ev - (0.6 * 2.2 - 1)) < 1e-9


def test_shrunk_ev_none_without_fair_prob():
    assert svc.shrunk_ev("Home Win", {"home_win": 0.6}, {}, {"home_win": 2.2}) is None


def test_killswitch_blocks_non_suggestable_market():
    # Over 2.5 has a huge raw EV but is NOT in SUGGESTABLE_MARKETS → never suggested.
    ev = {"Over 2.5": 1.0}
    raw = {"over_2_5": 3.0}
    fair = {"over_2_5": 0.6}
    model = {"home_win": 0.3, "draw": 0.3, "away_win": 0.4, "over_2_5": 0.9}
    assert svc._top_ev_markets(ev, raw, fair_probs=fair, model_probs=model) == []


def test_suggestable_market_passes_when_value_is_real():
    ev = {"Home Win": 0.32}
    raw = {"home_win": 2.2, "draw": 3.4, "away_win": 3.6}
    fair = {"home_win": 0.5, "draw": 0.28, "away_win": 0.22}
    model = {"home_win": 0.6, "draw": 0.2, "away_win": 0.2, "over_2_5": 0.5}
    out = svc._top_ev_markets(ev, raw, fair_probs=fair, model_probs=model)
    assert out and out[0].startswith("Home Win @")


def test_suggestable_set_is_only_home_and_draw():
    # Documents the current kill-switch; failing this should be a deliberate change.
    assert svc.SUGGESTABLE_MARKETS == {"Home Win", "Draw"}
