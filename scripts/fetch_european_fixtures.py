"""
Fetch UEFA competition fixtures + results (CL / EL / ECL).

Source: API-Football (leagues CL=2, EL=3, ECL=848).
Ingest-only — predictions come from scripts/compute_predictions.py.

Why not The Odds API (the previous source)
------------------------------------------
It cannot serve this competition family:
  • `soccer_uefa_europa_league_qualification` and
    `soccer_uefa_europa_conference_league_qualification` DO NOT EXIST as sport
    keys (only the CL one does) — the old code requested them and silently got
    404 → [].
  • Worse, `{**ODDS_API_COMPETITIONS, **ODDS_API_QUALIFIERS}` shared the keys
    "EL"/"ECL", so the merge OVERWROTE the two valid league-phase keys with the
    non-existent qualifier keys — we never fetched the league phase either.
  • Bookmakers don't price 1st-qualifying-round ties (Escaldes–Mornar), so the
    sport stays inactive and returns no events regardless.
Net effect: no CL/EL/ECL fixture entered the DB after May 2026, including the
whole July qualifying programme. API-Football carries all of them, with scores.

Ingestion rule (deliberate, protects the public ROI / accuracy tracker)
----------------------------------------------------------------------
  • UPCOMING fixtures are inserted and predicted — including ties where neither
    club is in our training data (they get neutral default features).
  • FINISHED fixtures only ever FILL IN the score of a row we already had, i.e.
    one we predicted before kick-off. Past matches are never inserted, so we
    can't retro-fit predictions onto a known result and inflate our stats.

Team names are mapped to our domestic training-data names where possible.
Teams we have no history for (Vestri, Floriana, …) keep their API name and use
default features; those predictions are low-quality by construction.

Usage:
  docker compose exec backend python scripts/fetch_european_fixtures.py
  docker compose exec backend python scripts/fetch_european_fixtures.py --days-ahead 21 --days-back 5
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _PROJECT_ROOT)

from scripts._http_retry import get_with_retry  # noqa: E402
from scripts.team_resolver import same_club  # noqa: E402

API_BASE = "https://v3.football.api-sports.io"
API_KEY  = os.getenv("API_SPORTS_KEY", "")
HEADERS  = {"x-apisports-key": API_KEY}

# API-Football league ids. Qualifying rounds live under the SAME id as the
# league phase (distinguished by league.round), so one call covers both.
LEAGUE_IDS = {"CL": 2, "EL": 3, "ECL": 848}

UPCOMING_STATUSES = {"NS", "TBD"}
FINISHED_STATUSES = {"FT", "AET", "PEN", "WO", "AWD"}

# ── Team name mappings: external name → our training-data name ────────────────
# Only covers teams we have domestic data for. Unmapped teams keep their name;
# the feature engine will use default (neutral) stats for them.
TEAM_MAP: dict[str, str] = {
    # EL
    "SC Freiburg":       "Freiburg",
    "Nottingham Forest": "Nott'm Forest",
    "Real Betis":        "Betis",
    "Celta Vigo":        "Celta",
    "Aston Villa":       "Aston Villa",
    "Bologna":           "Bologna",
    # ECL
    "AEK Athens":        "AEK",
    "Rayo Vallecano":    "Vallecano",
    "Fiorentina":        "Fiorentina",
    "Crystal Palace":    "Crystal Palace",
    "Strasbourg":        "Strasbourg",
    "FSV Mainz 05":      "Mainz",
    # CL teams already mapped in download_european.py / European CSVs
    # (Bayern Munich, Real Madrid, Arsenal, etc. already correct)
}

def map_team(name: str) -> str:
    return TEAM_MAP.get(name, name)


def infer_season(d: date) -> str:
    if d.month >= 7:
        return f"{d.year}/{str(d.year + 1)[2:]}"
    return f"{d.year - 1}/{str(d.year)[2:]}"


def _api_season(d: date) -> int:
    """API-Football keys a UEFA season by its starting year (July → June)."""
    return d.year if d.month >= 7 else d.year - 1


def build_strict_resolver(known_teams: set[str]):
    """Resolver for this competition family — see scripts/team_resolver.py."""
    from scripts.team_resolver import build_resolver

    return build_resolver(known_teams, TEAM_MAP)


# ── CL / EL / ECL: fetch from API-Football ────────────────────────────────────

def fetch_api_football_fixtures(
    league_code: str, league_id: int, window_from: date, window_to: date
) -> list[dict]:
    """Every fixture for one competition in the window (qualifiers included).

    /fixtures is not paginated — one request per (league, season). A window that
    straddles a season boundary (e.g. June→July) needs both seasons.
    """
    raw: list[dict] = []
    for season in sorted({_api_season(window_from), _api_season(window_to)}):
        params = {
            "league": league_id, "season": season,
            "from": window_from.isoformat(), "to": window_to.isoformat(),
        }
        try:
            resp = get_with_retry(f"{API_BASE}/fixtures", headers=HEADERS,
                                  params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  {league_code}: ERROR fetching season {season} — {e}")
            continue
        if data.get("errors"):
            print(f"  {league_code}: API error (season {season}): {data['errors']}")
            continue
        raw.extend(data.get("response", []))
    print(f"  {league_code}: {len(raw)} fixture(s) from API-Football")
    return raw


def parse_fixtures(league_code: str, raw: list[dict], resolve) -> tuple[list[dict], list[dict]]:
    """Split the API payload into (upcoming, finished) fixture dicts.

    Unknown clubs keep their API name — we still price the tie (neutral default
    features) rather than hiding it from the schedule."""
    today = date.today()
    upcoming: list[dict] = []
    finished: list[dict] = []

    for entry in raw:
        fx = entry.get("fixture", {})
        status = fx.get("status", {}).get("short", "")
        try:
            dt_utc = datetime.fromisoformat(fx["date"].replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            continue

        api_home = entry["teams"]["home"]["name"]
        api_away = entry["teams"]["away"]["name"]

        # A club against its own youth/reserve side is not a real match-up:
        # both sides carry identical features, so the prediction is pure home
        # advantage and the club's Elo would update against itself.
        if same_club(api_home, api_away):
            print(f"  [skip] {league_code}: '{api_home}' vs '{api_away}' — same club")
            continue

        # Unresolved clubs keep their FULL API name, so two distinct clubs that
        # share a town ("Lincoln United" / "Lincoln") stay distinct.
        home = resolve(api_home) or map_team(api_home)
        away = resolve(api_away) or map_team(api_away)
        if home == away:
            print(f"  [warn] {league_code}: '{api_home}' vs '{api_away}' both resolved "
                  f"to '{home}' — skipped. Add one to TEAM_MAP.")
            continue

        base = {
            "match_date":   dt_utc.date(),
            "kickoff_time": dt_utc.time().replace(microsecond=0),
            "league":       league_code,
            # The stage ("1st Qualifying Round" / "League Phase - 3" /
            # "Round of 16"). A UEFA season stacks three different formats under
            # one league id; without this they're indistinguishable, and a
            # qualifying tie would be counted into the league-phase table.
            "round":        (entry.get("league") or {}).get("round"),
            "home_team":    home,
            "away_team":    away,
            "season":       infer_season(dt_utc.date()),
        }
        if status in UPCOMING_STATUSES and dt_utc.date() >= today:
            upcoming.append(base)
        elif status in FINISHED_STATUSES:
            goals = entry.get("goals", {})
            if goals.get("home") is None or goals.get("away") is None:
                continue
            base["home_goals"] = int(goals["home"])
            base["away_goals"] = int(goals["away"])
            finished.append(base)
    return upcoming, finished


def update_results(db, played: list[dict]) -> int:
    """Fill the score on rows we ALREADY have (result still NULL).

    Never inserts. A match we failed to fetch before kick-off stays out of the
    DB entirely, so it can't be retro-predicted into the accuracy/ROI tracker.
    Date matched ±1 day to absorb timezone drift against API-Football."""
    from sqlalchemy import select

    from backend.app.models.match import Match

    updated = 0
    for f in played:
        row = db.scalars(
            select(Match).where(
                Match.league    == f["league"],
                Match.home_team == f["home_team"],
                Match.away_team == f["away_team"],
                Match.result.is_(None),
                Match.match_date >= f["match_date"] - timedelta(days=1),
                Match.match_date <= f["match_date"] + timedelta(days=1),
            )
        ).first()
        if row is None:
            continue
        hg, ag = f["home_goals"], f["away_goals"]
        row.home_goals, row.away_goals = hg, ag
        row.result = "H" if hg > ag else ("A" if ag > hg else "D")
        # Finished fixtures never go through upsert_fixtures, so this is the only
        # place their stage gets recorded — and the league-phase table needs it.
        if f.get("round") and not row.round:
            row.round = f["round"]
        updated += 1
        print(f"  ✓ {f['league']}: {f['home_team']} {hg}-{ag} {f['away_team']}")
    db.commit()
    return updated


# ── DB helpers ────────────────────────────────────────────────────────────────

def insert_fixtures(db, fixtures: list[dict]) -> list:
    """Reschedule-aware upsert via the shared helper. Returns new Match objects.

    No pruning here: the CSV/Odds-API feeds are partial windows, so absence
    from the feed doesn't mean cancelled."""
    from scripts.fixture_upsert import upsert_fixtures
    new_matches, _ = upsert_fixtures(db, fixtures)
    return new_matches


