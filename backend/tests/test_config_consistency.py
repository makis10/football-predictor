"""Cross-file invariants that no single module can enforce on its own.

Every assertion here corresponds to a bug that actually shipped, was found by a
human looking at the site, and cost a debugging session. The common shape is a
fact duplicated in two places that quietly drifted apart — nothing raised, the
feature just stopped doing anything.

Deliberately offline: no DB, no network, no API keys, so CI runs it on every
push. That is the whole point — these are exactly the failures that survive to
production because nothing fails loudly enough to notice.
"""
from __future__ import annotations

import pytest

from backend.app.ml.club_props import NAME_OVERRIDES as READ_OVERRIDES
from backend.app.ml.draw_classifier import DRAW_FEATURE_COLS
from backend.app.ml.features import (
    FEATURE_COLS,
    HISTORY_ONLY_LEAGUES,
    LEAGUE_DUMMY_COLS,
    ONE_HOT_LEAGUES,
)
from backend.app.ml.odds_analysis_service import (
    LEAGUE_SPORT_KEY,
    LEAGUE_SPORT_KEY_ALTS,
    _LEAGUE_API_SPORTS_ID,
)


# ── League wiring ─────────────────────────────────────────────────────────────

def test_every_predicted_league_has_an_api_football_id():
    """A league we price must be resolvable for stats ingestion.

    2026-07-31: `fetch_club_team_stats` kept its own hand-copied LEAGUE_IDS that
    was missing the twelve leagues added the day before. Every one of their
    clubs fell through to the per-team /teams?search fallback — 177 search calls
    in a run that normally makes 54 — and 50 clubs still ended up with no id at
    all, so their cards showed "—" for cards and corners.
    """
    missing = [lg for lg in ONE_HOT_LEAGUES if lg not in _LEAGUE_API_SPORTS_ID]
    assert not missing, f"leagues with no API-Football id: {missing}"


def test_stats_fetcher_uses_the_shared_league_id_map():
    """The fetcher must not keep a private copy of the league→id mapping."""
    from scripts.fetch_club_team_stats import LEAGUE_IDS

    assert LEAGUE_IDS == dict(_LEAGUE_API_SPORTS_ID), (
        "fetch_club_team_stats.LEAGUE_IDS has drifted from "
        "odds_analysis_service._LEAGUE_API_SPORTS_ID"
    )


def test_history_only_leagues_are_never_one_hot_encoded():
    """History-only leagues are context for Elo/form, never a fixture we price.

    A dummy column for a league that never appears at prediction time is dead
    weight that reads as a real feature.
    """
    overlap = set(ONE_HOT_LEAGUES) & set(HISTORY_ONLY_LEAGUES)
    assert not overlap, f"league is both predicted and history-only: {sorted(overlap)}"


# ── Feature vector ────────────────────────────────────────────────────────────

def test_league_dummies_are_generated_not_hand_written():
    """FEATURE_COLS and DRAW_FEATURE_COLS must carry every league dummy.

    These three lists were maintained by hand and adding a league to some but
    not others produced a column that is always zero — no error, just a feature
    that silently does nothing.
    """
    for name, cols in (("FEATURE_COLS", FEATURE_COLS),
                       ("DRAW_FEATURE_COLS", DRAW_FEATURE_COLS)):
        present = {c for c in cols if c.startswith("league_")}
        missing = set(LEAGUE_DUMMY_COLS) - present
        assert not missing, f"{name} is missing league dummies: {sorted(missing)}"


def test_feature_columns_have_no_duplicates():
    """A repeated column silently doubles that feature's weight in the matrix."""
    for name, cols in (("FEATURE_COLS", FEATURE_COLS),
                       ("DRAW_FEATURE_COLS", DRAW_FEATURE_COLS)):
        dupes = {c for c in cols if cols.count(c) > 1}
        assert not dupes, f"{name} has duplicate columns: {sorted(dupes)}"


# ── Team-name tables ──────────────────────────────────────────────────────────

def test_name_overrides_is_one_shared_table():
    """The read and write sides must be the SAME object, not two copies.

    2026-07-31: club_props held 45 entries and fetch_club_team_stats 60. The
    read side was a strict subset, so stats were ingested for Sion, Thun, LASK,
    Rakow, Univ. Craiova and CFR Cluj and the match page could not find them —
    the rows were in the database the whole time, displayed as "—".
    """
    from scripts.fetch_club_team_stats import NAME_OVERRIDES as WRITE_OVERRIDES

    assert WRITE_OVERRIDES is READ_OVERRIDES, (
        "fetch_club_team_stats defines its own NAME_OVERRIDES again — import "
        "club_props.NAME_OVERRIDES instead, or the two will drift"
    )


def test_no_alias_points_at_a_youth_reserve_or_womens_side():
    """Aliases must resolve to the senior men's team.

    2026-07-31: the /teams?search fallback accepted "SK Rapid W" (women's),
    "CFR Cluj II" (reserves) and "Flamengo RJ U17" because each search returned
    exactly one hit and that was taken as unambiguous. Their match stats would
    have been charged to the first team's cards and corners.
    """
    from scripts.team_resolver import COMMON_ALIASES, is_youth_side

    bad = {src: dst for src, dst in
           {**COMMON_ALIASES, **READ_OVERRIDES}.items()
           if is_youth_side(dst) and not is_youth_side(src)}
    assert not bad, f"alias resolves a senior club onto another side: {bad}"


def test_alias_tables_have_no_self_referential_loops():
    """A → B where B → C means the first hop is dead. Catches half-renames."""
    from scripts.team_resolver import COMMON_ALIASES

    chained = {src: dst for src, dst in COMMON_ALIASES.items()
               if dst in COMMON_ALIASES and COMMON_ALIASES[dst] != dst}
    assert not chained, f"alias target is itself aliased: {chained}"


# ── Bookmaker sport keys ──────────────────────────────────────────────────────

def test_every_sport_key_looks_like_a_real_odds_api_key():
    """Guards the shape, since the value itself needs the network.

    2026-07-30: `Championship` was mapped to "soccer_england_championship",
    which The Odds API answers with {"message": "Unknown sport"} — so that
    league silently carried NO odds at all, for as long as anyone can tell.
    The real key is "soccer_efl_champ". A live check lives in
    test_live_data.py; this one just stops obvious typos.
    """
    for league, key in LEAGUE_SPORT_KEY.items():
        assert key.startswith("soccer_"), f"{league}: {key!r} is not a soccer key"
        assert key == key.lower().strip(), f"{league}: {key!r} has case/space noise"
    for league, alts in LEAGUE_SPORT_KEY_ALTS.items():
        assert league in LEAGUE_SPORT_KEY, f"{league} has alts but no primary key"
        key_set = set(alts)
        assert key_set, f"{league}: empty alternate list"
        assert LEAGUE_SPORT_KEY[league] not in key_set, (
            f"{league}: primary key repeated in its own alternates")


@pytest.mark.parametrize("league", sorted(LEAGUE_SPORT_KEY))
def test_sport_keys_are_unique_per_league(league):
    """Two leagues sharing a key means one of them is silently served the
    other's fixtures — the bug that once wiped out EL and ECL league-phase odds."""
    owners = [lg for lg, k in LEAGUE_SPORT_KEY.items() if k == LEAGUE_SPORT_KEY[league]]
    assert owners == [league], f"sport key shared by {owners}"
