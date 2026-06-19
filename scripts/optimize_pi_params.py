"""
Optimize Pi-Rating constants using scipy differential evolution.

Evaluates PI_C, PI_K, PI_BASE, PI_DECAY by replaying match history and
computing log-loss of Poisson-derived outcome probabilities on the 2024/25
held-out season.  Runs entirely inside Docker (no XGBoost involved).

Usage:
  docker compose exec backend python scripts/optimize_pi_params.py

Runtime: ~5-15 minutes (100 evaluations × ~1s each).

Current defaults (Constantinou & Fenton 2012):
  PI_C=0.10, PI_K=3.0, PI_BASE=1.5, PI_DECAY=0.85
"""
from __future__ import annotations

import sys
import time
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))  # project root

import numpy as np
import pandas as pd
from collections import defaultdict
from sklearn.metrics import log_loss
from scipy.optimize import differential_evolution

from backend.app.ml.features import load_raw_csvs
from backend.app.ml.poisson import season_from_date, compute_poisson_probs

RAW_DIR = "/app/backend/data/raw"

# Evaluate on 2024/25 season (same as calibration set in train.py)
EVAL_START = pd.Timestamp("2024-07-01")
EVAL_END   = pd.Timestamp("2025-07-01")

print("Loading history …", flush=True)
_df = load_raw_csvs(RAW_DIR)
_df = _df.sort_values("Date").reset_index(drop=True)
print(f"  {len(_df):,} rows loaded", flush=True)


def _evaluate(PI_C: float, PI_K: float, PI_BASE: float, PI_DECAY: float) -> float:
    """
    Replay Pi-Rating updates through all history.
    For matches in the eval window, compute Poisson outcome probs and log-loss.
    """
    pi_home_att: dict[str, float] = defaultdict(float)
    pi_home_def: dict[str, float] = defaultdict(float)
    pi_away_att: dict[str, float] = defaultdict(float)
    pi_away_def: dict[str, float] = defaultdict(float)

    prev_season = None
    preds: list[list[float]] = []
    actuals: list[int] = []

    for _, row in _df.iterrows():
        h, a = row["home_team"], row["away_team"]
        hg, ag = int(row["home_goals"]), int(row["away_goals"])
        season = season_from_date(row["Date"])

        # Pi-Rating decay at season boundary
        if prev_season is not None and season != prev_season:
            for team in list(pi_home_att.keys()):
                pi_home_att[team] *= PI_DECAY
                pi_home_def[team] *= PI_DECAY
                pi_away_att[team] *= PI_DECAY
                pi_away_def[team] *= PI_DECAY
        prev_season = season

        # Expected goals from current Pi-Ratings (before update)
        h_att = pi_home_att[h]; h_def = pi_home_def[h]
        a_att = pi_away_att[a]; a_def = pi_away_def[a]
        pi_exp_h = PI_BASE * (10.0 ** ((h_att - a_def) / PI_K))
        pi_exp_a = PI_BASE * (10.0 ** ((a_att - h_def) / PI_K))

        # Evaluate on held-out season
        if EVAL_START <= row["Date"] < EVAL_END:
            probs = compute_poisson_probs(
                float(np.clip(pi_exp_h, 0.1, 6.0)),
                float(np.clip(pi_exp_a, 0.1, 6.0)),
            )
            preds.append([probs["home_win"], probs["draw"], probs["away_win"]])
            if hg > ag:
                actuals.append(0)
            elif hg == ag:
                actuals.append(1)
            else:
                actuals.append(2)

        # Update Pi-Ratings (after snapshot)
        err_h = hg - pi_exp_h
        err_a = ag - pi_exp_a
        pi_home_att[h] += PI_C * err_h; pi_away_def[a] -= PI_C * err_h
        pi_away_att[a] += PI_C * err_a; pi_home_def[h] -= PI_C * err_a

    if not preds:
        return 9999.0
    return float(log_loss(actuals, preds))


# Wrap for scipy: params is [PI_C, PI_K, PI_BASE, PI_DECAY]
_call_count = [0]
_t0 = time.time()

def _objective(params: np.ndarray) -> float:
    PI_C, PI_K, PI_BASE, PI_DECAY = params
    result = _evaluate(PI_C, PI_K, PI_BASE, PI_DECAY)
    _call_count[0] += 1
    if _call_count[0] % 10 == 0:
        elapsed = time.time() - _t0
        print(
            f"  trial {_call_count[0]:4d} | "
            f"PI_C={PI_C:.4f} PI_K={PI_K:.3f} PI_BASE={PI_BASE:.3f} PI_DECAY={PI_DECAY:.3f} "
            f"→ log-loss={result:.5f}  ({elapsed:.0f}s elapsed)",
            flush=True,
        )
    return result


# Current defaults as reference
_baseline = _evaluate(0.10, 3.0, 1.5, 0.85)
print(f"\nBaseline (current defaults) log-loss: {_baseline:.5f}\n", flush=True)

# Parameter search bounds
BOUNDS = [
    (0.03, 0.30),   # PI_C
    (1.0,  7.0),    # PI_K
    (1.0,  2.5),    # PI_BASE
    (0.70, 1.00),   # PI_DECAY
]

print("Running differential evolution (maxiter=20, popsize=8 = 160 evaluations) …", flush=True)
result = differential_evolution(
    _objective,
    bounds=BOUNDS,
    maxiter=20,
    popsize=8,
    seed=42,
    tol=1e-4,
    mutation=(0.5, 1.0),
    recombination=0.7,
    workers=1,
    updating="immediate",
    polish=True,
)

PI_C_opt, PI_K_opt, PI_BASE_opt, PI_DECAY_opt = result.x

print(f"\n{'='*60}")
print(f"Optimization complete in {time.time() - _t0:.0f}s")
print(f"{'='*60}")
print(f"Baseline log-loss : {_baseline:.5f}")
print(f"Optimized log-loss: {result.fun:.5f}  (Δ={_baseline - result.fun:+.5f})")
print(f"\nOptimal parameters:")
print(f"  PI_C     = {PI_C_opt:.4f}  (current: 0.10)")
print(f"  PI_K     = {PI_K_opt:.4f}  (current: 3.0)")
print(f"  PI_BASE  = {PI_BASE_opt:.4f}  (current: 1.5)")
print(f"  PI_DECAY = {PI_DECAY_opt:.4f}  (current: 0.85)")
print(f"\nTo apply, edit backend/app/ml/features.py:")
print(f"  PI_C     = {PI_C_opt:.4f}")
print(f"  PI_K     = {PI_K_opt:.4f}")
print(f"  PI_BASE  = {PI_BASE_opt:.4f}")
print(f"  PI_DECAY = {PI_DECAY_opt:.4f}")
print(f"\nThen retrain: python backend/app/ml/train.py")
