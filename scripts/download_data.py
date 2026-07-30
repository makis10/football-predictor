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
    # Added 2026-07-30 so UEFA qualifying ties stop landing on "Insufficient
    # data". Names are COUNTRY-based on purpose: the local names collide with
    # leagues we already carry (Austria's top flight is also "Bundesliga",
    # Denmark's and Romania's are both "Superliga"), and load_raw_csvs() keys
    # the league off the filename prefix.
    "Belgium":      "B1",
    "Turkey":       "T1",
    "Scotland":     "SC0",
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


# ── "New leagues" (football-data.co.uk /new/) — one growing file per country ──
# Different schema: Country,League,Season,Date,Time,Home,Away,HG,AG,Res + odds
# columns (PSCH/PSCD/PSCA = Pinnacle closing). No shots / cards / referee.
# Seasons are CALENDAR years (Brazil plays Apr–Dec). We convert to our per-season
# file layout + main-league column names so load_raw_csvs() ingests it unchanged.
#
# `division` is required whenever the country file carries more than one tier —
# SWZ.csv holds both "Super League" and "Challenge League", and without the
# filter the second division would be silently folded into the same club
# histories. Values are compared stripped: several files carry a trailing space
# ("Superliga ", "Allsvenskan ") on some rows and not others.
#
# `season` says how the upstream Season column is written. Both shapes are in
# play — summer leagues use a calendar year ("2024"), winter leagues a split
# year ("2024/2025") — and the original converter accepted only digits, so a
# split-season country would have parsed to ZERO rows without a word of warning.
NEW_LEAGUES = {
    "BrazilSerieA": {"url": "https://www.football-data.co.uk/new/BRA.csv", "season": "calendar"},
    "Denmark":      {"url": "https://www.football-data.co.uk/new/DNK.csv", "season": "split",
                     "division": "Superliga"},
    "Sweden":       {"url": "https://www.football-data.co.uk/new/SWE.csv", "season": "calendar",
                     "division": "Allsvenskan"},
    "Norway":       {"url": "https://www.football-data.co.uk/new/NOR.csv", "season": "calendar",
                     "division": "Eliteserien"},
    "Poland":       {"url": "https://www.football-data.co.uk/new/POL.csv", "season": "split",
                     "division": "Ekstraklasa"},
    "Austria":      {"url": "https://www.football-data.co.uk/new/AUT.csv", "season": "split",
                     "division": "Bundesliga"},
    "Switzerland":  {"url": "https://www.football-data.co.uk/new/SWZ.csv", "season": "split",
                     "division": "Super League"},
    "Romania":      {"url": "https://www.football-data.co.uk/new/ROU.csv", "season": "split",
                     "division": "Superliga"},
    "Ireland":      {"url": "https://www.football-data.co.uk/new/IRL.csv", "season": "calendar",
                     "division": "Premier Division"},
    "Finland":      {"url": "https://www.football-data.co.uk/new/FIN.csv", "season": "calendar",
                     "division": "Veikkausliiga"},
}
NEW_MIN_SEASON = 2012


def _parse_new_season(raw: str, mode: str) -> str | None:
    """Upstream Season → our filename suffix, or None to skip the row.

    calendar: "2024"      → "2024"   (summer leagues: Brazil, Scandinavia, …)
    split:    "2024/2025"  → "2425"   (winter leagues — matches the main-set
                                       naming already on disk, e.g. EPL_2425)
    """
    raw = (raw or "").strip()
    if mode == "calendar":
        return raw if raw.isdigit() and int(raw) >= NEW_MIN_SEASON else None
    start, _, end = raw.partition("/")
    if not (start.isdigit() and end.isdigit()):
        return None
    if int(start) < NEW_MIN_SEASON:
        return None
    return f"{start[-2:]}{end[-2:]}"


def download_new_league(league_name: str, spec: dict) -> bool:
    """Download a /new/-format CSV and split it into per-season files in the
    main-league schema (BrazilSerieA_2024.csv, …). Always refreshed — the
    upstream file grows in place, and one 600 KB download is cheap."""
    import csv
    import io

    url = spec["url"]
    season_mode = spec.get("season", "calendar")
    division = spec.get("division")

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [err]   {league_name} — {e}")
        return False

    text = resp.content.decode("utf-8-sig", errors="replace")
    by_season: dict[str, list[dict]] = {}
    skipped_division = 0
    for row in csv.DictReader(io.StringIO(text)):
        # Trailing spaces appear on some rows only — compare stripped.
        if division and (row.get("League") or "").strip() != division:
            skipped_division += 1
            continue
        season = _parse_new_season(row.get("Season", ""), season_mode)
        if season is None:
            continue
        if not (row.get("Home") and row.get("Away") and row.get("Res")):
            continue  # unplayed / malformed row
        by_season.setdefault(season, []).append({
            "Date":     row.get("Date", ""),
            "HomeTeam": row["Home"].strip(),
            "AwayTeam": row["Away"].strip(),
            "FTHG":     row.get("HG", ""),
            "FTAG":     row.get("AG", ""),
            "FTR":      row.get("Res", ""),
            # Pinnacle closing 1×2 → our PSH/PSD/PSA slots (pre-kickoff prices)
            "PSH":      row.get("PSCH", ""),
            "PSD":      row.get("PSCD", ""),
            "PSA":      row.get("PSCA", ""),
        })

    fields = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "PSH", "PSD", "PSA"]
    for season, rows in sorted(by_season.items()):
        filepath = os.path.join(RAW_DIR, f"{league_name}_{season}.csv")
        with open(filepath, "w", newline="", encoding="latin-1", errors="replace") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    total = sum(len(r) for r in by_season.values())
    if total == 0:
        # Loud, because the failure mode this guards is silence: a changed
        # Season format or a renamed division writes no files and the league
        # simply never appears in training.
        print(f"  [ERR]   {league_name}: 0 matches parsed — check the "
              f"'season'/'division' spec against {url}")
        return False
    extra = f", {skipped_division:,} rows in other divisions" if skipped_division else ""
    print(f"  [ok]    {league_name}: {total:,} matches → {len(by_season)} season files{extra}")
    return True


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

    print("\nNew-format leagues (always refreshed):")
    for league_name, spec in NEW_LEAGUES.items():
        if download_new_league(league_name, spec):
            ok += 1
        else:
            failed += 1
        time.sleep(0.3)

    print(f"\nDone — {ok} downloaded/skipped, {failed} failed.")


if __name__ == "__main__":
    main()
