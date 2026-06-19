"""
Poll bookmaker odds for all upcoming matches and store snapshots in odds_history.
Called every 3 hours by launchd (com.football-predictor.odds-poll).

One row per match per poll cycle.  The last two rows per match are compared
by the /predictions/{id}/analysis endpoint to compute movement arrows.
Rows older than 72 hours are pruned to keep the table lean.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.app.database import SessionLocal
from backend.app.models.match import Match
from backend.app.models.odds_history import OddsHistory
from backend.app.ml.odds_analysis_service import (
    fetch_all_league_odds,
    _teams_match,
)

# Only poll matches within this horizon (no point storing odds for matches
# more than 7 days away — the odds aren't reliable that far out anyway).
HORIZON_DAYS = 7
PRUNE_AFTER_HOURS = 72  # delete snapshots older than this


def _lookup(home: str, away: str, league_odds: list) -> dict | None:
    for entry in league_odds:
        if _teams_match(entry["api_home"], home) and \
           _teams_match(entry["api_away"], away):
            ro = entry.get("raw_odds", {})
            if ro.get("home_win") or ro.get("away_win"):
                return ro
    return None


def main() -> None:
    now = datetime.now(timezone.utc)
    horizon = now.date() + timedelta(days=HORIZON_DAYS)
    prune_before = now - timedelta(hours=PRUNE_AFTER_HOURS)

    db = SessionLocal()
    try:
        # Prune old rows first
        deleted = db.query(OddsHistory).filter(
            OddsHistory.fetched_at < prune_before
        ).delete()
        if deleted:
            print(f"Pruned {deleted} stale odds snapshots", flush=True)

        # Upcoming matches within horizon
        upcoming: list[Match] = (
            db.query(Match)
            .filter(
                Match.match_date >= now.date(),
                Match.match_date <= horizon,
                Match.result.is_(None),   # skip already-finished
            )
            .all()
        )

        if not upcoming:
            print("No upcoming matches to poll", flush=True)
            db.commit()
            return

        print(f"Polling odds for {len(upcoming)} upcoming matches …", flush=True)

        # Fetch odds once per league
        leagues = {m.league for m in upcoming}
        odds_by_league: dict[str, list] = {}
        for league in leagues:
            try:
                games = fetch_all_league_odds(league)
                odds_by_league[league] = games
                print(f"  {league}: {len(games)} games", flush=True)
            except Exception as exc:
                print(f"  {league}: error — {exc}", flush=True)
                odds_by_league[league] = []

        # Store a snapshot for each matched game
        stored = 0
        for match in upcoming:
            ro = _lookup(match.home_team, match.away_team,
                         odds_by_league.get(match.league, []))
            if not ro:
                continue

            snapshot = OddsHistory(
                match_id=match.id,
                home_odds=ro.get("home_win"),
                draw_odds=ro.get("draw"),
                away_odds=ro.get("away_win"),
                over_odds=ro.get("over_2_5"),
                fetched_at=now,
            )
            db.add(snapshot)
            stored += 1

        db.commit()
        print(f"Stored {stored} / {len(upcoming)} snapshots", flush=True)

    finally:
        db.close()


if __name__ == "__main__":
    main()
