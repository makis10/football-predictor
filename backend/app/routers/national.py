"""
National team predictions API.

GET /national/predictions        — all upcoming national team predictions
GET /national/predictions?tournament=FIFA+World+Cup  — filter by tournament
GET /national/predictions?from=2026-06-11&to=2026-06-30
GET /national/predictions/{id}   — single prediction by ID
GET /national/predictions/{id}/analysis — AI + bookmaker odds analysis
GET /national/stats              — accuracy stats from DB (actual_result not null)
GET /national/training-metrics   — model metrics from metrics.json file
GET /national/tournaments        — list distinct tournaments
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.national_prediction import NationalPrediction
from backend.app.schemas.prediction import (
    AnalysisResponse,
    BookmakerData,
    BookmakerFairProbs,
    BookmakerRawOdds,
    ModelProbs,
)

router = APIRouter(prefix="/national", tags=["national"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class NationalPredictionOut(BaseModel):
    id:            int
    match_date:    str
    kickoff_utc:   Optional[datetime] = None
    home_team:     str
    away_team:     str
    tournament:    str
    neutral:       bool
    home_win_prob: float
    draw_prob:     float
    away_win_prob: float
    prediction:    str
    confidence:    str
    over_2_5_prob: float
    btts_prob:     Optional[float]
    bm_home_odds:     Optional[float] = None
    bm_draw_odds:     Optional[float] = None
    bm_away_odds:     Optional[float] = None
    bm_over_odds:     Optional[float] = None
    bm_btts_yes_odds: Optional[float] = None
    bm_btts_no_odds:  Optional[float] = None
    num_bookmakers:   Optional[int]   = None
    ev_score:         Optional[float] = None
    suggested_market: Optional[str]   = None
    exp_home_cards:   Optional[float] = None
    exp_away_cards:   Optional[float] = None
    exp_home_corners:      Optional[float] = None
    exp_away_corners:      Optional[float] = None
    corners_over_9_5_prob: Optional[float] = None
    most_likely_score: Optional[str] = None
    top_scores:        Optional[list[dict]] = None   # [{"score":"2-0","prob":0.16}, …]
    h_elo:         Optional[float]
    a_elo:         Optional[float]
    actual_result:      Optional[str]
    actual_home_goals:  Optional[int]
    actual_away_goals:  Optional[int]
    # ── Settlement ("what we caught") — populated only for finished matches ────
    actual_home_corners: Optional[int]   = None
    actual_away_corners: Optional[int]   = None
    corners_hit:         Optional[bool]  = None   # Over/Under 9.5 call was right
    actual_home_cards:   Optional[float] = None
    actual_away_cards:   Optional[float] = None
    cards_hit:           Optional[bool]  = None   # predicted total within ±1.5
    score_hit:           Optional[bool]  = None   # most_likely_score == actual
    score_in_top:        Optional[bool]  = None   # actual score in top_scores

    @field_validator("top_scores", mode="before")
    @classmethod
    def _parse_top_scores(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return None
        return v

    class Config:
        from_attributes = True


class NationalPredictionList(BaseModel):
    count:       int
    predictions: list[NationalPredictionOut]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/predictions", response_model=NationalPredictionList)
def list_national_predictions(
    tournament: Optional[str]  = Query(None, description="Filter by tournament (partial match)"),
    from_date:  Optional[str]  = Query(None, alias="from",  description="From date YYYY-MM-DD"),
    to_date:    Optional[str]  = Query(None, alias="to",    description="To date YYYY-MM-DD"),
    confidence: Optional[str]  = Query(None, description="HIGH / MEDIUM / LOW"),
    prediction: Optional[str]  = Query(None, description="H / D / A"),
    order:      str            = Query("asc", pattern="^(asc|desc)$",
                                       description="Sort by match_date asc (default) or desc"),
    limit:      int            = Query(200, ge=1, le=500, description="Max results"),
    db: Session = Depends(get_db),
):
    """Return national team predictions, optionally filtered.

    NOTE on `order`: with the default `asc`, a `limit` returns the OLDEST rows.
    The Results view must pass `order=desc` so the cap keeps the most RECENT
    matches — otherwise the ~2.4k backfilled 2024 replay rows fill the limit and
    bury current results.
    """
    q = db.query(NationalPrediction)

    if tournament:
        q = q.filter(NationalPrediction.tournament.ilike(f"%{tournament}%"))
    if from_date:
        q = q.filter(NationalPrediction.match_date >= from_date)
    if to_date:
        q = q.filter(NationalPrediction.match_date <= to_date)
    if confidence:
        q = q.filter(NationalPrediction.confidence == confidence.upper())
    if prediction:
        q = q.filter(NationalPrediction.prediction == prediction.upper())

    col = NationalPrediction.match_date
    q = q.order_by(col.desc() if order == "desc" else col.asc(),
                   NationalPrediction.kickoff_utc.desc() if order == "desc"
                   else NationalPrediction.kickoff_utc.asc())
    rows = q.limit(limit).all()

    return {"count": len(rows), "predictions": rows}


def _date_window(d: str, days: int = 1) -> tuple[str, str]:
    """±`days` calendar window around an ISO date string. Stats are keyed by the
    API fixture date (UTC); our match_date is local, so a late kick-off can land
    on the next UTC day. The window absorbs that ±1-day rollover. Falls back to
    (d, d) if the date can't be parsed."""
    from datetime import date, timedelta
    try:
        base = date.fromisoformat(d)
        return ((base - timedelta(days=days)).isoformat(),
                (base + timedelta(days=days)).isoformat())
    except Exception:
        return (d, d)


