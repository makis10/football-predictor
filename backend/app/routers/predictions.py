import os
import time
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.cache import CACHE_MISS, cache_get, cache_set
from backend.app.database import get_db
from backend.app.ml.predict import confidence_for
from backend.app.models.match import Match
from backend.app.models.odds_history import OddsHistory
from backend.app.models.prediction import Prediction
from backend.app.schemas.prediction import (
    AnalysisResponse,
    BookmakerData,
    BookmakerFairProbs,
    BookmakerRawOdds,
    CorrectScoreProb,
    GoalsPrediction,
    InjuredPlayer,
    InjuryData,
    ModelProbs,
    OddsMovement,
    PoissonStats,
    PredictionResponse,
    WinProbabilities,
)

router = APIRouter(prefix="/predictions", tags=["predictions"])

_RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw")
_history_df: pd.DataFrame | None = None
_team_snapshot: dict | None = None

# ── Injury cache ──────────────────────────────────────────────────────────────
# TTL = 30 min — avoids hammering API-Football on repeated page loads.
# Stored in Redis so it survives backend restarts.
_INJURY_TTL = 30 * 60   # seconds


def _get_history() -> pd.DataFrame:
    """Load CSVs once and cache for the lifetime of the process."""
    global _history_df
    if _history_df is None:
        from backend.app.ml.features import load_raw_csvs
        _history_df = load_raw_csvs(_RAW_DIR)
    return _history_df


def _get_snapshot() -> dict:
    """
    Build team snapshot (Elo, Pi-Ratings, Poisson state, rolling windows) once
    and cache for the lifetime of the process.  The snapshot is used to compute
    BTTS probability on-the-fly without a DB column or extra API call.
    """
    global _team_snapshot
    if _team_snapshot is None:
        from backend.app.ml.features import build_team_snapshot
        _team_snapshot = build_team_snapshot(_get_history())
    return _team_snapshot


def _get_injuries_cached(
    match_id: int,
    home_team: str,
    away_team: str,
    league: str,
    match_date,
) -> Optional[dict]:
    """
    Return injury data for a match, using a 30-minute in-process cache.
    Returns None when API key is missing, league unsupported, or API fails.
    """
    cached = cache_get(f"injuries:{match_id}")
    if cached is not CACHE_MISS:
        return cached  # may be None (no injuries) or a dict

    from backend.app.ml.odds_analysis_service import fetch_injuries
    result = fetch_injuries(home_team, away_team, league, match_date)
    cache_set(f"injuries:{match_id}", result, _INJURY_TTL)
    return result


def _compute_btts(
    home_team: str,
    away_team: str,
    league: str,
    match_date,
    xgb_over_2_5: float | None = None,
) -> float | None:
    """
    Return a BTTS probability that blends the Poisson model with the XGBoost
    over_2_5_prob signal.

    The Poisson model uses Pi-Ratings / Elo which are slow to update; when a
    team has improved recently, Poisson can significantly underestimate its
    attack strength.  When |xgb_over - poisson_over| > 0.20 we scale btts
    proportionally toward the XGBoost view so the two displayed predictions
    (Over/Under and BTTS) are directionally coherent.
    """
    try:
        from backend.app.ml.features import compute_match_features
        feat = compute_match_features(
            snapshot=_get_snapshot(),
            home_team=home_team,
            away_team=away_team,
            league=league,
            match_date=match_date,
        )
        val = feat.get("poisson_btts")
        if val is None or (isinstance(val, float) and val != val):
            return None

        poisson_btts = float(val)

        # Blend with XGBoost over_2_5 when they disagree significantly (>0.20).
        # This corrects for stale Poisson ratings without overriding cases where
        # the Poisson model is well-calibrated (small disagreement = trust Poisson).
        if xgb_over_2_5 is not None:
            poisson_over_raw = feat.get("poisson_over_2_5")
            if poisson_over_raw and float(poisson_over_raw) > 0.05:
                poisson_over = float(poisson_over_raw)
                disagreement = abs(xgb_over_2_5 - poisson_over)
                if disagreement > 0.20:
                    scale = xgb_over_2_5 / poisson_over
                    btts_scaled = max(0.05, min(0.95, poisson_btts * scale))
                    # 40% Poisson, 60% XGBoost-scaled when large disagreement
                    poisson_btts = round(0.4 * poisson_btts + 0.6 * btts_scaled, 4)

        return round(max(0.05, min(0.95, poisson_btts)), 4)
    except Exception as e:
        import logging
        logging.getLogger("predictions").warning("[btts] Could not compute BTTS for %s vs %s: %s", home_team, away_team, e)
    return None


