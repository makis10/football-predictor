"""
Load Greek Super League fixtures + results from API-Football (league 197).

Why this exists alongside fetch_greek_fixtures.py (The Odds API)
---------------------------------------------------------------
The Odds API's `soccer_greece_super_league` key goes inactive out of season, so
between seasons we have NO upcoming Greek fixtures — which is exactly why the
Greek SL had no long-term projection while every other league (whose fixtures
come from football-data.org) did. API-Football publishes the new-season schedule
weeks earlier, so pulling from it lights up the projection as soon as the fixture
list is out. Greece is our primary market, so it's worth the extra source.

Same shape as the daily European fetch:
  • UPCOMING fixtures are inserted (predictions come from compute_predictions.py),
  • FINISHED fixtures only fill the score of a row we already had.
Team names resolve against our training data (all Greek clubs are in it); the
name guard warns on anything unmapped.

Usage:
  docker compose exec backend python scripts/fetch_greek_apifootball.py --days-ahead 120
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts._http_retry import get_with_retry  # noqa: E402

API_BASE = "https://v3.football.api-sports.io"
API_KEY  = os.getenv("API_SPORTS_KEY", "")
HEADERS  = {"x-apisports-key": API_KEY}

GREEK_LEAGUE_ID = 197
LEAGUE_CODE = "GreekSL"

UPCOMING_STATUSES = {"NS", "TBD"}
FINISHED_STATUSES = {"FT", "AET", "PEN", "WO", "AWD"}


def _api_season(d: date) -> int:
    return d.year if d.month >= 7 else d.year - 1


def _get(path: str, params: dict) -> dict:
    r = get_with_retry(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    body = r.json()
    errs = body.get("errors")
    if errs:
        if isinstance(errs, dict) and "requests" in errs:
            raise SystemExit(f"[fatal] API-Football daily quota exhausted: {errs['requests']}")
        raise RuntimeError(f"API-Football error: {errs}")
    return body


def infer_season(d: date) -> str:
    return f"{d.year}/{str(d.year + 1)[2:]}" if d.month >= 7 else f"{d.year - 1}/{str(d.year)[2:]}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch Greek SL fixtures/results (API-Football)")
    ap.add_argument("--days-ahead", type=int, default=120)
    ap.add_argument("--days-back", type=int, default=5)
    args = ap.parse_args()

    if not API_KEY:
        print("[error] API_SPORTS_KEY not set."); sys.exit(1)

    today = date.today()
    window_from = today - timedelta(days=args.days_back)
    window_to   = today + timedelta(days=args.days_ahead)

    from scripts.fetch_club_friendlies import _known_teams
    from scripts.team_resolver import build_resolver, warn_unknown_teams

    # Greek clubs are all in the training data, so the same strict resolver used
    # for the European feed maps them (spelling drift + affix handling).
    resolve = build_resolver(_known_teams())

    raw: list[dict] = []
    for season in sorted({_api_season(window_from), _api_season(window_to)}):
        data = _get("/fixtures", {
            "league": GREEK_LEAGUE_ID, "season": season,
            "from": window_from.isoformat(), "to": window_to.isoformat(),
        })
        raw.extend(data.get("response", []))
    print(f"GreekSL: {len(raw)} fixture(s) from API-Football {window_from} → {window_to}")

    upcoming: list[dict] = []
    finished: list[dict] = []
    for entry in raw:
        fx = entry.get("fixture", {})
        status = fx.get("status", {}).get("short", "")
        try:
            dt_utc = datetime.fromisoformat(fx["date"].replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            continue
        home = resolve(entry["teams"]["home"]["name"]) or entry["teams"]["home"]["name"]
        away = resolve(entry["teams"]["away"]["name"]) or entry["teams"]["away"]["name"]
        base = {
            "match_date":   dt_utc.date(),
            "kickoff_time": dt_utc.time().replace(microsecond=0),
            "league":       LEAGUE_CODE,
            "home_team":    home,
            "away_team":    away,
            "season":       infer_season(dt_utc.date()),
        }
        if status in UPCOMING_STATUSES and dt_utc.date() >= today:
            upcoming.append(base)
        elif status in FINISHED_STATUSES:
            g = entry.get("goals", {})
            if g.get("home") is None or g.get("away") is None:
                continue
            base["home_goals"], base["away_goals"] = int(g["home"]), int(g["away"])
            finished.append(base)

    print(f"  {len(upcoming)} upcoming / {len(finished)} finished")
    warn_unknown_teams(upcoming, domestic=True)

    from sqlalchemy import select

    from backend.app.database import SessionLocal
    from backend.app.models.match import Match
    from scripts.fixture_upsert import upsert_fixtures

    db = SessionLocal()
    try:
        new_matches, _ = upsert_fixtures(db, upcoming)

        scored = 0
        for f in finished:
            row = db.scalars(select(Match).where(
                Match.league == LEAGUE_CODE,
                Match.home_team == f["home_team"],
                Match.away_team == f["away_team"],
                Match.result.is_(None),
                Match.match_date >= f["match_date"] - timedelta(days=1),
                Match.match_date <= f["match_date"] + timedelta(days=1),
            )).first()
            if row is None:
                continue
            hg, ag = f["home_goals"], f["away_goals"]
            row.home_goals, row.away_goals = hg, ag
            row.result = "H" if hg > ag else ("A" if ag > hg else "D")
            scored += 1
        db.commit()
        print(f"  {len(new_matches)} new fixture(s) inserted, {scored} result(s) filled. "
              f"Predictions come from compute_predictions.py.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
