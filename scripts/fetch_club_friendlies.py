"""
Fetch CLUB friendly fixtures (pre-season & mid-season exhibition games) from
API-Football and store them under league code "ClubFriendly", with
low-confidence ML predictions.

Why a separate script
---------------------
None of our regular fixture sources carries club friendlies:
  - football-data.org free tier  → league competitions only
  - The Odds API                 → no club-friendlies sport key
API-Football models them as league id 667 ("Friendlies Clubs", seasons keyed
by calendar year), which we already pay for (API_SPORTS_KEY).

What it does per run
--------------------
  1. Pull league-667 fixtures for [today - days_back, today + days_ahead]
     (1 request per page per calendar year in the window — normally 1-2).
  2. Resolve API-Football team names against our training data
     (static map → exact slug → alias/substring → difflib). Fixtures whose
     teams we can't resolve are skipped by default: a team with no CSV
     history gets Elo 1500 and a junk prediction. Use --allow-unknown to
     keep fixtures where at least ONE side is known (european-pipeline
     behaviour: the unknown side gets neutral default features).
  3. Upsert upcoming fixtures (league="ClubFriendly") and prune ones that
     vanished from the feed (friendlies get cancelled a lot).
  4. Fill in final scores for played friendlies (results never come from
     update_results.py / update_european_results.py — their sources don't
     cover friendlies).
  5. Compute predictions for new fixtures via the shared european-style
     cross-league path. Confidence is forced "low" for ClubFriendly by
     confidence_for() — both here and at serve time. No odds/EV: The Odds
     API doesn't quote friendlies, so odds columns stay NULL and friendlies
     never enter value-bet suggestions.

Usage (inside the backend container):
  python scripts/fetch_club_friendlies.py
  python scripts/fetch_club_friendlies.py --days-ahead 21 --days-back 3
  python scripts/fetch_club_friendlies.py --no-predictions
  python scripts/fetch_club_friendlies.py --allow-unknown
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

LEAGUE_CODE = "ClubFriendly"
FRIENDLIES_CLUBS_LEAGUE_ID = 667   # API-Football "Friendlies Clubs"

UPCOMING_STATUSES = {"NS", "TBD"}
FINISHED_STATUSES = {"FT", "AET", "PEN", "WO", "AWD"}

# API-Football name → our training-data name, for spellings the resolver can't
# bridge on its own. Extend this map whenever the run log prints an
# "unresolved" warning for a team we do have history for.
TEAM_MAP: dict[str, str] = {
    "AEK Athens":         "AEK",
    "AEK Athens FC":      "AEK",
    "Aris Thessaloniki":  "Aris",
    "Olympiakos Piraeus": "Olympiakos",
    "PAOK Thessaloniki":  "PAOK",
    "Volos NPS":          "Volos NFC",
    # League clubs whose API name carries a suffix our CSVs drop. These used to
    # resolve by substring containment — which ALSO (wrongly) matched their
    # non-league neighbours "Cambridge City" / "Peterborough Sports", collapsing
    # both sides of a fixture onto one name. Now stated explicitly.
    "Cambridge United":   "Cambridge",
    "Peterborough":       "Peterboro",
}


def infer_season(d: date) -> str:
    if d.month >= 7:
        return f"{d.year}/{str(d.year + 1)[2:]}"
    return f"{d.year - 1}/{str(d.year)[2:]}"


# ── API-Football fetch ────────────────────────────────────────────────────────

def fetch_friendlies(window_from: date, window_to: date) -> list[dict]:
    """All league-667 fixtures in the window (one request per calendar year).

    NOTE: /fixtures is NOT paginated — it returns every match in the window
    in a single response, and rejects a `page` parameter outright
    ("The Page field do not exist")."""
    fixtures: list[dict] = []
    seasons = sorted({window_from.year, window_to.year})
    for season in seasons:
        params = {
            "league": FRIENDLIES_CLUBS_LEAGUE_ID,
            "season": season,
            "from":   window_from.isoformat(),
            "to":     window_to.isoformat(),
        }
        resp = get_with_retry(f"{API_BASE}/fixtures", headers=HEADERS,
                              params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            print(f"  [error] API-Football (season {season}): {data['errors']}")
            continue
        fixtures.extend(data.get("response", []))
        remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
        print(f"  season {season}: cumulative {len(fixtures)} fixture(s) "
              f"(quota remaining: {remaining})")
    return fixtures


# ── Team-name resolution against training data ───────────────────────────────

def _build_resolver(known_teams: set[str]):
    """Return resolve(api_name) -> our training-data name, or None.

    Thin wrapper over the shared resolver. It used to match by substring
    containment, which collapsed distinct clubs onto one name:
        "Lincoln United"   → "Lincoln"   (two different Lincoln clubs)
        "Plymouth Parkway" → "Plymouth"  (Argyle)
        "Cambridge City"   → "Cambridge" (United)
    We stored the resulting "Lincoln vs Lincoln" self-fixtures with a phantom
    prediction. Unresolved clubs now keep their full API name instead.
    """
    from scripts.team_resolver import build_resolver

    return build_resolver(known_teams, TEAM_MAP)


def _known_teams() -> set[str]:
    from backend.app.ml.features import load_raw_csvs
    raw_dir = os.path.join(_PROJECT_ROOT, "backend", "data", "raw")
    history = load_raw_csvs(raw_dir)
    return set(history["home_team"]) | set(history["away_team"])


# ── DB: results for played friendlies ─────────────────────────────────────────

def update_results(db, played: list[dict]) -> int:
    """Fill home_goals/away_goals/result on ClubFriendly rows we inserted
    earlier. Only rows with result still NULL are touched; date matches
    ±1 day to absorb timezone drift between us and API-Football."""
    from sqlalchemy import select

    from backend.app.models.match import Match

    updated = 0
    for f in played:
        row = db.scalars(
            select(Match).where(
                Match.league    == LEAGUE_CODE,
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
        row.home_goals = hg
        row.away_goals = ag
        row.result = "H" if hg > ag else ("A" if ag > hg else "D")
        updated += 1
        print(f"  ✓ {f['home_team']} {hg}-{ag} {f['away_team']}")
    db.commit()
    return updated


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fetch club friendlies (API-Football league 667) + predictions"
    )
    parser.add_argument("--days-ahead", type=int, default=14,
                        help="How far ahead to look for upcoming friendlies (default 14)")
    parser.add_argument("--days-back", type=int, default=7,
                        help="How far back to look for finished friendlies (default 7)")
    parser.add_argument("--allow-unknown", action="store_true",
                        help="Keep fixtures where only ONE team is in our training data "
                             "(default: both teams must be known)")
    parser.add_argument("--no-predictions", action="store_true",
                        help="No-op, kept for compatibility: this script no longer "
                             "predicts. compute_predictions.py is the only path.")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: API_SPORTS_KEY not set in environment.")
        sys.exit(1)

    today = date.today()
    window_from = today - timedelta(days=args.days_back)
    window_to   = today + timedelta(days=args.days_ahead)

    print(f"Fetching club friendlies {window_from} → {window_to} …")
    raw = fetch_friendlies(window_from, window_to)
    if not raw:
        print("No friendlies returned — nothing to do.")
        return

    print("Loading training-data team names …")
    known = _known_teams()
    resolve = _build_resolver(known)

    upcoming: list[dict] = []
    played:   list[dict] = []
    skipped_unknown = 0
    skipped_same_club = 0
    unresolved_names: set[str] = set()

    for entry in raw:
        fx     = entry.get("fixture", {})
        status = fx.get("status", {}).get("short", "")
        try:
            dt = datetime.fromisoformat(fx["date"].replace("Z", "+00:00"))
            dt_utc = dt.astimezone(timezone.utc)
        except Exception:
            continue

        api_home = entry["teams"]["home"]["name"]
        api_away = entry["teams"]["away"]["name"]

        # A club against its own youth/reserve side ("Fiorentina" vs
        # "Fiorentina U20") is not a real match-up: identical features on both
        # sides make the prediction pure home advantage, and the club's Elo
        # would update against itself.
        if same_club(api_home, api_away):
            skipped_same_club += 1
            continue

        home = resolve(api_home)
        away = resolve(api_away)
        if home is None:
            unresolved_names.add(api_home)
        if away is None:
            unresolved_names.add(api_away)

        n_known = (home is not None) + (away is not None)
        required = 1 if args.allow_unknown else 2
        if n_known < required:
            skipped_unknown += 1
            continue
        # --allow-unknown: the unknown side keeps its FULL API name; the feature
        # engine gives it neutral defaults (same as unmapped EL/ECL teams).
        home = home or api_home
        away = away or api_away
        if home == away:
            print(f"  [warn] '{api_home}' vs '{api_away}' both resolved to "
                  f"'{home}' — skipped. Add one to TEAM_MAP.")
            continue

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
            goals = entry.get("goals", {})
            if goals.get("home") is None or goals.get("away") is None:
                continue
            base["home_goals"] = int(goals["home"])
            base["away_goals"] = int(goals["away"])
            played.append(base)

    print(f"  {len(upcoming)} upcoming / {len(played)} finished with both teams known"
          f"{' (or one, --allow-unknown)' if args.allow_unknown else ''}; "
          f"{skipped_unknown} skipped (unknown teams); "
          f"{skipped_same_club} skipped (club vs its own youth/reserve side)")
    if unresolved_names:
        sample = ", ".join(sorted(unresolved_names)[:15])
        print(f"  Unresolved team names ({len(unresolved_names)}): {sample}"
              + (" …" if len(unresolved_names) > 15 else ""))

    from backend.app.database import SessionLocal
    from scripts.fixture_upsert import prune_vanished, upsert_fixtures

    db = SessionLocal()
    try:
        print("\nUpserting upcoming friendlies …")
        new_matches, touched_ids = upsert_fixtures(db, upcoming)
        # Friendlies get cancelled/moved constantly — drop unplayed rows the
        # feed no longer lists, strictly within the window we just fetched.
        prune_vanished(db, [LEAGUE_CODE], touched_ids,
                       horizon_days=args.days_ahead)

        print("\nFilling results for played friendlies …")
        n_res = update_results(db, played)
        print(f"  {n_res} result(s) written")

        if new_matches:
            print(f"\n{len(new_matches)} new fixture(s) inserted. Run "
                  f"scripts/compute_predictions.py to price them (run_daily "
                  f"does this in step 6). confidence_for() forces 'low' for "
                  f"ClubFriendly, and no odds are quoted, so they never enter "
                  f"value-bet suggestions.")
    finally:
        db.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
