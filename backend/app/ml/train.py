"""
Train four XGBoost models and save them as .pkl files.

  model_result.pkl  → Win / Draw / Loss  (3-class: 0=H, 1=D, 2=A)
  model_goals.pkl   → Over / Under 2.5   (binary:  1=over, 0=under)
  draw_classifier.pkl / draw_calibrator.pkl → draw specialist (blended with main result model)
  btts_classifier.pkl / btts_calibrator.pkl → Both Teams To Score (binary: GG / NG)

Why XGBoost:
  - Histogram-based gradient boosting: fast on mid-size tabular data.
  - scale_pos_weight for class imbalance (result model, BTTS model).
  - Isotonic calibration applied post-training for well-calibrated probabilities.
  - Native GPU support if available (tree_method="hist").

Why Pi-Ratings alongside Elo:
  - Pi-Ratings separate attack/defense and home/away contexts.
  - They update by goal margin, not just win/loss — richer signal.

Three-way time split:
  - XGBoost trains on everything before CAL_CUTOFF (2024-07-01).
  - Calibration set (2024-07-01 → TRAIN_CUTOFF 2025-07-01): fits isotonic regressors + BTTS threshold sweep.
  - Test set (TRAIN_CUTOFF → TEST_CUTOFF 2026-09-01): held-out evaluation only.

Usage:
  python -m backend.app.ml.train
  # or from repo root:
  python backend/app/ml/train.py
"""

from __future__ import annotations

import os
import pickle
import sys

import numpy as np
import pandas as pd
import lightgbm as lgb
from lightgbm import LGBMClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from backend.app.ml.features import (
    FEATURE_COLS, RESULT_FEATURE_COLS, GOALS_FEATURE_COLS, BTTS_FEATURE_COLS,
    build_features, load_raw_csvs,
    load_xg_data, merge_xg, XG_DIR,
)
from backend.app.ml.european import load_european_data, EUROPEAN_DIR, EUROPEAN_FEATURE_COLS
from backend.app.ml.poisson import POISSON_FEATURE_COLS
from backend.app.ml.predict import SoftVoteEnsemble  # defined there so pickle loads from any __main__
from backend.app.ml.calibration import fit_calibrators, save_calibrators
from backend.app.ml.draw_classifier import (
    fit_draw_classifier, save_draw_classifier, save_draw_calibrator,
    DRAW_FEATURE_COLS,
)
from backend.app.ml.btts_classifier import (
    fit_btts_classifier, save_btts_classifier, save_btts_calibrator,
)

RAW_DIR    = os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw")
MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models")

# Three-way time split:
#   XGBoost trains on everything up to end of 2022/23  (oldest → richest training set)
#   Calibration set  = 2023/24 season                  (held-out, fits isotonic regressors)
#   Test set         = 2024/25 season                  (never seen during training or calibration)
#
# Using a separate calibration season avoids calibrating on the same data that
# tunes XGBoost's trees (which would overfit the calibration curve) while still
# keeping the test set clean for unbiased accuracy reporting.
CAL_CUTOFF    = pd.Timestamp("2024-07-01")   # end of 2023/24 → XGBoost training cutoff
TRAIN_CUTOFF  = pd.Timestamp("2025-07-01")   # end of 2024/25 → calibration cutoff
TEST_CUTOFF   = pd.Timestamp("2026-09-01")   # 2025/26 season end → test
RECENT_CUTOFF = pd.Timestamp("2019-07-01")   # walk-forward recency member: 2019/20+ only

# Optional features that may contain NaN — impute before passing to XGBoost.
SHOTS_COLS  = ["h_shots_ot_5", "h_shots_otc_5", "a_shots_ot_5", "a_shots_otc_5"]
MARKET_COLS = ["market_home_prob", "market_draw_prob", "market_away_prob", "market_over_prob"]
XG_COLS     = [
    "h_xg_scored_5", "h_xg_conceded_5", "a_xg_scored_5", "a_xg_conceded_5",
    "h_xg_scored_10", "h_xg_conceded_10", "a_xg_scored_10", "a_xg_conceded_10",
]
# Referee features — EPL only; NaN for other leagues and upcoming matches.
# Imputed to the training-set median so non-EPL rows get a neutral prior.
REF_COLS    = ["ref_home_win_rate", "ref_draw_rate", "ref_cards_per_game"]

# Poisson features — NaN for first MIN_SEASON_MATCHES of each season/league.
# Imputed with training-set median (neutral prior for cold-start matches).
POISSON_COLS = POISSON_FEATURE_COLS

# Exponential time-decay: a match this many days before TRAIN_CUTOFF gets weight 0.5.
# 3-year half-life: 2020/21 season (~1000 days ago) gets weight ~0.80, 2015/16 (~2800 days) ~0.28.
TIME_DECAY_HALF_LIFE = 365 * 3


def _time_decay_weights(dates: pd.Series) -> np.ndarray:
    """
    Exponential decay weighting so recent seasons matter more than old ones.
    Normalised to mean=1 so the overall gradient magnitude stays unchanged.
    """
    k = np.log(2) / TIME_DECAY_HALF_LIFE
    days_old = (TRAIN_CUTOFF - dates).dt.days.clip(lower=0).values.astype(float)
    w = np.exp(-k * days_old)
    return w / w.mean()


# Persisted imputation medians — the single source of truth for every consumer
# (train, predict.py, compute_predictions.py, backtest_2526.py). Written at
# train time from PRE-CAL rows only (no fit-before-split), loaded everywhere
# else so train/serve/backtest all see the same fill values.
IMPUTE_MEDIANS_PATH = os.path.join(MODELS_DIR, "impute_medians.json")


