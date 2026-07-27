"""
Cross-source team aliases.

The same club is spelled differently by football-data.org, The Odds API and
API-Football. Every mismatch creates a PHANTOM TEAM: a name with no training
history, so the fixture is priced from default features (Elo 1500) while the
real club's league table and record are split in two.

This has now bitten four times — "Bayer Leverkusen"/"AC Milan", the promoted
Championship cohort, the 2026/27 continental intake (Braga, Schalke, Nijmegen…)
and the Greek clubs under three feeds — so the alias table is shared and tested
rather than re-discovered per fetcher.
"""
from scripts.fetch_greek_fixtures import map_team as greek_map
from scripts.fetch_upcoming import map_team as upcoming_map
from scripts.team_resolver import COMMON_ALIASES, build_resolver, known_team_names

# API spelling → the name our training CSVs actually use.
CASES = [
    ("Braga",              "Sp Braga"),
    ("CD Nacional",        "Nacional"),
    ("Vitoria SC",         "Vitoria"),
    ("Málaga",             "Malaga"),
    ("Schalke",            "Schalke 04"),
    ("NEC Nijmegen",       "Nijmegen"),
    ("Go Ahead",           "Go Ahead Eagles"),
    ("Sittard",            "For Sittard"),
    ("Sparta",             "Sparta Rotterdam"),
    ("AEK Athens FC",      "AEK"),
    ("Aris Thessalonikis", "Aris"),
    ("Olympiakos Piraeus", "Olympiakos"),
    ("OFI",                "OFI Crete"),
]


def test_every_alias_target_exists_in_the_training_data():
    """An alias pointing at a name we don't train on would just move the phantom."""
    known = known_team_names()
    missing = {v for v in COMMON_ALIASES.values() if v not in known}
    assert not missing, f"alias targets absent from CSVs: {sorted(missing)}"


def test_resolver_applies_the_shared_aliases():
    resolve = build_resolver(known_team_names())
    for api_name, expected in CASES:
        assert resolve(api_name) == expected, api_name


def test_plain_map_team_fetchers_also_inherit_them():
    """fetch_upcoming / fetch_greek_fixtures don't use the resolver — they map by
    dict — so they need the same fallback or a fix in one feed misses the rest."""
    for api_name, expected in CASES:
        assert upcoming_map(api_name) == expected, f"fetch_upcoming: {api_name}"
        assert greek_map(api_name) == expected, f"fetch_greek_fixtures: {api_name}"


def test_genuinely_new_clubs_are_not_force_mapped():
    """A club we have no history for must keep its own name and be priced from
    default features. Mapping it onto a similar-looking club is far worse than
    admitting we don't know it."""
    resolve = build_resolver(known_team_names())
    for name in ("Elversberg", "Le Mans", "Acad. Viseu", "Kalamata"):
        assert resolve(name) is None, name
        assert name not in COMMON_ALIASES


def test_similar_but_distinct_clubs_stay_apart():
    """Names close enough to trip a fuzzy match, but different clubs."""
    resolve = build_resolver(known_team_names())
    assert resolve("AEK Larnaca") != "AEK"          # Cyprus, not Greece
    assert resolve("Atletico GO") != "Atletico-MG"  # Goianiense vs Mineiro
