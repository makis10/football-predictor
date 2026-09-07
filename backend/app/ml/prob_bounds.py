"""One calibrator for probabilities, and one bound, written once.

2026-09-07. Four fixtures were live on the site asserting a 0% chance of Under
2.5 — Bayern v Union Berlin, PSV v Heerenveen, Bayern v RB Leipzig, PSV v Willem
II — and two settled rows had already been graded against an impossible claim
(Club Brugge 1-0 Cercle at p_over = 1.0, Heerenveen 0-0 Ajax at p_btts = 1.0).

Nothing in the model believed any of it: the raw classifier outputs on those
four were 0.78-0.81. The certainty was fitted INTO the calibrator. Isotonic
regression on binary labels gives every member of a PAVA block the block's own
mean, so a terminal block whose handful of points all went over is worth exactly
1.0. The live goals artefact read:

    raw 0.7468-0.7684  ->  0.8333     (five of six)
    raw 0.7698-0.8259  ->  1.0000     (k of k)

Those are the honest block means and they are terrible estimates: a block of six
says almost nothing about the 78th percentile of the model's output.

Three guards, because each alone has a hole:

  * `SmoothedIsotonic` — the real fix. A block cannot claim more certainty than
    its sample size supports. Takes effect at the next retrain.
  * `FIT_EPS` inside it — a hard stop on the endpoints even if the shrinkage is
    ever removed or a block is enormous and unanimous.
  * `PROB_EPS` at serving time (poisson.project_probs_coherent) — covers
    artefacts already on disk and any future path that builds a probability some
    other way.

Measured, walk-forward over 1,460 held-out settled matches (expanding window,
five folds, raw model output as the calibrator input):

    uncalibrated raw   0.6776
    base-rate constant 0.6826
    plain isotonic     0.6806     <- worse than not calibrating at all
    bounded isotonic   0.6759
    smoothed isotonic  0.6722

    smoothed vs plain  -0.0085, 95% CI [-0.0257, +0.0012], P(better) = 0.903
    smoothed vs raw    -0.0054, 95% CI [-0.0099, -0.0006], P(better) = 0.987

The first of those does NOT clear this project's 0.95 shipping bar, so the
log-loss gain is not the argument and is not claimed as one. The argument is
that plain isotonic was serving 1.0000 for a model belief of 0.78, and this
serves 0.8279. The improvement is a bonus that never turned negative in any
fold. What the second line does establish is that calibrating at all was only
worth it once the terminal blocks stopped shouting.
"""
from __future__ import annotations

from sklearn.isotonic import IsotonicRegression

#: Serving-time clamp, applied to stored/served probabilities.
PROB_EPS = 1e-4

#: Fit-time bound, one order looser than PROB_EPS so a clamped value is never
#: itself on the boundary and the two guards cannot be confused in a traceback.
FIT_EPS = 1e-3

#: Pseudo-count for the block shrinkage. Deliberately timid: this exists to stop
#: terminal blocks shouting, not to reshape the middle of a well-supported curve.
#: A block of 600 keeps 99.7% of its own mean; a block of 6 keeps 75%.
PSEUDO_COUNT = 2.0


class SmoothedIsotonic:
    """Isotonic calibration whose blocks cannot claim more certainty than the
    sample behind them supports.

    Each PAVA block is shrunk toward the overall base rate with a pseudo-count:

        v = (sum_y + m * base_rate) / (n + m)

    Shrinkage with per-block weights can cross two adjacent blocks (a block of
    two at 0.62 lands below a block of a hundred at 0.60), so the corrected
    values are pushed back through a weighted PAVA pass. The result is monotone
    by construction, and the tests assert it rather than trusting the argument.

    Duck-types `IsotonicRegression` — `.fit`, `.predict`, `.transform` — so it
    drops into every call site that had one, and `apply_calibration` needs no
    change. Artefacts pickled before this landed are plain IsotonicRegression
    and keep working; they simply keep their old plateau until the next retrain.
    """

    def __init__(self, pseudo_count: float = PSEUDO_COUNT, out_of_bounds: str = "clip"):
        self.pseudo_count = float(pseudo_count)
        self.out_of_bounds = out_of_bounds

    def fit(self, X, y, sample_weight=None):
        import numpy as np

        X = np.asarray(X, dtype=float).ravel()
        y = np.asarray(y, dtype=float).ravel()
        base = float(y.mean()) if y.size else 0.5

        raw = IsotonicRegression(out_of_bounds=self.out_of_bounds).fit(
            X, y, sample_weight=sample_weight)
        blocks = np.asarray(raw.predict(X), dtype=float)

        # Group by fitted value: PAVA gives every member of a block the same one.
        order = np.argsort(blocks, kind="mergesort")
        vals, starts = np.unique(blocks[order], return_index=True)
        edges = list(starts) + [len(order)]

        m = self.pseudo_count
        shrunk = np.empty(len(vals)); weights = np.empty(len(vals)); reps = np.empty(len(vals))
        for k in range(len(vals)):
            idx = order[edges[k]:edges[k + 1]]
            n = float(len(idx))
            shrunk[k]  = (y[idx].sum() + m * base) / (n + m)
            weights[k] = n
            reps[k]    = X[idx].mean()

        keep = np.argsort(reps, kind="mergesort")
        self._iso = IsotonicRegression(out_of_bounds=self.out_of_bounds).fit(
            reps[keep], shrunk[keep], sample_weight=weights[keep])
        self.base_rate_ = base
        self.n_blocks_  = int(len(vals))
        self.n_fit_     = int(y.size)
        return self

    def predict(self, X):
        import numpy as np

        out = np.asarray(self._iso.predict(np.asarray(X, dtype=float).ravel()), dtype=float)
        return np.clip(out, FIT_EPS, 1.0 - FIT_EPS)

    def transform(self, X):
        return self.predict(X)

    def fit_transform(self, X, y, sample_weight=None):
        return self.fit(X, y, sample_weight=sample_weight).predict(X)


def probability_isotonic(**kwargs) -> SmoothedIsotonic:
    """The calibrator to fit against binary outcomes, everywhere.

    A free function rather than the class directly so the shrinkage can be
    tuned, disabled or replaced in one place if the measurement ever changes.
    """
    kwargs.setdefault("out_of_bounds", "clip")
    return SmoothedIsotonic(**kwargs)
