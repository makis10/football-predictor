"""
UEFA (CL / EL / ECL) ingestion guards.

Two bugs these lock down, both found when the July qualifying rounds were first
pulled in from API-Football:

1. The shared fuzzy resolver mapped minor clubs onto famous ones by substring
   containment — "Inter Club d'Escaldes" → "Inter" (Milan), "Lincoln Red Imps
   FC" → "Lincoln" — handing a giant's Elo and rolling stats to a minnow.
   (Resolution rules themselves are covered in test_team_resolver.py.)
2. Every qualifying tie is priced from neutral default features (no CSV history
   for either club), so they all collapse onto the same few probabilities. They
   were being served as "medium"/"high" confidence.
"""
from backend.app.ml.predict import confidence_for
from scripts.fetch_european_fixtures import build_strict_resolver

KNOWN = {"Inter", "Lincoln", "Arsenal", "Bayern Munich", "Freiburg", "Real Madrid"}


def test_minor_club_does_not_collapse_onto_famous_one():
    resolve = build_strict_resolver(KNOWN)
    # The exact regressions: neither may resolve to the big club it embeds.
    assert resolve("Inter Club d'Escaldes") is None
    assert resolve("Lincoln Red Imps FC") is None


def test_exact_and_near_identical_names_still_resolve():
    resolve = build_strict_resolver(KNOWN)
    assert resolve("Arsenal") == "Arsenal"            # exact slug
    assert resolve("Bayern München") == "Bayern Munich"  # spelling drift
    assert resolve("SC Freiburg") == "Freiburg"       # explicit TEAM_MAP entry


def test_unrelated_name_resolves_to_nothing():
    resolve = build_strict_resolver(KNOWN)
    assert resolve("Vestri") is None
    assert resolve("Floriana") is None


def test_no_history_forces_low_confidence():
    """A default-feature prediction may never be labelled medium/high."""
    # Same probabilities, only has_history differs.
    assert confidence_for("CL", 0.54, 0.52, has_history=False) == "low"
    assert confidence_for("CL", 0.90, 0.80, has_history=False) == "low"
    # With history the composite formula is free to say more than "low".
    assert confidence_for("CL", 0.90, 0.80, has_history=True) != "low"


def test_club_friendly_stays_low_regardless():
    assert confidence_for("ClubFriendly", 0.90, 0.80, has_history=True) == "low"
