"""Season projections must simulate the season that is actually left.

league_sim derived the remaining fixtures from the team list alone: every
ordered pair minus the set of pairs already played. Split and triple
round-robin leagues meet the same pairing twice at the same ground — Finland
held 75 rows over 67 pairings, Scotland 138 over 132 — so their real repeat
fixtures vanished from the simulation, and each projection declared its season
over as soon as every pairing had been played once.
"""
from __future__ import annotations

from datetime import date

from backend.app.ml import european_sim as E
from backend.app.ml import league_sim as L

TEAMS = ["A", "B", "C", "D"]


def _row(h, a, hg=None, ag=None, d=date(2026, 9, 1)):
    return (h, a, hg, ag, d)


def _all_pairs_played():
    return [_row(h, a, 1, 1) for h in TEAMS for a in TEAMS if h != a]


def test_a_scheduled_repeat_meeting_is_simulated():
    rows = [_row("A", "B", 1, 0), _row("A", "B", d=date(2026, 10, 1))]
    reg, phase, remaining = L._split_fixtures(rows, TEAMS, playoff=False)
    assert remaining.count(("A", "B")) == 1
    assert (reg, phase) == ([("A", "B", 1, 0)], [])


def test_played_repeats_both_count_and_the_round_robin_is_still_completed():
    rows = [_row("A", "B", 1, 0), _row("A", "B", 2, 2, d=date(2026, 9, 20))]
    reg, _, remaining = L._split_fixtures(rows, TEAMS, playoff=False)
    assert len(reg) == 2
    # The eleven other ordered pairings a 4-team double round-robin still owes.
    assert len(remaining) == 11 and ("A", "B") not in remaining


def test_a_season_is_not_over_while_a_repeat_meeting_is_unplayed():
    rows = _all_pairs_played() + [_row("C", "D", d=date(2027, 3, 1))]
    _, _, remaining = L._split_fixtures(rows, TEAMS, playoff=False)
    assert remaining == [("C", "D")]


def test_a_play_off_formats_second_meeting_is_left_to_the_play_off_phase():
    """GreekSL: the regular season is one meeting per ordered pair and the spec
    simulates the groups, so a scheduled second meeting must not also be
    simulated as a regular fixture, and a played one is banked as a group
    result."""
    rows = _all_pairs_played() + [_row("A", "B", d=date(2027, 3, 1)),
                                  _row("C", "D", 0, 0, d=date(2027, 3, 2))]
    reg, phase, remaining = L._split_fixtures(rows, TEAMS, playoff=True)
    assert (len(reg), phase, remaining) == (12, [("C", "D", 0, 0)], [])


def test_the_last_play_off_group_takes_every_team_below_it():
    """A 15th GreekSL team fell outside every group and showed 0% relegation."""
    assert L._group_ranges([(1, 4), (5, 8), (9, 14)], 15) == [(1, 4), (5, 8), (9, 15)]
    assert L._group_ranges([(1, 4), (5, 8), (9, 14)], 14) == [(1, 4), (5, 8), (9, 14)]


def test_the_top_seed_meets_the_weakest_play_off_survivor():
    seeded = [f"S{i}" for i in range(1, 9)]
    po_winners = [f"W{9 + i}v{24 - i}" for i in range(8)]     # 9v24 winner first
    b = E._r16_bracket(seeded, po_winners)
    pairs = [(b[i], b[len(b) - 1 - i]) for i in range(len(b) // 2)]
    assert pairs[0] == ("S1", "W16v17")
    assert pairs[7] == ("S8", "W9v24")
