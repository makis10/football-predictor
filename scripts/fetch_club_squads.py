"""
Fetch CURRENT club squads from API-Football (api-sports.io).

Why this exists
---------------
Club player props are derived from player_match_stats, which is a *match log*,
not a roster: a row says "this player played for this team on this date". The
prop engine treated "appeared for team X inside the 3-year window" as "is on
team X's squad", so a transferred player kept showing up for his old club
indefinitely — and during the summer window, when no new matches are played,
there is nothing in the log that could ever correct it.

This script fetches the actual current squad so the prop pool can be filtered
down to players who are really at the club.

Output:
  backend/data/models/club_squads.json
    {team: {"team_id": int, "player_ids": [int, ...], "fetched_at": iso}}

Player ids come from the same API-Football namespace as
player_match_stats.player_id, so the filter matches on id — no name
normalisation, no fuzzy matching.

Teams missing from the file are simply not filtered (graceful degradation:
props behave exactly as before for them), so a partial run is still useful.

Budget-aware: 1 request per team. Targets teams with an upcoming fixture first,
so quota goes where users will actually look.

Usage:
  docker compose exec backend python scripts/fetch_club_squads.py
  docker compose exec backend python scripts/fetch_club_squads.py --days-ahead 7
  docker compose exec backend python scripts/fetch_club_squads.py --max-age-days 6
  docker compose exec backend python scripts/fetch_club_squads.py --force
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts._http_retry import (  # noqa: E402
    API_FOOTBALL_QUOTA_RC, QuotaExhausted, get_with_retry,
)

API_BASE = "https://v3.football.api-sports.io"
API_KEY = os.getenv("API_SPORTS_KEY", "")
HEADERS = {"x-apisports-key": API_KEY}
ID_CACHE = ROOT / "backend" / "data" / "models" / "club_team_ids.json"
SQUADS_PATH = ROOT / "backend" / "data" / "models" / "club_squads.json"
SLEEP_BETWEEN_CALLS = 0.4


class Budget:
    def __init__(self, cap): self.cap, self.used = cap, 0
    def ok(self): return self.used < self.cap
    def hit(self): self.used += 1


def _get(path, params, budget):
    budget.hit()
    r = get_with_retry(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    body = r.json()
    errs = body.get("errors")
    # API-Football signals quota/plan errors as HTTP 200 + an errors dict —
    # without this check an exhausted quota silently looks like "empty squad",
    # which would then wipe every player out of the props.
    if errs:
        if isinstance(errs, dict) and "requests" in errs:
            raise QuotaExhausted(f"[fatal] API-Football daily quota exhausted: {errs['requests']}")
        raise RuntimeError(f"API-Football error: {errs}")
    return body


def fetch_squad(team_id: int, budget: Budget) -> list[int]:
    """Return the current squad as API-Football player ids."""
    try:
        response = _get("/players/squads", {"team": team_id}, budget).get("response", [])
    finally:
        time.sleep(SLEEP_BETWEEN_CALLS)
    ids: list[int] = []
    for squad in response:
        for p in squad.get("players", []):
            pid = p.get("id")
            if pid is not None:
                ids.append(int(pid))
    return ids


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch current club squads from API-Football")
    ap.add_argument("--days-ahead", type=int, default=7,
                    help="Only teams with a fixture inside this window")
    ap.add_argument("--max-requests", type=int, default=400)
    ap.add_argument("--max-age-days", type=float, default=None,
                    help="Skip entirely if club_squads.json is fresher than this")
    ap.add_argument("--force", action="store_true", help="Refetch even if the file is fresh")
    args = ap.parse_args()

    if not API_KEY:
        print("[error] API_SPORTS_KEY not set."); sys.exit(1)
    if not ID_CACHE.exists():
        print("[error] club_team_ids.json missing — run fetch_club_team_stats.py first.")
        sys.exit(1)

    # Freshness guard so the daily job can call this unconditionally.
    if args.max_age_days is not None and not args.force and SQUADS_PATH.exists():
        age_days = (time.time() - SQUADS_PATH.stat().st_mtime) / 86400
        if age_days < args.max_age_days:
            print(f"club_squads.json is {age_days:.1f}d old (< {args.max_age_days}d) — skipping.")
            return

    cache = json.loads(ID_CACHE.read_text())

    from sqlalchemy import text
    from backend.app.database import SessionLocal

    # Merge into whatever we already have: a partial/failed run must never
    # shrink the file, or teams would silently lose their roster filter.
    existing: dict = {}
    if SQUADS_PATH.exists():
        try:
            existing = json.loads(SQUADS_PATH.read_text())
        except Exception:
            existing = {}

    budget = Budget(args.max_requests)
    db = SessionLocal()
    try:
        hi = (date.today() + timedelta(days=args.days_ahead)).isoformat()
        # Ordered by soonest kick-off, so if the budget or the daily quota runs
        # out the teams that play first are already covered. (Alphabetical order
        # would truncate arbitrarily.)
        rows = db.execute(text(
            "SELECT team, MIN(match_date) AS next_match FROM ("
            "  SELECT home_team AS team, match_date FROM matches"
            "   WHERE home_goals IS NULL AND match_date BETWEEN :lo AND :hi"
            "  UNION ALL"
            "  SELECT away_team AS team, match_date FROM matches"
            "   WHERE away_goals IS NULL AND match_date BETWEEN :lo AND :hi"
            ") t GROUP BY team ORDER BY next_match, team"
        ), {"lo": date.today().isoformat(), "hi": hi}).fetchall()
        target = [r[0] for r in rows if cache.get(r[0])]
        print(f"{len(target)} club teams (with resolved ids) to fetch, soonest fixture first.")
        if len(target) > args.max_requests:
            print(f"  [warn] --max-requests {args.max_requests} < {len(target)} teams — "
                  f"the last {len(target) - args.max_requests} will keep their previous "
                  f"(possibly stale) squad.")

        n_ok = n_fail = 0
        quota_hit = None
        for team in target:
            if not budget.ok():
                print(f"  [budget] cap reached — {len(target) - n_ok - n_fail} teams not refreshed.")
                break
            tid = cache[team]
            try:
                ids = fetch_squad(tid, budget)
            except QuotaExhausted as e:
                # Daily quota gone. Stop fetching, but fall through to the write
                # below so the squads we did get are not thrown away. The message
                # is already on stdout — QuotaExhausted prints it.
                quota_hit = str(e)
                break
            except Exception as e:
                print(f"  [warn] squad {team}: {e}"); n_fail += 1; continue
            if not ids:
                # Empty response is not a real roster — keep the previous entry
                # rather than writing an empty list that would filter everyone out.
                print(f"  [warn] {team}: empty squad, keeping previous entry"); n_fail += 1
                continue
            existing[team] = {
                "team_id": tid,
                "player_ids": ids,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            n_ok += 1
            print(f"  {team}: {len(ids)} players  [req {budget.used}]")

        if n_ok:
            SQUADS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SQUADS_PATH.write_text(json.dumps(existing, indent=1, ensure_ascii=False))
        print(f"\nDone. {n_ok} squads fetched, {n_fail} failed, "
              f"{len(existing)} total in file, {budget.used} API requests.")

        # Staleness is the failure mode that matters during a transfer window:
        # an old entry looks healthy but silently filters on last month's roster.
        stale = sorted(
            ((t, e.get("fetched_at", "")) for t, e in existing.items() if t in set(target)),
            key=lambda x: x[1])[:3]
        if stale and stale[0][1]:
            print(f"  oldest squad among upcoming fixtures: {stale[0][0]} @ {stale[0][1]}")
        print(f"→ {SQUADS_PATH}")

        if quota_hit:
            # Non-zero exit so the daily job's `|| warn` fires and the run is
            # visibly incomplete rather than looking like a clean pass — but the
            # quota-specific code, so run_daily.sh skips the remaining
            # API-Football steps instead of paging about a broken pipeline.
            sys.exit(API_FOOTBALL_QUOTA_RC)
    finally:
        db.close()


if __name__ == "__main__":
    main()
