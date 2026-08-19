#!/usr/bin/env python3
"""Fill bookmaker odds from API-Football when The Odds API cannot.

Why a second source
-------------------
The Odds API plan is 20,000 credits a month and it runs out. When it did on
2026-08-13 the site spent the rest of the month with no bookmaker price on any
fixture: no EV, no value gate, and an accumulator ladder that built nothing
because every leg would have been our own fair odds.

API-Football is already paid for, already IP-whitelisted, and runs at about two
thirds of its 7,500/day allowance. Its /odds endpoint carries 33 bookmakers over
exactly the markets we price:

    bet 1  Match Winner        → bm_home / bm_draw / bm_away
    bet 5  Goals Over/Under    → bm_over / bm_under   (the 2.5 line)
    bet 8  Both Teams Score    → bm_btts_yes / bm_btts_no

Cost is one request per (league, date) that actually has fixtures, not per
match, so a week of our card is tens of requests rather than hundreds.

Which bookmaker
---------------
Not the best price on offer — the most honest one. Preference order starts at
Pinnacle, which runs the lowest margin in the industry and is the closest thing
to a consensus fair price; the rest are fallbacks for fixtures Pinnacle does not
post. Taking the MAXIMUM odds across books would look generous and be wrong: it
would systematically overstate every payout the site quotes and inflate EV
against a price no single book offers on the whole slip.

Only fills what is missing. A prediction that already carries odds from The Odds
API is left alone, so this can run every day whether or not that plan is alive.

    docker compose exec -T backend python scripts/fetch_odds_apifootball.py
    docker compose exec -T backend python scripts/fetch_odds_apifootball.py --days 7 --dry-run
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from backend.app.redaction import redact  # noqa: E402

BASE = "https://v3.football.api-sports.io"

BET_MATCH_WINNER = 1
BET_OVER_UNDER   = 5
BET_BTTS         = 8

# Lowest margin first. Pinnacle's price is the industry's reference for fair
# value; the others are there so a fixture it does not post still gets priced.
BOOKMAKER_PREFERENCE = (
    "Pinnacle", "Marathonbet", "Bet365", "William Hill",
    "Bwin", "1xBet", "10Bet", "Betfair",
)


def _get(path: str, params: dict) -> dict:
    key = os.getenv("API_SPORTS_KEY", "")
    r = requests.get(f"{BASE}{path}", headers={"x-apisports-key": key},
                     params=params, timeout=25)
    r.raise_for_status()
    return r.json()


def _pick(values: list[dict], want: str) -> float | None:
    for v in values:
        if (v.get("value") or "").strip().lower() == want:
            try:
                return float(v["odd"])
            except (TypeError, ValueError):
                return None
    return None


def parse_fixture_odds(entry: dict) -> dict:
    """The prices we store, from one /odds response entry.

    Walks BOOKMAKER_PREFERENCE and takes each market from the first book that
    posts it, so a fixture Pinnacle prices for 1x2 but not BTTS still gets both
    rather than neither. Markets are independent; mixing books across markets
    costs nothing because we never combine them into one price.
    """
    books = {b.get("name"): b for b in entry.get("bookmakers", [])}
    out: dict[str, float] = {}

    for name in BOOKMAKER_PREFERENCE:
        book = books.get(name)
        if not book:
            continue
        for bet in book.get("bets", []):
            vals = bet.get("values") or []
            if bet.get("id") == BET_MATCH_WINNER and "bm_home_odds" not in out:
                h, d, a = _pick(vals, "home"), _pick(vals, "draw"), _pick(vals, "away")
                if h and d and a:
                    out.update(bm_home_odds=h, bm_draw_odds=d, bm_away_odds=a)
            elif bet.get("id") == BET_OVER_UNDER and "bm_over_odds" not in out:
                # Only the 2.5 line. The endpoint returns every line from 0.5 to
                # 5.5 and picking the wrong one would silently price a different
                # bet than the one the site displays.
                o, u = _pick(vals, "over 2.5"), _pick(vals, "under 2.5")
                if o and u:
                    out.update(bm_over_odds=o, bm_under_odds=u)
            elif bet.get("id") == BET_BTTS and "bm_btts_yes_odds" not in out:
                y, n = _pick(vals, "yes"), _pick(vals, "no")
                if y and n:
                    out.update(bm_btts_yes_odds=y, bm_btts_no_odds=n)
    return out


def resolve_missing_ids(db, rows, league_ids) -> int:
    """Fill api_fixture_id on fixtures that came from another feed.

    The top-5 leagues and the Championship arrive from football-data.org and
    Brazil from a CSV converter, so they carry no API-Football id and could
    never be priced from it — 137 of the 204 fixtures in the next week.

    One /fixtures request per (league, date), matched on team names with the
    same matcher the odds seam uses. This only WRITES A COLUMN: it never
    inserts a fixture, never moves a date, and never touches a row it cannot
    match confidently on both sides. football-data.org stays the schedule of
    record for those leagues; this just teaches us their id in the other feed.
    """
    from backend.app.ml.odds_analysis_service import _teams_match

    groups: dict[tuple, list] = collections.defaultdict(list)
    for m in rows:
        league_id = league_ids.get(m.league)
        if league_id:
            groups[(league_id, m.match_date)].append(m)
    if not groups:
        return 0

    print(f"Resolving API-Football ids for {sum(len(v) for v in groups.values())} "
          f"fixture(s) → {len(groups)} request(s)")
    resolved = 0
    for (league_id, day), members in sorted(groups.items(), key=lambda kv: kv[0][1]):
        season = day.year if day.month >= 7 else day.year - 1
        try:
            data = _get("/fixtures", {"league": league_id, "season": season,
                                      "date": day.isoformat()})
        except Exception as e:
            print(f"  [warn] league {league_id} {day}: {redact(e)}")
            continue
        for m in members:
            for entry in data.get("response", []):
                api_home = entry["teams"]["home"]["name"]
                api_away = entry["teams"]["away"]["name"]
                # Both sides must match. One is not enough: a league-day can
                # hold two fixtures involving clubs with similar names, and a
                # half match would attach the wrong match's prices.
                if _teams_match(api_home, m.home_team) and _teams_match(api_away, m.away_team):
                    m.api_fixture_id = entry["fixture"]["id"]
                    resolved += 1
                    break
    print(f"  resolved {resolved}")
    return resolved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7, help="how far ahead to price")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="overwrite odds a prediction already has")
    ap.add_argument("--no-resolve", action="store_true",
                    help="skip the id-resolution pass (saves requests)")
    args = ap.parse_args()

    if not os.getenv("API_SPORTS_KEY"):
        print("API_SPORTS_KEY not set")
        return 2

    from backend.app.database import SessionLocal
    from backend.app.ml.odds_analysis_service import _LEAGUE_API_SPORTS_ID
    from backend.app.models.match import Match
    from backend.app.models.prediction import Prediction

    today = date.today()
    horizon = today + timedelta(days=args.days)

    db = SessionLocal()
    try:
        base_q = (db.query(Match, Prediction)
                    .join(Prediction, Prediction.match_id == Match.id)
                    .filter(Match.result.is_(None),
                            Match.match_date >= today,
                            Match.match_date <= horizon))

        # Teach ourselves the ids we are missing before asking for prices,
        # otherwise the leagues that come from football-data.org can never be
        # priced from this source at all.
        unknown = [m for m, p in base_q.filter(Match.api_fixture_id.is_(None)).all()
                   if args.force or p.bm_home_odds is None]
        if unknown and not args.no_resolve:
            resolve_missing_ids(db, unknown, _LEAGUE_API_SPORTS_ID)
            if not args.dry_run:
                db.commit()

        rows = base_q.filter(Match.api_fixture_id.isnot(None)).all()
        if not args.force:
            rows = [(m, p) for m, p in rows if p.bm_home_odds is None]

        if not rows:
            print("Nothing to price — every upcoming fixture already carries odds "
                  "(or none has an API-Football id).")
            return 0

        # One request per (league, date). Grouping is the whole cost saving:
        # 151 fixtures across a week is ~40 requests, not 151.
        groups: dict[tuple, list] = collections.defaultdict(list)
        missing_league = set()
        for m, p in rows:
            league_id = _LEAGUE_API_SPORTS_ID.get(m.league)
            if not league_id:
                missing_league.add(m.league)
                continue
            groups[(league_id, m.match_date)].append((m, p))

        print(f"{len(rows)} fixture(s) without odds → {len(groups)} request(s)")
        if missing_league:
            print(f"  [skip] no API-Football league id: {', '.join(sorted(missing_league))}")

        priced = empty = failed = 0
        for (league_id, day), members in sorted(groups.items(), key=lambda kv: kv[0][1]):
            season = day.year if day.month >= 7 else day.year - 1
            try:
                data = _get("/odds", {"league": league_id, "season": season,
                                      "date": day.isoformat()})
            except Exception as e:
                print(f"  [warn] league {league_id} {day}: {redact(e)}")
                failed += 1
                continue

            by_fixture = {e["fixture"]["id"]: e for e in data.get("response", [])}
            for m, p in members:
                entry = by_fixture.get(m.api_fixture_id)
                if entry is None:
                    empty += 1
                    continue
                odds = parse_fixture_odds(entry)
                if not odds:
                    empty += 1
                    continue
                for field, value in odds.items():
                    setattr(p, field, value)
                priced += 1
                print(f"  {m.match_date} {m.home_team} vs {m.away_team}: "
                      + " ".join(f"{k.replace('bm_', '').replace('_odds', '')}={v}"
                                 for k, v in odds.items()))

        if args.dry_run:
            db.rollback()
            print(f"\nDRY RUN — would price {priced}, no market for {empty}, "
                  f"{failed} request(s) failed.")
        else:
            db.commit()
            print(f"\nPriced {priced} fixture(s); no market for {empty}; "
                  f"{failed} request(s) failed.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
