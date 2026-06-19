"""
Walk-forward validation for football prediction models.

Expanding-window time-series cross-validation:
  Fold k:  train  = Date < season_start[k]          (all seasons up to k-1)
           cal    = season_start[k]  ≤ Date < season_start[k+1]   (1 season)
           test   = season_start[k+1] ≤ Date < season_start[k+2]  (1 season)

Feature engineering runs ONCE on the full dataset (no data leakage — features
are computed chronologically by build_features()). Only the train/cal/test
slices differ per fold.

Usage:
  python scripts/walk_forward_eval.py
  python scripts/walk_forward_eval.py --min-train 5  # skip folds with <5 train seasons
  python scripts/walk_forward_eval.py --csv out.csv  # export fold metrics to CSV
  python scripts/walk_forward_eval.py --last-cal 2022
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import accuracy_score
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

warnings.filterwarnings("ignore", category=UserWarning)

# ── path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.ml.train import (
    prepare_data,
    _time_decay_weights,
    MARKET_COLS,
)
from backend.app.ml.features import (
    RESULT_FEATURE_COLS,
    GOALS_FEATURE_COLS,
    BTTS_FEATURE_COLS,
)

RAW_DIR = str(ROOT / "backend" / "data" / "raw")

# ── fold config ───────────────────────────────────────────────────────────────
DEFAULT_MIN_TRAIN_SEASONS = 3
DATA_START_YEAR           = 2010    # first season (2010/11)
LAST_CAL_YEAR             = 2023    # last full cal season (2023/24 → test 2024/25)

# XGBoost hyperparameters (same architecture as production, reduced n_estimators for speed)
# eval_metric is set per-call depending on n_classes (mlogloss=multiclass, logloss=binary)
_XGB_COMMON = dict(
    max_depth=4, learning_rate=0.05,
    subsample=0.75, colsample_bytree=0.7, min_child_weight=5,
    gamma=0.1, reg_alpha=0.1, reg_lambda=1.5,
    early_stopping_rounds=30,
    tree_method="hist", nthread=-1, random_state=42,
)
MARKET_DROPOUT = 0.35


def _season_boundary(year: int) -> pd.Timestamp:
    return pd.Timestamp(year, 7, 1)


def _train_xgb(
    X_inner:   pd.DataFrame,
    y_inner:   pd.Series,
    dates_inner: pd.Series,      # Date column for time-decay (NOT in X_inner)
    X_val:     pd.DataFrame,
    y_val:     pd.Series,
    n_classes: int = 3,          # 2=binary, 3=multiclass
    n_estimators: int = 500,
    dropout_market: bool = True,
    seed_offset: int = 0,
) -> XGBClassifier:
    rng = np.random.default_rng(42 + seed_offset)
    X_tr = X_inner.copy()

    if dropout_market:
        mask = rng.random(len(X_tr)) < MARKET_DROPOUT
        for col in MARKET_COLS:
            if col in X_tr.columns:
                X_tr.loc[X_tr.index[mask], col] = np.nan

    class_w = compute_sample_weight("balanced", y_inner)
    decay_w = _time_decay_weights(dates_inner)
    sw = class_w * decay_w
    sw = sw / sw.mean()

    # mlogloss for multiclass, logloss for binary — mixing them causes XGBoost error
    metric = "mlogloss" if n_classes > 2 else "logloss"
    model = XGBClassifier(n_estimators=n_estimators, eval_metric=metric, **_XGB_COMMON)
    model.fit(X_tr, y_inner, sample_weight=sw,
              eval_set=[(X_val, y_val)], verbose=False)
    return model


def _iso_calibrate(
    model,
    X_cal: pd.DataFrame, y_cal: pd.Series,
    X_test: pd.DataFrame, y_test: pd.Series,
    n_classes: int,
) -> tuple[float, float]:
    """Fit isotonic calibrator on cal set, evaluate on test set.
    Returns (raw_acc, cal_acc)."""
    if n_classes > 2:
        raw_p_cal  = model.predict_proba(X_cal)    # (n_cal, n_classes)
        raw_p_test = model.predict_proba(X_test)   # (n_test, n_classes)
        cal_p_test = np.zeros_like(raw_p_test)
        for c in range(n_classes):
            iso = IsotonicRegression(out_of_bounds="clip")
            iso.fit(raw_p_cal[:, c], (y_cal == c).astype(int))
            cal_p_test[:, c] = iso.predict(raw_p_test[:, c])
        # renormalise rows
        row_sum = cal_p_test.sum(axis=1, keepdims=True)
        cal_p_test /= np.maximum(row_sum, 1e-9)
        y_pred_raw = raw_p_test.argmax(axis=1)
        y_pred_cal = cal_p_test.argmax(axis=1)
    else:
        raw_p_cal  = model.predict_proba(X_cal)[:, 1]
        raw_p_test = model.predict_proba(X_test)[:, 1]
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(raw_p_cal, y_cal)
        cal_p_test = iso.predict(raw_p_test)
        y_pred_raw = (raw_p_test  >= 0.5).astype(int)
        y_pred_cal = (cal_p_test >= 0.5).astype(int)

    return accuracy_score(y_test, y_pred_raw), accuracy_score(y_test, y_pred_cal)


def _feats(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Subset to available feature columns (handles folds missing optional cols)."""
    return df[[c for c in cols if c in df.columns]]