def _impute_optional(df: pd.DataFrame, save_medians: bool = True) -> pd.DataFrame:
    """
    Impute optional features and persist the fill values.

    Medians are computed ONLY on rows before CAL_CUTOFF (the model-training
    window) — computing them on the full frame would leak cal/test information
    into training rows (textbook fit-before-split; measured impact ≈0 here, but
    structurally wrong). The whole frame is then filled with those values.

    Shots on target  → pre-CAL median.
    European features → 0 (not in Europe = no fatigue, neutral result).
    xG / market / Poisson → pre-CAL median with documented fallbacks.
    Referee features: deliberately NOT imputed (XGBoost handles NaN natively;
    a fake "average referee" in no-data leagues hurts more than it helps).
    """
    df = df.copy()
    train_mask = df["Date"] < CAL_CUTOFF
    medians: dict[str, float] = {}

    def _fill(col: str, fallback: float) -> None:
        m = df.loc[train_mask, col].median()
        v = float(m) if pd.notna(m) else float(fallback)
        medians[col] = round(v, 6)
        df[col] = df[col].fillna(v)

    for col in SHOTS_COLS:
        _fill(col, 0.0)
    for col in EUROPEAN_FEATURE_COLS:
        medians[col] = 0.0
        df[col] = df[col].fillna(0.0)
    for col in XG_COLS:
        if col in df.columns:
            _fill(col, 1.5)
    for col in MARKET_COLS:
        if col in df.columns:
            _fill(col, 1 / 3)
    for col in POISSON_COLS:
        if col in df.columns:
            if "lambda" in col:
                fb = 1.5
            elif col in ("poisson_home_attack", "poisson_away_defense"):
                fb = 1.0
            else:
                fb = 1.0 / 3
            _fill(col, fb)

    if save_medians:
        import json
        os.makedirs(MODELS_DIR, exist_ok=True)
        with open(IMPUTE_MEDIANS_PATH, "w") as f:
            json.dump(medians, f, indent=2, sort_keys=True)
        print(f"  Imputation medians (pre-CAL rows only) saved → {IMPUTE_MEDIANS_PATH}")
    return df


def prepare_data(raw_dir: str) -> pd.DataFrame:
    print("Loading CSVs …")
    df = load_raw_csvs(raw_dir)
    print(f"  {len(df):,} raw matches loaded")

    print("Loading xG data (understat) …")
    xg_df = load_xg_data(XG_DIR)
    if xg_df is not None:
        df = merge_xg(df, xg_df)
        n_xg = df["home_xg"].notna().sum()
        print(f"  {len(xg_df):,} xG records loaded, {n_xg:,} matched to training rows")
    else:
        print("  No xG data found in", XG_DIR, "— xG features will be imputed with median")

    print("Loading European competition data …")
    eur_df = load_european_data(EUROPEAN_DIR)
    if eur_df is not None:
        print(f"  {len(eur_df):,} European fixtures loaded "
              f"({(eur_df['status']=='FINISHED').sum()} played)")
    else:
        print("  No European data found — congestion features will be 0")

    print("Engineering features …")
    df = build_features(df, european_df=eur_df)

    # Exclude 2020/21 COVID season — no crowds → home advantage signal distorted.
    covid_mask = (df["Date"] >= "2020-07-01") & (df["Date"] < "2021-07-01")
    df = df[~covid_mask].copy()
    print(f"  {covid_mask.sum():,} COVID-season rows excluded")

    # Drop rows where core features are NaN (first few matches per team).
    # Pi-Ratings start at 0.0 (not NaN) so they never cause row drops here.
    optional_feats = (set(SHOTS_COLS) | set(EUROPEAN_FEATURE_COLS) | set(MARKET_COLS) |
                  set(XG_COLS) | set(REF_COLS) | set(POISSON_COLS) |
                  {"h2h_draw_rate",    # NaN when teams have no H2H history
                   # H2H goals — NaN until first meeting between this pair
                   "h2h_home_goals_avg", "h2h_away_goals_avg", "h2h_total_goals_avg",
                   "h2h_btts_rate", "h2h_over25_rate",
                   "goals_asymmetry_5", "combined_draw_tendency", "pi_closeness",
                   "market_draw_edge", "low_total_xg", "elo_closeness",
                   # EWMA / league-position: NaN for first few team/season matches
                   "h_ewma_scored", "h_ewma_conceded", "a_ewma_scored", "a_ewma_conceded",
                   "h_ewma_form", "a_ewma_form",
                   "h_league_pos_norm", "a_league_pos_norm", "league_pos_diff",
                   # Motivation: NaN until ≥3 teams have played in the season
                   "h_pts_vs_cl", "a_pts_vs_cl",
                   "h_pts_vs_relegation", "a_pts_vs_relegation",
                   "motivation_diff"})
    core_feats = [f for f in FEATURE_COLS if f not in optional_feats]
    before = len(df)
    df = df.dropna(subset=core_feats)
    print(f"  {before - len(df):,} rows dropped (insufficient history), {len(df):,} remain")

    # Impute optional features — XGBoost handles NaN natively but imputation
    # gives more stable splits for lower-frequency features.
    df = _impute_optional(df)
    print("  Optional features imputed (shots → median, European → 0)")

    # Targets
    df["target_result"] = df.apply(
        lambda r: 0 if r["home_goals"] > r["away_goals"]
                  else (1 if r["home_goals"] == r["away_goals"] else 2),
        axis=1,
    )  # 0=HomeWin, 1=Draw, 2=AwayWin

    df["target_goals"] = (df["home_goals"] + df["away_goals"] > 2.5).astype(int)
    df["target_btts"]  = ((df["home_goals"] > 0) & (df["away_goals"] > 0)).astype(int)

    return df


