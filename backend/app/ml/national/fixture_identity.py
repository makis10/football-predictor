"""One national match, one prediction row.

results.csv (martj42) carries no fixture id, so every national writer rebuilt
identity from the exact (match_date, home_team, away_team) — while every reader
and settler (update_national_results, sync_results_to_dataset,
fetch_wc_results) treats ±1 day in either orientation as the same match. When
the source re-dated a fixture, a writer missed its row and inserted a second
one: the World Cup's Argentina–Egypt and Switzerland–Colombia were each stored
twice, on 6 and 7 July, and /national/wc-review counted 106 matches instead
of 104.

find_national_row gives every writer the same identity: the exact key, then
(where the writer allows it) the reversed orientation, then a MOVED row — same
tournament and pairing within MOVE_WINDOW_DAYS — but only one the source no
longer lists anywhere (an orphan). The orphan test is what tells a date
correction from a genuine double-header: two meetings days apart are both in
the source, so neither is an orphan and neither is merged.
"""
from __future__ import annotations

from datetime import date, timedelta

MOVE_WINDOW_DAYS = 3

# A source listing fewer rows than this is a truncated download, not the
# calendar: every stored row would look orphaned. Refuse to move anything then
# — the worst outcome becomes a duplicate row, never a wrong date.
MIN_SOURCE_KEYS = 1000

Key = tuple[str, str, str]


def source_keys(*frames) -> set[Key]:
    """(YYYY-MM-DD, home, away) for every row the source lists, played or not."""
    keys: set[Key] = set()
    for df in frames:
        if df is None or len(df) == 0:
            continue
        dates = df["date"]
        ds = (dates.dt.strftime("%Y-%m-%d") if hasattr(dates, "dt")
              else dates.astype(str).str[:10])
        keys.update(zip(ds, df["home_team"], df["away_team"]))
    return keys


def find_national_row(db, match_date: str, home: str, away: str, tournament: str,
                      keys: set[Key], *, allow_reversed: bool):
    """The stored row for this match, and how it was found.

    Returns (row, how) with how in 'exact' | 'reversed' | 'moved' | 'none'.
    'moved' is a row of the same tournament and pairing, within
    MOVE_WINDOW_DAYS, on a date the source no longer lists — the caller moves
    it to `match_date` rather than inserting a second row.
    """
    from backend.app.models.national_prediction import NationalPrediction as NP

    q = db.query(NP)
    row = q.filter(NP.match_date == match_date, NP.home_team == home,
                   NP.away_team == away).first()
    if row is not None:
        return row, "exact"
    if allow_reversed:
        row = q.filter(NP.match_date == match_date, NP.home_team == away,
                       NP.away_team == home).first()
        if row is not None:
            return row, "reversed"

    if len(keys) < MIN_SOURCE_KEYS:
        return None, "none"
    d0 = date.fromisoformat(match_date)
    lo = (d0 - timedelta(days=MOVE_WINDOW_DAYS)).isoformat()
    hi = (d0 + timedelta(days=MOVE_WINDOW_DAYS)).isoformat()
    pairs = [(home, away)] + ([(away, home)] if allow_reversed else [])
    candidates = []
    for h, a in pairs:
        candidates += q.filter(
            NP.tournament == tournament, NP.home_team == h, NP.away_team == a,
            NP.match_date >= lo, NP.match_date <= hi, NP.match_date != match_date,
        ).all()
    orphans = [c for c in candidates
               if (c.match_date, c.home_team, c.away_team) not in keys
               and (c.match_date, c.away_team, c.home_team) not in keys]
    if not orphans:
        return None, "none"
    orphans.sort(key=lambda c: abs((date.fromisoformat(c.match_date) - d0).days))
    return orphans[0], "moved"
