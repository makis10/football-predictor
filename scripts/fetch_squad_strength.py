"""
Compute a SQUAD-STRENGTH score per national team from the leagues its
called-up players actually play in — pure sporting data, no bookmaker odds.

WHY
---
The international results-Elo is confederation-siloed and blind to player
quality (see backend/app/ml/national/league_strength.py). This script transfers
"which league each player plays in" into a single per-team number that the
national model uses to build a talent-adjusted Elo at inference time.

Flow:
  1. Teams = keys of wc_squads.json (canonical names + API-Football team_id).
  2. /players/squads?team={id} → current squad with player ids.
  3. /players?id={pid}&season={SEASON} → that player's clubs/leagues this
     season; take the domestic LEAGUE with the most minutes (cups skipped).
  4. league_strength.league_coef() → coefficient per player.
  5. squad strength = mean of the team's TOP-N player coefficients.
  6. Save backend/data/raw/international/squad_strength.json + report unknown
     leagues (those that fell back to DEFAULT) for auditing the coefficients.

Budget-aware (API-Football Pro = 7500/day). ~1 + 26 requests per team.

Usage:
  docker compose exec backend python scripts/fetch_squad_strength.py
  docker compose exec backend python scripts/fetch_squad_strength.py --teams Ghana Panama Germany
  docker compose exec backend python scripts/fetch_squad_strength.py --season 2025 --max-requests 1500
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Reuse the API client + budget + name maps from the player-stats ingester.
from scripts.fetch_player_stats import Budget, _get  # noqa: E402
from backend.app.ml.national.league_strength import league_coef, DEFAULT_STRENGTH  # noqa: E402

SQUADS_JSON   = ROOT / "backend" / "data" / "raw" / "international" / "wc_squads.json"
OUT_JSON      = ROOT / "backend" / "data" / "raw" / "international" / "squad_strength.json"

TOP_N = 16        # average the best-N players' leagues (≈ likely XI + key subs)
MIN_RATED = 6     # below this many rated players, mark low-confidence


def _primary_league_coef(stats: list) -> tuple[float | None, str, str, int | None]:
    """From a player's /players statistics, pick the domestic league with the
    most minutes and return (coef, league_name, country, league_id).
    Cups are skipped (league_coef returns None)."""
    best = None  # (minutes, coef, name, country, lid)
    for s in stats or []:
        lg = s.get("league") or {}
        games = s.get("games") or {}
        mins = games.get("minutes") or 0
        apps = games.get("appearences") or 0
        if not mins and not apps:
            continue
        lid = lg.get("id")
        name = lg.get("name") or ""
        country = lg.get("country") or ""
        coef = league_coef(lid, name, country)
        if coef is None:        # cup → no league signal
            continue
        score = mins if mins else apps * 30
        if best is None or score > best[0]:
            best = (score, coef, name, country, lid)
    if best is None:
        return None, "", "", None
    return best[1], best[2], best[3], best[4]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2025,
                    help="Club season (year it started; 2025 ≈ 2025/26)")
    ap.add_argument("--teams", nargs="*", default=None,
                    help="Limit to these canonical team names (default: all in wc_squads.json)")
    ap.add_argument("--max-requests", type=int, default=1600)
    ap.add_argument("--max-age-days", type=float, default=None,
                    help="Skip entirely if squad_strength.json is younger than this "
                         "(squads change slowly → cheap to call daily, runs ~weekly).")
    args = ap.parse_args()

    if args.max_age_days is not None and OUT_JSON.exists() and not args.teams:
        import time as _t
        age_days = (_t.time() - OUT_JSON.stat().st_mtime) / 86400.0
        if age_days < args.max_age_days:
            print(f"squad_strength.json is {age_days:.1f}d old (< {args.max_age_days}d) — skipping.")
            return

    squads = json.loads(SQUADS_JSON.read_text())
    teams = args.teams or list(squads.keys())
    budget = Budget(args.max_requests)

    out: dict[str, dict] = {}
    unknown_leagues: Counter = Counter()
    if OUT_JSON.exists():
        try:
            out = json.loads(OUT_JSON.read_text())
        except Exception:
            out = {}

    for team in teams:
        entry = squads.get(team)
        if not entry:
            print(f"  [skip] {team}: not in wc_squads.json")
            continue
        tid = entry.get("team_id")
        if not tid:
            print(f"  [skip] {team}: no team_id")
            continue
        if not budget.ok():
            print("  [budget] exhausted — stopping")
            break

        # Current squad with player ids. Empty response is usually a transient
        # rate-limit blip (300/min) — retry once after a pause.
        players = []
        for attempt in range(2):
            try:
                sq = _get("/players/squads", {"team": tid}, budget)
            except Exception as e:
                print(f"  [warn] squad fetch failed for {team}: {e}")
                break
            resp = sq.get("response") or []
            players = (resp[0].get("players") if resp else []) or []
            if players:
                break
            time.sleep(2.0)
        if not players:
            print(f"  [warn] {team}: empty squad from API")
            continue

        coefs: list[float] = []
        league_hits: Counter = Counter()
        for pl in players:
            if not budget.ok():
                break
            pid = pl.get("id")
            if pid is None:
                continue
            try:
                pdata = _get("/players", {"id": pid, "season": args.season}, budget)
                time.sleep(0.22)   # throttle under the 300/min rate limit
            except Exception:
                continue
            presp = pdata.get("response") or []
            stats = presp[0].get("statistics") if presp else []
            coef, lname, country, lid = _primary_league_coef(stats)
            if coef is None:
                continue
            coefs.append(coef)
            league_hits[f"{lname} ({country})"] += 1
            # flag leagues that hit the country/default fallback for audit
            from backend.app.ml.national.league_strength import LEAGUE_ID_STRENGTH
            if lid not in LEAGUE_ID_STRENGTH and abs(coef - DEFAULT_STRENGTH) < 1e-6:
                unknown_leagues[f"{lname} ({country}) id={lid}"] += 1

        if not coefs:
            print(f"  [warn] {team}: 0 rated players (coverage gap)")
            continue
        coefs.sort(reverse=True)
        top = coefs[:TOP_N]
        strength = round(sum(top) / len(top), 4)
        out[team] = {
            "strength":  strength,
            "n_rated":   len(coefs),
            "n_squad":   len(players),
            "coverage":  round(len(coefs) / max(1, len(players)), 2),
            "top_leagues": [lg for lg, _ in league_hits.most_common(4)],
            "low_confidence": len(coefs) < MIN_RATED,
        }
        print(f"  ✓ {team:<24} strength={strength:.3f}  "
              f"rated={len(coefs)}/{len(players)}  top={out[team]['top_leagues'][:2]}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nSaved {len(out)} teams → {OUT_JSON}   (requests used: {budget.used})")
    if unknown_leagues:
        print("\n⚠ Leagues that fell back to DEFAULT (consider adding to league_strength):")
        for lg, n in unknown_leagues.most_common(25):
            print(f"    {n:>3}×  {lg}")


if __name__ == "__main__":
    main()
