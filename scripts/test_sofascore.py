"""
SofaScore unofficial API probe — test rate limits + available data.

DISCLAIMER: SofaScore has no public API. This uses reverse-engineered endpoints.
Violates their ToS. Use only for evaluation purposes.

Usage:
  python scripts/test_sofascore.py
  python scripts/test_sofascore.py --date 2026-05-12
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date, timedelta

import requests

BASE = "https://api.sofascore.com/api/v1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.sofascore.com/",
    "Origin":          "https://www.sofascore.com",
}

# SofaScore tournament IDs for our leagues
TOURNAMENTS = {
    "EPL":          17,
    "LaLiga":       8,
    "SerieA":       23,
    "Bundesliga":   35,
    "Ligue1":       34,
    "Championship": 18,
}

RATE_SLEEP = 3.0   # seconds between requests — conservative


def get(path: str, label: str = "") -> dict | None:
    url = f"{BASE}{path}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        status = r.status_code
        remaining = r.headers.get("X-RateLimit-Remaining", "?")
        limit     = r.headers.get("X-RateLimit-Limit", "?")
        cf        = r.headers.get("CF-RAY", None)
        print(f"  [{status}] {label or path}  "
              f"rate={remaining}/{limit}  "
              f"CF={'yes' if cf else 'no'}  "
              f"size={len(r.content)}b")
        if status == 200:
            return r.json()
        if status == 403:
            print("  → 403 Forbidden — likely Cloudflare block")
        if status == 429:
            retry = r.headers.get("Retry-After", "60")
            print(f"  → 429 Rate limited — Retry-After: {retry}s")
        return None
    except Exception as e:
        print(f"  ERROR {label}: {e}")
        return None


def test_scheduled_events(target_date: str) -> list[dict]:
    """GET /sport/football/scheduled-events/{date} — all football matches."""
    data = get(f"/sport/football/scheduled-events/{target_date}",
               f"scheduled-events {target_date}")
    if not data:
        return []
    events = data.get("events", [])
    print(f"  → {len(events)} total football events on {target_date}")
    return events


def filter_our_leagues(events: list[dict]) -> list[dict]:
    our_ids = set(TOURNAMENTS.values())
    filtered = [
        e for e in events
        if e.get("tournament", {}).get("uniqueTournament", {}).get("id") in our_ids
    ]
    print(f"  → {len(filtered)} events in our leagues")
    return filtered


def test_event_detail(event_id: int, label: str = "") -> dict | None:
    """GET /event/{id} — full event details."""
    return get(f"/event/{event_id}", f"event/{event_id} {label}")


def test_event_statistics(event_id: int) -> dict | None:
    """GET /event/{id}/statistics — shots, xG, possession, etc."""
    return get(f"/event/{event_id}/statistics", f"statistics/{event_id}")


def test_event_lineups(event_id: int) -> dict | None:
    """GET /event/{id}/lineups — starting XI + bench."""
    return get(f"/event/{event_id}/lineups", f"lineups/{event_id}")


def test_team_form(team_id: int, label: str = "") -> dict | None:
    """GET /team/{id}/performance — recent form."""
    return get(f"/team/{team_id}/performance", f"team-form/{team_id} {label}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="Date to probe (YYYY-MM-DD)")
    parser.add_argument("--yesterday", action="store_true",
                        help="Use yesterday's date")
    args = parser.parse_args()

    target = (date.today() - timedelta(days=1)).isoformat() if args.yesterday else args.date
    print(f"\n{'='*60}")
    print(f"SofaScore API probe — {target}")
    print(f"{'='*60}\n")

    # ── 1. Scheduled events ───────────────────────────────────────────────────
    print("1. Fetching scheduled events …")
    events = test_scheduled_events(target)
    time.sleep(RATE_SLEEP)

    if not events:
        print("No events returned — API may be blocked.")
        return

    # ── 2. Filter to our leagues ──────────────────────────────────────────────
    print("\n2. Filtering to our leagues …")
    ours = filter_our_leagues(events)

    if not ours:
        print("No matching events for our leagues on this date.")
        # Show sample of what's available
        sample = events[:3]
        for e in sample:
            t = e.get("tournament", {})
            print(f"  Sample: {e.get('homeTeam',{}).get('name')} vs {e.get('awayTeam',{}).get('name')} "
                  f"— {t.get('uniqueTournament',{}).get('name')} (id={t.get('uniqueTournament',{}).get('id')})")
        return

    # ── 3. Event detail for first 3 matches ───────────────────────────────────
    print("\n3. Fetching event details (first 3) …")
    sample_events = ours[:3]
    event_details = []
    for e in sample_events:
        eid  = e["id"]
        home = e.get("homeTeam", {}).get("name", "?")
        away = e.get("awayTeam", {}).get("name", "?")
        detail = test_event_detail(eid, f"{home} vs {away}")
        if detail:
            event_details.append((eid, home, away, detail))
        time.sleep(RATE_SLEEP)

    # ── 4. Statistics for first finished match ────────────────────────────────
    finished = [
        (eid, h, a, d) for (eid, h, a, d) in event_details
        if d.get("event", {}).get("status", {}).get("type") in ("finished", "notstarted")
    ]

    if finished:
        eid, home, away, _ = finished[0]
        print(f"\n4. Fetching statistics: {home} vs {away} …")
        stats = test_event_statistics(eid)
        time.sleep(RATE_SLEEP)

        if stats:
            # Show what stat keys are available
            groups = stats.get("statistics", [])
            for group in groups[:1]:
                print(f"  Stat period: {group.get('period')}")
                for item in group.get("groups", [])[:2]:
                    print(f"    Group: {item.get('groupName')}")
                    for s in item.get("statisticsItems", [])[:4]:
                        print(f"      {s.get('name')}: home={s.get('home')} away={s.get('away')}")

        # ── 5. Lineups ────────────────────────────────────────────────────────
        print(f"\n5. Fetching lineups: {home} vs {away} …")
        lineups = test_event_lineups(eid)
        time.sleep(RATE_SLEEP)

        if lineups:
            home_lineup = lineups.get("home", {}).get("players", [])
            away_lineup = lineups.get("away", {}).get("players", [])
            print(f"  Home XI: {[p.get('player',{}).get('name','?') for p in home_lineup[:5]]} …")
            print(f"  Away XI: {[p.get('player',{}).get('name','?') for p in away_lineup[:5]]} …")

    # ── 6. Burst test — 10 rapid requests ────────────────────────────────────
    print("\n6. Burst test — 10 requests with 0.5s sleep …")
    blocked = 0
    for i, e in enumerate(ours[:10]):
        eid  = e["id"]
        data = get(f"/event/{eid}", f"burst-{i+1}/{min(10,len(ours))}")
        if data is None:
            blocked += 1
        time.sleep(0.5)   # aggressive — testing limits

    print(f"\n  Result: {blocked}/10 blocked")
    if blocked == 0:
        print("  → No rate limiting detected at 2req/s")
    elif blocked < 5:
        print("  → Partial blocking — reduce rate")
    else:
        print("  → Heavy blocking — not viable without proxy/rotation")

    print(f"\n{'='*60}")
    print("Probe complete.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
