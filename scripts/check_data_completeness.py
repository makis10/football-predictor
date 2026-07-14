"""
Data-completeness healthcheck — catches silent ingestion failures.

Audits every cross-source seam for fixtures in the next --days days and
prints WARN/ALERT lines. Exit code 1 when any ALERT fired, so cron logs
make failures visible instead of the UI quietly showing "—".

Seams covered (each has silently failed at least once):
  1. club_team_ids.json          — null-poisoned / missing team ids
  2. team_match_stats            — tracked-league team with zero stats rows
  3. player_match_stats          — tracked-league team with zero player rows
  4. matches (club Elo source)   — team with no completed match (Elo=1500 default)
  5. wc_team_ids.json            — null-poisoned national team ids
  6. squad_strength.json         — upcoming national team missing
  7. player_club_form            — share of players stuck without a club rate
  8. predictions bookmaker odds  — odds-name seam (aliases) match rate

Usage:
  docker compose exec backend python scripts/check_data_completeness.py [--days 7]
Scheduled from run_daily.sh after the ingestion steps.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CLUB_IDS = ROOT / "backend" / "data" / "models" / "club_team_ids.json"
WC_IDS   = ROOT / "backend" / "data" / "models" / "national" / "wc_team_ids.json"
SQUADS   = ROOT / "backend" / "data" / "raw" / "international" / "squad_strength.json"

# Leagues whose teams SHOULD have stats coverage (mirrors fetch_club_team_stats).
# DOMESTIC teams missing stats = ALERT (our ingestion is broken).
# EURO-only teams (CL/EL/ECL qualifier minnows) = warn — API-Football often has
# no statistics for their domestic micro-leagues, so absence is expected until
# they play a covered European tie.
DOMESTIC = {"EPL", "Championship", "LeagueOne", "LaLiga", "SerieA", "Bundesliga",
            "Ligue1", "GreekSL", "PrimeiraLiga", "Eredivisie", "BrazilSerieA"}
EURO     = {"CL", "EL", "ECL"}
TRACKED  = DOMESTIC | EURO

alerts: list[str] = []
warns:  list[str] = []


def _alert(msg: str) -> None:
    alerts.append(msg); print(f"  ALERT  {msg}")


def _warn(msg: str) -> None:
    warns.append(msg); print(f"  warn   {msg}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Data completeness healthcheck")
    ap.add_argument("--days", type=int, default=7, help="Upcoming-fixture window")
    args = ap.parse_args()

    from sqlalchemy import text
    from backend.app.database import SessionLocal
    from backend.app.ml.club_props import _api_name

    lo, hi = date.today().isoformat(), (date.today() + timedelta(days=args.days)).isoformat()
    db = SessionLocal()
    try:
        # Upcoming club fixtures: (team, league) pairs.
        rows = db.execute(text(
            "SELECT home_team, league FROM matches WHERE result IS NULL AND match_date BETWEEN :lo AND :hi "
            "UNION SELECT away_team, league FROM matches WHERE result IS NULL AND match_date BETWEEN :lo AND :hi"
        ), {"lo": lo, "hi": hi}).fetchall()
        club_teams = sorted({(t, lg) for t, lg in rows})
        team_leagues: dict[str, set] = {}
        for t, lg in club_teams:
            team_leagues.setdefault(t, set()).add(lg)
        tracked_teams = sorted({t for t, lgs in team_leagues.items() if lgs & TRACKED})
        print(f"[club] {len(club_teams)} (team, league) pairs with fixtures in next {args.days}d "
              f"({len(tracked_teams)} teams in tracked leagues)")

        def _severity(team: str):
            """ALERT for domestic-league teams, warn for euro-qualifier-only ones."""
            return _alert if team_leagues.get(team, set()) & DOMESTIC else _warn

        # 1. club id cache
        ids = json.loads(CLUB_IDS.read_text()) if CLUB_IDS.exists() else {}
        for k, v in sorted(ids.items()):
            if v is None:
                _warn(f"club_team_ids: null entry '{k}' (unresolved — search fallback should retry)")
        for t in tracked_teams:
            if not ids.get(t):
                _severity(t)(f"club_team_ids: tracked-league team '{t}' has no API id — "
                             f"stats ingestion skips it (add NAME_OVERRIDES?)")

        # 2+3. stats coverage (via the same name translation the UI uses)
        for t in tracked_teams:
            api = _api_name(db, t)
            if api is None:
                _severity(t)(f"team_match_stats: '{t}' resolves to NO stored name — cards/corners show '—'")
                continue
            n_team = db.execute(text(
                "SELECT COUNT(*) FROM team_match_stats WHERE team = :t"), {"t": api}).scalar()
            n_players = db.execute(text(
                "SELECT COUNT(*) FROM player_match_stats WHERE team = :t"), {"t": api}).scalar()
            if not n_team:
                _severity(t)(f"team_match_stats: 0 rows for '{t}' (stored name '{api}')")
            if not n_players:
                # Team stats present but no player rows usually means API-Football
                # has no lineup coverage for that league — warn, don't alert.
                (_warn if n_team else _severity(t))(
                    f"player_match_stats: 0 rows for '{t}' (stored name '{api}') — player panel empty")

        # 4. club Elo source (info only — friendlies vs untracked sides expected)
        for t, lg in club_teams:
            n = db.execute(text(
                "SELECT COUNT(*) FROM matches WHERE (home_team = :t OR away_team = :t) "
                "AND home_goals IS NOT NULL"), {"t": t}).scalar()
            if not n and lg in TRACKED:
                _warn(f"club Elo: '{t}' ({lg}) has no completed match in DB — shows default 1500")

        # 5+6. national seams
        nrows = db.execute(text(
            "SELECT home_team FROM national_predictions WHERE match_date BETWEEN :lo AND :hi "
            "UNION SELECT away_team FROM national_predictions WHERE match_date BETWEEN :lo AND :hi"
        ), {"lo": lo, "hi": hi}).fetchall()
        nat_teams = sorted({r[0] for r in nrows})
        print(f"[national] {len(nat_teams)} teams with fixtures in next {args.days}d")
        wc_ids  = json.loads(WC_IDS.read_text()) if WC_IDS.exists() else {}
        squads  = json.loads(SQUADS.read_text()) if SQUADS.exists() else {}
        for k, v in sorted(wc_ids.items()):
            if v is None:
                _warn(f"wc_team_ids: null entry '{k}'")
        for t in nat_teams:
            if wc_ids and not wc_ids.get(t):
                _warn(f"wc_team_ids: no id for upcoming national team '{t}'")
            if squads and t not in squads:
                _warn(f"squad_strength: missing '{t}' — talent-Elo falls back to results-Elo")

        # 7. player_club_form health (July rollover regression guard)
        r = db.execute(text(
            "SELECT COUNT(*) AS n, COUNT(g90) AS with_rate FROM player_club_form "
            "WHERE updated_at >= NOW() - INTERVAL '30 days'")).fetchone()
        if r.n:
            share = r.with_rate / r.n
            print(f"[club form] {r.with_rate}/{r.n} recently-refreshed players have a club rate ({share:.0%})")
            if share < 0.40:
                _alert(f"player_club_form: only {share:.0%} of refreshed players have g90 — "
                       f"season-rollover overwrite? (fetch_club_form fallback should fix)")

        # 8. bookmaker odds seam — predictions stored in the last 7d for tracked leagues
        r = db.execute(text(
            "SELECT COUNT(*) AS n, COUNT(p.bm_home_odds) AS with_odds "
            "FROM predictions p JOIN matches m ON m.id = p.match_id "
            "WHERE m.match_date BETWEEN :lo AND :hi AND m.league = ANY(:lgs)"),
            {"lo": lo, "hi": hi, "lgs": list(TRACKED)}).fetchone()
        if r.n:
            share = r.with_odds / r.n
            print(f"[odds] {r.with_odds}/{r.n} tracked-league predictions carry bookmaker odds ({share:.0%})")
            if share < 0.50:
                _warn(f"odds seam: only {share:.0%} of tracked-league predictions matched odds "
                      f"(check _ALIASES in odds_analysis_service)")
    finally:
        db.close()

    # API-Football quota visibility (the /status call is not billed). A day at
    # >85% of the cap means the next backfill will start silently starving.
    import os
    import requests as _rq
    try:
        r = _rq.get("https://v3.football.api-sports.io/status",
                    headers={"x-apisports-key": os.getenv("API_SPORTS_KEY", "")},
                    timeout=10).json()
        resp = r.get("response") or {}
        if isinstance(resp, dict) and resp:
            used = (resp.get("requests") or {}).get("current", 0)
            cap  = (resp.get("requests") or {}).get("limit_day", 0)
            plan = (resp.get("subscription") or {}).get("plan", "?")
            print(f"[quota] API-Football {plan}: {used:,}/{cap:,} requests today "
                  f"({used / cap:.0%})" if cap else f"[quota] plan {plan}, usage {used}")
            if cap and used / cap > 0.85:
                _warn(f"API-Football quota at {used / cap:.0%} — ingestion may starve")
        elif r.get("errors"):
            _warn(f"API-Football status: {r['errors']}")
    except Exception:
        pass

    print(f"\n{'FAIL' if alerts else 'OK'} — {len(alerts)} alert(s), {len(warns)} warning(s)")
    sys.exit(1 if alerts else 0)


if __name__ == "__main__":
    main()
