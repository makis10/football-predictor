"""Cross-league strength for UEFA ties, from ClubElo rather than our own Elo.

WHY THIS EXISTS
---------------
The result model has never been fitted on a single cross-league match. Every CSV
in backend/data/raw is one country's domestic competition, and the only European
file (backend/data/european/CL_*.csv) is read for congestion features alone. So
when a Champions League tie is priced, every feature the model leans on —
rolling form, Poisson strengths, league position — was learned inside closed
domestic pools, and the one feature meant to carry cross-league information,
`elo_diff`, is built by `club_elo()` from a shared 1500 start in leagues that
barely play each other. A club that dominates a small country climbs against
opponents whose ratings never had a reason to fall.

Measured on 296 settled UEFA ties (2026-09-03):

    spearman(our elo_diff, clubelo_diff)          0.247
      both clubs from leagues we fit on           0.527
      at least one from a history-only league     0.118
    disagreement about WHICH side is favourite    40.2%

    picker                                        accuracy
    higher ClubElo + 80 home advantage              60.5%
    always the home side                            50.7%
    our served argmax                               49.3%
    higher OUR elo + 60 home advantage              44.3%

Our own rating is worse than a coin weighted toward the home side. That is the
finding this module answers.

WHAT IT DOES
------------
Fits a multinomial logistic on a single feature, the ClubElo difference, over
every finished UEFA tie we hold, and uses it to replace the model's HOME:AWAY
split — while keeping the model's own P(draw) untouched.

The split matters. On 373 held-out ties (fit on everything before 2026-07-01,
scored on what followed):

    served (production chain)                acc 48.26%   log-loss 1.0590
    logistic on clubelo_diff alone           acc 53.08%   log-loss 0.9955
    served p_draw + ClubElo home:away        acc 53.08%   log-loss 0.9849  ← this

    paired bootstrap 5,000x vs served: accuracy +4.81pp, 95% CI [+0.54, +9.12],
    P(better) = 0.986; log-loss -0.063, CI [-0.102, -0.026], P = 1.000

    per competition:  EL 39.2% -> 55.4%   ECL 49.1% -> 52.2%   CL 55.2% -> 53.7%
    double-chance pick hit rate: 71.3% -> 76.1%

Keeping our p_draw is not politeness. The ClubElo logistic's own draw AUC is
0.399 — worse than random, because a single strength difference cannot express
"these two will cancel out". ClubElo knows who is better; it does not know when
a match is tight. Ours does, marginally (0.5645). Each contributes the half it
is good at.

WHAT IT DOES NOT DO
-------------------
It is not a substitute for training data. The honest fix is a real history of
EL/ECL matches (scripts/import_history_apifootball.py, one request per
league-season); this is the cheap stand-in until that exists. It also touches
only CL/EL/ECL — domestic fixtures are unaffected, since inside one league our
Elo is exactly the feature the model was trained on and is not broken.

Fitting happens at prediction time, in-process: a few hundred rows and one
logistic take milliseconds, and re-fitting on every run means the blend tracks
new results without an artefact anyone has to remember to regenerate.
"""
from __future__ import annotations

import glob
import logging
import os
from typing import Iterable, Optional

import numpy as np

log = logging.getLogger("european_blend")

# The competitions this applies to. Domestic leagues keep the model's own split.
UEFA_LEAGUES = frozenset({"CL", "EL", "ECL"})

# Below this many finished ties the logistic is not worth trusting; fall back to
# leaving the prediction alone. 200 is comfortably above the ~12 parameters'
# worth of freedom in a 1-feature 3-class fit, and we hold ~900.
MIN_FIT_ROWS = 200

# ClubElo points are divided by this before fitting purely to keep the
# coefficients in a sane range for the solver.
_SCALE = 100.0

_EUROPEAN_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "european")


class _EloSplitModel:
    """Multinomial logistic P(H/D/A) from the ClubElo difference alone."""

    def __init__(self, lr, n_fit: int):
        self._lr = lr
        self.n_fit = n_fit

    def probs(self, elo_diff: float) -> tuple[float, float, float]:
        p = self._lr.predict_proba(np.array([[elo_diff / _SCALE]]))[0]
        return float(p[0]), float(p[1]), float(p[2])


