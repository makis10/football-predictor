"""
Parse downloaded CSVs and insert matches + ML predictions into PostgreSQL.

Usage (from repo root):
  python scripts/seed_db.py [--seasons 2324 2425] [--no-predictions]

By default seeds the two most recent complete seasons + generates predictions
for ALL matches (can be slow; pass --no-predictions to skip).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.app.database import Base, SessionLocal, engine
from backend.app.models.match import Match
from backend.app.models.prediction import Prediction

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "raw")

# Map filename prefix → season label from folder code
def _season_label(code: str) -> str:
    """'2324' → '2023/24'"""
    return f"20{code[:2]}/20{code[2:]}" if int(code[:2]) >= 10 else f"20{code[:2]}/{code[2:]}"

LEAGUE_FULL = {
    "EPL":        "English Premier League",
    "LaLiga":     "Spanish La Liga",
    "SerieA":     "Italian Serie A",
    "Bundesliga": "German Bundesliga",
    "Ligue1":     "French Ligue 1",
    "GreekSL":    "Greek Super League",
}


def create_tables():
    Base.metadata.create_all(bind=engine)
    print("Tables created (if not already present).")


def load_csv(path: str, league: str, season_code: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip")
    except Exception as e:
        print(f"  [warn] {path}: {e}")
        return pd.DataFrame()

    rename = {
        "HomeTeam": "home_team", "AwayTeam": "away_team",
        "FTHG": "home_goals",   "FTAG": "away_goals",
        "FTR": "result",
    }
    df = df.rename(columns=rename)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, format="mixed", errors="coerce")
    df = df.dropna(subset=["Date", "home_team", "away_team"])
    df["home_goals"] = pd.to_numeric(df.get("home_goals"), errors="coerce").astype("Int64")
    df["away_goals"] = pd.to_numeric(df.get("away_goals"), errors="coerce").astype("Int64")
    df["result"]     = df.get("result", pd.Series(dtype=str))
    df["league"]     = league
    df["season"]     = _season_label(season_code)
    return df[["Date", "league", "season", "home_team", "away_team",
               "home_goals", "away_goals", "result"]]


def seed_matches(db, rows: pd.DataFrame, season_filter: list[str]) -> list[int]:
    """Insert matches, return list of inserted Match.id values."""
    inserted = []

    for _, r in rows.iterrows():
        # Skip if already present (idempotent)
        existing = (
            db.query(Match)
            .filter_by(
                league=r["league"],
                season=r["season"],
                match_date=r["Date"].date(),
                home_team=r["home_team"],
                away_team=r["away_team"],
            )
            .first()
        )
        if existing:
            inserted.append(existing.id)
            continue

        hg = None if pd.isna(r["home_goals"]) else int(r["home_goals"])
        ag = None if pd.isna(r["away_goals"]) else int(r["away_goals"])
        res = r["result"] if isinstance(r["result"], str) and r["result"] in ("H", "D", "A") else None

        match = Match(
            league=r["league"],
            season=r["season"],
            match_date=r["Date"].date(),
            home_team=r["home_team"],
            away_team=r["away_team"],
            home_goals=hg,
            away_goals=ag,
            result=res,
        )
        db.add(match)
        db.flush()
        inserted.append(match.id)

    db.commit()
    return inserted


def seed_predictions(db, match_ids: list[int], history_df):
    """Compute and store ML predictions for each match id."""
    from backend.app.ml.predict import predict_match

    existing_ids = {
        r[0] for r in db.query(Prediction.match_id).filter(
            Prediction.match_id.in_(match_ids)
        ).all()
    }

    to_predict = [mid for mid in match_ids if mid not in existing_ids]
    print(f"    Generating {len(to_predict)} predictions (skipping {len(existing_ids)} existing)…")

    matches = db.query(Match).filter(Match.id.in_(to_predict)).all()
    batch = []

    for i, m in enumerate(matches, 1):
        try:
            result = predict_match(
                history_df=history_df,
                home_team=m.home_team,
                away_team=m.away_team,
                match_date=m.match_date,
                league=m.league,
                match_id=m.id,
            )
            batch.append(Prediction(
                match_id=m.id,
                home_win_prob=result["win_probabilities"]["home_win"],
                draw_prob=result["win_probabilities"]["draw"],
                away_win_prob=result["win_probabilities"]["away_win"],
                over_2_5_prob=result["goals"]["over_2_5_probability"],
                goals_prediction=result["goals"]["prediction"],
                btts_prob=result["btts"]["gg_probability"],
                btts_prediction=result["btts"]["prediction"],
                poisson_lambda_home=result.get("poisson_lambda_home"),
                poisson_lambda_away=result.get("poisson_lambda_away"),
                model_version=result["model_version"],
                confidence=result["confidence"],
            ))
        except Exception as e:
            print(f"      [warn] match {m.id} ({m.home_team} vs {m.away_team}): {e}")

        if len(batch) >= 500:
            db.bulk_save_objects(batch)
            db.commit()
            batch = []
            print(f"      …{i}/{len(matches)} done")

    if batch:
        db.bulk_save_objects(batch)
        db.commit()
    print(f"    Done — {len(matches)} predictions stored.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="*",
                        help="Season codes to seed, e.g. 2324 2425. Default: all downloaded.")
    parser.add_argument("--no-predictions", action="store_true",
                        help="Skip generating ML predictions.")
    args = parser.parse_args()

    create_tables()

    import glob
    csv_files = sorted(glob.glob(os.path.join(RAW_DIR, "*.csv")))
    if not csv_files:
        print("No CSV files found. Run scripts/download_data.py first.")
        sys.exit(1)

    # Group by season code
    season_map: dict[str, list[str]] = {}
    for path in csv_files:
        base = os.path.basename(path)          # e.g. EPL_2324.csv
        parts = base.replace(".csv", "").split("_")
        if len(parts) == 2:
            league, season_code = parts
            season_map.setdefault(season_code, []).append((league, path))

    if args.seasons:
        season_map = {k: v for k, v in season_map.items() if k in args.seasons}

    print(f"Seeding {len(season_map)} season(s): {sorted(season_map)}")

    # Load history for predictions (used globally)
    if not args.no_predictions:
        from backend.app.ml.features import load_raw_csvs
        print("Loading full history for ML features…")
        history_df = load_raw_csvs(RAW_DIR)
        print(f"  {len(history_df):,} historical matches loaded.")
    else:
        history_df = None

    db = SessionLocal()
    try:
        for season_code in sorted(season_map):
            print(f"\nSeason {season_code}:")
            all_ids = []
            for league, path in season_map[season_code]:
                rows = load_csv(path, league, season_code)
                if rows.empty:
                    continue
                ids = seed_matches(db, rows, [season_code])
                print(f"  {league}: {len(rows)} rows → {len(ids)} matches in DB")
                all_ids.extend(ids)

            if not args.no_predictions and all_ids and history_df is not None:
                seed_predictions(db, all_ids, history_df)
    finally:
        db.close()

    print("\nSeed complete.")


if __name__ == "__main__":
    main()
