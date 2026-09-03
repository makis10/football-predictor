"""The bookmaker baseline must be the bookmaker.

`train._result_scoring_report` prints the one line that answers "do we have an
edge?", and for its whole life it printed a win we did not have:

    [Baseline] de-vig bookmaker log-loss=1.0549 vs model 1.0246 (coverage 99%)

The 99% was fiction. `build_features` replaces a missing Pinnacle line with our
own Poisson probabilities — correct in June 2026, when the market columns were
the model's two most important features and a NaN there broke the prediction.
When market features were removed from every model on 2026-06-17 the fallback
stopped affecting the model, which is exactly why nobody touched it: it became
invisible. It kept feeding the one consumer left, the baseline.

The guard that was supposed to catch this, `market_was_imputed`, was written
into `_impute_optional` — one stage too late, downstream of the fallback, where
there is nothing left to detect. It reported 50 imputed rows out of 7,427; the
real number was 4,443. On the 40% of rows that do carry a real line the model
loses to Pinnacle by 0.021 log-loss.

These tests pin both halves: the flag is recorded before the fallback, and the
report refuses to invent a baseline when the flag is absent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.ml.features import FEATURE_COLS, build_features


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    """Two clubs, alternating home and away, with Pinnacle odds on half the rows.

    Enough rows that the Poisson state passes MIN_SEASON_MATCHES and the
    fallback actually fires on the odds-less rows — which is the whole point.
    """
    rows = []
    for i in range(40):
        has_odds = i % 2 == 0
        rows.append({
            "Date": pd.Timestamp("2019-08-01") + pd.Timedelta(days=7 * i),
            "home_team": "Alpha FC" if i % 2 == 0 else "Beta FC",
            "away_team": "Beta FC" if i % 2 == 0 else "Alpha FC",
            "home_goals": (i % 3), "away_goals": ((i + 1) % 3),
            "League": "EPL",
            "PSH": 2.10 if has_odds else np.nan,
            "PSD": 3.40 if has_odds else np.nan,
            "PSA": 3.60 if has_odds else np.nan,
            "HST": 5, "AST": 4, "HS": 12, "AS": 10,
            "Referee": None, "HY": 1, "AY": 2, "HR": 0, "AR": 0,
        })
    raw = pd.DataFrame(rows)
    # _normalise expects football-data.co.uk column names; build_features expects
    # the normalised ones, so mirror what load_raw_csvs does.
    from backend.app.ml.features import _normalise
    return build_features(_normalise(raw))


def test_market_is_real_marks_the_rows_that_actually_had_a_price(frame):
    """Half the fixture rows carry Pinnacle odds; the flag must say exactly that."""
    assert "market_is_real" in frame.columns, (
        "build_features no longer records market_is_real — the bookmaker "
        "baseline in train.py has no way to tell a real line from a Poisson fill"
    )
    real = frame["market_is_real"].astype(float)
    assert set(np.unique(real)) <= {0.0, 1.0}
    # Exactly the rows we gave odds to, and no others.
    expected = frame["psh"].notna().astype(float)
    assert (real == expected).all(), (
        f"market_is_real disagrees with the presence of a Pinnacle price on "
        f"{int((real != expected).sum())} row(s)"
    )
    assert 0 < real.sum() < len(frame), "fixture is degenerate — no contrast to test"


def test_the_poisson_fallback_still_fills_the_market_columns(frame):
    """The fallback itself is deliberate and must stay: the flag exists so the
    baseline can see through it, not to remove it."""
    filled = frame.loc[frame["market_is_real"] < 0.5, "market_home_prob"]
    assert filled.notna().any(), (
        "no odds-less row got a Poisson fill — if the fallback was removed, "
        "market_is_real is pointless and this test should be deleted with it"
    )


def test_market_is_real_is_not_a_model_feature(frame):
    """It describes the row's provenance, not the match. Feeding it to a model
    would let the model learn 'fixtures the bookmaker priced behave differently',
    which is a market feature by the back door — the exact thing the 2026-06-17
    market-independence cutoff removed."""
    for col in ("market_is_real", "market_over_is_real"):
        assert col not in FEATURE_COLS, f"{col} leaked into FEATURE_COLS"


def test_the_baseline_reports_nothing_when_it_cannot_tell(monkeypatch):
    """A frame with no market_is_real column must produce NO bookmaker baseline.

    Falling back to 'assume every row is real' is what made the number
    flattering. Silence is the correct answer when the provenance is unknown.
    """
    from backend.app.ml.train import _result_scoring_report

    n = 400
    rng = np.random.default_rng(0)
    y = pd.Series(rng.integers(0, 3, n))
    probs = np.full((n, 3), 1 / 3)
    test = pd.DataFrame({
        "market_home_prob": np.full(n, 0.45),
        "market_draw_prob": np.full(n, 0.27),
        "market_away_prob": np.full(n, 0.28),
    })   # note: no market_was_imputed column

    out = _result_scoring_report(probs, y, test)
    assert "bookmaker_log_loss" not in out, (
        "the report invented a bookmaker baseline from rows whose provenance "
        "it does not know"
    )


def test_the_baseline_uses_only_rows_with_a_real_line():
    """With the flag present, coverage must equal the real-line share."""
    from backend.app.ml.train import _result_scoring_report

    n = 400
    rng = np.random.default_rng(1)
    y = pd.Series(rng.integers(0, 3, n))
    probs = np.full((n, 3), 1 / 3)
    imputed = np.arange(n) >= 150            # 150 real, 250 imputed
    test = pd.DataFrame({
        "market_home_prob": np.full(n, 0.45),
        "market_draw_prob": np.full(n, 0.27),
        "market_away_prob": np.full(n, 0.28),
        "market_was_imputed": imputed,
    })

    out = _result_scoring_report(probs, y, test)
    assert "bookmaker_log_loss" in out
    assert out["bookmaker_coverage"] == pytest.approx(150 / n, abs=1e-3), (
        f"baseline coverage {out['bookmaker_coverage']} counts imputed rows"
    )
