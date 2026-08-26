"""ClubElo cold-start fallback: page parsing, load, linear fit, and seeding.

Pure-logic tests — no network, no artifacts required. A synthetic overlap fixes
the fit so the assertions are deterministic, and the page fixture below is a
hand-cut copy of the real clubelo.com markup rather than a simplification, so a
layout change upstream fails here instead of silently seeding nothing.
"""
import json
from collections import defaultdict

from backend.app.ml.clubelo import (
    fit_clubelo_map,
    load_clubelo,
    load_clubelo_index,
    seed_cold_start,
)
from scripts.fetch_clubelo import parse_snapshot


def _snapshot(elo: dict) -> dict:
    d = defaultdict(lambda: 1500.0)
    d.update(elo)
    return {"elo": d}


# ── clubelo.com page fixture ──────────────────────────────────────────────────
# The ratings we need are NOT in the page's Vega-Lite chart blob (top 50 only) —
# they are in the accordion of per-federation tables below it. Both are present
# here so a parser that reads the wrong one fails loudly: the chart claims
# Bayern is the only German club and knows no minnows at all.

def _row(name: str, elo, href: str | None = None, flag: str = "GER") -> str:
    """One club row. Clubs with their own page carry a link whose slug is the
    untruncated name; most minnows carry no link at all."""
    label = (f'<span class="NonAst">{name[:3].upper()}</span>'
             f'<span class="Ast">{name}</span>')
    if href:
        label = f'<a href="/{href}">{label}</a>'
    return (f'<tr><td class="l"><a href="/{flag}">'
            f'<img alt="{flag}" src="/static/flags/x.png"/></a> '
            f'<span class="min481"><small> 1 </small></span> {label}</td>'
            f'<td class="r">{elo}</td></tr>')


def _section(header: str, body: str) -> str:
    return (f'<div class="accordion-item"><div class="accordion-header"> {header}'
            f'</div><div class="accordion-content"><table class="ast">'
            f'<tr><th class="l">Club</th><th class="r">Elo</th></tr>{body}'
            f'</table></div></div>')


def _level(n: int, teams: int) -> str:
    return f'<tr><td class="l"><i> Level {n} ({teams} teams)</i></td><td><i>⌀1733</i>'


PAGE = (
    '<h1><a href="/2026-08-24/"></a></h1>'
    '<div id="chartEloGolo"></div><script>'
    '{"datasets": {"data-abc": [{"Elo": 2023.0, "FedURL": "GER", '
    '"Level": 1, "Name": "Bayern M\\u00fcnchen"}]}}</script>'
    + _section('<a href="GER">Germany</a>',
               _level(1, 2)
               + _row("Bayern München", 2023, href="Bayern")
               + _row("Dortmund", 1863, href="Dortmund")
               + _level(4, 1)
               + _row("Dortmund II", 1420, href="DortmundII"))
    + _section('<a href="NED">Netherlands</a>',
               _level(1, 2)
               + _row("Willem II", 1394, flag="NED")
               + _row("PSV", 1800, href="PSV", flag="NED")
               + _row("Jong PSV", 1350, flag="NED"))
    + _section('<a href="KOS">Kosovo</a>',
               _level(1, 1) + _row("KF Ballkani", 1356, flag="KOS"))
    + _section('<a href="GIB">Gibraltar</a>', _row("Lincoln", 1312, flag="GIB"))
    + _section('<a href="SMR">San Marino</a>', _row("Tre Fiori", 947, flag="SMR"))
    + _section('<a href="PAR">Paraguay</a>',
               _row("Sportivo Trinide", 1574,
                    href="sportivo-trinidense", flag="PAR"))
    # The confederation roll-ups have no federation link and list national
    # sides, not clubs.
    + _section('Europe', _row("EUR", 1700, flag="EUR"))
)


def _parsed() -> dict:
    return parse_snapshot(PAGE)[1]


def test_fit_requires_minimum_overlap():
    # Only 3 overlapping teams → below _MIN_OVERLAP → no fit.
    our = {f"Team {i}": 1500 + i for i in range(3)}
    clubelo = {f"team{i}": 1500 + i for i in range(3)}
    assert fit_clubelo_map(our, clubelo) is None


