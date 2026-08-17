"""A curated alias must not swallow every club that merely contains it.

`_ALIASES["Ath Madrid"]` carries the bare string "atletico". Rule (3) of
`build_resolver` matched aliases on plain containment — no check on what was
left over — while rule (2) had required the remainder to be corporate noise
since it was written. So "atletico" scored 50 + 8 against every club in the
Spanish-speaking world spelt with it, and won:

    Club Atlético Osasuna  → Ath Madrid     ← a LaLiga club we price
    Atlético Paranaense    → Ath Madrid     ← a Brazil SerieA club we price
    Atlético Nacional / Baleares / Sanluqueño / Tucumán / San Luis / Ottawa
    Cristo Atlético / Atlético Tordesillas  → Ath Madrid

Only the last pair was ever reported, and only by luck: `fetch_club_friendlies`
warns when BOTH sides of a fixture collapse to one club. A one-sided hit is
silent — the match is filed under the wrong club and its goals feed that club's
Elo and form.

The fix applies rule (2)'s leftover guard to rule (3). Verified against 1,863
real names (every key in club_name_map.json plus every training-data club):
**zero** resolutions changed, so nothing we actually ingest relied on the loose
behaviour.

Offline: CSV/JSON names only, no network, no database.
"""
from __future__ import annotations

import pytest

from scripts.team_resolver import build_resolver, known_team_names


@pytest.fixture(scope="module")
def resolve():
    known = set(known_team_names())
    if not known:
        pytest.skip("training-data names unavailable (no raw CSVs in this checkout)")
    return build_resolver(known)


# ── the real club must still resolve ─────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Atlético Madrid",
    "Atletico Madrid",
    "Atlético Madrid CF",
])
def test_the_actual_club_still_resolves(resolve, name):
    """The guard must not cost us the club the alias exists for."""
    assert resolve(name) == "Ath Madrid"


# ── everything else must NOT ─────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Club Atlético Osasuna",   # LaLiga — we price this club under "Osasuna"
    "Atlético Paranaense",     # Brazil SerieA
    "Atlético Nacional",
    "Atlético Baleares",
    "Atlético Sanluqueño",
    "Atlético Tucumán",
    "Atlético San Luis",
    "Atlético Ottawa",
    "Cristo Atlético",         # the pair that surfaced the bug, 2026-08-16
    "Atlético Tordesillas",
])
def test_other_clubs_do_not_collapse_into_atletico_madrid(resolve, name):
    """None is the right answer here. Unresolved names are collected and
    reported by the fetchers; a WRONG name is silent and corrupts a real
    club's history."""
    assert resolve(name) != "Ath Madrid", (
        f"{name!r} resolved to Atlético Madrid — its results would be credited "
        "to the wrong club's Elo and form"
    )


# ── clubs that share the word but have their own entry keep it ───────────────

@pytest.mark.parametrize("name, expected", [
    ("Atlético Mineiro",    "Atletico-MG"),
    ("Atlético Goianiense", "Atletico Goianiense"),
])
def test_clubs_with_their_own_entry_are_unaffected(resolve, name, expected):
    assert resolve(name) == expected


# ── the guard must not have broken ordinary alias matching ───────────────────

@pytest.mark.parametrize("name, expected", [
    ("Olympique Lyonnais", "Lyon"),      # curated alias, leftover empty
    ("Bayern München",     "Bayern Munich"),  # spelling drift, rule (4)
])
def test_legitimate_alias_and_drift_matches_survive(resolve, name, expected):
    assert resolve(name) == expected


def test_no_alias_is_a_truncation_of_another_alias_of_the_same_club():
    """The shape that made "atletico" dangerous, stated generally.

    `_ALIASES["Ath Madrid"]` held both "atleticomadrid" and "atletico" — the
    second a prefix of the first. A truncated duplicate adds nothing (the full
    spelling already matches) and matches every OTHER club built on the same
    word. Catching the shape is what protects clubs nobody has thought of yet.

    Guarding here rather than in the resolver is deliberate: requiring the
    leftover to be corporate noise was tried on 2026-08-16 and silently
    unresolved Wolverhampton Wanderers and Paris Saint Germain, because a real
    alias IS a prefix of the club's own longer name.
    """
    from backend.app.ml.odds_analysis_service import _ALIASES

    bad = [
        (team, short, long)
        for team, aliases in _ALIASES.items()
        for short in aliases for long in aliases
        if short != long and long.startswith(short)
    ]
    assert not bad, (
        "alias(es) that are truncations of a longer alias for the same club — "
        f"drop the short one, it can only over-match: {bad}"
    )


def test_no_alias_claims_two_different_clubs():
    """An alias must identify exactly one club. If two clubs list aliases where
    one contains the other, an incoming name can satisfy both and which one
    wins comes down to string length."""
    from backend.app.ml.odds_analysis_service import _ALIASES

    owner: dict[str, str] = {}
    clashes = []
    for team, aliases in _ALIASES.items():
        for a in aliases:
            if a in owner and owner[a] != team:
                clashes.append((a, owner[a], team))
            owner[a] = team
    assert not clashes, f"alias claimed by two clubs: {clashes}"


# ── determinism ──────────────────────────────────────────────────────────────

def test_affix_stripping_is_deterministic():
    """`_leftover_is_affixes_only` takes the FIRST affix that fits, and the
    affix table contains nested pairs (fc/afc, fk/ifk, sc/ssc, if/ifk, as/ss).
    While it iterated the SET, which affix won depended on Python's per-process
    string hashing: over five runs of identical input, "AFC Mansfield" resolved
    to Mansfield three times and to None twice. A club's fixtures could be
    ingested one day and skipped the next, with nothing in the logs.

    Longest-first is both deterministic and the correct greedy choice.
    """
    from scripts.team_resolver import _AFFIXES, _AFFIXES_ORDERED

    assert isinstance(_AFFIXES_ORDERED, tuple), (
        "the strip must iterate an ORDERED collection, not the set"
    )
    assert set(_AFFIXES_ORDERED) == set(_AFFIXES), "ordering must not drop affixes"
    lens = [len(a) for a in _AFFIXES_ORDERED]
    assert lens == sorted(lens, reverse=True), (
        "affixes must be tried longest-first, or 'afc' gets stripped as 'fc' "
        "and leaves an 'a' behind"
    )


def test_the_strip_uses_the_ordered_table():
    import inspect

    from scripts import team_resolver

    src = inspect.getsource(team_resolver._leftover_is_affixes_only)
    assert "_AFFIXES_ORDERED" in src and "for a in _AFFIXES:" not in src, (
        "iterating the set makes resolution differ between runs"
    )


@pytest.mark.parametrize("name", ["AFC Mansfield", "IFK Trelleborg", "FC Koln"])
def test_nested_affixes_strip_the_same_way_every_time(resolve, name):
    """Same input, repeated — the answer must not wander."""
    first = resolve(name)
    assert all(resolve(name) == first for _ in range(20))
