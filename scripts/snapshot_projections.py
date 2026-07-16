"""
Daily snapshot of every competition's season projection.

For each projectable competition it:
  1. runs the Monte Carlo (domestic title/relegation, or European champion),
  2. attaches the de-vigged bookmaker title market where one is offered
     (best-effort — usually absent off-season),
  3. re-writes the projection into the Redis cache (so the live panel carries
     the market column), and
  4. appends one dated row to backend/data/models/projections/{league}.jsonl,
     which powers the odds-over-time chart.

One snapshot per UTC day (a re-run replaces today's). Mirrors the World Cup
champion-odds history, generalised to every league and cup.

Usage:
  docker compose exec backend python scripts/snapshot_projections.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HIST_DIR = ROOT / "backend" / "data" / "models" / "projections"

COMPETITIONS = [
    "EPL", "LaLiga", "SerieA", "Bundesliga", "Ligue1", "Championship",
    "LeagueOne", "GreekSL", "Eredivisie", "PrimeiraLiga", "BrazilSerieA",
    "CL", "EL", "ECL",
]


def _primary_prob(team: dict) -> float:
    """The headline number that varies by competition type: title for a league,
    champion for a European cup."""
    return team.get("p_title", team.get("p_champion", 0.0)) or 0.0


def _attach_market(proj: dict, league: str) -> None:
    """Add `market_pct` to each projected team from the bookmaker outright, when
    one is offered. No-op (leaves market_pct absent) otherwise."""
    from backend.app.ml.odds_analysis_service import _teams_match
    from backend.app.ml.title_market import fetch_title_market

    market = fetch_title_market(league)
    if not market:
        return
    for team in proj["teams"]:
        for mkt_name, prob in market.items():
            if _teams_match(mkt_name, team["team"]):
                team["market_pct"] = round(prob, 4)
                break


def _write_history(league: str, proj: dict) -> int:
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    path = HIST_DIR / f"{league}.jsonl"
    today = datetime.now(timezone.utc).date().isoformat()

    snapshot = {
        "date":              today,
        "league":            league,
        "season":            proj.get("season"),
        "matches_remaining": proj.get("matches_remaining"),
        # Only the movers worth charting; keep the file small.
        "teams": [
            {"team": t["team"], "prob": _primary_prob(t), "market_pct": t.get("market_pct")}
            for t in proj["teams"][:12]
        ],
    }

    rows: list[dict] = []
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("date") != today:      # replace today's on a re-run
                rows.append(row)
    rows.append(snapshot)
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def main() -> None:
    from backend.app.cache import cache_set
    from backend.app.database import SessionLocal
    from backend.app.ml.european_sim import simulate_european
    from backend.app.ml.league_sim import simulate_league
    from backend.app.ml.standings import EUROPEAN_STRUCTURE

    db = SessionLocal()
    done = skipped = 0
    try:
        for lg in COMPETITIONS:
            proj = (simulate_european(db, lg) if lg in EUROPEAN_STRUCTURE
                    else simulate_league(db, lg))
            if not proj:
                skipped += 1
                print(f"  {lg:14s} n/a")
                continue
            _attach_market(proj, lg)
            # Overwrite the cache the page reads, now enriched with the market.
            cache_set(f"league_projection:{lg}", proj, 25 * 3600)
            n = _write_history(lg, proj)
            has_mkt = any("market_pct" in t for t in proj["teams"])
            print(f"  {lg:14s} snapshot #{n}"
                  + ("  +market" if has_mkt else "  (model only)"))
            done += 1
    finally:
        db.close()
    print(f"\nDone. {done} competitions snapshotted, {skipped} n/a.")


if __name__ == "__main__":
    main()
