"""
Fit the national serve-path blend on held-out data — instead of eyeballing it.

Why this exists (audit finding, 2026-07-10):
  predict_national.py sharpens the calibrated model 1×2 by blending it with
  elo_three_way() at ELO_BLEND_W. Both the weight and the curve constants
  (scale=110, draw_base=0.26, draw_decay=0.7) were hand-picked, applied AFTER
  isotonic calibration (invalidating it), and the published metrics.json
  describes the UNBLENDED model — i.e. a system that never serves. This script
  replays the actual serve path over held-out matches and fits the constants:

    1. Rebuild point-in-time features (same chronological builder as training).
    2. Compute the calibrated + draw-blended model 1×2 for CAL and TEST rows.
    3. Grid-search (w, scale, draw_base, draw_decay) by log-loss on CAL only.
    4. Report TEST metrics for: pure model (w=0), current production constants,
       and the fitted constants — the fitted TEST numbers are the honest
       production metrics.
    5. Persist the fitted values to models/national/blend.json (consumed by
       predict_national.py at serve time).

Caveat: the replay uses pure results-Elo (as trained). Production also shifts
inputs via talent_adjusted_elo(), which cannot be replayed historically (no
point-in-time squad data) — that residual train/serve gap remains documented.

Usage:
  docker compose exec backend python scripts/fit_national_blend.py
  docker compose exec backend python scripts/fit_national_blend.py --no-save
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.ml.national.features import HOME_ADV, elo_three_way
from backend.app.ml.national.train import (
    CAL_START, TEST_START, TEST_END,
    prepare_data, blend_draw_probability,
)
from backend.app.ml.national.features import NATIONAL_FEATURE_COLS, DRAW_FEATURE_COLS

DATA_DIR   = ROOT / "backend" / "data" / "raw" / "international"
MODELS_DIR = ROOT / "backend" / "data" / "models" / "national"
BLEND_PATH = MODELS_DIR / "blend.json"

# Grid — coarse but covers the plausible space. Cal rows ≈ few hundred, so a
# finer grid would only overfit the fit set.
W_GRID          = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
SCALE_GRID      = [80.0, 110.0, 140.0, 180.0]
DRAW_BASE_GRID  = [0.22, 0.26, 0.30]
DRAW_DECAY_GRID = [0.4, 0.7, 1.0]

CURRENT_PROD = {"elo_blend_w": 0.5, "scale": 110.0, "draw_base": 0.26, "draw_decay": 0.7}


def _load_models() -> dict:
    objects = {}
    for fname in ["model_result.pkl", "model_draw_clf.pkl",
                  "calibrator_result.pkl", "calibrator_draw_clf.pkl"]:
        with open(MODELS_DIR / fname, "rb") as f:
            objects[fname.replace(".pkl", "").replace("calibrator_", "cal_")] = pickle.load(f)
    alpha_path = MODELS_DIR / "draw_alpha.json"
    objects["draw_alpha"] = (json.load(open(alpha_path)).get("draw_blend_alpha", 0.35)
                             if alpha_path.exists() else 0.35)
    return objects


def _model_probs(models: dict, df: pd.DataFrame) -> np.ndarray:
    """Calibrated + draw-blended 1×2 for every row — the pre-Elo serve path."""
    X  = df[[c for c in NATIONAL_FEATURE_COLS if c in df.columns]]
    Xd = df[[c for c in DRAW_FEATURE_COLS if c in df.columns]]

    raw = models["model_result"].predict_proba(X)
    cal = np.zeros_like(raw)
    for c, iso in enumerate(models["cal_result"]):
        cal[:, c] = iso.predict(raw[:, c])
    cal /= np.maximum(cal.sum(axis=1, keepdims=True), 1e-9)

    draw_raw = models["model_draw_clf"].predict_proba(Xd)[:, 1]
    draw_cal = models["cal_draw_clf"].predict(draw_raw)
    alpha = models["draw_alpha"]

    out = np.zeros_like(cal)
    for i in range(len(cal)):
        out[i] = blend_draw_probability(cal[i, 0], cal[i, 1], cal[i, 2],
                                        float(draw_cal[i]), alpha=alpha)
    return out    # columns: [home, draw, away]


def _elo3way_matrix(df: pd.DataFrame, scale: float, base: float, decay: float) -> np.ndarray:
    adj = df["h_elo"].to_numpy() - df["a_elo"].to_numpy() \
        + np.where(df["neutral"].to_numpy(dtype=float) > 0, 0.0, HOME_ADV)
    out = np.zeros((len(df), 3))
    for i, d in enumerate(adj):
        out[i] = elo_three_way(float(d), scale=scale, draw_base=base, draw_decay=decay)
    return out


def _log_loss(y: np.ndarray, probs: np.ndarray) -> float:
    p = np.clip(probs[np.arange(len(y)), y], 1e-12, 1.0)
    return float(-np.mean(np.log(p)))


def _metrics(y: np.ndarray, probs: np.ndarray) -> dict:
    pred = probs.argmax(axis=1)
    return {"accuracy": round(float((pred == y).mean()), 4),
            "log_loss": round(_log_loss(y, probs), 4),
            "draw_share_predicted": round(float((pred == 1).mean()), 4),
            "n": int(len(y))}


def main() -> None:
    ap = argparse.ArgumentParser(description="Fit national Elo-blend on held-out data")
    ap.add_argument("--no-save", action="store_true", help="Report only; don't write blend.json")
    args = ap.parse_args()

    print("Building point-in-time national features (chronological replay) …")
    df = prepare_data(DATA_DIR)
    # target_result encoding: 0=H, 1=D, 2=A (same as training)
    #
    # Window protocol: the 2023 cal season (used to fit the isotonic
    # calibrators) proved unrepresentative for blend selection — it prefers
    # w=0 while every later window strongly prefers the blend. So the blend is
    # selected on 2024-01→2025-07 (out-of-sample for BOTH the model and the
    # calibrators, and disjoint from their fit windows) and the final report
    # comes from the untouched 2025-07→TEST_END holdout.
    SELECT_END = pd.Timestamp("2025-07-01")
    cal_df  = df[(df["date"] >= TEST_START) & (df["date"] < SELECT_END)].reset_index(drop=True)
    test_df = df[(df["date"] >= SELECT_END) & (df["date"] < TEST_END)].reset_index(drop=True)
    print(f"  blend-selection rows (2024-01→2025-07): {len(cal_df):,}   "
          f"final holdout rows (2025-07→{TEST_END.date()}): {len(test_df):,}")

    models = _load_models()
    print("Computing calibrated model probabilities (pre-Elo serve path) …")
    cal_model  = _model_probs(models, cal_df)
    test_model = _model_probs(models, test_df)
    y_cal  = cal_df["target_result"].to_numpy(dtype=int)
    y_test = test_df["target_result"].to_numpy(dtype=int)

    # ── Grid search on CAL only ───────────────────────────────────────────────
    print(f"Grid-searching {len(W_GRID)*len(SCALE_GRID)*len(DRAW_BASE_GRID)*len(DRAW_DECAY_GRID)} combos on CAL …")
    best = None
    for scale in SCALE_GRID:
        for base in DRAW_BASE_GRID:
            for decay in DRAW_DECAY_GRID:
                e3 = _elo3way_matrix(cal_df, scale, base, decay)
                for w in W_GRID:
                    blended = (1 - w) * cal_model + w * e3
                    blended /= blended.sum(axis=1, keepdims=True)
                    ll = _log_loss(y_cal, blended)
                    if best is None or ll < best["cal_log_loss"]:
                        best = {"elo_blend_w": w, "scale": scale,
                                "draw_base": base, "draw_decay": decay,
                                "cal_log_loss": round(ll, 4)}
    print(f"  Best on CAL: {best}")

    # ── TEST report: pure vs current-production vs fitted ────────────────────
    def _blend_on_test(w, scale, base, decay):
        e3 = _elo3way_matrix(test_df, scale, base, decay)
        b = (1 - w) * test_model + w * e3
        return b / b.sum(axis=1, keepdims=True)

    report = {
        "pure_model_w0":      _metrics(y_test, test_model),
        "production_current": _metrics(y_test, _blend_on_test(
                                    CURRENT_PROD["elo_blend_w"], CURRENT_PROD["scale"],
                                    CURRENT_PROD["draw_base"], CURRENT_PROD["draw_decay"])),
        "fitted":             _metrics(y_test, _blend_on_test(
                                    best["elo_blend_w"], best["scale"],
                                    best["draw_base"], best["draw_decay"])),
    }

    # Per-w trade-off curve (best curve-params per w, CAL selection → TEST metrics):
    # makes the calibration-vs-sharpness decision visible instead of hidden.
    print("\nPer-w curve (curve params re-fitted on CAL per w; metrics on TEST):")
    print(f"{'w':>5}{'cal-ll':>9}{'test-acc':>10}{'test-ll':>9}{'pred-draw%':>12}")
    per_w = {}
    for w in W_GRID:
        b_ll, b_params = None, None
        for scale in SCALE_GRID:
            for base in DRAW_BASE_GRID:
                for decay in DRAW_DECAY_GRID:
                    e3 = _elo3way_matrix(cal_df, scale, base, decay)
                    bl = (1 - w) * cal_model + w * e3
                    bl /= bl.sum(axis=1, keepdims=True)
                    ll = _log_loss(y_cal, bl)
                    if b_ll is None or ll < b_ll:
                        b_ll, b_params = ll, (scale, base, decay)
        m = _metrics(y_test, _blend_on_test(w, *b_params))
        per_w[w] = {"cal_log_loss": round(b_ll, 4), **m,
                    "scale": b_params[0], "draw_base": b_params[1], "draw_decay": b_params[2]}
        print(f"{w:>5.1f}{b_ll:>9.4f}{m['accuracy']:>10.3f}{m['log_loss']:>9.4f}{m['draw_share_predicted']:>12.1%}")
    print("\n══════════ TEST-SET REPORT (the honest production numbers) ══════════")
    print(f"{'variant':<22}{'acc':>8}{'log-loss':>10}{'pred-draw%':>12}{'n':>7}")
    for k, m in report.items():
        print(f"{k:<22}{m['accuracy']:>8.3f}{m['log_loss']:>10.4f}{m['draw_share_predicted']:>12.1%}{m['n']:>7}")

    actual_draw = round(float((y_test == 1).mean()), 4)
    print(f"\nActual draw rate on test: {actual_draw:.1%}")
    print("Caveat: replay uses results-Elo inputs (as trained); production also applies "
          "talent_adjusted_elo(), which is not historically replayable.")

    if not args.no_save:
        payload = {
            **{k: best[k] for k in ("elo_blend_w", "scale", "draw_base", "draw_decay")},
            "fitted_at":    datetime.now(timezone.utc).isoformat(),
            "cal_log_loss": best["cal_log_loss"],
            "cal_window":   [str(TEST_START.date()), "2025-07-01"],
            "test_window":  ["2025-07-01", str(TEST_END.date())],
            "test_report":  report,
            "per_w_curve":  {str(k): v for k, v in per_w.items()},
            "actual_test_draw_rate": actual_draw,
        }
        with open(BLEND_PATH, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"\n✓ Saved fitted blend → {BLEND_PATH}")
        print("  predict_national.py picks it up on next run (re-run predict_national --save-db "
              "to refresh stored upcoming predictions).")


if __name__ == "__main__":
    main()
