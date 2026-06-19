"""
Download UEFA Champions League fixtures and results from football-data.org.

Free tier covers the last 3 seasons (2023, 2024, 2025).
EL / Conference League require a paid plan — stub columns are left empty
so the feature layer handles them gracefully as NaN.

Usage:
    FOOTBALLDATA_API_KEY=<token> python scripts/download_european.py
    python scripts/download_european.py --key <token>

Output:
    backend/data/european/CL_<season>.csv  for each accessible season

CSV columns:
    date, competition, stage, home_team, away_team,
    home_goals, away_goals, status
    (home_team / away_team mapped to domestic-league names where possible;
     non-domestic teams left as the API shortName)
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import pandas as pd
import requests

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "european")

# ── Mapping: football-data.org shortName → our CSV team names ────────────────
# Only covers the ~40 teams that appear in our 6 domestic leagues.
# Non-domestic clubs (Porto, Benfica, Ajax, etc.) are kept as-is;
# the feature layer ignores teams it cannot match to a domestic side.
TEAM_MAP: dict[str, str] = {
    # EPL
    "Arsenal":      "Arsenal",
    "Chelsea":      "Chelsea",
    "Liverpool":    "Liverpool",
    "Man City":     "Man City",
    "Man United":   "Man United",
    "Tottenham":    "Tottenham",
    "Newcastle":    "Newcastle",
    "Aston Villa":  "Aston Villa",
    "Brighton":     "Brighton",
    "West Ham":     "West Ham",
    "Wolves":       "Wolves",
    "Fulham":       "Fulham",
    "Brentford":    "Brentford",
    "Everton":      "Everton",
    "Leicester":    "Leicester",
    # LaLiga
    "Barça":        "Barcelona",
    "Real Madrid":  "Real Madrid",
    "Atleti":       "Ath Madrid",
    "Athletic":     "Ath Bilbao",
    "Villarreal":   "Villarreal",
    "Real Sociedad":"Sociedad",
    "Sevilla FC":   "Sevilla",
    "Betis":        "Betis",
    "Valencia":     "Valencia",
    "Osasuna":      "Osasuna",
    "Girona":       "Girona",
    "Celta":        "Celta",
    # Bundesliga
    "Bayern":       "Bayern Munich",
    "Dortmund":     "Dortmund",
    "RB Leipzig":   "RB Leipzig",
    "Leverkusen":   "Leverkusen",
    "Stuttgart":    "Stuttgart",
    "Freiburg":     "Freiburg",
    "Frankfurt":    "Ein Frankfurt",
    "Union Berlin": "Union Berlin",
    "Wolfsburg":    "Wolfsburg",
    "Bremen":       "Werder Bremen",
    "Gladbach":     "M'gladbach",
    "Mainz":        "Mainz",
    "Hoffenheim":   "Hoffenheim",
    "Augsburg":     "Augsburg",
    # Serie A
    "Inter":        "Inter",
    "Milan":        "Milan",
    "Juventus":     "Juventus",
    "Napoli":       "Napoli",
    "Roma":         "Roma",
    "Lazio":        "Lazio",
    "Fiorentina":   "Fiorentina",
    "Atalanta":     "Atalanta",
    "Bologna":      "Bologna",
    "Torino":       "Torino",
    "Udinese":      "Udinese",
    "Monza":        "Monza",
    "Genoa":        "Genoa",
    # Ligue 1
    "PSG":          "Paris SG",
    "Monaco":       "Monaco",
    "Marseille":    "Marseille",
    "RC Lens":      "Lens",
    "Lens":         "Lens",
    "Lille":        "Lille",
    "Nice":         "Nice",
    "Lyon":         "Lyon",
    "Rennes":       "Rennes",
    "Brest":        "Brest",
    "Strasbourg":   "Strasbourg",
    "Reims":        "Reims",
    # Greek SL
    "Olympiakos":   "Olympiakos",
    "PAOK":         "PAOK",
    "AEK":          "AEK",
    "Panathinaikos":"Panathinaikos",
}

COMPETITIONS = {
    "CL": "UEFA Champions League",
    # EL and UECL need a paid plan — leave as stubs for future integration
    # "EL":  "UEFA Europa League",
    # "UECL": "UEFA Conference League",
}

# Seasons the free tier can access (adjust when plan is upgraded)
ACCESSIBLE_SEASONS = [2023, 2024, 2025]


def _map_team(name: str | None) -> str:
    if not name:
        return "Unknown"
    return TEAM_MAP.get(name, name)


def fetch_season(competition: str, season: int, api_key: str) -> list[dict]:
    url = f"https://api.football-data.org/v4/competitions/{competition}/matches?season={season}"
    resp = requests.get(url, headers={"X-Auth-Token": api_key}, timeout=30)
    if resp.status_code == 403:
        print(f"    [restricted] {competition} {season} — not in your plan")
        return []
    if resp.status_code == 404:
        print(f"    [not found]  {competition} {season}")
        return []
    resp.raise_for_status()
    data = resp.json()
    return data.get("matches", [])


def matches_to_df(matches: list[dict], competition: str) -> pd.DataFrame:
    rows = []
    for m in matches:
        home = _map_team(m["homeTeam"].get("shortName"))
        away = _map_team(m["awayTeam"].get("shortName"))
        score = m.get("score", {})
        ft    = score.get("fullTime", {})
        hg    = ft.get("home")
        ag    = ft.get("away")
        rows.append({
            "date":        m["utcDate"][:10],          # YYYY-MM-DD
            "competition": competition,
            "stage":       m.get("stage", ""),
            "home_team":   home,
            "away_team":   away,
            "home_goals":  hg,                         # None if not yet played
            "away_goals":  ag,
            "status":      m.get("status", ""),        # FINISHED / SCHEDULED / etc.
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", default=os.getenv("FOOTBALLDATA_API_KEY", ""),
                        help="football-data.org API token (or set FOOTBALLDATA_API_KEY env var)")
    args = parser.parse_args()

    if not args.key:
        print("[error] Provide an API key via --key or FOOTBALLDATA_API_KEY env var")
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)

    total_rows = 0
    for comp in COMPETITIONS:
        for season in ACCESSIBLE_SEASONS:
            print(f"Fetching {comp} {season}…")
            matches = fetch_season(comp, season, args.key)
            if not matches:
                continue

            df = matches_to_df(matches, comp)
            out = os.path.join(OUT_DIR, f"{comp}_{season}.csv")
            df.to_csv(out, index=False)
            finished = (df["status"] == "FINISHED").sum()
            scheduled = (df["status"] != "FINISHED").sum()
            print(f"    {len(df)} matches saved → {out}  ({finished} played, {scheduled} upcoming)")
            total_rows += len(df)

            time.sleep(6)   # stay within 10 req/min

    print(f"\nDone — {total_rows} total rows written to {OUT_DIR}/")
    print("\nNote: Europa League and Conference League require a paid plan.")
    print("Add 'EL' and 'UECL' to COMPETITIONS once upgraded.")


if __name__ == "__main__":
    main()
