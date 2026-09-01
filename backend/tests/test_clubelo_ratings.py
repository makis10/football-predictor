"""European simulations need ONE scale across 55 federations.

club_elo() pools every league from a shared 1500 start, and the leagues barely
play each other — so each is a closed pool where a dominant club climbs against
opponents whose ratings never had a reason to fall. Measured 2026-09-01:

    Lincoln Red Imps (Gibraltar)  1847      Juventus  1837
    Inter d'Escaldes (Andorra)    1838      Ajax      1825
    Riga (Latvia)                 1876      Milan     1798
    Borac Banja Luka (Bosnia)     1867      Atalanta  1777

The Europa League simulation duly made Levski Sofia a likelier winner than
Milan, and the Conference League was led by Riga.
"""
from __future__ import annotations

import pytest

from backend.app.ml.clubelo_ratings import clubelo_by_our_name, european_strength


@pytest.fixture(scope="module")
def table():
    t = clubelo_by_our_name()
    if not t:
        pytest.skip("clubelo.json absent in this checkout")
    return t


def test_the_big_clubs_are_actually_mapped(table):
    """ClubElo uses its own short forms — Bayern, Brugge, Atletico, PSV. Left
    unmapped they fall through to the fallback, which is how a Gibraltar
    champion came to outrank them."""
    for club in ("Bayern Munich", "Ath Madrid", "PSV Eindhoven", "Club Brugge",
                 "Milan", "Juventus", "Ajax"):
        assert club in table, f"{club} did not map to a ClubElo entry"


def test_a_spanish_rating_never_lands_on_a_brazilian_club(table):
    """The resolver maps a bare "Atletico" (ESP in ClubElo) onto Atlético
    MINEIRO. Without the country guard, Atlético Madrid's rating crosses an
    ocean."""
    assert table.get("Atletico-MG") != table.get("Ath Madrid")


def test_the_micro_league_sides_rank_below_the_big_ones():
    """The whole point. Not an assertion about any single club's number — just
    that the ORDER stops being nonsense."""
    strength = european_strength([
        "Milan", "Juventus", "Ajax", "Atalanta",
        "Lincoln Red Imps FC", "Inter Club d'Escaldes", "Borac Banja Luka",
    ])

    for big in ("Milan", "Juventus", "Ajax", "Atalanta"):
        for small in ("Lincoln Red Imps FC", "Inter Club d'Escaldes",
                      "Borac Banja Luka"):
            assert strength[big] > strength[small], f"{small} outranks {big}"


def test_an_uncovered_club_is_placed_low_not_at_the_default():
    """1500 was the old behaviour and it is ABOVE most of the real
    distribution — which is precisely why the minnows floated to the top."""
    strength = european_strength(["Lincoln Red Imps FC"])

    assert strength["Lincoln Red Imps FC"] < 1500


def test_every_team_asked_for_gets_a_rating():
    """The simulation indexes elo[t] directly; a missing key is a crash mid-run
    rather than a bad projection."""
    teams = ["Milan", "Some Club That Does Not Exist", "Borac Banja Luka"]

    strength = european_strength(teams)

    assert set(strength) == set(teams)
