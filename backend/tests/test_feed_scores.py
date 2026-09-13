"""A knockout decided in extra time is graded on its 90-minute score.

Every club market we predict and grade — 1×2, Over 2.5, BTTS, every ticket leg —
settles at 90 minutes. API-Football's `goals` and football-data.org's
`fullTime` include extra time, so a tie level 1-1 after 90 and won 2-1 after
120 was stored as a home win and an over: the bookmaker settled it a draw and an
under. See scripts/_feed_scores.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts._feed_scores import api_football_goals, football_data_goals

ROOT = Path(__file__).resolve().parents[2]


def _af(status, goals, fulltime):
    return {"fixture": {"status": {"short": status}},
            "goals": {"home": goals[0], "away": goals[1]},
            "score": {"fulltime": {"home": fulltime[0], "away": fulltime[1]}}}


def test_an_extra_time_winner_is_stored_as_the_90_minute_draw():
    assert api_football_goals(_af("AET", (2, 1), (1, 1))) == (1, 1)


def test_a_shootout_is_stored_as_the_90_minute_score():
    assert api_football_goals(_af("PEN", (2, 2), (1, 1))) == (1, 1)


@pytest.mark.parametrize("status", ["FT", "AWD", "WO"])
def test_a_match_settled_in_normal_time_reads_goals(status):
    assert api_football_goals(_af(status, (3, 0), (None, None))) == (3, 0)


def test_a_missing_breakdown_falls_back_to_goals_rather_than_dropping_the_result():
    assert api_football_goals(_af("AET", (2, 1), (None, None))) == (2, 1)


def test_an_unplayed_entry_has_no_score():
    assert api_football_goals(_af("NS", (None, None), (None, None))) == (None, None)
    assert api_football_goals({}) == (None, None)


def _fd(duration, full, regular=None):
    score = {"duration": duration, "fullTime": {"home": full[0], "away": full[1]}}
    if regular is not None:
        score["regularTime"] = {"home": regular[0], "away": regular[1]}
    return {"score": score}


def test_football_data_extra_time_reads_regular_time():
    assert football_data_goals(_fd("EXTRA_TIME", (2, 1), (1, 1))) == (1, 1)
    assert football_data_goals(_fd("PENALTY_SHOOTOUT", (5, 4), (0, 0))) == (0, 0)


def test_football_data_regular_reads_full_time():
    assert football_data_goals(_fd("REGULAR", (2, 0))) == (2, 0)
    assert football_data_goals(_fd("REGULAR", (None, None))) == (None, None)


def test_the_repair_only_rewrites_scores_from_after_the_90th_minute():
    """Goals are only added after 90 minutes. repair_extra_time_scores rewrites a
    stored score at or above the 90-minute one on both sides, and nothing else —
    a score below it on either side is a different disagreement."""
    from scripts.repair_extra_time_scores import _after_90

    assert _after_90((2, 1), (1, 1))          # extra-time winner
    assert _after_90((5, 4), (1, 1))          # football-data fullTime + shootout
    assert _after_90((2, 2), (1, 1))          # one per side, none in extra time
    assert not _after_90((1, 1), (1, 1))      # already right
    assert not _after_90((0, 2), (1, 1))      # below on one side: not ours to fix


# Every writer of club results. National writers are deliberately absent: the
# national model's target includes extra time (martj42), see _feed_scores.
CLUB_RESULT_WRITERS = [
    "scripts/fetch_european_fixtures.py",
    "scripts/fetch_greek_apifootball.py",
    "scripts/fetch_domestic_apifootball.py",
    "scripts/fetch_club_friendlies.py",
    "scripts/import_history_apifootball.py",
    "scripts/update_results.py",
    "scripts/download_european.py",
]


@pytest.mark.parametrize("rel", CLUB_RESULT_WRITERS)
def test_no_club_result_writer_reads_a_raw_score(rel):
    src = (ROOT / rel).read_text()
    for raw in ('.get("goals"', '["goals"]', '"fullTime"'):
        assert raw not in src, f"{rel} reads {raw} directly — after extra time"
    assert "scripts._feed_scores import" in src, rel
