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
  4b. clubelo.json               — cold-start Elo snapshot gone stale (dead upstream)
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
CLUBELO  = ROOT / "backend" / "data" / "clubelo.json"

# How old the ClubElo snapshot may get before it is worth saying so. ClubElo
# publishes daily, so a gap is always a failed fetch, never a quiet week
# upstream. The pull is deliberately non-fatal in run_daily.sh (step 5c), which
# is right — but it also means a dead upstream shows up only as one [error] line
# buried mid-run, and cold-start Elo silently decays back toward the flat 1500
# default. These thresholds put it in the summary instead.
CLUBELO_WARN_DAYS  = 3
CLUBELO_ALERT_DAYS = 10

# Leagues whose teams SHOULD have stats coverage (mirrors fetch_club_team_stats).
# DOMESTIC teams missing stats = ALERT (our ingestion is broken).
# EURO-only teams (CL/EL/ECL qualifier minnows) = warn — API-Football often has
# no statistics for their domestic micro-leagues, so absence is expected until
# they play a covered European tie.
DOMESTIC = {"EPL", "Championship", "LeagueOne", "LaLiga", "SerieA", "Bundesliga",
            "Ligue1", "GreekSL", "PrimeiraLiga", "Eredivisie", "BrazilSerieA",
            "Belgium", "Turkey", "Scotland", "Denmark", "Sweden", "Norway", "Poland", "Austria", "Switzerland", "Romania", "Ireland", "Finland"}
EURO     = {"CL", "EL", "ECL"}
TRACKED  = DOMESTIC | EURO

