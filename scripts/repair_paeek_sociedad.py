"""One-off repair for two clubs a feed name handed to the wrong side.

Both were found on 2026-09-09 from a reader's screenshot: the Recent Results page
showed LASK playing twice on the same afternoon, once against "AEK Athens" and
once against "PAEEK".

1. PAEEK (Cypriot, 32 rows of second-tier history) took four Champions League
   fixtures off AEK Athens, because football-data.org calls AEK "PAE AEK" — ΠΑΕ
   ΑΕΚ, the Greek legal form — and the resolver's spelling-drift rule scored
   "paeek" against "paeaek" at 0.909 while the correct answer, "AEK", was
   excluded by the >=5-character guard that exists to stop short names hijacking
   long ones. Each phantom is a DUPLICATE: the real AEK fixture exists alongside
   it, carrying the API-Football id and, for the first one, the result. The
   phantoms are deleted; their predictions go with them via ON DELETE CASCADE,
   and any accumulator holding one is voided by generate_tickets.py's existing
   leg-count check.

2. Real Sociedad's B team took eleven fixtures off the first team — eight Europa
   League ties including Juventus, Lyon and Crystal Palace — because
   "realsociedad" against "realsociedadii" is 0.923 and nothing refused a
   reserve side as the ANSWER. These are not duplicates: no correct row exists,
   so they are renamed rather than deleted, which is what dedupe_fixtures.py
   does with a keeper. The settled friendlies are renamed too: the prediction we
   published stays exactly as it was, and it is now filed against the club that
   actually played.

The resolver fix is in scripts/team_resolver.py and stops both recurring; this
only cleans up what was already written.

Dry run by default. Nothing is written without --apply.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually write")
    args = ap.parse_args()

    from sqlalchemy import or_

    from backend.app.database import SessionLocal
    from backend.app.models.match import Match

    db = SessionLocal()
    try:
        # ── 1. the PAEEK phantoms ────────────────────────────────────────────
        phantoms = db.query(Match).filter(
            or_(Match.home_team == "PAEEK", Match.away_team == "PAEEK")
        ).all()

        print(f"PAEEK rows: {len(phantoms)}")
        deletable = []
        for m in phantoms:
            other = "AEK"
            twin = db.query(Match).filter(
                Match.league == m.league,
                Match.match_date == m.match_date,
                Match.home_team == (other if m.home_team == "PAEEK" else m.home_team),
                Match.away_team == (other if m.away_team == "PAEEK" else m.away_team),
                Match.id != m.id,
            ).first()
            if twin is None:
                print(f"  [keep] {m.id} {m.match_date} {m.home_team} v {m.away_team} "
                      f"— no AEK twin; not a duplicate, leaving it alone")
                continue
            if m.result is not None:
                print(f"  [keep] {m.id} — has a result; refusing to delete graded history")
                continue
            print(f"  [drop] {m.id} {m.match_date} {m.home_team} v {m.away_team} "
                  f"→ duplicate of {twin.id} ({twin.home_team} v {twin.away_team}, "
                  f"api id {twin.api_fixture_id}, result {twin.result})")
            deletable.append(m)

        # ── 2. the reserve-side misattributions ──────────────────────────────
        reserves = db.query(Match).filter(
            or_(Match.home_team == "Real Sociedad II", Match.away_team == "Real Sociedad II")
        ).all()
        print(f"\nReal Sociedad II rows: {len(reserves)}")
        renamable = []
        for m in reserves:
            h = "Sociedad" if m.home_team == "Real Sociedad II" else m.home_team
            a = "Sociedad" if m.away_team == "Real Sociedad II" else m.away_team
            clash = db.query(Match).filter(
                Match.league == m.league, Match.match_date == m.match_date,
                Match.home_team == h, Match.away_team == a, Match.id != m.id,
            ).first()
            if clash is not None:
                print(f"  [keep] {m.id} — renaming would collide with {clash.id}; "
                      f"leave for dedupe_fixtures.py")
                continue
            print(f"  [rename] {m.id} {m.match_date} {m.league:12s} "
                  f"{m.home_team} v {m.away_team} → {h} v {a}"
                  + ("  (settled — prediction unchanged)" if m.result else ""))
            renamable.append((m, h, a))

        if not args.apply:
            print(f"\nDRY RUN — would delete {len(deletable)} and rename {len(renamable)}. "
                  f"Re-run with --apply.")
            return 0

        for m in deletable:
            db.delete(m)
        for m, h, a in renamable:
            m.home_team, m.away_team = h, a
        db.commit()
        print(f"\nApplied: {len(deletable)} deleted, {len(renamable)} renamed.")
        print("Run generate_tickets.py --settle-only to void any slip that lost a leg,")
        print("and compute_predictions.py to re-price the renamed fixtures.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
