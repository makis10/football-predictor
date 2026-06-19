"""
Draw-specialist binary classifier.

Draws are the hardest outcome to predict — they're the most stochastic and
market odds are weakest at separating them from tight wins.  A dedicated binary
classifier (target = 1 if draw, else 0) trained on draw-specific signals adds
an orthogonal view that, when blended with the result model's raw draw
probability, improves draw recall significantly.

How it works:
  1. XGBClassifier binary: target = (result == Draw)
  2. Uses DRAW_FEATURE_COLS — a subset focused on draw-relevant signals
     (draw rates, market draw prob, score tightness, referee tendencies, etc.)
  3. At inference, blend with result model:
       final_p_draw = alpha * draw_clf_prob + (1 - alpha) * result_p_draw
     where alpha controls how much weight we give the specialist.
  4. Renormalize home/away so all three sum to 1.

Usage:
  from backend.app.ml.draw_classifier import (
      DRAW_FEATURE_COLS, fit_draw_classifier, save_draw_classifier,
      load_draw_classifier, blend_draw_probability,
  )
"""

from __future__ import annotations

import os
import pickle
from typing import Optional

import numpy as np
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBClassifier

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models")

# ── Feature subset for the draw specialist ───────────────────────────────────
# Chosen for draw-relevant signal. The full FEATURE_COLS list includes many
# features that are informative about home/away wins but noisy for draws.
# A focused subset lets the specialist be more decisive.
DRAW_FEATURE_COLS = [
    # Recent draw tendency per team
    "h_draw_rate_5",       "a_draw_rate_5",
    "h_draw_rate_10",      "a_draw_rate_10",
    # Head-to-head draw statistics (last 5 meetings)
    "h2h_draws",
    "h2h_draw_rate",       # fraction of H2H meetings that ended in a draw
    # Season phase — late-season matches often more conservative / higher draw rate
    "season_phase",
    "season_week",
    # (market_draw_prob removed — predictions are market-independent by directive)
    # Elo: close ratings → more draws
    "elo_diff",
    "elo_home_win_prob",
    # Pi-Rating differentials: small diff → tight match → draw more likely
    "pi_att_diff",
    "pi_def_diff",
    "pi_exp_diff",
    "pi_exp_total",        # low total expected goals → draw more likely
    # Poisson draw probability
    "poisson_draw",
    "poisson_home_win",
    "poisson_away_win",
    "poisson_btts",        # Both Teams To Score: low BTTS → 0-0 or 1-0 / 0-1 → draw skews 0-0
    # Referee draw tendency (EPL only; NaN for others)
    "ref_draw_rate",
    # Recent form: similar points → tight match
    "h_form_5",            "a_form_5",
    "h_form_10",           "a_form_10",
    # Goal-scoring averages: both scoring low → draw likely
    "h_goals_scored_5",    "a_goals_scored_5",
    "h_goals_conceded_5",  "a_goals_conceded_5",
    "h_over25_rate_5",     "a_over25_rate_5",
    # League dummies: draw rates differ by league
    "league_EPL",          "league_LaLiga",    "league_SerieA",
    "league_Bundesliga",   "league_Ligue1",    "league_GreekSL",
    # Draw-balance features (new — capture match symmetry directly)
    "goals_asymmetry_5",      # abs(h_scored - a_scored): low = matched offences
    "combined_draw_tendency", # sqrt(h_draw_rate * a_draw_rate): both teams draw-prone
    "pi_closeness",           # 1/(1+|pi_att_diff|+|pi_def_diff|): evenly matched
    # market_draw_edge removed — market-independent by directive
    "low_total_xg",           # 1 if pi_exp_total < 2.0: defensive match flag
    "elo_closeness",          # 1/(1+|elo_diff|): close Elo ratings
]


# ── Fitting ───────────────────────────────────────────────────────────────────

def fit_draw_classifier(
    X_train: "pd.DataFrame",
    y_train: "np.ndarray",   # 0/1/2 result labels (0=H, 1=D, 2=A)
    X_val:   "pd.DataFrame",
    y_val:   "np.ndarray",
    draw_weight: float = 1.0,
    random_state: int = 7,
) -> "tuple[XGBClassifier, Any]":
    """
    Train a binary draw classifier then fit an isotonic calibrator on its output.

    draw_weight=1.0 (no scale_pos_weight inflation). Previously 3.0 caused
    draw probs to inflate to ~37% vs market-implied ~25%. Calibration now
    handles the class-imbalance correction instead.

    Returns (model, isotonic_calibrator).
    """
    import pandas as pd
    from sklearn.isotonic import IsotonicRegression

    draw_cols = [c for c in DRAW_FEATURE_COLS if c in X_train.columns]

    Xd_train = X_train[draw_cols]
    Xd_val   = X_val[draw_cols]
    yd_train = (y_train == 1).astype(int)
    yd_val   = (y_val   == 1).astype(int)

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
        scale_pos_weight=draw_weight,
        eval_metric="logloss",
        early_stopping_rounds=40,
        tree_method="hist",
        nthread=-1,
        random_state=random_state,
    )
    model.fit(
        Xd_train, yd_train,
        eval_set=[(Xd_val, yd_val)],
        verbose=False,
    )

    # Fit isotonic calibrator on validation output
    raw_probs  = model.predict_proba(Xd_val)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_probs, yd_val.astype(float))
    cal_probs  = calibrator.predict(raw_probs)

    draw_preds   = (cal_probs >= 0.5).astype(int)
    draw_acc     = (draw_preds == yd_val).mean()
    draw_recall  = yd_val[draw_preds == 1].mean() if draw_preds.sum() > 0 else 0.0
    actual_draws = yd_val.mean()
    print(f"  [draw_clf] val acc={draw_acc:.3f}  "
          f"draw_recall={draw_recall:.3f}  "
          f"actual_draw_rate={actual_draws:.3f}  "
          f"mean_p_draw(cal)={cal_probs.mean():.3f}")
    return model, calibrator


