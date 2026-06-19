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
        ORDER BY u.created_at ASC
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
