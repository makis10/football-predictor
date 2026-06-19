"""
Download historical match CSVs from football-data.co.uk.

League codes:
  E0  = English Premier League
  E1  = English Championship
  E2  = English League One
  SP1 = Spanish La Liga
  I1  = Italian Serie A
  D1  = German Bundesliga
  F1  = French Ligue 1
  G1  = Greek Super League
  P1  = Portuguese Primeira Liga
  N1  = Dutch Eredivisie

Seasons available: 9394 … current
We download from 1011 (2010/11) through the current season.
Already-completed seasons are skipped unless --refresh-current is passed.

Usage:
  python scripts/download_data.py                  # download all, skip existing
  python scripts/download_data.py --refresh-current # re-download last 2 seasons
                                                    # (picks up new match results)
"""

import argparse
import os
import time
import requests

BASE_URL = "https://www.football-data.co.uk/mmz4281"

LEAGUES = {
    "EPL":          "E0",
    "Championship": "E1",
    "LeagueOne":    "E2",
    "LaLiga":       "SP1",
    "SerieA":       "I1",
    "Bundesliga":   "D1",
    "Ligue1":       "F1",
    "GreekSL":      "G1",
    "PrimeiraLiga": "P1",
    "Eredivisie":   "N1",
}

# Seasons to download (folder name on the site, e.g. "2324" → 2023/24)
# Going back to 2010/11 gives ~15 seasons of training data.
# 2526 = current 2025/26 season (partial — grows during the season).
SEASONS = [
    "1011", "1112", "1213", "1314", "1415",
    "1516", "1617", "1718", "1819", "1920",
    "2021", "2122", "2223", "2324", "2425", "2526",
]

# Seasons that are still live / recently completed — always re-download
# when --refresh-current is passed so we pick up new match results.
CURRENT_SEASONS = {"2425", "2526"}

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "raw")


def download_csv(league_name: str, league_code: str, season: str,
                 force: bool = False) -> bool:
    url = f"{BASE_URL}/{season}/{league_code}.csv"
    filename = f"{league_name}_{season}.csv"
    filepath = os.path.join(RAW_DIR, filename)

    if os.path.exists(filepath) and not force:
        print(f"  [skip]  {filename} already exists")
        return True

    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 404:
            print(f"  [miss]  {url} — not found (season may not exist yet)")
            return False
        resp.raise_for_status()

        with open(filepath, "wb") as f:
            f.write(resp.content)
        tag = "[refresh]" if force and os.path.exists(filepath) else "[ok]"
        print(f"  {tag}    {filename}  ({len(resp.content):,} bytes)")
        return True

    except requests.RequestException as e:
        print(f"  [err]   {filename} — {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Download match CSVs from football-data.co.uk")
    parser.add_argument(
        "--refresh-current", action="store_true",
        help="Re-download the current and previous season CSVs even if they exist "
             "(picks up new match results added during the season).",
    )
    args = parser.parse_args()

    os.makedirs(RAW_DIR, exist_ok=True)
    ok = failed = 0

    for season in SEASONS:
        force = args.refresh_current and season in CURRENT_SEASONS
        print(f"\nSeason {season}{' [REFRESH]' if force else ''}:")
        for league_name, league_code in LEAGUES.items():
            success = download_csv(league_name, league_code, season, force=force)
            if success:
                ok += 1
            else:
                failed += 1
            time.sleep(0.3)  # be polite to the server

    print(f"\nDone — {ok} downloaded/skipped, {failed} failed.")


if __name__ == "__main__":
    main()