# ── Blending ─────────────────────────────────────────────────────────────────

def blend_draw_probability(
    p_home: float,
    p_draw: float,
    p_away: float,
    draw_clf_prob: float,
    alpha: float = 0.45,
) -> "tuple[float, float, float]":
    """
    Blend draw classifier output with result model draw probability.

    The specialist's draw probability replaces alpha of the result model's
    draw estimate. Home/away probabilities are scaled so the three sum to 1.

    alpha   : weight given to draw specialist (0 = ignore, 1 = use only specialist).
    Returns : (p_home, p_draw, p_away) renormalized to sum to 1.
    """
    blended_draw = alpha * draw_clf_prob + (1.0 - alpha) * p_draw

    # Scale home and away proportionally to fill the remaining mass
    ha_old = p_home + p_away
    ha_new = 1.0 - blended_draw
    if ha_old > 1e-9:
        scale = ha_new / ha_old
        new_home = p_home * scale
        new_away = p_away * scale
    else:
        new_home = new_away = ha_new / 2.0

    total = new_home + blended_draw + new_away
    if total > 1e-9:
        new_home     /= total
        blended_draw /= total
        new_away     /= total
    else:
        new_home = new_away = blended_draw = 1.0 / 3.0

    return new_home, blended_draw, new_away


# ── Persist / Load ────────────────────────────────────────────────────────────

def save_draw_classifier(model: XGBClassifier, models_dir: str = MODELS_DIR) -> None:
    os.makedirs(models_dir, exist_ok=True)
    path = os.path.join(models_dir, "model_draw_clf.pkl")
    with open(path, "wb") as f:
        pickle.dump(model, f)
    print(f"  Draw classifier saved → {path}")


def save_draw_calibrator(calibrator: IsotonicRegression, models_dir: str = MODELS_DIR) -> None:
    os.makedirs(models_dir, exist_ok=True)
    path = os.path.join(models_dir, "calibrator_draw_clf.pkl")
    with open(path, "wb") as f:
        pickle.dump(calibrator, f)
    print(f"  Draw calibrator saved  → {path}")


_draw_clf: Optional[XGBClassifier] = None
_draw_loaded: bool = False

_draw_cal: Optional[IsotonicRegression] = None
_draw_cal_loaded: bool = False


def load_draw_classifier(models_dir: str = MODELS_DIR) -> "Optional[XGBClassifier]":
    """Load draw classifier once per process; return None when file missing."""
    global _draw_clf, _draw_loaded
    if _draw_loaded:
        return _draw_clf

    path = os.path.join(models_dir, "model_draw_clf.pkl")
    try:
        with open(path, "rb") as f:
            _draw_clf = pickle.load(f)
        print("[draw_clf] Draw classifier loaded.")
        _draw_loaded = True   # only mark loaded after successful load
    except FileNotFoundError:
        print("[draw_clf] No draw classifier found — skipping draw blend. "
              "Run `python -m backend.app.ml.train` to generate it.")
    except Exception as e:
        print(f"[draw_clf] Error loading draw classifier: {e}")
    return _draw_clf


def load_draw_calibrator(models_dir: str = MODELS_DIR) -> "Optional[IsotonicRegression]":
    """Load draw specialist calibrator once per process; return None when file missing."""
    global _draw_cal, _draw_cal_loaded
    if _draw_cal_loaded:
        return _draw_cal

    path = os.path.join(models_dir, "calibrator_draw_clf.pkl")
    try:
        with open(path, "rb") as f:
            _draw_cal = pickle.load(f)
        print("[draw_clf] Draw calibrator loaded.")
        _draw_cal_loaded = True   # only mark loaded after successful load
    except FileNotFoundError:
        print("[draw_clf] No draw calibrator found — using raw draw specialist probs.")
    except Exception as e:
        print(f"[draw_clf] Error loading draw calibrator: {e}")
    return _draw_cal


def reload_draw_models() -> None:
    """Force-reload draw classifier and calibrator from disk (e.g. after retrain)."""
    global _draw_clf, _draw_loaded, _draw_cal, _draw_cal_loaded
    _draw_clf = None
    _draw_loaded = False
    _draw_cal = None
    _draw_cal_loaded = False
    print("[draw_clf] Cache cleared — will reload on next predict call.")


def apply_draw_calibration(
    calibrator: "Optional[IsotonicRegression]",
    raw_prob: float,
) -> float:
    """Apply isotonic calibration to a single draw specialist probability."""
    if calibrator is None:
        return raw_prob
    return float(calibrator.predict([raw_prob])[0])


def predict_draw_prob(
    draw_clf: "Optional[XGBClassifier]",
    feat: dict,
) -> "Optional[float]":
    """
    Run the draw classifier on a single feature dict.
    Returns P(draw) or None when the classifier is unavailable.
    """
    import pandas as pd  # local import
    if draw_clf is None:
        return None
    draw_cols = [c for c in DRAW_FEATURE_COLS if c in feat]
    row = pd.DataFrame([{c: feat.get(c, np.nan) for c in DRAW_FEATURE_COLS}])
    prob = float(draw_clf.predict_proba(row)[0, 1])
    return prob
