"""
Pre-warm the Redis injury cache for upcoming matches.

Fetches injury/suspension data from API-Football for every match
scheduled within the next `--days` days (default 7) that belongs
to a league with injury support.  Results are stored in Redis with
a 30-minute TTL (same key used by the detail page), so:

  • The match list page immediately shows injury-adjusted predictions.
  • The detail page hits Redis instead of the live API for 30 min.

API-Football free tier: 100 calls/day.
Supported leagues consume ~20-30 calls/day for a 7-day window.

Daily run uses --days 3 (matches the 3-day window on the main page) with no
--force, so only genuinely new fixtures (no Redis entry yet) are fetched.
Existing cached entries are left untouched; if an injury changes, the user
sees it on first visit to the match detail page.

Usage:
  docker compose exec backend python scripts/warmup_injuries.py
  docker compose exec backend python scripts/warmup_injuries.py --days 3
  docker compose exec backend python scripts/warmup_injuries.py --days 7 --force
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))  # project root

# Leagues that have injury data on API-Football (api-sports.io).
# Championship / LeagueOne / PrimeiraLiga / Eredivisie are supported
# by the API but the free-tier response is often empty; include them
# anyway so the cache is consistent.
INJURY_LEAGUES = {
    "EPL", "LaLiga", "SerieA", "Bundesliga", "Ligue1",
    "GreekSL", "CL", "EL", "ECL",
    "Championship", "LeagueOne", "PrimeiraLiga", "Eredivisie",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-warm Redis injury cache for upcoming matches."
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="How many days ahead to warm (default: 7)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-fetch even when Redis already has a cached entry"
    )
    args = parser.parse_args()

    from backend.app.database import SessionLocal
    from backend.app.models.match import Match
    from backend.app.models.prediction import Prediction
    from backend.app.routers.predictions import _get_injuries_cached, _INJURY_TTL
    from backend.app.cache import cache_get, CACHE_MISS
    import redis, os

    today   = date.today()
    horizon = today + timedelta(days=args.days)

    db = SessionLocal()
    from sqlalchemy import select
    rows = db.execute(
        select(Match, Prediction)
        .join(Prediction, Prediction.match_id == Match.id)
        .where(Match.result.is_(None))
        .where(Match.match_date >= today)
        .where(Match.match_date <= horizon)
        .order_by(Match.match_date.asc())
    ).all()
    db.close()

    eligible = [(m, p) for m, p in rows if m.league in INJURY_LEAGUES]
    skipped  = len(rows) - len(eligible)

    print(f"\nWarm-up: {len(eligible)} matches in next {args.days} days "
          f"({skipped} skipped — unsupported league)\n")

    ok = cached_hits = errors = 0

    for match, _ in eligible:
        key = f"injuries:{match.id}"

        if not args.force:
            existing = cache_get(key)
            if existing is not CACHE_MISS:
                cached_hits += 1
                print(f"  [cache] {match.home_team} vs {match.away_team} "
                      f"[{match.league}] {match.match_date}")
                continue

        try:
            result = _get_injuries_cached(
                match.id,
                match.home_team,
                match.away_team,
                match.league,
                match.match_date,
            )
            n_home = len(result.get("home", [])) if result else 0
            n_away = len(result.get("away", [])) if result else 0
            status = f"{n_home}H {n_away}A" if result else "no data"
            print(f"  [fetch] {match.home_team} vs {match.away_team} "
                  f"[{match.league}] {match.match_date}  →  {status}")
            ok += 1
        except Exception as e:
            print(f"  [error] {match.home_team} vs {match.away_team}: {e}")
            errors += 1

    print(f"\nDone: {ok} fetched, {cached_hits} already cached, {errors} errors.\n")


if __name__ == "__main__":
    main()
