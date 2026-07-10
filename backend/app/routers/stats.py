"""
GET /stats — Accuracy tracking and model monitoring endpoint.

Computes accuracy metrics from the matches + predictions tables for all
completed matches that have a cached prediction.

Performance:
  - One DB round-trip: JOIN matches + predictions WHERE result IS NOT NULL
  - All aggregations done in Python (fast for O(10k) rows)
  - 6-hour in-process TTL cache (same pattern as injuries cache)

Cache invalidation:
  - Results are scraped nightly; a 6h TTL is precise enough for a dashboard.
  - Cache is cleared on first request if it's stale (no background thread needed).
"""
from __future__ import annotations

import math
import time as _time
from datetime import datetime, date, timedelta, timezone
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, Query

from backend.app.routers.admin import _require_admin_key
from sqlalchemy import select, true as sql_true

from backend.app.cache import CACHE_MISS, cache_delete_pattern, cache_get, cache_set
from backend.app.database import SessionLocal
from backend.app.models.match import Match
from backend.app.models.national_prediction import NationalPrediction
from backend.app.models.prediction import Prediction
from backend.app.schemas.stats import (
    AccuracySlice,
    BTTSStats,
    CalibrationBucket,
    CLVStats,
    ConfidenceBreakdown,
    DrawStats,
    EVDataPoint,
    InjuryAdjustmentStats,
    LeagueBreakdown,
    MethodologyInfo,
    RegimeSlice,
    ModelVersionStats,
    PredictedOutcomeBreakdown,
    ResultCalibration,
    ROIStats,
    RollingAccuracy,
    StatsResponse,
    TopPicksStats,
)

router = APIRouter(prefix="/stats", tags=["stats"])

# ── Redis TTL ─────────────────────────────────────────────────────────────────
_TTL_SECONDS = 6 * 3600   # 6 hours