def _build_response(
    match: Match,
    pred: Prediction,
    adjusted: Optional[tuple[float, float, float, float]] = None,
) -> PredictionResponse:
    """
    Build the PredictionResponse.

    adjusted: optional (home_win, draw, away_win, over_2_5) tuple produced by
              the injury adjustment layer.  When supplied, these values are
              served to the frontend instead of the raw DB values — the DB
              record is never overwritten so accuracy tracking stays clean.
    """
    if adjusted:
        hw, d, aw, ov = adjusted
        goals_pred = "OVER" if ov >= 0.5 else "UNDER"
    else:
        hw = round(pred.home_win_prob, 4)
        d  = round(pred.draw_prob,     4)
        aw = round(pred.away_win_prob,  4)
        ov = round(pred.over_2_5_prob,  4)
        goals_pred = pred.goals_prediction

    btts = _compute_btts(
        match.home_team, match.away_team, match.league, match.match_date,
        xgb_over_2_5=ov,
    )

    # Enforce logical consistency: a draw with Over 2.5 goals (≥ 3 total) is
    # impossible without both teams scoring.  Any draw at 2-2, 3-3 etc.
    # requires BTTS = True (GG).  The three models (result, goals, Poisson)
    # are trained independently and can produce this impossible combination;
    # correct it at display time without touching the stored probabilities.
    result_pred = max({"H": hw, "D": d, "A": aw}, key=lambda k: {"H": hw, "D": d, "A": aw}[k])
    if btts is not None and result_pred == "D" and goals_pred == "OVER" and btts < 0.5:
        btts = max(btts, 0.51)

    return PredictionResponse(
        match_id=match.id,
        home_team=match.home_team,
        away_team=match.away_team,
        league=match.league,
        match_date=match.match_date,
        win_probabilities=WinProbabilities(
            home_win=hw,
            draw=d,
            away_win=aw,
        ),
        goals=GoalsPrediction(
            over_2_5_probability=ov,
            prediction=goals_pred,
        ),
        btts_prob=btts,
        model_version=pred.model_version,
        # Recompute confidence from the DISPLAYED probs (which may be
        # injury-adjusted) so the label always matches what the user sees.
        # The raw DB value is intentionally ignored here.
        confidence=confidence_for(match.league, max(hw, d, aw), ov),
    )


def _apply_injury_adjustment(
    match: Match,
    pred: Prediction,
) -> Optional[tuple[float, float, float, float]]:
    """
    Fetch injuries (cached 30 min) and compute adjusted probabilities.
    Returns None when: no injury data, match already started, or change is tiny.
    Only applies to upcoming matches (result is None).
    """
    import datetime
    if match.result is not None:
        return None   # match has a result — don't adjust

    injuries = _get_injuries_cached(
        match.id, match.home_team, match.away_team,
        match.league, match.match_date,
    )
    if not injuries:
        return None

    from backend.app.ml.injury_adjustment import adjust_probabilities, has_significant_injuries
    home_inj = injuries.get("home", [])
    away_inj = injuries.get("away", [])

    if not has_significant_injuries(home_inj, away_inj):
        return None   # only trivial questionable players — not worth adjusting

    return adjust_probabilities(
        pred.home_win_prob, pred.draw_prob, pred.away_win_prob, pred.over_2_5_prob,
        home_inj, away_inj,
    )


