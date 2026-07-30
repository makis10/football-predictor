"""
Fixtures + results for the domestic leagues that only API-Football covers.

The 2026-07-30 expansion added twelve countries (Belgium, Turkey, Scotland,
Denmark, Sweden, Norway, Poland, Austria, Switzerland, Romania, Ireland,
Finland) so that UEFA qualifying ties stop resolving to "Insufficient data".
Their HISTORY comes from football-data.co.uk via scripts/download_data.py, but
that only publishes played matches — the upcoming schedule has to come from
somewhere else, and football-data.org's free tier does not carry these
competitions. API-Football does, and we already pay for it.

Generalises scripts/fetch_greek_apifootball.py, which did exactly this for a
single hard-coded league. League ids are read from the one map the rest of the
project already uses (odds_analysis_service._LEAGUE_API_SPORTS_ID) rather than
being restated here, so a league can never be wired for odds but forgotten for
fixtures.

Contract, same as the European feed:
  • UPCOMING fixtures are INSERTED (predictions come from compute_predictions.py)
  • FINISHED fixtures only FILL the score of a row we already had — a past match
    we never anticipated is not back-filled, so it can't flatter the accuracy
    stats with a prediction made after the fact.

Usage:
  docker compose exec -T backend python scripts/fetch_domestic_apifootball.py
  docker compose exec -T backend python scripts/fetch_domestic_apifootball.py --leagues Belgium,Turkey
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
API_KEY = os.getenv("API_SPORTS_KEY", "")
HEADERS = {"x-apisports-key": API_KEY}

# The leagues this script owns. The older leagues get their fixtures from
# football-data.org (fetch_upcoming.py) and must NOT be double-ingested here.
DEFAULT_LEAGUES = [
    "Belgium", "Turkey", "Scotland", "Denmark", "Sweden", "Norway",
    "Poland", "Austria", "Switzerland", "Romania", "Ireland", "Finland",
]

UPCOMING_STATUSES = {"NS", "TBD"}
FINISHED_STATUSES = {"FT", "AET", "PEN", "WO", "AWD"}


# Summer leagues run Feb/Mar–Nov within one calendar year, so their API season
# is simply that year. Winter leagues use the start year of the split season.
CALENDAR_YEAR_LEAGUES = {"Sweden", "Norway", "Ireland", "Finland"}


def _api_season(league: str, d: date) -> int:
    if league in CALENDAR_YEAR_LEAGUES:
        return d.year
    return d.year if d.month >= 7 else d.year - 1


def _infer_season(league: str, d: date) -> str:
    """Our season label, matching what the CSV history uses for this league."""
    if league in CALENDAR_YEAR_LEAGUES:
        return str(d.year)
    return f"{d.year}/{str(d.year + 1)[2:]}" if d.month >= 7 \
        else f"{d.year - 1}/{str(d.year)[2:]}"


def _get(path: str, params: dict) -> dict:
    r = get_with_retry(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    body = r.json()
    errs = body.get("errors")
    if errs:
        # A quota error arrives as HTTP 200 with an errors dict — without this
        # check an exhausted plan looks exactly like "no fixtures today".
        if isinstance(errs, dict) and "requests" in errs:
            raise SystemExit(f"[fatal] API-Football daily quota exhausted: {errs['requests']}")
        raise RuntimeError(f"API-Football error: {errs}")
    return body


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch domestic fixtures/results from API-Football")
    ap.add_argument("--days-ahead", type=int, default=120)
    ap.add_argument("--days-back", type=int, default=5)
    ap.add_argument("--leagues", type=str, default=None,
                    help="Comma-separated league codes (default: the twelve expansion leagues)")
    args = ap.parse_args()

    if not API_KEY:
        print("[error] API_SPORTS_KEY not set.")
        sys.exit(1)

    from backend.app.ml.odds_analysis_service import _LEAGUE_API_SPORTS_ID

    leagues = [s.strip() for s in args.leagues.split(",")] if args.leagues else DEFAULT_LEAGUES
    unknown = [lg for lg in leagues if lg not in _LEAGUE_API_SPORTS_ID]
    if unknown:
        print(f"[error] no API-Football id for: {', '.join(unknown)}")
        sys.exit(1)

    today = date.today()
    window_from = today - timedelta(days=args.days_back)
    window_to = today + timedelta(days=args.days_ahead)

    from sqlalchemy import select

    from backend.app.database import SessionLocal
    from backend.app.models.match import Match
    from scripts.fetch_club_friendlies import _known_teams
    from scripts.fixture_upsert import upsert_fixtures
    from scripts.team_resolver import build_resolver, warn_unknown_teams

    # Aliases live in team_resolver.COMMON_ALIASES, which every resolver
    # inherits — these clubs also arrive via the European feed, and a map local
    # to this script left "Hearts" and "Heart Of Midlothian" as two clubs.
    resolve = build_resolver(_known_teams())
    db = SessionLocal()
    total_new = total_scored = 0
    try:
        for league in leagues:
            league_id = _LEAGUE_API_SPORTS_ID[league]
            raw: list[dict] = []
            seasons = sorted({_api_season(league, window_from), _api_season(league, window_to)})
            for season in seasons:
                try:
                    data = _get("/fixtures", {
                        "league": league_id, "season": season,
                        "from": window_from.isoformat(), "to": window_to.isoformat(),
                    })
                except Exception as e:
                    print(f"  [warn] {league} season {season}: {e}")
                    continue
                raw.extend(data.get("response", []))

            upcoming: list[dict] = []
            finished: list[dict] = []
            for entry in raw:
                fx = entry.get("fixture", {})
                status = fx.get("status", {}).get("short", "")
                try:
                    dt_utc = datetime.fromisoformat(
                        fx["date"].replace("Z", "+00:00")).astimezone(timezone.utc)
                except Exception:
                    continue
                home = resolve(entry["teams"]["home"]["name"]) or entry["teams"]["home"]["name"]
                away = resolve(entry["teams"]["away"]["name"]) or entry["teams"]["away"]["name"]
                base = {
                    "match_date":   dt_utc.date(),
                    "kickoff_time": dt_utc.time().replace(microsecond=0),
                    "league":       league,
                    "home_team":    home,
                    "away_team":    away,
                    "season":       _infer_season(league, dt_utc.date()),
                }
                if status in UPCOMING_STATUSES and dt_utc.date() >= today:
                    upcoming.append(base)
                elif status in FINISHED_STATUSES:
                    g = entry.get("goals", {})
                    if g.get("home") is None or g.get("away") is None:
                        continue
                    base["home_goals"], base["away_goals"] = int(g["home"]), int(g["away"])
                    finished.append(base)

            print(f"{league}: {len(raw)} fixture(s) — "
                  f"{len(upcoming)} upcoming / {len(finished)} finished")
            warn_unknown_teams(upcoming, domestic=True)

            new_matches, _ = upsert_fixtures(db, upcoming)

            scored = 0
            for f in finished:
                row = db.scalars(select(Match).where(
                    Match.league == league,
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
            print(f"  {len(new_matches)} new fixture(s) inserted, {scored} result(s) filled.")
            total_new += len(new_matches)
            total_scored += scored
    finally:
        db.close()

    print(f"\nDone: {total_new} new fixture(s), {total_scored} result(s) filled "
          f"across {len(leagues)} league(s). Predictions come from compute_predictions.py.")


if __name__ == "__main__":
    main()
