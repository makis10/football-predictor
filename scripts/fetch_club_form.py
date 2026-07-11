"""
Ingest current-season CLUB form per player from API-Football (/players) into
player_club_form — the empirical-Bayes prior for the international player-prop
rates (scorer / SoT / assist).

Why: player_match_stats only holds NATIONAL-team appearances (sparse — a few
caps a year), so a prolific club striker with few caps regresses to a flat
league prior. Their actual club scoring rate is a far better prior.

Flow:
  1. Target players = distinct player_id in player_match_stats (optionally only
     those on WC national teams, --wc-only).
  2. For each (skipping any refreshed within --max-age-days), call
     /players?id&season and SUM every CLUB competition block (the player's
     national-team blocks are excluded by name).
  3. Upsert g90 / sot90 / ast90 (computed only when club minutes ≥ floor).

Budget-aware: API-Football Pro = 7500 req/day. --max-requests caps a run
(1 request per player). Idempotent: re-running only refreshes stale rows.

Usage:
  docker compose exec backend python scripts/fetch_club_form.py --wc-only
  docker compose exec backend python scripts/fetch_club_form.py --max-requests 300 --season 2025
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts._http_retry import get_with_retry  # noqa: E402

API_BASE = "https://v3.football.api-sports.io"
API_KEY  = os.getenv("API_SPORTS_KEY", "")
HEADERS  = {"x-apisports-key": API_KEY}

# Default season: API-Football keys a season by its START year. The 2025/26
# club season is "2025". Auto-derived below from the current month if not given.
def _default_season() -> int:
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 7 else now.year - 1

MIN_CLUB_MIN = 270        # ≥ ~3 full club matches before we trust a club rate

# National-team competition name fragments — a safety net on top of the
# per-player national-team-name exclusion (handles odd team-name mismatches).
NATIONAL_COMP_FRAGMENTS = (
    "friendl", "world cup", "nations league", "euro", "copa america",
    "gold cup", "africa cup", "afcon", "asian cup", "qualific",
    "confederations", "olympic",
)


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
    r = get_with_retry(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    body = r.json()
    errs = body.get("errors")
    # API-Football signals quota/plan errors as HTTP 200 + an errors dict —
    # without this check an exhausted quota silently looks like "0 fixtures".
    if errs:
        if isinstance(errs, dict) and "requests" in errs:
            raise SystemExit(f"[fatal] API-Football daily quota exhausted: {errs['requests']}")
        raise RuntimeError(f"API-Football error: {errs}")
    return body



def _is_national_block(team_name: str, league_name: str, national_names: set[str]) -> bool:
    """A block belongs to the player's national team (exclude from club form)."""
    tl = (team_name or "").strip().lower()
    if tl in national_names:
        return True
    ll = (league_name or "").lower()
    return any(frag in ll for frag in NATIONAL_COMP_FRAGMENTS)


