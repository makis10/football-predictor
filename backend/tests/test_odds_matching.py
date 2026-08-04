"""Can the odds feed's name for a club be tied to ours — and only to ours?

Everything in `test_team_name_mapping.py` checks names against each other and
against the id cache. Nothing checked the OTHER seam: `_teams_match`, which
decides whether a fixture gets bookmaker odds at all. Three bugs lived there
undetected until a user asked why matches showed no odds:

  · `_slug` used NFKD, which does not decompose ł ø đ ħ ß æ œ — those letters
    were dropped outright. "Wisła Kraków" became "wisakrakow", whose tail is
    "rakow", so it matched Raków Częstochowa and its own fixture matched
    nothing at all.
  · containment was a raw substring test, so "Aris" sat inside "Paris FC"
    (p-aris-fc) and "AEK" inside "AE Kifisia FC".
  · nothing used the fact that we ALREADY HOLD both clubs by name. Rangers and
    Angers are two clubs, they meet in the Europa League, and difflib scores
    them 0.92.

A wrong match is worse than no match: the fixture is served with another
club's prices, and the EV and value gate are computed from them.

Offline — CSV names only, no network, no API key.
"""
from __future__ import annotations

import collections
import os

import pytest

from backend.app.ml.odds_analysis_service import (
    EMPTY_ODDS_TTL, LEAGUE_ODDS_TTL, _ALIASES, _slug, _teams_match,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RAW = os.path.join(_ROOT, "backend", "data", "raw")


@pytest.fixture(scope="module")
def clubs() -> list[str]:
    if not os.path.isdir(_RAW):
        pytest.skip("no raw CSV directory in this checkout")
    from scripts.team_resolver import known_team_names
    return sorted(known_team_names())


# ── The invariant that would have caught all three bugs ───────────────────────

def test_no_two_clubs_we_hold_can_be_matched_to_each_other(clubs):
    """Two clubs we both know about must never be confused for one another.

    They meet: a friendly or a European tie puts any two of them in the same
    odds blob, and there the feed offers only names. Since we hold both, the
    matcher can always tell them apart — this asserts it does.

    Pairs are pre-filtered to the ones actually at risk (one name inside the
    other, or a near-identical spelling); comparing all 1.8M pairs would be
    slow and would test nothing extra.
    """
    from difflib import SequenceMatcher

    slugs = {c: _slug(c) for c in clubs if _slug(c)}
    by_initial: dict[str, list[str]] = collections.defaultdict(list)
    for club, slug in slugs.items():
        by_initial[slug[0]].append(club)

    risky: list[tuple[str, str]] = []
    for club, slug in slugs.items():
        for other, other_slug in slugs.items():
            if other <= club:
                continue
            if slug in other_slug or other_slug in slug:
                risky.append((club, other))
    for group in by_initial.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                sa, sb = slugs[a], slugs[b]
                if abs(len(sa) - len(sb)) <= 3 and SequenceMatcher(None, sa, sb).ratio() >= 0.85:
                    risky.append((a, b))

    confused = [(a, b) for a, b in set(risky) if _teams_match(a, b)]
    assert not confused, (
        f"{len(confused)} pairs of distinct clubs match each other — a fixture "
        f"can be priced off the wrong club: {sorted(confused)[:12]}")


# ── The spellings the feed actually uses ─────────────────────────────────────

# (odds-feed name, our name). Every one of these was a fixture served with no
# bookmaker odds until it was fixed.
_MUST_MATCH = [
    ("FC Barcelona", "Barcelona"),
    ("1. FC Köln", "FC Koln"),
    ("AS Roma", "Roma"),
    ("Birmingham City", "Birmingham"),
    ("Preston North End", "Preston"),
    ("Espanyol", "Espanol"),
    ("Wisła Kraków", "Wisla"),               # ł must survive slugging
    ("Wisła Płock", "Wisla Plock"),
    ("Zagłębie Lubin", "Zaglebie"),
    ("Fortuna Sittard", "For Sittard"),      # broken by a 2026-08-04 merge
    ("Sporting Lisbon", "Sp Lisbon"),
    ("Union Saint-Gilloise", "St. Gilloise"),
    ("Hamburger SV", "Hamburg"),
    ("West Bromwich Albion", "West Brom"),
    ("FSV Mainz 05", "Mainz"),               # decorated on both sides
    ("FC Twente Enschede", "Twente"),
    ("AE Kifisia FC", "Kifisia"),
]

# Pairs that must NEVER match. Each is two real clubs.
_MUST_NOT_MATCH = [
    ("Paris FC", "Aris"),                    # p-ARIS-fc
    ("Paris SG", "Aris"),
    ("Larisa", "Aris"),                      # l-ARIS-a
    ("Rangers", "Angers"),                   # difflib 0.92
    ("Angers", "Rangers"),
    ("AE Kifisia FC", "AEK"),                # AE-K-ifisia
    ("Wisła Kraków", "Rakow"),               # wisla-KRAKOW
    ("Barcelona", "Barcelona B"),            # first team vs its B side
    ("Heracles", "Hercules"),
    ("Zagłębie Lubin", "Zaglebie Sosnowiec"),
]


@pytest.mark.parametrize("api_name,our_name", _MUST_MATCH)
def test_feed_spelling_matches_our_club(api_name, our_name):
    assert _teams_match(api_name, our_name), (
        f"{api_name!r} no longer ties to {our_name!r} — that fixture loses its "
        "odds, EV and value gate. Add a slug to _ALIASES[our_name].")


@pytest.mark.parametrize("api_name,our_name", _MUST_NOT_MATCH)
def test_different_clubs_are_never_matched(api_name, our_name):
    assert not _teams_match(api_name, our_name), (
        f"{api_name!r} matches {our_name!r} — the fixture would be priced off "
        "another club's odds, which is worse than having none.")


# ── Slugging ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("letter,expected", [
    ("ł", "l"), ("ø", "o"), ("đ", "d"), ("ð", "d"), ("ħ", "h"),
    ("ŧ", "t"), ("ß", "ss"), ("æ", "ae"), ("œ", "oe"), ("þ", "th"), ("ı", "i"),
])
def test_slug_transliterates_letters_nfkd_cannot_decompose(letter, expected):
    """NFKD splits a letter from a COMBINING mark; these carry the stroke in
    the glyph, so they decompose to nothing and were silently deleted. A
    deleted consonant does not blur a name, it turns it into another one."""
    assert _slug(f"a{letter}b") == f"a{expected}b"


