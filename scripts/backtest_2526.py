"""
2025-26 out-of-sample backtest using production models.

Walk-forward feature engineering on the FULL dataset ensures every 2025-26 row
gets causally correct rolling stats (Elo, Pi-ratings, form windows updated
match-by-match through the season — same as production).

Production models are loaded from disk rather than retrained here, so this
directly measures the live system's performance on unseen data.

Usage:
  docker compose exec backend python scripts/backtest_2526.py
  docker compose exec backend python scripts/backtest_2526.py --output /tmp/bt.csv
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, brier_score_loss

from backend.app.ml.features import (
    load_raw_csvs, load_xg_data, merge_xg, build_features,
    RESULT_FEATURE_COLS, GOALS_FEATURE_COLS, BTTS_FEATURE_COLS,
)
from backend.app.ml.european import load_european_data, EUROPEAN_DIR
from backend.app.ml.calibration import apply_calibration, load_calibrators
from backend.app.ml.draw_classifier import blend_draw_probability
from backend.app.ml.predict import _get_draw_alpha, _get_btts_threshold, SoftVoteEnsemble

RAW_DIR    = "/app/backend/data/raw"
XG_DIR     = "/app/backend/data/xg"
MODELS_DIR = "/app/backend/data/models"
CUTOFF     = pd.Timestamp("2025-07-01")   # 2025-26 season starts here

parser = argparse.ArgumentParser()
parser.add_argument("--output", default=None, help="Save per-match rows to CSV")
args = parser.parse_args()


# ── 1. Load raw data ──────────────────────────────────────────────────────────
print("Loading raw data …")
df_all = load_raw_csvs(RAW_DIR)
print(f"  {len(df_all):,} rows  |  {df_all['Date'].min().date()} → {df_all['Date'].max().date()}")

xg_df = load_xg_data(XG_DIR)
if xg_df is not None:
    df_all = merge_xg(df_all, xg_df)
    print(f"  xG: {xg_df.shape[0]:,} records, {df_all['home_xg'].notna().sum():,} matched")

eur_df = load_european_data(EUROPEAN_DIR)

n_eval_raw = (df_all["Date"] >= CUTOFF).sum()
print(f"  Train (< 2025-07-01): {(df_all['Date'] < CUTOFF).sum():,} rows")
print(f"  Eval  (2025-26 YTD) : {n_eval_raw:,} rows")


# ── 2. Walk-forward feature engineering on ALL data ───────────────────────────
print("\nBuilding walk-forward features (full dataset) …")
df_feat = build_features(df_all, european_df=eur_df)

# Exclude COVID season
covid_mask = (df_feat["Date"] >= "2020-07-01") & (df_feat["Date"] < "2021-07-01")
df_feat = df_feat[~covid_mask].copy()

# Encode targets
df_feat["target_result"] = df_feat.apply(
    lambda r: 0 if r["home_goals"] > r["away_goals"]
              else (1 if r["home_goals"] == r["away_goals"] else 2),
    axis=1,
)
df_feat["target_goals"] = (df_feat["home_goals"] + df_feat["away_goals"] > 2.5).astype(int)
df_feat["target_btts"]  = ((df_feat["home_goals"] > 0) & (df_feat["away_goals"] > 0)).astype(int)

df_eval = df_feat[df_feat["Date"] >= CUTOFF].dropna(subset=["home_goals", "away_goals"]).copy()
print(f"  Eval rows with known result: {len(df_eval):,}")

if len(df_eval) == 0:
    print("[ERROR] No 2025-26 completed matches found.")
    sys.exit(1)


# ── 3. Load production models ─────────────────────────────────────────────────
print("\nLoading production models …")

def _load(name: str):
    with open(os.path.join(MODELS_DIR, name), "rb") as f:
        return pickle.load(f)

result_model = _load("model_result.pkl")
goals_model  = _load("model_goals.pkl")
draw_clf     = _load("model_draw_clf.pkl")
btts_clf     = _load("model_btts_clf.pkl")

result_cals, goals_cal, league_goals_cals = load_calibrators(MODELS_DIR)
draw_cal     = _load("calibrator_draw_clf.pkl")
btts_cal     = _load("calibrator_btts_clf.pkl")
draw_alpha   = _get_draw_alpha()
btts_thresh  = _get_btts_threshold()

print(f"  Models loaded. draw_alpha={draw_alpha:.2f}  btts_threshold={btts_thresh:.2f}")


# ── 4. Predict every eval row ─────────────────────────────────────────────────
print(f"\nPredicting {len(df_eval):,} completed 2025-26 matches …")

res_cols  = [c for c in RESULT_FEATURE_COLS if c in df_eval.columns]
gls_cols  = [c for c in GOALS_FEATURE_COLS  if c in df_eval.columns]
btts_cols = [c for c in BTTS_FEATURE_COLS   if c in df_eval.columns]
draw_cols = res_cols   # draw clf trained on result feature subset

records = []
errors  = 0

for _, row in df_eval.sort_values("Date").iterrows():
    try:
        X_res  = row[res_cols].to_frame().T.astype(float)
        X_gls  = row[gls_cols].to_frame().T.astype(float)
        X_btts = row[btts_cols].to_frame().T.astype(float)

        # Result model
        res_probs  = result_model.predict_proba(X_res)[0]
        raw_over   = float(goals_model.predict_proba(X_gls)[0][1])
        raw_btts   = float(btts_clf.predict_proba(X_btts)[0][1])

        # Calibrate
        hw, d, aw, over_p = apply_calibration(
            res_probs, raw_over,
            result_cals, goals_cal,
            league=row.get("League"), league_goals_cals=league_goals_cals,
        )

        # Draw-specialist blend
        try:
            draw_raw = float(draw_clf.predict_proba(X_res)[0][1])
            draw_p   = float(draw_cal.predict([draw_raw])[0])
            hw, d, aw = blend_draw_probability(hw, d, aw, draw_p, alpha=draw_alpha)
        except Exception:
            pass  # draw blend is best-effort

        # BTTS calibrate
        btts_p = float(btts_cal.predict([raw_btts])[0])

        actual      = row.get("result", "")
        total_goals = int(row["home_goals"] + row["away_goals"])
        actual_over = int(total_goals > 2.5)
        actual_btts = int(row["home_goals"] > 0 and row["away_goals"] > 0)

        pred_out  = "H" if hw >= d and hw >= aw else ("D" if d >= aw else "A")
        pred_over = "OVER" if over_p >= 0.5 else "UNDER"
        pred_btts = "GG" if btts_p >= btts_thresh else "NG"

        records.append({
            "date":       row["Date"].date(),
            "league":     row.get("League", ""),
            "home":       row.get("home_team", ""),
            "away":       row.get("away_team", ""),
            "home_goals": int(row["home_goals"]),
            "away_goals": int(row["away_goals"]),
            "total_goals": total_goals,
            "actual":     actual,
            "pred":       pred_out,
            "correct":    int(pred_out == actual),
            "actual_over": actual_over,
            "pred_over":   pred_over,
            "correct_ou":  int(pred_over == ("OVER" if actual_over else "UNDER")),
            "actual_btts": actual_btts,
            "pred_btts":   pred_btts,
            "correct_btts": int((pred_btts == "GG") == bool(actual_btts)),
            "p_home":  round(hw,      4),
            "p_draw":  round(d,       4),
            "p_away":  round(aw,      4),
            "p_over":  round(over_p,  4),
            "p_btts":  round(btts_p,  4),
        })
    except Exception as e:
        errors += 1
        if errors <= 3:
            print(f"  [error] {row.get('home_team','?')} vs {row.get('away_team','?')}: {e}")

results_df = pd.DataFrame(records)
print(f"  Predicted: {len(results_df):,}  errors: {errors}")

if args.output:
    results_df.to_csv(args.output, index=False)
    print(f"  Saved → {args.output}")

if results_df.empty:
    print("[ERROR] No predictions produced.")
    sys.exit(1)


# ── 5. Report ─────────────────────────────────────────────────────────────────
def pct(n, d):
    return f"{n/d*100:.1f}%" if d else "N/A"

W = 66
print("\n" + "═"*W)
print("  2025-26 OUT-OF-SAMPLE BACKTEST  (production models)")
print("═"*W)

n            = len(results_df)
n_correct    = results_df["correct"].sum()
n_correct_ou = results_df["correct_ou"].sum()
n_correct_bt = results_df["correct_btts"].sum()

# Log-loss & Brier
try:
    label_map  = {"H": 0, "D": 1, "A": 2}
    y_true_int = results_df["actual"].map(label_map).values
    ll         = log_loss(y_true_int, results_df[["p_home","p_draw","p_away"]].values, labels=[0,1,2])
except Exception:
    ll = None

y_oh    = pd.get_dummies(results_df["actual"]).reindex(columns=["H","D","A"], fill_value=0)
brier_r = np.mean([
    brier_score_loss(y_oh["H"], results_df["p_home"]),
    brier_score_loss(y_oh["D"], results_df["p_draw"]),
    brier_score_loss(y_oh["A"], results_df["p_away"]),
])
brier_g = brier_score_loss(results_df["actual_over"], results_df["p_over"])
brier_b = brier_score_loss(results_df["actual_btts"], results_df["p_btts"])

print(f"\n{'OVERALL':─<{W}}")
print(f"  Matches evaluated   : {n:,}")
print(f"  Result accuracy     : {n_correct}/{n}  ({pct(n_correct, n)})")
print(f"  O/U 2.5 accuracy    : {n_correct_ou}/{n}  ({pct(n_correct_ou, n)})")
print(f"  BTTS accuracy       : {n_correct_bt}/{n}  ({pct(n_correct_bt, n)})")
if ll:
    print(f"  Log-loss (result)   : {ll:.4f}  (random baseline ≈ {np.log(3):.4f})")
print(f"  Brier (result)      : {brier_r:.4f}")
print(f"  Brier (O/U 2.5)     : {brier_g:.4f}")
print(f"  Brier (BTTS)        : {brier_b:.4f}")

# By league
print(f"\n{'BY LEAGUE':─<{W}}")
print(f"  {'League':<14} {'N':>5}  {'Result%':>8}  {'O/U%':>6}  {'BTTS%':>6}  {'AvgConf':>8}")
print(f"  {'─'*14} {'─'*5}  {'─'*8}  {'─'*6}  {'─'*6}  {'─'*8}")
for lg, g in sorted(results_df.groupby("league"), key=lambda x: -len(x[1])):
    conf = g[["p_home","p_draw","p_away"]].max(axis=1).mean()
    print(f"  {lg:<14} {len(g):>5}  {pct(g['correct'].sum(),len(g)):>8}  "
          f"{pct(g['correct_ou'].sum(),len(g)):>6}  "
          f"{pct(g['correct_btts'].sum(),len(g)):>6}  {conf:>8.3f}")

# By predicted outcome
print(f"\n{'BY PREDICTED OUTCOME':─<{W}}")
print(f"  {'Predicted':<10} {'N':>5}  {'Correct':>8}  {'Accuracy':>9}  {'BaseRate':>9}")
print(f"  {'─'*10} {'─'*5}  {'─'*8}  {'─'*9}  {'─'*9}")
for code, label in [("H","HomeWin"),("D","Draw"),("A","AwayWin")]:
    g      = results_df[results_df["pred"] == code]
    actual = results_df[results_df["actual"] == code]
    print(f"  {label:<10} {len(g):>5}  {g['correct'].sum():>8}  "
          f"{pct(g['correct'].sum(),len(g)):>9}  {pct(len(actual),n):>9}")

# Confusion matrix
print(f"\n{'CONFUSION MATRIX':─<{W}}")
conf = pd.crosstab(results_df["pred"], results_df["actual"],
                   rownames=["Predicted"], colnames=["Actual"])
conf = conf.reindex(index=["H","D","A"], columns=["H","D","A"], fill_value=0)
print(f"  {'':14} {'Actual H':>9} {'Actual D':>9} {'Actual A':>9}")
for r, label in [("H","  Pred Home"),("D","  Pred Draw"),("A","  Pred Away")]:
    vals = "".join(f"{conf.loc[r,c]:>9}" for c in ["H","D","A"])
    print(f"  {label}{vals}")

# Draw analysis
print(f"\n{'DRAW ANALYSIS':─<{W}}")
n_act_d  = (results_df["actual"] == "D").sum()
n_pred_d = (results_df["pred"] == "D").sum()
tp_d     = ((results_df["actual"] == "D") & (results_df["pred"] == "D")).sum()
prec_d   = tp_d / n_pred_d if n_pred_d else 0
rec_d    = tp_d / n_act_d  if n_act_d  else 0
f1_d     = 2*prec_d*rec_d/(prec_d+rec_d) if (prec_d+rec_d) else 0
print(f"  Actual draws     : {n_act_d} ({n_act_d/n:.1%})")
print(f"  Predicted draws  : {n_pred_d}")
print(f"  Precision        : {prec_d:.3f}   Recall: {rec_d:.3f}   F1: {f1_d:.3f}")
print(f"  Mean p_draw      : {results_df['p_draw'].mean():.3f}")

# Confidence bands
print(f"\n{'ACCURACY BY CONFIDENCE BAND (max predicted prob)':─<{W}}")
results_df["max_prob"] = results_df[["p_home","p_draw","p_away"]].max(axis=1)
print(f"  {'Band':<12} {'N':>5}  {'Accuracy':>9}  {'ExpAcc':>8}  {'Edge':>7}")
print(f"  {'─'*12} {'─'*5}  {'─'*9}  {'─'*8}  {'─'*7}")
for lo, hi in [(0.33,0.45),(0.45,0.55),(0.55,0.65),(0.65,0.75),(0.75,1.01)]:
    g = results_df[(results_df["max_prob"] >= lo) & (results_df["max_prob"] < hi)]
    if len(g):
        label = f"{lo:.0%}–{hi:.0%}" if hi < 1 else f"{lo:.0%}+"
        acc   = g["correct"].mean()
        exp   = g["max_prob"].mean()
        print(f"  {label:<12} {len(g):>5}  {acc:>9.1%}  {exp:>8.1%}  {acc-exp:>+7.1%}")

# O/U calibration
print(f"\n{'OVER/UNDER 2.5 CALIBRATION':─<{W}}")
print(f"  Avg goals/match  : {results_df['total_goals'].mean():.2f}")
print(f"  Actual over 2.5  : {results_df['actual_over'].mean():.1%}")
print(f"  Predicted over   : {(results_df['p_over'] >= 0.5).mean():.1%}")
print()
print(f"  {'p_over band':<13} {'N':>5}  {'Act.Over%':>10}  {'Accuracy':>9}")
print(f"  {'─'*13} {'─'*5}  {'─'*10}  {'─'*9}")
for lo, hi in [(0.0,0.4),(0.4,0.5),(0.5,0.6),(0.6,0.7),(0.7,1.01)]:
    g = results_df[(results_df["p_over"] >= lo) & (results_df["p_over"] < hi)]
    if len(g):
        label = f"{lo:.0%}–{hi:.0%}" if hi < 1 else f"{lo:.0%}+"
        print(f"  {label:<13} {len(g):>5}  {g['actual_over'].mean():>10.1%}  "
              f"{pct(g['correct_ou'].sum(),len(g)):>9}")

# Goals by league
print(f"\n{'O/U & BTTS BY LEAGUE':─<{W}}")
print(f"  {'League':<14} {'AvgGls':>7} {'Over%':>7} {'OUAcc':>7} {'BTTSAcc':>8}")
print(f"  {'─'*14} {'─'*7} {'─'*7} {'─'*7} {'─'*8}")
for lg, g in sorted(results_df.groupby("league"), key=lambda x: -len(x[1])):
    print(f"  {lg:<14} {g['total_goals'].mean():>7.2f} "
          f"{g['actual_over'].mean():>7.1%} "
          f"{pct(g['correct_ou'].sum(),len(g)):>7} "
          f"{pct(g['correct_btts'].sum(),len(g)):>8}")

# Top 15 highest-confidence misses
print(f"\n{'TOP 15 HIGHEST-CONFIDENCE WRONG PREDICTIONS':─<{W}}")
misses = results_df[results_df["correct"] == 0].copy()
misses["p_actual"] = misses.apply(
    lambda r: r["p_home"] if r["actual"]=="H" else (r["p_draw"] if r["actual"]=="D" else r["p_away"]),
    axis=1,
)
for _, m in misses.nsmallest(15, "p_actual").iterrows():
    score = f"{m['home_goals']}-{m['away_goals']}"
    print(f"  {str(m['date']):<12} {m['league']:<12} "
          f"{m['home'][:13]:<14} vs {m['away'][:13]:<14} "
          f"{score:<5} pred={m['pred']}({m['max_prob']:.0%})  "
          f"p({m['actual']})={m['p_actual']:.0%}")

print("\n" + "═"*W)
