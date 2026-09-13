"""The correct-score grid must look like football.

fit_lambdas_to_probs used to reproduce all four headline targets exactly —
Over 2.5, supremacy, BTTS and draw — with four free knobs and no preference
for a plausible shape. BTTS was met by cutting every scoring draw, and the
draw then had to come back through the one draw cell BTTS does not count:
0-0, inflated up to six times its Poisson weight. Measured 2026-09-13: 0-0 was
the most likely score on 398 of 1,991 upcoming fixtures (20%). On 2,086
settled matches the grid made 0-0 modal on 52.5% of them, and where it stated
P(0-0) >= 0.12 (n=939) it averaged 0.163 against 0.077 realised.

The grid now keeps Over 2.5 and supremacy exact and treats draw and BTTS as
soft targets, with a penalty on bending the draw cells away from Poisson. The
headline projection (project_probs_coherent) keeps the exact fit, so the
probabilities the site publishes do not move.
"""
from __future__ import annotations

import itertools

import pytest

from backend.app.ml.poisson import (
    _matrix_summary,
    _score_matrix,
    compute_extended_poisson_stats,
    fit_lambdas_to_probs,
    project_probs_coherent,
)

# Stored inputs of fixture 22415, whose served grid put 0-0 at 0.1888 beside
# Over 2.5 at 0.567.
H, D, A, O, B = 0.3324, 0.2635, 0.4041, 0.5769, 0.5293

# ph, pd, po, pb — away is 1 - ph - pd. 108 realistic headline combinations.
SWEEP = list(itertools.product((0.25, 0.35, 0.45, 0.55), (0.24, 0.28, 0.31),
                               (0.50, 0.58, 0.66), (0.45, 0.52, 0.60)))


def _grid(ph, pa, po, pb=None):
    f = fit_lambdas_to_probs(ph, pa, po, p_btts=pb)
    assert f is not None, (ph, pa, po, pb)
    return f, _score_matrix(*f)


def _stats(f):
    return compute_extended_poisson_stats(f[0], f[1], rho=f[2], diag=f[3], diag0=f[4])


def test_an_over_leaning_fixture_does_not_get_a_modal_0_0():
    f, m = _grid(H, A, O, B)
    assert _stats(f)["most_likely_score"] != "0-0"
    # Settled matches with a stated Over 2.5 of 0.55-0.65 ended 0-0 6.4% of
    # the time (n=1,195).
    assert m[0][0] < 0.10
    # Plausibility must not be bought by dropping the hard targets.
    s = _matrix_summary(m)
    assert s["over_2_5"] == pytest.approx(O, abs=5e-3)
    assert s["home_win"] - s["away_win"] == pytest.approx(H - A, abs=5e-3)


def test_p00_stays_in_the_observed_range_across_realistic_inputs():
    """77 of these 108 inputs gave P(0-0) > 0.12 before the fix."""
    bad = []
    for ph, pd, po, pb in SWEEP:
        _, m = _grid(ph, 1.0 - ph - pd, po, pb)
        if m[0][0] > 0.12:
            bad.append((ph, pd, po, pb, round(m[0][0], 4)))
    assert not bad, f"P(0-0) > 0.12 on {len(bad)} inputs, e.g. {bad[:4]}"


def test_the_grid_still_agrees_with_the_headline_on_a_feasible_fixture():
    """The fitter exists so the combo markets agree with the published BTTS and
    draw — "GG+Over 41%" beside "NG 65%" was the bug it was written for. Where
    a Poisson-shaped grid can produce the targets, the softer fit must stay
    close to them."""
    ph, pd, pa, po, pb = 0.45, 0.27, 0.28, 0.55, 0.56
    _, m = _grid(ph, pa, po, pb)
    s = _matrix_summary(m)
    assert s["btts"] == pytest.approx(pb, abs=0.025)
    assert s["draw"] == pytest.approx(pd, abs=0.02)


def test_win_to_nil_combos_never_contradict_the_btts_target():
    """Home-win-to-nil plus away-win-to-nil is part of "no BTTS", so it cannot
    materially exceed 1 − P(BTTS) as published."""
    bad = []
    for ph, pd, po, pb in SWEEP:
        f, _ = _grid(ph, 1.0 - ph - pd, po, pb)
        ps = _stats(f)
        if ps["home_win_and_ng"] + ps["away_win_and_ng"] > 1.0 - pb + 0.02:
            bad.append((ph, pd, po, pb))
    assert not bad, f"{len(bad)} contradictions, e.g. {bad[:4]}"


def test_without_a_btts_target_every_draw_carries_the_draw_mass():
    """Legacy rows carry no BTTS. With no BTTS to protect there is no reason to
    load the draw onto 0-0 alone: one knob moves every draw cell together."""
    f, m = _grid(H, A, O)
    assert f[3] == pytest.approx(f[4])
    assert m[0][0] < 0.10


def test_the_headline_projection_is_still_exact():
    """project_probs_coherent keeps the exact fit — the published headline
    numbers must not move. Fails if the softened grid fit leaks into it (it
    would return a draw of 0.2403 here)."""
    p = project_probs_coherent(H, D, A, O, B)
    assert p["draw"] == pytest.approx(D, abs=1e-3)
