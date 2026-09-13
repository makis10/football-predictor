"""Settle or void club fixtures the result feeds have left behind.

settle_stale_fixtures.py answers what the training CSVs can. What they cannot —
a friendly the CSVs never carry, a play-off, a match abandoned or cancelled on
the day — stayed unsettled for ever: nine rows on 2026-09-13, the oldest a
Championship play-off final from May. Unsettled, a fixture drops out of every
accuracy figure, keeps any slip carrying it "still running", and is listed every
morning among the fixtures stuck without a result. Each is asked about once
more, at API-Football, which says what happened:

  FT / AET / PEN   played: settled with the 90-minute score
  AWD / WO         awarded: the awarded score, which the league table counts,
                   plus a void_reason so nothing grades it (migration 0038)
  CANC / ABD       not played: a void_reason and no score
  anything else    left alone and listed (postponed, or not found)

A row carrying a feed id is looked up by it, twenty ids to a request. One
without is found in that day's fixture list by its pairing — one request per
day, whatever the competition. Needs API_SPORTS_KEY.

Dry run by default; --apply writes.

  docker compose exec -T backend python scripts/resolve_stranded_fixtures.py
  docker compose exec -T backend python scripts/resolve_stranded_fixtures.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts._feed_scores import api_football_goals, api_football_void_reason  # noqa: E402

GRACE_DAYS = 2          # the regular pollers get their chance first
_PLAYED = ("FT", "AET", "PEN")
_IDS_PER_REQUEST = 20


def classify(entry: dict) -> tuple:
    """(action, home_goals, away_goals, void_reason) for one API-Football entry;
    action is settle | award | void | leave."""
    status = ((entry.get("fixture") or {}).get("status") or {}).get("short", "")
    reason = api_football_void_reason(entry)
    if status in _PLAYED:
        hg, ag = api_football_goals(entry)
        return ("settle", hg, ag, None) if hg is not None else ("leave", None, None, None)
    if reason in ("awarded", "walkover"):
        hg, ag = api_football_goals(entry)
        return ("award", hg, ag, reason)
    if reason:
        return ("void", None, None, reason)
    return ("leave", None, None, None)


def _result(hg: int, ag: int) -> str:
    return "H" if hg > ag else ("A" if ag > hg else "D")


def main() -> int:
    ap = argparse.ArgumentParser(description="Settle or void fixtures the feeds left behind")
    ap.add_argument("--grace-days", type=int, default=GRACE_DAYS)
    ap.add_argument("--apply", action="store_true", help="write; default is a dry run")
    args = ap.parse_args()

    if not os.getenv("API_SPORTS_KEY"):
        print("ERROR: API_SPORTS_KEY not set in environment.")
        return 1

    from sqlalchemy import select

    from backend.app.database import SessionLocal
    from backend.app.models.match import Match
    from scripts._http_retry import get_with_retry, raise_for_api_football_errors
    from scripts.fetch_club_friendlies import _known_teams
    from scripts.fetch_european_fixtures import API_BASE, HEADERS, build_strict_resolver, map_team

    def _get(params: dict) -> list:
        resp = get_with_retry(f"{API_BASE}/fixtures", headers=HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        raise_for_api_football_errors(body)
        return body.get("response", [])

    cutoff = date.today() - timedelta(days=args.grace_days)
    db = SessionLocal()
    try:
        stale = list(db.scalars(
            select(Match)
            .where(Match.result.is_(None), Match.void_reason.is_(None),
                   Match.match_date < cutoff)
            .order_by(Match.match_date)
        ).all())
        if not stale:
            print("No stranded fixtures.")
            return 0
        print(f"{len(stale)} fixture(s) before {cutoff} with no result and no void reason.")

        found: dict[int, dict] = {}                       # match id → entry
        ids = sorted({m.api_fixture_id for m in stale if m.api_fixture_id})
        for i in range(0, len(ids), _IDS_PER_REQUEST):
            chunk = ids[i:i + _IDS_PER_REQUEST]
            by_fid = {e["fixture"]["id"]: e
                      for e in _get({"ids": "-".join(str(x) for x in chunk)})}
            for m in stale:
                if m.api_fixture_id in by_fid:
                    found[m.id] = by_fid[m.api_fixture_id]

        rest = [m for m in stale if m.id not in found]
        if rest:
            resolve = build_strict_resolver(_known_teams())
            by_day: dict[date, list] = defaultdict(list)
            for m in rest:
                by_day[m.match_date].append(m)
            for day, rows in sorted(by_day.items()):
                pairs: dict[tuple, dict] = {}
                for e in _get({"date": day.isoformat()}):
                    h_api, a_api = e["teams"]["home"]["name"], e["teams"]["away"]["name"]
                    key = (resolve(h_api) or map_team(h_api), resolve(a_api) or map_team(a_api))
                    pairs.setdefault(key, e)
                for m in rows:
                    e = pairs.get((m.home_team, m.away_team))
                    if e is not None:
                        found[m.id] = e

        counts: dict[str, int] = defaultdict(int)
        for m in stale:
            e = found.get(m.id)
            label = f"{m.match_date} {m.league:<13} {m.home_team} v {m.away_team}"
            if e is None:
                counts["not found"] += 1
                print(f"  · {label}: not in the feed")
                continue
            action, hg, ag, reason = classify(e)
            status = e["fixture"]["status"]["short"]
            counts[action] += 1
            if action == "leave":
                print(f"  · {label}: {status} — left alone")
                continue
            print(f"  ✎ {label}: {status} → "
                  + (f"{hg}-{ag}" if hg is not None else "no score")
                  + (f", void ({reason})" if reason else ""))
            if not args.apply:
                continue
            if not m.api_fixture_id:
                m.api_fixture_id = e["fixture"]["id"]
            if hg is not None:
                m.home_goals, m.away_goals, m.result = hg, ag, _result(hg, ag)
            m.void_reason = reason

        print("\n" + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
        if args.apply:
            db.commit()
            from backend.app.cache import cache_delete_pattern
            for pattern in ("stats:*", "tickets:*"):
                cache_delete_pattern(pattern)
            print(f"Applied {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC; "
                  f"stats and tickets caches cleared.")
        else:
            db.rollback()
            print("DRY RUN — nothing written. Re-run with --apply.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
