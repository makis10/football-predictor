"""
BTTS (Both Teams To Score) binary classifier.

GG/NG is harder to predict than Over/Under because it requires BOTH teams to
score (or fail to), regardless of total goals. The Poisson model gives ~50%
accuracy — barely better than chance. A dedicated binary classifier trained on
goals-scoring signals provides a meaningful improvement.

How it works:
  1. XGBClassifier binary: target = 1 if both teams scored, else 0
  2. Uses BTTS_FEATURE_COLS — subset focused on scoring rates, xG, form
  3. Isotonic calibration corrects class-imbalance bias
  4. At inference, classifier output replaces raw Poisson BTTS estimate

Usage:
  from backend.app.ml.btts_classifier import (
      fit_btts_classifier, save_btts_classifier, save_btts_calibrator,
      load_btts_classifier, load_btts_calibrator,
      predict_btts_prob, apply_btts_calibration,
  )
"""

from __future__ import annotations

import os
import pickle
from typing import Optional

import numpy as np
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBClassifier

from backend.app.ml.features import BTTS_FEATURE_COLS

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models")


def fit_btts_classifier(
    X_train: "pd.DataFrame",
    y_train: "np.ndarray",
    X_val:   "pd.DataFrame",
    y_val:   "np.ndarray",
    random_state: int = 13,
) -> "tuple[XGBClassifier, IsotonicRegression]":
    """
    Train BTTS binary classifier then fit isotonic calibrator on validation output.
    Returns (model, calibrator).
    """
    import pandas as pd

    btts_cols = [c for c in BTTS_FEATURE_COLS if c in X_train.columns]

    Xb_train = X_train[btts_cols]
    Xb_val   = X_val[btts_cols]
    yb_train = y_train.astype(int)
    yb_val   = y_val.astype(int)

    # No scale_pos_weight inflation — isotonic calibration handles class imbalance
    model = XGBClassifier(
        n_estimators=600,
        max_depth=4,
        learning_rate=0.03,
        subsample=0.75,
        colsample_bytree=0.7,
        min_child_weight=5,
        gamma=0.1,
        reg_alpha=0.15,
        reg_lambda=1.5,
        eval_metric="logloss",
        early_stopping_rounds=40,
        tree_method="hist",
        nthread=-1,
        random_state=random_state,
    )
    model.fit(
        Xb_train, yb_train,
        eval_set=[(Xb_val, yb_val)],
        verbose=False,
    )

    raw_probs  = model.predict_proba(Xb_val)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_probs, yb_val.astype(float))
    cal_probs  = calibrator.predict(raw_probs)

    btts_preds    = (cal_probs >= 0.5).astype(int)
    btts_acc      = (btts_preds == yb_val).mean()
    btts_recall   = yb_val[btts_preds == 1].mean() if btts_preds.sum() > 0 else 0.0
    actual_gg     = yb_val.mean()
    print(f"  [btts_clf] val acc={btts_acc:.3f}  "
          f"gg_recall={btts_recall:.3f}  "
          f"actual_gg_rate={actual_gg:.3f}  "
          f"mean_p_gg(cal)={cal_probs.mean():.3f}")
    return model, calibrator


def predict_btts_prob(
    btts_clf: "Optional[XGBClassifier]",
    feat: dict,
) -> "Optional[float]":
    """Run BTTS classifier on a single feature dict. Returns P(GG) or None."""
    import pandas as pd
    if btts_clf is None:
        return None
    btts_cols = [c for c in BTTS_FEATURE_COLS if c in feat]
    row = pd.DataFrame([{c: feat.get(c, np.nan) for c in BTTS_FEATURE_COLS}])
    return float(btts_clf.predict_proba(row)[0, 1])


def apply_btts_calibration(
    calibrator: "Optional[IsotonicRegression]",
    raw_prob: float,
) -> float:
    if calibrator is None:
        return raw_prob
    return float(calibrator.predict([raw_prob])[0])


def save_btts_classifier(model: XGBClassifier, models_dir: str = MODELS_DIR) -> None:
    os.makedirs(models_dir, exist_ok=True)
    path = os.path.join(models_dir, "model_btts_clf.pkl")
    with open(path, "wb") as f:
        pickle.dump(model, f)
    print(f"  BTTS classifier saved → {path}")


def save_btts_calibrator(calibrator: IsotonicRegression, models_dir: str = MODELS_DIR) -> None:
    os.makedirs(models_dir, exist_ok=True)
    path = os.path.join(models_dir, "calibrator_btts_clf.pkl")
    with open(path, "wb") as f:
        pickle.dump(calibrator, f)
    print(f"  BTTS calibrator saved  → {path}")


_btts_clf: Optional[XGBClassifier] = None
_btts_loaded: bool = False

_btts_cal: Optional[IsotonicRegression] = None
_btts_cal_loaded: bool = False


def load_btts_classifier(models_dir: str = MODELS_DIR) -> "Optional[XGBClassifier]":
    global _btts_clf, _btts_loaded
    if _btts_loaded:
        return _btts_clf
    path = os.path.join(models_dir, "model_btts_clf.pkl")
    try:
        with open(path, "rb") as f:
            _btts_clf = pickle.load(f)
        print("[btts_clf] BTTS classifier loaded.")
        _btts_loaded = True   # only mark loaded after successful load
    except FileNotFoundError:
        print("[btts_clf] No BTTS classifier found — using Poisson BTTS. "
              "Run `python -m backend.app.ml.train` to generate it.")
    except Exception as e:
        print(f"[btts_clf] Error loading BTTS classifier: {e}")
    return _btts_clf


def load_btts_calibrator(models_dir: str = MODELS_DIR) -> "Optional[IsotonicRegression]":
    global _btts_cal, _btts_cal_loaded
    if _btts_cal_loaded:
        return _btts_cal
    path = os.path.join(models_dir, "calibrator_btts_clf.pkl")
    try:
        with open(path, "rb") as f:
            _btts_cal = pickle.load(f)
        print("[btts_clf] BTTS calibrator loaded.")
        _btts_cal_loaded = True   # only mark loaded after successful load
    except FileNotFoundError:
        print("[btts_clf] No BTTS calibrator found — using raw BTTS classifier probs.")
    except Exception as e:
        print(f"[btts_clf] Error loading BTTS calibrator: {e}")
    return _btts_cal


def reload_btts_models() -> None:
    """Force-reload BTTS classifier and calibrator from disk (e.g. after retrain)."""
    global _btts_clf, _btts_loaded, _btts_cal, _btts_cal_loaded
    _btts_clf = None
    _btts_loaded = False
    _btts_cal = None
    _btts_cal_loaded = False
    print("[btts_clf] Cache cleared — will reload on next predict call.")