def test_fit_recovers_known_linear_relationship():
    # our = 0.5*clubelo + 800 by construction; fit must recover it.
    our, clubelo = {}, {}
    for i in range(40):
        c = 1400 + i * 15
        our[f"Team {i}"] = 0.5 * c + 800
        clubelo[f"team{i}"] = c
    fit = fit_clubelo_map(our, clubelo)
    assert fit is not None
    a, b, lo, hi = fit
    assert abs(a - 0.5) < 1e-6
    assert abs(b - 800) < 1e-3
    assert lo == min(our.values()) and hi == max(our.values())


def test_fit_rejects_zero_spread():
    # All clubelo identical → cannot fit a slope → None (not a crash).
    our = {f"Team {i}": 1500 + i for i in range(40)}
    clubelo = {f"team{i}": 1600.0 for i in range(40)}
    assert fit_clubelo_map(our, clubelo) is None


def _overlap(n=40):
    our, clubelo = {}, {}
    for i in range(n):
        c = 1400 + i * 15
        our[f"Known {i}"] = 0.6 * c + 500
        clubelo[f"known{i}"] = c
    return our, clubelo


def test_seed_only_touches_cold_start_fixture_teams():
    our, clubelo = _overlap()
    snap = _snapshot(our)
    known = set(our)
    clubelo["coldteam"] = 1700.0            # a team absent from `our`
    seeded = seed_cold_start(snap, known, ["Cold Team", "Known 0"], clubelo)
    # Known 0 is skipped (already has history); Cold Team is seeded.
    assert "Known 0" not in seeded
    assert "Cold Team" in seeded
    assert snap["elo"]["Cold Team"] == seeded["Cold Team"]
    # Value follows the fitted map (0.6*1700 + 500 = 1520), inside clamp range.
    assert abs(seeded["Cold Team"] - (0.6 * 1700 + 500)) < 1e-6


def test_seed_clamps_to_observed_range():
    our, clubelo = _overlap()
    snap = _snapshot(our)
    known = set(our)
    hi = max(our.values())
    clubelo["monster"] = 9000.0             # absurd → maps far above our range
    seeded = seed_cold_start(snap, known, ["Monster"], clubelo)
    assert seeded["Monster"] == hi          # clamped, never extrapolated


def test_seed_no_clubelo_is_noop():
    our, _ = _overlap()
    snap = _snapshot(our)
    seeded = seed_cold_start(snap, set(our), ["Whoever"], {})
    assert seeded == {}


def test_seed_unmatched_team_stays_default():
    our, clubelo = _overlap()
    snap = _snapshot(our)
    seeded = seed_cold_start(snap, set(our), ["Totally Unknown XYZ"], clubelo)
    assert seeded == {}
    assert snap["elo"]["Totally Unknown XYZ"] == 1500.0   # defaultdict fallback


# ── page parsing ──────────────────────────────────────────────────────────────

def test_parse_reads_the_accordion_not_the_chart():
    # The chart blob names exactly one club. Anything that reads it instead of
    # the tables below would "work" while seeding none of the clubs this seam
    # exists for.
    clubs = _parsed()
    assert clubs["Bayern München"]["elo"] == 2023.0
    for minnow in ("Lincoln", "Tre Fiori", "KF Ballkani"):
        assert minnow in clubs, f"{minnow} missing — top-N page, not full table"


def test_parse_records_federation_and_level():
    clubs = _parsed()
    assert clubs["Dortmund"]["country"] == "GER"
    assert clubs["Dortmund"]["level"] == 1
    # Gibraltar's section has no "Level N" header at all.
    assert clubs["Lincoln"] == {"elo": 1312.0, "country": "GIB", "level": 0,
                                "aka": ["Lincoln Red Imps"]}


def test_parse_keeps_uefa_only():
    clubs = _parsed()
    # Paraguay is on the page; taking it would put "Guaraní" and "Nacional" and
    # "Racing" into a name space our European fixtures share.
    assert not [c for c in clubs.values() if c["country"] == "PAR"]
    assert "Sportivo Trinide" not in clubs