def aggregate_club(stats: list[dict], national_names: set[str]) -> dict:
    """Sum minutes/goals/assists/SoT across CLUB competition blocks."""
    club_min = club_goals = club_ast = club_sot = 0
    by_club_min: dict[str, int] = {}
    for s in stats:
        team = (s.get("team") or {}).get("name") or ""
        league = (s.get("league") or {}).get("name") or ""
        if _is_national_block(team, league, national_names):
            continue
        g = s.get("games") or {}
        go = s.get("goals") or {}
        sh = s.get("shots") or {}
        mins = g.get("minutes") or 0
        if not mins:
            continue
        club_min  += mins
        club_goals += go.get("total") or 0
        club_ast  += go.get("assists") or 0
        club_sot  += sh.get("on") or 0
        by_club_min[team] = by_club_min.get(team, 0) + mins
    club = max(by_club_min, key=by_club_min.get) if by_club_min else None
    out = {
        "club": club, "club_minutes": club_min, "club_goals": club_goals,
        "club_assists": club_ast, "club_sot": club_sot,
        "g90": None, "sot90": None, "ast90": None,
    }
    if club_min >= MIN_CLUB_MIN:
        out["g90"]   = round(90.0 * club_goals / club_min, 4)
        out["sot90"] = round(90.0 * club_sot   / club_min, 4)
        out["ast90"] = round(90.0 * club_ast   / club_min, 4)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest club-season form per player")
    ap.add_argument("--season", type=int, default=None, help="Season start year (default: auto)")
    ap.add_argument("--max-requests", type=int, default=400, help="API request cap (1/player)")
    ap.add_argument("--max-age-days", type=int, default=7, help="Skip rows refreshed within N days")
    ap.add_argument("--wc-only", action="store_true", help="Only players on WC national teams")
    ap.add_argument("--limit", type=int, default=None, help="Cap players (debug)")
    args = ap.parse_args()

    if not API_KEY:
        print("[error] API_SPORTS_KEY not set."); sys.exit(1)

    season = args.season or _default_season()

    from sqlalchemy import text
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from backend.app.database import Base, SessionLocal, engine
    from backend.app.models.player_club_form import PlayerClubForm
    # ensure player_match_stats model is registered for metadata too
    from backend.app.models.player_match_stats import PlayerMatchStats  # noqa: F401

    Base.metadata.create_all(bind=engine)

    budget = Budget(args.max_requests)
    db = SessionLocal()
    try:
        # Candidate players + the national team(s) they appear for.
        where = ""
        if args.wc_only:
            where = (
                "WHERE pms.team IN ("
                "  SELECT home_team FROM national_predictions WHERE tournament = 'FIFA World Cup' "
                "  UNION SELECT away_team FROM national_predictions WHERE tournament = 'FIFA World Cup')"
            )
        rows = db.execute(text(
            f"""
            SELECT pms.player_id,
                   MAX(pms.player_name) AS player_name,
                   ARRAY_AGG(DISTINCT pms.team) AS teams,
                   MAX(pms.match_date) AS last_seen
            FROM player_match_stats pms
            {where}
            GROUP BY pms.player_id
            ORDER BY last_seen DESC
            """
        )).fetchall()

        # Skip rows refreshed recently (idempotent) — but NEVER skip rows
        # without a usable rate (g90 IS NULL): those are exactly the ones the
        # season-rollover overwrite damaged, and skipping them for a week
        # would freeze the damage. They retry daily until a rate lands.
        fresh_cut = datetime.now(timezone.utc) - timedelta(days=args.max_age_days)
        fresh = {
            r[0] for r in db.execute(text(
                "SELECT player_id FROM player_club_form "
                "WHERE updated_at >= :cut AND g90 IS NOT NULL"
            ), {"cut": fresh_cut}).fetchall()
        }

        todo = [r for r in rows if r[0] not in fresh]
        if args.limit:
            todo = todo[:args.limit]
        print(f"{len(rows)} candidate players · {len(todo)} to refresh "
              f"(season {season}, budget {args.max_requests}).")

        upserted = with_rate = 0
        for pid, pname, teams, _last in todo:
            if not budget.ok():
                print("  [budget] request cap reached — stopping."); break
            national_names = {(t or "").strip().lower() for t in (teams or [])}
            try:
                data = _get("/players", {"id": pid, "season": season}, budget)
            except Exception as e:
                print(f"  [warn] /players failed for {pname} ({pid}): {e}"); continue
            resp = data.get("response", [])
            agg = (aggregate_club(resp[0].get("statistics", []), national_names)
                   if resp else None)
            agg_season = season
            # Season-rollover fallback (July–Sept): the new club season has no
            # minutes yet, so a current-season row would OVERWRITE last season's
            # usable g90 with None. Use the previous season's rates instead
            # until the player accrues MIN_CLUB_MIN minutes in the new one.
            if (agg is None or agg["g90"] is None) and budget.ok():
                try:
                    prev = _get("/players", {"id": pid, "season": season - 1}, budget)
                    presp = prev.get("response", [])
                    if presp:
                        pagg = aggregate_club(presp[0].get("statistics", []), national_names)
                        if pagg["g90"] is not None:
                            agg = pagg
                            agg_season = season - 1
                except Exception:
                    pass
            if agg is None:
                continue
            vals = {
                "player_id": pid, "player_name": pname,
                "season": agg_season, **agg,
                "updated_at": datetime.now(timezone.utc),
            }
            stmt = pg_insert(PlayerClubForm).values(**vals)
            stmt = stmt.on_conflict_do_update(
                index_elements=[PlayerClubForm.player_id],
                set_={k: vals[k] for k in (
                    "player_name", "club", "season", "club_minutes", "club_goals",
                    "club_assists", "club_sot", "g90", "sot90", "ast90", "updated_at")},
            )
            db.execute(stmt)
            db.commit()
            upserted += 1
            if agg["g90"] is not None:
                with_rate += 1
            if upserted % 25 == 0:
                print(f"  …{upserted} upserted ({with_rate} with a usable rate)  [req {budget.used}]")
        print(f"\nDone. {upserted} players upserted, {with_rate} with a club rate, "
              f"{budget.used} API requests.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