def _finished_uefa_rows(db) -> list[tuple[str, str, int]]:
    """(home, away, outcome) for every settled UEFA tie in the database."""
    from sqlalchemy import text

    rows = db.execute(text("""
        SELECT home_team, away_team, result
        FROM matches
        WHERE league IN ('CL', 'EL', 'ECL') AND result IS NOT NULL
    """)).fetchall()
    code = {"H": 0, "D": 1, "A": 2}
    return [(r.home_team, r.away_team, code[r.result])
            for r in rows if r.result in code]


def _finished_csv_rows() -> list[tuple[str, str, int]]:
    """The same, from backend/data/european/*.csv — several seasons of CL that
    predate anything in the database, and the reason the fit has enough rows to
    be worth doing at all."""
    import pandas as pd

    out: list[tuple[str, str, int]] = []
    for path in sorted(glob.glob(os.path.join(_EUROPEAN_DIR, "*.csv"))):
        try:
            df = pd.read_csv(path)
        except Exception as e:                       # noqa: BLE001 — best effort
            log.warning("could not read %s: %s", path, e)
            continue
        if not {"home_team", "away_team", "home_goals", "away_goals"} <= set(df.columns):
            continue
        df = df[df.get("status", "FINISHED").eq("FINISHED")] if "status" in df else df
        df = df.dropna(subset=["home_goals", "away_goals"])
        for r in df.itertuples():
            hg, ag = int(r.home_goals), int(r.away_goals)
            out.append((r.home_team, r.away_team,
                        0 if hg > ag else (1 if hg == ag else 2)))
    return out


def fit_elo_split_model(db=None, strengths: Optional[dict] = None) -> Optional[_EloSplitModel]:
    """Fit the ClubElo→outcome logistic, or return None when it cannot be trusted."""
    from sklearn.linear_model import LogisticRegression

    rows = _finished_csv_rows()
    if db is not None:
        try:
            rows += _finished_uefa_rows(db)
        except Exception as e:                       # noqa: BLE001 — DB is optional
            log.warning("could not read UEFA rows from the database: %s", e)

    if len(rows) < MIN_FIT_ROWS:
        log.info("european blend disabled: only %d finished ties", len(rows))
        return None

    if strengths is None:
        # Direct table only — a club ClubElo does not carry must be DROPPED from
        # the fit, not given european_strength()'s floor. Training the logistic
        # on a pile of identical floor values teaches it that "1309" means
        # something, and every uncovered club then inherits that meaning.
        from backend.app.ml.clubelo_ratings import clubelo_by_our_name
        strengths = clubelo_by_our_name()

    X, y = [], []
    for home, away, outcome in rows:
        h, a = strengths.get(home), strengths.get(away)
        if h is None or a is None:
            continue
        X.append([(h - a) / _SCALE])
        y.append(outcome)

    if len(X) < MIN_FIT_ROWS or len(set(y)) < 3:
        log.info("european blend disabled: %d usable rows, %d classes",
                 len(X), len(set(y)))
        return None

    lr = LogisticRegression(max_iter=2000, C=1.0)
    lr.fit(np.asarray(X), np.asarray(y))
    log.info("european blend fitted on %d finished ties", len(X))
    return _EloSplitModel(lr, len(X))


def apply_elo_split(
    model_probs: tuple[float, float, float],
    home_strength: Optional[float],
    away_strength: Optional[float],
    split_model: Optional[_EloSplitModel],
) -> tuple[float, float, float]:
    """Keep our P(draw); take the home:away ratio from ClubElo.

    Returns `model_probs` unchanged whenever anything needed is missing — no
    ClubElo rating for one of the clubs, no fitted model, or a degenerate split.
    A UEFA tie between two clubs the upstream table does not carry is exactly
    the case where this cannot help, and guessing would be worse than the
    model's own answer.
    """
    p_h, p_d, p_a = (float(x) for x in model_probs)
    if split_model is None or home_strength is None or away_strength is None:
        return p_h, p_d, p_a

    ce_h, _ce_d, ce_a = split_model.probs(home_strength - away_strength)
    denom = ce_h + ce_a
    if denom <= 1e-9:
        return p_h, p_d, p_a

    # P(draw) is ours; the remaining mass is split in ClubElo's ratio.
    rest = max(0.0, 1.0 - p_d)
    new_h = rest * (ce_h / denom)
    new_a = rest * (ce_a / denom)
    total = new_h + p_d + new_a
    if total <= 1e-9:
        return p_h, p_d, p_a
    return new_h / total, p_d / total, new_a / total


def is_uefa(league: Optional[str]) -> bool:
    return league in UEFA_LEAGUES
