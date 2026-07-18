"""
Admin users router — list users and their stats, plus training run history.
Requires X-User-Id of an admin user.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.internal_auth import require_internal_secret
from backend.app.models.user import User
from backend.app.models.training_run import TrainingRun
from backend.app.models.feedback import Feedback

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_internal_secret)],
)

from fastapi import Header as _Header


def _require_admin(
    x_user_id: Optional[str] = _Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        uid = int(x_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid user id")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


class UserStatsOut(BaseModel):
    id:              int
    email:           str
    name:            Optional[str]
    provider:        Optional[str]
    is_admin:        bool
    created_at:      str
    last_login_at:   Optional[str]
    last_seen_at:    Optional[str]
    login_count:     int
    tracked_count:   int
    bets_count:      int
    bets_won:        int
    total_profit:    float
    roi_pct:         float


@router.get("/users", response_model=List[UserStatsOut])
def list_users(
    _admin: User = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    rows = db.execute(text("""
        SELECT
            u.id,
            u.email,
            u.name,
            u.provider,
            u.is_admin,
            u.created_at::text                                          AS created_at,
            u.last_login_at::text                                       AS last_login_at,
            u.last_seen_at::text                                        AS last_seen_at,
            COALESCE(u.login_count, 0)                                  AS login_count,
            COUNT(DISTINCT tm.id)                                       AS tracked_count,
            COUNT(DISTINCT ub.id)                                       AS bets_count,
            COUNT(DISTINCT ub.id) FILTER (WHERE ub.outcome = 'win')    AS bets_won,
            COALESCE(SUM(ub.profit), 0)                                 AS total_profit,
            CASE
                WHEN COALESCE(SUM(ub.stake), 0) > 0
                THEN ROUND((COALESCE(SUM(ub.profit), 0) / SUM(ub.stake) * 100)::numeric, 2)
                ELSE 0
            END                                                         AS roi_pct
        FROM users u
        LEFT JOIN tracked_matches tm ON tm.user_id = u.id
        LEFT JOIN user_bets ub       ON ub.user_id = u.id AND ub.outcome IN ('win','loss')
        GROUP BY u.id
        ORDER BY u.last_seen_at DESC NULLS LAST, u.created_at DESC
    """)).fetchall()

    return [dict(r._mapping) for r in rows]


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    admin: User = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete another admin")
    db.delete(target)
    db.commit()


# ── Training runs ─────────────────────────────────────────────────────────────

class TrainingRunOut(BaseModel):
    id:            int
    run_at:        datetime
    model_version: Optional[str]

    n_train: Optional[int]
    n_cal:   Optional[int]
    n_test:  Optional[int]
    cal_cutoff:   Optional[date]
    train_cutoff: Optional[date]
    test_cutoff:  Optional[date]

    result_test_accuracy:  Optional[float]
    result_home_recall:    Optional[float]
    result_draw_recall:    Optional[float]
    result_away_recall:    Optional[float]
    result_home_precision: Optional[float]
    result_draw_precision: Optional[float]
    result_away_precision: Optional[float]

    goals_test_accuracy:  Optional[float]
    goals_over_recall:    Optional[float]
    goals_under_recall:   Optional[float]
    goals_over_precision: Optional[float]

    draw_raw_mean:    Optional[float]
    draw_cal_mean:    Optional[float]
    draw_actual_rate: Optional[float]

    btts_test_accuracy: Optional[float]
    btts_gg_recall:     Optional[float]
    btts_ng_recall:     Optional[float]
    btts_gg_precision:  Optional[float]
    btts_ng_precision:  Optional[float]

    notes: Optional[str]

    model_config = {"from_attributes": True, "protected_namespaces": ()}


@router.get("/training-runs", response_model=List[TrainingRunOut])
def list_training_runs(
    _admin: User = Depends(_require_admin),
    db: Session = Depends(get_db),
    limit: int = 52,
):
    runs = (
        db.query(TrainingRun)
        .order_by(TrainingRun.run_at.desc())
        .limit(limit)
        .all()
    )
    return runs


# ── Feedback inbox (Contact form) ───────────────────────────────────────────────

class FeedbackOut(BaseModel):
    id:         int
    user_id:    Optional[int]
    user_email: Optional[str]
    user_name:  Optional[str]
    message:    str
    is_read:    bool
    created_at: str

    @classmethod
    def from_row(cls, f: Feedback) -> "FeedbackOut":
        return cls(
            id=f.id, user_id=f.user_id, user_email=f.user_email, user_name=f.user_name,
            message=f.message, is_read=f.is_read,
            created_at=f.created_at.isoformat() if f.created_at else "",
        )


@router.get("/feedback", response_model=List[FeedbackOut])
def list_feedback(
    _admin: User = Depends(_require_admin),
    db: Session = Depends(get_db),
    limit: int = 200,
):
    """Contact-form messages, newest first (unread on top)."""
    rows = (
        db.query(Feedback)
        .order_by(Feedback.is_read.asc(), Feedback.created_at.desc())
        .limit(limit)
        .all()
    )
    return [FeedbackOut.from_row(f) for f in rows]


@router.post("/feedback/{feedback_id}/read")
def mark_feedback_read(
    feedback_id: int,
    _admin: User = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    fb = db.get(Feedback, feedback_id)
    if not fb:
        raise HTTPException(status_code=404, detail="Not found")
    fb.is_read = True
    db.commit()
    return {"ok": True}


# ── Market record (dynamic-gate shadow-tracking visibility) ─────────────────────

# Ordered MOST-RECENT-FIRST within each market so the rolling-window cap below
# keeps only the recent settled tickets — matching proven_markets() exactly.
_MARKET_RECORD_SQL = {
    "national": """
        SELECT vb.market, vb.odds, vb.created_at::text AS created_at,
               np.actual_result, np.actual_home_goals, np.actual_away_goals
        FROM value_bets vb
        JOIN national_predictions np ON np.id = vb.national_prediction_id
        WHERE vb.source = 'national'
        ORDER BY vb.market, np.match_date DESC, vb.id DESC
    """,
    "club": """
        SELECT vb.market, vb.odds, vb.created_at::text AS created_at,
               m.result, m.home_goals, m.away_goals
        FROM value_bets vb
        JOIN matches m ON m.id = vb.match_id
        WHERE vb.source = 'club'
        ORDER BY vb.market, m.match_date DESC, vb.id DESC
    """,
}


@router.get("/market-record")
def market_record(
    source: str = "national",
    _admin: User = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Per-market NEW-model settled record from the value-bet ledger — so you can
    watch a shadow-tracked market (GG, Over, …) accumulate evidence and see how
    close it is to promotion into a headline suggestion (or a base market to
    demotion). `source` selects the club or national ledger (same gate rule).

    Settled record + ROI reflect the most-recent PROVEN_ROLLING_WINDOW settled
    tickets — the exact window the live gate evaluates — so a demoted market can
    visibly recover as its recent form improves."""
    from backend.app.ml.odds_analysis_service import (
        _market_won, _market_is_proven, BASE_SUGGESTABLE, NEW_MODEL_CUTOFF,
        PROVEN_MIN_SAMPLES, PROVEN_ROI_FLOOR, DEMOTE_MIN_SAMPLES, DEMOTE_ROI_CEIL,
        PROVEN_ROLLING_WINDOW,
    )

    sql = _MARKET_RECORD_SQL.get(source)
    if sql is None:
        raise HTTPException(status_code=400, detail=f"unknown source: {source!r}")
    rows = db.execute(text(sql)).fetchall()

    agg: dict[str, dict] = {}
    for market, odds, created_at, res, hg, ag in rows:
        a = agg.setdefault(market, {"tracked": 0, "settled": 0, "wins": 0,
                                    "pnl": 0.0, "post_cutoff": 0})
        a["tracked"] += 1
        post = bool(created_at and created_at >= NEW_MODEL_CUTOFF)
        if post:
            a["post_cutoff"] += 1
        won = _market_won(market, res, hg, ag)
        # Only the most-recent PROVEN_ROLLING_WINDOW post-cutoff settled tickets
        # count toward promotion/demotion (rows are date-desc within market).
        if won is not None and odds and post and a["settled"] < PROVEN_ROLLING_WINDOW:
            a["settled"] += 1
            a["wins"] += 1 if won else 0
            a["pnl"] += (float(odds) - 1.0) if won else -1.0

    out = []
    for market, a in sorted(agg.items()):
        n = a["settled"]
        roi = (a["pnl"] / n) if n else None
        is_base = market in BASE_SUGGESTABLE
        proven = _market_is_proven(market, n, roi)   # same rule as the live gate
        out.append({
            "market":            market,
            "is_base":           is_base,
            "proven":            proven,
            "demoted":           is_base and not proven,
            "tracked_total":     a["tracked"],
            "settled":           n,
            "wins":              a["wins"],
            "win_pct":           round(a["wins"] / n, 3) if n else None,
            "roi_pct":           round(roi * 100, 1) if roi is not None else None,
            # Sample-count path applies to non-base markets; a demoted base
            # market re-enters by record recovery, not by counting samples.
            "samples_to_promote": max(0, PROVEN_MIN_SAMPLES - n) if not (proven or is_base) else 0,
        })

    return {
        "source":              source,
        "cutoff":              NEW_MODEL_CUTOFF,
        "min_samples":         PROVEN_MIN_SAMPLES,
        "rolling_window":      PROVEN_ROLLING_WINDOW,
        "roi_floor_pct":       round(PROVEN_ROI_FLOOR * 100, 1),
        "demote_min_samples":  DEMOTE_MIN_SAMPLES,
        "demote_roi_ceil_pct": round(DEMOTE_ROI_CEIL * 100, 1),
        "markets":             out,
    }


@router.get("/gate-changes")
def gate_changes(
    source: Optional[str] = None,
    limit: int = 100,
    _admin: User = Depends(_require_admin),
):
    """History of dynamic-gate promotions/demotions (what the GATE_ALERT_URL
    webhook fires on) — so a market moving in/out of the suggestable set is
    visible in-panel, not only in the logs. Newest first."""
    from backend.app.ml.gate_alerts import load_history
    src = source if source in ("club", "national") else None
    return {"events": load_history(limit=min(max(limit, 1), 500), source=src)}
