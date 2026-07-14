"""
Update match results for fixtures that have been played.

Fetches FINISHED matches from football-data.org for each league and updates
the DB rows that still have result=NULL but match_date < today.

Safe to run multiple times (idempotent).

Usage:
  docker compose exec backend python scripts/update_results.py
  docker compose exec backend python scripts/update_results.py --days-back 14
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))  # project root

COMPETITIONS = {
    "PL":  "EPL",
    "PD":  "LaLiga",
    "SA":  "SerieA",
    "BL1": "Bundesliga",
    "FL1": "Ligue1",
    "CL":  "CL",     # UEFA Champions League — free tier on football-data.org
    "ELC": "Championship",
    "PPL": "PrimeiraLiga",
    "DED": "Eredivisie",
    "BSA": "BrazilSerieA",
}

# Same team name mapping as fetch_upcoming.py
TEAM_MAP: dict[str, str] = {
    # Brazil Serie A — football-data.org shortName → football-data.co.uk CSV name
    "Botafogo":       "Botafogo RJ",
    "Chapecoense":    "Chapecoense-SC",
    "Clube do Remo":  "Remo",
    "Flamengo":       "Flamengo RJ",
    "Grêmio":         "Gremio",
    "Mineiro":        "Atletico-MG",
    "Paranaense":     "Athletico-PR",
    "São Paulo":      "Sao Paulo",
    "Vasco da Gama":  "Vasco",
    "Vitória":        "Vitoria",
    "Leeds United":   "Leeds",
    "Wolverhampton":  "Wolves",
    "Brighton Hove":  "Brighton",
    "Nottingham":     "Nott'm Forest",
    "Sheffield":      "Sheffield United",
    "Athletic":       "Ath Bilbao",
    "Atleti":         "Ath Madrid",
    "Barça":          "Barcelona",
    "Espanyol":       "Espanol",
    "Rayo Vallecano": "Vallecano",
    "Real Betis":     "Betis",
    "Real Sociedad":  "Sociedad",
    "Alavés":         "Alaves",
    "Sevilla FC":     "Sevilla",
    "Real Oviedo":    "Oviedo",
    "UD Las Palmas":  "Las Palmas",
    "CD Leganés":     "Leganes",
    "Milan":          "AC Milan",
    "AC Pisa":        "Pisa",
    "Como 1907":      "Como",
    "Venezia FC":     "Venezia",
    "1. FC Köln":     "FC Koln",
    "Bayern":         "Bayern Munich",
    "Leverkusen":     "Bayer Leverkusen",
    "HSV":            "Hamburg",
    "Bremen":         "Werder Bremen",
    "Frankfurt":      "Ein Frankfurt",
    "St. Pauli":      "St Pauli",
    "Olympique Lyon": "Lyon",
    "PSG":            "Paris SG",
    "Stade Rennais":  "Rennes",
    "Angers SCO":     "Angers",
    "FC Metz":        "Metz",
    "RC Lens":        "Lens",
    "St Etienne":     "St Etienne",
    "Clermont Foot":  "Clermont",
    # Championship
    "Sheffield Wed":  "Sheffield Wednesday",
    "Coventry":       "Coventry City",
    "Hull":           "Hull City",
    # Primeira Liga
    "Sporting CP":    "Sp Lisbon",
    "FC Porto":       "Porto",
    "SL Benfica":     "Benfica",
    "SC Braga":       "Braga",
    "Vitória SC":     "Vitoria SC",
    "Moreirense FC":  "Moreirense",
    "Famalicão":      "Famalicao",
    "Estoril Praia":  "Estoril",
    # Eredivisie
    "PSV":            "PSV Eindhoven",
    "AZ":             "AZ Alkmaar",
    "FC Utrecht":     "Utrecht",
    "FC Twente":      "Twente",
    "Sparta Rotterdam": "Sparta",
    "NEC":            "NEC Nijmegen",
    "Almere City FC": "Almere City",
    "RKC":            "RKC Waalwijk",
    "PEC Zwolle":     "Zwolle",
    "Fortuna Sittard": "Sittard",
    "FC Volendam":    "Volendam",
}


def map_team(short_name: str) -> str:
    return TEAM_MAP.get(short_name, short_name)


def fetch_finished(api_key: str, days_back: int) -> list[dict]:
    """Fetch finished matches from the last `days_back` days for all competitions."""
    date_to   = date.today().isoformat()
    date_from = (date.today() - timedelta(days=days_back)).isoformat()
    headers   = {"X-Auth-Token": api_key}
    results   = []

    for code, league in COMPETITIONS.items():
        url = (
            f"https://api.football-data.org/v4/competitions/{code}/matches"
            f"?status=FINISHED&dateFrom={date_from}&dateTo={date_to}"
        )
        print(f"  Fetching {league} results ({code}) …", end=" ", flush=True)
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 429:
                print("rate limited — waiting 65s …")
                time.sleep(65)
                resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            matches = resp.json().get("matches", [])
            print(f"{len(matches)} finished")
            for m in matches:
                score = m.get("score", {}).get("fullTime", {})
                hg = score.get("home")
                ag = score.get("away")
                if hg is None or ag is None:
                    continue
                match_date = m["utcDate"][:10]
                home = map_team(m["homeTeam"]["shortName"])
                away = map_team(m["awayTeam"]["shortName"])
                if hg > ag:
                    result = "H"
                elif hg == ag:
                    result = "D"
                else:
                    result = "A"
                results.append({
                    "match_date": date.fromisoformat(match_date),
                    "league":     league,
                    "home_team":  home,
                    "away_team":  away,
                    "home_goals": int(hg),
                    "away_goals": int(ag),
                    "result":     result,
                })
        except Exception as e:
            print(f"ERROR: {e}")

        time.sleep(6)  # free-tier rate limit: 10 req/min

    return results


def update_db(finished: list[dict]) -> tuple[int, int]:
    """
    Update match rows that have result=NULL.
    Returns (updated, not_found).
    """
    from sqlalchemy import select
    from backend.app.database import SessionLocal
    from backend.app.models.match import Match

    db = SessionLocal()
    updated = not_found = 0
    try:
        for f in finished:
            match = db.scalars(
                select(Match).where(
                    Match.match_date == f["match_date"],
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
    parser = argparse.ArgumentParser(description="Update past match results from football-data.org")
    parser.add_argument(
        "--key",
        default=os.getenv("API_FOOTBALL_KEY", os.getenv("FOOTBALLDATA_API_KEY", "")),
        help="football-data.org API key",
    )
    parser.add_argument(
        "--days-back", type=int, default=7,
        help="How many days back to look for finished matches (default: 7)",
    )
    args = parser.parse_args()

    if not args.key:
        print("ERROR: Set API_FOOTBALL_KEY in .env or pass --key.")
        sys.exit(1)

    print(f"\nFetching finished matches (last {args.days_back} days) …")
    finished = fetch_finished(args.key, args.days_back)
    print(f"\nTotal finished matches fetched: {len(finished)}")

    print("\nUpdating database …")
    updated, not_found = update_db(finished)
    print(f"  Updated:   {updated} matches")
    print(f"  Not found: {not_found} (already updated or not in our DB)")
    print("\nDone.")


if __name__ == "__main__":
    main()
