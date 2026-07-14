"""
Authoritative current-tournament results overlay from API-Football.

martj42 (results.csv / shootouts.csv) is the historical backbone — 150 years of
international results, every confederation, free — but it is volunteer-maintained
and lags hours-to-days behind live matches and rarely records penalty winners
quickly. API-Football is fresher and more accurate for the live tournament.

So for the CURRENT World Cup we treat API-Football as the source of truth and
overlay it onto the martj42 files (martj42 still provides history + anything
API-Football doesn't cover, and remains the fallback):

  • new fixtures  → results.csv   (knockout pairings the moment the previous
                                    round settles them — martj42 lags days, and
                                    a missing fixture row means no prediction
                                    and an invisible match in the app)
  • final scores  → results.csv   (fills blanks AND overrides stale/incorrect
                                    martj42 scores for the current season's WC)
  • penalty wins  → shootouts.csv  (so the simulator can eliminate the loser of
                                    a drawn knockout)

One /fixtures call. Idempotent. Only touches current-season WC rows; history is
never modified.

Usage:
  docker compose exec backend python scripts/fetch_wc_results.py
  docker compose exec backend python scripts/fetch_wc_results.py --league 1 --season 2026
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

ROOT      = Path(__file__).resolve().parent.parent
DATA_DIR  = ROOT / "backend" / "data" / "raw" / "international"
RESULTS   = DATA_DIR / "results.csv"
SHOOTOUTS = DATA_DIR / "shootouts.csv"

sys.path.insert(0, str(ROOT))
from scripts._http_retry import get_with_retry  # noqa: E402
API_BASE  = "https://v3.football.api-sports.io"
API_KEY   = os.getenv("API_SPORTS_KEY", "")
HEADERS   = {"x-apisports-key": API_KEY}

# API-Football team name → our canonical name (mirrors the other fetchers).
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


def _canon(name: str) -> str:
    return API_TO_CANON.get(name, name)


def _fetch_fixtures(league: int, season: int) -> list[dict]:
    r = get_with_retry(f"{API_BASE}/fixtures", headers=HEADERS,
                        params={"league": league, "season": season}, timeout=20)
    r.raise_for_status()
    return r.json().get("response", [])


# Knockout pairings appear in API-Football with placeholder names until the
# previous round settles them — never write those into the dataset.
_PLACEHOLDER_TOKENS = ("winner", "loser", "tbd", "to be", "match ", "play-off", "playoff")

# WC 2026 host city → country, for the results.csv `country` + `neutral`
# columns. API-Football's /fixtures venue has no country field. Unknown
# cities default to the primary host (United States).
_HOST_COUNTRY = {
    "Toronto": "Canada", "Vancouver": "Canada",
    "Mexico City": "Mexico", "Guadalajara": "Mexico", "Zapopan": "Mexico",
    "Monterrey": "Mexico", "Guadalupe": "Mexico",
}


def _is_placeholder(name: str | None) -> bool:
    if not name:
        return True
    low = name.lower()
    return any(t in low for t in _PLACEHOLDER_TOKENS)


def append_missing_fixtures(fixtures: list[dict], season: int) -> int:
    """Insert current-WC fixtures API-Football knows but results.csv doesn't.

    martj42 pre-populates the group stage, but knockout pairings only exist
    once the previous round settles them, and the volunteer dataset adds them
    hours-to-days later. Without this step a semi-final is invisible to the
    app (no fixture row → no prediction → not shown) until AFTER it has been
    played. Scores are left blank here; overlay_scores() fills them once the
    match finishes. Idempotent: a pairing already present within ±1 day is
    skipped (martj42 dates the match by local kick-off, API-Football by UTC,
    so the calendar day can differ by one)."""
    df = pd.read_csv(RESULTS)
    dates = pd.to_datetime(df["date"], errors="coerce")
    cutoff = pd.Timestamp(f"{season}-06-01")
    wc = df[(df["tournament"] == "FIFA World Cup") & (dates >= cutoff)]
    have: dict[frozenset, list[pd.Timestamp]] = {}
    for d, h, a in zip(pd.to_datetime(wc["date"]), wc["home_team"], wc["away_team"]):
        have.setdefault(frozenset({h, a}), []).append(d)

    new_rows: list[dict] = []
    for f in fixtures:
        h_raw = f["teams"]["home"]["name"]
        a_raw = f["teams"]["away"]["name"]
        if _is_placeholder(h_raw) or _is_placeholder(a_raw):
            continue
        h, a = _canon(h_raw), _canon(a_raw)
        fdate = pd.Timestamp(f["fixture"]["date"][:10])
        if fdate < cutoff:
            continue
        if any(abs((fdate - d).days) <= 1 for d in have.get(frozenset({h, a}), [])):
            continue
        city = ((f["fixture"].get("venue") or {}).get("city") or "").split(",")[0].strip()
        country = _HOST_COUNTRY.get(city, "United States")
        new_rows.append({
            "date": fdate.strftime("%Y-%m-%d"),
            "home_team": h, "away_team": a,
            "home_score": pd.NA, "away_score": pd.NA,
            "tournament": "FIFA World Cup",
            "city": city, "country": country,
            # Host nations play true home games; everyone else is on neutral ground.
            "neutral": h != country,
        })
        have.setdefault(frozenset({h, a}), []).append(fdate)

    if not new_rows:
        return 0
    out = pd.concat([df, pd.DataFrame(new_rows)[df.columns.tolist()]], ignore_index=True)
    out.to_csv(RESULTS, index=False)
    for r in new_rows:
        print(f"  new fixture: {r['date']}  {r['home_team']} v {r['away_team']}  ({r['city']})")
    return len(new_rows)


def overlay_scores(fixtures: list[dict], season: int) -> int:
    """Write API-Football final scores into results.csv current-season WC rows."""
    df = pd.read_csv(RESULTS)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Map a finished fixture by the unordered team pair → (home, away, hg, ag).
    # NOTE: use `goals` (the FINAL score incl. extra time, excl. penalties) —
    # `score.fulltime` is the 90-minute score, which silently rewrote AET wins
    # (e.g. Argentina 3-2 aet Cape Verde) into draws and broke KO conditioning.
    # Keyed by pair + kept per-date: the same two teams can meet twice in one
    # tournament (group stage, then a knockout round) and pair-only matching
    # would stamp the later score onto BOTH rows.
    finished: dict[frozenset, list[dict]] = {}
    for f in fixtures:
        if f["fixture"]["status"]["short"] not in ("FT", "AET", "PEN"):
            continue
        g = f["goals"]
        if g["home"] is None or g["away"] is None:
            continue
        h, a = _canon(f["teams"]["home"]["name"]), _canon(f["teams"]["away"]["name"])
        finished.setdefault(frozenset({h, a}), []).append(
            {"home": h, "away": a, "hg": int(g["home"]), "ag": int(g["away"]),
             "date": pd.Timestamp(f["fixture"]["date"][:10])})

    cutoff = pd.Timestamp(f"{season}-06-01")
    mask = (df["tournament"] == "FIFA World Cup") & (df["date"] >= cutoff)
    changed = 0
    for i in df[mask].index:
        row = df.loc[i]
        rh, ra = row["home_team"], row["away_team"]
        # ±1 day absorbs the local-date (martj42) vs UTC-date (API) rollover.
        fx = next((c for c in finished.get(frozenset({rh, ra}), [])
                   if abs((c["date"] - row["date"]).days) <= 1), None)
        if not fx:
            continue
        # Re-orient API-Football goals to the results.csv row orientation.
        if fx["home"] == rh:
            hg, ag = fx["hg"], fx["ag"]
        else:
            hg, ag = fx["ag"], fx["hg"]
        old_h, old_a = row["home_score"], row["away_score"]
        if pd.notna(old_h) and pd.notna(old_a) and int(old_h) == hg and int(old_a) == ag:
            continue   # already correct
        was = "blank" if pd.isna(old_h) else f"{int(old_h)}-{int(old_a)}"
        df.at[i, "home_score"] = hg
        df.at[i, "away_score"] = ag
        changed += 1
        print(f"  {row['date'].date()}  {rh} {hg}-{ag} {ra}  (was {was})")

    if changed:
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        df.to_csv(RESULTS, index=False)
    return changed


def overlay_shootouts(fixtures: list[dict]) -> int:
    """Append penalty-shootout winners (drawn knockouts) to shootouts.csv."""
    rows: list[dict] = []
    for f in fixtures:
        if f["fixture"]["status"]["short"] not in ("FT", "AET", "PEN"):
            continue
        # Level after extra time (`goals`) + a penalty score = shoot-out decided.
        g, pen = f["goals"], f["score"]["penalty"]
        if g["home"] is None or g["home"] != g["away"]:
            continue
        if pen["home"] is None or pen["away"] is None:
            continue
        h, a = f["teams"]["home"], f["teams"]["away"]
        if h.get("winner"):
            winner = _canon(h["name"])
        elif a.get("winner"):
            winner = _canon(a["name"])
        else:
            winner = _canon(h["name"]) if pen["home"] > pen["away"] else _canon(a["name"])
        rows.append({"date": f["fixture"]["date"][:10],
                     "home_team": _canon(h["name"]), "away_team": _canon(a["name"]),
                     "winner": winner, "first_shooter": ""})

    if not rows:
        return 0
    existing = pd.read_csv(SHOOTOUTS)
    have = set(zip(existing["date"], existing["home_team"], existing["away_team"]))
    fresh = [r for r in rows if (r["date"], r["home_team"], r["away_team"]) not in have]
    if not fresh:
        return 0
    out = pd.concat([existing, pd.DataFrame(fresh)], ignore_index=True)
    out.to_csv(SHOOTOUTS, index=False)
    for r in fresh:
        print(f"  pens: {r['date']}  {r['home_team']} v {r['away_team']} → {r['winner']}")
    return len(fresh)


def main() -> None:
    ap = argparse.ArgumentParser(description="Overlay current-WC results from API-Football")
    ap.add_argument("--league", type=int, default=1, help="API-Football league id (1 = World Cup)")
    ap.add_argument("--season", type=int, default=2026, help="Season (WC year)")
    args = ap.parse_args()

    if not API_KEY:
        print("[error] API_SPORTS_KEY not set."); sys.exit(1)
    if not RESULTS.exists():
        print(f"[error] {RESULTS} not found — run fetch_international_data.py first."); sys.exit(1)

    try:
        fixtures = _fetch_fixtures(args.league, args.season)
    except Exception as e:
        print(f"[error] /fixtures failed: {e}"); sys.exit(1)

    print(f"API-Football: {len(fixtures)} fixtures (league {args.league}, season {args.season}).")
    n_added  = append_missing_fixtures(fixtures, args.season)
    n_scores = overlay_scores(fixtures, args.season)
    n_pens   = overlay_shootouts(fixtures)
    print(f"\n✓ Added {n_added} new fixture(s), overlaid {n_scores} score(s) into results.csv, "
          f"{n_pens} new shoot-out(s) into shootouts.csv.")


if __name__ == "__main__":
    main()
