"""
Isotonic calibration for XGBoost probability outputs.

After XGBoost training, a dedicated calibration set (the 2023/24 season) is
used to fit isotonic regressors on each model's raw outputs. This corrects
systematic over/underconfidence without changing the model's ranking power.

For the result model (3-class) we use one-vs-rest: three separate isotonic
regressors, one per outcome (Home Win, Draw, Away Win). After calibration the
three values are renormalized to sum to 1.

For the goals model (binary) we fit:
  - One GLOBAL isotonic regressor on P(Over 2.5).
  - Per-LEAGUE isotonic regressors on P(Over 2.5) — fitted only when the
    league has >= min_league_samples calibration rows.  At inference time the
    per-league calibrator is preferred; the global one is the fallback.

Reference:
  Zadrozny & Elkan (2002) "Transforming classifier scores into accurate
  multiclass probability estimates."

Usage:
  # During training (train.py):
  from backend.app.ml.calibration import fit_calibrators, save_calibrators
  result_cals, goals_cal, league_goals_cals = fit_calibrators(
      result_model, goals_model, X_cal, y_cal_result, y_cal_goals,
      cal_df=cal_df,          # full calibration DataFrame (needs 'League' col)
  )
  save_calibrators(result_cals, goals_cal, league_goals_cals)

  # During inference (predict.py / compute_predictions.py):
  from backend.app.ml.calibration import load_calibrators, apply_calibration
  result_cals, goals_cal, league_goals_cals = load_calibrators()
  hw, d, aw, ov = apply_calibration(
      raw_result_probs, raw_over,
      result_cals, goals_cal,
      league=league,
      league_goals_cals=league_goals_cals,
  )
"""

from __future__ import annotations

import os
import pickle
from typing import Optional

import numpy as np
from sklearn.isotonic import IsotonicRegression

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models")


# ── Fitting ───────────────────────────────────────────────────────────────────

def fit_calibrators(
    result_model,
    goals_model,
    X_cal: "pd.DataFrame",
    y_cal_result: "np.ndarray",
    y_cal_goals: "np.ndarray",
    cal_df: "pd.DataFrame | None" = None,
    min_league_samples: int = 80,
    X_cal_goals: "pd.DataFrame | None" = None,
) -> "tuple[list[IsotonicRegression], IsotonicRegression, dict[str, IsotonicRegression]]":
    """
    Fit isotonic calibrators on a held-out calibration set.

    result_model      : fitted XGBClassifier for 1×2 (0=H, 1=D, 2=A)
    goals_model       : fitted SoftVoteEnsemble for O/U 2.5
    X_cal             : feature DataFrame for result model calibration
    y_cal_result      : true labels (0/1/2) for calibration matches
    y_cal_goals       : true labels (0=Under, 1=Over) for calibration matches
    cal_df            : full calibration DataFrame — must have a 'League' column.
                        When provided, per-league goals calibrators are fitted for
                        any league with >= min_league_samples rows.
    min_league_samples: minimum rows per league to fit a per-league calibrator.
    X_cal_goals       : optional separate feature DataFrame for goals model.
                        When None, falls back to X_cal.

    Returns (result_calibrators, goals_calibrator, league_goals_calibrators).
    league_goals_calibrators is {} when cal_df is None.
    """
    _X_goals = X_cal_goals if X_cal_goals is not None else X_cal

    # ── Result model (3-class OVR) ────────────────────────────────────────────
    raw_result = result_model.predict_proba(X_cal)   # shape (n, 3)
    result_cals: list[IsotonicRegression] = []
    for i in range(3):
        y_binary = (y_cal_result == i).astype(float)
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(raw_result[:, i], y_binary)
        result_cals.append(iso)

    # Measure calibration improvement on this split
    raw_acc = (raw_result.argmax(axis=1) == y_cal_result).mean()

    cal_probs = _apply_result(raw_result[0] if raw_result.ndim == 1 else raw_result,
                              result_cals, batch=True)
    cal_acc = (cal_probs.argmax(axis=1) == y_cal_result).mean()
    print(f"  [calibration] Result  — raw acc: {raw_acc:.3f}  calibrated acc: {cal_acc:.3f}")

    # ── Goals model (binary) — global calibrator ──────────────────────────────
    raw_goals = goals_model.predict_proba(_X_goals)  # shape (n, 2)
    raw_over  = raw_goals[:, 1]
    goals_cal = IsotonicRegression(out_of_bounds="clip")
    goals_cal.fit(raw_over, y_cal_goals.astype(float))

    cal_over_pred = (goals_cal.predict(raw_over) >= 0.5).astype(int)
    raw_over_pred = (raw_over >= 0.5).astype(int)
    raw_g_acc = (raw_over_pred == y_cal_goals).mean()
    cal_g_acc = (cal_over_pred == y_cal_goals).mean()
    print(f"  [calibration] Goals   — raw acc: {raw_g_acc:.3f}  calibrated acc: {cal_g_acc:.3f}")

    # ── Goals model — per-league calibrators (DISABLED 2026-08-03) ────────────
    #
    # Measured on the held-out test split (7,194 matches the calibrators never
    # saw), Over-2.5 log-loss:
    #
    #     raw model            0.6832
    #     global isotonic      0.6844
    #     + per-league         0.7168      ← this layer, +0.0324
    #
    # 20 of 23 leagues got worse, 3 better. Romania went 0.6968 → 1.0592.
    # Switzerland +0.107, Norway +0.125.
    #
    # The cause is the sample size. `min_league_samples = 80` binary outcomes is
    # nowhere near enough for isotonic regression, which is non-parametric and
    # will happily interpolate the noise: the fitted curves were 10-15 step
    # functions whose plateaus reached exactly 0.000 and 1.000 — a calibrator
    # asserting a 0% chance of Over 2.5 — and 0.74% of test predictions landed
    # on one of those pins, which is where most of the log-loss went.
    #
    # It was not a self-contained loss. Romania's raw 0.476 was pushed to 0.392,
    # which contradicts a BTTS of 0.529 (few goals, yet both teams score); the
    # coherence projection in poisson.project_probs_coherent then resolved the
    # contradiction by moving the mass into the draw, and all 114 upcoming Liga I
    # fixtures came out at a 0.372 draw probability against a 0.278 base rate.
    # The draw looked like the bug for a while. It was the symptom.
    #
    # Reviving this needs a genuine held-out check per league — fit on part of
    # the calibration window, keep the calibrator only if it beats the global one
    # on the rest — plus clipping away from 0 and 1. With a one-season window no
    # league has the rows for that, which is the honest answer for now.
    league_goals_cals: dict[str, IsotonicRegression] = {}
    print("  [calibration] per-league goals calibrators disabled "
          "(measured +0.0324 log-loss on held-out test; see comment)")

    return result_cals, goals_cal, league_goals_cals