@router.get("/{match_id}", response_model=PredictionResponse)
def get_prediction(match_id: int, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail=f"Match {match_id} not found")

    pred = db.scalars(
        select(Prediction).where(Prediction.match_id == match_id)
    ).first()

    if pred:
        adjusted = _apply_injury_adjustment(match, pred)
        return _build_response(match, pred, adjusted)

    # Snapshot what we need from the match, then release the DB connection
    # before the expensive ML computation so we don't exhaust the pool.
    home_team  = match.home_team
    away_team  = match.away_team
    match_date = match.match_date
    league     = match.league
    mid        = match.id
    db.close()

    # Compute prediction — history is cached after first request, so subsequent
    # calls skip the CSV loading and only run build_features for this one match.
    try:
        from backend.app.ml.predict import predict_match

        result = predict_match(
            history_df=_get_history(),
            home_team=home_team,
            away_team=away_team,
            match_date=match_date,
            league=league,
            match_id=mid,
        )
    except Exception as e:
        import logging
        logging.getLogger("predictions").error("predict_match failed for match %s: %s", mid, e)
        raise HTTPException(
            status_code=503,
            detail="Prediction service temporarily unavailable.",
        )

    # Open a fresh session to persist the result
    from backend.app.database import SessionLocal
    db2 = SessionLocal()
    try:
        # Guard against a race where another request already inserted
        existing = db2.scalars(
            select(Prediction).where(Prediction.match_id == mid)
        ).first()
        if existing:
            match2 = db2.get(Match, mid)
            adj2 = _apply_injury_adjustment(match2, existing)
            return _build_response(match2, existing, adj2)

        new_pred = Prediction(
            match_id=mid,
            home_win_prob=result["win_probabilities"]["home_win"],
            draw_prob=result["win_probabilities"]["draw"],
            away_win_prob=result["win_probabilities"]["away_win"],
            over_2_5_prob=result["goals"]["over_2_5_probability"],
            goals_prediction=result["goals"]["prediction"],
            model_version=result["model_version"],
            confidence=result["confidence"],
        )
        db2.add(new_pred)
        db2.commit()
        db2.refresh(new_pred)
        match2 = db2.get(Match, mid)
        adj3 = _apply_injury_adjustment(match2, new_pred)
        return _build_response(match2, new_pred, adj3)
    finally:
        db2.close()