def _load_rows(league: Optional[str] = None) -> list[dict]:
    """
    Load all completed matches that have a prediction.
    Returns a list of plain dicts — one per row — for fast Python processing.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            select(
                Match.id,
                Match.league,
                Match.match_date,
                Match.result,
                Match.home_goals,
                Match.away_goals,
                Prediction.home_win_prob,
                Prediction.draw_prob,
                Prediction.away_win_prob,
                Prediction.over_2_5_prob,
                Prediction.goals_prediction,
                Prediction.confidence,
                Prediction.model_version,
                Prediction.bm_home_odds,
                Prediction.bm_draw_odds,
                Prediction.bm_away_odds,
                Prediction.bm_over_odds,
                Prediction.bm_btts_yes_odds,
                Prediction.bm_btts_no_odds,
                Prediction.btts_prob,
                Prediction.btts_prediction,
                Prediction.poisson_lambda_home,
                Prediction.poisson_lambda_away,
                Prediction.suggested_market,
                Prediction.ev_score,
                Prediction.adj_home_win_prob,
                Prediction.adj_draw_prob,
                Prediction.adj_away_win_prob,
                Prediction.adj_over_2_5_prob,
            )
            .join(Prediction, Prediction.match_id == Match.id)
            .where(Match.result.isnot(None))
            .where(Match.league == league if league else sql_true())
            .order_by(Match.match_date)
        ).mappings().all()
        out = [dict(r) for r in rows]

        # ── National-team predictions (separate table, league="International") ─
        # Without this, rolling windows look empty whenever clubs are off-season
        # even though internationals were predicted and settled (e.g. pre-WC
        # friendlies week). Rows are mapped onto the same dict shape.
        if league is None or league == "International":
            # Only LIVE national predictions (made pre-match since the national
            # pipeline launched). The 2024+ backfilled replay rows would flood
            # all-time stats with ~2.4k matches that were never predicted live;
            # they remain visible on /national Results.
            NATIONAL_STATS_SINCE = "2026-06-01"
            nat = db.execute(
                select(NationalPrediction)
                .where(NationalPrediction.actual_result.isnot(None))
                .where(NationalPrediction.match_date >= NATIONAL_STATS_SINCE)
                .order_by(NationalPrediction.match_date)
            ).scalars().all()
            for p in nat:
                out.append({
                    "id":            p.id,
                    "is_national":   True,   # guards match_id-based joins (CLV)
                    "league":        "International",
                    "match_date":    date.fromisoformat(p.match_date),
                    "result":        p.actual_result,
                    "home_goals":    p.actual_home_goals,
                    "away_goals":    p.actual_away_goals,
                    "home_win_prob": p.home_win_prob,
                    "draw_prob":     p.draw_prob,
                    "away_win_prob": p.away_win_prob,
                    "over_2_5_prob": p.over_2_5_prob,
                    "goals_prediction": "OVER" if p.over_2_5_prob >= 0.5 else "UNDER",
                    "confidence":    (p.confidence or "low").lower(),
                    "model_version": "national",
                    "bm_home_odds":  p.bm_home_odds,
                    "bm_draw_odds":  p.bm_draw_odds,
                    "bm_away_odds":  p.bm_away_odds,
                    "bm_over_odds":  p.bm_over_odds,
                    "bm_btts_yes_odds": p.bm_btts_yes_odds,
                    "btts_prob":     p.btts_prob,
                    "btts_prediction": None,
                    "poisson_lambda_home": None,
                    "poisson_lambda_away": None,
                    "suggested_market": p.suggested_market,
                    "ev_score":      p.ev_score,
                })
            out.sort(key=lambda r: r["match_date"])
        return out
    finally:
        db.close()


# ── Metric helpers ────────────────────────────────────────────────────────────

def _predicted_result(r: dict) -> str:
    """Home/Draw/Away prediction based on which prob is highest."""
    probs = {
        "H": r["home_win_prob"],
        "D": r["draw_prob"],
        "A": r["away_win_prob"],
    }
    return max(probs, key=probs.__getitem__)


# suggested_market name → odds_history column with that market's closing odds.
# Under 2.5 / GG / NG have no odds_history column → no CLV for those.
_CLV_COLUMN = {
    "Home Win": "home_odds",
    "Draw":     "draw_odds",
    "Away Win": "away_odds",
    "Over 2.5": "over_odds",
}


def _compute_clv(rows: list[dict]) -> "Optional[CLVStats]":
    """
    Closing-line value of the suggested bets.

    CLV% = (odds we got at suggestion time / closing odds − 1) × 100.
    Closing odds = the last odds_history snapshot for the match (polling stops
    once the match kicks off, so the latest snapshot ≈ the closing line).
    """
    candidates: list[tuple[int, str, float]] = []   # (match_id, column, bet_odds)

    # Preferred source: the value_bets ticket ledger — immutable odds captured
    # the FIRST time each suggestion appeared (opening-line attack), so CLV
    # measures the soft early price, not whatever a later recompute stored.
    from backend.app.models.value_bet import ValueBet
    db_t = SessionLocal()
    try:
        tickets = db_t.execute(
            select(ValueBet).where(ValueBet.source == "club")
        ).scalars().all()
    finally:
        db_t.close()
    for t in tickets:
        col = _CLV_COLUMN.get(t.market)
        if col and t.match_id and t.odds and t.odds > 1.0:
            candidates.append((t.match_id, col, t.odds))

    # Fallback: legacy suggestions that predate the ledger (parsed from the
    # prediction row). Skip matches already covered by a ticket.
    covered = {mid for mid, _, _ in candidates}
    for r in rows:
        # National rows carry NationalPrediction ids, not club match ids —
        # they have no odds_history and would collide with club match_ids.
        if r.get("is_national") or r["id"] in covered:
            continue
        sm = r.get("suggested_market")
        if not sm or " @ " not in sm:
            continue
        market_name, odds_str = sm.rsplit(" @ ", 1)
        col = _CLV_COLUMN.get(market_name)
        if not col:
            continue
        try:
            bet_odds = float(odds_str)
        except ValueError:
            continue
        if bet_odds > 1.0:
            candidates.append((r["id"], col, bet_odds))

    if not candidates:
        return None

    from backend.app.models.odds_history import OddsHistory

    match_ids = list({mid for mid, _, _ in candidates})
    db = SessionLocal()
    try:
        snaps = db.execute(
            select(OddsHistory)
            .where(OddsHistory.match_id.in_(match_ids))
            .order_by(OddsHistory.match_id, OddsHistory.fetched_at)
        ).scalars().all()
    finally:
        db.close()

    closing: dict[int, OddsHistory] = {}
    for s in snaps:                      # ordered by fetched_at → last one wins
        closing[s.match_id] = s

    clvs: list[float] = []
    for mid, col, bet_odds in candidates:
        snap = closing.get(mid)
        close = getattr(snap, col, None) if snap else None
        if close and close > 1.0:
            clvs.append((bet_odds / close - 1.0) * 100.0)

    if not clvs:
        return None
    return CLVStats(
        bets=len(clvs),
        avg_clv_pct=round(float(np.mean(clvs)), 2),
        beat_close_pct=round(100.0 * sum(1 for c in clvs if c > 0) / len(clvs), 1),
    )


def _result_correct(r: dict) -> bool:
    return _predicted_result(r) == r["result"]


def _goals_correct(r: dict) -> bool:
    actual_goals = (r["home_goals"] or 0) + (r["away_goals"] or 0)
    actual_over = actual_goals > 2.5
    pred_over   = r["goals_prediction"] == "OVER"
    return actual_over == pred_over


def _btts_prob(r: dict) -> Optional[float]:
    """
    P(BTTS=GG). Prefers stored btts_prob (BTTS classifier, calibrated).
    Falls back to independent-Poisson approximation when classifier value absent.
    Returns None when neither is available.
    """
    # Prefer dedicated BTTS classifier probability (stored from migration 0013+)
    stored = r.get("btts_prob")
    if stored is not None:
        return float(stored)
    # Fallback: independent Poisson approximation from lambda values
    lam_h = r.get("poisson_lambda_home")
    lam_a = r.get("poisson_lambda_away")
    if not lam_h or not lam_a:
        return None
    return (1.0 - math.exp(-lam_h)) * (1.0 - math.exp(-lam_a))


def _actual_btts(r: dict) -> bool:
    return (r["home_goals"] or 0) > 0 and (r["away_goals"] or 0) > 0


def _top_pick_correct(r: dict) -> Optional[bool]:
    """
    Returns True/False if the suggested_market was correct, None if not a top pick.
    Parses suggested_market string (e.g. "Home Win @ 2.10", "Over 2.5 @ 1.85", "GG @ 1.70").
    """
    sm = r.get("suggested_market")
    if not sm:
        return None
    sm_l = sm.lower()
    total_goals = (r["home_goals"] or 0) + (r["away_goals"] or 0)
    if "home win" in sm_l:
        return r["result"] == "H"
    elif "away win" in sm_l:
        return r["result"] == "A"
    elif "draw" in sm_l:
        return r["result"] == "D"
    elif "over" in sm_l:
        return total_goals > 2.5
    elif "under" in sm_l:
        return total_goals <= 2.5
    elif sm_l.startswith("gg"):
        return _actual_btts(r)
    elif sm_l.startswith("ng"):
        return not _actual_btts(r)
    return None


def _top_pick_market_type(r: dict) -> Optional[str]:
    """Returns 'result', 'goals', or 'btts' for a top-pick row."""
    sm = r.get("suggested_market")
    if not sm:
        return None
    sm_l = sm.lower()
    if any(k in sm_l for k in ("home win", "away win", "draw")):
        return "result"
    elif any(k in sm_l for k in ("over", "under")):
        return "goals"
    elif any(sm_l.startswith(k) for k in ("gg", "ng")):
        return "btts"
    return None


def _accuracy_slice(rows: list[dict]) -> AccuracySlice:
    n = len(rows)
    if n == 0:
        return AccuracySlice(
            total=0, result_correct=0, goals_correct=0, both_correct=0,
            result_accuracy=0.0, goals_accuracy=0.0, both_accuracy=0.0,
        )
    rc = sum(_result_correct(r) for r in rows)
    gc = sum(_goals_correct(r) for r in rows)
    bc = sum(_result_correct(r) and _goals_correct(r) for r in rows)
    return AccuracySlice(
        total=n,
        result_correct=rc,
        goals_correct=gc,
        both_correct=bc,
        result_accuracy=round(rc / n, 4),
        goals_accuracy=round(gc / n, 4),
        both_accuracy=round(bc / n, 4),
    )


# ── Main computation ──────────────────────────────────────────────────────────

def _compute_stats(rows: list[dict]) -> StatsResponse:
    today = date.today()
    cutoff_7d  = today - timedelta(days=7)
    cutoff_30d = today - timedelta(days=30)

    rows_7d  = [r for r in rows if r["match_date"] >= cutoff_7d]
    rows_30d = [r for r in rows if r["match_date"] >= cutoff_30d]

    # Honesty flag: the model went market-independent on 2026-06-17 (market
    # features + anchoring removed). Predictions settled before that were served
    # by the prior anchored model, so all-time accuracy/ROI mixes methodologies.
    _METHODOLOGY_CUTOFF = date(2026, 6, 17)
    _before = sum(1 for r in rows if r["match_date"] < _METHODOLOGY_CUTOFF)
    # Regime eras — extend this list on every methodology change so per-era
    # accuracy never mixes models. (2026-07-10: unified train/serve imputation.)
    _REGIMES: list[tuple[str, Optional[date], Optional[date]]] = [
        ("anchored",       None,               date(2026, 6, 17)),
        ("pure-model",     date(2026, 6, 17),  date(2026, 7, 10)),
        ("pure-unified",   date(2026, 7, 10),  None),
    ]
    regime_slices = []
    for name, lo, hi in _REGIMES:
        sub = [r for r in rows
               if (lo is None or r["match_date"] >= lo)
               and (hi is None or r["match_date"] < hi)]
        if sub:
            regime_slices.append(RegimeSlice(
                regime=name,
                from_date=lo.isoformat() if lo else None,
                to_date=hi.isoformat() if hi else None,
                stats=_accuracy_slice(sub),
            ))
    methodology = MethodologyInfo(
        cutoff=_METHODOLOGY_CUTOFF.isoformat(),
        settled_before=_before,
        settled_after=len(rows) - _before,
        regimes=regime_slices,
    )

    rolling = RollingAccuracy(
        last_7d=_accuracy_slice(rows_7d),
        last_30d=_accuracy_slice(rows_30d),
        all_time=_accuracy_slice(rows),
    )

    # ── By league ─────────────────────────────────────────────────────────────
    league_map: dict[str, list[dict]] = {}
    for r in rows:
        league_map.setdefault(r["league"], []).append(r)

    by_league = []
    for lg, lg_rows in sorted(league_map.items()):
        n = len(lg_rows)
        rc = sum(_result_correct(r) for r in lg_rows)
        gc = sum(_goals_correct(r)  for r in lg_rows)
        bc = sum(_result_correct(r) and _goals_correct(r) for r in lg_rows)
        by_league.append(LeagueBreakdown(
            league=lg, total=n,
            result_correct=rc, goals_correct=gc, both_correct=bc,
            result_accuracy=round(rc / n, 4) if n else 0.0,
            goals_accuracy=round(gc / n, 4)  if n else 0.0,
            both_accuracy=round(bc / n, 4)   if n else 0.0,
        ))
    # sort by total desc
    by_league.sort(key=lambda x: x.total, reverse=True)

    # ── By confidence — CLUB and NATIONAL kept separate ──────────────────────
    # The two pipelines define the label differently (club: composite formula,
    # high needs p_max ≥ 0.55 AND O/U signal; national: p_max ≥ 0.65 alone), so
    # a shared bucket would compare incomparable tiers (club "high" avg p_max
    # ≈ 0.67 vs national "HIGH" ≈ 0.80).
    def _conf_breakdown(sub_rows: list[dict]) -> list[ConfidenceBreakdown]:
        cmap: dict[str, list[dict]] = {}
        for r in sub_rows:
            cmap.setdefault(r["confidence"], []).append(r)
        out = []
        for conf in ("high", "medium", "low"):
            conf_rows = cmap.get(conf, [])
            n  = len(conf_rows)
            rc = sum(_result_correct(r) for r in conf_rows)
            out.append(ConfidenceBreakdown(
                confidence=conf, total=n,
                result_correct=rc,
                result_accuracy=round(rc / n, 4) if n else 0.0,
            ))
        return out

    club_rows = [r for r in rows if not r.get("is_national")]
    nat_rows  = [r for r in rows if r.get("is_national")]
    by_confidence          = _conf_breakdown(club_rows)
    by_confidence_national = _conf_breakdown(nat_rows) if nat_rows else []

    # ── By predicted outcome (H/D/A + OVER/UNDER) ────────────────────────────
    outcome_map: dict[str, list[tuple[bool, dict]]] = {}
    for r in rows:
        pred = _predicted_result(r)
        outcome_map.setdefault(pred, []).append((True, r))
        # goals
        goals_pred = r["goals_prediction"]
        outcome_map.setdefault(goals_pred, []).append((False, r))

    # Rebuild as flat: key → (total, correct)
    outcome_totals: dict[str, list[int]] = {}
    for r in rows:
        pred_result = _predicted_result(r)
        correct_result = _result_correct(r)
        outcome_totals.setdefault(pred_result, [0, 0])
        outcome_totals[pred_result][0] += 1
        if correct_result:
            outcome_totals[pred_result][1] += 1

        goals_pred = r["goals_prediction"]
        correct_goals = _goals_correct(r)
        outcome_totals.setdefault(goals_pred, [0, 0])
        outcome_totals[goals_pred][0] += 1
        if correct_goals:
            outcome_totals[goals_pred][1] += 1

    by_predicted_outcome = []
    for label in ("H", "D", "A", "OVER", "UNDER"):
        if label not in outcome_totals:
            continue
        total, correct = outcome_totals[label]
        by_predicted_outcome.append(PredictedOutcomeBreakdown(
            predicted=label, total=total, correct=correct,
            accuracy=round(correct / total, 4) if total else 0.0,
        ))

    # ── Draw stats ────────────────────────────────────────────────────────────
    actual_draws    = [r for r in rows if r["result"] == "D"]
    predicted_draws = [r for r in rows if _predicted_result(r) == "D"]
    correctly_pred_draws = [r for r in rows
                            if _predicted_result(r) == "D" and r["result"] == "D"]

    total_d  = len(actual_draws)
    pred_d   = len(predicted_draws)
    correct_d = len(correctly_pred_draws)
    recall    = round(correct_d / total_d, 4)  if total_d else 0.0
    precision = round(correct_d / pred_d, 4)   if pred_d  else 0.0

    draw_stats = DrawStats(
        total_draws=total_d,
        predicted_draws=pred_d,
        correctly_predicted=correct_d,
        recall=recall,
        precision=precision,
    )

    # ── Top AI Picks stats (mirrors TopPicks.tsx: top 3/day by confidence→max_prob) ──

    def _top_pick_outcome_for_row(r: dict) -> tuple[str, float, bool]:
        """
        Returns (market_type, pick_prob, correct) for the highest-probability
        outcome in a row — same logic as TopPicks.tsx topPick() function.
        market_type: 'result' | 'goals'
        """
        total_goals = (r["home_goals"] or 0) + (r["away_goals"] or 0)
        under_prob  = 1.0 - r["over_2_5_prob"]
        candidates  = [
            ("result", r["home_win_prob"],   r["result"] == "H"),
            ("result", r["draw_prob"],       r["result"] == "D"),
            ("result", r["away_win_prob"],   r["result"] == "A"),
            ("goals",  r["over_2_5_prob"],   total_goals > 2.5),
            ("goals",  under_prob,           total_goals <= 2.5),
        ]
        return max(candidates, key=lambda c: c[1])

    # Group completed rows by date, sort each day, take top 3
    from collections import defaultdict as _dd
    _date_groups: dict = _dd(list)
    for r in rows:
        _date_groups[r["match_date"]].append(r)

    top_ai_pick_rows: list[tuple[dict, str, float, bool]] = []
    for _day_rows in _date_groups.values():
        # Mirrors TopPicks.tsx: rank by max result-prob only. Confidence tiers
        # are NOT comparable across the club/national pipelines (different
        # formulas/thresholds), so tier-first ranking inverted the true order.
        _sorted = sorted(
            _day_rows,
            key=lambda r: -max(r["home_win_prob"], r["draw_prob"], r["away_win_prob"]),
        )
        for r in _sorted[:3]:
            mt, prob, ok = _top_pick_outcome_for_row(r)
            top_ai_pick_rows.append((r, mt, prob, ok))

    overall_result_acc = rolling.all_time.result_accuracy
    top_picks_stats: Optional[TopPicksStats] = None
    if top_ai_pick_rows:
        n_tp       = len(top_ai_pick_rows)
        n_correct  = sum(1 for _, _, _, ok in top_ai_pick_rows if ok)
        res_rows   = [(prob, ok) for _, mt, prob, ok in top_ai_pick_rows if mt == "result"]
        goal_rows  = [(prob, ok) for _, mt, prob, ok in top_ai_pick_rows if mt == "goals"]
        all_probs  = [prob for _, _, prob, _ in top_ai_pick_rows]
        top_picks_stats = TopPicksStats(
            total=n_tp,
            correct=n_correct,
            accuracy=round(n_correct / n_tp, 4),
            result_picks=len(res_rows),
            result_correct=sum(1 for _, ok in res_rows if ok),
            result_accuracy=round(sum(1 for _, ok in res_rows if ok) / len(res_rows), 4) if res_rows else 0.0,
            goals_picks=len(goal_rows),
            goals_correct=sum(1 for _, ok in goal_rows if ok),
            goals_accuracy=round(sum(1 for _, ok in goal_rows if ok) / len(goal_rows), 4) if goal_rows else 0.0,
            avg_pick_prob=round(float(np.mean(all_probs)), 4),
            vs_overall_accuracy=round(n_correct / n_tp - overall_result_acc, 4),
        )

    # ── BTTS stats ────────────────────────────────────────────────────────────
    # Compute _btts_prob once per row to avoid double-call (filter + collect).
    _btts_all = [(r, _btts_prob(r)) for r in rows]
    btts_rows = [(r, p) for r, p in _btts_all if p is not None]
    btts_stats: Optional[BTTSStats] = None
    if btts_rows:
        actual_gg    = [_actual_btts(r) for r, _ in btts_rows]
        pred_gg      = [p >= 0.5 for _, p in btts_rows]
        n_bt         = len(btts_rows)
        n_actual_gg  = sum(actual_gg)
        n_actual_ng  = n_bt - n_actual_gg
        n_pred_gg    = sum(pred_gg)
        n_pred_ng    = n_bt - n_pred_gg
        n_correct_gg = sum(a and p for a, p in zip(actual_gg, pred_gg))
        n_correct_ng = sum(not a and not p for a, p in zip(actual_gg, pred_gg))
        n_correct    = n_correct_gg + n_correct_ng
        btts_stats = BTTSStats(
            total_gg=n_actual_gg,
            total_ng=n_actual_ng,
            predicted_gg=n_pred_gg,
            predicted_ng=n_pred_ng,
            correctly_predicted_gg=n_correct_gg,
            correctly_predicted_ng=n_correct_ng,
            gg_recall=round(n_correct_gg / n_actual_gg, 4) if n_actual_gg else 0.0,
            ng_recall=round(n_correct_ng / n_actual_ng, 4) if n_actual_ng else 0.0,
            gg_precision=round(n_correct_gg / n_pred_gg, 4) if n_pred_gg else 0.0,
            overall_accuracy=round(n_correct / n_bt, 4) if n_bt else 0.0,
        )

    # ── BTTS calibration ──────────────────────────────────────────────────────
    btts_calibration: list[CalibrationBucket] = []
    if btts_rows:
        bt_edges = [i * 0.10 for i in range(11)]
        for i in range(len(bt_edges) - 1):
            lo, hi = bt_edges[i], bt_edges[i + 1]
            bucket = [(r, p) for r, p in btts_rows if lo <= p < hi]
            if len(bucket) < 3:
                continue
            probs  = [p for _, p in bucket]
            actual = [_actual_btts(r) for r, _ in bucket]
            btts_calibration.append(CalibrationBucket(
                bucket_min=round(lo, 2),
                bucket_max=round(min(hi, 1.0), 2),
                predicted_prob=round(float(np.mean(probs)), 4),
                actual_rate=round(float(np.mean(actual)), 4),
                count=len(bucket),
            ))

    # ── O/U calibration — 10 equal-width probability buckets [0.30, 1.0) ─────
    buckets: list[CalibrationBucket] = []
    edges = [0.30 + i * 0.07 for i in range(10)] + [1.01]  # 10 buckets
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        bucket_rows = [r for r in rows if lo <= r["over_2_5_prob"] < hi]
        if not bucket_rows:
            continue
        probs  = [r["over_2_5_prob"] for r in bucket_rows]
        actual = [(r["home_goals"] or 0) + (r["away_goals"] or 0) > 2.5
                  for r in bucket_rows]
        buckets.append(CalibrationBucket(
            bucket_min=round(lo, 2),
            bucket_max=round(min(hi, 1.0), 2),
            predicted_prob=round(float(np.mean(probs)), 4),
            actual_rate=round(float(np.mean(actual)), 4),
            count=len(bucket_rows),
        ))

    # ── 1×2 Result calibration — per outcome (H / D / A) ────────────────────
    # Uses 0.10-wide bins; requires ≥ 3 matches per bin to surface a point.
    result_calibration: Optional[ResultCalibration] = None
    _result_edges = [round(i * 0.10, 2) for i in range(11)]  # 0.00 … 1.00
    _outcome_cfg = [
        ("H", "home_win_prob"),
        ("D", "draw_prob"),
        ("A", "away_win_prob"),
    ]
    _rc: dict[str, list[CalibrationBucket]] = {}
    for _outcome, _prob_key in _outcome_cfg:
        _ob: list[CalibrationBucket] = []
        for _i in range(len(_result_edges) - 1):
            _lo, _hi = _result_edges[_i], _result_edges[_i + 1]
            _br = [r for r in rows if _lo <= r[_prob_key] < _hi]
            if len(_br) < 3:
                continue
            _probs  = [r[_prob_key] for r in _br]
            _actual = [1.0 if r["result"] == _outcome else 0.0 for r in _br]
            _ob.append(CalibrationBucket(
                bucket_min=_lo,
                bucket_max=round(min(_hi, 1.0), 2),
                predicted_prob=round(float(np.mean(_probs)), 4),
                actual_rate=round(float(np.mean(_actual)), 4),
                count=len(_br),
            ))
        _rc[_outcome] = _ob
    if any(_rc.values()):
        result_calibration = ResultCalibration(
            home=_rc.get("H", []),
            draw=_rc.get("D", []),
            away=_rc.get("A", []),
        )

    # ── By model version ──────────────────────────────────────────────────────
    mv_map: dict[str, list[dict]] = {}
    for r in rows:
        mv_map.setdefault(r["model_version"], []).append(r)

    by_model_version = []
    for mv, mv_rows in sorted(mv_map.items()):
        n  = len(mv_rows)
        rc = sum(_result_correct(r) for r in mv_rows)
        gc = sum(_goals_correct(r)  for r in mv_rows)
        by_model_version.append(ModelVersionStats(
            model_version=mv, total=n,
            result_accuracy=round(rc / n, 4) if n else 0.0,
            goals_accuracy=round(gc / n, 4)  if n else 0.0,
        ))

    # ── ROI & Cumulative EV (only for rows with bookmaker odds stored) ─────────
    STAKE = 10.0  # flat €10 per bet

    # Assumed two-way overround for the O/U 2.5 market (under-2.5 odds are not
    # stored, so we cannot de-vig it exactly). 4% is typical for O/U 2.5 at the
    # major books. Result & BTTS are de-vigged exactly from their stored odds.
    GOALS_OVERROUND = 1.04

    res_staked = res_return = 0.0
    goals_staked = goals_return = 0.0
    btts_staked = btts_return = 0.0
    # Fair-value (de-vigged) returns — same bets, priced at fair odds.
    res_fair_return = goals_fair_return = btts_fair_return = 0.0
    fair_available = False
    # Strategy ROI: bet ONLY the EV-suggested market at its quoted odds.
    # This is the actual value strategy; the blanket bets above/below are a
    # model-health baseline (they pay the vig on every match by construction).
    strat_staked = strat_return = 0.0
    strat_bets = 0

    # EV series: date_str → {ev: float, pnl: float}
    daily: dict[str, dict[str, float]] = {}

    def _shrunk_prob(model_p: float, implied_p: Optional[float]) -> float:
        """Identity pass-through (2026-06-17): predictions are now fully
        market-independent — no anchoring, no EV shrinkage. ROI/EV is measured
        on the PURE model probability vs the market price, matching
        odds_analysis_service.MARKET_SHRINKAGE = 0. Kept as a hook so shrinkage
        can be reintroduced in one place if a future backtest justifies it."""
        return model_p

    for r in rows:
        d_str = str(r["match_date"])
        probs = {"H": r["home_win_prob"], "D": r["draw_prob"], "A": r["away_win_prob"]}
        pred_result = max(probs, key=probs.__getitem__)
        actual_result = r["result"]
        actual_goals = (r["home_goals"] or 0) + (r["away_goals"] or 0)

        # ── Result market bet (baseline: every match) ────────────────────────
        odds_map = {"H": r["bm_home_odds"], "D": r["bm_draw_odds"], "A": r["bm_away_odds"]}
        bet_odds = odds_map.get(pred_result)
        if bet_odds and bet_odds > 1.0:
            model_prob = probs[pred_result]
            won = (actual_result == pred_result)

            res_staked += STAKE
            pnl_r = STAKE * (bet_odds - 1) if won else -STAKE
            res_return += STAKE * bet_odds if won else 0.0
            # EV on the PURE-model probability vs the market price (anchoring +
            # EV-shrinkage were removed 2026-06-17; _shrunk_prob is now identity).
            ev_r = STAKE * (model_prob * bet_odds - 1)

            # Fair (de-vigged) odds for the picked outcome: multiplicative de-vig
            # over the full 1×2 market — fair_odds = quoted × Σ(implied probs).
            pnl_r_fair = pnl_r
            h_o, d_o, a_o = r["bm_home_odds"], r["bm_draw_odds"], r["bm_away_odds"]
            if h_o and d_o and a_o and h_o > 1 and d_o > 1 and a_o > 1:
                overround = 1.0 / h_o + 1.0 / d_o + 1.0 / a_o
                fair_odds = bet_odds * overround
                pnl_r_fair = STAKE * (fair_odds - 1) if won else -STAKE
                res_fair_return += STAKE * fair_odds if won else 0.0
                fair_available = True
            else:
                res_fair_return += STAKE * bet_odds if won else 0.0

            if d_str not in daily:
                daily[d_str] = {"ev": 0.0, "pnl": 0.0, "pnl_fair": 0.0}
            daily[d_str]["ev"]       += ev_r
            daily[d_str]["pnl"]      += pnl_r
            daily[d_str]["pnl_fair"] += pnl_r_fair

        # ── Strategy bet: the suggested market at its quoted odds ───────────
        sm = r.get("suggested_market")
        if sm and " @ " in sm:
            try:
                market_name, odds_str = sm.rsplit(" @ ", 1)
                s_odds = float(odds_str)
            except ValueError:
                market_name, s_odds = "", 0.0
            if s_odds > 1.0:
                gg_actual = (r["home_goals"] or 0) > 0 and (r["away_goals"] or 0) > 0
                outcome = {
                    "Home Win":  actual_result == "H",
                    "Draw":      actual_result == "D",
                    "Away Win":  actual_result == "A",
                    "Over 2.5":  actual_goals > 2.5,
                    "Under 2.5": actual_goals < 2.5,
                    "GG":        gg_actual,
                    "NG":        not gg_actual,
                }.get(market_name)
                if outcome is not None:
                    strat_bets += 1
                    strat_staked += STAKE
                    strat_return += STAKE * s_odds if outcome else 0.0

        # ── BTTS market bet (GG only, when btts_prob >= 0.5) ────────────────
        btts_p = _btts_prob(r)
        if btts_p is not None and btts_p >= 0.5 and r.get("bm_btts_yes_odds") and r["bm_btts_yes_odds"] > 1.0:
            gg_odds = r["bm_btts_yes_odds"]
            won_btts = _actual_btts(r)
            btts_staked += STAKE
            pnl_bt = STAKE * (gg_odds - 1) if won_btts else -STAKE
            btts_return += STAKE * gg_odds if won_btts else 0.0
            ev_bt = STAKE * (_shrunk_prob(btts_p, 1.0 / gg_odds) * gg_odds - 1)

            # Fair (de-vigged) GG odds: two-way de-vig over GG + NG odds.
            pnl_bt_fair = pnl_bt
            ng_odds = r.get("bm_btts_no_odds")
            if ng_odds and ng_odds > 1.0:
                overround_bt = 1.0 / gg_odds + 1.0 / ng_odds
                fair_gg = gg_odds * overround_bt
                pnl_bt_fair = STAKE * (fair_gg - 1) if won_btts else -STAKE
                btts_fair_return += STAKE * fair_gg if won_btts else 0.0
                fair_available = True
            else:
                btts_fair_return += STAKE * gg_odds if won_btts else 0.0

            if d_str not in daily:
                daily[d_str] = {"ev": 0.0, "pnl": 0.0, "pnl_fair": 0.0}
            daily[d_str]["ev"]       += ev_bt
            daily[d_str]["pnl"]      += pnl_bt
            daily[d_str]["pnl_fair"] += pnl_bt_fair

        # ── Goals market bet (OVER only, when model predicts OVER) ──────────
        if r["goals_prediction"] == "OVER" and r["bm_over_odds"] and r["bm_over_odds"] > 1.0:
            over_odds = r["bm_over_odds"]
            over_prob = r["over_2_5_prob"]
            won_goals = actual_goals > 2.5

            goals_staked += STAKE
            pnl_g = STAKE * (over_odds - 1) if won_goals else -STAKE
            goals_return += STAKE * over_odds if won_goals else 0.0
            # Pure-model Over prob vs market price (no anchoring since 2026-06-17).
            ev_g = STAKE * (over_prob * over_odds - 1)

            # Fair Over odds: under-2.5 odds are not stored, so de-vig with an
            # assumed 4% two-way overround (GOALS_OVERROUND) — an estimate.
            fair_over = over_odds * GOALS_OVERROUND
            pnl_g_fair = STAKE * (fair_over - 1) if won_goals else -STAKE
            goals_fair_return += STAKE * fair_over if won_goals else 0.0

            if d_str not in daily:
                daily[d_str] = {"ev": 0.0, "pnl": 0.0, "pnl_fair": 0.0}
            daily[d_str]["ev"]       += ev_g
            daily[d_str]["pnl"]      += pnl_g
            daily[d_str]["pnl_fair"] += pnl_g_fair

    roi: Optional[ROIStats] = None
    if res_staked > 0 or goals_staked > 0 or btts_staked > 0:
        res_pnl    = res_return - res_staked
        goals_pnl  = goals_return - goals_staked
        btts_pnl   = btts_return - btts_staked
        total_st   = res_staked + goals_staked + btts_staked
        total_ret  = res_return + goals_return  + btts_return
        total_pnl  = total_ret  - total_st
        strat_pnl  = strat_return - strat_staked

        # Fair-value (de-vigged) P&L per market + total.
        res_pnl_fair   = res_fair_return   - res_staked
        goals_pnl_fair = goals_fair_return - goals_staked
        btts_pnl_fair  = btts_fair_return  - btts_staked
        total_fair_ret = res_fair_return + goals_fair_return + btts_fair_return
        total_pnl_fair = total_fair_ret - total_st

        roi = ROIStats(
            strategy_bets=strat_bets,
            strategy_staked=round(strat_staked, 2),
            strategy_return=round(strat_return, 2),
            strategy_pnl=round(strat_pnl, 2),
            strategy_roi_pct=round(strat_pnl / strat_staked * 100, 2) if strat_staked else 0.0,
            result_bets=round(res_staked / STAKE),
            result_staked=round(res_staked, 2),
            result_return=round(res_return, 2),
            result_pnl=round(res_pnl, 2),
            result_roi_pct=round(res_pnl / res_staked * 100, 2) if res_staked else 0.0,
            goals_bets=round(goals_staked / STAKE),
            goals_staked=round(goals_staked, 2),
            goals_return=round(goals_return, 2),
            goals_pnl=round(goals_pnl, 2),
            goals_roi_pct=round(goals_pnl / goals_staked * 100, 2) if goals_staked else 0.0,
            btts_bets=round(btts_staked / STAKE) if btts_staked else 0,
            btts_staked=round(btts_staked, 2),
            btts_return=round(btts_return, 2),
            btts_pnl=round(btts_pnl, 2),
            btts_roi_pct=round(btts_pnl / btts_staked * 100, 2) if btts_staked else 0.0,
            total_bets=round(total_st / STAKE),
            total_staked=round(total_st, 2),
            total_return=round(total_ret, 2),
            total_pnl=round(total_pnl, 2),
            total_roi_pct=round(total_pnl / total_st * 100, 2) if total_st else 0.0,
            # Fair-value (vig-removed) ROI — model skill vs the fair market line.
            fair_available=fair_available,
            result_pnl_fair=round(res_pnl_fair, 2),
            result_roi_fair_pct=round(res_pnl_fair / res_staked * 100, 2) if res_staked else 0.0,
            goals_pnl_fair=round(goals_pnl_fair, 2),
            goals_roi_fair_pct=round(goals_pnl_fair / goals_staked * 100, 2) if goals_staked else 0.0,
            btts_pnl_fair=round(btts_pnl_fair, 2),
            btts_roi_fair_pct=round(btts_pnl_fair / btts_staked * 100, 2) if btts_staked else 0.0,
            total_pnl_fair=round(total_pnl_fair, 2),
            total_roi_fair_pct=round(total_pnl_fair / total_st * 100, 2) if total_st else 0.0,
            goals_fair_is_estimated=True,
        )

    # Build cumulative EV series sorted by date
    ev_series: list[EVDataPoint] = []
    cum_ev = cum_pnl = cum_pnl_fair = 0.0
    for d_str in sorted(daily.keys()):
        cum_ev       += daily[d_str]["ev"]
        cum_pnl      += daily[d_str]["pnl"]
        cum_pnl_fair += daily[d_str].get("pnl_fair", 0.0)
        ev_series.append(EVDataPoint(
            date=d_str,
            daily_ev=round(daily[d_str]["ev"], 2),
            daily_pnl=round(daily[d_str]["pnl"], 2),
            daily_pnl_fair=round(daily[d_str].get("pnl_fair", 0.0), 2),
            cumulative_ev=round(cum_ev, 2),
            cumulative_pnl=round(cum_pnl, 2),
            cumulative_pnl_fair=round(cum_pnl_fair, 2),
        ))

    # ── Injury adjustment: raw vs adjusted accuracy on the SAME rows ─────────
    adj_rows = [r for r in rows
                if not r.get("is_national") and r.get("adj_home_win_prob") is not None]
    injury_adjustment: Optional[InjuryAdjustmentStats] = None
    if adj_rows:
        def _adj_predicted(r: dict) -> str:
            probs = {"H": r["adj_home_win_prob"], "D": r["adj_draw_prob"], "A": r["adj_away_win_prob"]}
            return max(probs, key=probs.__getitem__)
        n_adj      = len(adj_rows)
        raw_res    = sum(_result_correct(r) for r in adj_rows)
        adj_res    = sum(_adj_predicted(r) == r["result"] for r in adj_rows)
        raw_goals  = sum(_goals_correct(r) for r in adj_rows)
        adj_goals  = sum((( (r["home_goals"] or 0) + (r["away_goals"] or 0)) > 2.5)
                         == (r["adj_over_2_5_prob"] >= 0.5) for r in adj_rows)
        injury_adjustment = InjuryAdjustmentStats(
            matches=n_adj,
            raw_result_accuracy=round(raw_res / n_adj, 4),
            adj_result_accuracy=round(adj_res / n_adj, 4),
            raw_goals_accuracy=round(raw_goals / n_adj, 4),
            adj_goals_accuracy=round(adj_goals / n_adj, 4),
        )

    # ── CLV: did our suggested bets beat the closing line? ────────────────────
    # For each suggested bet, compare the odds quoted at suggestion time with
    # the last odds_history snapshot for the match (≈ closing line). Positive
    # CLV is the fastest reliable signal of real edge — far less noisy than
    # P&L at this sample size.
    clv = _compute_clv(rows)

    return StatsResponse(
        methodology=methodology,
        rolling=rolling,
        top_picks=top_picks_stats,
        by_league=by_league,
        by_confidence=by_confidence,
        by_confidence_national=by_confidence_national,
        by_predicted_outcome=by_predicted_outcome,
        draw_stats=draw_stats,
        btts_stats=btts_stats,
        calibration=buckets,
        btts_calibration=btts_calibration,
        result_calibration=result_calibration,
        by_model_version=by_model_version,
        roi=roi,
        clv=clv,
        ev_series=ev_series,
        injury_adjustment=injury_adjustment,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


# ── Route ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=StatsResponse)
def get_stats(
    league: Optional[str] = Query(None, description="Filter stats to a single league code"),
) -> StatsResponse:
    """
    Return accuracy-tracking stats for completed matches with ML predictions.
    When league is specified, stats are filtered to that league and use a
    separate per-league cache (same 6h TTL as the global cache).
    """
    if league:
        redis_key = f"stats:league:{league}"
        cached_raw = cache_get(redis_key)
        if cached_raw is not CACHE_MISS:
            return StatsResponse.model_validate(cached_raw)
        rows = _load_rows(league=league)
        result = _compute_stats(rows)
        cache_set(redis_key, result.model_dump(mode="json"), _TTL_SECONDS)
        return result

    cached_raw = cache_get("stats:global")
    if cached_raw is not CACHE_MISS:
        return StatsResponse.model_validate(cached_raw)

    rows = _load_rows()
    result = _compute_stats(rows)
    cache_set("stats:global", result.model_dump(mode="json"), _TTL_SECONDS)
    return result


@router.post("/cache/clear", tags=["admin"], include_in_schema=False,
             dependencies=[Depends(_require_admin_key)])
def clear_stats_cache():
    """Internal endpoint — clear the stats cache so next GET recomputes.
    Requires the X-Admin-Key header (ADMIN_API_KEY) to prevent unauthenticated
    cache-busting (which would force an expensive full recompute)."""
    cache_delete_pattern("stats:*")
    return {"cleared": True}