def test_slug_keeps_accented_letters_as_their_base(clubs):
    assert _slug("Malmö FF") == "malmoff"
    assert _slug("Bodø/Glimt") == "bodoglimt"
    assert _slug("Göztepe") == "goztepe"


# ── Alias hygiene ────────────────────────────────────────────────────────────

def test_alias_keys_are_clubs_we_actually_hold(clubs):
    """An alias keyed on a name the training data no longer uses is dead: the
    club it was written for has been merged away and the alias can never fire.
    """
    known = set(clubs)
    stale = sorted(k for k in _ALIASES if k not in known)
    assert len(stale) < 20, (
        f"{len(stale)} _ALIASES keys name no club we hold: {stale[:20]}")


def test_alias_values_are_slugs(clubs):
    """Values are compared against `_slug(api_name)`, so anything with an
    uppercase letter, a space or a dot can never match."""
    bad = {k: [v for v in vals if v != _slug(v)] for k, vals in _ALIASES.items()}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, f"_ALIASES values must already be slugs: {bad}"


# ── Caching a failure ────────────────────────────────────────────────────────

def test_an_empty_league_is_retried_long_before_the_normal_ttl():
    """`_fetch_league_games_cached` used to store an empty list for the full
    30 minutes. One timeout then blanked the bookmaker panel for every fixture
    in that league, with no error logged anywhere — the Eredivisie held zero
    games while the same request by hand returned nine."""
    assert EMPTY_ODDS_TTL < LEAGUE_ODDS_TTL / 5, (
        "an empty odds response must expire far sooner than a real one")

    import inspect

    from backend.app.ml import odds_analysis_service as svc

    source = inspect.getsource(svc._fetch_league_games_cached)
    assert "EMPTY_ODDS_TTL" in source, (
        "_fetch_league_games_cached no longer distinguishes an empty result "
        "from a real one")