# Clubs whose fixtures carry NO statistics upstream, verified against the API.
#
# These are not our bug and no amount of ingestion will fix them, so raising a
# domestic-league ALERT every morning for one of them trains the reader to
# ignore the whole report — which is how a real outage gets missed. They stay
# VISIBLE as warnings, with the reason, rather than being silenced.
#
# Each entry records the check that put it here so it can be re-tested cheaply:
#   GET /fixtures?team=<id>&last=4  →  GET /fixtures/statistics?fixture=<id>
# and if the response now has 2 blocks, delete the line.
NO_UPSTREAM_STATS: dict[str, str] = {
    # 2026-08-26: emptied. Every entry that lived here has started carrying
    # stats, so keeping any of them would silence a real gap rather than
    # explain an unfixable one — which is exactly what the note above warns
    # against. Re-verified against the DB on 2026-08-26 with the stored name
    # each check actually queries:
    #   SJK           team_rows=2  player_rows=42  (was: no statistics at all)
    #   Iraklis 1908  team_rows=1  player_rows=22  (self-healed after 22 Aug)
    #   Kalamata      team_rows=1  player_rows=21  (self-healed after 22 Aug)
    # The two Greek clubs were filed with an explicit "re-check after 22 Aug";
    # this is that re-check.
}

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
            """ALERT for domestic-league teams, warn for euro-qualifier-only ones.

            A club in NO_UPSTREAM_STATS is always a warn: the data does not
            exist to ingest, so an alert would be asking someone to fix the
            weather.
            """
            if team in NO_UPSTREAM_STATS:
                return _warn
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

        # 4b. ClubElo cold-start snapshot freshness
        #
        # This is the fallback for exactly the teams flagged just above: the
        # ones with no completed match, whose Elo would otherwise be a flat
        # 1500. If the snapshot stops being refreshed, that fallback quietly
        # stops describing the present — the ratings are still applied, they
        # are just increasingly wrong — and nothing in this report said so.
        # api.clubelo.com went dark on 2026-08-12 and the snapshot had aged two
        # weeks before anyone noticed.
        if not CLUBELO.exists():
            _warn("clubelo.json missing — cold-start Elo seeding is off entirely "
                  "(cold-start teams fall back to a flat 1500)")
        else:
            try:
                snap = json.loads(CLUBELO.read_text())
                as_of = date.fromisoformat(snap["as_of"])
                n_clubs = snap.get("count", "?")
            except (OSError, ValueError, KeyError, TypeError) as e:
                _warn(f"clubelo.json unreadable ({type(e).__name__}) — cold-start Elo "
                      "seeding is off entirely")
            else:
                age = (date.today() - as_of).days
                print(f"[clubelo] cold-start snapshot {as_of} ({n_clubs} clubs), {age} day(s) old")
                if age >= CLUBELO_ALERT_DAYS:
                    _alert(f"ClubElo snapshot is {age} days old (as of {as_of}) — "
                           f"api.clubelo.com has been failing every run since. "
                           f"Cold-start teams are seeded from stale ratings; check "
                           f"whether the endpoint moved (scripts/fetch_clubelo.py)")
                elif age >= CLUBELO_WARN_DAYS:
                    _warn(f"ClubElo snapshot is {age} days old (as of {as_of}) — "
                          f"the daily fetch has failed for {age} run(s)")

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

        # 9. one match, two fixture rows, two dates
        #
        # dedupe_fixtures.py collapses same-DATE duplicates; this catches the
        # other shape — the same tie held on two dates, which is what a
        # postponement outside the reschedule window or two feeds disagreeing
        # leaves behind. It is not cosmetic: on 2026-08-17 the day's 'safe'
        # accumulator carried PAOK–Levadiakos as two independent legs and
        # multiplied one probability by itself. The builder now dedupes by tie
        # so that symptom cannot return, but the stale row is still a fixture
        # advertised on a date it will not be played on, and its result never
        # arrives. Ordered pair on purpose: a two-legged cup tie swaps the
        # venue, so it is a different key, not a duplicate.
        dupes = db.execute(text(
            "SELECT a.league, a.home_team, a.away_team, "
            "       a.id AS id_a, a.match_date AS date_a, "
            "       b.id AS id_b, b.match_date AS date_b "
            "FROM matches a JOIN matches b "
            "  ON a.league = b.league AND a.home_team = b.home_team "
            " AND a.away_team = b.away_team AND a.id < b.id "
            "WHERE a.result IS NULL AND b.result IS NULL "
            "  AND a.match_date >= :today "
            "  AND ABS(b.match_date - a.match_date) BETWEEN 1 AND 21 "
            "ORDER BY a.match_date"),
            {"today": date.today()}).fetchall()
        # 10. one club name, two countries — in the DATABASE
        #
        # The club-identity audit reads the CSVs, so it can only see a fusion
        # that exists in the training data. This one lived in the fixture table
        # alone: "Vitoria SC" resolved to "Vitoria", which in our CSVs is the
        # BRAZILIAN club, so twelve PrimeiraLiga fixtures were stored under it
        # and priced off a Brazilian side's Elo while Portugal's Vitória SC sat
        # under "Guimaraes" with 528 rows nobody was reading. Invisible to
        # every check we had, for months.
        from backend.app.ml.league_registry import LEAGUE_COUNTRY_TIER

        rows = db.execute(text(
            "SELECT home_team AS team, league FROM matches "
            "UNION SELECT away_team AS team, league FROM matches")).fetchall()
        countries: dict[str, set] = {}
        for r in rows:
            country = (LEAGUE_COUNTRY_TIER.get(r.league) or (None,))[0]
            if country:
                countries.setdefault(r.team, set()).add(country)
        for team, seen in sorted(countries.items()):
            if len(seen) > 1:
                _alert(f"club identity: '{team}' plays in {sorted(seen)} — one "
                       f"name, two countries; its Elo and form are the two "
                       f"clubs averaged together")

        for d in dupes:
            _alert(f"duplicate fixture: {d.league} {d.home_team} vs {d.away_team} "
                   f"stored twice — id {d.id_a} on {d.date_a} and id {d.id_b} on "
                   f"{d.date_b}; one is stale and will never be scored")
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

    # The Odds API credits. /sports is not billed, and its response headers
    # carry the account's usage, so this costs nothing to ask.
    #
    # Worth an ALERT rather than a warning because running out is silent from
    # the outside and looks like a bug: on 2026-08-17 the month's 20,000 credits
    # were spent by 08:00, every /odds call came back 401 OUT_OF_USAGE_CREDITS,
    # and the consequences showed up three layers away — no bookmaker price on
    # any fixture past today, so nearly every accumulator leg fell back to our
    # own fair odds, so the estimated-price cap could not be satisfied and the
    # ladder cut two slips instead of five. Nothing on the page said why.
    try:
        r = _rq.get("https://api.the-odds-api.com/v4/sports/",
                    params={"apiKey": os.getenv("ODDS_API_KEY", "")}, timeout=10)
        used = r.headers.get("x-requests-used")
        left = r.headers.get("x-requests-remaining")
        if left is not None:
            left_n, used_n = int(float(left)), int(float(used or 0))
            print(f"[quota] The Odds API: {used_n:,} used, {left_n:,} remaining")
            if left_n <= 0:
                _alert("The Odds API is OUT OF CREDITS — every /odds call returns "
                       "401, so no fixture can carry a bookmaker price and the "
                       "ticket ladder falls back to estimated odds")
            elif left_n < 500:
                _warn(f"The Odds API down to {left_n:,} credits")
    except Exception:
        pass

    # Wording matters here: this verdict is about DATA COMPLETENESS, not about
    # whether the pipeline ran. It stopped gating the heartbeat on 2026-07-31,
    # but kept printing "FAIL", so a run that completed every step still ended
    # with a red-looking line and a push that read as another failure.
    print(f"\n{'DATA GAPS' if alerts else 'DATA OK'} — "
          f"{len(alerts)} alert(s), {len(warns)} warning(s)")
    sys.exit(1 if alerts else 0)


if __name__ == "__main__":
    main()
