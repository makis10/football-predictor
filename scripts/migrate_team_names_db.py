#!/usr/bin/env python3
"""Bring stored fixtures onto the training data's spelling of each club.

`features._CSV_TEAM_CANON` decides which of two spellings a club's history is
filed under. Fixtures written before a merge still carry the losing spelling,
and that name no longer exists in `known_team_names()` — so the club looks
unknown, gets default features and renders as an insufficient-data card. The
2026-08-02 second-tier merges left 339 such rows, including upcoming Bundesliga
fixtures for Heidenheim, Bochum and St Pauli.

    python scripts/migrate_team_names_db.py --dry-run
    python scripts/migrate_team_names_db.py

Safe to re-run: canonical() is idempotent, so a second pass finds nothing.
"""
from __future__ import annotations

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from sqlalchemy import or_

    from backend.app.database import SessionLocal
    from backend.app.models.match import Match
    from scripts.team_resolver import alias_map

    renames = {src: dst for src, dst in alias_map().items() if src != dst}
    changes: collections.Counter = collections.Counter()

    db = SessionLocal()
    try:
        rows = (db.query(Match)
                .filter(or_(Match.home_team.in_(renames), Match.away_team.in_(renames)))
                .all())
        for match in rows:
            for col in ("home_team", "away_team"):
                old = getattr(match, col)
                new = renames.get(old)
                if new and new != old:
                    setattr(match, col, new)
                    changes[f"{old} → {new}"] += 1
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    total = sum(changes.values())
    print(f"{'would rename' if args.dry_run else 'renamed'} {total} team cell(s) "
          f"across {len(rows)} fixture(s)")
    for label, n in sorted(changes.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
