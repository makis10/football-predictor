"""
Ingest per-team, per-fixture statistics from API-Football into team_match_stats
— the foundation for team-level props (corners, shots, possession). Corners are
NOT exposed by /fixtures/players, so this is a separate ingestion alongside
fetch_player_stats.py, reusing its team-id cache and name maps.

Flow:
  1. Target teams = distinct teams in national_predictions (WC + recent).
  2. Resolve each to its API-Football team id (national side), cached in
     wc_team_ids.json (shared with fetch_player_stats.py).
  3. For each team, list its last --last fixtures (/fixtures?team&last).
  4. For each finished fixture not already ingested, pull /fixtures/statistics
     and upsert one row per team (parses "Corner Kicks" + a few extras).

Budget-aware: API-Football Pro = 7500 req/day. --max-requests caps a run.
Idempotent: unique (fixture_id, team); fixtures already in the table are
skipped without a request.

Usage:
  docker compose exec backend python scripts/fetch_match_statistics.py
  docker compose exec backend python scripts/fetch_match_statistics.py --wc-only --last 5 --max-requests 400
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Reuse the id cache, name maps and HTTP/budget helpers from the player-stats
# ingester so corners join cleanly to national_predictions on the same canon.
from scripts.fetch_player_stats import (  # noqa: E402
    API_KEY, Budget, _canon, _get, _load_id_cache, resolve_team_id,
)


def _to_int(value) -> int | None:
    """API-Football stat values come as int, numeric string or None."""
    if value is None:
        return None
    try:
        return int(float(str(value).strip().rstrip("%")))
    except (TypeError, ValueError):
        return None


def _to_pct(value) -> float | None:
    """Ball-possession arrives as e.g. '55%' → 55.0."""
    if value is None:
        return None
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def _parse_statistics(resp: list, fixture: dict, match_date: str, league_id: int) -> list[dict]:
    """Two team blocks → one row each, with corners + a few extras."""
    rows = []
    home = fixture["teams"]["home"]
    away = fixture["teams"]["away"]
    names = {b["team"]["id"]: _canon(b["team"]["name"]) for b in resp}
    for block in resp:
        tid  = block["team"]["id"]
        team = _canon(block["team"]["name"])
        opp_id = away["id"] if tid == home["id"] else home["id"]
        opp = names.get(opp_id) or _canon((away if tid == home["id"] else home)["name"])
        stats = {s.get("type"): s.get("value") for s in (block.get("statistics") or [])}
        rows.append({
            "fixture_id": fixture["fixture"]["id"], "match_date": match_date,
            "league_id": league_id, "team": team, "opponent": opp,
            "is_home": (tid == home["id"]),
            "corners":     _to_int(stats.get("Corner Kicks")),
            "possession":  _to_pct(stats.get("Ball Possession")),
            "shots_total": _to_int(stats.get("Total Shots")),
            "shots_on":    _to_int(stats.get("Shots on Goal")),
            "fouls":       _to_int(stats.get("Fouls")),
            "yellow_cards": _to_int(stats.get("Yellow Cards")),
            "red_cards":    _to_int(stats.get("Red Cards")),
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest team match statistics from API-Football")
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
    from backend.app.models.team_match_stats import TeamMatchStats

    budget = Budget(args.max_requests)
    cache  = _load_id_cache()
    db = SessionLocal()
    try:
        base_h = select(NationalPrediction.home_team).distinct()
        base_a = select(NationalPrediction.away_team).distinct()
        if args.wc_only:
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
            select(TeamMatchStats.fixture_id).distinct()
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
                    continue   # only finished fixtures have statistics
                mdate = f["fixture"]["date"][:10]
                lid   = f["league"]["id"]
                try:
                    sdata = _get("/fixtures/statistics", {"fixture": fid}, budget)
                except Exception as e:
                    print(f"  [warn] statistics failed for fixture {fid}: {e}"); continue
                resp = sdata.get("response", [])
                if len(resp) != 2:
                    continue   # incomplete / no stats for this fixture
                rows = _parse_statistics(resp, f, mdate, lid)
                for row in rows:
                    stmt = pg_insert(TeamMatchStats).values(**row).on_conflict_do_nothing(
                        constraint="uq_team_match_stats")
                    db.execute(stmt)
                db.commit()
                have_fixtures.add(fid)
                total_rows += len(rows); new_fixtures += 1
            print(f"  {name} (id {tid}): {new_fixtures} fixtures so far, {total_rows} rows  [req {budget.used}]")
    finally:
        db.close()

    print(f"\nDone. {new_fixtures} new fixtures, {total_rows} team rows, {budget.used} API requests.")


if __name__ == "__main__":
    main()
