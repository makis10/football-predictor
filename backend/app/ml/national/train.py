"""
National team model training.

Three binary/multiclass models:
  result_model  — 3-class (0=Home win, 1=Draw, 2=Away win)
  goals_model   — binary (over 2.5 goals)
  btts_model    — binary (both teams score)

Ensemble: XGBoost + LightGBM (no MLP — dataset ~20k rows after min_year filter)
Windows roll with the data (national_windows): the last twelve months test,
the twelve before them calibrate (isotonic), the trees fit everything older.

Usage:
  python scripts/train_national.py
"""
from __future__ import annotations

import pickle
import sys
import warnings
from pathlib import Path

import json

import numpy as np
import pandas as pd
import lightgbm as lgb
from lightgbm import LGBMClassifier
from sklearn.isotonic import IsotonicRegression  # noqa: F401  (type hints / isinstance)
from backend.app.ml.prob_bounds import probability_isotonic
from backend.app.ml.refit import refit_on_everything
from sklearn.metrics import accuracy_score, brier_score_loss, classification_report, log_loss
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.ml.national.features import (
    load_results, build_features, build_snapshot,
    NATIONAL_FEATURE_COLS, NATIONAL_OPTIONAL_COLS, DRAW_FEATURE_COLS,
)

DATA_DIR   = ROOT / "backend" / "data" / "raw" / "international"
MODELS_DIR = ROOT / "backend" / "data" / "models" / "national"

# Training data: only use from MIN_YEAR onward
MIN_YEAR = 1990

# Rolling windows, anchored on the newest played match: the last twelve months
# are the test window, the twelve before them calibrate, and the trees fit
# everything older. These were literals — calibration 2023, test 2024-01 to
# 2026-06 — so a model retrained every morning never fit a match played after
# 2022, and its test window stopped admitting results in June 2026.
TEST_MONTHS = 12
CAL_MONTHS  = 12


def national_windows(data_max) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    """(cal_start, test_start, test_end) for data whose newest played match is
    `data_max`. test_end is the first of the following month, so the newest
    match always sits inside the test window."""
    test_end = (pd.Timestamp(data_max) + pd.offsets.MonthBegin(1)).normalize()
    test_start = test_end - pd.DateOffset(months=TEST_MONTHS)
    cal_start = test_start - pd.DateOffset(months=CAL_MONTHS)
    return cal_start, test_start, test_end

# XGBoost / LightGBM shared hyperparameters
_XGB_PARAMS = dict(
    max_depth=4, learning_rate=0.05,
    subsample=0.75, colsample_bytree=0.7, min_child_weight=5,
    gamma=0.1, reg_alpha=0.1, reg_lambda=1.5,
    early_stopping_rounds=30,
    tree_method="hist", nthread=-1, random_state=42,
)
_LGB_PARAMS = dict(
    max_depth=4, learning_rate=0.05,
    subsample=0.75, colsample_bytree=0.7, min_child_samples=20,
    reg_alpha=0.1, reg_lambda=1.5,
    n_estimators=500, random_state=42, verbosity=-1,
)


def _time_decay_weights(dates: pd.Series, half_life_days: float = 365 * 3) -> np.ndarray:
    """Exponential time decay. Matches from 3 years ago get ~0.5 weight."""
    latest = dates.max()
    days_ago = (latest - dates).dt.days.clip(lower=0).to_numpy()
    return np.exp(-np.log(2) * days_ago / half_life_days)


class SoftVoteEnsemble:
    def __init__(self, models: list, weights: list[float] | None = None):
        self.models = models
        self.weights = weights or [1.0] * len(models)

    def predict_proba(self, X):
        total = sum(
            w * m.predict_proba(X)
            for m, w in zip(self.models, self.weights)
        )
        return total / sum(self.weights)

    def predict(self, X):
        return self.predict_proba(X).argmax(axis=1)


def prepare_data(data_dir: str | Path) -> pd.DataFrame:
    """Load, build features, return training DataFrame."""
    data_dir = Path(data_dir)
    print("Loading results …")
    historical, upcoming = load_results(data_dir)
    print(f"  {len(historical):,} played matches, {len(upcoming):,} upcoming")

    print(f"Engineering features (from {MIN_YEAR}) …")
    df = build_features(historical, min_year=MIN_YEAR)
    print(f"  {len(df):,} rows with features")

    # Drop rows with invalid targets
    df = df.dropna(subset=["target_result", "target_goals", "target_btts"])
    print(f"  {len(df):,} rows after dropping NaN targets")

    return df


