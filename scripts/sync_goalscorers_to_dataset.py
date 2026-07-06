"""
Backfill goalscorers.csv with same-day goals from player_match_stats.

The Golden Boot model reads martj42 goalscorers.csv, which lags ~1 day. We
already ingest player goals same-day from API-Football into player_match_stats
(scripts/fetch_player_stats.py). This appends scorer rows for recent fixtures
that goalscorers.csv doesn't yet contain, so the daily Golden Boot reflects
today's goals immediately — mirroring sync_results_to_dataset.py for scores.

Self-healing: when fetch_international_data --force re-downloads goalscorers.csv
and martj42 has finally published a fixture, this script detects the existing
(date, team) rows and skips it — no double counting.

Runs after fetch_player_stats.py and before simulate_wc.py in run_daily.sh.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "data" / "raw" / "international"
GS_PATH  = DATA_DIR / "goalscorers.csv"

sys.path.insert(0, str(ROOT))

from scripts._atomic_csv import atomic_to_csv  # noqa: E402


def main() -> None:
    from sqlalchemy import text
    from backend.app.database import SessionLocal

    if not GS_PATH.exists():
        print(f"[skip] {GS_PATH} missing.")
        return

    gs = pd.read_csv(GS_PATH)
    gs["_d"] = pd.to_datetime(gs["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    # (date, team) pairs martj42 already covers — never duplicate these.
    have = set(zip(gs["_d"], gs["team"]))

    cutoff = (date.today() - timedelta(days=10)).isoformat()
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT match_date, team, opponent, is_home, player_name, goals "
            "FROM player_match_stats WHERE goals > 0 AND match_date >= :c"
        ), {"c": cutoff}).fetchall()
    finally:
        db.close()

    new_rows = []
    added_keys = set()
    for mdate, team, opp, is_home, scorer, goals in rows:
        if (mdate, team) in have:           # martj42 already has it
            continue
        home = team if is_home else opp
        away = opp if is_home else team
        for _ in range(int(goals or 0)):
            new_rows.append({
                "date": mdate, "home_team": home, "away_team": away,
                "team": team, "scorer": scorer, "minute": "",
                "own_goal": False, "penalty": False,
            })
        added_keys.add((mdate, team))

    if not new_rows:
        print("✓ goalscorers.csv already current (nothing to sync).")
        return

    out = pd.concat([gs.drop(columns="_d"), pd.DataFrame(new_rows)], ignore_index=True)
    atomic_to_csv(out, GS_PATH, index=False)
    print(f"✓ Synced {len(new_rows)} goals across {len(added_keys)} fixture-sides into goalscorers.csv")


if __name__ == "__main__":
    main()
