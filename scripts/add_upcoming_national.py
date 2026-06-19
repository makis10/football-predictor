"""
Manually add upcoming national-team fixtures (friendlies or any tournament)
to the international results dataset, so they get predicted.

The martj42 dataset only pre-populates official tournament fixtures
(e.g. World Cup). Friendlies appear only AFTER they are played (with a
score). This script lets you inject upcoming friendlies (score = NA) by
hand, validating team names against the trained Elo snapshot so the model
can actually rate them.

Workflow
--------
1. Edit the fixtures file (default: scripts/upcoming_friendlies.csv) with
   columns:  date,home_team,away_team,tournament,city,country,neutral
   (no score columns — they're left blank / NA automatically)

2. Validate names without writing:
     docker compose run --rm backend python scripts/add_upcoming_national.py --check

3. Append to results.csv:
     docker compose run --rm backend python scripts/add_upcoming_national.py

4. Generate predictions:
     docker compose run --rm backend python scripts/predict_national.py \
         --tournament Friendly --save-db

Notes
-----
- Idempotent: rows already present (same date+home+away) are skipped.
- Unknown team names abort the write (use --force to override) because a
  name the snapshot doesn't know gets ELO_START (1500) and a useless
  prediction. Fix the name to match the dataset's spelling instead.
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT       = Path(__file__).resolve().parent.parent
DATA_DIR   = ROOT / "backend" / "data" / "raw" / "international"
MODELS_DIR = ROOT / "backend" / "data" / "models" / "national"
RESULTS    = DATA_DIR / "results.csv"
DEFAULT_FIXTURES = ROOT / "scripts" / "upcoming_friendlies.csv"

REQUIRED_COLS = ["date", "home_team", "away_team", "tournament", "city", "country", "neutral"]
RESULTS_COLS  = ["date", "home_team", "away_team", "home_score", "away_score",
                 "tournament", "city", "country", "neutral"]


def _known_teams() -> set[str]:
    snap_path = MODELS_DIR / "snapshot.pkl"
    if not snap_path.exists():
        print(f"[warn] No snapshot at {snap_path} — skipping name validation.")
        return set()
    with open(snap_path, "rb") as f:
        snap = pickle.load(f)
    return set(snap.get("elo", {}).keys())


def _load_fixtures(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"[error] Fixtures file not found: {path}")
        print("Create it with columns: " + ",".join(REQUIRED_COLS))
        sys.exit(1)
    fx = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLS if c not in fx.columns]
    if missing:
        print(f"[error] Fixtures file missing columns: {missing}")
        sys.exit(1)
    # Normalise
    fx["date"]    = pd.to_datetime(fx["date"]).dt.strftime("%Y-%m-%d")
    fx["neutral"] = fx["neutral"].astype(str).str.lower().isin(["true", "1", "yes"])
    for c in ["city", "country"]:
        fx[c] = fx[c].fillna("")
    return fx


def main() -> None:
    ap = argparse.ArgumentParser(description="Add upcoming national-team fixtures")
    ap.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES,
                    help=f"CSV of fixtures to add (default: {DEFAULT_FIXTURES})")
    ap.add_argument("--check", action="store_true",
                    help="Validate names + show what would be added, but don't write")
    ap.add_argument("--force", action="store_true",
                    help="Write even if some team names are unknown to the snapshot")
    args = ap.parse_args()

    fx    = _load_fixtures(args.fixtures)
    known = _known_teams()

    # ── Validate team names ──────────────────────────────────────────────────
    names    = pd.unique(fx[["home_team", "away_team"]].values.ravel())
    unknown  = sorted(n for n in names if known and n not in known)
    if unknown:
        print(f"\n⚠  {len(unknown)} team name(s) not in Elo snapshot:")
        for n in unknown:
            print(f"     {n!r}")
        print("   These will be rated ELO_START (1500) → weak predictions.")
        print("   Fix spelling to match the dataset, or pass --force to keep them.\n")

    # ── Load existing + dedup ────────────────────────────────────────────────
    existing = pd.read_csv(RESULTS)
    key      = lambda d: set(zip(d["date"], d["home_team"], d["away_team"]))
    have     = key(existing)
    fx["_k"] = list(zip(fx["date"], fx["home_team"], fx["away_team"]))
    new      = fx[~fx["_k"].isin(have)].drop(columns="_k")
    dup      = len(fx) - len(new)

    print(f"Fixtures in file:   {len(fx)}")
    print(f"Already in dataset: {dup}")
    print(f"New to add:         {len(new)}")
    if len(new):
        print("\nNew fixtures:")
        for _, r in new.iterrows():
            loc = "(N)" if r["neutral"] else "   "
            print(f"  {r['date']}  {loc}  {r['home_team']:<22} vs {r['away_team']:<22}  [{r['tournament']}]")

    if args.check:
        print("\n--check: nothing written.")
        return
    if unknown and not args.force:
        print("\n[abort] Unknown team names present. Fix them or pass --force.")
        sys.exit(1)
    if len(new) == 0:
        print("\nNothing new to add.")
        return

    # ── Append (score columns blank → NA) ────────────────────────────────────
    new = new.copy()
    new["home_score"] = pd.NA
    new["away_score"] = pd.NA
    new = new[RESULTS_COLS]

    out = pd.concat([existing, new], ignore_index=True)
    out.to_csv(RESULTS, index=False)
    print(f"\n✓ Appended {len(new)} fixtures → {RESULTS}")
    print("Next: docker compose run --rm backend python scripts/predict_national.py "
          "--tournament Friendly --save-db")


if __name__ == "__main__":
    main()
