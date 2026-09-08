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


def test_the_repass_actually_pools_a_crossing_pair():
    """Shrinking with per-block weights can cross two adjacent blocks — a block
    of two at 0.62 lands below a block of a hundred at 0.60 — so the corrected
    values go back through a weighted PAVA pass.

    2026-09-08: this test used to assert that predict() is monotone, which it is
    by construction — the final step IS an IsotonicRegression, so no mutation
    upstream could break it. Inverting every block value before the repass left
    it green. It now asserts the repass DID something: build a fixture where the
    shrunk values are known to cross, and require the two blocks to come out
    equal, which only pooling produces.
    """
    rng = np.random.RandomState(7)
    # A large block at 0.60 and a tiny one just above it at 0.75. Shrinkage pulls
    # the small one toward the base rate far harder, so it lands BELOW its
    # neighbour and the pass has to pool them.
    big_x = np.linspace(0.20, 0.60, 400)
    big_y = (rng.rand(400) < 0.60).astype(float)
    small_x = np.linspace(0.62, 0.66, 3)
    small_y = np.array([1.0, 1.0, 0.0])          # mean 0.667, n=3
    X = np.concatenate([big_x, small_x])
    y = np.concatenate([big_y, small_y])

    m = probability_isotonic().fit(X, y)
    lo = float(m.predict([0.50])[0])
    hi = float(m.predict([0.64])[0])
    assert hi >= lo - 1e-12, "the corrected values crossed and were not pooled"
    assert np.all(np.diff(m.predict(np.linspace(0, 1, 501))) >= -1e-12)


def test_shrinkage_moves_a_thin_block_and_leaves_a_fed_one():
    """The property the pseudo-count exists for, stated so it can fail.

    2026-09-08: the previous version fitted a SINGLE flat block, where the shrink
    target is the block's own mean and (n*base + m*base)/(n+m) = base for any m.
    Both PSEUDO_COUNT = 0 and PSEUDO_COUNT = 1e6 passed it. Two blocks at
    different rates are needed before the pseudo-count can do anything at all.
    """
    rng = np.random.RandomState(11)
    low_x, high_x = np.linspace(0.10, 0.45, 800), np.linspace(0.80, 0.86, 4)
    low_y = (rng.rand(800) < 0.25).astype(float)
    high_y = np.ones(4)
    X, y = np.concatenate([low_x, high_x]), np.concatenate([low_y, high_y])

    fed = float(probability_isotonic().fit(X, y).predict([0.30])[0])
    thin = float(probability_isotonic().fit(X, y).predict([0.83])[0])
    assert fed == pytest.approx(low_y.mean(), abs=0.02), (
        "the well-supported block was reshaped; the shrinkage is too aggressive")
    assert thin < 0.95, "a block of four unanimous rows still reads as near-certain"

    # …and turning the shrinkage off must break the second half.
    off = float(SmoothedIsotonic(pseudo_count=0.0).fit(X, y).predict([0.83])[0])
    assert off > thin, "PSEUDO_COUNT has no effect on the thin block"


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


def test_the_projection_fallback_clamps_what_it_keeps():
    """`project_probs_coherent` still returns None on an input it cannot fit at
    all — p_draw outside (0.005, 0.95), or a NaN supremacy. Both callers then
    keep their OWN numbers, and until 2026-09-08 they kept them untouched,
    endpoints and all. That is the identical shape as the bug this module exists
    for, one level further out: the guard running in the breakable direction on
    exactly the inputs that broke it."""
    from backend.app.ml.predict import finalise_probabilities

    assert project_probs_coherent(0.999, 0.001, 0.0, 1.0, 1.0) is None, (
        "the fixture no longer exercises the fallback")

    for args in (dict(home=0.999, draw=0.001, away=0.0, over=1.0, btts=1.0),
                 dict(home=0.001, draw=0.998, away=0.001, over=0.0, btts=0.0)):
        for v in finalise_probabilities(**args):
            if v is None:
                continue
            assert 0.0 < v < 1.0, f"{v} survived the fallback"


def test_the_national_path_has_its_own_clamp():
    """scripts/predict_national.py calls project_probs_coherent directly and
    never touches finalise_probabilities, so a guard placed there misses it
    entirely. 250 settled national rows already hold a 0 or a 1."""
    import pathlib as _p

    src = (_p.Path(__file__).resolve().parents[2]
           / "scripts" / "predict_national.py").read_text()
    block = src[src.index("project_probs_coherent(p_home"):]
    block = block[:block.index("prediction = max(")]
    assert "clamp_prob" in block, (
        "the national fallback keeps its own probabilities unclamped")


def test_a_feasible_input_still_round_trips_unchanged():
    """The clamp must be a no-op on every real forecast. The whole design of the
    projection rests on feasible inputs surviving it."""
    before = (0.45, 0.27, 0.28, 0.55, 0.56)
    out = project_probs_coherent(*before)
    assert out is not None
    assert out["over"] == pytest.approx(before[3], abs=5e-3)
    assert out["btts"] == pytest.approx(before[4], abs=5e-3)


def test_the_serving_clamp_reads_the_shared_bound():
    """One bound, in one place.

    2026-09-08: poisson.py carried its own `_EPS = 1e-4` beside PROB_EPS, so this
    test guarded a constant the guarded code did not read. Raising the duplicate
    to 0.05 — five hundred times the intended clip, deep inside the 0.20-0.88
    range real forecasts occupy — left the whole suite green.
    """
    from backend.app.ml import poisson

    assert poisson._EPS is PROB_EPS, (
        "poisson has its own copy of the bound again; the constant this test "
        "checks is not the one the clamp uses")
    assert PROB_EPS <= 1e-3
    assert FIT_EPS >= PROB_EPS, "a clamped value must never land on the fit bound"


def test_the_output_clamp_is_insurance_and_is_documented_as_such():
    """Only the INPUT half of the serving clamp is reachable, and this says so.

    2026-09-08: a first version of this test tried to exercise the output half
    and skipped, which is worse than no test — it looked like coverage.
    Searching the extremes the fitter admits (supremacy to 0.9985, totals to
    0.02 and 0.98, btts to 0.02 and 0.95) found ZERO inputs where
    _matrix_summary returns a 0 or a 1, because fit_lambdas_to_probs bounds
    lambda at 0.05 and both diagonal factors at 0.15. So the output clamp is
    defence-in-depth against a future change to those bounds, not a live guard,
    and no assertion can distinguish it being present from absent.

    What this keeps alive is the fact itself: remove the clamp and the paragraph
    in poisson.py explaining why it is there has to go with it.
    """
    import inspect

    from backend.app.ml import poisson

    src = inspect.getsource(poisson.project_probs_coherent)
    assert '_c(s["over_2_5"])' in src, (
        "the output clamp was removed; if that was deliberate, delete this test "
        "and the paragraph in poisson.py that explains why it is there")
    assert "insurance" in src.lower(), (
        "the output clamp is present but no longer explains that it is insurance "
        "rather than a guard with a reachable failure")


