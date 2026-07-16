"""
Best-effort bookmaker "league winner" outright, de-vigged to probabilities.

The Odds API exposes season outrights under dedicated per-competition sport keys
(the World Cup uses `soccer_fifa_world_cup_winner`). Domestic-league winner keys
only exist while the season is live and the market is posted — off-season, and on
some plans, they simply aren't offered. So this ALWAYS degrades to None rather
than failing: the projection then shows model-only, and a market column appears
on its own once bookmakers price the title.

Team names come back in the bookmakers' spelling; the caller maps them to our
names the same way the rest of the odds pipeline does.
"""
from __future__ import annotations

import os
from collections import defaultdict

ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Our league code → The Odds API "winner" sport key. Only leagues whose outright
# The Odds API has historically offered; the rest never had a key to try.
TITLE_MARKET_KEYS: dict[str, str] = {
    "EPL":          "soccer_epl_winner",
    "LaLiga":       "soccer_spain_la_liga_winner",
    "SerieA":       "soccer_italy_serie_a_winner",
    "Bundesliga":   "soccer_germany_bundesliga_winner",
    "Ligue1":       "soccer_france_ligue_one_winner",
    "Championship": "soccer_efl_champ_winner",
    "CL":           "soccer_uefa_champs_league_winner",
    "EL":           "soccer_uefa_europa_league_winner",
}


def fetch_title_market(league: str) -> dict[str, float] | None:
    """{bookmaker_team_name: de-vigged win probability}, or None when the market
    isn't offered (off-season, unsupported plan, or no key for this league)."""
    key = TITLE_MARKET_KEYS.get(league)
    api_key = os.getenv("ODDS_API_KEY", "")
    if not key or not api_key:
        return None

    import requests

    try:
        r = requests.get(
            f"{ODDS_API_BASE}/sports/{key}/odds/",
            params={"apiKey": api_key, "regions": "eu",
                    "markets": "outrights", "oddsFormat": "decimal"},
            timeout=20,
        )
        if r.status_code != 200:      # 404/422 → market not offered right now
            return None
        data = r.json()
    except Exception as e:
        print(f"[title-market] {league}: fetch failed — {e}")
        return None

    # Average the implied probability across bookmakers, then de-vig so the field
    # sums to 1 (bookmaker outright books are heavily over-round).
    acc: dict[str, list[float]] = defaultdict(list)
    for ev in data:
        for bm in ev.get("bookmakers", []):
            for mk in bm.get("markets", []):
                if mk.get("key") != "outrights":
                    continue
                for o in mk.get("outcomes", []):
                    if o.get("price"):
                        acc[o["name"]].append(1.0 / float(o["price"]))
    if not acc:
        return None
    raw = {team: sum(v) / len(v) for team, v in acc.items()}
    tot = sum(raw.values())
    return {team: p / tot for team, p in raw.items()} if tot else None