def run_fold(df: pd.DataFrame, cal_year: int) -> dict | None:
    t_end   = _season_boundary(cal_year)
    cal_end = _season_boundary(cal_year + 1)
    tst_end = _season_boundary(cal_year + 2)

    train = df[df["Date"] < t_end]
    cal   = df[(df["Date"] >= t_end)   & (df["Date"] < cal_end)]
    test  = df[(df["Date"] >= cal_end) & (df["Date"] < tst_end)]

    if len(train) < 3_000 or len(cal) < 200 or len(test) < 200:
        return None

    # val split for early stopping: last 15% of train
    n_val = max(200, int(len(train) * 0.15))
    inner = train.iloc[:-n_val]
    val   = train.iloc[-n_val:]

    # ── Result (3-class: 0=H 1=D 2=A) ────────────────────────────────────────
    X_i = _feats(inner, RESULT_FEATURE_COLS)
    X_v = _feats(val,   RESULT_FEATURE_COLS)
    X_c = _feats(cal,   RESULT_FEATURE_COLS)
    X_t = _feats(test,  RESULT_FEATURE_COLS)

    res_model = _train_xgb(X_i, inner["target_result"], inner["Date"],
                            X_v, val["target_result"],
                            n_classes=3, dropout_market=True, seed_offset=cal_year)
    res_raw, res_cal = _iso_calibrate(res_model, X_c, cal["target_result"],
                                       X_t, test["target_result"], n_classes=3)

    # ── Goals (binary: over 2.5) ──────────────────────────────────────────────
    X_i_g = _feats(inner, GOALS_FEATURE_COLS)
    X_v_g = _feats(val,   GOALS_FEATURE_COLS)
    X_c_g = _feats(cal,   GOALS_FEATURE_COLS)
    X_t_g = _feats(test,  GOALS_FEATURE_COLS)

    goals_model = _train_xgb(X_i_g, inner["target_goals"], inner["Date"],
                              X_v_g, val["target_goals"],
                              n_classes=2, dropout_market=True, seed_offset=cal_year + 100)
    goals_raw, goals_cal = _iso_calibrate(goals_model, X_c_g, cal["target_goals"],
                                           X_t_g, test["target_goals"], n_classes=2)

    # ── BTTS (binary) ─────────────────────────────────────────────────────────
    X_i_b = _feats(inner, BTTS_FEATURE_COLS)
    X_v_b = _feats(val,   BTTS_FEATURE_COLS)
    X_c_b = _feats(cal,   BTTS_FEATURE_COLS)
    X_t_b = _feats(test,  BTTS_FEATURE_COLS)

    btts_model = _train_xgb(X_i_b, inner["target_btts"], inner["Date"],
                             X_v_b, val["target_btts"],
                             n_classes=2, dropout_market=False, seed_offset=cal_year + 200)
    btts_raw, btts_cal = _iso_calibrate(btts_model, X_c_b, cal["target_btts"],
                                         X_t_b, test["target_btts"], n_classes=2)

    return {
        "cal_season":  f"{cal_year}/{str(cal_year + 1)[-2:]}",
        "test_season": f"{cal_year + 1}/{str(cal_year + 2)[-2:]}",
        "n_train":  len(train),
        "n_cal":    len(cal),
        "n_test":   len(test),
        "res_raw":    round(res_raw,   4),
        "res_cal":    round(res_cal,   4),
        "goals_raw":  round(goals_raw, 4),
        "goals_cal":  round(goals_cal, 4),
        "btts_raw":   round(btts_raw,  4),
        "btts_cal":   round(btts_cal,  4),
    }


