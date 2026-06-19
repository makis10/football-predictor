"""
Fill actual results for national-team predictions that have been played.

Two sources, in order:
  1. martj42 dataset (results.csv) — full historical coverage, but it is a
     volunteer-maintained repo and can lag hours-to-days behind live matches
     (observed: WC 2026 opening night missing the next morning).
  2. The Odds API scores endpoint — near-real-time fallback for tournaments
     it covers (World Cup, EURO, Copa, AFCON, NL, qualifiers). daysFrom max 3.

Idempotent — only touches rows where actual_result IS NULL.

Usage:
  docker compose exec backend python scripts/update_national_results.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "data" / "raw" / "international"
RESULTS  = DATA_DIR / "results.csv"

sys.path.insert(0, str(ROOT))


def _result(hg: int, ag: int) -> str:
    if hg > ag:
        return "H"
    if hg == ag:
        return "D"
    return "A"


def _fetch_live_scores(sport_key: str) -> list[dict]:
    """Completed matches from The Odds API scores endpoint (last 3 days)."""
    import os

    import requests

    api_key = os.getenv("ODDS_API_KEY", "")
    if not api_key:
        return []
    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/",
            params={"apiKey": api_key, "daysFrom": 3},
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json()
        out = []
        for e in events:
            if not (e.get("completed") and e.get("scores")):
                continue
            smap = {s["name"]: int(s["score"]) for s in e["scores"]}
            h, a = e.get("home_team", ""), e.get("away_team", "")
            if h in smap and a in smap:
                out.append({"home": h, "away": a, "hg": smap[h], "ag": smap[a]})
        print(f"  [odds-scores] {sport_key}: {len(out)} completed "
              f"(quota: {resp.headers.get('x-requests-remaining', '?')})")
        return out
    except Exception as e:
        print(f"  [odds-scores] {sport_key} failed: {e}")
        return []


def main() -> None:
    if not RESULTS.exists():
        print(f"[error] {RESULTS} not found. Run fetch_international_data.py first.")
        sys.exit(1)

    df = pd.read_csv(RESULTS)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    played = df[df["home_score"].notna() & df["away_score"].notna()].copy()

    # Index played results by (date, home, away) for O(1) lookup
    played_idx: dict[tuple[str, str, str], tuple[int, int]] = {}
    for _, r in played.iterrows():
        key = (r["date"], r["home_team"], r["away_team"])
        played_idx[key] = (int(r["home_score"]), int(r["away_score"]))

    from backend.app.database import SessionLocal
    from backend.app.models.national_prediction import NationalPrediction

    db = SessionLocal()
    filled = missing = 0
    try:
        pending = db.query(NationalPrediction).filter(
            NationalPrediction.actual_result.is_(None)
        ).all()
        print(f"{len(pending)} prediction(s) awaiting a result.")

        def _dataset_lookup(p) -> "tuple[int, int] | None":
            """Exact key, then reversed orientation, then ±1 day (both ways).

            Sources disagree on home/away designation (FIFA bracket position vs
            dataset convention — e.g. martj42 logged 'Peru v Spain' where we
            hold 'Spain v Peru') and on the calendar date for late local
            kick-offs, so a strict (date, home, away) lookup leaves real
            results unmatched."""
            from datetime import date as _d, timedelta as _td

            base = _d.fromisoformat(p.match_date)
            for delta in (0, 1, -1):
                d = (base + _td(days=delta)).isoformat()
                hit = played_idx.get((d, p.home_team, p.away_team))
                if hit is not None:
                    return hit
                rev = played_idx.get((d, p.away_team, p.home_team))
                if rev is not None:
                    return rev[1], rev[0]   # swap goals to OUR orientation
            return None

        still_pending = []
        for p in pending:
            score = _dataset_lookup(p)
            if score is None:
                missing += 1
                still_pending.append(p)
                continue
            hg, ag = score
            p.actual_home_goals = hg
            p.actual_away_goals = ag
            p.actual_result     = _result(hg, ag)
            filled += 1
            mark = "✓" if p.prediction == p.actual_result else "✗"
            print(f"  {mark} {p.match_date}  {p.home_team} {hg}-{ag} {p.away_team}"
                  f"  (pred {p.prediction}, actual {p.actual_result})")

        # ── Fallback: The Odds API live scores for recent, still-pending rows ─
        # Covers the martj42 publication lag during live tournaments. Only rows
        # whose match has plausibly finished (matchday ≤ today) are attempted.
        from datetime import date, timedelta

        from backend.app.ml.odds_analysis_service import (
            get_national_sport_key, _teams_match,
        )

        recent_cut = (date.today() - timedelta(days=3)).isoformat()
        today_iso  = date.today().isoformat()
        candidates = [p for p in still_pending
                      if recent_cut <= p.match_date <= today_iso]
        scores_by_key: dict[str, list[dict]] = {}
        live_filled = 0
        for p in candidates:
            sk = get_national_sport_key(p.tournament)
            if not sk:
                continue
            if sk not in scores_by_key:
                scores_by_key[sk] = _fetch_live_scores(sk)
            hit = None
            for s in scores_by_key[sk]:
                if _teams_match(s["home"], p.home_team) and _teams_match(s["away"], p.away_team):
                    hit = (s["hg"], s["ag"])
                    break
                if _teams_match(s["home"], p.away_team) and _teams_match(s["away"], p.home_team):
                    hit = (s["ag"], s["hg"])     # reversed orientation → swap
                    break
            if hit is None:
                continue
            hg, ag = hit
            p.actual_home_goals = hg
            p.actual_away_goals = ag
            p.actual_result     = _result(hg, ag)
            live_filled += 1
            missing -= 1
            mark = "✓" if p.prediction == p.actual_result else "✗"
            print(f"  {mark} {p.match_date}  {p.home_team} {hg}-{ag} {p.away_team}"
                  f"  (pred {p.prediction}, actual {p.actual_result})  [live scores]")

        db.commit()
        print(f"\nFilled: {filled} (dataset) + {live_filled} (live scores)   Still pending: {missing}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
