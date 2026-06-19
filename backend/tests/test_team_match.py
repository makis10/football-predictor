"""Fuzzy team-name matching between The Odds API names and our DB names."""
from backend.app.ml.odds_analysis_service import _slug, _teams_match


def test_slug_strips_accents_and_punctuation():
    assert _slug("1. FC Köln") == "1fckoln"
    assert _slug("Atlético Madrid") == "atleticomadrid"


def test_exact_and_contains_match():
    assert _teams_match("FC Barcelona", "Barcelona")
    assert _teams_match("AS Roma", "Roma")


def test_cagliari_alias_matches():
    # Regression: the alias was previously misspelled "caglaricalcio".
    assert _teams_match("Cagliari Calcio", "Cagliari")


def test_short_slug_guard_blocks_spurious_match():
    # A 1–3 char slug must not match an unrelated longer name.
    assert not _teams_match("PSV", "PS")


def test_unrelated_teams_do_not_match():
    assert not _teams_match("Liverpool", "Everton")
