"""
Update match results for leagues sourced from The Odds API.

Covers: Greek Super League.
Champions League + domestic leagues are handled by update_results.py (football-data.org).
CL / EL / ECL results now come from API-Football via fetch_european_fixtures.py.

Safe to run multiple times (idempotent).

Usage:
  docker compose exec backend python scripts/update_european_results.py
  docker compose exec backend python scripts/update_european_results.py --days-from 3
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))  # project root

ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Leagues we still score from The Odds API.
# EL/ECL were removed: their sport keys go inactive outside the league phase and
# never cover the qualifying rounds, so scores silently never arrived.
# fetch_european_fixtures.py fills those results from API-Football instead.
COMPETITIONS = {
    "GreekSL": "soccer_greece_super_league",
}

# Must match the mappings in fetch_greek_fixtures.py and fetch_european_fixtures.py
# so that team names align with what's already stored in the DB.
TEAM_MAP: dict[str, str] = {
    # ── Greek Super League ────────────────────────────────────────────────────
    "AE Kifisia FC":        "Kifisia",
    "AEK Athens":           "AEK",
    "AEL":                  "Larisa",
    "Aris Thessaloniki":    "Aris",
    "Asteras Tripolis":     "Asteras Tripolis",
    "Atromitos Athens":     "Atromitos",
    "Levadiakos":           "Levadeiakos",
    "OFI Crete":            "OFI Crete",
    "Olympiakos Piraeus":   "Olympiakos",
    "PAOK Thessaloniki":    "PAOK",
    "Panathinaikos":        "Panathinaikos",
    "Panetolikos Agrinio":  "Panetolikos",
    "Panserraikos FC":      "Panserraikos",
    "Volos FC":             "Volos NFC",
    # ── Europa League ─────────────────────────────────────────────────────────
    "SC Freiburg":          "Freiburg",
    "Nottingham Forest":    "Nott'm Forest",
    "Real Betis":           "Betis",
    "Celta Vigo":           "Celta",
    "Aston Villa":          "Aston Villa",
    "Bologna":              "Bologna",
    # ── Conference League ─────────────────────────────────────────────────────
    "Rayo Vallecano":       "Vallecano",
    "Fiorentina":           "Fiorentina",
    "Crystal Palace":       "Crystal Palace",
    "Strasbourg":           "Strasbourg",
    "FSV Mainz 05":         "Mainz",
}


def map_team(name: str) -> str:
    return TEAM_MAP.get(name, name)


def fetch_scores(api_key: str, days_from: int) -> list[dict]:
    """Fetch completed matches from The Odds API for EL and ECL."""
    results = []

    for league_code, sport_key in COMPETITIONS.items():
        url = f"{ODDS_API_BASE}/sports/{sport_key}/scores/"
        params = {"apiKey": api_key, "daysFrom": days_from}
        print(f"  Fetching {league_code} scores …", end=" ", flush=True)

        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                print("rate limited — waiting 65s …")
                time.sleep(65)
                resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()

            remaining = resp.headers.get("x-requests-remaining", "?")
            events = resp.json()
            completed = [e for e in events if e.get("completed") and e.get("scores")]
            print(f"{len(completed)} completed  (quota remaining: {remaining})")

            for event in completed:
                try:
                    scores = event["scores"]
                    # scores is a list: each element is {"name": "Team", "score": "2"}
                    # home/away order matches commence_time home_team / away_team
                    score_map = {s["name"]: int(s["score"]) for s in scores}
                    home_raw = event["home_team"]
                    away_raw = event["away_team"]
                    hg = score_map.get(home_raw)
                    ag = score_map.get(away_raw)
                    if hg is None or ag is None:
                        continue
                    home = map_team(home_raw)
                    away = map_team(away_raw)
                    match_date = event["commence_time"][:10]
                    if hg > ag:
                        result = "H"
                    elif hg == ag:
                        result = "D"
                    else:
                        result = "A"
                    results.append({
                        "match_date": match_date,
                        "league":     league_code,
                        "home_team":  home,
                        "away_team":  away,
                        "home_goals": hg,
                        "away_goals": ag,
                        "result":     result,
                    })
                except Exception as e:
                    print(f"    [warn] Could not parse event: {e}")

        except Exception as e:
            print(f"ERROR: {e}")

        time.sleep(2)  # be polite with the free-tier quota

    return results


def update_db(finished: list[dict]) -> tuple[int, int]:
    """
    Update match rows that have result=NULL.
    Returns (updated, not_found).
    """
    from datetime import date as date_type
    from sqlalchemy import select
    from backend.app.database import SessionLocal
    from backend.app.models.match import Match

    db = SessionLocal()
    updated = not_found = 0
    try:
        for f in finished:
            match_date = date_type.fromisoformat(f["match_date"])
            match = db.scalars(
                select(Match).where(
                    Match.match_date == match_date,
                    Match.home_team  == f["home_team"],
                    Match.away_team  == f["away_team"],
                    Match.league     == f["league"],
                    Match.result.is_(None),         # only update unresolved
                )
            ).first()

            if match:
                match.home_goals = f["home_goals"]
                match.away_goals = f["away_goals"]
                match.result     = f["result"]
                updated += 1
            else:
                not_found += 1

        db.commit()
    finally:
        db.close()

    return updated, not_found


def main():
    parser = argparse.ArgumentParser(
        description="Update EL/ECL match results from The Odds API"
    )
    parser.add_argument(
        "--key",
        default=os.getenv("ODDS_API_KEY", ""),
        help="The Odds API key (or set ODDS_API_KEY in .env)",
    )
    parser.add_argument(
        "--days-from", type=int, default=3,
        help="How many days back to look for completed matches (default: 3)",
    )
    args = parser.parse_args()

    if not args.key:
        print("ERROR: Set ODDS_API_KEY in .env or pass --key.")
        sys.exit(1)

    print(f"\nFetching GreekSL / EL / ECL scores (last {args.days_from} days) …")
    finished = fetch_scores(args.key, args.days_from)
    print(f"\nTotal completed matches fetched: {len(finished)}")

    if finished:
        print("\nUpdating database …")
        updated, not_found = update_db(finished)
        print(f"  Updated:   {updated} matches")
        print(f"  Not found: {not_found} (already updated or not in our DB)")
    else:
        print("No completed matches found.")

    print("\nDone.")


if __name__ == "__main__":
    main()
