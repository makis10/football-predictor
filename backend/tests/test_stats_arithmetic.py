"""The /stats payload's new arithmetic, which shipped with no test at all.

An independent review on 2026-09-08 found roughly eighty lines of new
measurement in a public endpoint — two hand-rolled statistics, three baselines,
a national-row counter and a threshold change — with not one assertion anywhere.
Every one of them is a pure function over a list of rows, so there was no excuse
beyond having written them in a hurry.

Two of the numbers were also wrong, and the tests below are the ones that would
have said so.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.app.routers.stats import (
    _MIN_STAT_ROWS,
    _accuracy_slice,
    _auc,
    _resolution,
)


def _rows(n, *, over=0, national=0, result="H", results=None):
    """Minimal row dicts in the shape _load_rows produces."""
    out = []
    for i in range(n):
        r = results[i] if results else result
        goals = (2, 1) if i < over else (1, 0)      # over 2.5 for the first `over`
        out.append({
            "result": r,
            "home_goals": goals[0], "away_goals": goals[1],
            "goals_prediction": "OVER",
            "home_win_prob": 0.5, "draw_prob": 0.3, "away_win_prob": 0.2,
            "over_2_5_prob": 0.6,
            "is_national": i < national,
        })
    return out


# ── AUC ───────────────────────────────────────────────────────────────────────

def test_auc_matches_a_known_good_implementation_including_ties():
    """It is hand-rolled with its own tie-averaging loop, which is the part most
    likely to be subtly wrong."""
    sklearn_metrics = pytest.importorskip("sklearn.metrics")
    rng = np.random.RandomState(0)
    worst = 0.0
    for _ in range(120):
        n = int(rng.randint(_MIN_STAT_ROWS, 400))
        # Few distinct values ⇒ heavy ties, which is the case the loop exists for.
        p = list(rng.choice([0.3, 0.5, 0.5, 0.7], size=n))
        y = list(rng.rand(n) < np.array(p))
        if len(set(y)) < 2:
            continue
        mine = _auc(p, y)
        theirs = sklearn_metrics.roc_auc_score(y, p)
        worst = max(worst, abs(mine - theirs))
    assert worst < 1e-9, f"largest disagreement with sklearn: {worst}"


def test_auc_of_a_constant_forecast_is_exactly_a_coin():
    p = [0.53] * 300
    y = [i % 2 == 0 for i in range(300)]
    assert _auc(p, y) == pytest.approx(0.5)


@pytest.mark.parametrize("y", [[True] * 300, [False] * 300])
def test_auc_declines_when_one_class_is_missing(y):
    assert _auc([0.5] * 300, y) is None


def test_neither_statistic_is_published_off_a_handful_of_rows():
    """Ireland's 20 settled matches were rendering an AUC of 0.271 and a
    resolution of 0.054 on the public page, with the same visual weight as the
    2,064-row figures beside them."""
    assert _MIN_STAT_ROWS >= 100
    rng = np.random.RandomState(1)
    n = _MIN_STAT_ROWS - 1
    p = list(rng.rand(n))
    y = list(rng.rand(n) < 0.5)
    assert _auc(p, y) is None
    assert _resolution(p, y) is None


# ── resolution ────────────────────────────────────────────────────────────────

def test_resolution_of_a_constant_forecast_is_zero():
    """Zero information must read as zero, however well calibrated."""
    assert _resolution([0.55] * 400, [i % 20 < 11 for i in range(400)]) == pytest.approx(0.0)


def test_resolution_is_near_zero_on_data_with_no_signal():
    """The naive plug-in estimator is NOT zero here — it carries a positive term
    of about Var(y)·K/n from estimating each bucket's rate on the rows it then
    scores. On the live BTTS sample it published 0.00346 where the null mean was
    0.00335, i.e. essentially all bias, while the AUC on the same card said 0.514.
    """
    rng = np.random.RandomState(2)
    vals = []
    for _ in range(60):
        n = 2000
        p = list(np.clip(rng.normal(0.55, 0.05, n), 0.01, 0.99))   # spread, no signal
        y = list(rng.rand(n) < 0.55)                                # independent of p
        v = _resolution(p, y)
        if v is not None:
            vals.append(v)
    assert np.mean(vals) < 0.001, f"still biased upward: mean {np.mean(vals):.5f}"


def test_resolution_still_sees_a_forecast_that_does_carry_information():
    """Debiasing must not flatten a real signal to zero."""
    rng = np.random.RandomState(3)
    p = np.clip(rng.normal(0.55, 0.15, 3000), 0.02, 0.98)
    y = rng.rand(3000) < p
    v = _resolution(list(p), list(y))
    assert v is not None and v > 0.005, v


def test_resolution_never_goes_negative():
    """The sampling correction can overshoot on noise; a negative 'share of
    variance explained' is not a number anyone can read."""
    rng = np.random.RandomState(4)
    for _ in range(40):
        n = 300
        p = list(np.clip(rng.normal(0.5, 0.02, n), 0.01, 0.99))
        y = list(rng.rand(n) < 0.5)
        v = _resolution(p, y)
        assert v is None or v >= 0.0


# ── baselines and the national mix ────────────────────────────────────────────

def test_the_goals_baseline_is_the_actual_over_rate():
    slice_ = _accuracy_slice(_rows(200, over=120))
    assert slice_.goals_baseline == pytest.approx(0.60)


def test_the_result_baseline_is_the_share_of_the_most_common_actual_result():
    results = ["H"] * 90 + ["D"] * 60 + ["A"] * 50
    slice_ = _accuracy_slice(_rows(200, results=results))
    assert slice_.result_baseline == pytest.approx(90 / 200)


def test_the_baselines_are_what_the_colour_coding_needs():
    """The bug they exist for: a hardcoded green threshold of 0.57 sat within
    0.06pp of the always-OVER base rate, so the O/U card rendered green for an
    edge indistinguishable from a constant while 1x2 rendered yellow for a real
    one. Whatever the accent function does, it needs a per-slice floor."""
    # These rows predict OVER every time, so the forecast carries no information
    # at all — and its accuracy is EXACTLY the base rate, in both slices. That is
    # the whole argument for shipping the baseline: 70% correct and 40% correct
    # are the same forecast, and only the second number tells you so.
    busy = _accuracy_slice(_rows(200, over=140))     # 70% of these went over
    quiet = _accuracy_slice(_rows(200, over=80))     # 40% did

    assert busy.goals_accuracy == pytest.approx(busy.goals_baseline)
    assert quiet.goals_accuracy == pytest.approx(quiet.goals_baseline)
    assert busy.goals_accuracy == pytest.approx(0.70)
    assert quiet.goals_accuracy == pytest.approx(0.40)
    # …so the edge is zero in both, which is what a colour should be reading.
    assert busy.goals_accuracy - busy.goals_baseline == pytest.approx(0.0)


def test_the_national_share_of_every_slice_is_reported():
    """One model-history row read '68.8% over 80 matches' of which 79 were
    international fixtures from a different pipeline with a much better record."""
    assert _accuracy_slice(_rows(80, national=79)).national_total == 79
    assert _accuracy_slice(_rows(80)).national_total == 0


def test_an_empty_slice_does_not_divide_by_zero():
    empty = _accuracy_slice([])
    assert empty.total == 0
    assert empty.result_baseline == 0.0 and empty.goals_baseline == 0.0
    assert empty.national_total == 0