@router.get("/{match_id}/analysis", response_model=AnalysisResponse)
def get_match_analysis(match_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Compare the ML prediction with live bookmaker odds and return a Claude
    AI analysis.  Results are cached in memory for 1 hour per match to
    conserve The Odds API free-tier quota (500 req/month).

    Returns 404 if no prediction exists yet for this match.
    Returns has_odds_data=false if ODDS_API_KEY is missing or match not found
    on The Odds API (still returns Claude analysis with model-only context).
    """
    # Public LLM-backed endpoint — rate-limit per client to protect the Groq /
    # Odds API free quotas from scraping.
    from backend.app.rate_limit import rate_limit_check, client_ip
    if not rate_limit_check(f"analysis:{client_ip(request)}", max_calls=20, window=60):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")

    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail=f"Match {match_id} not found")

    pred = db.scalars(
        select(Prediction).where(Prediction.match_id == match_id)
    ).first()
    if not pred:
        raise HTTPException(
            status_code=404,
            detail="No prediction cached for this match yet — call /predictions/{id} first.",
        )

    # Apply the same injury adjustment as get_prediction so that the ML probs
    # shown in the analysis panel ALWAYS match the top prediction cards.
    # Without this, the raw DB value (e.g. Over 61%) would be used here while
    # the prediction card shows the adjusted value (e.g. Over 46%), making the
    # two sections of the page show contradictory model numbers.
    adjusted = _apply_injury_adjustment(match, pred)
    if adjusted:
        hw, d, aw, ov = adjusted
    else:
        hw = round(pred.home_win_prob, 4)
        d  = round(pred.draw_prob,     4)
        aw = round(pred.away_win_prob, 4)
        ov = round(pred.over_2_5_prob, 4)

    # Use the same blended + logically-consistent BTTS as _build_response so that
    # the analysis bookmaker comparison table shows the same model btts as the
    # prediction card above it.
    btts = _compute_btts(
        match.home_team, match.away_team, match.league, match.match_date,
        xgb_over_2_5=ov,
    )
    result_pred = max({"H": hw, "D": d, "A": aw}, key=lambda k: {"H": hw, "D": d, "A": aw}[k])
    goals_pred_str = "OVER" if ov >= 0.5 else "UNDER"
    if btts is not None and result_pred == "D" and goals_pred_str == "OVER" and btts < 0.5:
        btts = max(btts, 0.51)

    model_probs = {
        "home_win": hw,
        "draw":     d,
        "away_win": aw,
        "over_2_5": ov,
        "btts":     btts,
    }

    from backend.app.ml.odds_analysis_service import run_comparison
    data = run_comparison(
        match_id=match_id,
        home_team=match.home_team,
        away_team=match.away_team,
        league=match.league,
        model_probs=model_probs,
        match_date=match.match_date,
    )

    # Build typed response
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

    # Build typed injury response
    inj_typed = None
    if data.get("injuries"):
        raw_inj = data["injuries"]
        inj_typed = InjuryData(
            home=[InjuredPlayer(**p) for p in raw_inj.get("home", []) if p.get("name")],
            away=[InjuredPlayer(**p) for p in raw_inj.get("away", []) if p.get("name")],
        )

    # ── Odds movement: compare the two most recent snapshots ─────────────────
    movement: OddsMovement | None = None
    snapshots = (
        db.query(OddsHistory)
        .filter(OddsHistory.match_id == match_id)
        .order_by(OddsHistory.fetched_at.desc())
        .limit(2)
        .all()
    )
    if len(snapshots) == 2:
        latest, prev = snapshots[0], snapshots[1]
        age_hours = None
        if prev.fetched_at and latest.fetched_at:
            import datetime as _dt
            diff = latest.fetched_at - prev.fetched_at
            age_hours = round(diff.total_seconds() / 3600, 1)

        def _delta(a, b):
            if a is not None and b is not None:
                return round(a - b, 3)
            return None

        movement = OddsMovement(
            home_delta=_delta(latest.home_odds, prev.home_odds),
            draw_delta=_delta(latest.draw_odds, prev.draw_odds),
            away_delta=_delta(latest.away_odds, prev.away_odds),
            over_delta=_delta(latest.over_odds, prev.over_odds),
            snapshot_age_hours=age_hours,
        )

    # ── Extended Poisson stats (serve-time, from stored λ values) ────────────
    poisson_stats_typed: PoissonStats | None = None
    lam_h = getattr(pred, "poisson_lambda_home", None)
    lam_a = getattr(pred, "poisson_lambda_away", None)
    if lam_h and lam_a and lam_h > 0 and lam_a > 0:
        from backend.app.ml.poisson import compute_extended_poisson_stats
        ps = compute_extended_poisson_stats(lam_h, lam_a)
        poisson_stats_typed = PoissonStats(
            over_1_5=ps["over_1_5"],
            under_1_5=ps["under_1_5"],
            over_2_5=ps["over_2_5"],
            under_2_5=ps["under_2_5"],
            over_3_5=ps["over_3_5"],
            under_3_5=ps["under_3_5"],
            home_over_1_5=ps["home_over_1_5"],
            home_under_1_5=ps["home_under_1_5"],
            away_over_1_5=ps["away_over_1_5"],
            away_under_1_5=ps["away_under_1_5"],
            top_scores=[CorrectScoreProb(**s) for s in ps["top_scores"]],
            most_likely_score=ps["most_likely_score"],
            btts_and_over_2_5=ps["btts_and_over_2_5"],
            btts_and_under_2_5=ps["btts_and_under_2_5"],
            home_win_and_btts=ps["home_win_and_btts"],
            away_win_and_btts=ps["away_win_and_btts"],
            home_win_and_ng=ps["home_win_and_ng"],
            away_win_and_ng=ps["away_win_and_ng"],
        )

    return AnalysisResponse(
        match_id=match_id,
        home_team=match.home_team,
        away_team=match.away_team,
        model=ModelProbs(**model_probs),
        bookmakers=bm_typed,
        injuries=inj_typed,
        analysis=data["analysis"],
        suggested_market=data.get("suggested_market"),
        suggested_markets=data.get("suggested_markets", []),
        poisson_stats=poisson_stats_typed,
        has_odds_data=data["has_odds_data"],
        has_injury_data=data.get("has_injury_data", False),
        odds_movement=movement,
    )


# ── In-process cache for postmortem analyses ──────────────────────────────────
_POSTMORTEM_TTL = 24 * 3600  # 24 h — deterministic once match is over


@router.get("/{match_id}/postmortem")
def get_postmortem(match_id: int, db: Session = Depends(get_db)):
    """
    AI post-mortem: why did this prediction fail?
    Requires the match to have a final result. Returns a short Groq analysis.
    Cached in-process (no TTL — result is deterministic once the match is over).
    """
    cached_pm = cache_get(f"postmortem:{match_id}")
    if cached_pm is not CACHE_MISS:
        return {"analysis": cached_pm}

    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
    if match.result is None:
        raise HTTPException(status_code=400, detail="Match has not finished yet.")

    pred = db.scalars(
        select(Prediction).where(Prediction.match_id == match_id)
    ).first()
    if not pred:
        raise HTTPException(status_code=404, detail="No prediction found for this match.")

    # Determine predicted vs actual outcome
    probs = {"H": pred.home_win_prob, "D": pred.draw_prob, "A": pred.away_win_prob}
    predicted_result = max(probs, key=probs.__getitem__)
    predicted_prob   = round(probs[predicted_result] * 100)
    actual_result    = match.result

    label = {"H": "Home Win", "D": "Draw", "A": "Away Win"}
    predicted_label = label[predicted_result]
    actual_label    = label[actual_result]

    goals_pred  = pred.goals_prediction
    total_goals = (match.home_goals or 0) + (match.away_goals or 0)
    goals_actual = "OVER" if total_goals > 2.5 else "UNDER"
    goals_correct = goals_pred == goals_actual

    score = f"{match.home_goals}–{match.away_goals}"

    # Fetch real match events (goals, cards, penalties) from API-Football
    from backend.app.ml.odds_analysis_service import GROQ_API_KEY, GROQ_MODEL, fetch_match_events
    events_text = fetch_match_events(
        match.home_team, match.away_team, match.league, match.match_date
    )

    events_block = (
        f"\nΓεγονότα αγώνα:\n{events_text}"
        if events_text
        else "\n(Δεν υπάρχουν διαθέσιμα δεδομένα γεγονότων αγώνα)"
    )

    result_wrong  = predicted_result != actual_result
    goals_wrong   = not goals_correct
    verdict_parts = []
    if result_wrong:
        verdict_parts.append(f"αποτέλεσμα: προβλέψαμε {predicted_label} ({predicted_prob}%), έγινε {actual_label}")
    if goals_wrong:
        verdict_parts.append(f"γκολ: προβλέψαμε {goals_pred} 2.5, έγιναν {total_goals} ({goals_actual})")

    prompt = f"""Post-mortem ανάλυση αποτυχημένης πρόβλεψης ποδοσφαίρου. Γράψε ΜΟΝΟ στα ελληνικά, 3-4 προτάσεις, χωρίς εισαγωγή.

Αγώνας: {match.home_team} vs {match.away_team} ({match.league}, {match.match_date})
Σκορ: {score}
Λάθος πρόβλεψη — {" | ".join(verdict_parts)}{events_block}

Βασίσου ΚΥΡΙΩΣ στα πραγματικά γεγονότα (γκολ, κόκκινες, πέναλτι) για να εξηγήσεις γιατί η πρόβλεψη απέτυχε. Ονόμασε συγκεκριμένα γεγονότα με λεπτά αν υπάρχουν. Αν δεν υπάρχουν γεγονότα, αναφέρσου στη φυσική αβεβαιότητα."""

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        msg = client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=300,
            temperature=0.35,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.choices[0].message.content.strip()
    except Exception as e:
        import logging
        logging.getLogger("predictions").error("postmortem Groq call failed for match %s: %s", match_id, e)
        text = "Ανάλυση μη διαθέσιμη αυτή τη στιγμή."

    cache_set(f"postmortem:{match_id}", text, _POSTMORTEM_TTL)
    return {"analysis": text}
