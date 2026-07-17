"""Unified imputation artifact + parametrized national Elo blend.

Model artifacts (backend/data/models/*) are gitignored — they only exist after
a local retrain, NEVER in a fresh CI checkout. So artifact-dependent assertions
are guarded with pytest.skip; the artifact-free behaviour (graceful fallback,
caching, the pure Elo math) is always tested.
"""
import json
import os

import pytest

from backend.app.ml.predict import get_impute_medians, MODELS_DIR
from backend.app.ml.national.features import elo_three_way

_MEDIANS_PATH = os.path.join(MODELS_DIR, "impute_medians.json")


def test_impute_medians_artifact_sane_when_present():
    if not os.path.exists(_MEDIANS_PATH):
        pytest.skip("impute_medians.json absent (no local retrain / fresh CI checkout)")
    d = json.load(open(_MEDIANS_PATH))
    assert len(d) >= 20
    # Regression guard for the train/serve skew this artifact fixes: shots
    # median must be the training value (~4.2), never the legacy 0.0 serve fill.
    assert d["h_shots_ot_5"] > 3.0
    assert 0.8 < d["poisson_lambda_home"] < 2.0


def test_get_impute_medians_caches_and_is_graceful():
    # Loader must be safe both ways: returns a dict, cached singleton, all floats.
    # When the artifact is absent it returns {} (never raises) — the serve path
    # relies on that fallback.
    m1 = get_impute_medians()
    m2 = get_impute_medians()
    assert m1 is m2                                  # cached singleton
    assert isinstance(m1, dict)
    assert all(isinstance(v, float) for v in m1.values())
    if os.path.exists(_MEDIANS_PATH):
        assert m1["h_shots_ot_5"] > 3.0              # training value, not legacy 0.0


def test_elo_three_way_sums_to_one_and_orders():
    h, d, a = elo_three_way(200.0)
    assert abs(h + d + a - 1.0) < 1e-9
    assert h > a                          # favourite favoured
    h2, d2, a2 = elo_three_way(0.0)
    assert abs(h2 - a2) < 1e-9            # even match symmetric
    assert d2 > d                         # draws peak for even games


def test_elo_three_way_respects_fitted_params():
    # Larger scale flattens the win share; larger draw_base raises draws.
    h_sharp, _, _ = elo_three_way(150.0, scale=80.0)
    h_flat,  _, _ = elo_three_way(150.0, scale=180.0)
    assert h_sharp > h_flat
    _, d_lo, _ = elo_three_way(0.0, draw_base=0.22)
    _, d_hi, _ = elo_three_way(0.0, draw_base=0.30)
    assert d_hi > d_lo


def test_blend_json_consistent_when_present():
    path = os.path.join(MODELS_DIR, "national", "blend.json")
    if not os.path.exists(path):
        return   # pre-fit environments: nothing to check
    b = json.load(open(path))
    assert 0.0 <= b["elo_blend_w"] <= 1.0
    assert b["scale"] > 0 and 0.1 < b["draw_base"] < 0.4
    # The persisted holdout report must exist — it IS the honest production metric.
    assert "test_report" in b and "fitted" in b["test_report"]
