"""Guards for the two ways a real data gap can be silenced by accident.

1. `NO_UPSTREAM_STATS` demotes an alert to a warning for clubs whose statistics
   simply do not exist upstream. That is right — alerting on them is asking
   someone to fix the weather — but an entry that outlives the gap silences a
   REAL problem, and nothing would ever say so. Every entry therefore has to
   carry the date it was verified, so a reader can tell a fresh exemption from
   a forgotten one.

2. `fetch_club_form` must skip player_id 0. `/players` rejects it outright
   ("The Id field cannot be 0"), and because the row never gets a rate it is
   exempt from the freshness skip — so it was re-requested on every single run,
   forever, and can never succeed.

Offline: no network, no database.
"""
from __future__ import annotations


import inspect
import re

import pytest

from scripts.check_data_completeness import NO_UPSTREAM_STATS


def test_every_exemption_says_when_it_was_checked():
    """A bare "no stats for this club" is unfalsifiable a month later. The date
    is what lets the next reader decide whether to re-test or delete."""
    undated = [k for k, v in NO_UPSTREAM_STATS.items()
               if not re.search(r"\d{4}-\d{2}-\d{2}", v)]
    assert not undated, (
        f"NO_UPSTREAM_STATS entries with no checked-date: {undated}. "
        "Add 'checked YYYY-MM-DD' so a stale exemption is visible."
    )


def test_exemptions_are_reasons_not_labels():
    """'no data' tells the next reader nothing. The reason has to name what was
    observed, so re-testing does not start from scratch."""
    thin = [k for k, v in NO_UPSTREAM_STATS.items() if len(v) < 40]
    assert not thin, f"NO_UPSTREAM_STATS entries with no real reason: {thin}"


def test_exemption_list_stays_small():
    """This list suppresses alerts. If it grows into the dozens it has stopped
    being a handful of verified upstream gaps and become a way to keep the
    health check quiet."""
    assert len(NO_UPSTREAM_STATS) <= 10, (
        f"{len(NO_UPSTREAM_STATS)} clubs exempted from stats alerts — that is "
        "no longer a list of one-off upstream gaps"
    )


def test_club_form_skips_players_without_an_api_id():
    """player_id 0 can never be answered by /players. Without an explicit skip
    it costs a request (now three, with the rate-limit retry) on every run to
    be told the same thing."""
    import scripts.fetch_club_form as m

    src = inspect.getsource(m)
    loop = src[src.index("for pid, pname, teams"):]

    # The guard must appear BEFORE the first /players call in the loop.
    guard = loop.find("if not pid:")
    call = loop.find('_get("/players"')
    assert guard != -1, "fetch_club_form must skip falsy player ids"
    assert call != -1, "expected a /players call in this loop"
    assert guard < call, (
        "the player_id 0 guard must come before the /players request, "
        "otherwise the request is still spent"
    )
    assert "continue" in loop[guard:call], "the guard must skip the player"
