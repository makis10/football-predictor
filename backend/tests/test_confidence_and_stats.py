"""Confidence label + stats correctness helpers."""
from backend.app.ml.predict import _confidence
from backend.app.routers.stats import _predicted_result, _goals_correct, _top_pick_correct


def test_confidence_high_requires_clear_result_and_goal_signal():
    assert _confidence(0.60, 0.70) == "high"


def test_confidence_medium_when_goals_are_coinflip():
    # Clear-ish result but Over ≈ 50/50 → not high.
    assert _confidence(0.60, 0.50) == "medium"


def test_confidence_low_when_result_uncertain():
    assert _confidence(0.30, 0.80) == "low"


def test_predicted_result_picks_argmax():
    assert _predicted_result({"home_win_prob": 0.5, "draw_prob": 0.3, "away_win_prob": 0.2}) == "H"
    assert _predicted_result({"home_win_prob": 0.1, "draw_prob": 0.2, "away_win_prob": 0.7}) == "A"


def test_goals_correct_over_under():
    over_pred = {"home_goals": 2, "away_goals": 1, "goals_prediction": "OVER"}   # 3 goals
    under_pred = {"home_goals": 1, "away_goals": 0, "goals_prediction": "UNDER"}  # 1 goal
    wrong = {"home_goals": 0, "away_goals": 0, "goals_prediction": "OVER"}        # 0 goals
    assert _goals_correct(over_pred)
    assert _goals_correct(under_pred)
    assert not _goals_correct(wrong)


def test_top_pick_correct_parses_market_string():
    row = {"suggested_market": "Home Win @ 2.10", "result": "H",
           "home_goals": 1, "away_goals": 0}
    assert _top_pick_correct(row) is True

    row_over = {"suggested_market": "Over 2.5 @ 1.85", "result": "H",
                "home_goals": 2, "away_goals": 2}
    assert _top_pick_correct(row_over) is True

    row_none = {"suggested_market": None, "result": "H",
                "home_goals": 1, "away_goals": 0}
    assert _top_pick_correct(row_none) is None