def _settle_team_markets(row, db: Session) -> dict:
    """Compare our cards / corners / correct-score predictions with the actual
    outcome for a FINISHED match. Returns {} when the match isn't finished or
    the actual stats haven't been ingested yet. Pure read of existing data."""
    if row.actual_home_goals is None or row.actual_away_goals is None:
        return {}
    out: dict = {}

    # Stats are keyed by the API fixture date (UTC), which can be ±1 day off our
    # local match_date when kick-off rolls over midnight UTC. Match on a ±1-day
    # window + the two teams (a side won't play twice within that span).
    lo, hi = _date_window(row.match_date)

    # Correct score — exact hit and top-6 hit
    actual_score = f"{row.actual_home_goals}-{row.actual_away_goals}"
    if row.most_likely_score:
        out["score_hit"] = (row.most_likely_score == actual_score)
    if row.top_scores:
        ts = row.top_scores
        if isinstance(ts, str):
            try:
                ts = json.loads(ts)
            except Exception:
                ts = []
        out["score_in_top"] = any(s.get("score") == actual_score for s in (ts or []))

    # Actual corners (team_match_stats) — Over/Under 9.5 call
    corners = dict(db.execute(text(
        "SELECT team, corners FROM team_match_stats "
        "WHERE match_date BETWEEN :lo AND :hi AND team IN (:h, :a)"
    ), {"lo": lo, "hi": hi, "h": row.home_team, "a": row.away_team}).fetchall())
    if row.home_team in corners or row.away_team in corners:
        ch = corners.get(row.home_team)
        ca = corners.get(row.away_team)
        out["actual_home_corners"] = ch
        out["actual_away_corners"] = ca
        if ch is not None and ca is not None and row.corners_over_9_5_prob is not None:
            actual_total = ch + ca
            predicted_over = row.corners_over_9_5_prob > 0.5
            out["corners_hit"] = (actual_total > 9.5) == predicted_over

    # Actual cards = Σ(yellow+red) per team from player_match_stats
    cards = dict(db.execute(text(
        "SELECT team, COALESCE(SUM(yellow),0)+COALESCE(SUM(red),0) AS c "
        "FROM player_match_stats WHERE match_date BETWEEN :lo AND :hi AND team IN (:h, :a) "
        "GROUP BY team"
    ), {"lo": lo, "hi": hi, "h": row.home_team, "a": row.away_team}).fetchall())
    if cards:
        ah = cards.get(row.home_team)
        aa = cards.get(row.away_team)
        out["actual_home_cards"] = float(ah) if ah is not None else None
        out["actual_away_cards"] = float(aa) if aa is not None else None
        if (ah is not None and aa is not None
                and row.exp_home_cards is not None and row.exp_away_cards is not None):
            pred_total = row.exp_home_cards + row.exp_away_cards
            out["cards_hit"] = abs(pred_total - (ah + aa)) <= 1.5

    return out


