"""
Import upcoming fixture CSV into the database as matches with no result,
then optionally pre-compute ML predictions for each fixture.

The CSV must have columns: date, league, home_team, away_team
Date format: YYYY-MM-DD

Usage:
  docker compose exec backend python scripts/import_fixtures.py
  docker compose exec backend python scripts/import_fixtures.py --file backend/data/fixtures.csv
  docker compose exec backend python scripts/import_fixtures.py --clear-future  # delete existing upcoming rows first
  docker compose exec backend python scripts/import_fixtures.py --no-predictions  # skip ML step

The season is inferred automatically from the match date (e.g. April 2026 → "2025/26").
Predictions are pre-computed sequentially (not in parallel) to avoid overloading the ML pipeline.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.app.database import SessionLocal
from backend.app.models.match import Match

DEFAULT_FILE = os.path.join(
    os.path.dirname(__file__), "..", "backend", "data", "fixtures.csv"
)

VALID_LEAGUES = {"EPL", "LaLiga", "SerieA", "Bundesliga", "Ligue1", "GreekSL"}


def infer_season(d: date) -> str:
    """2026-04-18 → '2025/26'"""
    if d.month >= 7:
        return f"{d.year}/{str(d.year + 1)[2:]}"
    else:
        return f"{d.year - 1}/{str(d.year)[2:]}"


def _compute_predictions(match_ids: list[int]) -> None:
    """Pre-warm the predictions cache for the given match IDs (sequential)."""
    from backend.app.ml.features import load_raw_csvs
    from backend.app.ml.predict import predict_match
    from backend.app.models.match import Match
    from backend.app.models.prediction import Prediction

    RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "raw")
    print("Loading history for ML features…")
    history_df = load_raw_csvs(RAW_DIR)
    print(f"  {len(history_df):,} historical rows loaded.")

    db = SessionLocal()
    try:
        existing_ids = {
            r[0] for r in db.query(Prediction.match_id)
            .filter(Prediction.match_id.in_(match_ids)).all()
        }
        to_predict = [mid for mid in match_ids if mid not in existing_ids]
        print(f"  Computing {len(to_predict)} predictions (skipping {len(existing_ids)} cached)…")

        matches = db.query(Match).filter(Match.id.in_(to_predict)).all()
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
                db.add(Prediction(
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
                if i % 10 == 0:
                    db.commit()
                    print(f"    {i}/{len(matches)} done…")
            except Exception as e:
                print(f"    [warn] match {m.id} ({m.home_team} vs {m.away_team}): {e}")
        db.commit()
        print(f"  Predictions complete.")
    finally:
        db.close()


def import_fixtures(path: str, clear_future: bool = False, with_predictions: bool = True) -> None:
    df = pd.read_csv(path)
    required = {"date", "league", "home_team", "away_team"}
    missing = required - set(df.columns)
    if missing:
        print(f"[error] CSV is missing columns: {missing}")
        sys.exit(1)

    df["date"] = pd.to_datetime(df["date"]).dt.date
    today = date.today()

    invalid_leagues = set(df["league"].unique()) - VALID_LEAGUES
    if invalid_leagues:
        print(f"[warn] Unknown leagues will be skipped: {invalid_leagues}")
    df = df[df["league"].isin(VALID_LEAGUES)]

    db = SessionLocal()
    inserted = skipped = 0
    new_ids: list[int] = []

    try:
        if clear_future:
            deleted = (
                db.query(Match)
                .filter(Match.result.is_(None), Match.match_date >= today)
                .delete()
            )
            db.commit()
            print(f"Cleared {deleted} existing upcoming fixtures.")

        for _, row in df.iterrows():
            match_date = row["date"]
            league     = row["league"]
            home_team  = str(row["home_team"]).strip()
            away_team  = str(row["away_team"]).strip()
            season     = infer_season(match_date)

            # Skip past dates
            if match_date < today:
                print(f"  [skip] {match_date} {home_team} vs {away_team} — date is in the past")
                skipped += 1
                continue

            # Idempotent — skip if already present
            exists = (
                db.query(Match)
                .filter_by(
                    league=league,
                    match_date=match_date,
                    home_team=home_team,
                    away_team=away_team,
                )
                .first()
            )
            if exists:
                skipped += 1
                continue

            m = Match(
                league=league,
                season=season,
                match_date=match_date,
                home_team=home_team,
                away_team=away_team,
                home_goals=None,
                away_goals=None,
                result=None,
            )
            db.add(m)
            db.flush()          # populate m.id before commit
            new_ids.append(m.id)
            inserted += 1

        db.commit()
        print(f"Done — {inserted} fixtures inserted, {skipped} skipped.")
    finally:
        db.close()

    if with_predictions and new_ids:
        print(f"\nPre-computing predictions for {len(new_ids)} new fixtures…")
        _compute_predictions(new_ids)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=DEFAULT_FILE, help="Path to fixtures CSV")
    parser.add_argument(
        "--clear-future",
        action="store_true",
        help="Delete all existing upcoming (result=NULL) rows before import",
    )
    parser.add_argument(
        "--no-predictions",
        action="store_true",
        help="Skip pre-computing ML predictions after import",
    )
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"[error] File not found: {args.file}")
        sys.exit(1)

    print(f"Importing from {args.file} …")
    import_fixtures(
        args.file,
        clear_future=args.clear_future,
        with_predictions=not args.no_predictions,
    )


if __name__ == "__main__":
    main()
