"""One season rule for every writer.

Brazil's Série A plays April–December inside one calendar year. The July rule
seven fixture writers each carried labelled one championship "2025/26" until
June and "2026/27" after it, so its table held only the matches since July —
7 to 9 per club on 2026-09-13.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date, timedelta

import pytest

from backend.app.ml.seasons import CALENDAR_YEAR_LEAGUES, api_season, season_label


@pytest.mark.parametrize("league, d, label, api", [
    ("BrazilSerieA", date(2027, 4, 10), "2027", 2027),
    ("BrazilSerieA", date(2026, 11, 4), "2026", 2026),
    ("Finland", date(2026, 9, 13), "2026", 2026),
    ("EPL", date(2027, 1, 5), "2026/27", 2026),
    ("EPL", date(2026, 7, 1), "2026/27", 2026),
    ("EPL", date(2026, 6, 30), "2025/26", 2025),
    (None, date(2026, 9, 1), "2026/27", 2026),
])
def test_season_label_and_api_season(league, d, label, api):
    assert season_label(league, d) == label
    assert api_season(league, d) == api


def test_brazil_is_a_calendar_year_league():
    assert "BrazilSerieA" in CALENDAR_YEAR_LEAGUES


def test_no_writer_keeps_its_own_season_rule():
    """Every function that labels a season delegates to backend/app/ml/seasons.py
    — a local copy is how one championship ended up with two labels."""
    root = pathlib.Path(__file__).resolve().parents[2] / "scripts"
    names = {"infer_season", "_infer_season", "_api_season"}
    local = []
    for p in sorted(root.glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        for fn in tree.body:
            if isinstance(fn, ast.FunctionDef) and fn.name in names and any(
                    isinstance(n, ast.Attribute) and n.attr == "month" for n in ast.walk(fn)):
                local.append(f"{p.name}:{fn.lineno} {fn.name}")
    assert not local, "season rules outside backend/app/ml/seasons.py: " + ", ".join(local)


def test_the_backfill_inserts_only_matches_we_never_held():
    from scripts.fetch_domestic_apifootball import _missing_finished

    d = date(2026, 5, 1)
    existing = [(111, "A", "B", d), (None, "C", "D", d + timedelta(days=1))]
    finished = [
        # held under its feed id, on the date it was moved from
        {"api_fixture_id": 111, "home_team": "A", "away_team": "B", "match_date": d - timedelta(days=9)},
        # held by pairing, a day out (late kick-off drift)
        {"api_fixture_id": 222, "home_team": "C", "away_team": "D", "match_date": d},
        # never held
        {"api_fixture_id": 333, "home_team": "E", "away_team": "F", "match_date": d},
    ]
    assert [f["api_fixture_id"] for f in _missing_finished(finished, existing)] == [333]