def split(df: pd.DataFrame):
    """Return (xgb_train, cal, test) — three non-overlapping time splits."""
    xgb_train = df[df["Date"] < CAL_CUTOFF]
    cal       = df[(df["Date"] >= CAL_CUTOFF) & (df["Date"] < TRAIN_CUTOFF)]
    test      = df[(df["Date"] >= TRAIN_CUTOFF) & (df["Date"] < TEST_CUTOFF)]
    print(f"  XGBoost train : {len(xgb_train):,}  "
          f"| Calibration : {len(cal):,}  "
          f"| Test : {len(test):,}")
    return xgb_train, cal, test


def _val_split(train: pd.DataFrame, val_frac: float = 0.15) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Carve the last val_frac of rows (by date) out of train for XGBoost early-stopping.
    This avoids using the held-out TEST set for early stopping (which would be data leakage).
    The calibration set is used separately for isotonic calibration — it is NOT used here.
    """
    n_val = max(200, int(len(train) * val_frac))
    inner = train.iloc[:-n_val]
    val   = train.iloc[-n_val:]
    print(f"  Early-stopping val split: {len(inner):,} train / {n_val:,} val "
          f"(last {val_frac:.0%} of XGBoost train set)")
    return inner, val


def _result_scoring_report(probs: np.ndarray, y_true: pd.Series, test: pd.DataFrame) -> dict:
    """Proper scoring rules + baselines for the 3-way result model on the test set.

    Accuracy alone is a bad 3-class metric (a model that never predicts Draw can
    'win' on accuracy). Log-loss/Brier/RPS grade the full probability vector, and
    the two baselines anchor the numbers: always-home (naive) and the de-vigged
    bookmaker (the sharp ceiling — beat it or you have no edge).
    """
    from sklearn.metrics import log_loss

    y = y_true.to_numpy()
    n = len(y)
    onehot = np.zeros((n, 3))
    onehot[np.arange(n), y] = 1.0

    ll    = float(log_loss(y, probs, labels=[0, 1, 2]))
    brier = float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))
    # Ranked Probability Score — respects the H<D<A ordering.
    cp, co = np.cumsum(probs, axis=1), np.cumsum(onehot, axis=1)
    rps = float(np.mean(np.sum((cp[:, :2] - co[:, :2]) ** 2, axis=1) / 2.0))

    # Baseline 1: always predict Home at the train-era base rates.
    base_rates = np.array([0.44, 0.26, 0.30])
    ll_home  = float(log_loss(y, np.tile(base_rates, (n, 1)), labels=[0, 1, 2]))
    acc_home = float(np.mean(y == 0))

    # Baseline 2: de-vigged bookmaker probabilities, where present in the test
    # rows. NOTE: market_*_prob may be median-imputed for rows without odds —
    # restrict to rows where all three are present and off-median-ish by using
    # the raw columns directly (coverage printed alongside).
    out = {
        "test_log_loss": round(ll, 4), "test_brier": round(brier, 4),
        "test_rps": round(rps, 4),
        "baseline_home_acc": round(acc_home, 4), "baseline_home_log_loss": round(ll_home, 4),
    }
    mk_cols = ["market_home_prob", "market_draw_prob", "market_away_prob"]
    if all(c in test.columns for c in mk_cols):
        mk = test[mk_cols].to_numpy(dtype=float)
        ok = ~np.isnan(mk).any(axis=1)
        if ok.sum() >= 100:
            mk_ok = mk[ok] / mk[ok].sum(axis=1, keepdims=True)
            ll_bm  = float(log_loss(y[ok], mk_ok, labels=[0, 1, 2]))
            ll_us  = float(log_loss(y[ok], probs[ok], labels=[0, 1, 2]))
            out["bookmaker_log_loss"]     = round(ll_bm, 4)
            out["model_log_loss_same_rows"] = round(ll_us, 4)
            out["bookmaker_coverage"]     = round(float(ok.mean()), 3)
    print(f"  [Scoring] log-loss={ll:.4f}  Brier={brier:.4f}  RPS={rps:.4f}")
    print(f"  [Baseline] always-home: acc={acc_home:.3f} log-loss={ll_home:.4f}")
    if "bookmaker_log_loss" in out:
        print(f"  [Baseline] de-vig bookmaker log-loss={out['bookmaker_log_loss']:.4f} "
              f"vs model {out['model_log_loss_same_rows']:.4f} "
              f"(coverage {out['bookmaker_coverage']:.0%}) — beat the bookmaker or no edge")
    return out


def train_result_model(train: pd.DataFrame, test: pd.DataFrame) -> SoftVoteEnsemble:
    print("\n--- Result model (Win/Draw/Loss) — XGBoost + LightGBM + MLP ---")
    inner, val = _val_split(train)
    X_train, y_train = inner[RESULT_FEATURE_COLS], inner["target_result"]
    X_val,   y_val   = val[RESULT_FEATURE_COLS],   val["target_result"]
    X_test,  y_test  = test[RESULT_FEATURE_COLS],  test["target_result"]
    # (Market-feature NaN dropout removed 2026-07: MARKET_COLS ∩ RESULT_FEATURE_COLS
    #  is empty since the 2026-06-17 market-independent refactor — it was a no-op.)

    # Combined weights: class balance × time decay.
    class_w  = compute_sample_weight("balanced", y_train)
    decay_w  = _time_decay_weights(inner["Date"])
    sample_weights = class_w * decay_w
    sample_weights = sample_weights / sample_weights.mean()

    # ── XGBoost ───────────────────────────────────────────────────────────────
    print("  [XGBoost] training …")
    xgb_model = XGBClassifier(
        n_estimators=800, max_depth=4, learning_rate=0.03,
        subsample=0.75, colsample_bytree=0.7, min_child_weight=5,
        gamma=0.1, reg_alpha=0.1, reg_lambda=1.5,
        eval_metric="mlogloss", early_stopping_rounds=50,
        tree_method="hist", nthread=-1, random_state=42,
    )
    xgb_model.fit(X_train, y_train, sample_weight=sample_weights,
                  eval_set=[(X_val, y_val)], verbose=False)
    xgb_acc = accuracy_score(y_val, xgb_model.predict(X_val))
    print(f"  [XGBoost] val acc={xgb_acc:.3f}")

    # ── LightGBM ──────────────────────────────────────────────────────────────
    # Leaf-wise tree growth (different inductive bias from XGB's depth-wise).
    # Errors from the two boosters are partially uncorrelated → ensemble gain.
    print("  [LightGBM] training …")
    lgbm_model = LGBMClassifier(
        n_estimators=800, num_leaves=63, learning_rate=0.03,
        subsample=0.75, colsample_bytree=0.7, min_child_samples=20,
        reg_alpha=0.1, reg_lambda=1.5,
        random_state=42, verbose=-1, n_jobs=-1,
    )
    lgbm_model.fit(
        X_train, y_train, sample_weight=sample_weights,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(period=-1)],
    )
    lgbm_acc = accuracy_score(y_val, lgbm_model.predict(X_val))
    print(f"  [LightGBM] val acc={lgbm_acc:.3f}")

    # ── MLP ───────────────────────────────────────────────────────────────────
    # Learns nonlinear feature interactions that tree models may miss.
    # Pipeline: median imputation (handles NaN) → StandardScaler → MLP.
    # Note: MLPClassifier does not support sample_weight; relies on XGB + LGBM
    # for class balance. Uses equal class treatment.
    print("  [MLP] training …")
    mlp_model = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler",  StandardScaler()),
        ("mlp",     MLPClassifier(
            hidden_layer_sizes=(256, 128, 64), activation="relu", solver="adam",
            max_iter=300, early_stopping=True, validation_fraction=0.1,
            n_iter_no_change=20, random_state=42,
        )),
    ])
    mlp_model.fit(X_train, y_train)
    mlp_acc = accuracy_score(y_val, mlp_model.predict(X_val))
    print(f"  [MLP]     val acc={mlp_acc:.3f}")

    # ── XGBoost-recent (walk-forward recency member: RECENT_CUTOFF+ only) ────
    # Trained on recent seasons only with flat class weights (no time-decay —
    # data window already enforces recency). Specialises in current-era patterns
    # and complements the full-history members.
    print(f"  [XGBoost-recent] training on {RECENT_CUTOFF.year}/{str(RECENT_CUTOFF.year+1)[-2:]}+ data …")
    _recent_r = train[train["Date"] >= RECENT_CUTOFF]
    if len(_recent_r) >= 3_000:
        _n_rv = max(200, int(len(_recent_r) * 0.15))
        _r_inner = _recent_r.iloc[:-_n_rv]
        _r_val   = _recent_r.iloc[-_n_rv:]
        _X_ri = _r_inner[RESULT_FEATURE_COLS]
        _X_rv = _r_val[RESULT_FEATURE_COLS]
        _y_ri, _y_rv = _r_inner["target_result"], _r_val["target_result"]

        _sw_ri = compute_sample_weight("balanced", _y_ri)   # flat weights — no time-decay

        xgb_recent = XGBClassifier(
            n_estimators=800, max_depth=4, learning_rate=0.03,
            subsample=0.75, colsample_bytree=0.7, min_child_weight=5,
            gamma=0.1, reg_alpha=0.1, reg_lambda=1.5,
            eval_metric="mlogloss", early_stopping_rounds=50,
            tree_method="hist", nthread=-1, random_state=77,
        )
        xgb_recent.fit(_X_ri, _y_ri, sample_weight=_sw_ri,
                       eval_set=[(_X_rv, _y_rv)], verbose=False)
        _acc_recent = accuracy_score(_y_rv, xgb_recent.predict(_X_rv))
        print(f"  [XGBoost-recent] val acc={_acc_recent:.3f}  (n={len(_recent_r):,} rows)")
        ensemble = SoftVoteEnsemble([xgb_model, lgbm_model, mlp_model, xgb_recent], [1, 1, 1, 1])
    else:
        print(f"  [XGBoost-recent] skipped — insufficient data ({len(_recent_r):,} rows)")
        ensemble = SoftVoteEnsemble([xgb_model, lgbm_model, mlp_model], [1, 1, 1])

    # ── Soft-vote ensemble ────────────────────────────────────────────────────
    # NOTE: the fixed 2025/26 test window is FINAL-REPORT-ONLY. Member selection,
    # weights and thresholds must be decided on val/cal or walk_forward_eval fold
    # means — never against this window (adaptive reuse inflates it).
    probs = ensemble.predict_proba(X_test)
    preds = ensemble.classes_[np.argmax(probs, axis=1)]
    acc   = accuracy_score(y_test, preds)
    print(f"  [Ensemble] test accuracy: {acc:.3f}")
    report = classification_report(y_test, preds,
                                   target_names=["HomeWin", "Draw", "AwayWin"],
                                   output_dict=True)
    print(classification_report(y_test, preds, target_names=["HomeWin", "Draw", "AwayWin"]))
    scoring = _result_scoring_report(probs, y_test, test)
    metrics = {
        **scoring,
        "result_test_accuracy":  round(acc, 4),
        "result_home_recall":    round(report["HomeWin"]["recall"], 4),
        "result_draw_recall":    round(report["Draw"]["recall"], 4),
        "result_away_recall":    round(report["AwayWin"]["recall"], 4),
        "result_home_precision": round(report["HomeWin"]["precision"], 4),
        "result_draw_precision": round(report["Draw"]["precision"], 4),
        "result_away_precision": round(report["AwayWin"]["precision"], 4),
    }
    return ensemble, metrics


def train_goals_model(train: pd.DataFrame, test: pd.DataFrame) -> SoftVoteEnsemble:
    print("\n--- Goals model (Over/Under 2.5) — XGBoost + LightGBM + MLP ---")
    inner, val = _val_split(train)
    X_train, y_train = inner[GOALS_FEATURE_COLS], inner["target_goals"]
    X_val,   y_val   = val[GOALS_FEATURE_COLS],   val["target_goals"]
    X_test,  y_test  = test[GOALS_FEATURE_COLS],  test["target_goals"]
    # (Market-feature NaN dropout removed 2026-07 — dead code, see result model.)

    class_w  = compute_sample_weight("balanced", y_train)
    decay_w  = _time_decay_weights(inner["Date"])
    sample_weights = class_w * decay_w
    sample_weights = sample_weights / sample_weights.mean()

    # ── XGBoost ───────────────────────────────────────────────────────────────
    print("  [XGBoost] training …")
    xgb_model = XGBClassifier(
        n_estimators=1000, max_depth=5, learning_rate=0.02,
        subsample=0.8, colsample_bytree=0.75, colsample_bylevel=0.75,
        min_child_weight=3, gamma=0.05, reg_alpha=0.05, reg_lambda=1.0,
        eval_metric="logloss", early_stopping_rounds=60,
        tree_method="hist", nthread=-1, random_state=42,
    )
    xgb_model.fit(X_train, y_train, sample_weight=sample_weights,
                  eval_set=[(X_val, y_val)], verbose=False)
    xgb_acc = accuracy_score(y_val, xgb_model.predict(X_val))
    print(f"  [XGBoost] val acc={xgb_acc:.3f}")

    # ── LightGBM ──────────────────────────────────────────────────────────────
    print("  [LightGBM] training …")
    lgbm_model = LGBMClassifier(
        n_estimators=1000, num_leaves=63, learning_rate=0.02,
        subsample=0.8, colsample_bytree=0.75, min_child_samples=15,
        reg_alpha=0.05, reg_lambda=1.0,
        random_state=42, verbose=-1, n_jobs=-1,
    )
    lgbm_model.fit(
        X_train, y_train, sample_weight=sample_weights,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(60, verbose=False), lgb.log_evaluation(period=-1)],
    )
    lgbm_acc = accuracy_score(y_val, lgbm_model.predict(X_val))
    print(f"  [LightGBM] val acc={lgbm_acc:.3f}")

    # ── MLP ───────────────────────────────────────────────────────────────────
    print("  [MLP] training …")
    mlp_model = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler",  StandardScaler()),
        ("mlp",     MLPClassifier(
            hidden_layer_sizes=(256, 128, 64), activation="relu", solver="adam",
            max_iter=300, early_stopping=True, validation_fraction=0.1,
            n_iter_no_change=20, random_state=42,
        )),
    ])
    mlp_model.fit(X_train, y_train)
    mlp_acc = accuracy_score(y_val, mlp_model.predict(X_val))
    print(f"  [MLP]     val acc={mlp_acc:.3f}")

    # ── XGBoost-recent (walk-forward recency member: RECENT_CUTOFF+ only) ────
    print(f"  [XGBoost-recent] training on {RECENT_CUTOFF.year}/{str(RECENT_CUTOFF.year+1)[-2:]}+ data …")
    _recent_g = train[train["Date"] >= RECENT_CUTOFF]
    if len(_recent_g) >= 3_000:
        _n_gv = max(200, int(len(_recent_g) * 0.15))
        _g_inner = _recent_g.iloc[:-_n_gv]
        _g_val   = _recent_g.iloc[-_n_gv:]
        _X_gi = _g_inner[GOALS_FEATURE_COLS]
        _X_gv = _g_val[GOALS_FEATURE_COLS]
        _y_gi, _y_gv = _g_inner["target_goals"], _g_val["target_goals"]

        _sw_gi = compute_sample_weight("balanced", _y_gi)   # flat weights — no time-decay

        xgb_recent_g = XGBClassifier(
            n_estimators=1000, max_depth=5, learning_rate=0.02,
            subsample=0.8, colsample_bytree=0.75, colsample_bylevel=0.75,
            min_child_weight=3, gamma=0.05, reg_alpha=0.05, reg_lambda=1.0,
            eval_metric="logloss", early_stopping_rounds=60,
            tree_method="hist", nthread=-1, random_state=78,
        )
        xgb_recent_g.fit(_X_gi, _y_gi, sample_weight=_sw_gi,
                          eval_set=[(_X_gv, _y_gv)], verbose=False)
        _acc_recent_g = accuracy_score(_y_gv, xgb_recent_g.predict(_X_gv))
        print(f"  [XGBoost-recent] val acc={_acc_recent_g:.3f}  (n={len(_recent_g):,} rows)")
        ensemble = SoftVoteEnsemble([xgb_model, lgbm_model, mlp_model, xgb_recent_g], [1, 1, 1, 1])
    else:
        print(f"  [XGBoost-recent] skipped — insufficient data ({len(_recent_g):,} rows)")
        ensemble = SoftVoteEnsemble([xgb_model, lgbm_model, mlp_model], [1, 1, 1])

    # ── Soft-vote ensemble ────────────────────────────────────────────────────
    preds = ensemble.predict(X_test)
    acc   = accuracy_score(y_test, preds)
    print(f"  [Ensemble] test accuracy: {acc:.3f}")
    report = classification_report(y_test, preds, target_names=["Under", "Over"], output_dict=True)
    print(classification_report(y_test, preds, target_names=["Under", "Over"]))
    metrics = {
        "goals_test_accuracy":  round(acc, 4),
        "goals_over_recall":    round(report["Over"]["recall"], 4),
        "goals_under_recall":   round(report["Under"]["recall"], 4),
        "goals_over_precision": round(report["Over"]["precision"], 4),
    }
    return ensemble, metrics


def save_model(model, name: str, models_dir: str):
    os.makedirs(models_dir, exist_ok=True)
    path = os.path.join(models_dir, name)
    with open(path, "wb") as f:
        pickle.dump(model, f)
    print(f"  Saved → {path}")


def _save_training_run(metrics: dict) -> None:
    """Persist training metrics to the DB. Silently skips if DB unavailable.

    Keys without a TrainingRun column (e.g. the scoring-rule report) are folded
    into the free-text `notes` JSON instead of crashing the insert."""
    try:
        import json as _json
        from backend.app.database import SessionLocal
        from backend.app.models.training_run import TrainingRun
        cols = {c.name for c in TrainingRun.__table__.columns}
        known = {k: v for k, v in metrics.items() if k in cols}
        extra = {k: v for k, v in metrics.items() if k not in cols}
        if extra:
            merged_notes = {"scoring": extra}
            if known.get("notes"):
                merged_notes["notes"] = known["notes"]
            known["notes"] = _json.dumps(merged_notes)
        db = SessionLocal()
        try:
            run = TrainingRun(**known)
            db.add(run)
            db.commit()
            print(f"  Training run saved to DB (id will be assigned by DB).")
        finally:
            db.close()
    except Exception as e:
        print(f"  [warn] Could not save training run to DB: {e}")


def main():
    df = prepare_data(RAW_DIR)

    print("\nSplitting data …")
    xgb_train, cal, test = split(df)

    # ── Train XGBoost models on xgb_train, evaluate on test ───────────────────
    result_model, result_metrics = train_result_model(xgb_train, test)
    save_model(result_model, "model_result.pkl", MODELS_DIR)

    goals_model, goals_metrics = train_goals_model(xgb_train, test)
    save_model(goals_model, "model_goals.pkl", MODELS_DIR)

    # ── Fit isotonic calibrators on the held-out calibration season ───────────
    print("\n--- Fitting isotonic calibrators on 2023/24 calibration set ---")
    X_cal_result = cal[RESULT_FEATURE_COLS]
    X_cal_goals  = cal[GOALS_FEATURE_COLS]
    y_cal_result = cal["target_result"].values
    y_cal_goals  = cal["target_goals"].values

    result_cals, goals_cal, league_goals_cals = fit_calibrators(
        result_model, goals_model,
        X_cal_result, y_cal_result, y_cal_goals,
        cal_df=cal,
        X_cal_goals=X_cal_goals,
    )
    save_calibrators(result_cals, goals_cal, league_goals_cals, MODELS_DIR)

    # ── Train draw specialist classifier — XGBoost + LightGBM + MLP ──────────
    _draw_inner, _draw_val = _val_split(xgb_train)
    print("\n--- Draw classifier (binary: is this match a draw?) ---")

    # XGBoost draw (via dedicated function)
    draw_clf_xgb, _draw_val_cal = fit_draw_classifier(
        _draw_inner[RESULT_FEATURE_COLS], _draw_inner["target_result"].values,
        _draw_val[RESULT_FEATURE_COLS],   _draw_val["target_result"].values,
    )
    print("  [XGBoost] draw done")

    # Binary draw labels for LGBM + MLP (1=draw, 0=not draw)
    # Use DRAW_FEATURE_COLS (same subset as fit_draw_classifier uses internally)
    y_draw_inner = (_draw_inner["target_result"].values == 1).astype(int)
    y_draw_val   = (_draw_val["target_result"].values   == 1).astype(int)
    draw_cols    = [c for c in DRAW_FEATURE_COLS if c in _draw_inner.columns]

    # LightGBM draw
    print("  [LightGBM] draw training …")
    draw_clf_lgbm = LGBMClassifier(
        n_estimators=800, num_leaves=63, learning_rate=0.03,
        subsample=0.75, colsample_bytree=0.7, min_child_samples=20,
        reg_alpha=0.1, reg_lambda=1.5, class_weight="balanced",
        random_state=42, verbose=-1, n_jobs=-1,
    )
    draw_clf_lgbm.fit(
        _draw_inner[draw_cols], y_draw_inner,
        eval_set=[(_draw_val[draw_cols], y_draw_val)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(period=-1)],
    )

    # MLP draw
    print("  [MLP] draw training …")
    draw_clf_mlp = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler",  StandardScaler()),
        ("mlp",     MLPClassifier(
            hidden_layer_sizes=(128, 64), activation="relu", solver="adam",
            max_iter=200, early_stopping=True, validation_fraction=0.1,
            n_iter_no_change=15, random_state=42,
        )),
    ])
    draw_clf_mlp.fit(_draw_inner[draw_cols], y_draw_inner)

    # Wrap all three in ensemble; save as model_draw_clf.pkl (transparent to predict.py)
    draw_clf = SoftVoteEnsemble([draw_clf_xgb, draw_clf_lgbm, draw_clf_mlp], [1, 1, 1])
    save_draw_classifier(draw_clf, MODELS_DIR)

    # ── Calibrate draw specialist on held-out calibration set ─────────────────
    print("\n--- Calibrating draw classifier on calibration set ---")
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import brier_score_loss
    from backend.app.ml.draw_classifier import blend_draw_probability
    from backend.app.ml.calibration import _apply_result as _apply_result_cal
    import json

    draw_cols_avail = [c for c in DRAW_FEATURE_COLS if c in cal.columns]
    draw_raw_cal = draw_clf.predict_proba(cal[draw_cols_avail])[:, 1]
    y_cal_draw   = (cal["target_result"].values == 1).astype(float)
    draw_iso = IsotonicRegression(out_of_bounds="clip")
    draw_iso.fit(draw_raw_cal, y_cal_draw)
    draw_cal_probs = draw_iso.predict(draw_raw_cal)
    draw_cal_mean  = draw_cal_probs.mean()
    print(f"  mean raw={draw_raw_cal.mean():.3f}  "
          f"mean calibrated={draw_cal_mean:.3f}  "
          f"actual draw rate={y_cal_draw.mean():.3f}")
    save_draw_calibrator(draw_iso, MODELS_DIR)

    # ── Auto-tune draw blend alpha on calibration set ─────────────────────────
    print("\n--- Tuning draw blend alpha on calibration set ---")
    raw_cal_result_probs = result_model.predict_proba(X_cal_result)
    cal_result_probs     = _apply_result_cal(raw_cal_result_probs, result_cals, batch=True)

    best_alpha, best_brier = 0.20, float("inf")
    for alpha_candidate in np.arange(0.05, 0.50, 0.05):
        blended = []
        for i in range(len(cal)):
            ph, pd_, pa = cal_result_probs[i]
            dc = float(draw_cal_probs[i])
            _, bd, _ = blend_draw_probability(float(ph), float(pd_), float(pa), dc, alpha=float(alpha_candidate))
            blended.append(bd)
        brier = brier_score_loss(y_cal_draw, blended)
        print(f"  alpha={alpha_candidate:.2f}  brier={brier:.5f}")
        if brier < best_brier:
            best_brier  = brier
            best_alpha  = float(alpha_candidate)
    print(f"  → Optimal alpha: {best_alpha:.2f}  (Brier={best_brier:.5f})")

    alpha_path = os.path.join(MODELS_DIR, "draw_alpha.json")
    os.makedirs(MODELS_DIR, exist_ok=True)
    with open(alpha_path, "w") as f:
        json.dump({"draw_blend_alpha": best_alpha}, f)
    print(f"  Draw alpha saved → {alpha_path}")

    # ── Train dedicated BTTS classifier — XGBoost + LightGBM + MLP ───────────
    print("\n--- BTTS classifier (binary: both teams score?) ---")

    # XGBoost BTTS (via dedicated function)
    btts_clf_xgb, _btts_val_cal = fit_btts_classifier(
        _draw_inner, _draw_inner["target_btts"].values,
        _draw_val,   _draw_val["target_btts"].values,
    )
    print("  [XGBoost] BTTS done")

    # LightGBM BTTS
    btts_cols   = [c for c in BTTS_FEATURE_COLS if c in _draw_inner.columns]
    y_btts_inner = _draw_inner["target_btts"].values.astype(int)
    y_btts_val   = _draw_val["target_btts"].values.astype(int)

    print("  [LightGBM] BTTS training …")
    btts_clf_lgbm = LGBMClassifier(
        n_estimators=600, num_leaves=31, learning_rate=0.03,
        subsample=0.8, colsample_bytree=0.8, min_child_samples=20,
        reg_alpha=0.05, reg_lambda=1.0,
        random_state=42, verbose=-1, n_jobs=-1,
    )
    btts_clf_lgbm.fit(
        _draw_inner[btts_cols], y_btts_inner,
        eval_set=[(_draw_val[btts_cols], y_btts_val)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(period=-1)],
    )

    # MLP BTTS
    print("  [MLP] BTTS training …")
    btts_clf_mlp = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler",  StandardScaler()),
        ("mlp",     MLPClassifier(
            hidden_layer_sizes=(128, 64), activation="relu", solver="adam",
            max_iter=200, early_stopping=True, validation_fraction=0.1,
            n_iter_no_change=15, random_state=42,
        )),
    ])
    btts_clf_mlp.fit(_draw_inner[btts_cols], y_btts_inner)

    # Wrap in ensemble; save as model_btts_clf.pkl (transparent to predict.py)
    btts_clf = SoftVoteEnsemble([btts_clf_xgb, btts_clf_lgbm, btts_clf_mlp], [1, 1, 1])
    save_btts_classifier(btts_clf, MODELS_DIR)

    # Calibrate BTTS specialist on cal set
    btts_cols_avail = [c for c in BTTS_FEATURE_COLS if c in cal.columns]
    btts_raw_cal = btts_clf.predict_proba(cal[btts_cols_avail])[:, 1]
    y_cal_btts   = cal["target_btts"].values.astype(float)
    btts_iso = IsotonicRegression(out_of_bounds="clip")
    btts_iso.fit(btts_raw_cal, y_cal_btts)
    btts_cal_mean = btts_iso.predict(btts_raw_cal).mean()
    print(f"  [btts_clf] cal mean raw={btts_raw_cal.mean():.3f}  "
          f"mean calibrated={btts_cal_mean:.3f}  "
          f"actual GG rate={y_cal_btts.mean():.3f}")
    save_btts_calibrator(btts_iso, MODELS_DIR)

    # ── BTTS threshold sweep on cal set (maximise macro F1) ──────────────────
    # Encoding: y_true 1=GG 0=NG; y_pred 1=GG (P>=t) 0=NG (P<t).
    # Objective: macro F1 = mean(GG_F1, NG_F1).
    # Using macro F1 prevents the threshold from collapsing either class:
    #   - NG-only F1 → threshold rises until model always predicts NG
    #   - GG-only F1 → threshold drops until model always predicts GG
    #   - macro F1   → balanced; both classes must be predicted reasonably well
    btts_cal_probs = btts_iso.predict(btts_raw_cal)   # calibrated P(GG) on cal set
    best_btts_threshold, best_macro_f1 = 0.5, 0.0
    for t_candidate in np.arange(0.30, 0.75, 0.01):
        macro_f1 = f1_score(
            y_cal_btts,
            (btts_cal_probs >= t_candidate).astype(int),   # 1=GG, 0=NG
            average="macro", zero_division=0,
        )
        if macro_f1 > best_macro_f1:
            best_macro_f1       = macro_f1
            best_btts_threshold = float(t_candidate)
    # Log per-class F1 at chosen threshold for visibility
    _preds_at_best = (btts_cal_probs >= best_btts_threshold).astype(int)
    _gg_f1 = f1_score(y_cal_btts, _preds_at_best, pos_label=1, zero_division=0)
    _ng_f1 = f1_score(y_cal_btts, _preds_at_best, pos_label=0, zero_division=0)
    print(f"  → Optimal BTTS threshold: {best_btts_threshold:.2f}  "
          f"(macro F1={best_macro_f1:.4f}  GG_F1={_gg_f1:.4f}  NG_F1={_ng_f1:.4f})")
    btts_threshold_path = os.path.join(MODELS_DIR, "btts_threshold.json")
    with open(btts_threshold_path, "w") as f:
        json.dump({"btts_gg_threshold": best_btts_threshold}, f)
    print(f"  BTTS threshold saved → {btts_threshold_path}")

    # BTTS test evaluation
    btts_actual    = test["target_btts"].values
    btts_test_cols = [c for c in BTTS_FEATURE_COLS if c in test.columns]
    btts_raw_test  = btts_clf.predict_proba(test[btts_test_cols])[:, 1]
    btts_cal_test  = btts_iso.predict(btts_raw_test)
    btts_pred      = (btts_cal_test >= best_btts_threshold).astype(int)
    btts_report    = classification_report(
        btts_actual, btts_pred,
        target_names=["NG", "GG"],
        output_dict=True,
        zero_division=0,
    )
    btts_acc = accuracy_score(btts_actual, btts_pred)
    print(f"  BTTS classifier accuracy (threshold={best_btts_threshold:.2f}): {btts_acc:.3f}")
    print(classification_report(btts_actual, btts_pred, target_names=["NG", "GG"], zero_division=0))
    btts_metrics = {
        "btts_test_accuracy": round(btts_acc, 4),
        "btts_gg_recall":     round(btts_report["GG"]["recall"], 4),
        "btts_ng_recall":     round(btts_report["NG"]["recall"], 4),
        "btts_gg_precision":  round(btts_report["GG"]["precision"], 4),
        "btts_ng_precision":  round(btts_report["NG"]["precision"], 4),
        "btts_threshold":     round(best_btts_threshold, 2),
    }

    # ── Persist all metrics to DB ──────────────────────────────────────────────
    print("\n--- Saving training run metrics ---")
    run_metrics = {
        "model_version":   os.getenv("MODEL_VERSION", "1.0.0"),
        "n_train":         len(xgb_train),
        "n_cal":           len(cal),
        "n_test":          len(test),
        "cal_cutoff":      CAL_CUTOFF.date(),
        "train_cutoff":    TRAIN_CUTOFF.date(),
        "test_cutoff":     TEST_CUTOFF.date(),
        **result_metrics,
        **goals_metrics,
        "draw_raw_mean":    round(float(draw_raw_cal.mean()), 4),
        "draw_cal_mean":    round(float(draw_cal_mean), 4),
        "draw_actual_rate": round(float(y_cal_draw.mean()), 4),
        **btts_metrics,
    }
    _save_training_run(run_metrics)

    print("\nTraining complete — models + calibrators saved to", MODELS_DIR)
    print("Run `compute_predictions.py --force` to recompute all predictions "
          "with the new calibrated model.")


if __name__ == "__main__":
    main()
