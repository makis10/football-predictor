"""
Settle fixtures the results pollers have given up on.

`update_results.py` runs with `--days-back 7`. A fixture whose result misses
that window is never asked about again: on 2026-08-11 thirteen matches sat
unresolved, two of them 80 and 86 days old — Nantes v Toulouse from 17 May and
Hull v Southampton from 23 May. They are not missing data. The result was
sitting in our own CSVs the whole time:

    F1,17/05/2026,20:00,Nantes,Toulouse,0,0,D

An unsettled past fixture is not cosmetic. Its prediction is never graded, so
it silently drops out of every accuracy figure on /stats; it keeps a row in the
"upcoming" side of queries that filter on `result IS NULL`; and a ticket leg
pointing at it can never settle, which would strand the slip for ever.

This costs no API credits — it reads the same CSVs the model trains on, through
the same loader, so team names are canonicalised identically. Anything the CSVs
cannot answer is listed rather than guessed: a fixture that was cancelled or
abandoned has no result to find, and inventing one would poison the accuracy
numbers this project exists to publish honestly.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select                                  # noqa: E402

from backend.app.database import SessionLocal                  # noqa: E402
from backend.app.models.match import Match                     # noqa: E402

_RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "raw")

# Leave the normal pollers their chance before stepping in. Anything still
# unresolved after this is not "late", it is stuck.
DEFAULT_GRACE_DAYS = 3


def _result_letter(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "H"
    if away_goals > home_goals:
        return "A"
    return "D"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grace-days", type=int, default=DEFAULT_GRACE_DAYS,
                    help="only touch fixtures older than this many days")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cutoff = date.today() - timedelta(days=args.grace_days)
    db = SessionLocal()
    try:
        stale = list(db.scalars(
            select(Match)
            .where(Match.result.is_(None))
            .where(Match.match_date < cutoff)
            .order_by(Match.match_date)
        ).all())
        if not stale:
            print("No stale fixtures — every past match has a result.")
            return 0

        print(f"{len(stale)} fixture(s) past {cutoff} with no result.")

        from backend.app.ml.features import load_raw_csvs
        df = load_raw_csvs(_RAW_DIR)
        # (date, home, away) → (home_goals, away_goals). The loader has already
        # canonicalised the names, so this matches the spelling the DB uses.
        index: dict[tuple, tuple[int, int]] = {}
        for row in df.itertuples(index=False):
            key = (row.Date.date(), row.home_team, row.away_team)
            index[key] = (int(row.home_goals), int(row.away_goals))

        settled = 0
        unresolved: list[Match] = []
        for m in stale:
            hit = index.get((m.match_date, m.home_team, m.away_team))
            if hit is None:
                unresolved.append(m)
                continue
            hg, ag = hit
            print(f"  settling {m.match_date} {m.league:<13} "
                  f"{m.home_team} {hg}-{ag} {m.away_team}")
            if not args.dry_run:
                m.home_goals, m.away_goals = hg, ag
                m.result = _result_letter(hg, ag)
            settled += 1

        if not args.dry_run and settled:
            db.commit()

        print(f"\nSettled {settled} fixture(s) from the CSVs.")

        if unresolved:
            # Not an error. Friendlies get cancelled, and the CSV feeds do not
            # cover every competition we hold fixtures for. Listed so a real
            # gap is visible rather than accumulating in silence.
            print(f"{len(unresolved)} still unresolved — no CSV row for them:")
            for m in unresolved[:20]:
                age = (date.today() - m.match_date).days
                print(f"  {m.match_date} ({age:>3}d) {m.league:<13} "
                      f"{m.home_team} v {m.away_team}")
            oldest = (date.today() - unresolved[0].match_date).days
            if oldest > 30:
                from backend.app.alerting import post_alert
                post_alert(
                    f"{len(unresolved)} fixture(s) have had no result for up to "
                    f"{oldest} days and the CSVs do not have one either. They are "
                    f"excluded from every accuracy figure until resolved.",
                    title="Fixtures stuck without a result",
                    tags="warning", log="daily.log",
                )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
