#!/usr/bin/env python3
"""
Fetch a daily ClubElo.com rating snapshot → backend/data/clubelo.json.

Why: our internal club Elo only knows teams that appear in our historical CSVs.
A newly-promoted side, a lower-division cup/friendly opponent (e.g. Wrexham) or a
European-qualifier minnow is absent, so `compute_match_features` silently defaults
its Elo to 1500 (ELO_START) — i.e. treats it as a perfectly average team. ClubElo
publishes a rating for ~600 clubs across Europe; seeding those into the snapshot for
cold-start teams gives the model a real strength signal instead of a flat prior.

The raw ClubElo scale (top club ~2060, wider spread than ours) is NOT injected
directly — compute_predictions.py fits a linear ClubElo→our-Elo map on the overlap
of teams present in both, so seeded values land on our trained distribution.

API: http://api.clubelo.com/YYYY-MM-DD → CSV (Rank,Club,Country,Level,Elo,From,To).
One unauthenticated GET, no key, refreshed at most once/day (cheap).

Idempotent: rewrites clubelo.json each run. Network failure is non-fatal — the
seeding path treats a missing/stale file as "no fallback" and behaves exactly as
before (flat 1500).
"""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "backend" / "data" / "clubelo.json"
API_URL = "http://api.clubelo.com/{d}"
TIMEOUT = 20


def fetch_snapshot(on_date: str) -> dict[str, dict]:
    """Return {club_name: {"elo": float, "country": str, "level": int}}."""
    url = API_URL.format(d=on_date)
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()

    out: dict[str, dict] = {}
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        name = (row.get("Club") or "").strip()
        elo_raw = (row.get("Elo") or "").strip()
        if not name or not elo_raw:
            continue
        try:
            elo = float(elo_raw)
        except ValueError:
            continue
        try:
            level = int((row.get("Level") or "0").strip())
        except ValueError:
            level = 0
        # If a club appears twice (rare data quirk), keep the higher-rated row.
        if name in out and out[name]["elo"] >= elo:
            continue
        out[name] = {"elo": round(elo, 2),
                     "country": (row.get("Country") or "").strip(),
                     "level": level}
    return out


def main() -> int:
    on_date = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    try:
        snap = fetch_snapshot(on_date)
    except Exception as e:  # noqa: BLE001 — non-fatal by design
        print(f"[error] ClubElo fetch failed ({type(e).__name__}: {e}). "
              f"Leaving {OUT_PATH.name} untouched.")
        return 1

    if len(snap) < 100:
        print(f"[warn] only {len(snap)} clubs parsed — refusing to overwrite "
              f"(likely a bad/empty response).")
        return 1

    payload = {"as_of": on_date, "count": len(snap), "clubs": snap}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=0))
    print(f"✓ ClubElo snapshot ({on_date}): {len(snap)} clubs → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
