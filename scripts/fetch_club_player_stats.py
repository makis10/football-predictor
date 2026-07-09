"""
Ingest per-player, per-fixture CLUB statistics from API-Football into
player_match_stats — the source for CLUB player props (anytime scorer / SoT /
assist), bringing club match pages to parity with the national ones.

Reuses the club team-id cache built by fetch_club_team_stats.py and the same
/fixtures/players parser as the national fetch_player_stats.py. Targets teams
with an UPCOMING club fixture first, so budget goes where users will look.

Budget-aware (Pro = 7500/day). Idempotent (unique fixture_id+player_id).

Usage:
  docker compose exec backend python scripts/fetch_club_player_stats.py --days-ahead 5 --last 6 --max-requests 1500
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts._http_retry import get_with_retry  # noqa: E402
from scripts.fetch_player_stats import _parse_players  # reuse the parser  # noqa: E402

API_BASE = "https://v3.football.api-sports.io"
API_KEY  = os.getenv("API_SPORTS_KEY", "")
HEADERS  = {"x-apisports-key": API_KEY}
ID_CACHE = ROOT / "backend" / "data" / "models" / "club_team_ids.json"


class Budget:
    def __init__(self, cap): self.cap, self.used = cap, 0
    def ok(self): return self.used < self.cap
    def hit(self): self.used += 1


def _get(path, params, budget):
    budget.hit()
    r = get_with_retry(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest club player match stats")
    ap.add_argument("--days-ahead", type=int, default=5)
    ap.add_argument("--last", type=int, default=6, help="Recent finished fixtures per team")
    ap.add_argument("--max-requests", type=int, default=1500)
    args = ap.parse_args()

    if not API_KEY:
        print("[error] API_SPORTS_KEY not set."); sys.exit(1)
    if not ID_CACHE.exists():
        print("[error] club_team_ids.json missing — run fetch_club_team_stats.py first."); sys.exit(1)

    cache = json.loads(ID_CACHE.read_text())

    from sqlalchemy import text
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from backend.app.database import SessionLocal
    from backend.app.models.player_match_stats import PlayerMatchStats

    budget = Budget(args.max_requests)
    db = SessionLocal()
    try:
        hi = (date.today() + timedelta(days=args.days_ahead)).isoformat()
        rows = db.execute(text(
            "SELECT DISTINCT home_team FROM matches WHERE home_goals IS NULL "
            "AND match_date BETWEEN :lo AND :hi "
            "UNION SELECT DISTINCT away_team FROM matches WHERE away_goals IS NULL "
            "AND match_date BETWEEN :lo AND :hi"
        ), {"lo": date.today().isoformat(), "hi": hi}).fetchall()
        target = [t for t in sorted({r[0] for r in rows}) if t in cache]
        print(f"{len(target)} club teams (with resolved ids) to ingest.")

        have = {r[0] for r in db.execute(
            text("SELECT DISTINCT fixture_id FROM player_match_stats")).fetchall()}

        n_fx = n_rows = 0
        for team in target:
            if not budget.ok():
                print("  [budget] cap reached."); break
            tid = cache[team]
            try:
                fx = _get("/fixtures", {"team": tid, "last": args.last}, budget).get("response", [])
            except Exception as e:
                print(f"  [warn] fixtures {team}: {e}"); continue
            for f in fx:
                if not budget.ok():
                    break
                fid = f["fixture"]["id"]
                if fid in have or f["fixture"]["status"]["short"] not in ("FT", "AET", "PEN"):
                    continue
                try:
                    pdata = _get("/fixtures/players", {"fixture": fid}, budget).get("response", [])
                except Exception:
                    continue
                prows = _parse_players(pdata, fid, f["fixture"]["date"][:10], f["league"]["id"])
                home_name = f["teams"]["home"]["name"]
                for row in prows:
                    row["is_home"] = (row["team"] == home_name)
                    db.execute(pg_insert(PlayerMatchStats).values(**row)
                               .on_conflict_do_nothing(constraint="uq_player_match_stats"))
                db.commit()
                have.add(fid); n_fx += 1; n_rows += len(prows)
            print(f"  {team}: {n_fx} fixtures so far, {n_rows} rows  [req {budget.used}]")
        print(f"\nDone. {n_fx} new fixtures, {n_rows} player rows, {budget.used} API requests.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
