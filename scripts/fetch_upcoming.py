"""
Fetch real upcoming fixtures from football-data.org and import them into the DB.

Replaces the static fixtures.csv approach with live data from the API.
Supports: EPL, LaLiga, SerieA, Bundesliga, Ligue1
(GreekSL is not available on the free tier)

Usage:
  docker compose exec backend python scripts/fetch_upcoming.py
  docker compose exec backend python scripts/fetch_upcoming.py --days 60
  docker compose exec backend python scripts/fetch_upcoming.py --no-predictions
  docker compose exec backend python scripts/fetch_upcoming.py --key YOUR_TOKEN
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _PROJECT_ROOT)  # project root

# ── Competition config ────────────────────────────────────────────────────────

COMPETITIONS = {
    "PL":  "EPL",
    "ELC": "Championship",
    "PD":  "LaLiga",
    "SA":  "SerieA",
    "BL1": "Bundesliga",
    "FL1": "Ligue1",
    "PPL": "PrimeiraLiga",
    "DED": "Eredivisie",
    "BSA": "BrazilSerieA",
    "CL":  "CL",
}

# ── Team name mapping: API shortName → our CSV/DB name ───────────────────────

TEAM_MAP: dict[str, str] = {
    # Brazil Serie A — football-data.org shortName → football-data.co.uk CSV name
    "Botafogo":         "Botafogo RJ",
    "Chapecoense":      "Chapecoense-SC",
    "Clube do Remo":    "Remo",
    "Flamengo":         "Flamengo RJ",
    "Grêmio":           "Gremio",
    "Mineiro":          "Atletico-MG",     # Atlético Mineiro
    "Paranaense":       "Athletico-PR",    # Athletico Paranaense
    "São Paulo":        "Sao Paulo",
    "Vasco da Gama":    "Vasco",
    "Vitória":          "Vitoria",
    # Premier League
    "Leeds United":     "Leeds",
    "Wolverhampton":    "Wolves",
    "Brighton Hove":    "Brighton",
    "Nottingham":       "Nott'm Forest",
    "Sheffield":        "Sheffield United",
    # All others match exactly (Arsenal, Chelsea, Liverpool, Man City,
    # Man United, Tottenham, Aston Villa, Brentford, Fulham, Newcastle,
    # Bournemouth, Burnley, Crystal Palace, Everton, West Ham, Ipswich,
    # Leicester, Luton, Southampton, Sunderland)

    # La Liga
    "Athletic":         "Ath Bilbao",
    "Atleti":           "Ath Madrid",
    "Barça":            "Barcelona",
    "Espanyol":         "Espanol",
    "Rayo Vallecano":   "Vallecano",
    "Real Betis":       "Betis",
    "Real Sociedad":    "Sociedad",
    "Alavés":           "Alaves",
    "Sevilla FC":       "Sevilla",
    "Real Oviedo":      "Oviedo",
    "UD Las Palmas":    "Las Palmas",
    "CD Leganés":       "Leganes",
    "Granada CF":       "Granada",
    "UD Almería":       "Almeria",
    "Cádiz CF":         "Cadiz",
    "Valladolid":       "Valladolid",

    # Serie A
    "AC Pisa":          "Pisa",
    "Como 1907":        "Como",
    "Venezia FC":       "Venezia",

    # Bundesliga
    "1. FC Köln":       "FC Koln",
    "Bayern":           "Bayern Munich",
    "HSV":              "Hamburg",
    "Bremen":           "Werder Bremen",
    "Frankfurt":        "Ein Frankfurt",
    "St. Pauli":        "St Pauli",
    "Bochum":           "Bochum",
    "Darmstadt":        "Darmstadt",
    "Holstein Kiel":    "Holstein Kiel",

    # Ligue 1
    "Olympique Lyon":   "Lyon",
    "PSG":              "Paris SG",
    "Stade Rennais":    "Rennes",
    "Angers SCO":       "Angers",
    "FC Metz":          "Metz",
    "RC Lens":          "Lens",
    "St Etienne":       "St Etienne",
    "Clermont Foot":    "Clermont",

    # Champions League
    "Bayern München":   "Bayern Munich",
    "Atlético":         "Ath Madrid",
    "Barça":            "Barcelona",
    "Inter":            "Inter",
    "Paris":            "Paris SG",
    "Dortmund":         "Dortmund",
    "Real":             "Real Madrid",
    # NOTE: do NOT map "Milan" → "AC Milan" or "Leverkusen" → "Bayer Leverkusen".
    # This map's direction is API shortName → OUR CSV name, and the CSV name is
    # the short one. Those two entries were inverted: they rewrote a correct name
    # into one that exists nowhere in the training data, so the club was split in
    # two (Leverkusen 99 matches + "Bayer Leverkusen" 6) — a phantom team with no
    # history, hence Elo 1500 and junk predictions for its upcoming fixtures.
    "Ipswich Town":     "Ipswich",

    # Championship — direction is API shortName → CSV name, and the CSVs use the
    # SHORT form. "Coventry"→"Coventry City" / "Hull"→"Hull City" /
    # "Sheffield Wed"→"Sheffield Wednesday" were inverted (same phantom-team bug
    # as Leverkusen/Milan): they rewrote the correct CSV name into one with no
    # history, so the club got Elo 1500 and its league record split in two.
    "Sheffield Wed":    "Sheffield Weds",
    "Sheffield Utd":    "Sheffield United",
    "Middlesbrough":    "Middlesbrough",
    "Coventry City":    "Coventry",
    "Hull City":        "Hull",
    "Preston NE":       "Preston",
    "Lincoln City":     "Lincoln",
    "Derby County":     "Derby",
    "QPR":              "QPR",
    "Millwall":         "Millwall",

    # Primeira Liga
    "Sporting CP":      "Sp Lisbon",
    "FC Porto":         "Porto",
    "SL Benfica":       "Benfica",
    "SC Braga":         "Braga",
    "Vitória SC":       "Vitoria SC",
    "Moreirense FC":    "Moreirense",
    "Gil Vicente":      "Gil Vicente",
    "Famalicão":        "Famalicao",
    "Estoril Praia":    "Estoril",
    "Boavista":         "Boavista",

    # Eredivisie
    "Ajax":             "Ajax",
    "PSV":              "PSV Eindhoven",
    "Feyenoord":        "Feyenoord",
    "AZ":               "AZ Alkmaar",
    "FC Utrecht":       "Utrecht",
    "FC Twente":        "Twente",
    "Vitesse":          "Vitesse",
    "Sparta Rotterdam": "Sparta Rotterdam",
    "NEC":              "NEC Nijmegen",
    "Heerenveen":       "Heerenveen",
    "FC Groningen":     "Groningen",
    "RKC Waalwijk":     "RKC Waalwijk",
    "Almere City":      "Almere City",
    "PEC Zwolle":       "Zwolle",
    "Go Ahead Eagles":  "Go Ahead Eagles",
}


def map_team(short_name: str) -> str:
    return TEAM_MAP.get(short_name, short_name)


def infer_season(d: date) -> str:
    if d.month >= 7:
        return f"{d.year}/{str(d.year + 1)[2:]}"
    return f"{d.year - 1}/{str(d.year)[2:]}"


def fetch_fixtures(api_key: str, days: int) -> list[dict]:
    """Fetch scheduled fixtures for all competitions within the next `days` days."""
    date_from = date.today().isoformat()
    date_to   = (date.today() + timedelta(days=days)).isoformat()
    headers   = {"X-Auth-Token": api_key}
    fixtures  = []

    for code, league in COMPETITIONS.items():
        url = (
            f"https://api.football-data.org/v4/competitions/{code}/matches"
            f"?status=SCHEDULED&dateFrom={date_from}&dateTo={date_to}"
        )
        print(f"  Fetching {league} ({code}) …", end=" ", flush=True)
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 429:
                print("rate limited — waiting 60s …")
                time.sleep(60)
                resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            matches = data.get("matches", [])
            print(f"{len(matches)} fixtures")
            for m in matches:
                # utcDate is an ISO-8601 timestamp like "2026-04-18T15:00:00Z";
                # store both the date and the time (UTC) separately so the
                # frontend can render the kick-off hour.
                try:
                    dt = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
                    dt_utc = dt.astimezone(timezone.utc)
                    match_d = dt_utc.date()
                    match_t = dt_utc.time().replace(microsecond=0)
                except Exception:
                    # Fallback: date only, no time
                    match_d = date.fromisoformat(m["utcDate"][:10])
                    match_t = None

                home = map_team(m["homeTeam"].get("shortName") or "")
                away = map_team(m["awayTeam"].get("shortName") or "")
                if not home or not away:
                    continue  # TBD fixtures (e.g. CL Final before semis played)
                fixtures.append({
                    "match_date":   match_d,
                    "kickoff_time": match_t,
                    "league":       league,
                    "home_team":    home,
                    "away_team":    away,
                    "season":       infer_season(match_d),
                })
        except Exception as e:
            print(f"ERROR: {e}")

        time.sleep(6)  # respect free-tier rate limit (10 req/min)

    return fixtures


def insert_fixtures(db, fixtures: list[dict]) -> tuple[list, set[int]]:
    """Reschedule-aware upsert (shared helper). Returns (new_matches, touched_ids)."""
    from scripts.fixture_upsert import upsert_fixtures
    return upsert_fixtures(db, fixtures)


def compute_predictions(new_matches: list, db):
    """Run ML inference for each new fixture and cache the result."""
    import os
    import pandas as pd
    from backend.app.ml.features import load_raw_csvs
    from backend.app.ml.predict import predict_match
    from backend.app.models.prediction import Prediction

    RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "data", "raw")
    # Try alternate path
    if not os.path.isdir(RAW_DIR):
        RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "raw")

    print(f"  Loading history from {RAW_DIR} …")
    history_df = load_raw_csvs(RAW_DIR)
    print(f"  History: {len(history_df):,} rows")

    # Snapshot all match attrs eagerly — avoids lazy-load after session expires
    # (which would raise ObjectDeletedError if a mid-loop commit fails).
    match_rows = [
        {
            "id":         m.id,
            "home_team":  m.home_team,
            "away_team":  m.away_team,
            "match_date": m.match_date,
            "league":     m.league,
        }
        for m in new_matches
    ]

    ok = 0
    for i, row in enumerate(match_rows, 1):
        try:
            result = predict_match(
                history_df=history_df,
                home_team=row["home_team"],
                away_team=row["away_team"],
                match_date=row["match_date"],
                league=row["league"],
                match_id=row["id"],
            )
            pred = Prediction(
                match_id=row["id"],
                home_win_prob=result["win_probabilities"]["home_win"],
                draw_prob=result["win_probabilities"]["draw"],
                away_win_prob=result["win_probabilities"]["away_win"],
                over_2_5_prob=result["goals"]["over_2_5_probability"],
                goals_prediction=result["goals"]["prediction"],
                model_version=result["model_version"],
                confidence=result["confidence"],
            )
            db.add(pred)
            ok += 1
            if i % 10 == 0:
                try:
                    db.commit()
                except Exception as commit_err:
                    db.rollback()
                    print(f"    [warn] Commit failed at {i}: {commit_err}")
                else:
                    print(f"    {i}/{len(match_rows)} predictions done …")
        except Exception as e:
            db.rollback()
            print(f"    [warn] Prediction failed for match {row['id']} "
                  f"({row['home_team']} vs {row['away_team']}): {e}")

    db.commit()
    print(f"  Predictions complete: {ok}/{len(match_rows)} computed.")


def main():
    parser = argparse.ArgumentParser(description="Fetch real upcoming fixtures from football-data.org")
    parser.add_argument("--key",  default=os.getenv("FOOTBALLDATA_API_KEY", ""),
                        help="API key (or set FOOTBALLDATA_API_KEY env var)")
    parser.add_argument("--days", type=int, default=60,
                        help="How many days ahead to fetch (default: 60)")
    parser.add_argument("--no-predictions", action="store_true",
                        help="Skip ML prediction computation")
    parser.add_argument("--keep-existing", action="store_true",
                        help="Skip pruning unplayed fixtures that vanished from the feed")
    args = parser.parse_args()

    if not args.key:
        print("ERROR: Provide --key or set FOOTBALLDATA_API_KEY env var.")
        sys.exit(1)

    from backend.app.database import SessionLocal

    print(f"\nFetching fixtures for the next {args.days} days …")
    fixtures = fetch_fixtures(args.key, args.days)
    print(f"\nTotal: {len(fixtures)} fixtures fetched across {len(COMPETITIONS)} leagues.\n")

    # These are all top-division leagues we train on, so an unmapped name is a
    # bug (phantom team), not a new minnow — hence domestic=True.
    from scripts.team_resolver import warn_unknown_teams
    warn_unknown_teams(fixtures, domestic=True)

    db = SessionLocal()
    try:
        print("Upserting fixtures (reschedule-aware) …")
        new_matches, touched_ids = insert_fixtures(db, fixtures)

        # Prune unplayed fixtures of the FETCHED leagues that the source feed
        # no longer lists. This replaces the old clear_upcoming(), which
        # deleted every league's upcoming fixtures (cascading away predictions
        # and user-tracked matches) before re-inserting only its own.
        if not args.keep_existing:
            from scripts.fixture_upsert import prune_vanished
            prune_vanished(db, list(COMPETITIONS.values()), touched_ids,
                           horizon_days=args.days)

        if new_matches and not args.no_predictions:
            print(f"\nComputing predictions for {len(new_matches)} new fixtures …")
            compute_predictions(new_matches, db)
        elif args.no_predictions:
            print("\nSkipping predictions (--no-predictions).")
        else:
            print("\nNo new fixtures to predict.")

    finally:
        db.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