# ── Internal helpers ──────────────────────────────────────────────────────────

def _apply_result(
    raw_probs,
    calibrators: list[IsotonicRegression],
    batch: bool = False,
) -> np.ndarray:
    """
    Apply 3 OVR isotonic calibrators and renormalize to sum to 1.
    batch=True handles shape (n, 3); batch=False handles shape (3,).
    """
    raw = np.atleast_2d(raw_probs)          # always (n, 3)
    cal = np.column_stack([
        calibrators[i].predict(raw[:, i]) for i in range(3)
    ])                                       # shape (n, 3)
    totals = cal.sum(axis=1, keepdims=True)
    totals = np.where(totals > 0, totals, 1.0)
    cal = cal / totals
    return cal if batch else cal[0]


# ── Public apply API ──────────────────────────────────────────────────────────

def apply_calibration(
    raw_result_probs: "np.ndarray",          # shape (3,) — [HomeWin, Draw, AwayWin]
    raw_over: float,                          # P(Over 2.5) from XGBoost
    result_cals: "Optional[list]",
    goals_cal: "Optional[IsotonicRegression]",
    league: "Optional[str]" = None,
    league_goals_cals: "Optional[dict]" = None,
) -> "tuple[float, float, float, float]":
    """
    Apply both calibrators and return (home_win, draw, away_win, over_2_5).
    Falls back to raw values gracefully when calibrators are None.

    league            : current league name — selects per-league goals calibrator
                        when available, falling back to global.
    league_goals_cals : dict {league_name: IsotonicRegression}
    """
    # Result calibration
    if result_cals is not None:
        cal_result = _apply_result(raw_result_probs, result_cals)
        hw, d, aw = float(cal_result[0]), float(cal_result[1]), float(cal_result[2])
    else:
        hw, d, aw = (float(raw_result_probs[0]),
                     float(raw_result_probs[1]),
                     float(raw_result_probs[2]))

    # Goals calibration — prefer per-league calibrator when available
    chosen_cal = None
    if league and league_goals_cals:
        chosen_cal = league_goals_cals.get(league)
    if chosen_cal is None:
        chosen_cal = goals_cal

    if chosen_cal is not None:
        ov = float(chosen_cal.predict([raw_over])[0])
    else:
        ov = float(raw_over)

    return hw, d, aw, ov


# ── Persist ───────────────────────────────────────────────────────────────────

