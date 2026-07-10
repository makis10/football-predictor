"""
Pre-warm the Redis analysis cache for upcoming fixtures.

Why
---
`/predictions/{id}/analysis` and `/national/predictions/{id}/analysis` fetch
bookmaker odds, injuries and a Groq narrative. Cold, that costs several seconds;
warm it is ~0.1 s. The match pages fetch the analysis client-side, so a cold
cache means the panel sits on a skeleton for the first visitor after every
expiry. This script pays that cost on a schedule instead of making a user pay it.

Why it calls the HTTP endpoints rather than the service functions
-----------------------------------------------------------------
The cache key embeds the model probabilities AS THE ENDPOINT ROUNDS THEM, after
injury adjustment and the blended-BTTS fix-ups:

    analysis:{match_id}:{home}:{draw}:{away}:{over}:{has_injuries}

Rebuilding those probabilities here would risk a key that differs in the last
decimal, and the warm entry would never be read. Driving the real endpoint
guarantees the key we populate is the key a visitor looks up.

The analysis endpoints are rate-limited to 20 calls / 60 s per client IP, so
requests are paced. Already-warm entries return in ~0.1 s, making a re-run cheap.

Usage:
  docker compose exec backend python scripts/warmup_analysis.py
  docker compose exec backend python scripts/warmup_analysis.py --days 3 --limit 40
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "http://localhost:8000"
# Endpoint limit is 20 calls / 60 s per IP; stay just under it.
PACE_SECONDS = 3.2


def _get(url: str, timeout: int = 60) -> tuple[int, float]:
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            r.read()
            return r.status, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t0
    except Exception:
        return 0, time.time() - t0


def main() -> None:
    ap = argparse.ArgumentParser(description="Pre-warm the analysis cache")
    ap.add_argument("--days", type=int, default=2, help="Warm fixtures kicking off within N days")
    ap.add_argument("--limit", type=int, default=60, help="Max fixtures to warm")
    args = ap.parse_args()

    from sqlalchemy import text

    from backend.app.database import SessionLocal

    lo, hi = date.today().isoformat(), (date.today() + timedelta(days=args.days)).isoformat()
    db = SessionLocal()
    try:
        # Only fixtures that HAVE a prediction — the endpoint 404s otherwise.
        club = [r[0] for r in db.execute(text(
            "SELECT m.id FROM matches m JOIN predictions p ON p.match_id = m.id "
            "WHERE m.home_goals IS NULL AND m.match_date BETWEEN :lo AND :hi "
            "ORDER BY m.match_date, m.kickoff_time NULLS LAST"
        ), {"lo": lo, "hi": hi}).fetchall()]
        national = [r[0] for r in db.execute(text(
            "SELECT id FROM national_predictions "
            "WHERE actual_result IS NULL AND match_date BETWEEN :lo AND :hi "
            "ORDER BY match_date"
        ), {"lo": lo, "hi": hi}).fetchall()]
    finally:
        db.close()

    targets = ([(f"{BASE}/predictions/{i}/analysis", f"club:{i}") for i in club]
               + [(f"{BASE}/national/predictions/{i}/analysis", f"nat:{i}") for i in national])
    targets = targets[: args.limit]
    print(f"Warming {len(targets)} fixture(s) ({len(club)} club, {len(national)} national) "
          f"kicking off {lo} → {hi}")

    warm = cold = failed = 0
    t_start = time.time()
    for idx, (url, label) in enumerate(targets):
        status, secs = _get(url)
        if status != 200:
            failed += 1
            print(f"  [fail {status}] {label} ({secs:.1f}s)")
        elif secs < 1.0:
            warm += 1          # already cached — nothing to pay for
        else:
            cold += 1
            print(f"  warmed {label} in {secs:.1f}s")
        if idx < len(targets) - 1:
            time.sleep(PACE_SECONDS)

    print(f"\nDone in {time.time() - t_start:.0f}s. "
          f"{cold} warmed, {warm} already cached, {failed} failed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
