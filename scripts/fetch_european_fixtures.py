"""
Fetch upcoming UEFA competition fixtures (CL / EL / ECL) and add predictions.

Sources:
  • Champions League  — European CSVs already downloaded by download_european.py
                        (football-data.org free tier covers CL)
  • Europa League     — The Odds API  (soccer_uefa_europa_league)
  • Conference League — The Odds API  (soccer_uefa_europa_conference_league)

Team names are mapped to our domestic training-data names where possible.
Teams not in our training data (Porto, Sporting CP, etc.) use default features;
predictions for those matches are lower-quality but still show the
domestic-league team's relative strength.

Usage:
  docker compose exec backend python scripts/fetch_european_fixtures.py
  docker compose exec backend python scripts/fetch_european_fixtures.py --no-predictions
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone

import pandas as pd

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _PROJECT_ROOT)

from scripts._http_retry import get_with_retry  # noqa: E402

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

EUROPEAN_DIR = os.path.join(_PROJECT_ROOT, "backend", "data", "european")

# ── Team name mappings: external name → our training-data name ────────────────
# Only covers teams we have domestic data for. Unmapped teams keep their name;
# the feature engine will use default (neutral) stats for them.
TEAM_MAP: dict[str, str] = {
    # EL
    "SC Freiburg":       "Freiburg",
    "Nottingham Forest": "Nott'm Forest",
    "Real Betis":        "Betis",
    "Celta Vigo":        "Celta",
    "Aston Villa":       "Aston Villa",
    "Bologna":           "Bologna",
    # ECL
    "AEK Athens":        "AEK",
    "Rayo Vallecano":    "Vallecano",
    "Fiorentina":        "Fiorentina",
    "Crystal Palace":    "Crystal Palace",
    "Strasbourg":        "Strasbourg",
    "FSV Mainz 05":      "Mainz",
    # CL teams already mapped in download_european.py / European CSVs
    # (Bayern Munich, Real Madrid, Arsenal, etc. already correct)
}

ODDS_API_COMPETITIONS = {
    "EL":  "soccer_uefa_europa_league",
    "ECL": "soccer_uefa_europa_conference_league",
}


def map_team(name: str) -> str:
    return TEAM_MAP.get(name, name)


def infer_season(d: date) -> str:
    if d.month >= 7:
        return f"{d.year}/{str(d.year + 1)[2:]}"
    return f"{d.year - 1}/{str(d.year)[2:]}"


# ── CL: read from European CSVs ───────────────────────────────────────────────

def fetch_cl_fixtures() -> list[dict]:
    """Read upcoming CL matches from the European data directory."""
    frames = []
    for fname in os.listdir(EUROPEAN_DIR):
        if fname.startswith("CL_") and fname.endswith(".csv"):
            try:
                df = pd.read_csv(os.path.join(EUROPEAN_DIR, fname))
                frames.append(df)
            except Exception as e:
                print(f"  [warn] Could not read {fname}: {e}")

    if not frames:
        print("  No CL CSV files found in", EUROPEAN_DIR)
        return []

    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    today = pd.Timestamp(date.today())

    # Upcoming = no score yet AND not Unknown (semi/final TBD)
    upcoming = df[
        (df["status"] != "FINISHED") &
        (df["date"] >= today) &
        (df["home_team"] != "Unknown") &
        (df["away_team"] != "Unknown")
    ].copy()

    print(f"  CL: {len(upcoming)} upcoming fixture(s) from CSVs")
    fixtures = []
    for _, row in upcoming.iterrows():
        match_date = row["date"].date()
        fixtures.append({
            "match_date": match_date,
            "league":     "CL",
            "home_team":  row["home_team"],
            "away_team":  row["away_team"],
            "season":     infer_season(match_date),
        })
    return fixtures


# ── EL / ECL: fetch from The Odds API ─────────────────────────────────────────

def fetch_odds_api_fixtures(league_code: str, sport_key: str, api_key: str) -> list[dict]:
    """Fetch upcoming fixtures from The Odds API for a given competition."""
    url = f"{ODDS_API_BASE}/sports/{sport_key}/events"
    try:
        resp = get_with_retry(url, params={"apiKey": api_key}, timeout=15)
        resp.raise_for_status()
        events = resp.json()
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"  {league_code}: {len(events)} fixture(s) from The Odds API  (quota: {remaining})")
    except Exception as e:
        print(f"  {league_code}: ERROR fetching from Odds API — {e}")
        return []

    today = date.today()
    fixtures = []
    for event in events:
        try:
            dt = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
            dt_utc = dt.astimezone(timezone.utc)
            match_date = dt_utc.date()
            match_time = dt_utc.time().replace(microsecond=0)
        except Exception:
            continue
        if match_date < today:
            continue
        home = map_team(event["home_team"])
        away = map_team(event["away_team"])
        fixtures.append({
            "match_date":   match_date,
            "kickoff_time": match_time,
            "league":       league_code,
            "home_team":    home,
            "away_team":    away,
            "season":       infer_season(match_date),
        })
    return fixtures


# ── DB helpers ────────────────────────────────────────────────────────────────

def insert_fixtures(db, fixtures: list[dict]) -> list:
    """Reschedule-aware upsert via the shared helper. Returns new Match objects.

    No pruning here: the CSV/Odds-API feeds are partial windows, so absence
    from the feed doesn't mean cancelled."""
    from scripts.fixture_upsert import upsert_fixtures
    new_matches, _ = upsert_fixtures(db, fixtures)
    return new_matches