# NOTE: this module used to carry its own `compute_predictions()` (a stripped
# copy of scripts/compute_predictions.py). It silently produced ZERO predictions
# after the market-independence refactor — it fed the model FEATURE_COLS while
# the retrained model expects RESULT_FEATURE_COLS / GOALS_FEATURE_COLS — and
# even when working it skipped calibration, the draw/BTTS specialists and the
# Poisson λ (so match pages lost Goals Lines / GG-NG). It is gone: predictions
# for every league, this one included, come from scripts/compute_predictions.py.


def main():
    parser = argparse.ArgumentParser(
        description="Fetch CL / EL / ECL fixtures + results (API-Football)"
    )
    parser.add_argument("--days-ahead", type=int, default=21,
                        help="How far ahead to look for upcoming ties (default 21)")
    parser.add_argument("--days-back", type=int, default=5,
                        help="How far back to look for finished ties to score (default 5)")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: API_SPORTS_KEY not set in environment.")
        sys.exit(1)

    today = date.today()
    window_from = today - timedelta(days=args.days_back)
    window_to   = today + timedelta(days=args.days_ahead)

    # Reuse the friendlies fetcher's training-data name list (lazy import keeps
    # module import cheap), but resolve with our own stricter matcher.
    from scripts.fetch_club_friendlies import _known_teams

    print(f"Fetching CL / EL / ECL fixtures {window_from} → {window_to} …")
    print("Loading training-data team names …")
    resolve = build_strict_resolver(_known_teams())

    from backend.app.database import SessionLocal
    db = SessionLocal()

    all_new: list = []
    total_scored = 0

    try:
        for code, league_id in LEAGUE_IDS.items():
            print(f"\n{code} (API-Football league {league_id}) …")
            raw = fetch_api_football_fixtures(code, league_id, window_from, window_to)
            if not raw:
                continue
            upcoming, finished = parse_fixtures(code, raw, resolve)
            print(f"  {len(upcoming)} upcoming / {len(finished)} finished")

            # domestic=False: unresolved UEFA teams are genuine minnows we have
            # no history for (they keep their full name + default features), not
            # a mapping bug — so this is an FYI, not a warning.
            from scripts.team_resolver import warn_unknown_teams
            warn_unknown_teams(upcoming, domestic=False)

            if upcoming:
                all_new.extend(insert_fixtures(db, upcoming))
            if finished:
                total_scored += update_results(db, finished)

        print(f"\n{total_scored} result(s) written onto fixtures we already had.")
        print(f"{len(all_new)} new fixture(s) inserted. Run scripts/compute_predictions.py "
              f"to price them (run_daily does this in step 6).")

    finally:
        db.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
