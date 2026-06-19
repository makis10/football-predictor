"""
Rebuild the national-team inference snapshot from the latest results.

The trained models (model_*.pkl) are feature-based and stay valid between
weekly retrains — but the Elo / form / H2H state they consume lives in
snapshot.pkl, which train.py only regenerates weekly. During a live tournament
that means a team's strength is frozen at last Monday's value: Mexico beating
South Africa wouldn't raise Mexico's Elo for their next prediction until the
weekly retrain.

This script rebuilds ONLY the snapshot (the chronological Elo/form walk over
all played matches — seconds, no model training) so daily predictions reflect
every result so far. It's the cheap, correct version of "retrain after each
match": the trees barely move from a handful of new games, but the team state
must stay current.

Usage:
  docker compose exec backend python scripts/refresh_national_snapshot.py
Runs daily from run_daily.sh, before predict_national.py.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR   = ROOT / "backend" / "data" / "raw" / "international"
SNAP_PATH  = ROOT / "backend" / "data" / "models" / "national" / "snapshot.pkl"


def main() -> None:
    from backend.app.ml.national.features import load_results, build_snapshot

    if not SNAP_PATH.exists():
        print(f"[skip] No trained snapshot at {SNAP_PATH} — run train_national.py first.")
        return

    historical, _ = load_results(DATA_DIR)
    snap = build_snapshot(historical)

    last = snap.get("last_date")
    n_teams = len(snap.get("elo", {}))
    with open(SNAP_PATH, "wb") as f:
        pickle.dump(snap, f)
    print(f"✓ Snapshot refreshed: {n_teams} teams, latest result {last} → {SNAP_PATH}")


if __name__ == "__main__":
    main()
