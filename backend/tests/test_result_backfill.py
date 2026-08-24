"""A finished match the schedule feed never gave us.

football-data.org publishes fixtures in a rolling window. Ask too late and the
match is simply not in it — but the RESULT feed still reports it, so we end up
holding a score with nowhere to put it. On 2026-08-24 five matches were in that
state, the oldest from the 8th:

    EPL          Ipswich Town v Sunderland   2-1
    LaLiga       Alaves v Getafe             3-0
    LaLiga       Sevilla v Vallecano         2-1
    PrimeiraLiga Maritimo v Casa Pia         1-0
    Eredivisie   Nijmegen v Telstar          1-2

Nothing recovered them: no Elo update for ten clubs, and four league tables
permanently a game short. The warning had been printing for over a week.
"""
from __future__ import annotations

import re
from pathlib import Path

from scripts.team_resolver import canonical

SRC = Path(__file__).resolve().parents[2] / "scripts" / "update_results.py"


def test_a_result_with_no_fixture_creates_one():
    body = SRC.read_text(encoding="utf-8")
    assert "created missing fixture" in body, \
        "a result that ties to no fixture is dropped again"


def test_a_created_fixture_carries_its_score():
    """Created and left unsettled would be worse than not created: an upcoming
    fixture in the past, which the ticket builder and the stale-fixture sweep
    both have to deal with."""
    body = SRC.read_text(encoding="utf-8")
    block = body[body.index("created missing fixture") - 1200:
                 body.index("created missing fixture")]
    for field in ("home_goals=", "away_goals=", "result="):
        assert field in block, f"the created row has no {field}"


def test_a_fixture_is_never_created_for_a_club_we_do_not_know():
    """This is the phantom-team guard. A completed match between clubs we have
    no history for is a match nobody can look up, and it would put a brand-new
    club into the Elo table off one row."""
    body = SRC.read_text(encoding="utf-8")
    assert "known_teams" in body
    assert re.search(r"if home in known_teams and away in known_teams", body), \
        "fixtures can be created for unknown clubs"


# ── The alias that made one of the five unfixable ────────────────────────────
# "Ipswich Town" → "Ipswich" already existed, in features._SNAP_NAME_MAP, which
# canonical() does not read. Two tables doing the same job, agreeing on
# everything except the entry that mattered.

def test_the_result_feed_spelling_resolves_to_the_club_we_hold():
    assert canonical("Ipswich Town") == "Ipswich"


def test_every_snapshot_rename_is_also_a_canonical_alias():
    """The general form of that bug. A name the snapshot map folds away must
    fold the same way through canonical(), or the two layers disagree and a
    result lands nowhere."""
    from backend.app.ml.features import _SNAP_NAME_MAP

    disagree = {src: dst for src, dst in _SNAP_NAME_MAP.items()
                if canonical(src) != canonical(dst)}

    assert not disagree, (
        "these names fold one way for the snapshot and another for the "
        f"resolver: {disagree}")
