import csv
import io
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.app.database import get_db
from backend.app.ml.predict import confidence_for as _ml_confidence_for
from backend.app.models.match import Match
from backend.app.rate_limit import client_ip, rate_limit_check
from backend.app.schemas.match import MatchResponse, PredictionEmbed

# 20 export requests / min per IP — generous for real users, stops scrapers.
_EXPORT_RATE_LIMIT  = 20
_EXPORT_RATE_WINDOW = 60

router = APIRouter(prefix="/matches", tags=["matches"])


def _utc_today() -> date:
    """UTC-anchored 'today', consistent with the datetime.now(timezone.utc) cutoffs
    used elsewhere in this router — avoids day-boundary drift if the server's
    local timezone isn't UTC."""
    return datetime.now(timezone.utc).date()


def _adjust_prediction_embed(match_id: int, pred, league: "str | None" = None) -> "PredictionEmbed":
    """
    Build an adjusted PredictionEmbed that matches what the detail page serves:

    1. Cached injury adjustment — applied only when injury data is already in the
       process-level cache (populated by a prior /predictions/{id} call).  We
       deliberately do NOT trigger a fresh API call here to avoid N×40 HTTP
       requests on every listing page load.

    2. Dynamic confidence — always recomputed via the composite formula so the
       listing card is never stale (e.g. after model retraining writes a new DB
       confidence value before the cache is cleared).
    """
    hw = pred.home_win_prob
    d  = pred.draw_prob
    aw = pred.away_win_prob
    ov = pred.over_2_5_prob

    # Apply cached injury adjustment if already available (no new API call).
    # Reads from Redis cache populated by a prior /predictions/{id} detail visit.
    try:
        from backend.app.cache import cache_get, CACHE_MISS
        from backend.app.ml.injury_adjustment import adjust_probabilities, has_significant_injuries
        injuries = cache_get(f"injuries:{match_id}")
        if injuries is not CACHE_MISS and injuries:
            home_inj = injuries.get("home", [])
            away_inj = injuries.get("away", [])
            if has_significant_injuries(home_inj, away_inj):
                hw, d, aw, ov = adjust_probabilities(hw, d, aw, ov, home_inj, away_inj)
    except Exception:
        pass  # graceful fallback — listing is never broken by an adjustment error

    goals_pred = "OVER" if ov >= 0.5 else "UNDER"
    confidence = _ml_confidence_for(league, max(hw, d, aw), ov)

    return PredictionEmbed(
        home_win_prob=round(hw, 4),
        draw_prob=round(d, 4),
        away_win_prob=round(aw, 4),
        over_2_5_prob=round(ov, 4),
        goals_prediction=goals_pred,
        model_version=pred.model_version,
        confidence=confidence,
        suggested_market=pred.suggested_market,
        ev_score=pred.ev_score,
        insufficient_data=bool(getattr(pred, "insufficient_data", False)),
    )

VALID_LEAGUES = {
    "EPL", "LaLiga", "SerieA", "Bundesliga", "Ligue1", "GreekSL", "CL", "EL", "ECL",
    "Championship", "LeagueOne", "PrimeiraLiga", "Eredivisie", "BrazilSerieA",
    "ClubFriendly",
}


