"""
Backfill bm_btts_yes_odds / bm_btts_no_odds for past predictions
that were computed before migration 0012 added the BTTS odds columns.

Strategy
--------
Uses The Odds API HISTORICAL endpoint (no event IDs needed):

  GET /v4/historical/sports/{sport}/odds
      ?date={match_date}T12:00:00Z&markets=btts&regions=eu

One call per (league, match_date) combination — returns all events
that day with BTTS odds as they were at 12:00 UTC (pre-kickoff for
evening matches). We match events to our DB rows by team name.

API cost
--------
  ~1–2 credits per (league, date) pair.
  181 matches → ~30–70 unique (league, date) pairs → ~60–140 credits.
  Well within 20k/month budget.

Usage
-----
  docker compose exec backend python scripts/backfill_btts_odds.py
  docker compose exec backend python scripts/backfill_btts_odds.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Optional

import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))  # project root

import requests
from sqlalchemy import text

from backend.app.database import SessionLocal
from backend.app.ml.odds_analysis_service import ODDS_API_KEY, LEAGUE_SPORT_KEY

RATE_LIMIT_SLEEP     = 0.3    # seconds between API calls
TEAM_MATCH_THRESHOLD = 0.75
BASE_URL             = "https://api.the-odds-api.com/v4"


# ── Team name normalisation ───────────────────────────────────────────────────

def _slug(name: str) -> str:
    return (
        name.lower()
        .replace("fc ", "").replace(" fc", "")
        .replace("athletic ", "ath ").replace("atletico", "ath")
        .replace("manchester", "man")
        .replace("tottenham hotspur", "tottenham")
        .replace("nottingham", "nott'm").replace("nott'm forest", "nott'm forest")
        .replace(".", "").replace("-", " ").strip()
    )


def _teams_match(api_name: str, db_name: str) -> bool:
    a, b = _slug(api_name), _slug(db_name)
    if a == b or a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() >= TEAM_MATCH_THRESHOLD


# ── The Odds API — historical endpoint ───────────────────────────────────────

def _fetch_historical_btts(sport_key: str, snapshot_date: date) -> list[dict]:
    """
    Fetch BTTS odds for ALL events on snapshot_date at 12:00 UTC.
    Returns list of {"home_team", "away_team", "yes_odds", "no_odds"}.
    Tries 12:00 UTC; falls back to 08:00 UTC day-before if empty.
    """
    for dt_str in [
        f"{snapshot_date}T12:00:00Z",
        f"{snapshot_date - timedelta(days=1)}T20:00:00Z",
    ]:
        try:
            resp = requests.get(
                f"{BASE_URL}/historical/sports/{sport_key}/odds/",
                params={
                    "apiKey":     ODDS_API_KEY,
                    "regions":    "eu",
                    "markets":    "btts",
                    "dateFormat": "iso",
                    "oddsFormat": "decimal",
                    "date":       dt_str,
                },
                timeout=15,
            )
            # Print response body on error for diagnosis
            if not resp.ok:
                print(f"    [hist] {sport_key} @ {dt_str}  HTTP {resp.status_code}: {resp.text[:200]}")
                continue

            remaining = resp.headers.get("x-requests-remaining", "?")
            payload   = resp.json()
            events    = payload.get("data", [])

            if not events:
                continue

            print(f"    [hist] {sport_key} @ {dt_str}  → {len(events)} events  (quota left: {remaining})")
            results = []
            for ev in events:
                parsed = _parse_btts_from_bookmakers(ev.get("bookmakers", []))
                if parsed:
                    results.append({
                        "home_team": ev.get("home_team", ""),
                        "away_team": ev.get("away_team", ""),
                        "yes_odds":  parsed[0],
                        "no_odds":   parsed[1],
                    })
            return results

        except Exception as e:
            print(f"    [hist] {sport_key} @ {dt_str} FAILED: {e}")

    return []


def _parse_btts_from_bookmakers(bookmakers: list) -> Optional[tuple[float, float]]:
    yes_list: list[float] = []
    no_list:  list[float] = []
    for bm in bookmakers:
        for market in bm.get("markets", []):
            if market.get("key") != "btts":
                continue
            for outcome in market.get("outcomes", []):
                if outcome["name"] == "Yes":
                    yes_list.append(float(outcome["price"]))
                elif outcome["name"] == "No":
                    no_list.append(float(outcome["price"]))
    if not yes_list:
        return None
    return (
        round(sum(yes_list) / len(yes_list), 2),
        round(sum(no_list)  / len(no_list),  2) if no_list else None,
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print matches found but do not update DB")
    args = parser.parse_args()

    if not ODDS_API_KEY:
        print("ERROR: ODDS_API_KEY not set")
        sys.exit(1)

    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT
                p.id            AS pred_id,
                m.league,
                m.match_date,
                m.home_team,
                m.away_team
            FROM predictions p
            JOIN matches m ON m.id = p.match_id
            WHERE m.home_goals IS NOT NULL
              AND p.bm_btts_yes_odds IS NULL
            ORDER BY m.league, m.match_date
        """)).fetchall()

        print(f"\nFound {len(rows)} past predictions missing BTTS odds\n")

        # Group by (league, match_date) — one API call per pair
        by_league_date: dict[tuple, list] = defaultdict(list)
        for r in rows:
            by_league_date[(r.league, r.match_date)].append(r)

        print(f"Unique (league, date) pairs: {len(by_league_date)}")
        print(f"Estimated API credits: {len(by_league_date) * 2} (worst case)\n")

        total_updated = total_skipped = 0

        # Group pairs by league to log cleanly
        leagues_done: set = set()
        for (league, match_date), preds in sorted(by_league_date.items()):
            sport_key = LEAGUE_SPORT_KEY.get(league)
            if not sport_key:
                print(f"[{league}] No sport key — skip")
                total_skipped += len(preds)
                continue

            if league not in leagues_done:
                print(f"\n{'─'*60}\n[{league}]  →  {sport_key}")
                leagues_done.add(league)

            print(f"  {match_date}  ({len(preds)} matches)")

            # One API call for this (league, date)
            time.sleep(RATE_LIMIT_SLEEP)
            api_events = _fetch_historical_btts(sport_key, match_date)

            for pred in preds:
                # Find matching event by team name
                matched = None
                for ev in api_events:
                    if (_teams_match(ev["home_team"], pred.home_team) and
                            _teams_match(ev["away_team"], pred.away_team)):
                        matched = ev
                        break

                if not matched:
                    print(f"    [MISS] {pred.home_team} vs {pred.away_team}")
                    total_skipped += 1
                    continue

                yes = matched["yes_odds"]
                no  = matched["no_odds"]
                print(f"    [OK]   {pred.home_team} vs {pred.away_team}  GG={yes}  NG={no}")

                if not args.dry_run:
                    db.execute(text("""
                        UPDATE predictions
                        SET bm_btts_yes_odds = :yes,
                            bm_btts_no_odds  = :no
                        WHERE id = :pred_id
                    """), {"yes": yes, "no": no, "pred_id": pred.pred_id})
                    db.commit()

                total_updated += 1

        print(f"\n{'='*60}")
        print(f"DONE: updated={total_updated}  skipped/unavailable={total_skipped}")
        if args.dry_run:
            print("(DRY RUN — no DB changes written)")

    finally:
        db.close()


if __name__ == "__main__":
    main()
