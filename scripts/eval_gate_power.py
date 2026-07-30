"""
Can the value gate's ROI be improved — and can we even TELL?

This exists because of a specific trap. Bucketing settled picks by claimed EV
showed the low-EV bucket at +13% fair ROI and the mid bucket at −45%, which
invites the obvious "fix": keep the buckets that did well. That is selection on
the realised outcome — strictly worse than the original mistake (selection on
the model's disagreement with the market), and it will always produce a pretty
backtest.

So this script does not tune anything. It answers the prior question: given the
settled sample we actually have, is ANY bucket-level difference distinguishable
from chance, and how much data would it take? It reports:

  1. Regime split. Predictions served before MARKET_INDEPENDENT_CUTOFF were
     market-anchored — the served probabilities had market information blended
     in, so their model-vs-market gap means something different. Those picks
     cannot be pooled with current ones, however much it hurts the sample size.
  2. Bootstrap CIs on fair-odds ROI, overall and per EV bucket. A point ROI
     without an interval is what makes noise look like signal.
  3. A permutation test: resample same-size subsets from the pick pool and see
     how often chance alone produces a bucket as good as the best observed one.
  4. Power: the settled-bet count needed to detect a given true edge, and how
     long that takes at the observed pick rate.

Read (3) and (4) before believing (2).

Usage:
  docker compose exec -T backend python scripts/eval_gate_power.py
  docker compose exec -T backend python scripts/eval_gate_power.py --edge 0.03
"""
from __future__ import annotations

import argparse
import math
import random
import re
import statistics
from collections import Counter
from datetime import date

# Predictions served before this date were anchored to the market (see the
# 2026-06-17 market-independence refactor) — a different estimator.
MARKET_INDEPENDENT_CUTOFF = date(2026, 6, 17)

# Under-2.5 odds are not stored, so the O/U market is de-vigged with an assumed
# two-way overround. Mirrors stats.GOALS_OVERROUND — keep them in step.
GOALS_OVERROUND = 1.04

BUCKETS = [("0-10%", 0.0, 0.10), ("10-20%", 0.10, 0.20),
           ("20-40%", 0.20, 0.40), ("40%+", 0.40, 9.99)]

BOOTSTRAP_N = 20_000
PERMUTATION_N = 20_000


def _odds(row) -> float | None:
    m = re.search(r"@\s*([0-9.]+)", row.get("suggested_market") or "")
    return float(m.group(1)) if m else None


def _fair_odds(row) -> float | None:
    """Vig-free odds for the suggested leg, or None when we can't de-vig it."""
    o = _odds(row)
    if not o:
        return None
    sm = (row.get("suggested_market") or "").lower()
    if any(k in sm for k in ("home win", "away win", "draw")):
        h, d, a = row["bm_home_odds"], row["bm_draw_odds"], row["bm_away_odds"]
        if None in (h, d, a):
            return None
        return o * (1 / h + 1 / d + 1 / a)          # exact, all three legs stored
    if "over" in sm or "under" in sm:
        return o * GOALS_OVERROUND                   # assumed overround
    if sm.startswith("gg") or sm.startswith("ng"):
        gg, ng = row["bm_btts_yes_odds"], row["bm_btts_no_odds"]
        if None in (gg, ng):
            return None
        return o * (1 / gg + 1 / ng)                 # exact when both stored
    return None


def _roi(sample: list[tuple[float, bool]]) -> float | None:
    """ROI per unit staked for [(fair_odds, won), …]."""
    if not sample:
        return None
    return sum(o if w else 0.0 for o, w in sample) / len(sample) - 1.0


def _bootstrap_ci(sample, n=BOOTSTRAP_N, conf=0.95):
    """Percentile bootstrap CI for ROI — no normality assumed (returns are
    heavily skewed: mostly −1, occasionally +odds)."""
    if len(sample) < 2:
        return None, None
    rois = []
    k = len(sample)
    for _ in range(n):
        rois.append(_roi([sample[random.randrange(k)] for _ in range(k)]))
    rois.sort()
    lo = rois[int((1 - conf) / 2 * n)]
    hi = rois[int((1 + conf) / 2 * n) - 1]
    return lo, hi


def _required_n(edge: float, odds: float, win_prob: float) -> int:
    """Settled bets needed for `edge` to sit ~2 SE above zero.

    Per-bet return R = odds if win else 0, so Var(R) = p·odds²·(1−p) and
    SE(ROI) = odds·sqrt(p(1−p)/n). Solve 2·SE = edge.
    """
    if edge <= 0:
        return 0
    sd = odds * math.sqrt(max(win_prob * (1 - win_prob), 1e-9))
    return int(math.ceil((2 * sd / edge) ** 2))