def test_parse_skips_confederation_rollups():
    # "Europe" is an accordion item with no federation link, listing national
    # sides. A parser keying off the table alone would ingest them as clubs.
    assert "EUR" not in _parsed()


def test_parse_recovers_the_untruncated_name_from_the_href():
    # Display names are cut at 16 characters; the club's own URL is not.
    ned = parse_snapshot(_section('<a href="NED">Netherlands</a>',
                                  _row("Sportivo Trinide", 1574,
                                       href="sportivo-trinidense",
                                       flag="NED")))[1]
    assert "sportivo trinidense" in ned["Sportivo Trinide"]["aka"]


def test_parse_aliases_club_type_prefixes_our_fixtures_omit():
    # Our fixtures say "Ballkani"; the page says "KF Ballkani", and the shared
    # _slug does not strip "KF".
    assert "Ballkani" in _parsed()["KF Ballkani"]["aka"]


def test_parse_drops_reserve_sides():
    clubs = _parsed()
    assert "Dortmund II" not in clubs
    assert "Jong PSV" not in clubs
    assert "Dortmund" in clubs and "PSV" in clubs


def test_parse_keeps_a_first_team_that_merely_looks_like_a_reserve_side():
    # Willem II is an Eredivisie first team. The reserve test is relational —
    # a side only counts as one when the club it names is also in the table —
    # so there being no "Willem" above it is what saves it.
    assert "Willem II" in _parsed()


def test_parse_reads_the_rating_date():
    assert parse_snapshot(PAGE)[0] == "2026-08-24"
    assert parse_snapshot("<h1></h1>")[0] is None


def test_parse_of_a_changed_layout_yields_nothing_rather_than_junk():
    # The caller's floor (MIN_CLUBS) turns this into "keep yesterday's file".
    assert parse_snapshot("<html><body>maintenance</body></html>") == (None, {})


# ── snapshot loading ──────────────────────────────────────────────────────────

def _write(tmp_path, clubs):
    p = tmp_path / "clubelo.json"
    p.write_text(json.dumps({"as_of": "2026-08-24", "count": len(clubs),
                             "clubs": clubs}), encoding="utf-8")
    return str(p)


def test_load_indexes_alternative_spellings(tmp_path):
    p = _write(tmp_path, {"KF Ballkani": {"elo": 1356.0, "country": "KOS",
                                          "level": 1, "aka": ["Ballkani"]}})
    by_slug, names = load_clubelo_index(p)
    assert by_slug["kfballkani"] == 1356.0
    assert by_slug["ballkani"] == 1356.0
    assert names["ballkani"] == "Ballkani"


def test_load_lets_a_real_name_beat_another_clubs_alias(tmp_path):
    # If an alias could displace a name, a club actually called "Ajax" would
    # lose its rating to whatever generated "Ajax" as a guess.
    p = _write(tmp_path, {
        "Ajax": {"elo": 1900.0, "country": "NED", "level": 1},
        "Ajax Cape": {"elo": 1100.0, "country": "NED", "level": 2,
                      "aka": ["Ajax"]},
    })
    assert load_clubelo(p)["ajax"] == 1900.0


def test_load_drops_a_slug_two_clubs_answer_to(tmp_path):
    # _slug strips "city", so both of these reduce to "lincoln". Seeding
    # Gibraltar's Lincoln Red Imps with Lincoln City's rating would be a
    # confident lie; no rating at all falls back to the documented 1500.
    p = _write(tmp_path, {
        "Lincoln": {"elo": 1312.0, "country": "GIB", "level": 0},
        "Lincoln City": {"elo": 1578.0, "country": "ENG", "level": 3},
    })
    assert "lincoln" not in load_clubelo(p)


def test_load_reads_a_snapshot_written_before_aka_existed(tmp_path):
    p = _write(tmp_path, {"Arsenal": {"elo": 2063.76, "country": "ENG",
                                      "level": 1}})
    assert load_clubelo(p) == {"arsenal": 2063.76}


def test_load_missing_file_is_empty():
    assert load_clubelo("/nonexistent/clubelo.json") == {}
    assert load_clubelo_index("/nonexistent/clubelo.json") == ({}, {})