def save_calibrators(
    result_calibrators: "list[IsotonicRegression]",
    goals_calibrator: "IsotonicRegression",
    league_goals_calibrators: "dict[str, IsotonicRegression] | None" = None,
    models_dir: str = MODELS_DIR,
) -> None:
    os.makedirs(models_dir, exist_ok=True)
    path_r = os.path.join(models_dir, "calibrator_result.pkl")
    path_g = os.path.join(models_dir, "calibrator_goals.pkl")
    path_l = os.path.join(models_dir, "calibrator_goals_leagues.pkl")
    with open(path_r, "wb") as f:
        pickle.dump(result_calibrators, f)
    with open(path_g, "wb") as f:
        pickle.dump(goals_calibrator, f)
    with open(path_l, "wb") as f:
        pickle.dump(league_goals_calibrators or {}, f)
    print(f"  Calibrators saved → {path_r}")
    print(f"                    → {path_g}")
    print(f"                    → {path_l}  "
          f"({len(league_goals_calibrators or {})} leagues)")


# ── Load (module-level singletons) ────────────────────────────────────────────

_result_cals: Optional[list] = None
_goals_cal: Optional[IsotonicRegression] = None
_league_goals_cals: Optional[dict] = None
_loaded: bool = False


def load_calibrators(
    models_dir: str = MODELS_DIR,
) -> "tuple[Optional[list], Optional[IsotonicRegression], dict]":
    """
    Load calibrators once per process.  Returns (None, None, {}) gracefully when
    the files don't exist — callers use raw XGBoost probabilities as fallback.
    Run `python -m backend.app.ml.train` to generate calibrator files.
    """
    global _result_cals, _goals_cal, _league_goals_cals, _loaded
    if _loaded:
        return _result_cals, _goals_cal, _league_goals_cals or {}

    path_r = os.path.join(models_dir, "calibrator_result.pkl")
    path_g = os.path.join(models_dir, "calibrator_goals.pkl")
    path_l = os.path.join(models_dir, "calibrator_goals_leagues.pkl")

    try:
        with open(path_r, "rb") as f:
            _result_cals = pickle.load(f)
        with open(path_g, "rb") as f:
            _goals_cal = pickle.load(f)
        print("[calibration] Calibrators loaded.")
        _loaded = True   # only mark loaded after successful load
    except FileNotFoundError:
        print("[calibration] No calibrators found — using raw XGBoost probabilities. "
              "Run `python -m backend.app.ml.train` to generate them.")
        # _loaded stays False so the next call retries (e.g. after training)
    except Exception as e:
        print(f"[calibration] Error loading calibrators: {e}")

    try:
        with open(path_l, "rb") as f:
            _league_goals_cals = pickle.load(f)
        if _league_goals_cals:
            print(f"[calibration] Per-league goals calibrators loaded "
                  f"({len(_league_goals_cals)} leagues).")
    except FileNotFoundError:
        _league_goals_cals = {}

    return _result_cals, _goals_cal, _league_goals_cals or {}


def reload_calibrators(models_dir: str = MODELS_DIR) -> None:
    """
    Force-reload calibrators from disk (e.g. after a retrain).
    Resets the module-level singletons so the next load_calibrators() call
    reads fresh files from disk instead of returning stale in-memory objects.
    """
    global _result_cals, _goals_cal, _league_goals_cals, _loaded
    _result_cals = None
    _goals_cal = None
    _league_goals_cals = None
    _loaded = False
    print("[calibration] Cache cleared — will reload on next predict call.")


# ── Second-stage rolling recalibration — REMOVED 2026-09-03 ───────────────────
#
# There used to be a second isotonic stage here, refitted monthly by
# scripts/recalibrate.py from the last 365 days of stored predictions and applied
# right after the draw blend. It is gone, for two reasons, in this order:
#
# 1. It fitted one quantity and corrected a different one. recalibrate.py read
#    predictions.home_win_prob / draw_prob / away_win_prob — the SERVED columns —
#    and those have been market-anchored since 2026-09-01 (commit 496c842).
#    Inference applied the result BEFORE anchoring. So it learned "given an
#    anchored probability, what actually happens" and was then asked "given an
#    unanchored one, correct it". The two distributions are not the same: mean
#    p_draw 0.31 raw against 0.25 anchored. Nothing connected the two files
#    except the database, so changing what a column meant broke a consumer three
#    directories away, silently, with no test able to see it.
#
# 2. Measured on the 2025/26 test rows (2026-09-03), it was making things worse
#    even before that. Over/Under 2.5: log-loss 0.6853 with it against 0.6831
#    without, AUC 0.5688 against 0.5771, accuracy 55.47% against 55.90%. On the
#    1x2 through the full chain: 0.9890 with, 0.9883 without. Its fitted curves
#    had saturated plateaus (P(over) pinned to 0.000 for any input <= 0.2), the
#    same failure that retired the per-league goals calibrators above.
#
# Bringing it back needs the quantity it corrects to be STORED, not reconstructed:
# a column holding the post-blend, pre-anchor probability at the time each
# prediction was written. Without that column any second stage is fitted on the
# wrong distribution again. Do not re-add it by pointing recalibrate.py at
# raw_*_prob — those are the uncalibrated ensemble outputs, a third distribution.