def _selection_rules(rows):
    """Pre-specified selection rules, compared on identical matches.

    Every rule here has ZERO fitted parameters — that is the point. The moment a
    threshold is chosen by looking at the results, the comparison stops being a
    test and becomes the curve-fit this whole script exists to prevent.

    `market favourite` is the control that matters: it uses no model output at
    all. Any rule that cannot beat it is not earning its keep.

    Yields (name, [(odds, fair_odds, won), …]).
    """
    legs = {"H": ("bm_home_odds", "home_win_prob"),
            "D": ("bm_draw_odds", "draw_prob"),
            "A": ("bm_away_odds", "away_win_prob")}

    usable = [r for r in rows
              if r["result"] in ("H", "D", "A")
              and None not in (r["bm_home_odds"], r["bm_draw_odds"], r["bm_away_odds"])
              and None not in (r["home_win_prob"], r["draw_prob"], r["away_win_prob"])]

    def bet(r, leg):
        o = r[legs[leg][0]]
        overround = (1 / r["bm_home_odds"] + 1 / r["bm_draw_odds"] + 1 / r["bm_away_odds"])
        return (o, o * overround, r["result"] == leg)

    def model_argmax(r):
        return max(legs, key=lambda k: r[legs[k][1]])

    def market_fav(r):
        return min(legs, key=lambda k: r[legs[k][0]])   # shortest price

    out = []

    # what the site suggests today — only where the gate actually fired
    from backend.app.routers.stats import _top_pick_correct
    gate = []
    for r in rows:
        if not r.get("suggested_market") or _top_pick_correct(r) is None:
            continue
        fo, o = _fair_odds(r), _odds(r)
        if fo and o:
            gate.append((o, fo, bool(_top_pick_correct(r))))
    out.append(("gate (EV-selected, current)", gate))

    out.append(("model argmax (most likely)",
                [bet(r, model_argmax(r)) for r in usable]))
    out.append(("model argmax, p>=0.50",
                [bet(r, model_argmax(r)) for r in usable
                 if max(r[legs[k][1]] for k in legs) >= 0.50]))
    out.append(("market favourite (NO model)",
                [bet(r, market_fav(r)) for r in usable]))
    out.append(("always home (naive)",
                [bet(r, "H") for r in usable]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Is the gate's ROI difference real?")
    ap.add_argument("--edge", type=float, default=0.05,
                    help="True ROI edge to size for (default 0.05 = 5%%)")
    ap.add_argument("--seed", type=int, default=20260730)
    args = ap.parse_args()
    random.seed(args.seed)   # reproducible bootstrap/permutation

    from backend.app.routers.stats import _load_rows, _top_pick_correct

    rows = _load_rows()
    picks = [r for r in rows
             if r.get("suggested_market") and _top_pick_correct(r) is not None]
    if not picks:
        print("No settled picks yet — nothing to evaluate.")
        return

    dates = [r["match_date"] for r in picks]
    span_days = (max(dates) - min(dates)).days or 1

    print("=" * 74)
    print("1. SAMPLE AND REGIME")
    print("=" * 74)
    print(f"settled picks total      : {len(picks)}  "
          f"({min(dates)} → {max(dates)}, {span_days} days)")

    current = [r for r in picks if r["match_date"] >= MARKET_INDEPENDENT_CUTOFF]
    legacy = [r for r in picks if r["match_date"] < MARKET_INDEPENDENT_CUTOFF]
    print(f"market-anchored (legacy) : {len(legacy)}  — DIFFERENT estimator, not poolable")
    print(f"current pure-model regime: {len(current)}  ← the only usable sample")
    if current:
        comp = Counter(r["league"] for r in current).most_common(6)
        print(f"  composition            : {', '.join(f'{k} {v}' for k, v in comp)}")
        cur_dates = [r["match_date"] for r in current]
        cur_span = (max(cur_dates) - min(cur_dates)).days or 1
        rate = len(current) / cur_span
        print(f"  accrual rate           : {rate:.2f} settled picks/day")
    else:
        rate = 0.0

    def prep(rs):
        out = []
        for r in rs:
            fo = _fair_odds(r)
            if fo:
                out.append((fo, bool(_top_pick_correct(r))))
        return out

    for label, rs in (("CURRENT REGIME", current), ("ALL PICKS (incl. legacy)", picks)):
        sample = prep(rs)
        print()
        print("=" * 74)
        print(f"2. FAIR-ODDS ROI WITH UNCERTAINTY — {label}")
        print("=" * 74)
        if len(sample) < 2:
            print(f"  n={len(sample)} de-viggable — too few to say anything.")
            continue
        roi = _roi(sample)
        lo, hi = _bootstrap_ci(sample)
        print(f"  overall  n={len(sample):4}  fair ROI {roi:+7.1%}   95% CI [{lo:+.1%}, {hi:+.1%}]")
        print(f"  {'bucket':8} {'n':>4} {'fair ROI':>10}   95% CI")
        for name, lo_ev, hi_ev in BUCKETS:
            bs = prep([r for r in rs
                       if r.get("ev_score") is not None
                       and lo_ev <= r["ev_score"] < hi_ev])
            if len(bs) < 2:
                print(f"  {name:8} {len(bs):4}        —      (too few)")
                continue
            b_roi = _roi(bs)
            b_lo, b_hi = _bootstrap_ci(bs)
            width = (b_hi - b_lo) * 100
            # A bucket with no wins (or no losses) resamples to the same value
            # every time, so the bootstrap reports a zero-width interval. That
            # is degeneracy, not precision — say so, or it reads as certainty.
            wins = sum(1 for _, w in bs if w)
            flag = ""
            if wins in (0, len(bs)):
                flag = f"  ⚠ degenerate ({wins}/{len(bs)} won) — interval is meaningless"
            print(f"  {name:8} {len(bs):4} {b_roi:+9.1%}   [{b_lo:+.1%}, {b_hi:+.1%}]"
                  f"  (width {width:.0f}pp){flag}")

    # ── 2b. selection rules head to head ──────────────────────────────────────
    print()
    print("=" * 74)
    print("2b. WOULD A DIFFERENT SELECTION RULE DO BETTER?")
    print("=" * 74)
    print("  Fair ROI strips the vig, so it asks: does this rule beat the MARKET'S")
    print("  own probabilities? ~0% = exactly as good as the market (no edge, no")
    print("  anti-edge). Offered ROI is what a real bettor would actually collect.")
    print()
    print(f"  {'rule':30} {'n':>4} {'hit':>6} {'odds':>5} {'ROI offered':>12} {'ROI fair':>9}   95% CI (fair)")
    for name, sample in _selection_rules(rows):
        if len(sample) < 2:
            print(f"  {name:30} {len(sample):4}   — too few")
            continue
        hit = sum(1 for *_, w in sample if w) / len(sample)
        mo = statistics.mean(o for o, _, _ in sample)
        roi_off = sum(o if w else 0 for o, _, w in sample) / len(sample) - 1
        pairs = [(fo, w) for _, fo, w in sample]
        roi_fair = _roi(pairs)
        lo, hi = _bootstrap_ci(pairs)
        print(f"  {name:30} {len(sample):4} {hit:5.1%} {mo:5.2f} {roi_off:+11.1%} "
              f"{roi_fair:+8.1%}   [{lo:+.1%}, {hi:+.1%}]")

    # ── 3. permutation test ───────────────────────────────────────────────────
    print()
    print("=" * 74)
    print("3. COULD THE BEST BUCKET BE CHANCE?")
    print("=" * 74)
    pool = prep(picks)
    bucket_samples = []
    for name, lo_ev, hi_ev in BUCKETS:
        bs = prep([r for r in picks if r.get("ev_score") is not None
                   and lo_ev <= r["ev_score"] < hi_ev])
        if len(bs) >= 2:
            bucket_samples.append((name, bs))
    if not bucket_samples or len(pool) < 4:
        print("  not enough data.")
    else:
        best_name, best = max(bucket_samples, key=lambda t: _roi(t[1]))
        best_roi, k = _roi(best), len(best)
        # Null: the EV label carries no information, so a same-size random draw
        # from the pool is an equally valid "bucket".
        hits = 0
        for _ in range(PERMUTATION_N):
            draw = [pool[random.randrange(len(pool))] for _ in range(k)]
            if _roi(draw) >= best_roi:
                hits += 1
        p = hits / PERMUTATION_N
        print(f"  best observed bucket   : {best_name}  n={k}  fair ROI {best_roi:+.1%}")
        print(f"  random same-size draws matching or beating it: {p:.1%}")
        print(f"  → p ≈ {p:.3f} for ONE bucket; {len(bucket_samples)} were compared, so the")
        print(f"    multiplicity-adjusted p is ≈ {min(1.0, p * len(bucket_samples)):.3f}")
        verdict = ("indistinguishable from chance"
                   if p * len(bucket_samples) > 0.05 else
                   "survives a naive multiplicity correction — still needs out-of-sample")
        print(f"  VERDICT: {verdict}")

    # ── 4. power ──────────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    print("4. HOW MUCH DATA WOULD SETTLE IT?")
    print("=" * 74)
    if pool:
        mean_odds = statistics.mean(o for o, _ in pool)
        win_rate = statistics.mean(1.0 if w else 0.0 for _, w in pool)
        implied = 1 / mean_odds
        print(f"  observed mean fair odds  : {mean_odds:.2f}  (implies {implied:.1%} win rate)")
        print(f"  observed win rate        : {win_rate:.1%}")
        for edge in (args.edge, 0.03, 0.10):
            need = _required_n(edge, mean_odds, implied)
            years = need / rate / 365 if rate else float("inf")
            when = f"{years:.1f} years at the current rate" if rate else "never at the current rate"
            print(f"  to detect a {edge:+.0%} true edge : {need:,} settled bets  →  {when}")
        se_now = mean_odds * math.sqrt(implied * (1 - implied) / max(len(pool), 1))
        print(f"  with today's n={len(pool)}      : ROI standard error is ±{se_now:.1%}, "
              f"so the 95% window is ±{2 * se_now:.1%}")


if __name__ == "__main__":
    main()