def compute_predictions(new_matches: list, db):
    import pandas as pd
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from backend.app.ml.features import load_raw_csvs, build_team_snapshot, compute_match_features, FEATURE_COLS
    from backend.app.ml.predict import _get_models, MODEL_VERSION, confidence_for
    from backend.app.models.prediction import Prediction
    from backend.app.ml.odds_analysis_service import fetch_all_league_odds, _teams_match

    RAW_DIR = os.path.join(_PROJECT_ROOT, "backend", "data", "raw")
    print("  Loading history …", flush=True)
    history_df = load_raw_csvs(RAW_DIR)
    snapshot = build_team_snapshot(history_df)
    result_model, goals_model = _get_models()

    # Fetch live odds per European league (one call each; CL returns [])
    eur_leagues = list({m.league for m in new_matches})
    eur_league_odds: dict[str, list] = {}
    for lg in eur_leagues:
        games = fetch_all_league_odds(lg)
        eur_league_odds[lg] = games
        print(f"  {lg} live odds: {len(games)} games", flush=True)

    def _lookup_eur_odds(league, home, away):
        for entry in eur_league_odds.get(league, []):
            if _teams_match(entry["api_home"], home) and _teams_match(entry["api_away"], away):
                fp = entry["fair_probs"]
                if fp.get("home_win") and fp.get("away_win"):
                    return {"home_win": fp.get("home_win"), "draw": fp.get("draw"),
                            "away_win": fp.get("away_win"), "over_2_5": fp.get("over_2_5")}
        return None

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

    inserted = 0
    for match in new_matches:
        try:
            live_odds = _lookup_eur_odds(match.league, match.home_team, match.away_team)
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
                confidence=confidence_for(match.league, max_prob, over_p),
            ).on_conflict_do_nothing(index_elements=["match_id"])
            db.execute(stmt)
            inserted += 1
            print(f"    ✓ {match.home_team} vs {match.away_team} ({match.league})", flush=True)
        except Exception as e:
            print(f"    [warn] {match.home_team} vs {match.away_team}: {e}")

    db.commit()
    print(f"  Predictions: {inserted} / {len(new_matches)} computed")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch upcoming CL / EL / ECL fixtures and compute predictions"
    )
    parser.add_argument(
        "--odds-key",
        default=os.getenv("ODDS_API_KEY", ""),
        help="The Odds API key for EL/ECL (or set ODDS_API_KEY in .env)",
    )
    parser.add_argument(
        "--no-predictions", action="store_true",
        help="Skip ML prediction computation",
    )
    args = parser.parse_args()

    from backend.app.database import SessionLocal
    db = SessionLocal()

    all_new: list = []

    try:
        # ── Champions League (from European CSVs) ──────────────────────────────
        print("\nFetching Champions League fixtures …")
        cl_fixtures = fetch_cl_fixtures()
        if cl_fixtures:
            new = insert_fixtures(db, cl_fixtures)
            all_new.extend(new)

        # ── Europa League + Conference League (The Odds API) ───────────────────
        if args.odds_key:
            for code, sport_key in ODDS_API_COMPETITIONS.items():
                print(f"\nFetching {code} fixtures …")
                fixtures = fetch_odds_api_fixtures(code, sport_key, args.odds_key)
                if fixtures:
                    new = insert_fixtures(db, fixtures)
                    all_new.extend(new)
        else:
            print("\n[skip] EL/ECL: no ODDS_API_KEY available")

        # ── Compute predictions ────────────────────────────────────────────────
        if all_new and not args.no_predictions:
            print(f"\nComputing predictions for {len(all_new)} new fixture(s) …")
            compute_predictions(all_new, db)
        elif args.no_predictions:
            print("\nSkipping predictions (--no-predictions).")
        else:
            print("\nNo new fixtures inserted.")

    finally:
        db.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
