"""Final scores as the markets we grade settle them: after 90 minutes.

API-Football's `goals` for a match decided in extra time (AET) or on penalties
(PEN) includes the extra-time goals; `score.fulltime` holds the regulation
score. football-data.org's `score.fullTime` likewise includes extra time when
`score.duration` is EXTRA_TIME or PENALTY_SHOOTOUT, and `regularTime` holds the
90 minutes.

Every club market we predict and grade — 1×2, Over 2.5, BTTS, every ticket leg
(backend/app/ml/tickets.py settle_market) — settles at 90 minutes. A knockout
tie level 1-1 after 90 and won 2-1 in extra time settles "draw" and "under 2.5"
at the bookmaker; stored with the extra-time score it was graded a home win and
an over, in the public record and on every accumulator carrying it.

National results are deliberately not read through here: the national model is
trained on martj42's scores, which include extra time, so its target is the
result after extra time and it is graded the same way.
"""
from __future__ import annotations

_EXTRA_TIME = ("AET", "PEN")


def api_football_goals(entry: dict) -> "tuple[int | None, int | None]":
    """(home, away) after 90 minutes for an API-Football fixture entry."""
    status = ((entry.get("fixture") or {}).get("status") or {}).get("short", "")
    if status in _EXTRA_TIME:
        ft = (entry.get("score") or {}).get("fulltime") or {}
        if ft.get("home") is not None and ft.get("away") is not None:
            return int(ft["home"]), int(ft["away"])
    g = entry.get("goals") or {}
    if g.get("home") is None or g.get("away") is None:
        return None, None
    return int(g["home"]), int(g["away"])


# API-Football closes a fixture without a played result four ways. An awarded
# score (AWD, WO) stands in the league table, but no bookmaker settles a match
# that was not played, and nothing of ours may grade it (migration 0038).
API_FOOTBALL_VOID = {"AWD": "awarded", "WO": "walkover",
                     "CANC": "cancelled", "ABD": "abandoned"}


def api_football_void_reason(entry: dict) -> "str | None":
    """matches.void_reason for an API-Football fixture entry, None if played."""
    status = ((entry.get("fixture") or {}).get("status") or {}).get("short", "")
    return API_FOOTBALL_VOID.get(status)


def football_data_goals(match: dict) -> "tuple[int | None, int | None]":
    """(home, away) after 90 minutes for a football-data.org v4 match."""
    score = match.get("score") or {}
    part = score.get("fullTime") or {}
    if score.get("duration") in ("EXTRA_TIME", "PENALTY_SHOOTOUT"):
        regular = score.get("regularTime") or {}
        if regular.get("home") is not None and regular.get("away") is not None:
            part = regular
    hg, ag = part.get("home"), part.get("away")
    if hg is None or ag is None:
        return None, None
    return int(hg), int(ag)
