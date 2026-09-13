"""The headline projection must round-trip what it can.

project_probs_coherent promises that feasible inputs come back unchanged. Its
exact fit ran a fixed three coordinate sweeps, and each knob's solve moves the
other targets (diag0 ← draw shifts BTTS), so targets generated from
_score_matrix itself — an exact solution provably exists — were missed by up
to 0.03 on 133 of 270 grid points. It now sweeps to convergence.
"""
from __future__ import annotations

import itertools

import pytest

from backend.app.ml.poisson import _matrix_summary, _score_matrix, fit_lambdas_to_probs

GRID = list(itertools.product((0.9, 1.3, 1.7), (0.8, 1.2, 1.6), (0.7, 1.0, 1.4), (0.8, 1.0, 1.3)))


def test_a_coherent_triple_comes_back_unchanged():
    """A projection must be a no-op on what is already coherent. The sweeps
    alone moved 469 of 2,500 stored coherent rows by more than a point."""
    from backend.app.ml.poisson import project_probs_coherent

    for lam_h, lam_a, diag, diag0 in GRID[::5]:
        t = _matrix_summary(_score_matrix(lam_h, lam_a, 0.0, diag, diag0))
        p = project_probs_coherent(t["home_win"], t["draw"], t["away_win"],
                                   t["over_2_5"], t["btts"])
        for got, want in ((p["home"], t["home_win"]), (p["draw"], t["draw"]),
                          (p["away"], t["away_win"]), (p["over"], t["over_2_5"]),
                          (p["btts"], t["btts"])):
            assert got == pytest.approx(want, abs=1e-3), (lam_h, lam_a, diag, diag0)


@pytest.mark.parametrize("lam_h, lam_a, diag, diag0", GRID)
def test_targets_a_grid_can_produce_are_met_exactly(lam_h, lam_a, diag, diag0):
    t = _matrix_summary(_score_matrix(lam_h, lam_a, 0.0, diag, diag0))
    fit = fit_lambdas_to_probs(t["home_win"], t["away_win"], t["over_2_5"],
                               p_btts=t["btts"], exact=True)
    s = _matrix_summary(_score_matrix(*fit))
    for key in ("home_win", "draw", "away_win", "over_2_5", "btts"):
        assert s[key] == pytest.approx(t[key], abs=1e-3), key
