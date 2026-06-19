"""
Backfill the martj42 results.csv with settled results we already know from the
DB (via the live-scores fallback) but that martj42 hasn't published yet.

Why: train_national.py and the Elo snapshot are built from results.csv. martj42
is volunteer-maintained and lags ~1 day, so without this the "daily retrain"
would train on stale data missing yesterday's matches — defeating the
self-correction the tournament needs. This writes the scores we filled into
national_predictions back into results.csv so the retrain sees every result.

Idempotent. Runs after fetch_international_data.py --force (which overwrites
results.csv with the upstream copy) and before train_national.py. Matches on
(date, home, away) with reversed-orientation + ±1-day fallback, consistent with
update_national_results.py.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "data" / "raw" / "international"
RESULTS  = DATA_DIR / "results.csv"

sys.path.insert(0, str(ROOT))


def main() -> None:
    from backend.app.database import SessionLocal
    from backend.app.models.national_prediction import NationalPrediction

    df = pd.read_csv(RESULTS)
    df["_d"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")

    # Index rows missing a score for fast lookup: (date, home, away) -> df index
    missing = df[df["home_score"].isna() | df["away_score"].isna()]
    idx: dict[tuple, int] = {}
    for i, r in missing.iterrows():
        idx[(r["_d"], r["home_team"], r["away_team"])] = i

    db = SessionLocal()
    try:
        # Only recent settled results are worth syncing (older ones are already
        # in martj42); keep it cheap.
        cutoff = (date.today() - timedelta(days=10)).isoformat()
        settled = db.query(NationalPrediction).filter(
            NationalPrediction.actual_result.isnot(None),
            NationalPrediction.match_date >= cutoff,
        ).all()
    finally:
        db.close()

    def _find(p) -> "int | None":
        base = date.fromisoformat(p.match_date)
        for delta in (0, 1, -1):
            d = (base + timedelta(days=delta)).isoformat()
            if (d, p.home_team, p.away_team) in idx:
                return idx[(d, p.home_team, p.away_team)]
            if (d, p.away_team, p.home_team) in idx:        # reversed → mark swap
                return -idx[(d, p.away_team, p.home_team)] - 1
        return None

    written = 0
    for p in settled:
        loc = _find(p)
        if loc is None:
            continue
        swap = loc < 0
        i = (-loc - 1) if swap else loc
        hg, ag = p.actual_home_goals, p.actual_away_goals
        if hg is None or ag is None:
            continue
        df.at[i, "home_score"] = ag if swap else hg
        df.at[i, "away_score"] = hg if swap else ag
        written += 1

    if written:
        df.drop(columns="_d").to_csv(RESULTS, index=False)
    print(f"✓ Synced {written} settled result(s) from DB into results.csv")


if __name__ == "__main__":
    main()
