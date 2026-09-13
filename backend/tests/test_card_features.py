"""A match with no card data is not a match with no cards.

Eight leagues send card counts in full, five in part and the other thirty-odd
none; since July 2024 only a quarter of training rows carry them. The nine
discipline features read a missing count as zero, so most recent rows told both
models that both sides had spotless records. Under `cards_missing_nan` a missing
count stays missing. Training fits under it and stamps it on the models it saves;
serving builds the frame the way the loaded model was fitted, so a model saved
before the change keeps being served exactly as before.

Also: `float(NaN or 0)` is NaN, so one refereed match without card data turned
that referee's card rate into NaN for every match after it.
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.ml import features
from backend.app.ml.features import (
    CARD_FEATURE_COLS, _team_card_feats, build_features, build_team_snapshot,
    compute_match_features,
)

ROOT = Path(__file__).resolve().parents[2]
NA = np.nan

#            date          home away hg ag  hy  ay  hr  ar  referee
HISTORY = [("2025-08-10", "A", "B", 1, 0, 2,  3,  0,  1,  "Ref One"),
           ("2025-08-17", "B", "C", 2, 2, NA, NA, NA, NA, "Ref One"),   # no card data
           ("2025-08-24", "C", "A", 0, 1, 1,  4,  0,  0,  "Ref One"),
           ("2025-08-31", "A", "C", 3, 1, NA, NA, NA, NA, None),
           ("2025-09-07", "B", "A", 1, 1, NA, NA, NA, NA, None)]
TARGET = date(2025, 9, 14)


def _frame(rows):
    return pd.DataFrame([dict(Date=pd.Timestamp(d), home_team=h, away_team=a,
                              home_goals=hg, away_goals=ag, League="EPL",
                              h_yellow=hy, a_yellow=ay, h_red=hr, a_red=ar, referee=ref)
                         for d, h, a, hg, ag, hy, ay, hr, ar, ref in rows])


def _train_row(cards_missing_nan):
    rows = HISTORY + [(TARGET.isoformat(), "A", "B", 0, 0, NA, NA, NA, NA, "Ref One")]
    return build_features(_frame(rows), cards_missing_nan=cards_missing_nan).iloc[-1]


def _served(cards_missing_nan):
    snap = build_team_snapshot(_frame(HISTORY), cards_missing_nan=cards_missing_nan)
    return compute_match_features(snap, "A", "B", "EPL", match_date=TARGET, referee="Ref One")


def _same(x, y):
    return (isinstance(x, float) and math.isnan(x) and math.isnan(y)) or x == pytest.approx(y)


@pytest.fixture(autouse=True)
def _two_refereed_matches_suffice(monkeypatch):
    monkeypatch.setattr(features, "_MIN_REF_MATCHES", 2)


def test_the_legacy_convention_is_unchanged():
    """A model saved before the stamp must be served exactly as it was fitted."""
    r = _train_row(False)
    # A: reds [0,0,0,0] yellows [2,4,0,0]; B: reds [1,0,0] yellows [3,0,0]
    assert (r.h_red_last1, r.h_reds_5, r.h_discipline_5, r.h_season_yellows) == (0.0, 0.0, 1.5, 6.0)
    assert (r.a_red_last1, r.a_reds_5) == (0.0, 1.0)
    assert r.a_discipline_5 == pytest.approx(5 / 3)
    assert r.suspension_diff == 0.0


def test_missing_cards_stay_missing():
    r = _train_row(True)
    # A's last two matches have no card data: the rate is over the two that do.
    assert math.isnan(r.h_red_last1)
    assert (r.h_reds_5, r.h_discipline_5, r.h_season_yellows) == (0.0, 3.0, 6.0)
    assert (r.a_reds_5, r.a_discipline_5, r.a_season_yellows) == (1.0, 5.0, 3.0)
    assert math.isnan(r.suspension_diff)


def test_a_side_with_no_card_data_at_all_is_missing_not_clean():
    assert all(math.isnan(v) for v in _team_card_feats([NA, NA], [NA, NA], 0, 0, True))
    # The legacy windows never hold NaN: a missing count was stored as 0.0.
    assert _team_card_feats([0.0, 0.0], [0.0, 0.0], 0, 2, False) == (0.0, 0.0, 0.0, 0.0)


@pytest.mark.parametrize("cards_missing_nan", [False, True])
def test_serving_builds_what_training_built(cards_missing_nan):
    trained, served = _train_row(cards_missing_nan), _served(cards_missing_nan)
    for col in CARD_FEATURE_COLS + ["ref_cards_per_game"]:
        assert _same(served[col], trained[col]), col


@pytest.mark.parametrize("cards_missing_nan", [False, True])
def test_a_card_less_match_does_not_poison_the_referee(cards_missing_nan):
    """Ref One: 7 cards (reds double), a match with no data, then 5."""
    assert _train_row(cards_missing_nan).ref_cards_per_game == pytest.approx(6.0)
    assert _served(cards_missing_nan)["ref_cards_per_game"] == pytest.approx(6.0)


def test_serving_follows_the_convention_the_model_was_saved_with(monkeypatch):
    from backend.app.ml import predict

    class _Stamped:
        feature_conventions = {"cards_missing_nan": True}

    monkeypatch.setattr(predict, "_get_models", lambda: (_Stamped(), None))
    assert predict.feature_conventions() == {"cards_missing_nan": True}
    monkeypatch.setattr(predict, "_get_models", lambda: (object(), None))
    assert predict.feature_conventions() == {}, "an unstamped model is a legacy model"


def test_training_fits_under_the_convention_it_stamps():
    src = (ROOT / "backend/app/ml/train.py").read_text()
    assert 'cards_missing_nan=FEATURE_CONVENTIONS["cards_missing_nan"]' in src
    assert src.count("feature_conventions = dict(FEATURE_CONVENTIONS)") == 2
    # Without this, dropna(core_feats) throws away every row a league sent no
    # cards for — three in four recent rows.
    assert "set(CARD_FEATURE_COLS)" in src.split("def prepare_data")[1].split("def split")[0]


@pytest.mark.parametrize("rel, call", [
    ("scripts/compute_predictions.py", "build_team_snapshot("),
    ("backend/app/ml/predict.py", "build_features("),
    ("scripts/backtest_2526.py", "build_features("),
])
def test_every_model_serving_path_passes_the_convention(rel, call):
    src = (ROOT / rel).read_text()
    i = src.index(call, src.index("def predict_match") if rel.endswith("predict.py") else 0)
    assert "cards_missing_nan=feature_conventions()" in src[i:i + 200], rel