# ── name matching when neither source spells the club the same way ────────────
# Every case below is real: the left-hand name is ours, the right-hand one is
# what clubelo.com prints.

def _seeded(team: str, clubelo_name: str, elo: float = 1700.0):
    """Seed one cold-start team against one extra ClubElo club. Returns the
    seeded value, or None when the two names did not match."""
    our, clubelo = _overlap()
    names = {k: k for k in clubelo}
    from backend.app.ml.features import _slug
    clubelo[_slug(clubelo_name)] = elo
    names[_slug(clubelo_name)] = clubelo_name
    seeded = seed_cold_start(_snapshot(our), set(our), [team], clubelo, names)
    return seeded.get(team)


def test_seed_matches_a_whole_word_prefix():
    # ClubElo drops the city: "Gornik" for our "Gornik Zabrze".
    assert _seeded("Gornik Zabrze", "Gornik") is not None
    assert _seeded("Levski Sofia", "Levski") is not None


def test_seed_refuses_a_prefix_that_stops_mid_word():
    # The dangerous half of the same rule. Each of these is a DIFFERENT club
    # whose name merely starts the same way once _slug removes the spaces;
    # each was a wrong seed before the word-boundary check.
    assert _seeded("Lillestrom", "Lille") is None
    assert _seeded("Vikingur Gota", "Viking") is None
    assert _seeded("Spartak Trnava", "Sparta") is None
    assert _seeded("Bragantino", "Braga") is None


def test_seed_matches_a_name_the_page_cut_at_16_characters():
    # The one mid-word prefix that is admitted, because the page produced it:
    # display names are truncated at exactly 16 characters.
    assert len("Egnatia Rrogozhi") == 16
    assert _seeded("Egnatia Rrogozhinë", "Egnatia Rrogozhi") is not None
    # A short name that merely looks like a prefix gets no such licence.
    assert _seeded("Egnatia Rrogozhinë", "Egnatia Rro") is None


def test_seed_matches_when_our_name_is_the_shorter_one():
    # "Ilves" is our spelling of ClubElo's "Ilves Tampere".
    assert _seeded("Ilves", "Ilves Tampere") is not None
    # …but only up to a word boundary: Portugal's Naval is not Navalcarnero.
    assert _seeded("Naval", "Navalcarnero") is None


def test_seed_prefers_an_exact_match_over_any_prefix():
    our, clubelo = _overlap()
    from backend.app.ml.features import _slug
    names = {k: k for k in clubelo}
    for name, elo in (("Sparta", 1400.0), ("Sparta Rotterdam", 1700.0)):
        clubelo[_slug(name)] = elo
        names[_slug(name)] = name
    seeded = seed_cold_start(_snapshot(our), set(our), ["Sparta Rotterdam"],
                             clubelo, names)
    assert abs(seeded["Sparta Rotterdam"] - (0.6 * 1700 + 500)) < 1e-6


def test_seed_refuses_an_ambiguous_prefix():
    # Two candidates, so neither is safe — "riga" must never swallow "rigasfs".
    our, clubelo = _overlap()
    from backend.app.ml.features import _slug
    names = {k: k for k in clubelo}
    for name in ("Dinamo Kyiv", "Dinamo Minsk"):
        clubelo[_slug(name)] = 1700.0
        names[_slug(name)] = name
    assert seed_cold_start(_snapshot(our), set(our), ["Dinamo"],
                           clubelo, names) == {}


def test_seed_without_names_still_matches_and_stays_safe():
    # compute_predictions passes no name map when it hands in a slug dict, and
    # the older callers here do the same. The half of the rule that needs only
    # our own name keeps working; the half that needs theirs goes quiet rather
    # than guessing.
    our, clubelo = _overlap()
    from backend.app.ml.features import _slug
    clubelo[_slug("Gornik")] = 1700.0
    clubelo[_slug("Ilves Tampere")] = 1700.0
    seeded = seed_cold_start(_snapshot(our), set(our),
                             ["Gornik Zabrze", "Ilves"], clubelo)
    assert "Gornik Zabrze" in seeded
    assert "Ilves" not in seeded
