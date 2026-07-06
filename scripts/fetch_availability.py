"""
Fetch current player availability (injuries + suspensions) for the World Cup
from API-Football /injuries and write wc_unavailable.json — consumed by
simulate_wc.py to drop unavailable players from the Golden-Boot shares.

The /injuries feed for league=1 (FIFA World Cup) returns one row per player per
affected fixture, with a reason ("Calf Injury", "Suspended", "Red Card", …).
We dedupe to one entry per (team, player) and persist the latest reason.

Single cheap request. Idempotent (overwrites the JSON each run).

Usage:
  docker compose exec backend python scripts/fetch_availability.py
  docker compose exec backend python scripts/fetch_availability.py --league 1 --season 2026
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "backend" / "data" / "models" / "national" / "wc_unavailable.json"

sys.path.insert(0, str(ROOT))
from scripts._http_retry import get_with_retry  # noqa: E402
API_BASE = "https://v3.football.api-sports.io"
API_KEY  = os.getenv("API_SPORTS_KEY", "")
HEADERS  = {"x-apisports-key": API_KEY}

# API-Football team name → our canonical DB name (mirrors fetch_player_stats).
API_TO_CANON = {
    "Czechia":              "Czech Republic",
    "Congo DR":             "DR Congo",
    "USA":                  "United States",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Türkiye":              "Turkey",
    "Cape Verde Islands":   "Cape Verde",
    "Korea Republic":       "South Korea",
    "IR Iran":              "Iran",
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch WC injuries/suspensions")
    ap.add_argument("--league", type=int, default=1, help="API-Football league id (1 = World Cup)")
    ap.add_argument("--season", type=int, default=2026, help="Season (WC year)")
    args = ap.parse_args()

    if not API_KEY:
        print("[error] API_SPORTS_KEY not set."); sys.exit(1)

    try:
        r = get_with_retry(f"{API_BASE}/injuries", headers=HEADERS,
                           params={"league": args.league, "season": args.season}, timeout=20)
        r.raise_for_status()
        resp = r.json().get("response", [])
    except Exception as e:
        print(f"[error] /injuries failed: {e}"); sys.exit(1)

    # Dedupe to one entry per (team, player_id), keeping the latest reason.
    by_team: dict[str, dict[int, dict]] = {}
    for it in resp:
        pl = it.get("player") or {}
        tm = it.get("team") or {}
        name = pl.get("name")
        pid = pl.get("id")
        if not name or pid is None:
            continue
        team = API_TO_CANON.get(tm.get("name", ""), tm.get("name", ""))
        by_team.setdefault(team, {})[pid] = {
            "player": name,
            "player_id": pid,
            "type": pl.get("type"),
            "reason": pl.get("reason"),
        }

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "league": args.league,
        "season": args.season,
        "teams": {team: list(players.values()) for team, players in sorted(by_team.items())},
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    total = sum(len(v) for v in out["teams"].values())
    print(f"✓ {total} unavailable players across {len(out['teams'])} teams → {OUT_PATH}")
    for team, players in list(out["teams"].items())[:10]:
        print(f"  {team}: {', '.join(p['player'] for p in players)}")


if __name__ == "__main__":
    main()
