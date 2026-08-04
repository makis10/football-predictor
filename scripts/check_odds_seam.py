#!/usr/bin/env python3
"""Which clubs does the odds feed name differently from us?

A fixture only gets bookmaker odds if `_teams_match` can tie our stored team
name to The Odds API's. When it cannot, the match is served with no odds, no
EV and no value gate — and nothing says why. The daily health check reports the
seam as a percentage ("only 49% of tracked-league predictions matched odds"),
which tells you there is a problem but not which club causes it.

This names them. For every league with an active market it lists the upcoming
events, runs each side through the real matcher against the team names we hold
for that league, and prints the ones that fail.

Uses The Odds API's /events endpoint, which returns fixtures WITHOUT odds and
does not count against the quota, so this is free to run as often as you like.

    python scripts/check_odds_seam.py
    python scripts/check_odds_seam.py --league Eredivisie

Exit status is 1 when anything is unmatched, so it can gate a pipeline step.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from backend.app.ml.odds_analysis_service import (  # noqa: E402
    LEAGUE_SPORT_KEY, LEAGUE_SPORT_KEY_ALTS, _teams_match,
)

EVENTS_URL = "https://api.the-odds-api.com/v4/sports/{key}/events"
SPORTS_URL = "https://api.the-odds-api.com/v4/sports/"


def _active_keys(api_key: str) -> set[str]:
    r = requests.get(SPORTS_URL, params={"apiKey": api_key, "all": "true"}, timeout=20)
    r.raise_for_status()
    return {s["key"] for s in r.json() if s.get("active")}


def _events(sport_key: str, api_key: str) -> list[dict]:
    r = requests.get(EVENTS_URL.format(key=sport_key),
                     params={"apiKey": api_key}, timeout=20)
    if r.status_code != 200:
        return []
    body = r.json()
    return body if isinstance(body, list) else []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--league", help="check one league only")
    ap.add_argument("--days", type=int, default=14,
                    help="how far ahead our fixtures are read (default 14)")
    args = ap.parse_args()

    api_key = os.getenv("ODDS_API_KEY", "")
    if not api_key:
        print("ODDS_API_KEY not set")
        return 2

    from backend.app.database import SessionLocal
    from backend.app.models.match import Match

    # Every name we have ever stored for the league, not just the next
    # fortnight's: a league between seasons has almost no upcoming fixtures, so
    # matching against that window alone reported Barcelona and Real Madrid as
    # unmatched — the failure was in the question, not the data.
    db = SessionLocal()
    try:
        rows = db.query(Match).all()
    finally:
        db.close()

    ours: dict[str, set[str]] = collections.defaultdict(set)
    for m in rows:
        ours[m.league].update((m.home_team, m.away_team))

    active = _active_keys(api_key)
    leagues = [args.league] if args.league else sorted(ours)
    unmatched: dict[str, set[str]] = collections.defaultdict(set)
    no_market: list[str] = []

    for league in leagues:
        keys = [LEAGUE_SPORT_KEY.get(league)] + LEAGUE_SPORT_KEY_ALTS.get(league, [])
        keys = [k for k in keys if k]
        live = [k for k in keys if k in active]
        if not live:
            no_market.append(f"{league} ({keys[0] if keys else 'no sport key at all'})")
            continue
        for key in live:
            for event in _events(key, api_key):
                for side in ("home_team", "away_team"):
                    api_name = event.get(side) or ""
                    if not api_name:
                        continue
                    if not any(_teams_match(api_name, n) for n in ours[league]):
                        unmatched[league].add(api_name)

    if no_market:
        print(f"── no active market on The Odds API ({len(no_market)}) " + "─" * 26)
        for entry in no_market:
            print(f"  {entry}")
        print("  (nothing to fix here — these fixtures cannot carry odds)\n")

    total = sum(len(v) for v in unmatched.values())
    print(f"── odds-feed names we fail to match ({total}) " + "─" * 30)
    for league in sorted(unmatched):
        print(f"  {league}")
        for name in sorted(unmatched[league]):
            print(f"      {name!r}")
    if not total:
        print("  none — every event ties to one of our clubs")
    else:
        print("\n  Add each to odds_analysis_service._ALIASES under OUR name for "
              "the club, as a slug (lowercase, letters and digits only).")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
