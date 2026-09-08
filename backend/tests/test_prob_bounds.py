"""No served probability may be 0 or 1, and no block may shout louder than its
sample.

On 2026-09-07 four fixtures were live on the site asserting a 0% chance of Under
2.5, and two settled rows had already been graded against an impossible claim.
The model believed none of it — raw p_over on the four was 0.78-0.81. Isotonic
regression on binary labels had fitted the certainty in: PAVA's terminal block
held a handful of calibration points that all went over, so its value was k/k.

Three guards now stand between that and a reader. These tests pin each one, and
pin the property rather than today's numbers.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.app.ml.poisson import project_probs_coherent
from backend.app.ml.prob_bounds import (
    FIT_EPS,
    PROB_EPS,
    SmoothedIsotonic,
    probability_isotonic,
)


# ── the calibrator ────────────────────────────────────────────────────────────

def _thin_top(n_big: int = 600, n_top: int = 6):
    """A well-supported body plus a tiny unanimous block at the top — the exact
    shape that produced 1.0 in the live artefact."""
    rng = np.random.RandomState(0)
    x_body = np.linspace(0.20, 0.70, n_big)
    y_body = (rng.rand(n_big) < x_body).astype(float)
    x_top = np.linspace(0.75, 0.83, n_top)
    return np.concatenate([x_body, x_top]), np.concatenate([y_body, np.ones(n_top)])


def test_a_unanimous_handful_does_not_become_certainty():
    """Six calibration points that all went over say very little about the 78th
    percentile of the model's output. Plain isotonic reads them as 1.0."""
    X, y = _thin_top()
    plain = __import__("sklearn.isotonic", fromlist=["IsotonicRegression"]).IsotonicRegression(
        out_of_bounds="clip").fit(X, y)
    assert float(plain.predict([0.80])[0]) == pytest.approx(1.0), (
        "the failure this module exists for did not reproduce; the fixture is wrong")

    ours = probability_isotonic().fit(X, y)
    assert float(ours.predict([0.80])[0]) < 0.95


def test_a_large_block_keeps_its_own_mean():
    """The shrinkage must not reshape a well-supported curve. A block of 600 is
    entitled to its mean; only the thin tails are in scope."""
    rng = np.random.RandomState(1)
    x = np.linspace(0.3, 0.7, 2000)
    y = (rng.rand(2000) < 0.62).astype(float)          # one flat, well-fed block
    m = probability_isotonic().fit(x, y)
    assert float(m.predict([0.5])[0]) == pytest.approx(y.mean(), abs=0.01)


def test_the_output_is_monotone():
    """Shrinking with per-block weights can cross two adjacent blocks — a block
    of two at 0.62 lands below a block of a hundred at 0.60 — so the corrected
    values go back through a weighted PAVA pass. Assert it rather than trust it."""
    X, y = _thin_top()
    p = probability_isotonic().fit(X, y).predict(np.linspace(0, 1, 501))
    assert np.all(np.diff(p) >= -1e-12)


@pytest.mark.parametrize("y_const", [0.0, 1.0])
def test_even_a_unanimous_dataset_cannot_reach_the_endpoint(y_const):
    """The floor under the shrinkage: if every calibration row went the same way,
    the block mean IS the endpoint and only FIT_EPS stands in the way."""
    x = np.linspace(0.1, 0.9, 50)
    p = probability_isotonic().fit(x, np.full(50, y_const)).predict(x)
    assert np.all(p >= FIT_EPS) and np.all(p <= 1.0 - FIT_EPS)


def test_it_drops_in_where_an_isotonic_was():
    """apply_calibration and the national trainer call .predict/.transform on
    whatever load_calibrators hands back. Keep the duck-type intact."""
    X, y = _thin_top()
    m = probability_isotonic().fit(X, y)
    for name in ("predict", "transform", "fit_transform"):
        assert callable(getattr(m, name))
    assert np.allclose(m.predict(X), m.transform(X))


def test_it_survives_a_pickle_round_trip():
    """It is persisted with joblib beside the models and unpickled by the API."""
    import io

    import joblib

    X, y = _thin_top()
    buf = io.BytesIO()
    joblib.dump(probability_isotonic().fit(X, y), buf)
    buf.seek(0)
    assert float(joblib.load(buf).predict([0.80])[0]) < 0.95


def test_a_small_top_block_is_pulled_toward_a_well_supported_neighbour():
    """The shrinkage can be partly undone, and that is correct.

    PAVA's blocks must stay ordered, so after each is shrunk by its own sample
    size the corrected values go back through a weighted pass. A tiny terminal
    block shrunk hard can then land BELOW a large high neighbour, and the pass
    pools the two — lifting the terminal value back up.

    Probed 2026-09-07 on 900 body rows plus three unanimous ones at the top: the
    top block shrank from 1.0000 to 0.8526, the 30-row block below it to 0.9365,
    and pooling put both at 0.9245. That is a legitimate isotonic estimate — the
    height comes from thirty samples, not from three — and it is worth pinning so
    the next reader is not surprised into "fixing" it.
    """
    rng = np.random.RandomState(2)
    X = np.concatenate([np.linspace(0.2, 0.7, 900), np.linspace(0.75, 0.83, 3)])
    y = np.concatenate([(rng.rand(900) < X[:900]).astype(float), np.ones(3)])
    top = float(probability_isotonic().fit(X, y).predict([0.80])[0])
    assert 0.85 < top < 1.0 - FIT_EPS, top


