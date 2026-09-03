"""UEFA ties: our own Elo is worse than backing the home side.

`club_elo()` builds ratings from our results with every league pooled and each
club starting at 1500. Inside a league that is exactly the feature the model was
trained on. Across leagues it is close to meaningless, because they barely play
each other — a club that dominates a small country climbs against opponents
whose ratings never had a reason to fall.

Measured 2026-09-03 on 296 settled CL/EL/ECL ties:

    spearman(our elo_diff, clubelo_diff)  0.247  (0.118 on mixed pairings)
    disagreement about who is favourite   40.2%

    higher ClubElo + 80 home advantage    60.5%
    always the home side                  50.7%
    our served argmax                     49.3%
    higher OUR Elo + 60 home advantage    44.3%

On 373 held-out ties the ClubElo split lifts accuracy 48.26% -> 53.08% and
log-loss 1.0590 -> 0.9849 (paired bootstrap: +4.81pp, 95% CI [+0.54, +9.12]).

These tests pin the properties the measurement relies on, not the numbers
themselves: the draw is ours, the split is ClubElo's, it is symmetric, it only
touches UEFA, and it declines to act rather than guess.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.app.ml.european_blend import (
    MIN_FIT_ROWS,
    UEFA_LEAGUES,
    _EloSplitModel,
    apply_elo_split,
    is_uefa,
)


class _FakeLR:
    """P(home) rises with the Elo gap; P(draw) is flat. Enough to exercise the
    blending arithmetic without fitting anything."""

    @staticmethod
    def predict_proba(X):
        out = []
        for (d,) in np.asarray(X):
            p_h = 1.0 / (1.0 + np.exp(-1.2 * d))
            rest = 1.0 - 0.25
            out.append([rest * p_h, 0.25, rest * (1.0 - p_h)])
        return np.asarray(out)


@pytest.fixture()
def split_model() -> _EloSplitModel:
    return _EloSplitModel(_FakeLR(), n_fit=500)


BASE = (0.40, 0.26, 0.34)


def test_our_draw_probability_survives_untouched(split_model):
    """The whole design rests on this. ClubElo's own draw AUC is 0.399 — worse
    than random, because one strength gap cannot express 'these two cancel out'.
    If a future edit lets ClubElo set the draw, the measured gain goes away."""
    out = apply_elo_split(BASE, 1900.0, 1300.0, split_model)
    assert out[1] == pytest.approx(BASE[1], abs=1e-9)
    assert sum(out) == pytest.approx(1.0, abs=1e-9)


def test_the_home_away_split_follows_clubelo_not_the_model(split_model):
    """A big favourite must come out favoured even when the model disagreed."""
    modelled_away_favourite = (0.20, 0.26, 0.54)
    out = apply_elo_split(modelled_away_favourite, 1950.0, 1250.0, split_model)
    assert out[0] > out[2], (
        "the club ClubElo rates 700 points higher did not end up favoured")


def test_reversing_the_tie_reverses_the_split(split_model):
    """Same two clubs, other ground: home and away swap. Nothing else may."""
    a = apply_elo_split(BASE, 1900.0, 1400.0, split_model)
    b = apply_elo_split(BASE, 1400.0, 1900.0, split_model)
    assert a[1] == pytest.approx(b[1], abs=1e-9)
    # The fake LR has no home-advantage term, so the reversal is exact.
    assert a[0] == pytest.approx(b[2], abs=1e-9)
    assert a[2] == pytest.approx(b[0], abs=1e-9)


@pytest.mark.parametrize("home_strength,away_strength,model", [
    (None,   1500.0, "model"),      # club missing from ClubElo
    (1500.0, None,   "model"),
    (None,   None,   "model"),
    (1900.0, 1200.0, None),         # no fitted model
])
def test_it_declines_rather_than_guesses(home_strength, away_strength, model, split_model):
    """A tie between two clubs ClubElo does not carry is exactly the case this
    cannot help with. Returning the model's own answer is the correct fallback —
    the previous behaviour, not a worse one."""
    m = split_model if model else None
    assert apply_elo_split(BASE, home_strength, away_strength, m) == BASE


def test_a_degenerate_split_is_ignored():
    """If the fitted model somehow puts no mass on either side, keep ours."""

    class _Degenerate:
        @staticmethod
        def predict_proba(X):
            return np.tile([0.0, 1.0, 0.0], (len(np.asarray(X)), 1))

    assert apply_elo_split(BASE, 1900.0, 1200.0,
                           _EloSplitModel(_Degenerate(), 500)) == BASE


def test_a_certain_draw_is_left_alone(split_model):
    """p_draw = 1 leaves no mass to split; the result must stay a probability."""
    out = apply_elo_split((0.0, 1.0, 0.0), 1900.0, 1200.0, split_model)
    assert sum(out) == pytest.approx(1.0, abs=1e-9)
    assert out[1] == pytest.approx(1.0, abs=1e-9)


def test_only_uefa_competitions_are_touched():
    """Inside one league our Elo is the feature the model was trained on and is
    not broken. Applying this to domestic fixtures would replace a fitted signal
    with a one-feature logistic."""
    assert UEFA_LEAGUES == {"CL", "EL", "ECL"}
    for lg in ("CL", "EL", "ECL"):
        assert is_uefa(lg)
    for lg in ("EPL", "GreekSL", "BrazilSerieA", "ClubFriendly", "International", None):
        assert not is_uefa(lg)


def test_the_fit_refuses_a_sample_too_small_to_trust():
    """Below MIN_FIT_ROWS the logistic is noise; the caller must get None and
    leave predictions alone."""
    from backend.app.ml import european_blend as eb

    assert MIN_FIT_ROWS >= 100
    original = eb._finished_csv_rows
    try:
        eb._finished_csv_rows = lambda: [("A", "B", 0)] * (MIN_FIT_ROWS - 1)
        assert eb.fit_elo_split_model(db=None) is None
    finally:
        eb._finished_csv_rows = original


def test_the_real_fit_produces_a_usable_model():
    """End to end against the CSVs actually on disk: it must fit, and it must
    rate a European giant above a minnow."""
    from backend.app.ml.clubelo_ratings import european_strength
    from backend.app.ml.european_blend import fit_elo_split_model

    model = fit_elo_split_model(db=None)
    if model is None:
        pytest.skip("not enough finished UEFA ties on disk")
    assert model.n_fit >= MIN_FIT_ROWS

    st = european_strength(["Real Madrid", "Lincoln Red Imps"])
    if st.get("Real Madrid") is None or st.get("Lincoln Red Imps") is None:
        pytest.skip("ClubElo snapshot does not carry both clubs")

    out = apply_elo_split(BASE, st["Real Madrid"], st["Lincoln Red Imps"], model)
    assert out[0] > BASE[0], "Real Madrid at home did not gain against a minnow"
    assert out[0] > out[2]


def test_the_blend_never_reads_the_uncovered_floor():
    """european_strength() substitutes a flat 15th-percentile value for clubs
    ClubElo does not carry. That is right for the projections page, which is
    saying "we cannot rank these", and wrong here, where it reads as a confident
    claim that the club is poor.

    2026-09-03: the first wiring used it, and Atlético Madrid came out at the
    1309 floor rather than its actual 1881, inflating Liverpool's win
    probability against them to 0.606. The blend must consult the direct table
    and leave unrated fixtures alone.
    """
    import ast
    import pathlib

    from backend.app.ml import european_blend as eb

    def calls(path: pathlib.Path) -> set[str]:
        out: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    out.add(fn.id)
                elif isinstance(fn, ast.Attribute):
                    out.add(fn.attr)
        return out

    # A CALL, not a mention — the comments here deliberately name the function
    # they are warning against.
    assert "european_strength" not in calls(pathlib.Path(eb.__file__)), (
        "european_blend calls european_strength, which fills unknown clubs with "
        "a floor value — use clubelo_by_our_name() so a missing club stays "
        "missing and apply_elo_split declines")

    cp = pathlib.Path(eb.__file__).resolve().parents[3] / "scripts" / "compute_predictions.py"
    if cp.exists():
        assert "european_strength" not in calls(cp), (
            "compute_predictions calls european_strength — if that is for the "
            "blend it reintroduces the floor; give the blend clubelo_by_our_name()")


def test_the_clubs_that_were_silently_unrated_now_resolve():
    """Four UEFA regulars were falling to the floor because the alias table was
    matched literally against ClubElo's own spelling: it said "Atletico" while
    ClubElo writes "Atlético". Matching now folds accents and case."""
    from backend.app.ml.clubelo_ratings import _alias_for, clubelo_by_our_name

    assert _alias_for("Atlético") == _alias_for("Atletico") == "Ath Madrid"

    # The table itself is a daily snapshot whose membership changes, so assert
    # the MECHANISM, not today's contents: every alias whose ClubElo-side name is
    # present in the snapshot must resolve to our club. Naming four specific
    # clubs here failed in CI the first time, against an older snapshot that
    # simply did not carry OFI — a test coupled to refreshed data, not to the
    # bug it was meant to pin.
    import json
    import pathlib

    from backend.app.ml.clubelo_ratings import _CLUBELO_ALIASES, _fold

    snapshot = pathlib.Path(__file__).resolve().parents[1] / "data" / "clubelo.json"
    if not snapshot.exists():
        pytest.skip("no ClubElo snapshot on disk")
    clubs = json.loads(snapshot.read_text()).get("clubs") or {}
    if not clubs:
        pytest.skip("ClubElo snapshot carries no clubs")

    present = {_fold(name) for name in clubs}
    table = clubelo_by_our_name()
    unresolved = [
        (clubelo_name, our_name)
        for clubelo_name, our_name in _CLUBELO_ALIASES.items()
        if _fold(clubelo_name) in present and table.get(our_name) is None
    ]
    assert not unresolved, (
        f"aliases whose ClubElo entry exists but did not reach our club: "
        f"{unresolved}")

    # …and the Spanish alias must still never reach the Brazilian club.
    assert table.get("Atletico-MG") is None
