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
    """"1. FC", "SC", "AFC", "Calcio" decorate a name without changing the club.

    Asserted against the CANONICAL spelling rather than a literal, because a
    merge moves it: "1. FC Heidenheim" resolved to "Heidenheim" until the club
    was merged onto "FC Heidenheim", and this test then failed on a resolver
    that was doing exactly the right thing.
    """
    from backend.app.ml.features import _CSV_TEAM_CANON

    def canon(name):
        seen = {name}
        while name in _CSV_TEAM_CANON:
            name = _CSV_TEAM_CANON[name]
            if name in seen:
                break
            seen.add(name)
        return name

    r = _resolve()
    for decorated, plain in (("1. FC Heidenheim", "Heidenheim"),
                             ("1899 Hoffenheim", "Hoffenheim"),
                             ("SC Freiburg", "Freiburg"),
                             ("AFC Bournemouth", "Bournemouth"),
                             ("Borussia Dortmund", "Dortmund"),
                             ("Cagliari Calcio", "Cagliari")):
        assert r(decorated) == canon(plain), (
            f"{decorated!r} should resolve to the club stored as "
            f"{canon(plain)!r}, got {r(decorated)!r}")


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


# ── A whole word of the feed's own name ───────────────────────────────────────

def test_a_legal_form_prefix_does_not_hand_the_club_to_a_near_spelling():
    """football-data.org calls AEK Athens "PAE AEK" — ΠΑΕ ΑΕΚ, the Greek legal
    form, the way "PLC" trails an English company.

    The resolver gave it to PAEEK, a Cypriot club: slug "paeek" against
    "paeaek", one character apart, spelling-drift ratio 0.909. The correct
    answer, "AEK", scored ZERO — rule (2)'s >=5-char guard exists to stop "aek"
    hijacking a longer name, and here it excluded the only right candidate.

    Four Champions League fixtures entered the database as PAEEK v LASK,
    Shakhtar v PAEEK, Man City v PAEEK and PAEEK v Real Madrid, each a duplicate
    of the real AEK fixture, each priced off a Cypriot second-tier Elo of 1339.
    One was published on the site beside the genuine AEK card for the same match,
    with LASK apparently playing twice on the same afternoon.
    """
    from scripts.team_resolver import build_resolver, known_team_names

    resolve = build_resolver(known_team_names())
    assert resolve("PAE AEK") == "AEK"


def test_a_whole_word_loses_to_a_longer_club_with_only_noise_left_over():
    """The rule has to sit BETWEEN the other two.

    Scored above affix-containment it tied "Olympiakos" against "Olympiakos
    Volos" on the feed's own "Olympiakos Volos FC", and the resolver refused
    both — turning one bug into another. A longer club matching with only
    corporate noise left over is the better answer and must keep winning.
    """
    from scripts.team_resolver import build_resolver, known_team_names

    resolve = build_resolver(known_team_names())
    assert resolve("Olympiakos Volos FC") == "Olympiakos Volos"


def test_the_word_rule_does_not_reach_a_reserve_side():
    """"Real Sociedad" used to resolve to "Real Sociedad II" — the B team, 88
    rows of history against the senior side's 608. Youth and reserve sides are
    refused before any scoring happens, and the word rule must not reopen that."""
    from scripts.team_resolver import build_resolver, known_team_names

    resolve = build_resolver(known_team_names())
    got = resolve("Real Sociedad")
    assert got is not None and not got.endswith(" II"), got


def test_a_two_letter_word_is_not_a_club_identity():
    """Three characters is the floor. "AEK", "PSV", "OFI" are whole club
    identities; two letters is a country code, a shirt sponsor, or noise."""
    import re

    from backend.app.ml.odds_analysis_service import _slug
    from scripts.team_resolver import build_resolver, known_team_names

    known = known_team_names()
    short = sorted(t for t in known if len(_slug(t)) == 2)
    if not short:
        pytest.skip("no two-letter club names in the training data")
    resolve = build_resolver(known)
    for club in short[:5]:
        # A feed name that merely CONTAINS the two letters as a word must not
        # be handed this club.
        assert resolve(f"{club} Rovers Athletic") != club, club


def test_a_shared_feed_id_groups_a_settled_row_with_an_unsettled_one():
    """dedupe_fixtures could not see the pair it was built for.

    The api-id branch sat below the pairing branch and behind `result is None`,
    so it never ran: an unsettled row took the pairing key and a settled one
    fell through to the date key, and a pair made of one of each never met.
    Iraklis–Asteras of 2026-09-07 sat in the database twice under API-Football
    id 1593305 — once unsettled as "Iraklis 1908 v Asteras Tripolis" and once
    finished 0-2 with the venue reversed, which no unordered key reached either.
    """
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "dedupe_fixtures.py").read_text()
    body = src[src.index("for m in rows:"):src.index("dupes = {")]
    api_at = body.index("apiid")
    pairing_at = body.index('"pairing"')
    assert api_at < pairing_at, (
        "the api-id grouping is below the pairing grouping again, so a row that "
        "carries a feed id never reaches it")
    # …and it must not be gated on the row being unsettled. Look only at the
    # `if` that guards the api-id append, not at the whole preamble.
    guard = body[:api_at].rsplit("if ", 1)[-1]
    assert "result" not in guard, (
        f"the api-id grouping is gated on the result again ({guard.strip()[:60]!r}); "
        f"a settled row and its unsettled twin will never land in the same group")
    ast.parse(src)
