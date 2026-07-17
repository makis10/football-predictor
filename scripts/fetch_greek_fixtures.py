"""
Fetch upcoming Greek Super League fixtures from The Odds API.

football-data.org does NOT cover Greek SL on the free tier, and football-data.co.uk
CSVs only contain completed matches.  We use The Odds API (already integrated for
odds comparison) which carries the full upcoming schedule for Greek SL.

The script:
  1. Calls GET /v4/sports/soccer_greece_super_league/events  (no odds, just fixtures).
  2. Maps The Odds API team names to our training-data names.
  3. Inserts upcoming fixtures into the DB, skipping duplicates.
  4. Fetch-only — predictions are computed by compute_predictions.py.

API usage: 1 request per run — well within the 500 req/month free limit.
Safe to run multiple times (idempotent).

Usage (inside the backend container):
  python scripts/fetch_greek_fixtures.py
  python scripts/fetch_greek_fixtures.py   # --no-predictions accepted but a no-op
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _PROJECT_ROOT)

from scripts._http_retry import get_with_retry  # noqa: E402

SPORT_KEY = "soccer_greece_super_league"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Team name mapping: The Odds API → our training-data / DB names
TEAM_MAP: dict[str, str] = {
    "AE Kifisia FC":        "Kifisia",
    "AEK Athens":           "AEK",
    "AEL":                  "Larisa",        # AE Larissa
    "Aris Thessaloniki":    "Aris",
    "Asteras Tripolis":     "Asteras Tripolis",
    "Atromitos Athens":     "Atromitos",
    "Levadiakos":           "Levadeiakos",   # note different spelling in CSV
    "OFI Crete":            "OFI Crete",
    "Olympiakos Piraeus":   "Olympiakos",
    "PAOK Thessaloniki":    "PAOK",
    "Panathinaikos":        "Panathinaikos",
    "Panetolikos Agrinio":  "Panetolikos",
    "Panserraikos FC":      "Panserraikos",
    "Volos FC":             "Volos NFC",
}


def map_team(name: str) -> str:
    return TEAM_MAP.get(name, name)


def infer_season(d: date) -> str:
    if d.month >= 7:
        return f"{d.year}/{str(d.year + 1)[2:]}"
    return f"{d.year - 1}/{str(d.year)[2:]}"


def fetch_events(api_key: str) -> list[dict]:
    """Return upcoming Greek SL fixtures from The Odds API."""
    url = f"{ODDS_API_BASE}/sports/{SPORT_KEY}/events"
    params = {"apiKey": api_key}
    print(f"  GET {url} …", end=" ", flush=True)
    resp = get_with_retry(url, params=params, timeout=15)
    resp.raise_for_status()
    events = resp.json()
    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"{len(events)} events  (quota remaining: {remaining})")
    return events


def parse_fixtures(events: list[dict]) -> list[dict]:
    """Convert Odds API event records to our fixture format."""
    fixtures = []
    today = date.today()
    for event in events:
        try:
            # commence_time is UTC ISO-8601, e.g. "2026-04-18T15:00:00Z"
            dt = datetime.fromisoformat(
                event["commence_time"].replace("Z", "+00:00")
            )
            dt_utc = dt.astimezone(timezone.utc)
            match_date = dt_utc.date()
            match_time = dt_utc.time().replace(microsecond=0)
        except Exception:
            continue

        if match_date < today:
            continue  # already played

        home = map_team(event["home_team"])
        away = map_team(event["away_team"])
        fixtures.append({
            "match_date":   match_date,
            "kickoff_time": match_time,
            "league":       "GreekSL",
            "home_team":    home,
            "away_team":    away,
            "season":       infer_season(match_date),
        })

    return fixtures


def insert_fixtures(db, fixtures: list[dict]) -> list:
    """Reschedule-aware upsert via the shared helper. Returns new Match objects.

    No pruning here: The Odds API feed only lists matches with active odds
    (~8 days out), so absence from the feed doesn't mean cancelled."""
    # Greek SL is a training league — an unmapped Odds-API spelling becomes a
    # phantom team, so flag it (see the Bayer Leverkusen / AC Milan bug).
    from scripts.team_resolver import warn_unknown_teams
    warn_unknown_teams(fixtures, domestic=True)

    from scripts.fixture_upsert import upsert_fixtures
    new_matches, _ = upsert_fixtures(db, fixtures)
    return new_matches


def main():
    parser = argparse.ArgumentParser(
        description="Fetch upcoming Greek SL fixtures via The Odds API"
    )
    parser.add_argument(
        "--key",
        default=os.getenv("ODDS_API_KEY", ""),
        help="The Odds API key (or set ODDS_API_KEY in .env)",
    )
    parser.add_argument(
        "--no-predictions", action="store_true",
        help="Deprecated no-op (kept for backward-compat); this script is fetch-only",
    )
    args = parser.parse_args()

    if not args.key:
        print("ERROR: Set ODDS_API_KEY in .env or pass --key.")
        sys.exit(1)

    from backend.app.database import SessionLocal

    print("\nFetching Greek SL upcoming fixtures …")
    events = fetch_events(args.key)
    fixtures = parse_fixtures(events)
    print(f"  Valid upcoming fixtures: {len(fixtures)}")
    for f in fixtures:
        print(f"    {f['match_date']}  {f['home_team']} vs {f['away_team']}")

    if not fixtures:
        print("  Nothing to insert.")
        return

    db = SessionLocal()
    try:
        new_matches = insert_fixtures(db, fixtures)
        # Fetch-only. Predictions come exclusively from scripts/compute_predictions.py
        # (the single canonical path: calibration + draw/BTTS specialists + Poisson λ +
        # value gate). The old in-script predictor produced inferior, uncalibrated
        # rows without BTTS/λ and was removed 2026-07-17.
        print(f"\n{len(new_matches)} new fixture(s) inserted. "
              f"Predictions are computed by compute_predictions.py.")
    finally:
        db.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