@router.get("", response_model=List[MatchResponse])
def list_matches(
    league: Optional[str] = Query(None, description="Filter by league code"),
    season: Optional[str] = Query(None, description="Filter by season, e.g. 2023/24"),
    status: Optional[str] = Query(
        None,
        description=(
            "'upcoming' = fixtures with no result (date ≥ today, ordered soonest first); "
            "'past' = played matches (ordered most recent first); "
            "omit for all matches."
        ),
    ),
    include_predictions: bool = Query(
        False,
        description="When true, embed cached prediction data inside each match object. "
                    "Eliminates N+1 fetch round-trips from the frontend.",
    ),
    days_back: Optional[int] = Query(
        None, ge=1, le=90,
        description="When combined with status=past, limit to matches played in the last N days.",
    ),
    days_offset: Optional[int] = Query(
        None, ge=0, le=720,
        description="Shift the days_back window back by N days. "
                    "E.g. days_back=7&days_offset=7 returns matches from 8–14 days ago.",
    ),
    days_ahead: Optional[int] = Query(
        None, ge=1, le=30,
        description="When combined with status=upcoming, limit to fixtures within the next N days. "
                    "E.g. days_ahead=3 returns only today, tomorrow, and the day after.",
    ),
    min_odds: Optional[float] = Query(
        None, ge=1.01,
        description="Only return matches where the predicted outcome has bookmaker odds ≥ this value.",
    ),
    min_confidence: Optional[str] = Query(
        None,
        description="'high' = high only, 'medium' = high+medium; omit for all.",
    ),
    limit: int = Query(40, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    if league and league not in VALID_LEAGUES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown league '{league}'. Valid: {sorted(VALID_LEAGUES)}",
        )
    if status and status not in ("upcoming", "past"):
        raise HTTPException(
            status_code=400,
            detail="status must be 'upcoming' or 'past'",
        )

    if status == "upcoming":
        # A match counts as "upcoming" until 2 hours after its scheduled kick-off,
        # so finished games drop out of the upcoming list automatically even before
        # the results-updater has run and filled in the score.  When kickoff_time
        # is unknown (legacy rows) we fall back to the old date-only rule.
        now          = datetime.now(timezone.utc)
        cutoff       = now - timedelta(hours=2)
        cutoff_date  = cutoff.date()
        cutoff_time  = cutoff.time()

        stmt = (
            select(Match)
            .where(Match.result.is_(None))
            .where(
                or_(
                    # Strictly future day ⇒ definitely upcoming.
                    Match.match_date > cutoff_date,
                    # Same day as the cut-off ⇒ compare times (or accept when unknown).
                    and_(
                        Match.match_date == cutoff_date,
                        or_(
                            Match.kickoff_time.is_(None),
                            Match.kickoff_time > cutoff_time,
                        ),
                    ),
                )
            )
            .order_by(Match.match_date.asc(), Match.kickoff_time.asc().nulls_last(), Match.id.asc())
        )
        if days_ahead is not None:
            stmt = stmt.where(Match.match_date <= _utc_today() + timedelta(days=days_ahead - 1))
    elif status == "past":
        # Include matches that have a result (scraper ran) OR that have ended
        # (kickoff + 2 h ago) even if the scraper hasn't filled in the score yet.
        # This mirrors the inverse of the upcoming filter so there is no gap.
        now_p        = datetime.now(timezone.utc)
        cutoff_p     = now_p - timedelta(hours=2)
        cutoff_date_p = cutoff_p.date()
        cutoff_time_p = cutoff_p.time()

        ended_without_result = and_(
            Match.result.is_(None),
            or_(
                Match.match_date < cutoff_date_p,          # yesterday or older
                and_(
                    Match.match_date == cutoff_date_p,
                    Match.kickoff_time.isnot(None),
                    Match.kickoff_time <= cutoff_time_p,   # kicked off 2+ h ago today
                ),
            ),
        )
        stmt = select(Match).where(
            or_(Match.result.isnot(None), ended_without_result)
        )
        if include_predictions:
            # Only return matches that have a prediction — hides historical gaps
            # where compute_predictions wasn't running.
            from backend.app.models.prediction import Prediction as _PredFilter
            stmt = stmt.where(
                select(_PredFilter.id)
                .where(_PredFilter.match_id == Match.id)
                .exists()
            )
        if days_back is not None:
            lower = _utc_today() - timedelta(days=(days_offset or 0) + days_back)
            stmt = stmt.where(Match.match_date >= lower)
        if days_offset:
            upper = _utc_today() - timedelta(days=days_offset)
            stmt = stmt.where(Match.match_date <= upper)
        stmt = stmt.order_by(Match.match_date.desc(), Match.id.desc())
    else:
        stmt = select(Match).order_by(Match.match_date.desc(), Match.id.desc())

    if league:
        stmt = stmt.where(Match.league == league)
    if season:
        stmt = stmt.where(Match.season == season)

    need_pred_join = min_odds is not None or min_confidence is not None
    if need_pred_join:
        from backend.app.models.prediction import Prediction as _Pred
        stmt = stmt.join(_Pred, _Pred.match_id == Match.id)

        if min_odds is not None:
            predicted_odds = case(
                (
                    and_(
                        _Pred.home_win_prob >= _Pred.draw_prob,
                        _Pred.home_win_prob >= _Pred.away_win_prob,
                    ),
                    _Pred.bm_home_odds,
                ),
                (
                    and_(
                        _Pred.draw_prob >= _Pred.home_win_prob,
                        _Pred.draw_prob >= _Pred.away_win_prob,
                    ),
                    _Pred.bm_draw_odds,
                ),
                else_=_Pred.bm_away_odds,
            )
            stmt = stmt.where(predicted_odds >= min_odds)

        if min_confidence in ("high", "medium"):
            allowed = ["high"] if min_confidence == "high" else ["high", "medium"]
            stmt = stmt.where(_Pred.confidence.in_(allowed))

        stmt = stmt.options(joinedload(Match.prediction))
        include_predictions = True

    # One extra IN-clause query to load all predictions at once (no N+1).
    if include_predictions and not need_pred_join:
        stmt = stmt.options(selectinload(Match.prediction))

    stmt = stmt.offset(offset).limit(limit)
    matches = db.scalars(stmt).all()

    if not include_predictions:
        # Fast path — no prediction post-processing needed.
        return matches

    # Post-process: apply cached injury adjustments and recompute derived fields
    # (goals_prediction, confidence) using the current composite formula so the
    # listing card is always consistent with the match detail page.
    responses: List[MatchResponse] = []
    for match in matches:
        resp = MatchResponse.model_validate(match)
        if resp.prediction is not None and match.prediction is not None:
            resp.prediction = _adjust_prediction_embed(match.id, match.prediction, match.league)
        responses.append(resp)
    return responses


@router.get("/export")
def export_picks(
    request: Request,
    fmt: str = Query("csv", alias="format", description="'csv' or 'json'"),
    league: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    min_odds: Optional[float] = Query(None, ge=1.01),
    min_confidence: Optional[str] = Query(None),
    days_ahead: Optional[int] = Query(None, ge=1, le=30),
    days_back: Optional[int] = Query(None, ge=1, le=90),
    days_offset: Optional[int] = Query(None, ge=0, le=720),
    db: Session = Depends(get_db),
):
    """Export upcoming picks as CSV or JSON (max 500 rows)."""
    if not rate_limit_check(f"export:{client_ip(request)}", _EXPORT_RATE_LIMIT, _EXPORT_RATE_WINDOW):
        raise HTTPException(status_code=429, detail="Too many requests. Try again in a minute.")

    if league and league not in VALID_LEAGUES:
        raise HTTPException(status_code=400, detail=f"Unknown league '{league}'.")

    if status == "upcoming" or status is None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=2)
        cutoff_date = cutoff.date()
        cutoff_time = cutoff.time()
        stmt = (
            select(Match)
            .where(Match.result.is_(None))
            .where(
                or_(
                    Match.match_date > cutoff_date,
                    and_(
                        Match.match_date == cutoff_date,
                        or_(Match.kickoff_time.is_(None), Match.kickoff_time > cutoff_time),
                    ),
                )
            )
            .order_by(Match.match_date.asc(), Match.kickoff_time.asc().nulls_last(), Match.id.asc())
        )
        if days_ahead is not None:
            stmt = stmt.where(Match.match_date <= _utc_today() + timedelta(days=days_ahead - 1))
    else:
        now_e         = datetime.now(timezone.utc)
        cutoff_e      = now_e - timedelta(hours=2)
        cutoff_date_e = cutoff_e.date()
        cutoff_time_e = cutoff_e.time()
        ended_e = and_(
            Match.result.is_(None),
            or_(
                Match.match_date < cutoff_date_e,
                and_(
                    Match.match_date == cutoff_date_e,
                    Match.kickoff_time.isnot(None),
                    Match.kickoff_time <= cutoff_time_e,
                ),
            ),
        )
        stmt = select(Match).where(or_(Match.result.isnot(None), ended_e))
        if days_back is not None:
            lower = _utc_today() - timedelta(days=(days_offset or 0) + days_back)
            stmt = stmt.where(Match.match_date >= lower)
        if days_offset:
            upper = _utc_today() - timedelta(days=days_offset)
            stmt = stmt.where(Match.match_date <= upper)
        stmt = stmt.order_by(Match.match_date.desc(), Match.id.desc())

    if league:
        stmt = stmt.where(Match.league == league)

    from backend.app.models.prediction import Prediction as _Pred
    stmt = stmt.join(_Pred, _Pred.match_id == Match.id)

    if min_odds is not None:
        predicted_odds = case(
            (and_(_Pred.home_win_prob >= _Pred.draw_prob, _Pred.home_win_prob >= _Pred.away_win_prob), _Pred.bm_home_odds),
            (and_(_Pred.draw_prob >= _Pred.home_win_prob, _Pred.draw_prob >= _Pred.away_win_prob), _Pred.bm_draw_odds),
            else_=_Pred.bm_away_odds,
        )
        stmt = stmt.where(predicted_odds >= min_odds)

    if min_confidence in ("high", "medium"):
        allowed = ["high"] if min_confidence == "high" else ["high", "medium"]
        stmt = stmt.where(_Pred.confidence.in_(allowed))

    stmt = stmt.options(joinedload(Match.prediction)).limit(500)
    matches = db.scalars(stmt).all()

    rows = []
    for m in matches:
        p = m.prediction
        rows.append({
            "date": str(m.match_date),
            "time": str(m.kickoff_time) if m.kickoff_time else "",
            "league": m.league,
            "home": m.home_team,
            "away": m.away_team,
            "predicted": p.suggested_market or "",
            "confidence": p.confidence,
            "home_pct": round(p.home_win_prob * 100, 1) if p else "",
            "draw_pct": round(p.draw_prob * 100, 1) if p else "",
            "away_pct": round(p.away_win_prob * 100, 1) if p else "",
            "over_pct": round(p.over_2_5_prob * 100, 1) if p else "",
            "ev_score": round(p.ev_score, 4) if p and p.ev_score else "",
            "bm_home_odds": p.bm_home_odds or "",
            "bm_draw_odds": p.bm_draw_odds or "",
            "bm_away_odds": p.bm_away_odds or "",
        } if p else {
            "date": str(m.match_date),
            "time": str(m.kickoff_time) if m.kickoff_time else "",
            "league": m.league,
            "home": m.home_team,
            "away": m.away_team,
        })

    # ── Merge national-team fixtures ─────────────────────────────────────────
    # Only in the "All Leagues" view (no club league selected) and when no
    # min-odds filter is set — national predictions carry no bookmaker odds.
    if not league and min_odds is None:
        from backend.app.models.national_prediction import NationalPrediction as _Nat

        upcoming_export = (status == "upcoming" or status is None)
        nat_stmt = select(_Nat)
        if upcoming_export:
            nat_stmt = nat_stmt.where(_Nat.actual_result.is_(None))
            nat_stmt = nat_stmt.where(_Nat.match_date >= _utc_today().isoformat())
            if days_ahead is not None:
                upper = (_utc_today() + timedelta(days=days_ahead - 1)).isoformat()
                nat_stmt = nat_stmt.where(_Nat.match_date <= upper)
            nat_stmt = nat_stmt.order_by(_Nat.match_date.asc())
        else:
            nat_stmt = nat_stmt.where(_Nat.actual_result.isnot(None))
            if days_back is not None:
                lower = (_utc_today() - timedelta(days=(days_offset or 0) + days_back)).isoformat()
                nat_stmt = nat_stmt.where(_Nat.match_date >= lower)
            if days_offset:
                upper = (_utc_today() - timedelta(days=days_offset)).isoformat()
                nat_stmt = nat_stmt.where(_Nat.match_date <= upper)
            nat_stmt = nat_stmt.order_by(_Nat.match_date.desc())

        if min_confidence in ("high", "medium"):
            allowed_nat = ["HIGH"] if min_confidence == "high" else ["HIGH", "MEDIUM"]
            nat_stmt = nat_stmt.where(_Nat.confidence.in_(allowed_nat))

        _PICK = {"H": "Home Win", "D": "Draw", "A": "Away Win"}
        for n in db.scalars(nat_stmt.limit(500)).all():
            rows.append({
                "date": n.match_date,
                "time": "",
                "league": "International",
                "home": n.home_team,
                "away": n.away_team,
                "predicted": n.suggested_market or _PICK.get(n.prediction, n.prediction or ""),
                "confidence": (n.confidence or "").lower(),
                "home_pct": round(n.home_win_prob * 100, 1),
                "draw_pct": round(n.draw_prob * 100, 1),
                "away_pct": round(n.away_win_prob * 100, 1),
                "over_pct": round(n.over_2_5_prob * 100, 1),
                "ev_score": round(n.ev_score, 4) if n.ev_score is not None else "",
                "bm_home_odds": n.bm_home_odds or "",
                "bm_draw_odds": n.bm_draw_odds or "",
                "bm_away_odds": n.bm_away_odds or "",
            })

        # Re-sort the combined set so internationals interleave by date.
        rows.sort(key=lambda r: (r["date"], r["time"]),
                  reverse=not upcoming_export)

    if fmt == "json":
        content = json.dumps(rows, indent=2)
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=picks.json"},
        )

    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=picks.csv"},
    )


@router.get("/{match_id}", response_model=MatchResponse)
def get_match(match_id: int, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
    return match
