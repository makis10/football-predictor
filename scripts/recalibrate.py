"""
Rolling (second-stage) recalibration from stored predictions.

The base isotonic calibrators are fitted once per training run on a fixed
historical season. The live probability distribution drifts away from that
season over time. This script refits a light second-stage isotonic correction
from the predictions table itself: every stored prediction was made BEFORE its
match (frozen at compute time), so (stored final probability, actual outcome)
pairs from the last N days are genuinely out-of-sample.

Fits four regressors — P(H), P(D), P(A), P(Over 2.5) — and saves them as
calibrator_recent.pkl. Inference applies them after the draw blend (see
calibration.apply_recent_calibration); when the file is absent everything is a
no-op, so this is safe to skip.

Guard: requires at least --min-n completed predictions (default 300) — isotonic
on fewer points memorises noise and would do more harm than good.

Usage:
  docker compose exec backend python scripts/recalibrate.py
  docker compose exec backend python scripts/recalibrate.py --days 365 --min-n 300
Scheduled monthly (1st of the month) from run_daily.sh.
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from sklearn.isotonic import IsotonicRegression

from backend.app.database import SessionLocal
from backend.app.ml.calibration import MODELS_DIR

OUT_PATH = os.path.join(MODELS_DIR, "calibrator_recent.pkl")


def main() -> None:
    ap = argparse.ArgumentParser(description="Second-stage rolling recalibration")
    ap.add_argument("--days", type=int, default=365,
                    help="Lookback window of completed predictions (default 365)")
    ap.add_argument("--min-n", type=int, default=300,
                    help="Minimum completed predictions required (default 300)")
    args = ap.parse_args()

    from sqlalchemy import text
    cutoff = (date.today() - timedelta(days=args.days)).isoformat()

    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT p.home_win_prob, p.draw_prob, p.away_win_prob, p.over_2_5_prob,
                   m.result, m.home_goals, m.away_goals
            FROM predictions p
            JOIN matches m ON m.id = p.match_id
            WHERE m.result IS NOT NULL AND m.match_date >= :cutoff
        """), {"cutoff": cutoff}).fetchall()
    finally:
        db.close()

    n = len(rows)
    print(f"{n} completed predictions in the last {args.days} days.")
    if n < args.min_n:
        print(f"[skip] Below --min-n {args.min_n} — isotonic would overfit. "
              f"No calibrator written; inference stays on base calibration.")
        # Remove a stale file so we don't keep applying an outdated correction
        if os.path.exists(OUT_PATH):
            os.remove(OUT_PATH)
            print(f"[skip] Removed stale {OUT_PATH}.")
        return

    hw  = np.array([r[0] for r in rows], dtype=float)
    d   = np.array([r[1] for r in rows], dtype=float)
    aw  = np.array([r[2] for r in rows], dtype=float)
    ov  = np.array([r[3] for r in rows], dtype=float)
    res = [r[4] for r in rows]
    y_h = np.array([1.0 if x == "H" else 0.0 for x in res])
    y_d = np.array([1.0 if x == "D" else 0.0 for x in res])
    y_a = np.array([1.0 if x == "A" else 0.0 for x in res])
    y_o = np.array([1.0 if ((r[5] or 0) + (r[6] or 0)) > 2.5 else 0.0 for r in rows])

    def _fit(x: np.ndarray, y: np.ndarray, label: str) -> IsotonicRegression:
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(x, y)
        print(f"  {label:<5} mean prob {x.mean():.3f} → recal {iso.predict(x).mean():.3f}"
              f"   (actual rate {y.mean():.3f})")
        return iso

    print("Fitting second-stage isotonic …")
    cals = {
        "home": _fit(hw, y_h, "home"),
        "draw": _fit(d,  y_d, "draw"),
        "away": _fit(aw, y_a, "away"),
        "over": _fit(ov, y_o, "over"),
        "fitted_at": datetime.now(timezone.utc).isoformat(),
        "n": n,
        "window_days": args.days,
    }

    os.makedirs(MODELS_DIR, exist_ok=True)
    with open(OUT_PATH, "wb") as f:
        pickle.dump(cals, f)
    print(f"✓ Saved → {OUT_PATH}")


if __name__ == "__main__":
    main()
