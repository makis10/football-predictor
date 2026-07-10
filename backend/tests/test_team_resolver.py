"""
Team-name resolution (scripts/team_resolver.py).

Three rules, each learned from a real corruption in the fixtures table:

1. A corporate/legal affix does not change which club it is.
     "1. FC Heidenheim" → Heidenheim,  "SC Freiburg" → Freiburg
2. A club-identifying word DOES. Two clubs sharing a town are different clubs.
     "Lincoln United" ≠ "Lincoln" (City),  "Plymouth Parkway" ≠ "Plymouth"
   The old substring-containment resolver collapsed these onto one name and we
   stored self-fixtures ("Lincoln vs Lincoln") with phantom predictions. Same
   bug mapped "Inter Club d'Escaldes" (Andorra) onto Inter Milan.
3. A youth/reserve side is the same CLUB but not the same TEAM, so it must
   never resolve to the senior side (an U20 friendly would otherwise land on
   the first team's Elo, form and player stats). A similarity threshold cannot
   catch this: "Borussia Dortmund II" vs "Borussia Dortmund" scores 0.94.
"""
from scripts.team_resolver import build_resolver, is_youth_side, same_club, strip_youth

KNOWN = {
    "Heidenheim", "Hoffenheim", "Nurnberg", "Freiburg", "Bournemouth",
    "Dortmund", "Cagliari", "Bayern Munich", "Inter", "Lincoln", "Plymouth",
    "Cambridge", "Peterboro", "Fiorentina",
}
TEAM_MAP = {"Cambridge United": "Cambridge", "Peterborough": "Peterboro"}


def _resolve():
    return build_resolver(KNOWN, TEAM_MAP)


# ── 1. corporate affixes: same club ──────────────────────────────────────────

def test_corporate_affix_still_resolves_to_the_same_club():
    r = _resolve()
    assert r("1. FC Heidenheim") == "Heidenheim"
    assert r("1899 Hoffenheim") == "Hoffenheim"
    assert r("SC Freiburg") == "Freiburg"
    assert r("AFC Bournemouth") == "Bournemouth"
    assert r("Borussia Dortmund") == "Dortmund"
    assert r("Cagliari Calcio") == "Cagliari"


def test_spelling_drift_resolves():
    assert _resolve()("Bayern München") == "Bayern Munich"


# ── 2. different clubs sharing a town name ───────────────────────────────────

def test_distinct_club_sharing_a_town_never_collapses():
    r = _resolve()
    assert r("Lincoln United") is None
    assert r("Plymouth Parkway") is None
    assert r("Cambridge City") is None
    assert r("Peterborough Sports") is None


def test_minor_club_embedding_a_famous_name_never_collapses():
    r = _resolve()
    assert r("Inter Club d'Escaldes") is None     # not Inter Milan
    assert r("Lincoln Red Imps FC") is None       # not Lincoln City


def test_the_senior_sides_themselves_still_resolve():
    r = _resolve()
    assert r("Lincoln") == "Lincoln"
    assert r("Plymouth") == "Plymouth"
    assert r("Cambridge United") == "Cambridge"   # via TEAM_MAP
    assert r("Peterborough") == "Peterboro"       # via TEAM_MAP


# ── 3. youth / reserve sides ─────────────────────────────────────────────────

def test_youth_and_reserve_sides_never_resolve_to_the_senior_club():
    r = _resolve()
    for name in ("Fiorentina U20", "Bournemouth U21", "Dortmund II",
                 "Fiorentina Youth", "Dortmund Reserves"):
        assert r(name) is None, name


def test_youth_detection_and_stripping():
    assert strip_youth("Fiorentina U20") == ("Fiorentina", True)
    assert strip_youth("Famalicão U23") == ("Famalicão", True)
    assert strip_youth("Borussia Dortmund II") == ("Borussia Dortmund", True)
    assert strip_youth("Fiorentina") == ("Fiorentina", False)
    assert is_youth_side("Bayer Leverkusen U19")
    assert not is_youth_side("Bayer Leverkusen")


def test_same_club_only_for_a_club_against_its_own_youth_side():
    # Skipped: identical features on both sides, Elo would update against itself.
    assert same_club("Fiorentina", "Fiorentina U20")
    assert same_club("Borussia Dortmund", "Borussia Dortmund II")
    # Kept: genuinely different clubs.
    assert not same_club("Lincoln United", "Lincoln")
    assert not same_club("Cambridge City", "Cambridge United")
    assert not same_club("Plymouth Parkway", "Plymouth")
