"""Current club Elo ratings, built on demand from the matches table — mirrors
the Elo feature the club model uses (features.py: ELO_K=32, start=1500, no
per-season reset). Lets the club analysis surface Elo ratings like the national
page does, without persisting a new column. Cached with a short TTL.
"""
from __future__ import annotations

import time

from backend.app.ml.features import _elo_update, ELO_START

_CACHE: tuple[float, dict] | None = None
_TTL = 1800  # 30 min — Elo only moves when new results land


def _build(db) -> dict:
    from sqlalchemy import text
    rows = db.execute(text(
        "SELECT home_team, away_team, home_goals, away_goals FROM matches "
        "WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL "
        "ORDER BY match_date, id"
    )).fetchall()
    elo: dict[str, float] = {}
    for h, a, hg, ag in rows:
        rh, ra = elo.get(h, ELO_START), elo.get(a, ELO_START)
        elo[h], elo[a] = _elo_update(rh, ra, int(hg), int(ag))
    return elo


def club_elo(db) -> dict:
    global _CACHE
    now = time.time()
    if _CACHE is None or now - _CACHE[0] > _TTL:
        try:
            _CACHE = (now, _build(db))
        except Exception:
            return {}
    return _CACHE[1]


def club_elo_pair(db, home: str, away: str) -> tuple[float, float] | None:
    """(home_elo, away_elo), or None if neither team has any rated match."""
    e = club_elo(db)
    if not e or (home not in e and away not in e):
        return None
    return round(e.get(home, ELO_START), 1), round(e.get(away, ELO_START), 1)
