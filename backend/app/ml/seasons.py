"""Season labels — one rule, league-aware.

Every fixture writer used to carry its own copy of "a season starts in July":
seven copies, plus one league-aware copy in fetch_domestic_apifootball that
knew the Nordic and Irish leagues play within a calendar year. Brazil's Série
A does too (April–December), but the July rule labelled one championship
"2025/26" until June and "2026/27" after it, so its table on 2026-09-13 held
only the matches since July — 7 to 9 per club. And update_results' moved-
fixture lookup labelled a Finnish match "2026/27" while fetch_domestic had
stored it as "2026", so the lookup could never find the row it was looking for.
"""
from __future__ import annotations

from datetime import date

# Leagues whose whole season is played inside one calendar year.
CALENDAR_YEAR_LEAGUES = frozenset({"BrazilSerieA", "Sweden", "Norway", "Ireland", "Finland"})


def season_label(league: "str | None", d: date) -> str:
    """Our season label for a match on `d`: "2026" for a calendar-year league,
    "2026/27" for everything else (seasons roll over on 1 July)."""
    if league in CALENDAR_YEAR_LEAGUES:
        return str(d.year)
    if d.month >= 7:
        return f"{d.year}/{str(d.year + 1)[2:]}"
    return f"{d.year - 1}/{str(d.year)[2:]}"


def api_season(league: "str | None", d: date) -> int:
    """API-Football's `season` parameter for a match on `d`: the start year."""
    if league in CALENDAR_YEAR_LEAGUES:
        return d.year
    return d.year if d.month >= 7 else d.year - 1
