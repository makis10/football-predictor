"""Dynamic value-gate: qualifying vs watch vs proven, and per-market settlement.

Since 2026-06-30 the national gate no longer hard-hides non-{Home,Draw} markets.
A market that clears the EV/sanity filters is either a headline suggestion (if
its new-model record has PROVEN it) or a shadow-tracked "watch" market. These
tests pin that behaviour + the settlement logic that decides promotion.
"""
from backend.app.ml import odds_analysis_service as svc

# The France-vs-Sweden-style example from the app: GG has a real model edge
# (0.53 @ 2.33 → +23% EV) but is not a proven market.
MODEL = {"home_win": 0.60, "draw": 0.24, "away_win": 0.16, "over_2_5": 0.54, "btts": 0.53}
RAW = {"home_win": 1.33, "draw": 4.5, "away_win": 7.0, "over_2_5": 1.82,
       "under_2_5": 1.99, "btts_yes": 2.33, "btts_no": 1.62}
FAIR = {"home_win": 0.72, "draw": 0.18, "away_win": 0.09, "over_2_5": 0.52,
        "under_2_5": 0.48, "btts_yes": 0.41, "btts_no": 0.59}


def _ev():
    return svc._compute_ev(MODEL, {"raw_odds": RAW})


def test_gg_qualifies_no_longer_hard_hidden():
    q = svc._qualifying_markets(_ev(), RAW, FAIR, MODEL)
    assert "GG" in q                     # passes EV + sanity filters
    assert q["GG"] > 0.05                # meaningfully positive EV


def test_gg_is_watch_when_not_proven():
    ev = _ev()
    proven = {"Home Win", "Draw"}
    # Not a headline suggestion...
    assert svc._top_ev_markets(ev, RAW, fair_probs=FAIR, model_probs=MODEL,
                               suggestable=proven) == []
    # ...but surfaced as a watch market (shown + shadow-tracked).
    watch = svc._watch_markets(ev, RAW, fair_probs=FAIR, model_probs=MODEL,
                               suggestable=proven)
    assert any(w["market"].startswith("GG @") for w in watch)
    assert watch[0]["ev_pct"] > 0


def test_gg_promotes_once_proven():
    ev = _ev()
    proven = {"Home Win", "Draw", "GG"}
    out = svc._top_ev_markets(ev, RAW, fair_probs=FAIR, model_probs=MODEL,
                              suggestable=proven)
    assert any(m.startswith("GG @") for m in out)
    # And it drops out of the watch list once promoted.
    watch = svc._watch_markets(ev, RAW, fair_probs=FAIR, model_probs=MODEL,
                               suggestable=proven)
    assert not any(w["market"].startswith("GG @") for w in watch)


def test_default_suggestable_is_static_backcompat():
    # No `suggestable` passed → the club path's static kill-switch still applies.
    assert svc._top_ev_markets(_ev(), RAW, fair_probs=FAIR, model_probs=MODEL) == []


def test_market_won_covers_every_market():
    # France 3-0 Sweden (home win, over, no-GG).
    assert svc._market_won("Home Win", "H", 3, 0) is True
    assert svc._market_won("Away Win", "H", 3, 0) is False
    assert svc._market_won("Over 2.5", "H", 3, 0) is True
    assert svc._market_won("GG", "H", 3, 0) is False
    assert svc._market_won("NG", "H", 3, 0) is True
    # A 1-1 draw (draw, under, GG).
    assert svc._market_won("Draw", "D", 1, 1) is True
    assert svc._market_won("Under 2.5", "D", 1, 1) is True
    assert svc._market_won("GG", "D", 1, 1) is True
    assert svc._market_won("NG", "D", 1, 1) is False


def test_market_won_none_without_data():
    assert svc._market_won("Home Win", None, None, None) is None
