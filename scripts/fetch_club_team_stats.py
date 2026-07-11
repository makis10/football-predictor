"""
Ingest per-team, per-fixture CLUB statistics (corners + cards + shots) from
API-Football into team_match_stats — the foundation for club team props, so
club match pages reach parity with the national ones.

Team-id resolution is LEAGUE-BASED (one /teams?league&season call per league,
not per-team name search): far cheaper and unambiguous. API-Football names are
matched to our DB names via a slug + a small override table; unmatched teams are
logged so overrides can be added.

Budget-aware. Idempotent (unique fixture_id+team; done fixtures skipped).

Usage:
  docker compose exec backend python scripts/fetch_club_team_stats.py --days-ahead 5 --last 8
  docker compose exec backend python scripts/fetch_club_team_stats.py --refresh-ids
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts._http_retry import get_with_retry  # noqa: E402

API_BASE = "https://v3.football.api-sports.io"
API_KEY  = os.getenv("API_SPORTS_KEY", "")
HEADERS  = {"x-apisports-key": API_KEY}
ID_CACHE = ROOT / "backend" / "data" / "models" / "club_team_ids.json"
# our DB name → the exact name API-Football uses (= the name stored in
# team_match_stats / player_match_stats rows). Learned automatically from
# fixture responses; consumed by club_props._api_name so the read side never
# needs slug guessing for teams we ingest.
NAME_MAP = ROOT / "backend" / "data" / "models" / "club_name_map.json"

# our league code → API-Football league id (mirrors odds_analysis_service).
LEAGUE_IDS = {
    "EPL": 39, "Championship": 40, "LeagueOne": 41, "LaLiga": 140, "SerieA": 135,
    "Bundesliga": 78, "Ligue1": 61, "GreekSL": 197, "PrimeiraLiga": 94,
    "Eredivisie": 88, "CL": 2, "EL": 3, "ECL": 848,
}

# our DB name → API-Football name, where the slug match can't bridge them.
NAME_OVERRIDES = {
    "Man City": "Manchester City", "Man United": "Manchester United",
    "Nott'm Forest": "Nottingham Forest", "Sheffield United": "Sheffield Utd",
    "Ipswich": "Ipswich", "Wolves": "Wolves", "Spurs": "Tottenham",
    "Paris SG": "Paris Saint Germain", "Ath Bilbao": "Athletic Club",
    "Ath Madrid": "Atletico Madrid", "Betis": "Real Betis",
    "Sociedad": "Real Sociedad", "Inter": "Inter", "AC Milan": "AC Milan",
    "Bayern Munich": "Bayern München", "Dortmund": "Borussia Dortmund",
    "Stuttgart": "VfB Stuttgart", "Ein Frankfurt": "Eintracht Frankfurt",
    "Greuther Furth": "SpVgg Greuther Fürth", "Leverkusen": "Bayer Leverkusen",
    "Mainz": "FSV Mainz 05", "Wolfsburg": "VfL Wolfsburg",
    "Hoffenheim": "1899 Hoffenheim", "Gladbach": "Borussia Mönchengladbach",
    "AEK": "AEK Athens FC", "PAOK": "PAOK", "Leganes": "Leganes",
    # GreekSL — API names carry city suffixes / different spellings
    "Olympiakos": "Olympiakos Piraeus", "Aris": "Aris Thessalonikis",
    "Levadeiakos": "Levadiakos", "OFI Crete": "OFI",
    # Eredivisie — API prefixes (PEC/ADO/Fortuna/…) that the slug can't bridge
    "Zwolle": "PEC Zwolle", "Den Haag": "ADO Den Haag",
    "Sittard": "Fortuna Sittard", "Go Ahead": "GO Ahead Eagles",
    "Sparta": "Sparta Rotterdam",
    # Friendly opponents / lower divisions — resolved via /teams?search fallback
    "Graafschap": "De Graafschap", "Volendam": "FC Volendam",
    "Bochum": "VfL Bochum", "Almere City": "Almere City FC",
    "Accrington": "Accrington ST",
}


def _slug(name: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", (name or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", s.lower())


class Budget:
    def __init__(self, cap): self.cap, self.used = cap, 0
    def ok(self): return self.used < self.cap
    def hit(self): self.used += 1


def _get(path, params, budget):
    budget.hit()
    r = get_with_retry(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    body = r.json()
    errs = body.get("errors")
    # API-Football signals quota/plan errors as HTTP 200 + an errors dict —
    # without this check an exhausted quota silently looks like "0 fixtures".
    if errs:
        if isinstance(errs, dict) and "requests" in errs:
            raise SystemExit(f"[fatal] API-Football daily quota exhausted: {errs['requests']}")
        raise RuntimeError(f"API-Football error: {errs}")
    return body



def _to_int(v):
    try:
        return int(str(v).replace("%", "")) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def build_id_cache(our_teams: set[str], season: int, budget: Budget) -> dict:
    """Map our team names → API-Football team ids, league by league."""
    slug_to_name = {_slug(t): t for t in our_teams}
    override_slug = {_slug(k): _slug(v) for k, v in NAME_OVERRIDES.items()}
    # invert: API-slug we should accept for each our-name
    api_alias = {_slug(v): k for k, v in NAME_OVERRIDES.items()}

    cache: dict[str, int] = {}
    matched, unmatched = set(), []
    for code, lid in LEAGUE_IDS.items():
        if not budget.ok():
            break
        try:
            resp = _get("/teams", {"league": lid, "season": season}, budget).get("response", [])
            # In July/August the new season may not be registered on API-Football
            # yet (empty list) — fall back to the previous season's team list
            # (same team ids, only promoted/relegated sides differ).
            if not resp and budget.ok():
                resp = _get("/teams", {"league": lid, "season": season - 1}, budget).get("response", [])
                if resp:
                    print(f"  [info] /teams {code}: season {season} empty — using {season - 1}")
        except Exception as e:
            print(f"  [warn] /teams {code}: {e}"); continue
        for t in resp:
            api_name = t["team"]["name"]; api_id = t["team"]["id"]
            aslug = _slug(api_name)
            our = slug_to_name.get(aslug) or api_alias.get(aslug)
            if our:
                cache[our] = api_id
                matched.add(our)
    # Fallback: /teams?search= for teams outside the tracked leagues (friendly
    # opponents from lower divisions, e.g. Chesterfield, De Graafschap). Only
    # accept a result whose slug matches the target (or its override) exactly —
    # a fuzzy hit on the wrong club would poison the cache.
    for team in sorted(our_teams - matched):
        if not budget.ok():
            break
        target = NAME_OVERRIDES.get(team, team)
        if len(target) < 3:
            continue  # API requires >= 3 chars
        try:
            resp = _get("/teams", {"search": target}, budget).get("response", [])
        except Exception as e:
            print(f"  [warn] /teams search '{team}': {e}"); continue
        tslug = _slug(target)
        hit = next((t for t in resp if _slug(t["team"]["name"]) == tslug), None)
        if hit is None and len(resp) == 1:
            hit = resp[0]  # unambiguous single result
        if hit:
            cache[team] = hit["team"]["id"]
            matched.add(team)
            print(f"  [search] {team} → {hit['team']['name']} (id {hit['team']['id']})")

    unmatched = sorted(our_teams - matched)
    print(f"  resolved {len(matched)}/{len(our_teams)} club teams "
          f"({budget.used} API calls).")
    if unmatched:
        print(f"  [unmatched — add to NAME_OVERRIDES] {unmatched[:25]}")
    return cache


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest club team match stats")
    ap.add_argument("--days-ahead", type=int, default=5, help="Upcoming window for target teams")
    ap.add_argument("--last", type=int, default=8, help="Recent finished fixtures per team")
    ap.add_argument("--season", type=int, default=None, help="Season start year (default auto)")
    ap.add_argument("--max-requests", type=int, default=1200)
    ap.add_argument("--refresh-ids", action="store_true", help="Rebuild the team-id cache")
    args = ap.parse_args()

    if not API_KEY:
        print("[error] API_SPORTS_KEY not set."); sys.exit(1)

    season = args.season or (date.today().year if date.today().month >= 7 else date.today().year - 1)

    from sqlalchemy import text
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from backend.app.database import SessionLocal
    from backend.app.models.team_match_stats import TeamMatchStats

    budget = Budget(args.max_requests)
    db = SessionLocal()
    try:
        # Teams playing in the upcoming window (club leagues only).
        hi = (date.today() + timedelta(days=args.days_ahead)).isoformat()
        rows = db.execute(text(
            "SELECT DISTINCT home_team FROM matches WHERE home_goals IS NULL "
            "AND match_date BETWEEN :lo AND :hi "
            "UNION SELECT DISTINCT away_team FROM matches WHERE away_goals IS NULL "
            "AND match_date BETWEEN :lo AND :hi"
        ), {"lo": date.today().isoformat(), "hi": hi}).fetchall()
        target = sorted({r[0] for r in rows})
        print(f"{len(target)} club teams with upcoming fixtures.")

        # Team-id cache (rebuild if asked or missing).
        cache = {}
        if ID_CACHE.exists() and not args.refresh_ids:
            cache = json.loads(ID_CACHE.read_text())
        # Treat null-valued entries as missing too: earlier runs cached
        # unresolved teams as None, which permanently blocked re-resolution
        # (the Greek league outage — see 2026-07-11).
        missing = [t for t in target if cache.get(t) is None]
        if missing or args.refresh_ids:
            cache = {**cache, **build_id_cache(set(target) | set(cache), season, budget)}
            ID_CACHE.parent.mkdir(parents=True, exist_ok=True)
            ID_CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))

        have = {r[0] for r in db.execute(
            text("SELECT DISTINCT fixture_id FROM team_match_stats")).fetchall()}

        n_fx = n_rows = 0
        name_map: dict[str, str] = {}
        if NAME_MAP.exists():
            try:
                name_map = json.loads(NAME_MAP.read_text())
            except Exception:
                name_map = {}
        for team in target:
            if not budget.ok():
                print("  [budget] cap reached."); break
            tid = cache.get(team)
            if not tid:
                continue
            try:
                fx = _get("/fixtures", {"team": tid, "last": args.last}, budget).get("response", [])
            except Exception as e:
                print(f"  [warn] fixtures {team}: {e}"); continue
            # Learn the exact API-Football spelling for this team (the name the
            # stats rows are stored under) from the fixture header — no extra
            # API credits, keeps club_props._api_name exact instead of fuzzy.
            for f in fx:
                for side in ("home", "away"):
                    t_blk = f["teams"][side]
                    if t_blk["id"] == tid and t_blk.get("name"):
                        if name_map.get(team) != t_blk["name"]:
                            name_map[team] = t_blk["name"]
                        break
                else:
                    continue
                break
            for f in fx:
                if not budget.ok():
                    break
                fid = f["fixture"]["id"]
                if fid in have or f["fixture"]["status"]["short"] not in ("FT", "AET", "PEN"):
                    continue
                try:
                    sresp = _get("/fixtures/statistics", {"fixture": fid}, budget).get("response", [])
                except Exception:
                    continue
                if len(sresp) != 2:
                    continue
                th, ta = f["teams"]["home"], f["teams"]["away"]
                names = {b["team"]["id"]: b["team"]["name"] for b in sresp}
                for block in sresp:
                    bid = block["team"]["id"]
                    st = {s.get("type"): s.get("value") for s in (block.get("statistics") or [])}
                    row = {
                        "fixture_id": fid, "match_date": f["fixture"]["date"][:10],
                        "league_id": f["league"]["id"],
                        "team": names.get(bid, ""), "opponent": names.get(ta["id"] if bid == th["id"] else th["id"], ""),
                        "is_home": bid == th["id"],
                        "corners": _to_int(st.get("Corner Kicks")),
                        "possession": _to_int(st.get("Ball Possession")),
                        "shots_total": _to_int(st.get("Total Shots")),
                        "shots_on": _to_int(st.get("Shots on Goal")),
                        "fouls": _to_int(st.get("Fouls")),
                        "yellow_cards": _to_int(st.get("Yellow Cards")),
                        "red_cards": _to_int(st.get("Red Cards")),
                    }
                    db.execute(pg_insert(TeamMatchStats).values(**row)
                               .on_conflict_do_nothing(constraint="uq_team_match_stats"))
                db.commit()
                have.add(fid); n_fx += 1; n_rows += 2
            print(f"  {team}: {n_fx} fixtures so far  [req {budget.used}]")
        NAME_MAP.write_text(json.dumps(name_map, indent=2, ensure_ascii=False, sort_keys=True))
        print(f"\nDone. {n_fx} new fixtures, {n_rows} rows, {budget.used} API requests. "
              f"Name map: {len(name_map)} teams → {NAME_MAP.name}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
