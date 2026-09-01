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


def test_enough_of_the_field_is_mapped_to_be_useful(table):
    """Not specific clubs: ClubElo's spellings change between snapshots — one
    said "Bayern", the next "Bayern München" — and a test naming them fails on
    the upstream's whim rather than on ours. What must hold is that the table
    is populated enough to rank a European field."""
    assert len(table) >= 200, f"only {len(table)} clubs mapped"


def test_uncovered_clubs_are_not_ranked_against_each_other():
    """Ordering them by our own Elo was tried and reverted — that Elo is wrong
    precisely because it is per-pool, so it put Lincoln Red Imps above Dinamo
    Zagreb. Equal values say "we do not know", which is true."""
    s = european_strength(["Lincoln Red Imps FC", "PAEEK",
                           "Inter Club d'Escaldes"])

    assert len(set(s.values())) == 1


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
