"""
Fetch official World Cup 2026 squads from API-Football (api-sports.io).

For every national team with upcoming WC fixtures (from martj42 results.csv):
  1. Resolve the API-Football national-team id   (/teams?search=...)
  2. Fetch the current squad                      (/players/squads?team=...)

Output:
  backend/data/raw/international/wc_squads.json
    {team: {"team_id": int, "players": ["L. Messi", ...], "fetched_at": iso}}
  backend/data/raw/international/wc_team_ids.json   (id cache — saves API quota)

simulate_wc.py uses this to restrict Golden Boot shares to actually-called-up
players. Teams that fail to resolve are simply absent → sim falls back to
unfiltered shares for them.

Quota: ~10 req/min on the free tier — the script sleeps between calls.
First run ≈ 2 calls/team; with the id cache, re-runs ≈ 1 call/team.

Usage:
  docker compose exec backend python scripts/fetch_wc_squads.py
  docker compose exec backend python scripts/fetch_wc_squads.py --max-age-days 7
  docker compose exec backend python scripts/fetch_wc_squads.py --force
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR    = ROOT / "backend" / "data" / "raw" / "international"
SQUADS_PATH = DATA_DIR / "wc_squads.json"
IDS_PATH    = DATA_DIR / "wc_team_ids.json"

API_BASE = "https://v3.football.api-sports.io"
API_KEY  = os.getenv("API_SPORTS_KEY", "")

# Pro plan: 300 requests/minute → 0.3s is comfortably under it.
# (Free tier is 10/min — set ~6.5s there.)
SLEEP_BETWEEN_CALLS = 0.3

# Our (martj42) name → API-Football search term, where they differ.
_SEARCH_ALIASES = {
    "Bosnia and Herzegovina": "Bosnia",
    "United States":  "USA",
    "South Korea":    "South Korea",
    "DR Congo":       "Congo DR",
    "Ivory Coast":    "Ivory Coast",
    "Cape Verde":     "Cape Verde Islands",
    "Curacao":        "Curacao",
    "China PR":       "China",
}


def _get(path: str, params: dict) -> list:
    resp = requests.get(
        f"{API_BASE}{path}",
        headers={"x-apisports-key": API_KEY},
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    errs = body.get("errors")
    if errs and (errs if isinstance(errs, list) else list(errs.values())):
        raise RuntimeError(f"API error for {path} {params}: {errs}")
    return body.get("response", [])


def load_wc_teams() -> list[str]:
    df = pd.read_csv(DATA_DIR / "results.csv")
    wc = df[(df["tournament"] == "FIFA World Cup") & (df["home_score"].isna())]
    return sorted(set(wc["home_team"]) | set(wc["away_team"]))


def _strip_accents(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def _search_term(team: str) -> str:
    if team in _SEARCH_ALIASES:
        return _SEARCH_ALIASES[team]
    # Accent-insensitive alias lookup ('Curaçao' → alias key 'Curacao').
    t = _strip_accents(team).lower()
    for k, v in _SEARCH_ALIASES.items():
        if _strip_accents(k).lower() == t:
            return v
    return team


def resolve_team_id(team: str, id_cache: dict) -> int | None:
    if team in id_cache:
        return id_cache[team]
    search = _search_term(team)
    try:
        results = _get("/teams", {"search": search})
    except Exception as e:
        print(f"  [ids] search failed for {team!r}: {e}")
        return None
    finally:
        time.sleep(SLEEP_BETWEEN_CALLS)
    # Prefer exact-name national sides; fall back to any national side.
    nationals = [r for r in results if r.get("team", {}).get("national")]
    exact = [r for r in nationals
             if r["team"]["name"].lower() in (team.lower(), search.lower())]
    pick = (exact or nationals or [None])[0]
    if not pick:
        print(f"  [ids] no national team found for {team!r} (search={search!r})")
        return None
    tid = int(pick["team"]["id"])
    id_cache[team] = tid
    return tid


def fetch_squad(team_id: int) -> list[str]:
    try:
        response = _get("/players/squads", {"team": team_id})
    finally:
        time.sleep(SLEEP_BETWEEN_CALLS)
    players: list[str] = []
    for squad in response:
        for p in squad.get("players", []):
            if p.get("name"):
                players.append(p["name"])
    return players


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch WC 2026 squads from API-Football")
    ap.add_argument("--max-age-days", type=float, default=None,
                    help="Skip entirely if wc_squads.json is fresher than this many days")
    ap.add_argument("--force", action="store_true", help="Refetch even if file is fresh")
    args = ap.parse_args()

    if not API_KEY:
        print("API_SPORTS_KEY not set — cannot fetch squads. Exiting.")
        return

    if args.max_age_days is not None and not args.force and SQUADS_PATH.exists():
        age_days = (time.time() - SQUADS_PATH.stat().st_mtime) / 86400
        if age_days < args.max_age_days:
            print(f"wc_squads.json is {age_days:.1f} d old (< {args.max_age_days}) — skipping fetch.")
            return

    teams = load_wc_teams()
    if not teams:
        print("No upcoming WC fixtures in results.csv — nothing to fetch.")
        return
    print(f"{len(teams)} WC teams. Resolving ids + fetching squads "
          f"(~{SLEEP_BETWEEN_CALLS}s/call for rate limit)…")

    id_cache: dict = {}
    if IDS_PATH.exists():
        id_cache = json.loads(IDS_PATH.read_text())

    squads: dict = {}
    if SQUADS_PATH.exists():
        squads = json.loads(SQUADS_PATH.read_text())

    fetched = failed = 0
    for team in teams:
        tid = resolve_team_id(team, id_cache)
        IDS_PATH.write_text(json.dumps(id_cache, indent=2, ensure_ascii=False))
        if tid is None:
            failed += 1
            continue
        try:
            players = fetch_squad(tid)
        except Exception as e:
            print(f"  [squad] fetch failed for {team} (id {tid}): {e}")
            failed += 1
            continue
        if len(players) < 15:
            # Partial/placeholder squad — don't store, sim will fall back.
            print(f"  [squad] {team}: only {len(players)} players — ignored.")
            failed += 1
            continue
        squads[team] = {
            "team_id":    tid,
            "players":    players,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        SQUADS_PATH.write_text(json.dumps(squads, indent=2, ensure_ascii=False))
        fetched += 1
        print(f"  ✓ {team}: {len(players)} players")

    print(f"\nDone: {fetched} squads fetched, {failed} failed/skipped → {SQUADS_PATH}")


if __name__ == "__main__":
    main()
