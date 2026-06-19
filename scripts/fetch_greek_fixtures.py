"""
Fetch upcoming Greek Super League fixtures from The Odds API.

football-data.org does NOT cover Greek SL on the free tier, and football-data.co.uk
CSVs only contain completed matches.  We use The Odds API (already integrated for
odds comparison) which carries the full upcoming schedule for Greek SL.

The script:
  1. Calls GET /v4/sports/soccer_greece_super_league/events  (no odds, just fixtures).
  2. Maps The Odds API team names to our training-data names.
  3. Inserts upcoming fixtures into the DB, skipping duplicates.
  4. Optionally computes ML predictions.

API usage: 1 request per run — well within the 500 req/month free limit.
Safe to run multiple times (idempotent).

Usage (inside the backend container):
  python scripts/fetch_greek_fixtures.py
  python scripts/fetch_greek_fixtures.py --no-predictions
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone

import requests

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _PROJECT_ROOT)

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
    resp = requests.get(url, params=params, timeout=15)
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
    from scripts.fixture_upsert import upsert_fixtures
    new_matches, _ = upsert_fixtures(db, fixtures)
    return new_matches


def compute_predictions(new_matches: list, db):
    """Run ML inference for each new Greek SL fixture."""
    import pandas as pd
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from backend.app.ml.features import load_raw_csvs, build_team_snapshot, compute_match_features, FEATURE_COLS
    from backend.app.ml.predict import _get_models, MODEL_VERSION, _confidence
    from backend.app.models.prediction import Prediction
    from backend.app.ml.odds_analysis_service import fetch_all_league_odds, _teams_match

    RAW_DIR = os.path.join(_PROJECT_ROOT, "backend", "data", "raw")
    print(f"  Loading history …")
    history_df = load_raw_csvs(RAW_DIR)
    snapshot = build_team_snapshot(history_df)
    result_model, goals_model = _get_models()

    # Fetch live odds for GreekSL (one API call; empty list if unavailable)
    greek_odds = fetch_all_league_odds("GreekSL")
    print(f"  GreekSL live odds: {len(greek_odds)} games")

    DEFAULTS = {
        "h_goals_scored_5": 1.5, "h_goals_conceded_5": 1.5,
        "a_goals_scored_5": 1.5, "a_goals_conceded_5": 1.5,
        "h_home_scored_5": 1.5, "h_home_conceded_5": 1.5,
        "a_away_scored_5": 1.5, "a_away_conceded_5": 1.5,
        "h_form_5": 1.0, "a_form_5": 1.0,
        "h_goals_scored_10": 1.5, "h_goals_conceded_10": 1.5,
        "a_goals_scored_10": 1.5, "a_goals_conceded_10": 1.5,
        "h_home_scored_10": 1.5, "h_home_conceded_10": 1.5,
        "a_away_scored_10": 1.5, "a_away_conceded_10": 1.5,
        "h_form_10": 1.0, "a_form_10": 1.0,
        "h_goal_diff_5": 0.0, "a_goal_diff_5": 0.0,
        "h_goal_diff_10": 0.0, "a_goal_diff_10": 0.0,
        "expected_home_goals_5": 1.5, "expected_away_goals_5": 1.5, "expected_goals_5": 3.0,
        "expected_home_goals_10": 1.5, "expected_away_goals_10": 1.5, "expected_goals_10": 3.0,
        "h_total_goals_5": 3.0, "a_total_goals_5": 3.0,
        "h_total_goals_10": 3.0, "a_total_goals_10": 3.0,
        "h_over25_rate_5": 0.5, "a_over25_rate_5": 0.5,
        "h_over25_rate_10": 0.5, "a_over25_rate_10": 0.5,
        "h_shots_ot_5": 0.0, "h_shots_otc_5": 0.0,
        "a_shots_ot_5": 0.0, "a_shots_otc_5": 0.0,
        "h_xg_scored_5": 1.35,   "h_xg_conceded_5": 1.35,
        "a_xg_scored_5": 1.35,   "a_xg_conceded_5": 1.35,
        "h_xg_scored_10": 1.35,  "h_xg_conceded_10": 1.35,
        "a_xg_scored_10": 1.35,  "a_xg_conceded_10": 1.35,
        "market_home_prob": 0.44, "market_draw_prob": 0.27,
        "market_away_prob": 0.29, "market_over_prob": 0.52,
        "h_elo": 1500.0, "a_elo": 1500.0,
        "elo_diff": 0.0, "elo_home_win_prob": 0.5,
        "h_pi_att": 0.0, "h_pi_def": 0.0,
        "a_pi_att": 0.0, "a_pi_def": 0.0,
        "pi_att_diff": 0.0, "pi_def_diff": 0.0,
        "pi_exp_home": 1.5, "pi_exp_away": 1.5,
        "pi_exp_diff": 0.0, "pi_exp_total": 3.0,
        "h2h_home_wins": 0, "h2h_away_wins": 0, "h2h_draws": 0,
        "h_eur_fatigue": 0.0, "a_eur_fatigue": 0.0,
        "h_eur_away": 0.0, "a_eur_away": 0.0,
        "h_eur_result": 0.0, "a_eur_result": 0.0,
    }

    def _lookup_greek_odds(home, away):
        for entry in greek_odds:
            if _teams_match(entry["api_home"], home) and _teams_match(entry["api_away"], away):
                fp = entry["fair_probs"]
                if fp.get("home_win") and fp.get("away_win"):
                    return {"home_win": fp.get("home_win"), "draw": fp.get("draw"),
                            "away_win": fp.get("away_win"), "over_2_5": fp.get("over_2_5")}
        return None

    inserted = 0
    for match in new_matches:
        try:
            live_odds = _lookup_greek_odds(match.home_team, match.away_team)
            feats = compute_match_features(
                snapshot,
                match.home_team,
                match.away_team,
                match.league,
                match.match_date,
                european_df=None,
                market_probs=live_odds,
            )
            feat_row = pd.DataFrame([feats])[FEATURE_COLS].fillna(DEFAULTS)

            result_probs = result_model.predict_proba(feat_row)[0]
            home_win_p = float(result_probs[0])
            draw_p     = float(result_probs[1])
            away_win_p = float(result_probs[2])

            goals_probs = goals_model.predict_proba(feat_row)[0]
            over_p      = float(goals_probs[1])
            goals_pred  = "OVER" if over_p >= 0.5 else "UNDER"
            max_prob    = max(home_win_p, draw_p, away_win_p)

            stmt = pg_insert(Prediction).values(
                match_id=match.id,
                home_win_prob=round(home_win_p, 4),
                draw_prob=round(draw_p, 4),
                away_win_prob=round(away_win_p, 4),
                over_2_5_prob=round(over_p, 4),
                goals_prediction=goals_pred,
                model_version=MODEL_VERSION,
                confidence=_confidence(max_prob, over_p),
            ).on_conflict_do_nothing(index_elements=["match_id"])
            db.execute(stmt)
            inserted += 1
        except Exception as e:
            print(f"    [warn] {match.home_team} vs {match.away_team}: {e}")

    db.commit()
    print(f"  Predictions computed: {inserted} / {len(new_matches)}")


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
        help="Skip ML prediction computation",
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

        if new_matches and not args.no_predictions:
            print(f"\nComputing predictions for {len(new_matches)} new fixtures …")
            compute_predictions(new_matches, db)
        elif args.no_predictions:
            print("Skipping predictions (--no-predictions).")
        else:
            print("No new fixtures to predict.")
    finally:
        db.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
