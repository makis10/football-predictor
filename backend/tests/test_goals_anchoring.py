"""Over/Under and BTTS were the only headline probabilities with no market
content, and the only two that measured at chance.

Measured 2026-09-07 on every settled row carrying both our probability and a
two-sided price:

    Over 2.5   our AUC 0.5222 [0.4505, 0.5955]   de-vigged market 0.5851
    BTTS       our AUC 0.5020 [0.4547, 0.5502]   de-vigged market 0.5607

Sweeping the blend weight found no interior optimum in either market — log-loss
falls monotonically to w=1.00 — because a blend of one informative signal with an
uninformative one is monotone in the informative one's weight. w=0.85 is the same
presentation trade the 1x2 weight records, and deliberately the SAME constant so
the codebase has one anchor weight rather than three that drift.

The dangerous part is not the blend, it is what reads it afterwards. These tests
pin that separation.
"""
from __future__ import annotations

import pytest

from backend.app.ml.predict import (
    MARKET_ANCHOR_WEIGHT,
    anchor_binary_to_market,
    finalise_probabilities,
)


def _devig(yes: float, no: float) -> float:
    iy, ino = 1.0 / yes, 1.0 / no
    return iy / (iy + ino)


def test_it_blends_toward_the_devigged_line_not_the_raw_price():
    """1/odds still carries the bookmaker's margin. Anchoring to it would pull
    every probability up toward a number that sums past 1 — the same mistake that
    made the ticket legs look like the market was overconfident."""
    yes, no = 1.80, 2.00
    fair = _devig(yes, no)
    assert 1.0 / yes > fair, "fixture is wrong: the raw price should exceed fair"

    out = anchor_binary_to_market(0.50, yes, no)
    expected = (1.0 - MARKET_ANCHOR_WEIGHT) * 0.50 + MARKET_ANCHOR_WEIGHT * fair
    assert out == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("yes,no", [
    (None, 2.0), (1.8, None), (None, None),   # no price on one or both sides
    (1.0, 2.0), (1.8, 0.9),                   # impossible decimal odds
    ("x", 2.0),                               # junk from a feed
])
def test_it_returns_our_own_number_when_there_is_no_usable_price(yes, no):
    """Most of a thin midweek card has no two-sided goals line. Declining is the
    honest fallback and it is also what the 1x2 anchor has always done."""
    assert anchor_binary_to_market(0.61, yes, no) == 0.61


def test_the_weight_is_the_one_1x2_uses():
    """Three anchor weights would drift apart within a month. If a future
    measurement moves one of them, this test should be the thing that forces the
    decision to be explicit."""
    assert MARKET_ANCHOR_WEIGHT == 0.85
    fair = _devig(1.75, 2.10)
    assert anchor_binary_to_market(0.30, 1.75, 2.10) == pytest.approx(
        0.15 * 0.30 + 0.85 * fair, abs=1e-9)


def test_anchoring_moves_a_wild_number_a_long_way_toward_the_price():
    """The whole point: our O/U had no discrimination, so a confident model
    number is mostly noise and the price should dominate the served answer."""
    out = anchor_binary_to_market(0.98, 1.90, 1.90)
    assert 0.50 < out < 0.62


def test_finalise_leaves_the_goals_markets_alone_without_prices():
    a = finalise_probabilities(home=0.45, draw=0.27, away=0.28, over=0.55, btts=0.56)
    b = finalise_probabilities(home=0.45, draw=0.27, away=0.28, over=0.55, btts=0.56,
                               market_odds=(2.2, 3.3, 3.4))
    assert a[3] == pytest.approx(b[3], abs=1e-9), "O/U moved with only a 1x2 price present"
    assert a[4] == pytest.approx(b[4], abs=1e-9), "BTTS moved with only a 1x2 price present"


def test_each_market_is_anchored_by_its_own_price_only():
    """A fixture priced on 1x2 but not on totals must get an anchored result and
    an unanchored O/U — not one price standing in for another."""
    base = dict(home=0.45, draw=0.27, away=0.28, over=0.72, btts=0.56)
    only_ou = finalise_probabilities(**base, over_odds=(1.9, 1.9))
    neither = finalise_probabilities(**base)
    assert only_ou[3] != pytest.approx(neither[3], abs=1e-6)
    assert only_ou[0] == pytest.approx(neither[0], abs=1e-9)


def test_the_value_gate_never_reads_an_anchored_goals_probability():
    """The failure this could have shipped: odds_analysis_service computes GG/NG
    expected value as `prob * that same book's odds - 1`. Hand it an anchored
    probability and every edge collapses to roughly minus the margin, so the gate
    silently stops surfacing goals bets — an accuracy 'improvement' that removes
    a feature. raw_btts_prob (migration 0034) exists for this line alone.
    """
    import ast
    import pathlib

    router = pathlib.Path(__file__).resolve().parents[1] / "app" / "routers" / "predictions.py"
    tree = ast.parse(router.read_text())

    raw_names = {"raw_home_prob", "raw_draw_prob", "raw_away_prob",
                 "raw_over_prob", "raw_btts_prob"}
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value in raw_names:
            found.add(node.value)
    assert raw_names <= found, (
        f"the EV gate does not read every unanchored column; missing {raw_names - found}")


