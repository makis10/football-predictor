"""
Backfill bookmaker odds (bm_home_odds, bm_draw_odds, bm_away_odds, bm_over_odds)
for completed matches whose predictions have NULL bm_odds.

Source: football-data.co.uk CSVs (already downloaded to backend/data/raw/).
Uses Bet365 closing odds: B365H, B365D, B365A, B365>2.5.

Coverage:  EPL, LaLiga, SerieA, Bundesliga, Ligue1, GreekSL
No coverage: CL, EL, ECL (not in football-data CSVs — will remain NULL).

Run manually after a CSV refresh:
    docker compose exec backend python scripts/backfill_bm_odds.py

Also called automatically by run_daily.sh after download_data.py --refresh-current.
"""
from __future__ import annotations

import glob
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))  # project root

import pandas as pd
from datetime import date
from sqlalchemy import text

from backend.app.database import SessionLocal, engine

# ── Mapping: CSV league prefix → DB league code ──────────────────────────────
LEAGUE_MAP: dict[str, str] = {
    "EPL":        "EPL",
    "LaLiga":     "LaLiga",
    "SerieA":     "SerieA",
    "Bundesliga": "Bundesliga",
    "Ligue1":     "Ligue1",
    "GreekSL":    "GreekSL",
}

DATA_DIR = "/app/backend/data/raw"


def _load_csv_odds() -> pd.DataFrame:
    """Load all available season CSVs and return a lookup table keyed by
    (league, match_date, home_team, away_team) → (bm_home, bm_draw, bm_away, bm_over)."""
    frames = []
    # Current + previous season (catches early-season matches)
    for pattern in ["*_2526.csv", "*_2425.csv"]:
        for path in sorted(glob.glob(f"{DATA_DIR}/{pattern}")):
            prefix = path.split("/")[-1].rsplit("_", 1)[0]
            if prefix not in LEAGUE_MAP:
                continue
            league = LEAGUE_MAP[prefix]
            try:
                df = pd.read_csv(path, dayfirst=True)
            except Exception as e:
                print(f"  [warn] Could not read {path}: {e}")
                continue

            required = {"Date", "HomeTeam", "AwayTeam", "B365H", "B365D", "B365A"}
            if not required.issubset(df.columns):
                print(f"  [warn] {path}: missing columns {required - set(df.columns)}")
                continue

            df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
            df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "B365H", "B365D", "B365A"])

            over_col = next(
                (c for c in ["B365>2.5", "B365C>2.5", "Avg>2.5"] if c in df.columns),
                None,
            )

            rows = []
            for _, row in df.iterrows():
                rows.append({
                    "league":     league,
                    "match_date": row["Date"].date(),
                    "home_team":  str(row["HomeTeam"]).strip(),
                    "away_team":  str(row["AwayTeam"]).strip(),
                    "bm_home":    float(row["B365H"]),
                    "bm_draw":    float(row["B365D"]),
                    "bm_away":    float(row["B365A"]),
                    "bm_over":    float(row[over_col]) if over_col and pd.notna(row.get(over_col)) else None,
                })
            frames.append(pd.DataFrame(rows))

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    # Drop duplicates — keep first (current season takes priority over previous)
    combined = combined.drop_duplicates(subset=["league", "match_date", "home_team", "away_team"], keep="first")
    return combined


def run_backfill() -> None:
    print("=" * 60)
    print("Backfilling bm_odds from football-data.co.uk CSVs …")
    print("=" * 60)

    # ── 1. Load CSV odds ──────────────────────────────────────────────────────
    csv_df = _load_csv_odds()
    if csv_df.empty:
        print("No CSV data found. Run download_data.py first.")
        return
    print(f"CSV rows loaded: {len(csv_df)} (leagues: {csv_df['league'].unique().tolist()})")

    # Build a fast lookup dict
    lookup: dict[tuple, dict] = {}
    for _, row in csv_df.iterrows():
        key = (row["league"], row["match_date"], row["home_team"], row["away_team"])
        lookup[key] = {
            "bm_home": row["bm_home"],
            "bm_draw": row["bm_draw"],
            "bm_away": row["bm_away"],
            "bm_over": row["bm_over"],
        }

    # ── 2. Fetch completed predictions with NULL bm_odds ─────────────────────
    db = SessionLocal()
    total = matched = skipped = no_csv = 0
    try:
        rows = db.execute(text("""
            SELECT p.id, m.league, m.match_date, m.home_team, m.away_team
            FROM predictions p
            JOIN matches m ON m.id = p.match_id
            WHERE m.result IS NOT NULL
              AND p.bm_home_odds IS NULL
            ORDER BY m.match_date, m.league
        """)).fetchall()

        total = len(rows)
        print(f"\nCompleted predictions needing backfill: {total}")

        updates: list[dict] = []
        for pred_id, league, match_date, home_team, away_team in rows:
            key = (league, match_date, home_team, away_team)
            odds = lookup.get(key)

            if odds is None:
                # CSVs don't cover CL/EL/ECL — skip silently
                if league in ("CL", "EL", "ECL"):
                    no_csv += 1
                    continue
                # Domestic league: CSV might not be updated yet
                skipped += 1
                continue

            updates.append({
                "pred_id":  pred_id,
                "bm_home":  odds["bm_home"],
                "bm_draw":  odds["bm_draw"],
                "bm_away":  odds["bm_away"],
                "bm_over":  odds["bm_over"],
            })
            matched += 1

        # ── 3. Bulk update ────────────────────────────────────────────────────
        if updates:
            db.execute(
                text("""
                    UPDATE predictions
                    SET bm_home_odds = :bm_home,
                        bm_draw_odds = :bm_draw,
                        bm_away_odds = :bm_away,
                        bm_over_odds = :bm_over
                    WHERE id = :pred_id
                      AND bm_home_odds IS NULL
                """),
                updates,
            )
            db.commit()
    finally:
        db.close()   # always close — was outside try/finally (connection leak)

    # ── 4. Report ─────────────────────────────────────────────────────────────
    print(f"\nResults:")
    print(f"  ✅ Backfilled:  {matched}")
    print(f"  ⏳ CSV pending: {skipped}  (domestic leagues not yet in football-data CSVs)")
    print(f"  ⚪ No CSV:      {no_csv}   (CL/EL/ECL — not covered by football-data)")
    print(f"  Total:          {total}")

    if skipped > 0:
        print(f"\n  ℹ️  The {skipped} pending matches will be backfilled automatically")
        print(f"     once football-data.co.uk updates their CSVs (usually within a week).")


if __name__ == "__main__":
    run_backfill()