def _feats(df: pd.DataFrame) -> pd.DataFrame:
    """Subset to available NATIONAL_FEATURE_COLS."""
    return df[[c for c in NATIONAL_FEATURE_COLS if c in df.columns]]


def _draw_feats(df: pd.DataFrame) -> pd.DataFrame:
    """Subset to DRAW_FEATURE_COLS available in df."""
    return df[[c for c in DRAW_FEATURE_COLS if c in df.columns]]


def blend_draw_probability(
    p_home: float, p_draw: float, p_away: float,
    draw_clf_prob: float,
    alpha: float = 0.35,
) -> tuple[float, float, float]:
    """
    Blend main result model draw probability with draw specialist.
    alpha: weight of draw_clf relative to result model (0 = no blend, 1 = only clf).

    Returns renormalized (p_home, p_draw, p_away).
    """
    blended_draw = alpha * draw_clf_prob + (1 - alpha) * p_draw
    # Scale home/away proportionally to absorb the draw change
    remaining = 1.0 - blended_draw
    ha_sum = p_home + p_away
    if ha_sum > 1e-9:
        scale = remaining / ha_sum
        p_home_new = p_home * scale
        p_away_new = p_away * scale
    else:
        p_home_new = remaining / 2
        p_away_new = remaining / 2
    return p_home_new, blended_draw, p_away_new


def _split(df: pd.DataFrame, cal_start, test_start, test_end):
    """Return (train, cal, test) DataFrames by date."""
    train = df[df["date"] < cal_start]
    cal   = df[(df["date"] >= cal_start) & (df["date"] < test_start)]
    test  = df[(df["date"] >= test_start) & (df["date"] < test_end)]
    return train, cal, test


def _train_xgb(
    X_tr, y_tr, sw_tr,
    X_val, y_val,
    n_classes: int,
    n_estimators: int = 500,
) -> XGBClassifier:
    metric = "mlogloss" if n_classes > 2 else "logloss"
    m = XGBClassifier(n_estimators=n_estimators, eval_metric=metric, **_XGB_PARAMS)
    m.fit(X_tr, y_tr, sample_weight=sw_tr,
          eval_set=[(X_val, y_val)], verbose=False)
    return m


def _train_lgb(
    X_tr, y_tr, sw_tr,
    X_val, y_val,
    n_classes: int,
) -> LGBMClassifier:
    obj = "multiclass" if n_classes > 2 else "binary"
    m = LGBMClassifier(objective=obj, **_LGB_PARAMS)
    # The fold used to be handed over with no early-stopping callback, so every
    # member trained its full n_estimators and the fold decided nothing.
    m.fit(X_tr, y_tr, sample_weight=sw_tr,
          eval_set=[(X_val, y_val)],
          callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(period=-1)])
    return m


def _calibrate(
    ensemble, X_cal, y_cal, n_classes: int
) -> list[IsotonicRegression] | IsotonicRegression:
    """Fit per-class isotonic calibrators."""
    if n_classes > 2:
        cals = []
        probs = ensemble.predict_proba(X_cal)
        for c in range(n_classes):
            iso = probability_isotonic()
            iso.fit(probs[:, c], (y_cal == c).astype(int))
            cals.append(iso)
        return cals
    else:
        iso = probability_isotonic()
        probs = ensemble.predict_proba(X_cal)[:, 1]
        iso.fit(probs, y_cal)
        return iso


def _eval_calibrated(
    ensemble, calibrators,
    X_test, y_test, n_classes: int,
    label: str,
) -> dict:
    raw_proba = ensemble.predict_proba(X_test)
    if n_classes > 2:
        cal_proba = np.zeros_like(raw_proba)
        for c, iso in enumerate(calibrators):
            cal_proba[:, c] = iso.predict(raw_proba[:, c])
        row_sum = cal_proba.sum(axis=1, keepdims=True)
        cal_proba /= np.maximum(row_sum, 1e-9)
        y_raw = raw_proba.argmax(axis=1)
        y_cal = cal_proba.argmax(axis=1)
    else:
        cal_proba = calibrators.predict(raw_proba[:, 1])
        y_raw = (raw_proba[:, 1] >= 0.5).astype(int)
        y_cal = (cal_proba >= 0.5).astype(int)
        cal_proba_2d = np.column_stack([1 - cal_proba, cal_proba])
        raw_proba = raw_proba
        cal_proba = cal_proba_2d

    raw_acc = accuracy_score(y_test, y_raw)
    cal_acc = accuracy_score(y_test, y_cal)
    ll = log_loss(y_test, cal_proba)

    print(f"  [{label}] raw acc: {raw_acc:.4f}  calibrated acc: {cal_acc:.4f}  log-loss: {ll:.4f}")
    if n_classes > 2:
        print(classification_report(y_test, y_cal,
              target_names=["HomeWin", "Draw", "AwayWin"], zero_division=0))

    return {"raw_acc": raw_acc, "cal_acc": cal_acc, "log_loss": ll,
            "cal_proba": cal_proba}