def print_table(rows: list[dict]) -> None:
    hdr = (f"{'Cal season':<12} {'Test season':<12} "
           f"{'n_train':>8} {'n_test':>7}  "
           f"{'Res raw':>7} {'Res cal':>7}  "
           f"{'Gls raw':>7} {'Gls cal':>7}  "
           f"{'BTTS raw':>8} {'BTTS cal':>8}")
    sep = "─" * len(hdr)
    print(f"\n{sep}")
    print(hdr)
    print(sep)
    for r in rows:
        print(
            f"{r['cal_season']:<12} {r['test_season']:<12} "
            f"{r['n_train']:>8,} {r['n_test']:>7,}  "
            f"{r['res_raw']:>7.3f} {r['res_cal']:>7.3f}  "
            f"{r['goals_raw']:>7.3f} {r['goals_cal']:>7.3f}  "
            f"{r['btts_raw']:>8.3f} {r['btts_cal']:>8.3f}"
        )
    print(sep)

    res_cals   = [r["res_cal"]   for r in rows]
    goals_cals = [r["goals_cal"] for r in rows]
    btts_cals  = [r["btts_cal"]  for r in rows]

    print(
        f"{'MEAN':<26} {'':>8} {'':>7}  "
        f"{'':>7} {np.mean(res_cals):>7.3f}  "
        f"{'':>7} {np.mean(goals_cals):>7.3f}  "
        f"{'':>8} {np.mean(btts_cals):>8.3f}"
    )
    print(
        f"{'STD':<26} {'':>8} {'':>7}  "
        f"{'':>7} {np.std(res_cals):>7.3f}  "
        f"{'':>7} {np.std(goals_cals):>7.3f}  "
        f"{'':>8} {np.std(btts_cals):>8.3f}"
    )

    xs = np.arange(len(rows), dtype=float)
    print("\n  Trend (linear slope per fold, in pp):")
    for label, vals in [
        ("Result cal",     res_cals),
        ("Goals cal",      goals_cals),
        ("BTTS cal",       btts_cals),
    ]:
        slope = np.polyfit(xs, vals, 1)[0] * 100
        arrow = "↑" if slope > 0.05 else ("↓" if slope < -0.05 else "→")
        print(f"    {label:<16}: {slope:+.3f} pp/fold {arrow}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Walk-forward validation")
    parser.add_argument("--min-train", type=int, default=DEFAULT_MIN_TRAIN_SEASONS,
                        help=f"Min training seasons before first fold (default: {DEFAULT_MIN_TRAIN_SEASONS})")
    parser.add_argument("--last-cal",  type=int, default=LAST_CAL_YEAR,
                        help=f"Last cal year (default: {LAST_CAL_YEAR})")
    parser.add_argument("--csv",       type=str, default=None,
                        help="Export fold metrics to CSV")
    args = parser.parse_args()

    first_cal = DATA_START_YEAR + args.min_train
    n_folds   = args.last_cal - first_cal + 1

    print("=" * 70)
    print("Walk-forward validation — expanding training window, XGBoost per fold")
    print(f"  Folds : {first_cal}/{str(first_cal+1)[-2:]} → {args.last_cal}/{str(args.last_cal+1)[-2:]}  ({n_folds} folds)")
    print(f"  Min training seasons before first fold: {args.min_train}")
    print("=" * 70)

    print("\nPreparing data (feature engineering — runs once) …")
    df = prepare_data(RAW_DIR)
    print(f"  {len(df):,} rows ready\n")

    results = []
    for i, cal_year in enumerate(range(first_cal, args.last_cal + 1), 1):
        print(f"[Fold {i:>2}/{n_folds}] cal={cal_year}/{str(cal_year+1)[-2:]}  "
              f"test={cal_year+1}/{str(cal_year+2)[-2:]} …",
              end=" ", flush=True)
        row = run_fold(df, cal_year)
        if row is None:
            print("skipped")
            continue
        results.append(row)
        print(f"res={row['res_cal']:.3f}  goals={row['goals_cal']:.3f}  "
              f"btts={row['btts_cal']:.3f}  "
              f"(train={row['n_train']:,}  test={row['n_test']:,})")

    if not results:
        print("No folds completed.")
        return

    print_table(results)

    print("Production baseline (single split, all history → 2024/25+2025/26 test):")
    print("  Result cal: 52.8%   Goals cal: 58.1%   BTTS: 51.6%")
    print()

    if args.csv:
        pd.DataFrame(results).to_csv(args.csv, index=False)
        print(f"Exported → {args.csv}")


if __name__ == "__main__":
    main()
