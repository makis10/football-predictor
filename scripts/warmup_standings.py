"""
Pre-compute the league table + season projection for every league.

The table is cheap; the Monte Carlo is not (~2 s for 10k runs over a full
double round-robin). Both only move when a result lands, so they are computed
here — after the daily results/prediction refresh — and served from Redis.
Without this the first visitor to a league page after each expiry pays for the
simulation.

Runs through the HTTP endpoints so the cache keys are exactly the ones a page
lookup will use.

Usage:
  docker compose exec backend python scripts/warmup_standings.py
"""
from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "http://localhost:8000"

# Every club league we cover. A 404 is a normal answer (no results yet, season
# over, or a play-off format the simulator refuses to guess at) — not a failure.
LEAGUES = [
    "EPL", "LaLiga", "SerieA", "Bundesliga", "Ligue1", "Championship",
    "LeagueOne", "GreekSL", "Eredivisie", "PrimeiraLiga", "BrazilSerieA",
    # UEFA: both endpoints 404 until the league phase is drawn (during the
    # summer qualifying rounds there is no table and no field to project).
    "CL", "EL", "ECL",
]


def _get(url: str) -> tuple[int, float]:
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            r.read()
            return r.status, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t0
    except Exception:
        return 0, time.time() - t0


def main() -> None:
    ok = skipped = failed = 0
    t_start = time.time()

    for lg in LEAGUES:
        for kind, url in (
            ("table",      f"{BASE}/standings/{lg}"),
            ("projection", f"{BASE}/standings/{lg}/projection"),
        ):
            status, secs = _get(url)
            if status == 200:
                ok += 1
                print(f"  {lg:14s} {kind:11s} warmed in {secs:.1f}s")
            elif status == 404:
                skipped += 1
                print(f"  {lg:14s} {kind:11s} n/a")
            else:
                failed += 1
                print(f"  {lg:14s} {kind:11s} [fail {status}] ({secs:.1f}s)")

    print(f"\nDone in {time.time() - t_start:.0f}s. "
          f"{ok} warmed, {skipped} n/a, {failed} failed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
