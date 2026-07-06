"""
Users router — profile, tracked matches, bets, ROI.

All endpoints expect X-User-Id header (set by Next.js server actions
after NextAuth session verification — treated as trusted internal auth).
"""
from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.internal_auth import require_internal_secret
from backend.app.models.feedback import Feedback
from backend.app.models.prediction import Prediction
from backend.app.models.user import TrackedMatch, User, UserBet
from backend.app.rate_limit import rate_limit_check

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_internal_secret)],
)


# ── Auth helper ───────────────────────────────────────────────────────────────

def get_current_user(
    x_user_id: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        user_id = int(x_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid user id")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── Contact / feedback ──────────────────────────────────────────────────────────

class ContactRequest(BaseModel):
    message: str


@router.post("/contact", status_code=status.HTTP_201_CREATED)
def submit_contact(
    body: ContactRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A logged-in user sends an idea/suggestion → stored for the admin inbox."""
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Το μήνυμα είναι κενό.")
    if len(msg) > 2000:
        raise HTTPException(status_code=400, detail="Το μήνυμα είναι πολύ μεγάλο (μέγιστο 2000 χαρακτήρες).")
    # Light anti-spam: 5 messages / 5 min per user.
    if not rate_limit_check(f"contact:{user.id}", 5, 300):
        raise HTTPException(status_code=429, detail="Πολλά μηνύματα — δοκίμασε ξανά σε λίγο.")
    db.add(Feedback(user_id=user.id, user_email=user.email, user_name=user.name, message=msg))
    db.commit()
    return {"ok": True}


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProfileOut(BaseModel):
    id:                int
    email:             str
    name:              Optional[str]
    image:             Optional[str]
    preferred_leagues: List[str]
    is_admin:          bool = False

    model_config = {"from_attributes": True}


class ProfileUpdateRequest(BaseModel):
    name:              Optional[str]       = None
    preferred_leagues: Optional[List[str]] = None


class TrackRequest(BaseModel):
    match_id: int


class TrackedMatchOut(BaseModel):
    match_id:   int
    home_team:  str
    away_team:  str
    league:     str
    match_date: str
    tracked_at: str
    # Outcome info (NULL until match is played)
    suggested_market:  Optional[str]
    confidence:        Optional[str]


class BetRequest(BaseModel):
    match_id: int
    market:   str
    odds:     float
    stake:    float = 1.0

    @field_validator("odds")
    @classmethod
    def odds_must_be_valid(cls, v: float) -> float:
        if v < 1.0:
            raise ValueError("odds must be >= 1.0")
        return v

    @field_validator("stake")
    @classmethod
    def stake_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("stake must be > 0")
        return v


class BetOut(BaseModel):
    id:        int
    match_id:  int
    market:    str
    odds:      float
    stake:     float
    outcome:   Optional[str]
    profit:    Optional[float]
    placed_at: str


class ROIOut(BaseModel):
    total_bets:   int
    settled_bets: int
    wins:         int
    losses:       int
    total_staked: float
    total_profit: float
    roi_pct:      float
    win_rate:     float


# ── Profile ───────────────────────────────────────────────────────────────────

@router.get("/me", response_model=ProfileOut)
def get_profile(user: User = Depends(get_current_user)):
    return ProfileOut(
        id=user.id,
        email=user.email,
        name=user.name,
        image=user.image,
        preferred_leagues=user.get_preferred_leagues(),
        is_admin=bool(getattr(user, "is_admin", False)),
    )


@router.patch("/me", response_model=ProfileOut)
def update_profile(
    body: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    if body.name is not None:
        user.name = body.name
    if body.preferred_leagues is not None:
        user.set_preferred_leagues(body.preferred_leagues)
    db.commit()
    db.refresh(user)
    return ProfileOut(
        id=user.id,
        email=user.email,
        name=user.name,
        image=user.image,
        preferred_leagues=user.get_preferred_leagues(),
        is_admin=bool(getattr(user, "is_admin", False)),
    )


# ── Tracked Matches ───────────────────────────────────────────────────────────

@router.get("/tracked", response_model=List[TrackedMatchOut])
def get_tracked(
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    rows = db.execute(
        text("""
            SELECT
                tm.match_id,
                m.home_team,
                m.away_team,
                m.league,
                m.match_date::text       AS match_date,
                tm.tracked_at::text      AS tracked_at,
                p.suggested_market,
                p.confidence
            FROM tracked_matches tm
            JOIN predictions p ON p.match_id = tm.match_id
            JOIN matches m     ON m.id        = tm.match_id
            WHERE tm.user_id = :uid
            ORDER BY m.match_date DESC
        """),
        {"uid": user.id},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/tracked", status_code=status.HTTP_201_CREATED)
def track_match(
    body: TrackRequest,
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    existing = (
        db.query(TrackedMatch)
        .filter(TrackedMatch.user_id == user.id, TrackedMatch.match_id == body.match_id)
        .first()
    )
    if existing:
        # Toggle: untrack
        db.delete(existing)
        db.commit()
        return {"tracked": False}

    if not db.query(Prediction).filter(Prediction.match_id == body.match_id).first():
        raise HTTPException(status_code=404, detail="Match not found")

    tm = TrackedMatch(user_id=user.id, match_id=body.match_id)
    db.add(tm)
    db.commit()
    return {"tracked": True}


@router.get("/tracked/{match_id}/status")
def track_status(
    match_id: int,
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    exists = (
        db.query(TrackedMatch)
        .filter(TrackedMatch.user_id == user.id, TrackedMatch.match_id == match_id)
        .first()
    ) is not None
    return {"tracked": exists}


# ── Bets ──────────────────────────────────────────────────────────────────────

@router.get("/bets", response_model=List[BetOut])
def get_bets(
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    bets = db.query(UserBet).filter(UserBet.user_id == user.id).order_by(UserBet.placed_at.desc()).all()
    return [
        BetOut(
            id=b.id,
            match_id=b.match_id,
            market=b.market,
            odds=b.odds,
            stake=b.stake,
            outcome=b.outcome,
            profit=b.profit,
            placed_at=str(b.placed_at),
        )
        for b in bets
    ]


@router.post("/bets", response_model=BetOut, status_code=status.HTTP_201_CREATED)
def place_bet(
    body: BetRequest,
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    if not db.query(Prediction).filter(Prediction.match_id == body.match_id).first():
        raise HTTPException(status_code=404, detail="Match not found")

    bet = UserBet(
        user_id=user.id,
        match_id=body.match_id,
        market=body.market,
        odds=body.odds,
        stake=body.stake,
    )
    db.add(bet)
    db.commit()
    db.refresh(bet)
    return BetOut(
        id=bet.id,
        match_id=bet.match_id,
        market=bet.market,
        odds=bet.odds,
        stake=bet.stake,
        outcome=bet.outcome,
        profit=bet.profit,
        placed_at=str(bet.placed_at),
    )


class SettleRequest(BaseModel):
    outcome: str  # "win" | "loss" | "void"


@router.patch("/bets/{bet_id}", response_model=BetOut)
def settle_bet(
    bet_id: int,
    body: SettleRequest,
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    if body.outcome not in ("win", "loss", "void"):
        raise HTTPException(status_code=422, detail="outcome must be win, loss or void")
    bet = db.get(UserBet, bet_id)
    if not bet or bet.user_id != user.id:
        raise HTTPException(status_code=404, detail="Bet not found")
    bet.outcome = body.outcome
    if body.outcome == "win":
        bet.profit = round(bet.stake * bet.odds - bet.stake, 4)
    elif body.outcome == "loss":
        bet.profit = -bet.stake
    else:
        bet.profit = 0.0
    db.commit()
    db.refresh(bet)
    return BetOut(
        id=bet.id, match_id=bet.match_id, market=bet.market,
        odds=bet.odds, stake=bet.stake, outcome=bet.outcome,
        profit=bet.profit, placed_at=str(bet.placed_at),
    )


# ── ROI ───────────────────────────────────────────────────────────────────────

@router.get("/roi", response_model=ROIOut)
def get_roi(
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    bets = db.query(UserBet).filter(UserBet.user_id == user.id).all()
    total_bets   = len(bets)
    settled      = [b for b in bets if b.outcome in ("win", "loss")]
    settled_bets = len(settled)
    wins         = sum(1 for b in settled if b.outcome == "win")
    losses       = sum(1 for b in settled if b.outcome == "loss")
    total_staked = sum(b.stake for b in settled)
    total_profit = sum(b.profit or 0.0 for b in settled)
    roi_pct      = (total_profit / total_staked * 100) if total_staked > 0 else 0.0
    win_rate     = (wins / settled_bets * 100) if settled_bets > 0 else 0.0

    return ROIOut(
        total_bets=total_bets,
        settled_bets=settled_bets,
        wins=wins,
        losses=losses,
        total_staked=round(total_staked, 2),
        total_profit=round(total_profit, 2),
        roi_pct=round(roi_pct, 2),
        win_rate=round(win_rate, 2),
    )
