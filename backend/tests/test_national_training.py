"""The national models learn from the matches they are asked about.

The windows were literals — calibration 2023, test 2024-01 to 2026-06 — so a
model retrained every morning never fit a match played after 2022, and its test
window stopped admitting results in June 2026. Early stopping then took the
newest 15% of what was left and nothing put it back, so the shipped trees ended
in mid-2018. LightGBM was handed the fold with no early-stopping callback, so it
always trained its full 500 trees.
"""
from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
from lightgbm import LGBMClassifier
from xgboost import XGBClassifier

from backend.app.ml.national.train import CAL_MONTHS, TEST_MONTHS, national_windows
from backend.app.ml.refit import refit_on_everything

ROOT = Path(__file__).resolve().parents[2]


def test_the_windows_roll_with_the_data():
    assert national_windows(pd.Timestamp("2026-09-12")) == (
        pd.Timestamp("2024-10-01"), pd.Timestamp("2025-10-01"), pd.Timestamp("2026-10-01"))
    later = national_windows(pd.Timestamp("2027-03-02"))
    assert later > national_windows(pd.Timestamp("2026-09-12"))


@pytest.mark.parametrize("newest", ["2026-09-01", "2026-09-30", "2026-12-31", "2027-01-01"])
def test_the_newest_match_is_always_in_the_test_window(newest):
    cal, ts, te = national_windows(pd.Timestamp(newest))
    assert ts <= pd.Timestamp(newest) < te
    assert ts - pd.DateOffset(months=CAL_MONTHS) == cal
    assert te - pd.DateOffset(months=TEST_MONTHS) == ts


@pytest.mark.parametrize("kind", ["xgb", "lgb"])
def test_refit_pins_the_tree_count_early_stopping_found(kind):
    rng = np.random.default_rng(0)
    X = rng.normal(size=(600, 4))
    y = (X[:, 0] + rng.normal(scale=2.0, size=600) > 0).astype(int)
    if kind == "xgb":
        m = XGBClassifier(n_estimators=400, learning_rate=0.3, early_stopping_rounds=10,
                          eval_metric="logloss")
        m.fit(X[:400], y[:400], eval_set=[(X[400:], y[400:])], verbose=False)
        best = m.best_iteration
    else:
        m = LGBMClassifier(n_estimators=400, learning_rate=0.3, verbosity=-1)
        m.fit(X[:400], y[:400], eval_set=[(X[400:], y[400:])],
              callbacks=[lgb.early_stopping(10, verbose=False)])
        best = m.best_iteration_
    assert 0 < best < 399, "the fixture must actually stop early"

    refit = refit_on_everything(m, X, y, np.ones(len(y)), kind)
    assert refit is not m
    assert refit.get_params()["n_estimators"] == best + 1


def test_every_national_booster_is_refit_after_early_stopping():
    src = (ROOT / "backend/app/ml/national/train.py").read_text()
    assert src.split("def train(")[1].count("refit_on_everything(") == 8   # 4 models × 2
    lgb_fit = src.split("def _train_lgb")[1].split("\ndef ")[0]
    assert "lgb.early_stopping(" in lgb_fit, "LightGBM must stop early, or the fold decides nothing"


def test_no_frozen_window_survives():
    train_src = (ROOT / "backend/app/ml/national/train.py").read_text()
    blend_src = (ROOT / "scripts/fit_national_blend.py").read_text()
    for name in ("CAL_START", "TEST_START", "TEST_END"):
        assert name not in train_src and name not in blend_src, name
    assert "national_windows(" in blend_src, "the blend must select on the trainer's own windows"


def test_training_metrics_report_the_path_visitors_are_served(tmp_path, monkeypatch):
    """metrics.json describes the model before the Elo blend, which no visitor
    is shown. The endpoint must also carry the served path's holdout numbers."""
    import json

    from backend.app.routers import national

    (tmp_path / "metrics.json").write_text(json.dumps({"result_accuracy": 0.64}))
    (tmp_path / "blend.json").write_text(json.dumps({
        "elo_blend_w": 0.7, "test_window": ["2026-04-01", "2026-10-01"],
        "actual_test_draw_rate": 0.23,
        "test_report": {"fitted": {"accuracy": 0.61, "log_loss": 0.83,
                                   "draw_share_predicted": 0.0, "n": 786}}}))
    monkeypatch.setattr(national, "_METRICS_PATH", tmp_path / "metrics.json")
    monkeypatch.setattr(national, "_BLEND_PATH", tmp_path / "blend.json")

    out = national.training_metrics()
    assert out["available"] and out["result_accuracy"] == 0.64
    assert out["served"]["accuracy"] == 0.61 and out["served"]["n"] == 786
    assert out["served"]["window"] == ["2026-04-01", "2026-10-01"]

    (tmp_path / "blend.json").unlink()
    assert national.training_metrics()["served"] is None


def test_one_refit_for_both_trainers():
    club = (ROOT / "backend/app/ml/train.py").read_text()
    assert "from backend.app.ml.refit import refit_on_everything" in club
    assert "def _refit_on_everything" not in club
