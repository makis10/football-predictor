"""
Download per-match xG (expected goals) data from understat.com for the top-5 leagues.

Data is available from 2014/15 onwards for:
  EPL, La Liga, Serie A, Bundesliga, Ligue 1

Saves one CSV per league-season to backend/data/xg/.
Each file has columns: date, home_team, away_team, home_xg, away_xg, league

Run ONCE (or seasonally to pick up new results):
  docker compose exec backend python scripts/download_xg.py
  docker compose exec backend python scripts/download_xg.py --season 2025

Understat team names will differ from our training-data names — run with
--show-teams after downloading to see the mapping needed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))  # project root

XG_DIR = "/app/backend/data/xg"

# understat league keys → our league code
LEAGUES = {
    "EPL":        "EPL",
    "La liga":    "LaLiga",
    "Serie A":    "SerieA",
    "Bundesliga": "Bundesliga",
    "Ligue 1":    "Ligue1",
}

FIRST_SEASON = 2014   # understat starts from 2014/15
CURRENT_SEASON = 2025  # 2025/26


async def _fetch_league_season(league_key: str, season: int) -> list[dict]:
    """Fetch all match results with xG for one league-season."""
    import aiohttp
    import understat
    async with aiohttp.ClientSession() as session:
        u = understat.Understat(session)
        matches = await u.get_league_results(league_key, season)
    return matches


def download_league_season(league_key: str, league_code: str, season: int) -> pd.DataFrame | None:
    """Download one league-season and return a tidy DataFrame, or None on error."""
    try:
        matches = asyncio.run(_fetch_league_season(league_key, season))
    except Exception as e:
        print(f"    ERROR: {e}")
        return None

    if not matches:
        return None

    rows = []
    for m in matches:
        try:
            rows.append({
                "date":      m["datetime"][:10],      # "YYYY-MM-DD HH:MM:SS" → date
                "home_team": m["h"]["title"],
                "away_team": m["a"]["title"],
                "home_xg":   float(m["xG"]["h"]),
                "away_xg":   float(m["xG"]["a"]),
                "league":    league_code,
                "season":    season,
            })
        except (KeyError, TypeError, ValueError):
            continue

    return pd.DataFrame(rows) if rows else None


def main():
    parser = argparse.ArgumentParser(description="Download xG data from understat.com")
    parser.add_argument(
        "--season", type=int, default=None,
        help=f"Download only this season's start year (e.g. 2024 for 2024/25). "
             f"Default: all seasons from {FIRST_SEASON} to {CURRENT_SEASON}.",
    )
    parser.add_argument(
        "--show-teams", action="store_true",
        help="After downloading, print unique team names per league so you can build the name mapping.",
    )
    args = parser.parse_args()

    try:
        import understat  # noqa: F401
    except ImportError:
        print("ERROR: understat package not installed.")
        print("       Rebuild the container: docker compose up -d --build")
        sys.exit(1)

    os.makedirs(XG_DIR, exist_ok=True)

    seasons = [args.season] if args.season else list(range(FIRST_SEASON, CURRENT_SEASON + 1))

    all_frames = []

    for league_key, league_code in LEAGUES.items():
        print(f"\n{league_code} ({league_key})")
        for season in seasons:
            out_path = os.path.join(XG_DIR, f"{league_code}_{season}.csv")
            if os.path.exists(out_path) and not args.season:
                df_existing = pd.read_csv(out_path)
                print(f"  {season}/{str(season+1)[2:]}  — already downloaded ({len(df_existing)} matches), skipping")
                all_frames.append(df_existing)
                continue

            print(f"  {season}/{str(season+1)[2:]}  … ", end="", flush=True)
            df = download_league_season(league_key, league_code, season)
            if df is not None and len(df) > 0:
                df.to_csv(out_path, index=False)
                print(f"{len(df)} matches saved → {out_path}")
                all_frames.append(df)
            else:
                print("no data / season not started yet")
            time.sleep(1)   # be polite

    if all_frames and args.show_teams:
        combined = pd.concat(all_frames, ignore_index=True)
        print("\n\n=== Team names from understat (to build mapping) ===")
        for league_code in LEAGUES.values():
            subset = combined[combined["league"] == league_code]
            teams = sorted(set(subset["home_team"].tolist() + subset["away_team"].tolist()))
            print(f"\n{league_code}:")
            for t in teams:
                print(f"  {t!r}")

    print("\nDone.")


if __name__ == "__main__":
    main()
