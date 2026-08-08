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
    renames.update(_accent_folds())
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

    _migrate_id_cache(renames, args.dry_run)
    return 0


def _accent_folds() -> dict[str, str]:
    """DB names that are an accented spelling of a club we hold.

    The fixture feeds write "Velež" and "Žilina"; the history importer strips
    the accents, so the training data says "Velez" and "Zilina". Nothing bridged
    the two, and the consequences were silent and doubled: `update_results`
    matches team names with `==`, so those fixtures could never be scored, and
    the model had no history for them either, so they were served as
    insufficient-data cards.

    Only folds where the ASCII form is a name we actually hold — an accented
    name with no ASCII counterpart is a club we simply do not know.
    """
    import unicodedata

    from backend.app.database import SessionLocal
    from backend.app.models.match import Match
    from scripts.team_resolver import known_team_names

    known = set(known_team_names())
    db = SessionLocal()
    try:
        rows = db.query(Match.home_team, Match.away_team).all()
    finally:
        db.close()

    folds: dict[str, str] = {}
    for home, away in rows:
        for name in (home, away):
            if not name or name in known or name in folds:
                continue
            ascii_name = (unicodedata.normalize("NFKD", name)
                          .encode("ascii", "ignore").decode())
            if ascii_name and ascii_name != name and ascii_name in known:
                folds[name] = ascii_name
    return folds


def _migrate_id_cache(renames: dict[str, str], dry_run: bool) -> None:
    """Move cached API-Football ids onto the surviving club name.

    `club_team_ids.json` is keyed by OUR name, so a merge orphans the id: after
    "SK Beveren" folded into "Waasland-Beveren" the id sat under a name nothing
    looks up any more, and the daily check reported the club as having no API
    id at all — no cards, no corners, no player props.
    """
    import json
    import os

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "backend", "data", "models", "club_team_ids.json")
    if not os.path.isfile(path):
        return
    cache = json.load(open(path))
    moved: list[str] = []
    for old_name, new_name in renames.items():
        if old_name in cache and cache[old_name] and not cache.get(new_name):
            cache[new_name] = cache[old_name]
            moved.append(f"{old_name} → {new_name} (id {cache[old_name]})")
        cache.pop(old_name, None)
    print(f"\n{'would move' if dry_run else 'moved'} {len(moved)} cached id(s)")
    for label in moved:
        print(f"  {label}")
    if not dry_run:
        json.dump(cache, open(path, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    raise SystemExit(main())
