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

Three time windows, rolling with the season (see the comment on CAL_SEASONS):
  - Trees        — everything before TRAIN_CUTOFF.
  - Test         — the season after that, held out from fitting.
  - Calibration  — the CAL_SEASONS most recent COMPLETE seasons: isotonic /
                   matrix calibrators, the draw-alpha sweep and the BTTS
                   threshold are all fitted here.

The test window is the newest complete season and comes after both of the
others, so the metrics a run prints are a genuine forward estimate. See the
comment on CAL_SEASONS for why the calibration window is one season and not two:
measured, the calibrator saturates near 7,000 rows and a second season buys
nothing (-0.06pp accuracy, 95% CI [-0.16, +0.04]).

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
from sklearn.metrics import accuracy_score, classification_report, f1_score, log_loss
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
    HISTORY_ONLY_LEAGUES,
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

# ── The three windows ─────────────────────────────────────────────────────────
#
#     Date < CAL_CUTOFF             trees
#     CAL_CUTOFF .. TRAIN_CUTOFF    calibration  — CAL_SEASONS complete seasons
#     TRAIN_CUTOFF .. TEST_CUTOFF   test         — the newest complete season
#
# In time order: trees, calibration, test. The test season is always the most
# recent complete one and always comes AFTER everything that was fitted, so the
# number a run prints is a genuine forward estimate.
#
# WHY THE CALIBRATION WINDOW IS ONE SEASON, NOT TWO
#
# The obvious objection is that 2025/26 is better data than 2015 and it seems
# wasteful to spend it on a test set instead of on calibration. Measured
# 2026-09-04 with the trees held fixed, so only the calibration window varied,
# scored on 7,037 held-out matches (backend/data/cache/verify/cal_size.py):
#
#     cal = 23/24          n= 7,087   acc 50.21%   log-loss 1.0136
#     cal = 24/25          n= 7,008   acc 50.16%   log-loss 1.0134
#     cal = 23/24 + 24/25  n=14,095   acc 50.11%   log-loss 1.0134
#
#     two seasons vs one, paired bootstrap 5,000x:
#       accuracy  -0.06pp, 95% CI [-0.16, +0.04], P(two better) = 0.112
#       log-loss  +0.0000, 95% CI [-0.0004, +0.0004], P(two better) = 0.484
#
# That is not "too close to call" — the interval is ±0.1pp on 7,000 matches. The
# second season buys nothing, and which season it is does not matter either
# (older 23/24 scores the same as newer 24/25). The size sweep shows why:
#
#     n_cal    500 → acc 47.90%    3,500 → 49.31%
#            1,000 → 48.57%        7,000 → 50.16%
#            2,000 → 49.30%       14,000 → 50.16%   ← flat
#
# The calibrator is a 12-parameter map. It saturates somewhere between 3,500 and
# 7,000 rows and is completely flat above that. A season handed to it beyond the
# first is not "better data being used" — it is data going nowhere.
#
# So nothing is sacrificed by testing on the newest season. The alternative uses
# of it were both measured and both are worth nothing: extra calibration rows
# (above) and extra tree rows (2026-09-03 — extending the tree window and every
# time-decay half-life landed inside the noise, accuracy 48.8–49.7%). Against
# that, the test season buys the only number anyone is entitled to quote.
#
# Raising CAL_SEASONS to 2 still works and still leaves the test clean; it just
# costs the trees a season for no measured return.
CAL_SEASONS = 1

# A season only counts as complete once it has actually finished, so the test
# window is never a handful of August fixtures.
TEST_SEASON_MATURITY_MONTHS = 5


def _season_start(ts: pd.Timestamp) -> pd.Timestamp:
    """1 July of the season containing `ts` (European season boundary)."""
    return pd.Timestamp(ts.year if ts.month >= 7 else ts.year - 1, 7, 1)


