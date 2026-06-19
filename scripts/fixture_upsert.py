"""
Shared reschedule-aware fixture upsert used by all fixture-fetch scripts
(fetch_upcoming.py, fetch_greek_fixtures.py, fetch_european_fixtures.py).

Why it exists
-------------
Fixtures get rescheduled (weather, TV slots, cup clashes). The old per-script
logic matched on the EXACT (date, home, away, league) tuple, so a rescheduled
match never matched its DB row: the stale row stayed "pending" forever (its
result-updater lookup also uses the date) and a duplicate row appeared under
the new date. Observed in production: Panserraikos–Panetolikos stored on
2026-05-16 while the real kick-off was 05-17.

Matching order per incoming fixture:
  1. Exact (league, home, away, date)            → backfill/refresh kickoff_time
  2. Same (league, home, away), result IS NULL,
     date within ±window days                    → RESCHEDULE: update date+time
                                                   in place (preserves match id,
                                                   predictions, user tracking)
  3. No match                                    → INSERT new row

Returns (new_matches, touched_ids) so callers can optionally prune unplayed
rows of the same leagues that vanished from the source feed without touching
anything they didn't fetch.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select


def upsert_fixtures(
    db,
    fixtures: list[dict],
    reschedule_window_days: int = 5,
) -> tuple[list, set[int]]:
    """Insert or update fixtures; reschedule-aware. See module docstring."""
    from backend.app.models.match import Match

    new_matches: list = []
    touched_ids: set[int] = set()
    skipped = backfilled = rescheduled = 0

    for f in fixtures:
        # 1. Exact match
        exists = db.scalars(
            select(Match).where(
                Match.match_date == f["match_date"],
                Match.home_team  == f["home_team"],
                Match.away_team  == f["away_team"],
                Match.league     == f["league"],
            )
        ).first()
        if exists:
            if f.get("kickoff_time") is not None and exists.kickoff_time != f["kickoff_time"]:
                exists.kickoff_time = f["kickoff_time"]
                backfilled += 1
            skipped += 1
            touched_ids.add(exists.id)
            continue

        # 2. Reschedule: same pairing, unresolved, nearby date
        window = timedelta(days=reschedule_window_days)
        candidate = db.scalars(
            select(Match).where(
                Match.home_team  == f["home_team"],
                Match.away_team  == f["away_team"],
                Match.league     == f["league"],
                Match.result.is_(None),
                Match.match_date >= f["match_date"] - window,
                Match.match_date <= f["match_date"] + window,
            )
        ).first()
        if candidate:
            old_date = candidate.match_date
            candidate.match_date   = f["match_date"]
            candidate.kickoff_time = f.get("kickoff_time")
            rescheduled += 1
            touched_ids.add(candidate.id)
            print(f"  ↻ rescheduled {f['home_team']} vs {f['away_team']} "
                  f"({f['league']}): {old_date} → {f['match_date']}")
            continue

        # 3. New fixture
        m = Match(
            match_date=f["match_date"],
            kickoff_time=f.get("kickoff_time"),
            league=f["league"],
            season=f["season"],
            home_team=f["home_team"],
            away_team=f["away_team"],
        )
        db.add(m)
        new_matches.append(m)

    db.commit()
    for m in new_matches:
        db.refresh(m)
        touched_ids.add(m.id)

    print(f"  Inserted {len(new_matches)} new, {skipped} unchanged, "
          f"{rescheduled} rescheduled"
          + (f", kickoff updated on {backfilled}" if backfilled else "")
          + ".")
    return new_matches, touched_ids


def prune_vanished(
    db,
    leagues: list[str],
    touched_ids: set[int],
    horizon_days: int = 60,
) -> int:
    """
    Delete unplayed fixtures of the given leagues that the source feed no
    longer lists (cancelled / moved beyond recognition). Scope is strictly
    [today, today + horizon_days] — the window the feed actually covered —
    and only the given leagues; fixtures beyond the horizon, other leagues,
    past matches, and anything seen in this run are never touched, so user
    tracking and predictions on live fixtures survive.
    """
    from datetime import date as _date

    from sqlalchemy import delete

    from backend.app.models.match import Match

    today = _date.today()
    result = db.execute(
        delete(Match)
        .where(Match.result.is_(None))
        .where(Match.match_date >= today)
        .where(Match.match_date <= today + timedelta(days=horizon_days))
        .where(Match.league.in_(leagues))
        .where(Match.id.notin_(touched_ids) if touched_ids else True)
    )
    db.commit()
    if result.rowcount:
        print(f"  Pruned {result.rowcount} vanished fixture(s) in {leagues}.")
    return result.rowcount