def test_the_stored_unanchored_columns_are_calibrated_probabilities():
    """`raw_` means unanchored, not uncalibrated.

    Until 2026-09-07 these columns held the bare XGBoost outputs, which are not
    probabilities in any usable sense — the live isotonic mapped a raw 0.7832 to
    1.0. The batch ledger fed the value gate `pre_anchor` while the API's gate
    read these columns, so the same gate computed expected value from two
    different quantities depending on which path answered.
    """
    import pathlib
    import re

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "compute_predictions.py").read_text()
    block = re.search(r'"raw_home_prob":\s*([^,\n]+)', src)
    assert block, "the insert no longer names raw_home_prob"
    assert "pre_anchor" in block.group(1), (
        f"raw_home_prob is stored as {block.group(1)!r}; it must be the coherent, "
        f"calibrated, pre-anchor probability the EV gate is documented to read")
    assert re.search(r'"raw_over_prob":\s*round\(pre_anchor\[3\]', src)
    assert re.search(r'"raw_btts_prob":', src), "raw_btts_prob is never stored"


# ── a price that is not a number ──────────────────────────────────────────────

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_price_is_declined_not_propagated(bad):
    """NaN fails every ordering test, so `o <= 1.0` waves it straight through.

    Probed 2026-09-08: anchor_binary_to_market(0.61, nan, 2.0) returned nan,
    which would have been stored and rendered as "NaN%". The guard has to ask
    whether the number IS a number, not whether it is small.
    """
    from backend.app.ml.predict import anchor_to_market

    assert anchor_binary_to_market(0.61, bad, 2.0) == 0.61
    assert anchor_binary_to_market(0.61, 1.9, bad) == 0.61
    assert anchor_to_market((0.4, 0.3, 0.3), (bad, 3.5, 4.0)) == (0.4, 0.3, 0.3)
    assert anchor_to_market((0.4, 0.3, 0.3), (1.9, bad, 4.0)) == (0.4, 0.3, 0.3)


def test_the_batch_refuses_to_store_a_probability_that_is_not_a_number():
    """Both anchors now decline on a non-finite input, but a NaN can still
    originate upstream — one NaN feature through the calibrators is enough. There
    is no honest fallback for it, so the fixture must be skipped and counted with
    the other ML failures rather than written to the table."""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "compute_predictions.py").read_text()
    guard = src[src.index("btts_prediction = \"GG\"") - 1200:src.index("btts_prediction = \"GG\"")]
    assert "isfinite" in guard, (
        "nothing between the anchoring and the INSERT checks that the served "
        "probabilities are numbers")
    assert "raise" in guard, (
        "a non-finite probability must abort the fixture, not be stored")


# ── a book that is not a book ─────────────────────────────────────────────────

def test_a_book_summing_below_one_is_refused():
    """De-vigging normalises by the sum of the implied probabilities. A sum BELOW
    1 does not remove a margin — it inflates every price into a more confident
    number than the bookmaker offered.

    No bookmaker prices a negative margin, so a sum under 1 means the prices are
    not from one snapshot: a stale side, a mismatched pair, a feed that filled
    one leg from a different market. One of the 605 stored Over/Under pairs sums
    to 0.8402, and anchoring to it would have pulled the served probability
    toward a number nobody quoted.
    """
    from backend.app.ml.predict import anchor_to_market
    from backend.app.ml.tickets import _devig

    assert (1 / 2.50 + 1 / 2.60) < 1.0, "fixture is wrong: this pair is not implausible"
    assert anchor_binary_to_market(0.61, 2.50, 2.60) == 0.61
    assert _devig(1 / 2.50, (2.50, 2.60)) is None
    assert anchor_to_market((0.4, 0.3, 0.3), (5.0, 5.0, 5.0)) == (0.4, 0.3, 0.3)


def test_a_real_book_is_still_accepted():
    """The guard must not start rejecting ordinary prices. The widest real book
    on record here is 1.1685 on a 1x2; the mean is 1.067."""
    from backend.app.ml.predict import anchor_to_market
    from backend.app.ml.tickets import _devig

    assert anchor_binary_to_market(0.61, 1.90, 1.95) != 0.61
    assert _devig(1 / 1.70, (1.70, 3.80, 5.50)) is not None
    assert anchor_to_market((0.4, 0.3, 0.3), (1.70, 3.80, 5.50)) != (0.4, 0.3, 0.3)
    # …including one at the widest margin actually observed.
    wide = (1.55, 4.60, 6.50)
    assert 1.0 <= sum(1 / o for o in wide) <= 1.20
    assert anchor_to_market((0.4, 0.3, 0.3), wide) != (0.4, 0.3, 0.3)