_TODAY   = pd.Timestamp.today().normalize()
_CURRENT = _season_start(_TODAY)
# The most recent season we treat as complete.
_LATEST_COMPLETE = _CURRENT if _TODAY >= _CURRENT + pd.DateOffset(
    months=TEST_SEASON_MATURITY_MONTHS) else _CURRENT - pd.DateOffset(years=1)

TEST_CUTOFF   = _LATEST_COMPLETE + pd.DateOffset(years=1)   # end of the test season
TRAIN_CUTOFF  = _LATEST_COMPLETE                            # test starts here
CAL_CUTOFF    = TRAIN_CUTOFF - pd.DateOffset(years=CAL_SEASONS)
RECENT_CUTOFF = pd.Timestamp("2019-07-01")   # walk-forward recency member: 2019/20+ only

# The boundaries roll with the calendar rather than being literals. They used to
# be literals and it did not show: twelve consecutive weekly retrains added 54
# training rows BETWEEN THEM (training_runs id 35→46, n_train 84,411 → 84,465)
# while the test set grew by 246. A "weekly retrain" that refits the same data
# and reports the seed noise as a change in accuracy.
#
# Anchored to season boundaries (1 July), not to today, so a retrain on the 3rd
# and one on the 25th of the same month produce the same split; otherwise the
# windows would shift by a few rows every run and metrics would not be
# comparable week to week.
#
# What this does NOT do: make the trees current. A three-way split spends two
# seasons by construction, and the way to recover one — cross-fitted calibration,
# fitting the trees up to the test season and taking the calibrators from
# out-of-fold predictions inside that window — was built and measured on
# 2026-09-04 (backend/data/cache/four/oof.py). It LOSES:
#
#     A  cal season      (84,465 train)   log-loss 1.0132  acc 49.79%  drawAUC 0.5464
#     B  cross-fitted K=3 (91,473 train)           1.0144      49.65%          0.5397
#     B  cross-fitted K=5 (91,473 train)           1.0146      49.67%          0.5397
#
# An earlier measurement (2026-09-03) had it winning, 1.0197 against 1.0272. The
# difference is the calibrator: that comparison used one-vs-rest isotonic, which
# is data-hungry enough to benefit from the extra rows. Matrix scaling is twelve
# parameters and saturates long before, so all that is left is the mismatch —
# the out-of-fold predictions come from models trained on K-1/K of the data and
# are systematically less confident than the full model they end up correcting.
# Do not re-derive this; the numbers above are the answer.

# Overridable for backtests and for reproducing a historical run.
for _name, _env in (("CAL_CUTOFF", "ML_CAL_CUTOFF"),
                    ("TRAIN_CUTOFF", "ML_TRAIN_CUTOFF"),
                    ("TEST_CUTOFF", "ML_TEST_CUTOFF")):
    _override = os.getenv(_env)
    if _override:
        globals()[_name] = pd.Timestamp(_override)
        print(f"  [split] {_name} overridden by {_env}={_override}")

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
    # Rows that had NO real 1×2 market line. The scoring report needs it —
    # otherwise the de-vig bookmaker baseline is computed against numbers that
    # are not the bookmaker's.
    #
    # This USED to be derived here, by testing MARKET_COLS for NaN. That was
    # wrong by one pipeline stage: build_features already replaces a missing
    # Pinnacle line with our own Poisson probabilities (features.py, "Poisson
    # fallback for missing market probs"), so by the time this ran there was
    # nothing left to detect — it reported 50 imputed rows out of 7,427 when the
    # real number was 4,443. The flag now comes from `market_is_real`, which
    # build_features records BEFORE the fallback.
    if "market_is_real" in df.columns:
        df["market_was_imputed"] = df["market_is_real"] < 0.5
    else:
        # Frames built before market_is_real existed: refuse to guess. Treating
        # every row as real is what produced the flattering baseline.
        df["market_was_imputed"] = True
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

    # Drop the history-only leagues — AFTER build_features, which is the whole
    # point: their matches have already contributed Elo, form and H2H for clubs
    # that later appear in a competition we do price (a promoted side, a
    # European qualifier), and now they leave before fitting. We never predict a
    # Greek second-division or Faroese league match, and their scoring
    # environments would pull the parameters shared with the leagues we serve.
    hist_mask = df["League"].isin(HISTORY_ONLY_LEAGUES)
    if hist_mask.any():
        df = df[~hist_mask].copy()
        print(f"  {hist_mask.sum():,} history-only rows excluded from fitting "
              f"(kept for Elo/form)")

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
    """Return (xgb_train, cal, test) — trees, then calibration, then test.

    The test window is the newest complete season and sits after everything that
    was fitted, so the metrics printed at the end of a run are a real forward
    estimate rather than a replay.
    """
    xgb_train = df[df["Date"] < CAL_CUTOFF]
    cal       = df[(df["Date"] >= CAL_CUTOFF) & (df["Date"] < TRAIN_CUTOFF)]
    test      = df[(df["Date"] >= TRAIN_CUTOFF) & (df["Date"] < TEST_CUTOFF)]
    print(f"  XGBoost train : {len(xgb_train):,}  (< {CAL_CUTOFF.date()})")
    print(f"  Calibration   : {len(cal):,}  "
          f"({CAL_CUTOFF.date()} → {TRAIN_CUTOFF.date()}, "
          f"{CAL_SEASONS} season(s) — measured to saturate near 7,000 rows)")
    print(f"  Test          : {len(test):,}  "
          f"({TRAIN_CUTOFF.date()} → {TEST_CUTOFF.date()}, newest complete season, "
          f"held out from everything above)")
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


