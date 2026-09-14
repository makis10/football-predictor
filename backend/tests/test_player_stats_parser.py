"""
/fixtures/players parsing, shared by the national and club player-stats
ingesters. API-Football once returned a side with ``team.name: null``
(Chapecoense, fixture 1492373, 2026-09-12): the parser emitted team=None, the
NOT NULL insert failed, and fetch_club_player_stats.py died on that fixture on
every run, so no team after it alphabetically got new stats.
"""
from scripts.fetch_player_stats import _parse_players


def _block(team_id, name, player_id):
    return {
        "team": {"id": team_id, "name": name},
        "players": [{
            "player": {"id": player_id, "name": f"P{player_id}"},
            "statistics": [{"games": {"position": "G", "minutes": 90, "rating": "6.9"},
                            "goals": {"total": None, "assists": None}}],
        }],
    }


def test_both_sides_named():
    rows = _parse_players([_block(1, "Chapecoense-SC", 10), _block(2, "Internacional", 20)],
                          1492373, "2026-09-12", 71)
    assert [(r["team"], r["opponent"]) for r in rows] == [
        ("Chapecoense-SC", "Internacional"), ("Internacional", "Chapecoense-SC")]
    assert rows[0]["rating"] == 6.9 and rows[0]["goals"] == 0


def test_null_side_is_named_from_the_fixture_listing():
    rows = _parse_players([_block(1, None, 10), _block(2, "Internacional", 20)],
                          1492373, "2026-09-12", 71,
                          names_by_id={1: "Chapecoense-SC", 2: "Internacional"})
    assert [(r["team"], r["opponent"]) for r in rows] == [
        ("Chapecoense-SC", "Internacional"), ("Internacional", "Chapecoense-SC")]


def test_null_side_with_a_wrong_id_takes_the_listing_team_left_over():
    # What API-Football actually sent for 1492373: id 22722, not Chapecoense's 132.
    rows = _parse_players([_block(22722, None, 10), _block(119, "Internacional", 20)],
                          1492373, "2026-09-12", 71,
                          names_by_id={132: "Chapecoense-sc", 119: "Internacional"})
    assert [(r["team"], r["opponent"]) for r in rows] == [
        ("Chapecoense-sc", "Internacional"), ("Internacional", "Chapecoense-sc")]


def test_no_guess_when_the_named_side_is_not_in_the_listing():
    rows = _parse_players([_block(22722, None, 10), _block(119, "Internacional", 20)],
                          1492373, "2026-09-12", 71,
                          names_by_id={1: "Team A", 2: "Team B"})
    assert [r["team"] for r in rows] == ["Internacional"]


def test_unresolvable_side_is_dropped_never_stored_as_null():
    rows = _parse_players([_block(1, None, 10), _block(2, "Internacional", 20)],
                          1492373, "2026-09-12", 71)
    assert [r["team"] for r in rows] == ["Internacional"]


def test_national_names_are_still_canonicalised():
    rows = _parse_players([_block(1, "USA", 10), _block(2, "Czechia", 20)], 1, "2026-06-01", 1)
    assert [(r["team"], r["opponent"]) for r in rows] == [
        ("United States", "Czech Republic"), ("Czech Republic", "United States")]
