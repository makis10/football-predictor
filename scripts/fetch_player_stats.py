"""
Ingest per-player, per-fixture statistics from API-Football into
player_match_stats — the foundation for player-prop models (anytime scorer,
shots on target, assists).

Flow:
  1. Target teams = distinct teams in national_predictions (WC + recent).
  2. Resolve each to its API-Football team id (national side), cached in
     wc_team_ids.json.
  3. For each team, list its last --last fixtures (/fixtures?team&last).
  4. For each fixture not already ingested, pull /fixtures/players and upsert
     one row per player.

Budget-aware: API-Football Pro = 7500 req/day. --max-requests caps a run.
Idempotent: unique (fixture_id, player_id); fixtures already in the table are
skipped without a request.

Usage:
  docker compose exec backend python scripts/fetch_player_stats.py
  docker compose exec backend python scripts/fetch_player_stats.py --last 30 --max-requests 2000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT      = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ID_CACHE  = ROOT / "backend" / "data" / "models" / "national" / "wc_team_ids.json"
API_BASE  = "https://v3.football.api-sports.io"
API_KEY   = os.getenv("API_SPORTS_KEY", "")
HEADERS   = {"x-apisports-key": API_KEY}

# API-Football team name → our canonical DB name. Applied at ingestion so the
# player_match_stats.team column joins cleanly to national_predictions.
API_TO_CANON = {
    "Czechia":              "Czech Republic",
    "Congo DR":             "DR Congo",
    "USA":                  "United States",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Türkiye":              "Turkey",
    "Cape Verde Islands":   "Cape Verde",
    "Korea Republic":       "South Korea",
    "IR Iran":              "Iran",
}


def _canon(name: str) -> str:
    return API_TO_CANON.get(name, name)


# Our DB name → API-Football search term, where they differ.
NAME_TO_API = {
    "Czech Republic": "Czechia",
    "DR Congo":       "Congo DR",
    "United States":  "USA",
    "South Korea":    "South Korea",
    "Ivory Coast":    "Ivory Coast",
    "Cape Verde":     "Cape Verde Islands",
    "Bosnia and Herzegovina": "Bosnia",
    "Republic of Ireland":    "Ireland",
    "China PR":       "China",
}


class Budget:
    def __init__(self, cap: int):
        self.cap = cap
        self.used = 0
    def ok(self) -> bool:
        return self.used < self.cap
    def hit(self) -> None:
        self.used += 1


def _get(path: str, params: dict, budget: Budget) -> dict:
    budget.hit()
    r = requests.get(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=20)
    if r.status_code == 429:
        time.sleep(2)
        r = requests.get(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def _load_id_cache() -> dict:
    try:
        return json.loads(ID_CACHE.read_text())
    except Exception:
        return {}


def _save_id_cache(cache: dict) -> None:
    ID_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ID_CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def resolve_team_id(name: str, cache: dict, budget: Budget) -> int | None:
    if name in cache:
        return cache[name]
    if not budget.ok():
        return None
    term = NAME_TO_API.get(name, name)
    try:
        data = _get("/teams", {"search": term}, budget)
    except Exception as e:
        print(f"  [warn] team lookup failed for {name}: {e}")
        return None
    # Prefer a national side; fall back to first result.
    best = None
    for t in data.get("response", []):
        tm = t["team"]
        if tm.get("national"):
            best = tm["id"]; break
    if best is None and data.get("response"):
        best = data["response"][0]["team"]["id"]
    cache[name] = best
    _save_id_cache(cache)
    return best


def _parse_players(resp: list, fixture_id: int, match_date: str, league_id: int) -> list[dict]:
    rows = []
    teams = [_canon(t["team"]["name"]) for t in resp]
    for ti, block in enumerate(resp):
        team = _canon(block["team"]["name"])
        opp  = teams[1 - ti] if len(teams) == 2 else None
        for p in block.get("players", []):
            pl = p["player"]
            st = (p.get("statistics") or [{}])[0]
            games = st.get("games") or {}
            goals = st.get("goals") or {}
            shots = st.get("shots") or {}
            passes = st.get("passes") or {}
            cards = st.get("cards") or {}
            rows.append({
                "fixture_id": fixture_id, "match_date": match_date, "league_id": league_id,
                "team": team, "opponent": opp,
                "player_id": pl["id"], "player_name": pl.get("name") or "?",
                "position": games.get("position"),
                "minutes": games.get("minutes"),
                "goals": goals.get("total") or 0,
                "assists": goals.get("assists") or 0,
                "shots_total": shots.get("total") or 0,
                "shots_on": shots.get("on") or 0,
                "key_passes": passes.get("key") or 0,
                "yellow": cards.get("yellow") or 0,
                "red": cards.get("red") or 0,
                "rating": float(games["rating"]) if games.get("rating") else None,
            })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest player match stats from API-Football")
    ap.add_argument("--last", type=int, default=25, help="Fixtures per team to pull (default 25)")
    ap.add_argument("--max-requests", type=int, default=2000, help="API request cap per run")
    ap.add_argument("--teams", type=int, default=None, help="Limit number of teams (debug)")
    ap.add_argument("--wc-only", action="store_true",
                    help="Only WC participants (focus budget on the tournament)")
    ap.add_argument("--tournament", type=str, default=None,
                    help="Restrict target teams to a tournament (partial match)")
    args = ap.parse_args()

    if not API_KEY:
        print("[error] API_SPORTS_KEY not set."); sys.exit(1)

    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from backend.app.database import SessionLocal
    from backend.app.models.national_prediction import NationalPrediction
    from backend.app.models.player_match_stats import PlayerMatchStats

    budget = Budget(args.max_requests)
    cache  = _load_id_cache()
    db = SessionLocal()
    try:
        base_h = select(NationalPrediction.home_team).distinct()
        base_a = select(NationalPrediction.away_team).distinct()
        if args.wc_only:
            # Exact match — "FIFA World Cup" only, NOT "...qualification".
            base_h = base_h.where(NationalPrediction.tournament == "FIFA World Cup")
            base_a = base_a.where(NationalPrediction.tournament == "FIFA World Cup")
        elif args.tournament:
            base_h = base_h.where(NationalPrediction.tournament.ilike(f"%{args.tournament}%"))
            base_a = base_a.where(NationalPrediction.tournament.ilike(f"%{args.tournament}%"))
        teams = [r[0] for r in db.execute(base_h).all()] + \
                [r[0] for r in db.execute(base_a).all()]
        teams = sorted(set(teams))
        if args.teams:
            teams = teams[:args.teams]
        print(f"{len(teams)} teams to ingest (req budget {args.max_requests}).")

        # Fixtures already ingested → skip without a request.
        have_fixtures = {r[0] for r in db.execute(
            select(PlayerMatchStats.fixture_id).distinct()
        ).all()}

        total_rows = new_fixtures = 0
        for name in teams:
            if not budget.ok():
                print("  [budget] request cap reached — stopping."); break
            tid = resolve_team_id(name, cache, budget)
            if not tid:
                print(f"  [skip] no API id for {name}"); continue
            try:
                fx = _get("/fixtures", {"team": tid, "last": args.last}, budget)
            except Exception as e:
                print(f"  [warn] fixtures failed for {name}: {e}"); continue

            for f in fx.get("response", []):
                if not budget.ok():
                    break
                fid = f["fixture"]["id"]
                if fid in have_fixtures:
                    continue
                status = f["fixture"]["status"]["short"]
                if status not in ("FT", "AET", "PEN"):
                    continue   # only finished fixtures have player stats
                mdate = f["fixture"]["date"][:10]
                lid   = f["league"]["id"]
                try:
                    pdata = _get("/fixtures/players", {"fixture": fid}, budget)
                except Exception as e:
                    print(f"  [warn] players failed for fixture {fid}: {e}"); continue
                rows = _parse_players(pdata.get("response", []), fid, mdate, lid)
                home_id = f["teams"]["home"]["id"]
                for row in rows:
                    row["is_home"] = (f["teams"]["home"]["name"] == row["team"])
                for row in rows:
                    stmt = pg_insert(PlayerMatchStats).values(**row).on_conflict_do_nothing(
                        constraint="uq_player_match_stats")
                    db.execute(stmt)
                db.commit()
                have_fixtures.add(fid)
                total_rows += len(rows); new_fixtures += 1
            print(f"  {name} (id {tid}): {new_fixtures} fixtures so far, {total_rows} rows  [req {budget.used}]")
    finally:
        db.close()

    print(f"\nDone. {new_fixtures} new fixtures, {total_rows} player rows, {budget.used} API requests.")


if __name__ == "__main__":
    main()
