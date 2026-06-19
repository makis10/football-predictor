"""
One-off back-fill script for kickoff_time.

After migration 0002 added the kickoff_time column, all existing upcoming
matches have NULL kickoff_time.  This script queries The Odds API for each
supported league (one API call per league) and fuzzy-matches fixtures by
team name, setting the UTC kick-off time on any match that is still missing
one.

Safe to re-run — only updates rows where kickoff_time IS NULL.

Usage:
  docker compose exec backend python scripts/backfill_kickoff_times.py
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))  # project root

from datetime import date, datetime, timezone
from typing import Optional

import requests
from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.models.match import Match
from backend.app.ml.odds_analysis_service import (
    LEAGUE_SPORT_KEY,
    _teams_match,
)

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
if not ODDS_API_KEY:
    print("ERROR: ODDS_API_KEY not set in environment.", flush=True)
    sys.exit(1)


def fetch_league_events(sport_key: str) -> list:
    """Fetch event list (name + commence_time) for a sport, one cheap request."""
    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/events",
            params={"apiKey": ODDS_API_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json()
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"  {sport_key}: {len(events)} events  (quota remaining: {remaining})")
        return events if isinstance(events, list) else []
    except Exception as e:
        print(f"  {sport_key}: ERROR — {e}")
        return []


def event_kickoff(event: dict) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def main() -> None:
    db = SessionLocal()

    # Gather all upcoming matches (date >= today) with no kickoff_time.
    needs_backfill = db.scalars(
        select(Match)
        .where(Match.match_date >= date.today())
        .where(Match.kickoff_time.is_(None))
    ).all()

    print(f"Matches needing kickoff_time: {len(needs_backfill)}", flush=True)
    if not needs_backfill:
        db.close()
        return

    # Group by league so we can fetch each league's events with one API call.
    by_league: dict[str, list[Match]] = {}
    for m in needs_backfill:
        by_league.setdefault(m.league, []).append(m)

    total_filled = 0
    total_miss   = 0

    for league, matches in by_league.items():
        sport_key = LEAGUE_SPORT_KEY.get(league)
        if not sport_key:
            print(f"[skip] {league}: no sport_key mapping (or unsupported on Odds API)")
            total_miss += len(matches)
            continue

        events = fetch_league_events(sport_key)
        if not events:
            total_miss += len(matches)
            continue

        filled_here = 0
        for m in matches:
            match_dt: Optional[datetime] = None
            for event in events:
                if not _teams_match(event.get("home_team", ""), m.home_team):
                    continue
                if not _teams_match(event.get("away_team", ""), m.away_team):
                    continue
                dt = event_kickoff(event)
                if dt and dt.date() == m.match_date:
                    match_dt = dt
                    break

            if match_dt is not None:
                m.kickoff_time = match_dt.time().replace(microsecond=0)
                filled_here += 1
            # else: no match — leave NULL, UI falls back to date-only display

        print(f"  {league}: filled {filled_here}/{len(matches)}")
        total_filled += filled_here
        total_miss   += len(matches) - filled_here

    db.commit()
    db.close()

    print(
        f"\nDone: back-filled {total_filled} matches, "
        f"{total_miss} left with NULL kickoff_time."
    )


if __name__ == "__main__":
    main()
