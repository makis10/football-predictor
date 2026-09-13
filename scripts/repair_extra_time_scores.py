"""Re-score club ties stored with their extra-time score (one-off, 2026-09-13).

Until scripts/_feed_scores.py, a club match decided in extra time or on
penalties was stored with API-Football's `goals` or football-data.org's
`fullTime` — both after extra time, football-data's including the shootout.
Every club market is graded at 90 minutes, so each such tie was graded against
a score the bookmaker never settled on.

For each competition and season this asks API-Football for the fixture list
(one request each), keeps the AET/PEN entries, finds our row (feed id, else the
pairing within a day), and rewrites the score to the 90-minute one — but only
where the stored score is an after-90 score: goals are only ever added after
90 minutes, so that is a stored score at or above the 90-minute one on both
sides. It covers the 120-minute score, football-data.org's shootout-inclusive
fullTime, and five CL/ECL shootout ties stored one goal per side above the
90-minute score — which the feed's own extra-time record does not explain
(Rapid–Hearts and Lech–Aarhus: no extra-time goals). A row below the feed's
score on either side disagrees about the match itself; it is printed and left
alone. Ticket legs resting on a corrected match are re-graded, and a settled
ticket whose verdict changes with them is re-settled.

Dry run by default; --apply writes.

  docker compose exec -T backend python scripts/repair_extra_time_scores.py
  docker compose exec -T backend python scripts/repair_extra_time_scores.py --apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

COMPETITIONS = {"CL": 2, "EL": 3, "ECL": 848, "ClubFriendly": 667}
EXTRA_TIME = ("AET", "PEN")


def _result(hg: int, ag: int) -> str:
    return "H" if hg > ag else ("A" if ag > hg else "D")


def _after_90(stored: tuple[int, int], at_90: tuple[int, int]) -> bool:
    """Is `stored` a score from after the 90th minute of this match?"""
    return stored != at_90 and stored[0] >= at_90[0] and stored[1] >= at_90[1]


def _find_row(db, Match, league: str, f: dict):
    from sqlalchemy import select

    if f.get("api_fixture_id"):
        row = db.scalars(select(Match).where(
            Match.api_fixture_id == f["api_fixture_id"])).first()
        if row is not None:
            return row
    rows = db.scalars(select(Match).where(
        Match.league == league,
        Match.home_team == f["home_team"],
        Match.away_team == f["away_team"],
        Match.match_date >= f["match_date"] - timedelta(days=1),
        Match.match_date <= f["match_date"] + timedelta(days=1),
    )).all()
    return rows[0] if len(rows) == 1 else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-score club ties stored after extra time")
    ap.add_argument("--seasons", type=int, nargs="+", default=[2025, 2026],
                    help="API-Football seasons (start year) to scan")
    ap.add_argument("--apply", action="store_true", help="write; default is a dry run")
    args = ap.parse_args()

    from sqlalchemy import select

    from backend.app.database import SessionLocal
    from backend.app.ml.tickets import settle_market
    from backend.app.models.match import Match
    from backend.app.models.ticket import Ticket, TicketLeg
    from scripts._http_retry import QuotaExhausted, get_with_retry
    from scripts.fetch_club_friendlies import _known_teams
    from scripts.fetch_european_fixtures import (
        API_BASE, API_KEY, HEADERS, build_strict_resolver, parse_fixtures,
    )

    if not API_KEY:
        print("ERROR: API_SPORTS_KEY not set in environment.")
        return 1
    resolve = build_strict_resolver(_known_teams())

    db = SessionLocal()
    fixed, disagree, unmatched = [], [], []
    try:
        for code, league_id in COMPETITIONS.items():
            for season in args.seasons:
                resp = get_with_retry(f"{API_BASE}/fixtures", headers=HEADERS,
                                      params={"league": league_id, "season": season},
                                      timeout=30)
                resp.raise_for_status()
                body = resp.json()
                errs = body.get("errors")
                if errs:
                    if isinstance(errs, dict) and "requests" in errs:
                        raise QuotaExhausted(f"API-Football quota: {errs['requests']}")
                    print(f"  {code} {season}: API error {errs}")
                    continue
                entries = [e for e in body.get("response", [])
                           if ((e.get("fixture") or {}).get("status") or {})
                           .get("short") in EXTRA_TIME]
                print(f"{code} {season}: {len(entries)} tie(s) went beyond 90 minutes")
                for e in entries:
                    _, finished = parse_fixtures(code, [e], resolve)
                    if not finished:
                        continue
                    f = finished[0]
                    row = _find_row(db, Match, code, f)
                    if row is None:
                        unmatched.append((code, f))
                        continue
                    if row.result is None or row.home_goals is None:
                        continue                  # the normal pipeline will score it
                    stored = (row.home_goals, row.away_goals)
                    want = (f["home_goals"], f["away_goals"])
                    if stored == want:
                        continue
                    status = e["fixture"]["status"]["short"]
                    if _after_90(stored, want):
                        fixed.append((row, stored, want, status))
                    else:
                        disagree.append((row, stored, want, status))

        for row, stored, want, status in fixed:
            print(f"  ✎ {row.league} {row.match_date} {row.home_team} v {row.away_team}: "
                  f"{stored[0]}-{stored[1]} ({status}) → {want[0]}-{want[1]} at 90'")
            if args.apply:
                row.home_goals, row.away_goals = want
                row.result = _result(*want)

        want_by_id = {row.id: want for row, _, want, _ in fixed}
        new_won: dict[int, bool] = {}
        touched_tickets: set[int] = set()
        if want_by_id:
            for leg in db.scalars(select(TicketLeg).where(
                    TicketLeg.match_id.in_(want_by_id))).all():
                if leg.won is None:
                    continue
                now = settle_market(leg.market, *want_by_id[leg.match_id])
                if now is not None and now != leg.won:
                    new_won[leg.id] = now
                    touched_tickets.add(leg.ticket_id)
                    print(f"  ↻ ticket {leg.ticket_id} leg {leg.market}: "
                          f"{'won' if leg.won else 'lost'} → {'won' if now else 'lost'}")
                    if args.apply:
                        leg.won = now

        flipped = 0
        if touched_tickets:
            for t in db.scalars(select(Ticket).where(Ticket.id.in_(touched_tickets))).all():
                if t.outcome not in ("won", "lost"):
                    continue
                verdict = "won" if all(new_won.get(l.id, l.won) for l in t.legs) else "lost"
                if verdict != t.outcome:
                    flipped += 1
                    print(f"  ⚑ ticket {t.id} ({t.profile}, {t.generated_for}): "
                          f"{t.outcome} → {verdict}")
                    if args.apply:
                        t.outcome = verdict

        for row, stored, want, status in disagree:
            print(f"  ? {row.league} {row.match_date} {row.home_team} v {row.away_team}: "
                  f"stored {stored[0]}-{stored[1]}, feed {want[0]}-{want[1]} at 90' "
                  f"({status}) — below the 90-minute score; left alone")
        for code, f in unmatched:
            print(f"  · {code} {f['match_date']} {f['home_team']} v {f['away_team']}: "
                  f"no row of ours")

        print(f"\n{len(fixed)} match(es) re-scored, {len(new_won)} leg(s) re-graded, "
              f"{flipped} ticket verdict(s) changed, {len(disagree)} left for review, "
              f"{len(unmatched)} not held.")
        if args.apply:
            db.commit()
            from backend.app.cache import cache_delete_pattern
            for pattern in ("stats:*", "tickets:*", "postmortem:*"):
                cache_delete_pattern(pattern)
            print("Applied; stats, tickets and post-mortem caches cleared.")
        else:
            db.rollback()
            print("DRY RUN — nothing written. Re-run with --apply.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