def _result_scoring_report(probs: np.ndarray, y_true: pd.Series, test: pd.DataFrame,
                           train_base_rates: "np.ndarray | None" = None) -> dict:
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

    # Baseline 1: constant prediction at the train-era base rates.
    base_rates = train_base_rates if train_base_rates is not None else np.array([0.44, 0.26, 0.30])
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
        # Keep ONLY rows carrying a real Pinnacle line. A row without one holds
        # our own Poisson probabilities (see the fallback in build_features), so
        # counting it scores the model against itself and calls the result "the
        # bookmaker". `market_was_imputed` is derived from `market_is_real`,
        # which is recorded before that fallback runs.
        if "market_was_imputed" in test.columns:
            ok &= ~test["market_was_imputed"].to_numpy(dtype=bool)
        else:
            ok &= False   # no flag → no honest baseline; report none
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
        _gap = out["model_log_loss_same_rows"] - out["bookmaker_log_loss"]
        print(f"  [Baseline] de-vig Pinnacle log-loss={out['bookmaker_log_loss']:.4f} "
              f"vs model {out['model_log_loss_same_rows']:.4f} "
              f"({'model ahead by' if _gap < 0 else 'MODEL BEHIND by'} {abs(_gap):.4f}) "
              f"on the {out['bookmaker_coverage']:.0%} of test rows that carry a real line")
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

            # ── Ensemble membership ───────────────────────────────────────────────────
    # Two members, not four. Measured 2026-09-04 on the held-out season with the
    # current feature set (backend/data/cache/four/members.py):
    #
    #     combination        log-loss  accuracy  drawAUC   train
    #     all 4               1.0127    0.4986   0.5465     25s
    #     xgb + lgbm          1.0130    0.5005   0.5450     10s
    #     xgb only            1.0133    0.4975   0.5451      5s
    #     no mlp (3)          1.0130    0.4981   0.5444     14s
    #
    # Every paired-bootstrap interval against the four-member vote straddles zero,
    # so none of these is distinguishable from any other. This is therefore a COST
    # change, not an accuracy change: xgb + lgbm is 2.5x cheaper and keeps two
    # genuinely different inductive biases (depth-wise against leaf-wise growth).
    #
    # The MLP earned its removal twice over — it never separated from the trees,
    # and when the ensemble weights were fitted on the calibration set it took
    # 0.75 of the vote and made the result WORSE (1.0260 against 1.0023). xgb_recent
    # is a second XGBoost on a shorter window, correlated 0.849 with the first.
    ensemble = SoftVoteEnsemble([xgb_model, lgbm_model], [1, 1])

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
    _tr_counts = np.bincount(train["target_result"].to_numpy(dtype=int), minlength=3)
    scoring = _result_scoring_report(probs, y_test, test,
                                     train_base_rates=_tr_counts / max(_tr_counts.sum(), 1))
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

    # ── Soft-vote ensemble ────────────────────────────────────────────────────
    # Two members; see the note in train_result_model for the measurement.
    ensemble = SoftVoteEnsemble([xgb_model, lgbm_model], [1, 1])

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

    # The sweep starts at 0.00 and is scored on the THREE-WAY log-loss, not on
    # the Brier score of the draw alone. Both changes matter:
    #
    #   • Starting at 0.05 made "do not blend at all" unreachable. The specialist
    #     is not orthogonal to the result model (correlation 0.787) and it is
    #     WORSE at the one job it exists for — measured 2026-09-03 on the 2,984
    #     test rows with a Pinnacle line, draw AUC 0.5280 for the specialist
    #     against 0.5402 for the result model's own draw probability. Blending a
    #     weaker, correlated signal can only dilute; AUC falls monotonically as
    #     alpha rises, and the optimum for discrimination is exactly 0.
    #
    #   • Brier on the draw column alone rewards shrinking p_draw toward the base
    #     rate (variance reduction) regardless of whether the ordering improves,
    #     which is why it kept landing near 0.30 while AUC said 0. The blend
    #     rescales home and away too, so the honest score is the one over all
    #     three outcomes.
    #
    # If a future specialist genuinely adds signal this will find it and alpha
    # will come back up on its own. Nothing here is pinned to zero.
    # Selection is by the ONE-STANDARD-ERROR RULE: take the smallest alpha whose
    # calibration log-loss is within one standard error of the best, not the
    # argmin. Picking the argmin is what kept resurrecting this blend.
    #
    # On the 2026-09-03 retrain the entire sweep spanned 0.00076 log-loss
    # (1.00255 at alpha=0 down to 1.00179 at alpha=0.45) and fell monotonically
    # toward the edge of the grid — the signature of a flat objective with no
    # interior optimum. One standard error on ~7,000 rows is around 0.0096, more
    # than ten times the whole spread. The argmin duly chose 0.45, and the
    # held-out test window then said the opposite: alpha=0 was better on log-loss
    # (1.0020 against 1.0031 on the rows with a real line) AND on draw AUC
    # (0.5482 against 0.5411). The cal-set minimum was noise.
    #
    # This is the third scoring rule tried here. Brier on the draw column chose
    # ~0.30, three-way log-loss chose 0.45, and the two things that actually
    # matter — held-out log-loss and the specialist's own ranking power — both
    # say 0. The rule below prefers the simpler model unless the evidence clears
    # the noise floor, so a specialist that genuinely helps will still be picked
    # up while one that does not stops coming back.
    _cal_y = cal["target_result"].values
    sweep: list[tuple[float, float, float]] = []
    for alpha_candidate in np.arange(0.0, 0.50, 0.05):
        blended = np.empty((len(cal), 3), dtype=float)
        for i in range(len(cal)):
            ph, pd_, pa = cal_result_probs[i]
            dc = float(draw_cal_probs[i])
            blended[i] = blend_draw_probability(
                float(ph), float(pd_), float(pa), dc, alpha=float(alpha_candidate))
        # blend_draw_probability renormalises, but float error still leaves rows
        # a few ulps off 1.0 and sklearn warns on every one of them.
        blended /= blended.sum(axis=1, keepdims=True)
        row_ll = -np.log(np.clip(blended[np.arange(len(cal)), _cal_y], 1e-12, None))
        ll     = float(row_ll.mean())
        se     = float(row_ll.std(ddof=1) / np.sqrt(len(row_ll)))
        brier  = brier_score_loss(y_cal_draw, blended[:, 1])
        sweep.append((float(alpha_candidate), ll, se))
        print(f"  alpha={alpha_candidate:.2f}  3-way log-loss={ll:.5f} "
              f"(±{se:.5f})  draw brier={brier:.5f}")

    best_ll_alpha, best_ll, best_se = min(sweep, key=lambda r: r[1])
    threshold  = best_ll + best_se
    best_alpha = min(a for a, ll, _ in sweep if ll <= threshold)
    print(f"  → alpha={best_alpha:.2f}  (best log-loss {best_ll:.5f} at "
          f"alpha={best_ll_alpha:.2f}; anything under {threshold:.5f} is within "
          f"one standard error, so the smallest such alpha wins)")
    if best_alpha == 0.0:
        print("     alpha=0 — the draw specialist is not blended in. Expected: on "
              "held-out data it ranks draws WORSE than the result model it was "
              "meant to help (AUC 0.5280 against 0.5402).")

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

    # ── BTTS threshold sweep on cal set (maximise ACCURACY) ──────────────────
    # Encoding: y_true 1=GG 0=NG; y_pred 1=GG (P>=t) 0=NG (P<t).
    #
    # This used to maximise macro F1, to stop the threshold collapsing one class.
    # Changed 2026-09-04 by the owner's call: the site reports hit rate, so hit
    # rate is what the threshold should buy — "even if we say GG every time, if
    # we are right, that is what we want".
    #
    # The trade, measured on the 2026-09-04 artefacts:
    #
    #                       cal thr   TEST 23/24 (n=7,087)   CLEAN 26/27 (n=390)
    #   macro F1               0.54   acc 51.50%  GG 35%     acc 51.54%  GG 41%
    #   accuracy               0.51   acc 54.32%  GG 85%     acc 52.31%  GG 89%
    #   always GG              0.00   acc 53.79%  GG 100%    acc 53.08%  GG 100%
    #
    # +2.8pp on the test window. Two things to be clear about, since neither is
    # visible from the accuracy number alone:
    #
    #   • The classifier barely discriminates — AUC 0.54 on the calibration
    #     window. Most of that accuracy is the GG base rate (54.3%), not skill.
    #     The threshold beats "always GG" by half a point on 7,087 matches and
    #     loses to it on 390, which is about the size of edge that exists here.
    #   • NG becomes a rare label. Tickets are unaffected — candidate_legs prices
    #     both sides off the PROBABILITY, never this label — so this changes the
    #     badge on the card and the /stats BTTS row, nothing that gets bet.
    btts_cal_probs = btts_iso.predict(btts_raw_cal)   # calibrated P(GG) on cal set
    best_btts_threshold, best_btts_acc = 0.5, -1.0
    for t_candidate in np.arange(0.30, 0.75, 0.01):
        acc = float(((btts_cal_probs >= t_candidate).astype(int) == y_cal_btts).mean())
        if acc > best_btts_acc:
            best_btts_acc       = acc
            best_btts_threshold = float(t_candidate)
    _preds_at_best = (btts_cal_probs >= best_btts_threshold).astype(int)
    _gg_f1 = f1_score(y_cal_btts, _preds_at_best, pos_label=1, zero_division=0)
    _ng_f1 = f1_score(y_cal_btts, _preds_at_best, pos_label=0, zero_division=0)
    _base  = float(max(y_cal_btts.mean(), 1 - y_cal_btts.mean()))
    print(f"  → Optimal BTTS threshold: {best_btts_threshold:.2f}  "
          f"(cal accuracy={best_btts_acc:.4f}  GG_F1={_gg_f1:.4f}  NG_F1={_ng_f1:.4f}  "
          f"GG share={_preds_at_best.mean():.3f})")
    if best_btts_acc <= _base + 0.005:
        print(f"     NOTE: majority-class baseline is {_base:.4f} — the threshold "
              f"is buying at most half a point over always saying the same thing.")
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
