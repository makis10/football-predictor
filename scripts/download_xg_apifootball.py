"""
Download xG (expected goals) data from API-Football for leagues NOT covered
by understat: GreekSL, Champions League, Europa League, Conference League.

The understat.com downloader (download_xg.py) already covers the top-5 leagues.
This script fills the remaining gap using the /fixtures/statistics endpoint.

Output:
  backend/data/xg/{League}_{season_start_year}.csv
  e.g.  GreekSL_2023.csv,  CL_2023.csv,  EL_2023.csv,  ECL_2023.csv

CSV format (same as understat CSVs so load_xg_data() reads them identically):
  date, home_team, away_team, home_xg, away_xg, league, season

Usage:
  docker compose exec backend python scripts/download_xg_apifootball.py
  docker compose exec backend python scripts/download_xg_apifootball.py --seasons 2024
  docker compose exec backend python scripts/download_xg_apifootball.py --leagues GreekSL CL
  docker compose exec backend python scripts/download_xg_apifootball.py --force   # overwrite existing

After downloading, retrain to incorporate the new xG features:
  docker compose exec backend python -m backend.app.ml.train
  docker compose exec backend python scripts/compute_predictions.py --force
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))  # project root

from backend.app.ml.odds_analysis_service import _teams_match as fuzzy_match

# ── Config ────────────────────────────────────────────────────────────────────

API_KEY = os.getenv("API_SPORTS_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
XG_DIR   = Path("/app/backend/data/xg")

# Leagues to download (understat already covers the top-5 domestic leagues)
LEAGUES = {
    "GreekSL":      197,
    "CL":           2,
    "EL":           3,
    "ECL":          848,
    "Eredivisie":   88,
    "PrimeiraLiga": 94,
    "Championship": 40,
}

# Seasons (start year): fetch historical + current
DEFAULT_SEASONS = [2021, 2022, 2023, 2024, 2025]

# Finished match statuses (skip postponed / cancelled / not yet played)
FINISHED_STATUSES = {"FT", "AET", "PEN", "WO", "AWD"}

# Seconds between API calls — API-Football allows 10 req/sec on paid plans;
# we stay conservative to avoid triggering any burst limits.
RATE_DELAY  = 0.5    # seconds between requests (conservative — avoids per-second burst limits)
MAX_RETRIES = 4      # on 429, retry with exponential back-off (0.5 → 1 → 2 → 4 s)

# ── Argument parsing ──────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Download xG from API-Football")
parser.add_argument(
    "--leagues", nargs="+", choices=list(LEAGUES.keys()), default=None,
    help="Leagues to download (default: all four)",
)
parser.add_argument(
    "--seasons", nargs="+", type=int, default=None,
    help="Season start years to download, e.g. --seasons 2023 2024 (default: 2021-2024)",
)
parser.add_argument(
    "--force", action="store_true",
    help="Overwrite existing CSV files (default: skip already-downloaded files)",
)
args = parser.parse_args()

leagues_to_fetch = {k: v for k, v in LEAGUES.items()
                    if args.leagues is None or k in args.leagues}
seasons_to_fetch = args.seasons or DEFAULT_SEASONS

# ── API helpers ───────────────────────────────────────────────────────────────

HEADERS = {"x-apisports-key": API_KEY}


def _get(endpoint: str, params: dict) -> tuple[dict, str]:
    """
    GET request to API-Football with exponential back-off on 429.
    Raises after MAX_RETRIES exhausted or on non-429 HTTP errors.
    """
    delay = RATE_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        time.sleep(delay)
        resp = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS,
                            params=params, timeout=15)
        if resp.status_code == 429:
            wait = delay * (2 ** attempt)
            print(f"  [rate-limit] 429 — waiting {wait:.1f}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data      = resp.json()
        remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
        return data, remaining
    raise RuntimeError(f"Max retries exceeded for {endpoint} params={params}")


def fetch_fixtures(league_id: int, season: int) -> list[dict]:
    """
    Return all fixtures for (league_id, season) in one API call.
    Each fixture dict contains: id, date, status_short, home_name, away_name.
    """
    data, remaining = _get("fixtures", {"league": league_id, "season": season})
    fixtures = []
    for entry in data.get("response", []):
        status = entry.get("fixture", {}).get("status", {}).get("short", "")
        if status not in FINISHED_STATUSES:
            continue
        fixture_id   = entry["fixture"]["id"]
        date_str     = entry["fixture"]["date"][:10]      # "YYYY-MM-DD"
        home_name    = entry["teams"]["home"]["name"]
        away_name    = entry["teams"]["away"]["name"]
        fixtures.append({
            "id":   fixture_id,
            "date": date_str,
            "home": home_name,
            "away": away_name,
        })
    print(f"  {len(fixtures)} finished fixtures  (quota remaining: {remaining})")
    return fixtures


def fetch_xg(fixture_id: int) -> tuple[Optional[float], Optional[float]]:
    """
    Return (home_xg, away_xg) for a single fixture.
    Returns (None, None) when xG is not available for that match.
    """
    data, _ = _get("fixtures/statistics", {"fixture": fixture_id})
    teams = data.get("response", [])
    if len(teams) < 2:
        return None, None

    def _extract_xg(team_stats: dict) -> Optional[float]:
        for stat in team_stats.get("statistics", []):
            if stat.get("type", "").lower() in ("expected_goals", "xg"):
                val = stat.get("value")
                if val is None or val == "":
                    return None
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None
        return None

    home_xg = _extract_xg(teams[0])
    away_xg = _extract_xg(teams[1])
    return home_xg, away_xg


# ── Main loop ─────────────────────────────────────────────────────────────────

if not API_KEY:
    print("ERROR: API_SPORTS_KEY not set in environment.", flush=True)
    sys.exit(1)

XG_DIR.mkdir(parents=True, exist_ok=True)

total_written = 0
total_skipped_files = 0
total_no_xg = 0

for league_code, league_id in leagues_to_fetch.items():
    for season in seasons_to_fetch:
        out_path = XG_DIR / f"{league_code}_{season}.csv"

        if out_path.exists() and not args.force:
            print(f"[{league_code} {season}] Already exists → skipping "
                  f"(use --force to overwrite)")
            total_skipped_files += 1
            continue

        print(f"\n[{league_code} {season}] Fetching fixture list …")
        try:
            fixtures = fetch_fixtures(league_id, season)
        except Exception as e:
            print(f"  ERROR fetching fixtures: {e}")
            continue

        if not fixtures:
            print(f"  No finished fixtures found — skipping.")
            continue

        # Load already-fetched fixture IDs from partial progress file
        progress_path = XG_DIR / f".progress_{league_code}_{season}.csv"
        done_ids: set[int] = set()
        rows: list[dict] = []

        if progress_path.exists() and not args.force:
            with open(progress_path, newline="", encoding="utf-8") as pf:
                for pr in csv.DictReader(pf):
                    rows.append(pr)
                    done_ids.add(int(pr.get("fixture_id", 0)))
            print(f"  Resuming — {len(rows)} fixtures already fetched from progress file.")

        no_xg_count = 0
        remaining_fixtures = [fx for fx in fixtures if fx["id"] not in done_ids]

        for i, fx in enumerate(remaining_fixtures, 1):
            try:
                home_xg, away_xg = fetch_xg(fx["id"])
            except RuntimeError as e:
                # Rate-limit retries exhausted — save progress and abort
                print(f"  [error] {e}")
                print(f"  Saving progress ({len(rows)} rows) — re-run to continue.")
                break
            except Exception as e:
                print(f"  [warn] fixture {fx['id']} stats failed: {e}")
                home_xg = away_xg = None

            if home_xg is None or away_xg is None:
                no_xg_count += 1
                # Still mark as visited so we don't retry indefinitely
                done_ids.add(fx["id"])
                continue

            row = {
                "fixture_id": fx["id"],
                "date":       fx["date"],
                "home_team":  fx["home"],
                "away_team":  fx["away"],
                "home_xg":    round(home_xg, 5),
                "away_xg":    round(away_xg, 5),
                "league":     league_code,
                "season":     season,
            }
            rows.append(row)
            done_ids.add(fx["id"])

            # Flush progress after every row so we can resume if interrupted
            write_header = not progress_path.exists()
            with open(progress_path, "a", newline="", encoding="utf-8") as pf:
                writer = csv.DictWriter(pf, fieldnames=list(row.keys()))
                if write_header:
                    writer.writeheader()
                writer.writerow(row)

            if i % 20 == 0:
                print(f"  {i}/{len(remaining_fixtures)} done  "
                      f"({len(rows)} with xG, {no_xg_count} without) …",
                      flush=True)

        print(f"  Done: {len(rows)} matches with xG, "
              f"{no_xg_count} without xG data ({no_xg_count/max(len(fixtures),1):.0%})")

        if rows:
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["date","home_team","away_team",
                                   "home_xg","away_xg","league","season"],
                    extrasaction="ignore",   # ignore fixture_id and other internal fields
                )
                writer.writeheader()
                writer.writerows(rows)
            print(f"  Saved → {out_path}  ({len(rows)} rows)")
            total_written += len(rows)
        else:
            print(f"  No rows with xG to save — file not created.")

        total_no_xg += no_xg_count

print(f"\n{'='*50}")
print(f"Total rows written : {total_written}")
print(f"Matches without xG : {total_no_xg}  (not saved)")
print(f"Files skipped      : {total_skipped_files}  (already existed)")

if total_written > 0:
    print(
        "\nNext steps:\n"
        "  1. Retrain models:  docker compose exec backend python -m backend.app.ml.train\n"
        "  2. Recompute preds: docker compose exec backend python scripts/compute_predictions.py --force\n"
        "\nNote: API-Football team names may differ from training CSV names.\n"
        "If merge_xg() matches are lower than expected, check the unmatched\n"
        "teams and add mappings to _XG_TEAM_MAP in backend/app/ml/features.py."
    )