@router.get("/predictions/{prediction_id}", response_model=NationalPredictionOut)
def get_national_prediction(
    prediction_id: int,
    db: Session = Depends(get_db),
):
    row = db.query(NationalPrediction).filter(NationalPrediction.id == prediction_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Prediction not found")
    out = NationalPredictionOut.model_validate(row)
    for k, v in _settle_team_markets(row, db).items():
        setattr(out, k, v)
    return out


class PlayerPropOut(BaseModel):
    team:        str
    player_name: str
    exp_minutes: Optional[float]
    exp_goals:   Optional[float]
    p_score:     Optional[float]
    p_sot_1:     Optional[float]
    p_sot_2:     Optional[float]
    p_assist:    Optional[float]
    # ── Settlement ("what we caught") — only when the match is finished ────────
    played:         Optional[bool] = None   # appeared (has a stats row)
    actual_minutes: Optional[int]  = None
    actual_goals:   Optional[int]  = None
    actual_sot:     Optional[int]  = None
    actual_assists: Optional[int]  = None
    score_hit:      Optional[bool] = None    # scored (goals ≥ 1)
    sot_hit:        Optional[bool] = None    # ≥ 1 shot on target
    assist_hit:     Optional[bool] = None    # ≥ 1 assist

    class Config:
        from_attributes = True


@router.get("/predictions/{prediction_id}/player-props")
def get_player_props(prediction_id: int, db: Session = Depends(get_db)):
    """Per-player prop probabilities (scorer / SoT / assist) for a fixture,
    grouped by team and ordered by scoring probability. For FINISHED matches,
    each player is settled against player_match_stats ("what we caught")."""
    from backend.app.models.player_prop import PlayerProp

    rows = (
        db.query(PlayerProp)
        .filter(PlayerProp.national_prediction_id == prediction_id)
        .order_by(PlayerProp.p_score.desc().nulls_last())
        .all()
    )

    # Actuals for THIS match only — filter by the fixture's teams, not the whole
    # date. Otherwise a match whose stats aren't ingested yet inherits "finished"
    # from other matches that day and shows false DNPs.
    actuals: dict[int, dict] = {}
    if rows:
        lo, hi = _date_window(rows[0].match_date)
        teams = sorted({r.team for r in rows})
        stmt = text(
            "SELECT player_id, minutes, goals, shots_on, assists "
            "FROM player_match_stats WHERE match_date BETWEEN :lo AND :hi AND team IN :teams"
        ).bindparams(bindparam("teams", expanding=True))
        for s in db.execute(stmt, {"lo": lo, "hi": hi, "teams": teams}).fetchall():
            actuals[s.player_id] = {
                "minutes": s.minutes, "goals": s.goals,
                "shots_on": s.shots_on, "assists": s.assists,
            }
    finished = bool(actuals)

    by_team: dict[str, list[PlayerPropOut]] = {}
    for r in rows:
        out = PlayerPropOut.model_validate(r)
        a = actuals.get(r.player_id)
        if a:
            out.played         = (a["minutes"] or 0) > 0
            out.actual_minutes = a["minutes"]
            out.actual_goals   = a["goals"]
            out.actual_sot     = a["shots_on"]
            out.actual_assists = a["assists"]
            out.score_hit  = (a["goals"]    or 0) >= 1
            out.sot_hit    = (a["shots_on"] or 0) >= 1
            out.assist_hit = (a["assists"]  or 0) >= 1
        elif finished:
            out.played = False    # match settled but this player didn't appear
        by_team.setdefault(r.team, []).append(out)
    return {"prediction_id": prediction_id, "teams": by_team, "finished": finished}


@router.get("/predictions/{prediction_id}/analysis", response_model=AnalysisResponse)
def get_national_analysis(
    prediction_id: int,
    db: Session = Depends(get_db),
):
    """
    AI analysis for a national team match. Fetches bookmaker odds (where available
    via The Odds API) and returns a Groq LLM analysis. No injury data — API-Football
    does not support national team injury reports. Results cached 30 min in Redis.
    """
    pred = db.query(NationalPrediction).filter(NationalPrediction.id == prediction_id).first()
    if not pred:
        raise HTTPException(status_code=404, detail="Prediction not found")

    model_probs = {
        "home_win": round(pred.home_win_prob, 4),
        "draw":     round(pred.draw_prob,     4),
        "away_win": round(pred.away_win_prob,  4),
        "over_2_5": round(pred.over_2_5_prob,  4),
        "btts":     round(pred.btts_prob, 4) if pred.btts_prob is not None else None,
    }

    from backend.app.ml.odds_analysis_service import run_national_comparison
    data = run_national_comparison(
        prediction_id=prediction_id,
        home_team=pred.home_team,
        away_team=pred.away_team,
        tournament=pred.tournament,
        model_probs=model_probs,
        match_date=pred.match_date,
    )

    bm_typed = None
    if data.get("bookmakers"):
        bm = data["bookmakers"]
        fp = bm.get("fair_probs", {})
        ro = bm.get("raw_odds", {})
        bm_typed = BookmakerData(
            fair_probs=BookmakerFairProbs(**{k: fp.get(k) for k in
                ["home_win", "draw", "away_win", "over_2_5", "under_2_5",
                 "btts_yes", "btts_no"]}),
            raw_odds=BookmakerRawOdds(**{k: ro.get(k) for k in
                ["home_win", "draw", "away_win", "over_2_5", "under_2_5",
                 "btts_yes", "btts_no"]}),
            bookmakers=bm.get("bookmakers", []),
            num_bookmakers=bm.get("num_bookmakers", 0),
        )

    return AnalysisResponse(
        match_id=prediction_id,
        home_team=pred.home_team,
        away_team=pred.away_team,
        model=ModelProbs(**model_probs),
        bookmakers=bm_typed,
        injuries=None,
        analysis=data["analysis"],
        has_odds_data=data["has_odds_data"],
        has_injury_data=False,
        suggested_market=data.get("suggested_market"),
        suggested_markets=data.get("suggested_markets", []),
        odds_movement=None,
        poisson_stats=None,
    )


@router.get("/tournaments")
def list_tournaments(db: Session = Depends(get_db)):
    """Return distinct tournaments that have predictions."""
    from sqlalchemy import distinct
    rows = db.query(distinct(NationalPrediction.tournament)).order_by(
        NationalPrediction.tournament
    ).all()
    return {"tournaments": [r[0] for r in rows]}


@router.get("/stats")
def national_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Compute accuracy stats from past predictions where actual_result is not null.
    """
    rows = (
        db.query(NationalPrediction)
        .filter(NationalPrediction.actual_result.isnot(None))
        .all()
    )

    if not rows:
        return {
            "total": 0,
            "result_accuracy": 0.0,
            "result_correct": 0,
            "over_accuracy": 0.0,
            "over_correct": 0,
            "draw_stats": {
                "total_draws": 0,
                "predicted_draws": 0,
                "recall": 0.0,
                "precision": 0.0,
            },
            "by_tournament": [],
            "by_confidence": [],
        }

    def _over_correct(row: NationalPrediction) -> bool:
        """True if the over/under 2.5 prediction matches the actual result."""
        if row.actual_home_goals is None or row.actual_away_goals is None:
            return False
        total = row.actual_home_goals + row.actual_away_goals
        if row.over_2_5_prob > 0.5:
            return total > 2
        else:
            return total <= 2

    total = len(rows)
    result_correct = sum(1 for r in rows if r.prediction == r.actual_result)
    over_correct = sum(1 for r in rows if _over_correct(r))
    both_correct = sum(1 for r in rows if r.prediction == r.actual_result and _over_correct(r))

    # Draw stats
    total_draws = sum(1 for r in rows if r.actual_result == "D")
    predicted_draws = sum(1 for r in rows if r.prediction == "D")
    correctly_predicted_draws = sum(1 for r in rows if r.prediction == "D" and r.actual_result == "D")
    draw_recall = correctly_predicted_draws / total_draws if total_draws > 0 else 0.0
    draw_precision = correctly_predicted_draws / predicted_draws if predicted_draws > 0 else 0.0

    # By tournament
    tournament_map: dict[str, dict[str, Any]] = {}
    for r in rows:
        t = r.tournament
        if t not in tournament_map:
            tournament_map[t] = {"total": 0, "result_correct": 0, "over_correct": 0, "both_correct": 0}
        tournament_map[t]["total"] += 1
        res_ok  = r.prediction == r.actual_result
        over_ok = _over_correct(r)
        if res_ok:
            tournament_map[t]["result_correct"] += 1
        if over_ok:
            tournament_map[t]["over_correct"] += 1
        if res_ok and over_ok:
            tournament_map[t]["both_correct"] += 1

    by_tournament = []
    for t, d in sorted(tournament_map.items()):
        t_total = d["total"]
        by_tournament.append({
            "tournament": t,
            "total": t_total,
            "result_correct": d["result_correct"],
            "over_correct": d["over_correct"],
            "both_correct": d["both_correct"],
            "result_accuracy": d["result_correct"] / t_total if t_total > 0 else 0.0,
            "over_accuracy": d["over_correct"] / t_total if t_total > 0 else 0.0,
            "both_accuracy": d["both_correct"] / t_total if t_total > 0 else 0.0,
        })

    # By confidence
    confidence_map: dict[str, dict[str, Any]] = {}
    for r in rows:
        c = r.confidence.upper()
        if c not in confidence_map:
            confidence_map[c] = {"total": 0, "result_correct": 0}
        confidence_map[c]["total"] += 1
        if r.prediction == r.actual_result:
            confidence_map[c]["result_correct"] += 1

    by_confidence = []
    for conf in ["HIGH", "MEDIUM", "LOW"]:
        if conf in confidence_map:
            d = confidence_map[conf]
            c_total = d["total"]
            by_confidence.append({
                "confidence": conf,
                "total": c_total,
                "result_correct": d["result_correct"],
                "result_accuracy": d["result_correct"] / c_total if c_total > 0 else 0.0,
            })

    return {
        "total": total,
        "result_accuracy": result_correct / total if total > 0 else 0.0,
        "result_correct": result_correct,
        "over_accuracy": over_correct / total if total > 0 else 0.0,
        "over_correct": over_correct,
        "both_correct": both_correct,
        "both_accuracy": both_correct / total if total > 0 else 0.0,
        "draw_stats": {
            "total_draws": total_draws,
            "predicted_draws": predicted_draws,
            "recall": draw_recall,
            "precision": draw_precision,
        },
        "by_tournament": by_tournament,
        "by_confidence": by_confidence,
    }


# Path: backend/app/routers/national.py
# parent               = backend/app/routers
# parent.parent        = backend/app
# parent.parent.parent = backend          ← data/ lives here
_METRICS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "models"
    / "national"
    / "metrics.json"
)


@router.get("/training-metrics")
def training_metrics() -> dict[str, Any]:
    """Return national model training metrics from metrics.json, or {available: false}."""
    if not _METRICS_PATH.exists():
        return {"available": False}
    try:
        with open(_METRICS_PATH) as f:
            data = json.load(f)
        data["available"] = True
        return data
    except Exception:
        return {"available": False}


_WC_SIM_PATH = _METRICS_PATH.parent / "wc_simulation.json"


@router.get("/wc-simulation")
def wc_simulation() -> dict[str, Any]:
    """Return the Monte Carlo World Cup simulation results, or {available: false}."""
    if not _WC_SIM_PATH.exists():
        return {"available": False}
    try:
        with open(_WC_SIM_PATH) as f:
            data = json.load(f)
        data["available"] = True
        return data
    except Exception:
        return {"available": False}