def train(data_dir: str | Path = DATA_DIR, models_dir: str | Path = MODELS_DIR,
          *, asof: "pd.Timestamp | None" = None) -> None:
    """Fit, calibrate, evaluate and save. `asof` first drops every match from
    that date on — a reproducible past run, to be scored on what followed."""
    data_dir   = Path(data_dir)
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)

    df = prepare_data(data_dir)
    if asof is not None:
        df = df[df["date"] < pd.Timestamp(asof)]

    cal_start, test_start, test_end = national_windows(df["date"].max())
    train_df, cal_df, test_df = _split(df, cal_start, test_start, test_end)
    print(f"\nSplitting:")
    print(f"  Train : {len(train_df):,}  ({train_df['date'].min().date()} – {train_df['date'].max().date()})")
    print(f"  Cal   : {len(cal_df):,}  ({cal_df['date'].min().date()} – {cal_df['date'].max().date()})")
    print(f"  Test  : {len(test_df):,}  ({test_df['date'].min().date()} – {test_df['date'].max().date()})")

    # Val split for early stopping: last 15% of train. It finds a tree count and
    # nothing else — every booster is then refit on the whole of train_df. They
    # used to ship fitted on `inner` alone, so the trees ended in mid-2018.
    n_val = max(100, int(len(train_df) * 0.15))
    inner = train_df.iloc[:-n_val]
    val   = train_df.iloc[-n_val:]
    print(f"  Val (early-stop): {len(inner):,} train / {len(val):,} val")

    # Sample weights: class balance × match_type × time decay
    def _sw(subset):
        """Compute sample weights for a training split."""
        d = _time_decay_weights(subset["date"])
        mw = subset["match_weight"].fillna(1.0).to_numpy()
        # class balance
        cw = compute_sample_weight("balanced", subset["target_result"])
        sw = cw * mw * d
        return sw / sw.mean()

    sw_inner = _sw(inner)
    sw_full  = _sw(train_df)

    # ── Result model ───────────────────────────────────────────────────────────
    print("\n--- Result model (Home Win / Draw / Away Win) ---")
    Xr_i = _feats(inner); Xr_v = _feats(val)
    Xr_c = _feats(cal_df); Xr_t = _feats(test_df)

    xgb_r = _train_xgb(Xr_i, inner["target_result"], sw_inner,
                        Xr_v, val["target_result"], n_classes=3)
    print(f"  [XGBoost] val acc={accuracy_score(val['target_result'], xgb_r.predict(Xr_v)):.4f}")
    xgb_r = refit_on_everything(xgb_r, _feats(train_df), train_df["target_result"], sw_full, "XGBoost")

    lgb_r = _train_lgb(Xr_i, inner["target_result"], sw_inner,
                       Xr_v, val["target_result"], n_classes=3)
    print(f"  [LightGBM] val acc={accuracy_score(val['target_result'], lgb_r.predict(Xr_v)):.4f}")
    lgb_r = refit_on_everything(lgb_r, _feats(train_df), train_df["target_result"], sw_full, "LightGBM")

    ens_r = SoftVoteEnsemble([xgb_r, lgb_r], [1, 1])
    cal_r = _calibrate(ens_r, Xr_c, cal_df["target_result"], n_classes=3)
    metrics_r = _eval_calibrated(ens_r, cal_r, Xr_t, test_df["target_result"], 3, "Result")

    # ── Goals model ────────────────────────────────────────────────────────────
    print("\n--- Goals model (Over / Under 2.5) ---")
    Xg_i = _feats(inner); Xg_v = _feats(val)
    Xg_c = _feats(cal_df); Xg_t = _feats(test_df)

    sw_g = _time_decay_weights(inner["date"]) * inner["match_weight"].fillna(1.0).to_numpy()
    sw_g = sw_g / sw_g.mean()
    sw_g_full = (_time_decay_weights(train_df["date"])
                 * train_df["match_weight"].fillna(1.0).to_numpy())
    sw_g_full = sw_g_full / sw_g_full.mean()

    xgb_g = _train_xgb(Xg_i, inner["target_goals"], sw_g,
                        Xg_v, val["target_goals"], n_classes=2)
    print(f"  [XGBoost] val acc={accuracy_score(val['target_goals'], xgb_g.predict(Xg_v)):.4f}")
    xgb_g = refit_on_everything(xgb_g, _feats(train_df), train_df["target_goals"], sw_g_full, "XGBoost")

    lgb_g = _train_lgb(Xg_i, inner["target_goals"], sw_g,
                       Xg_v, val["target_goals"], n_classes=2)
    print(f"  [LightGBM] val acc={accuracy_score(val['target_goals'], lgb_g.predict(Xg_v)):.4f}")
    lgb_g = refit_on_everything(lgb_g, _feats(train_df), train_df["target_goals"], sw_g_full, "LightGBM")

    ens_g = SoftVoteEnsemble([xgb_g, lgb_g], [1, 1])
    cal_g = _calibrate(ens_g, Xg_c, cal_df["target_goals"], n_classes=2)
    metrics_g = _eval_calibrated(ens_g, cal_g, Xg_t, test_df["target_goals"], 2, "Goals")

    # ── BTTS model ─────────────────────────────────────────────────────────────
    print("\n--- BTTS model (Both Teams Score) ---")
    xgb_b = _train_xgb(Xg_i, inner["target_btts"], sw_g,
                        Xg_v, val["target_btts"], n_classes=2)
    print(f"  [XGBoost] val acc={accuracy_score(val['target_btts'], xgb_b.predict(Xg_v)):.4f}")
    xgb_b = refit_on_everything(xgb_b, _feats(train_df), train_df["target_btts"], sw_g_full, "XGBoost")

    lgb_b = _train_lgb(Xg_i, inner["target_btts"], sw_g,
                       Xg_v, val["target_btts"], n_classes=2)
    print(f"  [LightGBM] val acc={accuracy_score(val['target_btts'], lgb_b.predict(Xg_v)):.4f}")
    lgb_b = refit_on_everything(lgb_b, _feats(train_df), train_df["target_btts"], sw_g_full, "LightGBM")

    ens_b = SoftVoteEnsemble([xgb_b, lgb_b], [1, 1])
    cal_b = _calibrate(ens_b, Xg_c, cal_df["target_btts"], n_classes=2)
    metrics_b = _eval_calibrated(ens_b, cal_b, Xg_t, test_df["target_btts"], 2, "BTTS")

    # ── Draw specialist classifier ─────────────────────────────────────────────
    print("\n--- Draw classifier (binary: is this a draw?) ---")
    target_draw = (inner["target_result"] == 1).astype(int)
    val_draw    = (val["target_result"]   == 1).astype(int)
    cal_draw    = (cal_df["target_result"]== 1).astype(int)
    test_draw   = (test_df["target_result"]== 1).astype(int)

    Xd_i = _draw_feats(inner); Xd_v = _draw_feats(val)
    Xd_c = _draw_feats(cal_df); Xd_t = _draw_feats(test_df)

    sw_d = _time_decay_weights(inner["date"]) * inner["match_weight"].fillna(1.0).to_numpy()
    sw_d_bal = sw_d * compute_sample_weight("balanced", target_draw)
    sw_d_bal = sw_d_bal / sw_d_bal.mean()

    xgb_d = _train_xgb(Xd_i, target_draw, sw_d_bal, Xd_v, val_draw, n_classes=2, n_estimators=300)
    lgb_d = _train_lgb(Xd_i, target_draw, sw_d_bal, Xd_v, val_draw, n_classes=2)
    val_pred_d = SoftVoteEnsemble([xgb_d, lgb_d], [1, 1]).predict(Xd_v)   # before the refit sees val
    full_draw = (train_df["target_result"] == 1).astype(int)
    sw_d_full = (_time_decay_weights(train_df["date"])
                 * train_df["match_weight"].fillna(1.0).to_numpy()
                 * compute_sample_weight("balanced", full_draw))
    sw_d_full = sw_d_full / sw_d_full.mean()
    xgb_d = refit_on_everything(xgb_d, _draw_feats(train_df), full_draw, sw_d_full, "XGBoost draw")
    lgb_d = refit_on_everything(lgb_d, _draw_feats(train_df), full_draw, sw_d_full, "LightGBM draw")
    ens_d = SoftVoteEnsemble([xgb_d, lgb_d], [1, 1])

    draw_raw_cal  = ens_d.predict_proba(Xd_c)[:, 1]
    actual_draw_rate = float(cal_draw.mean())
    print(f"  [draw_clf] val acc={accuracy_score(val_draw, val_pred_d):.4f}"
          f"  draw_recall={accuracy_score(val_draw[val_draw==1], val_pred_d[val_draw==1]):.3f}"
          f"  actual_draw_rate={actual_draw_rate:.3f}")

    # Calibrate draw classifier on cal set
    cal_d_iso = probability_isotonic()
    cal_d_iso.fit(draw_raw_cal, cal_draw)
    draw_cal_cal = cal_d_iso.predict(draw_raw_cal)
    print(f"  mean raw={draw_raw_cal.mean():.3f}  mean calibrated={draw_cal_cal.mean():.3f}"
          f"  actual={actual_draw_rate:.3f}")

    # ── Tune draw blend alpha on calibration set ───────────────────────────────
    print("\n--- Tuning draw blend alpha on calibration set ---")
    # Get result model calibrated probs on cal set
    raw_r_cal = ens_r.predict_proba(Xr_c)
    cal_r_cal = np.zeros_like(raw_r_cal)
    for c, iso in enumerate(cal_r):
        cal_r_cal[:, c] = iso.predict(raw_r_cal[:, c])
    row_sum = cal_r_cal.sum(axis=1, keepdims=True)
    cal_r_cal /= np.maximum(row_sum, 1e-9)

    draw_clf_cal_probs = cal_d_iso.predict(ens_d.predict_proba(Xd_c)[:, 1])

    best_alpha = 0.35
    best_brier = float("inf")
    for alpha_candidate in np.arange(0.05, 0.70, 0.05):
        blended = []
        for i in range(len(cal_df)):
            _, bd, _ = blend_draw_probability(
                float(cal_r_cal[i, 0]), float(cal_r_cal[i, 1]), float(cal_r_cal[i, 2]),
                float(draw_clf_cal_probs[i]), alpha=float(alpha_candidate),
            )
            blended.append(bd)
        bs = brier_score_loss(cal_draw, blended)
        print(f"  alpha={alpha_candidate:.2f}  brier={bs:.5f}")
        if bs < best_brier:
            best_brier = bs; best_alpha = float(alpha_candidate)

    print(f"  → Optimal alpha: {best_alpha:.2f}  (Brier={best_brier:.5f})")

    # Evaluate blended result on test set
    draw_clf_test_probs = cal_d_iso.predict(ens_d.predict_proba(Xd_t)[:, 1])
    raw_r_test = ens_r.predict_proba(Xr_t)
    cal_r_test = np.zeros_like(raw_r_test)
    for c, iso in enumerate(cal_r):
        cal_r_test[:, c] = iso.predict(raw_r_test[:, c])
    row_sum = cal_r_test.sum(axis=1, keepdims=True)
    cal_r_test /= np.maximum(row_sum, 1e-9)

    blended_preds = []
    for i in range(len(test_df)):
        ph, pd_, pa = blend_draw_probability(
            float(cal_r_test[i, 0]), float(cal_r_test[i, 1]), float(cal_r_test[i, 2]),
            float(draw_clf_test_probs[i]), alpha=best_alpha,
        )
        blended_preds.append(np.argmax([ph, pd_, pa]))
    blended_acc = accuracy_score(test_df["target_result"], blended_preds)
    draw_recall = accuracy_score(
        test_df["target_result"][test_df["target_result"] == 1],
        np.array(blended_preds)[test_df["target_result"].values == 1]
    ) if (test_df["target_result"] == 1).any() else 0.0
    print(f"  Blended result acc: {blended_acc:.4f}  draw_recall: {draw_recall:.4f}")

    # ── Build full snapshot for inference ──────────────────────────────────────
    print("\nBuilding team snapshot (for prediction) …")
    historical, _ = load_results(data_dir)
    snapshot = build_snapshot(historical)

    # ── Save everything ────────────────────────────────────────────────────────
    print("\nSaving models …")
    objects = {
        "model_result.pkl":         ens_r,
        "model_goals.pkl":          ens_g,
        "model_btts.pkl":           ens_b,
        "model_draw_clf.pkl":       ens_d,
        "calibrator_result.pkl":    cal_r,
        "calibrator_goals.pkl":     cal_g,
        "calibrator_btts.pkl":      cal_b,
        "calibrator_draw_clf.pkl":  cal_d_iso,
        "snapshot.pkl":             snapshot,
    }
    for fname, obj in objects.items():
        path = models_dir / fname
        with open(path, "wb") as f:
            pickle.dump(obj, f)
        print(f"  Saved → {path}")

    alpha_path = models_dir / "draw_alpha.json"
    with open(alpha_path, "w") as f:
        json.dump({"draw_blend_alpha": best_alpha}, f)
    print(f"  Saved → {alpha_path}")

    # ── Save training metrics ──────────────────────────────────────────────────
    from datetime import datetime, timezone

    # Extract per-class metrics from classification_report for result model
    _result_report = classification_report(
        test_df["target_result"], blended_preds,
        target_names=["H", "D", "A"], output_dict=True, zero_division=0,
    )

    # For goals model: rebuild predictions from calibrated proba
    _goals_preds = (metrics_g["cal_proba"].argmax(axis=1)
                    if metrics_g["cal_proba"].ndim == 2
                    else (metrics_g["cal_proba"] >= 0.5).astype(int))
    _goals_report = classification_report(
        test_df["target_goals"], _goals_preds,
        target_names=["UNDER", "OVER"], output_dict=True, zero_division=0,
    )

    # For btts model
    _btts_preds = (metrics_b["cal_proba"].argmax(axis=1)
                   if metrics_b["cal_proba"].ndim == 2
                   else (metrics_b["cal_proba"] >= 0.5).astype(int))
    _btts_report = classification_report(
        test_df["target_btts"], _btts_preds,
        target_names=["NG", "GG"], output_dict=True, zero_division=0,
    )

    draw_raw_test_mean = float(ens_d.predict_proba(Xd_t)[:, 1].mean())
    draw_cal_test_mean = float(cal_d_iso.predict(ens_d.predict_proba(Xd_t)[:, 1]).mean())
    draw_actual_rate   = float((test_df["target_result"] == 1).mean())

    training_metrics = {
        "trained_at":            datetime.now(timezone.utc).isoformat(),
        "n_train":               int(len(train_df)),
        "n_cal":                 int(len(cal_df)),
        "n_test":                int(len(test_df)),
        "cal_start":             str(cal_start.date()),
        "test_start":            str(test_start.date()),
        "test_end":              str(test_end.date()),
        "trees_fitted_through":  str(train_df["date"].max().date()),
        # Result model (blended)
        "result_accuracy":       float(blended_acc),
        "result_home_recall":    float(_result_report["H"]["recall"]),
        "result_draw_recall":    float(_result_report["D"]["recall"]),
        "result_away_recall":    float(_result_report["A"]["recall"]),
        "result_home_precision": float(_result_report["H"]["precision"]),
        "result_draw_precision": float(_result_report["D"]["precision"]),
        "result_away_precision": float(_result_report["A"]["precision"]),
        # Goals model
        "goals_accuracy":        float(metrics_g["cal_acc"]),
        "goals_over_recall":     float(_goals_report["OVER"]["recall"]),
        "goals_under_recall":    float(_goals_report["UNDER"]["recall"]),
        # BTTS model
        "btts_accuracy":         float(metrics_b["cal_acc"]),
        "btts_gg_recall":        float(_btts_report["GG"]["recall"]),
        "btts_ng_recall":        float(_btts_report["NG"]["recall"]),
        # Draw calibration
        "draw_raw_mean":         draw_raw_test_mean,
        "draw_cal_mean":         draw_cal_test_mean,
        "draw_actual_rate":      draw_actual_rate,
        "draw_blend_alpha":      float(best_alpha),
    }

    metrics_path = models_dir / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(training_metrics, f, indent=2)
    print(f"  Saved → {metrics_path}")

    print("\nTraining complete.")
    print(f"  Result  calibrated acc : {metrics_r['cal_acc']:.4f}")
    print(f"  Result  blended acc    : {blended_acc:.4f}  draw_recall={draw_recall:.4f}")
    print(f"  Goals   calibrated acc : {metrics_g['cal_acc']:.4f}")
    print(f"  BTTS    calibrated acc : {metrics_b['cal_acc']:.4f}")


if __name__ == "__main__":
    train()
