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

    # ── Goals model — per-league calibrators ──────────────────────────────────
    league_goals_cals: dict[str, IsotonicRegression] = {}
    if cal_df is not None and "League" in cal_df.columns:
        leagues = cal_df["League"].values
        for league in np.unique(leagues):
            mask = leagues == league
            if mask.sum() < min_league_samples:
                continue
            iso_l = IsotonicRegression(out_of_bounds="clip")
            iso_l.fit(raw_over[mask], y_cal_goals[mask].astype(float))
            league_goals_cals[league] = iso_l
            # Log per-league improvement
            raw_l_acc = (raw_over_pred[mask] == y_cal_goals[mask]).mean()
            cal_l_acc = ((iso_l.predict(raw_over[mask]) >= 0.5).astype(int) == y_cal_goals[mask]).mean()
            print(f"  [calibration] {league:<12} — "
                  f"n={mask.sum():4d}  raw={raw_l_acc:.3f}  cal={cal_l_acc:.3f}")
        if league_goals_cals:
            print(f"  [calibration] {len(league_goals_cals)} per-league goals calibrators fitted.")

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
    global _result_cals, _goals_cal, _league_goals_cals, _loaded, _recent_cals, _recent_loaded
    _result_cals = None
    _goals_cal = None
    _league_goals_cals = None
    _loaded = False
    _recent_cals = None
    _recent_loaded = False
    print("[calibration] Cache cleared — will reload on next predict call.")


# ── Second-stage rolling recalibration ────────────────────────────────────────
# The base calibrators are fitted once per training run on a fixed historical
# season; the live distribution drifts. scripts/recalibrate.py refits a small
# second-stage isotonic monthly from the STORED final probabilities vs actual
# outcomes of the last 365 days (genuinely out-of-sample — every stored
# prediction was made before its match). Applied AFTER the draw blend, i.e. on
# the same quantity that gets stored/served.

RECENT_CAL_PATH = os.path.join(MODELS_DIR, "calibrator_recent.pkl")

_recent_cals: Optional[dict] = None
_recent_loaded: bool = False


def load_recent_calibrators(models_dir: str = MODELS_DIR) -> Optional[dict]:
    """Load the second-stage calibrator dict, or None when not fitted yet."""
    global _recent_cals, _recent_loaded
    if _recent_loaded:
        return _recent_cals
    path = os.path.join(models_dir, "calibrator_recent.pkl")
    try:
        with open(path, "rb") as f:
            _recent_cals = pickle.load(f)
        print(f"[calibration] Second-stage (rolling) calibrators loaded "
              f"(fitted {_recent_cals.get('fitted_at', '?')}, n={_recent_cals.get('n', '?')}).")
    except FileNotFoundError:
        _recent_cals = None
    except Exception as e:
        print(f"[calibration] Error loading recent calibrators: {e}")
        _recent_cals = None
    _recent_loaded = True
    return _recent_cals


def apply_recent_calibration(
    home_win: float, draw: float, away_win: float, over: float,
) -> "tuple[float, float, float, float]":
    """
    Apply the second-stage rolling calibrators (no-op when not fitted).
    1×2 values are recalibrated per class and renormalized; over is independent.
    """
    rc = load_recent_calibrators()
    if not rc:
        return home_win, draw, away_win, over

    hw = float(rc["home"].predict([home_win])[0]) if rc.get("home") else home_win
    d  = float(rc["draw"].predict([draw])[0])     if rc.get("draw") else draw
    aw = float(rc["away"].predict([away_win])[0]) if rc.get("away") else away_win
    total = hw + d + aw
    if total > 0:
        hw, d, aw = hw / total, d / total, aw / total
    ov = float(rc["over"].predict([over])[0]) if rc.get("over") else over
    return hw, d, aw, ov