def test_no_amount_of_unanimity_reaches_a_certainty():
    """The adversarial version of the test above: make the neighbour that does
    the pulling enormous and unanimous, at both ends. FIT_EPS is the floor under
    the whole design, and a served probability must clear it on both sides."""
    rng = np.random.RandomState(3)
    grid = np.linspace(0, 1, 2001)

    X = np.concatenate([np.linspace(.1, .5, 400), np.linspace(.55, .9, 400),
                        np.linspace(.92, .99, 3)])
    y = np.concatenate([(rng.rand(400) < 0.3).astype(float), np.ones(400), np.ones(3)])
    hi = probability_isotonic().fit(X, y).predict(grid)
    assert hi.max() <= 1.0 - FIT_EPS

    X2 = np.concatenate([np.linspace(.01, .08, 3), np.linspace(.1, .5, 400),
                         np.linspace(.55, .9, 400)])
    y2 = np.concatenate([np.zeros(3), np.zeros(400), (rng.rand(400) < 0.7).astype(float)])
    lo = probability_isotonic().fit(X2, y2).predict(grid)
    assert lo.min() >= FIT_EPS


@pytest.mark.parametrize("name,X,y", [
    ("one point",          [0.5], [1.0]),
    ("two points",         [0.4, 0.6], [0.0, 1.0]),
    ("every x identical",  [0.5] * 40, [0.0, 1.0] * 20),
    ("perfectly separable", list(np.linspace(.1, .9, 40)),
     list((np.linspace(.1, .9, 40) > 0.5).astype(float))),
    ("relationship reversed", list(np.linspace(.1, .9, 60)),
     list((np.linspace(.1, .9, 60) < 0.5).astype(float))),
    ("x outside [0,1]",    list(np.linspace(-3, 5, 60)),
     list((np.linspace(-3, 5, 60) > 1).astype(float))),
])
def test_degenerate_calibration_samples_do_not_explode(name, X, y):
    """A retrain on a thin league, an empty fold, or a feature that turned out to
    run backwards must produce a usable calibrator rather than a traceback in the
    middle of the nightly job."""
    p = probability_isotonic().fit(np.asarray(X, float), np.asarray(y, float)) \
        .predict(np.linspace(0, 1, 401))
    assert np.all(np.diff(p) >= -1e-12), f"{name}: not monotone"
    assert np.all(p >= FIT_EPS) and np.all(p <= 1.0 - FIT_EPS), f"{name}: out of bounds"


def test_sample_weight_is_forwarded():
    """calibration.py may start weighting rows by recency. If the argument were
    silently dropped the weights would do nothing and nobody would notice."""
    X = np.linspace(0.1, 0.9, 40)
    y = (X > 0.5).astype(float)
    flat = probability_isotonic().fit(X, y).predict(X)
    lopsided = probability_isotonic().fit(
        X, y, sample_weight=np.linspace(1.0, 50.0, 40)).predict(X)
    assert not np.allclose(flat, lopsided), "sample_weight had no effect"


# ── the serving clamp ─────────────────────────────────────────────────────────

def test_the_projection_repairs_a_certainty_instead_of_passing_it_through():
    """The guard used to run in the breakable direction: fit_lambdas_to_probs
    rejects p_over in {0, 1} and returns None, finalise_probabilities does
    `if proj:`, and the fallback kept the very value that broke the fit. A value
    1e-4 away was repaired; 1.0 sailed through untouched.

    These are the four fixtures that were live on 2026-09-07.
    """
    live = [
        (0.8356, 0.1183, 0.0461, 0.6193),   # 18510 Bayern v Union Berlin
        (0.8220, 0.1162, 0.0618, 0.6193),   # 23359 PSV v Heerenveen
        (0.5859, 0.2683, 0.1457, 0.7313),   # 23646 Bayern v RB Leipzig
        (0.8916, 0.0743, 0.0341, 0.5177),   # 24436 PSV v Willem II
    ]
    for h, d, a, btts in live:
        out = project_probs_coherent(h, d, a, 1.0, btts)
        assert out is not None, "the projection still disables itself on p_over = 1.0"
        assert out["over"] < 1.0


@pytest.mark.parametrize("field,args", [
    ("over", (0.40, 0.26, 0.34, 1.0, 0.55)),
    ("over", (0.40, 0.26, 0.34, 0.0, 0.55)),
    ("btts", (0.40, 0.26, 0.34, 0.55, 1.0)),
    ("btts", (0.40, 0.26, 0.34, 0.55, 0.0)),
])
def test_no_endpoint_reaches_the_caller(field, args):
    out = project_probs_coherent(*args)
    assert out is not None
    for k in ("home", "draw", "away", "over", "btts"):
        v = out[k]
        if v is None:
            continue
        assert PROB_EPS / 10 < v < 1.0 - PROB_EPS / 10, f"{k} came back as {v}"


def test_a_feasible_input_still_round_trips_unchanged():
    """The clamp must be a no-op on every real forecast. The whole design of the
    projection rests on feasible inputs surviving it."""
    before = (0.45, 0.27, 0.28, 0.55, 0.56)
    out = project_probs_coherent(*before)
    assert out is not None
    assert out["over"] == pytest.approx(before[3], abs=5e-3)
    assert out["btts"] == pytest.approx(before[4], abs=5e-3)


def test_the_bound_sits_far_outside_any_real_forecast():
    """1e-4 is chosen to clip artefacts and nothing else. The widest served
    spread on record is 0.20-0.88; if PROB_EPS ever grows into that range it
    would start moving genuine numbers."""
    assert PROB_EPS <= 1e-3
    assert FIT_EPS >= PROB_EPS, "a clamped value must never land on the fit bound"
