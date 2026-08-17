"""Can football-data.org's result actually be tied to the fixture it belongs to?

`update_results.py` looks a finished match up by exact (date, home, away, league).
Names arrive pre-mapped through `map_team` → `canonical`, so when a feed spelling
has no alias, `canonical` hands it back unchanged, nothing matches, and the row
keeps result=NULL — permanently. The old counter filed that under "already
updated or not in our DB", which reads as routine noise.

Found 2026-08-17 the worst possible way: a reader saw Bolton v Preston sitting
unsettled on three of his own accumulator slips, two days after the real score
(2-1) was public from two sources. All four unmatched fixtures were Championship
games whose feed spelling differs from ours — and the CSV backfill that normally
covers for this has no 2026/27 Championship file yet, so nothing else caught it.

Offline: alias tables only, no network, no database.
"""
from __future__ import annotations

import inspect

import pytest

from scripts.team_resolver import canonical, known_team_names


# ── the four spellings that lost real results ────────────────────────────────

@pytest.mark.parametrize("feed_name, ours", [
    ("Preston NE",    "Preston"),
    ("Lincoln City",  "Lincoln"),
    ("Derby County",  "Derby"),
    ("Sheffield Utd", "Sheffield United"),
])
def test_championship_feed_spellings_resolve(feed_name, ours):
    assert canonical(feed_name) == ours


@pytest.mark.parametrize("feed_name", [
    "Preston NE", "Lincoln City", "Derby County", "Sheffield Utd",
])
def test_those_targets_are_names_we_really_hold(feed_name):
    """An alias pointing at a name absent from the training data would move the
    failure rather than fix it — the lookup would still miss, just quietly."""
    known = set(known_team_names())
    if not known:
        pytest.skip("training-data names unavailable (no raw CSVs in this checkout)")
    assert canonical(feed_name) in known


def test_lincoln_united_is_still_a_different_club():
    """This module's header warns that "Lincoln United" and "Lincoln" (City) are
    two clubs. Adding the Lincoln City alias must not have blurred that."""
    assert canonical("Lincoln United") != "Lincoln"


def test_sheffield_wednesday_is_untouched():
    """"Sheffield Utd" → Sheffield United sits next to an existing Wednesday
    alias. Both must survive; conflating them would merge two rival clubs."""
    assert canonical("Sheffield Wednesday") == "Sheffield Weds"
    assert canonical("Sheffield Utd") == "Sheffield United"


# ── the reporting that would have caught it on day one ───────────────────────

def test_unmatched_results_are_reported_not_counted_silently():
    """A finished match that ties to NO fixture of ours is a lost result and has
    to be named. Lumping it in with "already had a result" is what let this run
    for days: both cases printed the same number."""
    src = inspect.getsource(__import__("scripts.update_results",
                                       fromlist=["update_db"]).update_db)
    assert "unmatched" in src, "update_db must collect unmatched results"
    assert "COMMON_ALIASES" in src, (
        "the warning should say where to add the missing spelling"
    )
    # The distinction is the whole point: a row that exists WITH a result is
    # routine; a row that does not exist at all is a lost score.
    assert src.count("select(Match)") >= 2, (
        "update_db must check whether the fixture exists at all before "
        "reporting it as unmatched, or every already-settled match is a warning"
    )
