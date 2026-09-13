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

from scripts._http_retry import QuotaExhausted, get_with_retry  # noqa: E402
from scripts._feed_scores import api_football_goals, api_football_void_reason  # noqa: E402

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


# Season rules: the one league-aware copy every writer shares.
from backend.app.ml.seasons import api_season as _api_season  # noqa: E402
from backend.app.ml.seasons import season_label as _infer_season  # noqa: E402


def _get(path: str, params: dict) -> dict:
    r = get_with_retry(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    body = r.json()
    errs = body.get("errors")
    if errs:
        # A quota error arrives as HTTP 200 with an errors dict — without this
        # check an exhausted plan looks exactly like "no fixtures today".
        if isinstance(errs, dict) and "requests" in errs:
            raise QuotaExhausted(f"[fatal] API-Football daily quota exhausted: {errs['requests']}")
        raise RuntimeError(f"API-Football error: {errs}")
    return body


def _missing_finished(finished: list[dict], existing: list[tuple]) -> list[dict]:
    """The finished fixtures we hold no row for: matched by feed id, or by the
    pairing within a day either side (feeds drift on late kick-offs).
    `existing` is (api_fixture_id, home, away, match_date) for every row held."""
    ids = {fid for fid, *_ in existing if fid}
    pairs = {(h, a, d) for _, h, a, d in existing}
    out = []
    for f in finished:
        if f.get("api_fixture_id") and f["api_fixture_id"] in ids:
            continue
        d = f["match_date"]
        if any((f["home_team"], f["away_team"], d + timedelta(days=k)) in pairs
               for k in (-1, 0, 1)):
            continue
        out.append(f)
    return out


def _backfill_season(db, league: str, league_id: int, resolve, today: date,
                     dry_run: bool) -> int:
    """Insert this season's finished matches we never held, as settled rows
    with no prediction.

    A league added mid-season only ever held rows from the day it was added,
    so its table and season projection were built from half a season: on
    2026-09-13 Norway showed 4–6 games per club with some twenty rounds
    played, Brazil 7–9. The normal run never inserts a finished match — it
    would let a prediction made afterwards into the accuracy record — but a
    row with no prediction cannot, and the table, Elo and projections need it.

    Refuses the whole league if a club the season does not already hold shows
    up: that is a name-mapping gap, and inserting it would split a club in two.
    """
    from sqlalchemy import select

    from backend.app.models.match import Match

    label = _infer_season(league, today)
    data = _get("/fixtures", {"league": league_id, "season": _api_season(league, today)})
    held = db.execute(select(Match.api_fixture_id, Match.home_team, Match.away_team,
                             Match.match_date, Match.season)
                      .where(Match.league == league)).all()
    existing = [(r[0], r[1], r[2], r[3]) for r in held]
    clubs = {t for r in held if r[4] == label for t in (r[1], r[2])}

    finished: list[dict] = []
    for entry in data.get("response", []):
        fx = entry.get("fixture", {})
        if fx.get("status", {}).get("short", "") not in FINISHED_STATUSES:
            continue
        hg, ag = api_football_goals(entry)     # 90 minutes, not after extra time
        if hg is None:
            continue
        try:
            dt_utc = datetime.fromisoformat(
                fx["date"].replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            continue
        finished.append({
            "api_fixture_id": fx.get("id"),
            "match_date":     dt_utc.date(),
            "kickoff_time":   dt_utc.time().replace(microsecond=0),
            "home_team": resolve(entry["teams"]["home"]["name"]) or entry["teams"]["home"]["name"],
            "away_team": resolve(entry["teams"]["away"]["name"]) or entry["teams"]["away"]["name"],
            "season":         _infer_season(league, dt_utc.date()),
            "home_goals":     hg,
            "away_goals":     ag,
            "void_reason":    api_football_void_reason(entry),
        })

    missing = [f for f in _missing_finished(finished, existing) if f["season"] == label]
    unknown = sorted({t for f in missing for t in (f["home_team"], f["away_team"])
                      if t not in clubs})
    if unknown:
        print(f"  [warn] {league}: nothing inserted — clubs season {label} does not "
              f"hold yet (map them first): {', '.join(unknown)}")
        return 0
    for f in missing:
        hg, ag = f["home_goals"], f["away_goals"]
        if not dry_run:
            db.add(Match(
                match_date=f["match_date"], kickoff_time=f["kickoff_time"],
                league=league, season=f["season"], api_fixture_id=f["api_fixture_id"],
                home_team=f["home_team"], away_team=f["away_team"],
                home_goals=hg, away_goals=ag,
                result="H" if hg > ag else ("A" if ag > hg else "D"),
                void_reason=f.get("void_reason"),
            ))
    if not dry_run:
        db.commit()
    print(f"  {league} {label}: {len(finished)} finished, {len(missing)} not held "
          f"→ {'would insert' if dry_run else 'inserted'} {len(missing)}")
    return len(missing)


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch domestic fixtures/results from API-Football")
    ap.add_argument("--days-ahead", type=int, default=120)
    ap.add_argument("--days-back", type=int, default=5)
    ap.add_argument("--leagues", type=str, default=None,
                    help="Comma-separated league codes (default: the twelve expansion leagues)")
    ap.add_argument("--backfill-season", action="store_true",
                    help="Insert this season's finished matches we never held (settled, "
                         "no prediction) — for a league added mid-season")
    ap.add_argument("--dry-run", action="store_true",
                    help="With --backfill-season: report what would be inserted, write nothing")
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
            if args.backfill_season:
                _backfill_season(db, league, league_id, resolve, today, dry_run=args.dry_run)
                continue
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
                    "api_fixture_id": fx.get("id"),
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
                    hg, ag = api_football_goals(entry)     # 90 minutes, not after extra time
                    if hg is None:
                        continue
                    base["home_goals"], base["away_goals"] = hg, ag
                    base["void_reason"] = api_football_void_reason(entry)   # awarded / walkover
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
                row.void_reason = f.get("void_reason")
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
