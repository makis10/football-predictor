#!/usr/bin/env python3
"""Rewrite history CSVs so no team name means two different clubs.

`league_registry.NAME_DISAMBIGUATION` is applied by the importer from now on;
this applies it once to the files already on disk. Without it, "Arsenal" keeps
holding Arsenal FC and FC Arsenal Dzyarzhynsk in one Elo rating, and the
importer's fix only takes effect the next time a season is re-fetched — which
for a finished season is never.

    python scripts/disambiguate_existing_csvs.py --dry-run
    python scripts/disambiguate_existing_csvs.py

Files are read and written as latin-1, the codec `features.load_raw_csvs` uses.
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.ml.league_registry import NAME_DISAMBIGUATION  # noqa: E402

RAW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "backend", "data", "raw")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    by_league: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for (league, old), new in NAME_DISAMBIGUATION.items():
        by_league[league][old] = new

    changed_files = 0
    changed_cells: collections.Counter = collections.Counter()

    for path in sorted(glob.glob(os.path.join(RAW, "*.csv"))):
        league, _, season = os.path.basename(path)[:-4].rpartition("_")
        renames = by_league.get(league)
        if not renames or not season.isdigit():
            continue

        with open(path, newline="", encoding="latin-1") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            rows = list(reader)
        home = "home_team" if "home_team" in fields else "HomeTeam"
        away = "away_team" if "away_team" in fields else "AwayTeam"
        if home not in fields or away not in fields:
            continue

        hits = 0
        for row in rows:
            for col in (home, away):
                new = renames.get((row.get(col) or "").strip())
                if new:
                    row[col] = new
                    hits += 1
                    changed_cells[f"{league}: {new}"] += 1
        if not hits:
            continue

        changed_files += 1
        print(f"  {os.path.basename(path):26s} {hits:4d} cell(s)")
        if not args.dry_run:
            with open(path, "w", newline="", encoding="latin-1") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

    print(f"\n{'would rewrite' if args.dry_run else 'rewrote'} {changed_files} file(s)")
    for label, n in sorted(changed_cells.items()):
        print(f"  {n:5d}  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
