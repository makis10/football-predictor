"""
Inference logic — load saved models and produce a prediction for a match.

The caller must supply:
  - The full historical DataFrame (used to derive team Elo + rolling stats
    up to the match date).
  - home_team, away_team, match_date (and optionally league).

Returns a dict compatible with the Phase 2 API response schema.
"""

from __future__ import annotations

import os
import pickle
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd


class SoftVoteEnsemble:
    """Lightweight 2-model soft-voting wrapper (pickle-friendly).

    Defined here (not in train.py) so that pickle.load works regardless of
    which script is __main__ at load time.
    """
    def __init__(self, models, weights):
        self.models   = models
        self.weights  = np.array(weights) / sum(weights)
        self.classes_ = models[0].classes_

    def predict_proba(self, X):
        return sum(w * m.predict_proba(X) for m, w in zip(self.models, self.weights))

    def predict(self, X):
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]


from backend.app.ml.features import (
    FEATURE_COLS, RESULT_FEATURE_COLS, GOALS_FEATURE_COLS,
    ELO_START,
    build_features,
)
from backend.app.ml.european import load_european_data, EUROPEAN_DIR
from backend.app.ml.calibration import load_calibrators, apply_calibration, apply_recent_calibration
from backend.app.ml.draw_classifier import (
    load_draw_classifier, load_draw_calibrator,
    predict_draw_prob, apply_draw_calibration, blend_draw_probability,
)
from backend.app.ml.btts_classifier import (
    load_btts_classifier, load_btts_calibrator,
    predict_btts_prob, apply_btts_calibration,
)

MODELS_DIR    = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models")
MODEL_VERSION = os.getenv("MODEL_VERSION", "1.0.0")

# Draw blend alpha — loaded from train-time auto-tune; fallback to 0.20
def _load_draw_alpha() -> float:
    import json
    path = os.path.join(MODELS_DIR, "draw_alpha.json")
    try:
        with open(path) as f:
            return float(json.load(f).get("draw_blend_alpha", 0.20))
    except Exception:
        return 0.20

_DRAW_ALPHA: Optional[float] = None

def _get_draw_alpha() -> float:
    global _DRAW_ALPHA
    if _DRAW_ALPHA is None:
        _DRAW_ALPHA = _load_draw_alpha()
    return _DRAW_ALPHA

# BTTS GG threshold — loaded from train-time PR-curve sweep; fallback to 0.50
def _load_btts_threshold() -> float:
    import json
    path = os.path.join(MODELS_DIR, "btts_threshold.json")
    try:
        with open(path) as f:
            return float(json.load(f).get("btts_gg_threshold", 0.50))
    except Exception:
        return 0.50

_BTTS_THRESHOLD: Optional[float] = None

def _get_btts_threshold() -> float:
    global _BTTS_THRESHOLD
    if _BTTS_THRESHOLD is None:
        _BTTS_THRESHOLD = _load_btts_threshold()
    return _BTTS_THRESHOLD

# Cache european data for the lifetime of the process
_european_df = None

def _get_european_df():
    global _european_df
    if _european_df is None:
        _european_df = load_european_data(EUROPEAN_DIR)
    return _european_df


def _load_model(name: str):
    path = os.path.join(MODELS_DIR, name)
    with open(path, "rb") as f:
        return pickle.load(f)


_result_model = None
_goals_model  = None


def _get_models():
    global _result_model, _goals_model
    if _result_model is None:
        _result_model = _load_model("model_result.pkl")
    if _goals_model is None:
        _goals_model = _load_model("model_goals.pkl")
    return _result_model, _goals_model


# ── Training imputation medians ───────────────────────────────────────────────
# Written by train.py at fit time (pre-CAL rows only). Serving MUST fill NaN
# with the SAME values the model saw in training — a 0.0 where training used
# median 4.2 makes a data-poor team look like the worst attack in history.
_impute_medians: Optional[dict] = None


def get_impute_medians() -> dict:
    global _impute_medians
    if _impute_medians is None:
        import json
        path = os.path.join(MODELS_DIR, "impute_medians.json")
        try:
            with open(path) as f:
                _impute_medians = {k: float(v) for k, v in json.load(f).items()}
        except Exception:
            _impute_medians = {}   # pre-refit models: fall back to legacy defaults
    return _impute_medians


def reload_predict_models() -> None:
    """
    Reset all module-level singletons so the next call reloads from disk.
    Call this after a retrain so the running process picks up the new models.
    """
    global _result_model, _goals_model, _DRAW_ALPHA, _BTTS_THRESHOLD, _european_df, _impute_medians
    _result_model    = None
    _goals_model     = None
    _DRAW_ALPHA      = None
    _BTTS_THRESHOLD  = None
    _european_df     = None
    _impute_medians  = None
    import logging
    logging.getLogger("predict").info("[predict] Model singletons cleared — will reload on next predict call.")


# ── Market anchoring — REMOVED (2026-06-17) ───────────────────────────────────
# Predictions are now 100% market-independent by directive. The served 1×2/Over
# probabilities are the pure model output (calibration + draw blend only). The
# bookmaker is used solely for downstream comparison (EV/value gate, ROI vs
# sharps), never to shift our numbers. anchor_to_market() was deleted; callers
# now serve the raw model probabilities directly.


def _confidence(max_result_prob: float, over_prob: float = 0.5) -> str:
    """
    Composite confidence based on BOTH result and goals certainty.

    Result certainty  = max(home_win, draw, away_win)
    Goals certainty   = |over_prob - 0.5| × 2   (0 = pure 50/50, 1 = certain)

    High requires the result to be clear AND the O/U not to be near-random.
    A match with 57% home-win but 46% Over is NOT high confidence — we're
    guessing on goals.  Medium is the honest rating there.
    """
    goals_certainty = abs(over_prob - 0.5) * 2   # 0.0 – 1.0

    # High: result clearly favours one outcome AND goals have meaningful signal
    # goals_certainty >= 0.10 means over_prob ≤ 0.45 or ≥ 0.55 (5pp from 50/50)
    if max_result_prob >= 0.55 and goals_certainty >= 0.10:
        return "high"
    if max_result_prob >= 0.42:
        return "medium"
    return "low"


# Leagues whose predictions are always served as "low" confidence, regardless
# of how sure the model looks. Club friendlies are cross-league exhibition
# games (heavy rotation, 3×30' halves, trialists) — the training distribution
# doesn't cover them, so an inflated confidence label would be dishonest.
LOW_CONFIDENCE_LEAGUES = {"ClubFriendly"}


def confidence_for(
    league: "str | None",
    max_result_prob: float,
    over_prob: float = 0.5,
    has_history: bool = True,
) -> str:
    """League-aware confidence: forced 'low' for LOW_CONFIDENCE_LEAGUES,
    otherwise the composite _confidence formula.

    `has_history=False` also forces 'low'. A fixture where a side has no CSV
    history (UEFA qualifying minnows: Vestri, Floriana, Inter Club d'Escaldes)
    is predicted entirely from neutral default features, so every such tie
    collapses onto the same handful of probabilities. Labelling that "medium" —
    let alone "high" — would be dishonest.
    """
    if league in LOW_CONFIDENCE_LEAGUES or not has_history:
        return "low"
    return _confidence(max_result_prob, over_prob)


def predict_match(
    history_df: pd.DataFrame,
    home_team: str,
    away_team: str,
    match_date: date,
    league: str = "Unknown",
    match_id: Optional[int] = None,
) -> dict:
    """
    Compute a prediction for a single (upcoming) match.

    history_df: normalised DataFrame of past matches (from features.load_raw_csvs).
                Must NOT include the match being predicted.
    """
    result_model, goals_model = _get_models()

    # Build a synthetic row for the target match so build_features can
    # compute the Elo / rolling-stat snapshot correctly.
    target_row = pd.DataFrame([{
        "Date":       pd.Timestamp(match_date),
        "home_team":  home_team,
        "away_team":  away_team,
        "home_goals": 0,   # dummy — not used for the snapshot
        "away_goals": 0,   # dummy
        "League":     league,
    }])

    # Only keep history strictly before the match date to avoid leakage
    hist = history_df[history_df["Date"] < pd.Timestamp(match_date)].copy()
    combined = pd.concat([hist, target_row], ignore_index=True)
    combined = build_features(combined, european_df=_get_european_df())

    # Last row is our target — keep all FEATURE_COLS for downstream slicing
    feat_row = combined.iloc[[-1]][FEATURE_COLS]

    # Impute NaN values. Pi-Ratings start at 0.0 so they're never NaN.
    # Rolling stats may be NaN for new teams with insufficient history.
    _fill = {
        # Rolling stats
        "h_goals_scored_5":   1.5, "h_goals_conceded_5": 1.5,
        "a_goals_scored_5":   1.5, "a_goals_conceded_5": 1.5,
        "h_home_scored_5":    1.5, "h_home_conceded_5":  1.5,
        "a_away_scored_5":    1.5, "a_away_conceded_5":  1.5,
        "h_form_5":           1.0, "a_form_5":           1.0,
        "h_goals_scored_10":   1.5, "h_goals_conceded_10": 1.5,
        "a_goals_scored_10":   1.5, "a_goals_conceded_10": 1.5,
        "h_home_scored_10":    1.5, "h_home_conceded_10":  1.5,
        "a_away_scored_10":    1.5, "a_away_conceded_10":  1.5,
        "h_form_10":           1.0, "a_form_10":           1.0,
        "h_goal_diff_5":  0.0, "a_goal_diff_5":  0.0,
        "h_goal_diff_10": 0.0, "a_goal_diff_10": 0.0,
        "expected_home_goals_5":  1.5, "expected_away_goals_5":  1.5, "expected_goals_5":  3.0,
        "expected_home_goals_10": 1.5, "expected_away_goals_10": 1.5, "expected_goals_10": 3.0,
        "h_total_goals_5": 3.0, "a_total_goals_5": 3.0,
        "h_total_goals_10":3.0, "a_total_goals_10":3.0,
        "h_over25_rate_5": 0.5, "a_over25_rate_5": 0.5,
        "h_over25_rate_10":0.5, "a_over25_rate_10":0.5,
        "h_draw_rate_5": 0.26,  "a_draw_rate_5": 0.26,
        "h_draw_rate_10":0.26,  "a_draw_rate_10":0.26,
        # Shots — 0 = data not available
        "h_shots_ot_5": 0.0, "h_shots_otc_5": 0.0,
        "a_shots_ot_5": 0.0, "a_shots_otc_5": 0.0,
        # Elo
        "h_elo": ELO_START, "a_elo": ELO_START,
        "elo_diff": 0.0, "elo_home_win_prob": 0.5,
        # Pi-Ratings — new team defaults (0 = baseline, exp goals = 1.5 each)
        "h_pi_att": 0.0, "h_pi_def": 0.0,
        "a_pi_att": 0.0, "a_pi_def": 0.0,
        "pi_att_diff": 0.0, "pi_def_diff": 0.0,
        "pi_exp_home": 1.5, "pi_exp_away": 1.5,
        "pi_exp_diff": 0.0, "pi_exp_total": 3.0,
        # H2H
        "h2h_home_wins": 0, "h2h_away_wins": 0, "h2h_draws": 0, "h2h_draw_rate": 0.26,
        # Season phase — mid-season as default
        "season_week": 15, "season_phase": 2, "days_since_season_start": 105,
        # European — 0 = not in Europe
        "h_eur_fatigue": 0.0, "a_eur_fatigue": 0.0,
        "h_eur_away":    0.0, "a_eur_away":    0.0,
        "h_eur_result":  0.0, "a_eur_result":  0.0,
        # Poisson — neutral league-average defaults
        "poisson_lambda_home":  1.5,  "poisson_lambda_away":  1.2,
        "poisson_home_attack":  1.0,  "poisson_away_defense": 1.0,
        "poisson_home_win":     0.44, "poisson_draw":         0.26,
        "poisson_away_win":     0.30, "poisson_over_2_5":     0.50,
        "poisson_btts":         0.50,
        # Draw-balance features
        "goals_asymmetry_5":      0.0,
        "combined_draw_tendency": 0.26,
        "pi_closeness":           0.5,
        "market_draw_edge":       0.0,
        "low_total_xg":           0.0,
        "elo_closeness":          0.5,
    }
    # Training medians override the legacy literals above — serving must fill
    # NaN with the SAME values the model was trained with (impute_medians.json,
    # written by train.py from pre-CAL rows). Legacy literals remain the
    # fallback for models trained before the artifact existed.
    _fill.update(get_impute_medians())
    feat_row = feat_row.fillna(_fill)

    # Slice to model-specific feature lists
    feat_result = feat_row[RESULT_FEATURE_COLS]
    feat_goals  = feat_row[GOALS_FEATURE_COLS]

    # Raw XGBoost probabilities
    result_probs = result_model.predict_proba(feat_result)[0]  # [HomeWin, Draw, AwayWin]
    goals_probs  = goals_model.predict_proba(feat_goals)[0]    # [Under, Over]
    raw_over     = float(goals_probs[1])

    # Apply isotonic calibration (identity pass-through when files not found)
    result_cals, goals_cal, league_goals_cals = load_calibrators()
    home_win_p, draw_p, away_win_p, over_p = apply_calibration(
        result_probs, raw_over,
        result_cals, goals_cal,
        league=league,
        league_goals_cals=league_goals_cals,
    )

    feat_dict = feat_row.iloc[0].to_dict()

    # Draw specialist blend with auto-tuned alpha
    draw_clf = load_draw_classifier()
    draw_cal = load_draw_calibrator()
    if draw_clf is not None:
        draw_raw = predict_draw_prob(draw_clf, feat_dict)
        if draw_raw is not None:
            draw_clf_cal = apply_draw_calibration(draw_cal, draw_raw)
            home_win_p, draw_p, away_win_p = blend_draw_probability(
                home_win_p, draw_p, away_win_p,
                draw_clf_cal,
                alpha=_get_draw_alpha(),
            )

    # Second-stage rolling recalibration (no-op until scripts/recalibrate.py runs)
    home_win_p, draw_p, away_win_p, over_p = apply_recent_calibration(
        home_win_p, draw_p, away_win_p, over_p
    )

    # NOTE: served probabilities are the PURE model output — no market anchoring.
    # By directive the bookmaker never influences our predictions; it is used only
    # downstream for comparison (EV/value gate, ROI vs sharps).

    # BTTS classifier (replaces raw Poisson BTTS)
    btts_clf = load_btts_classifier()
    btts_cal = load_btts_calibrator()
    btts_raw = predict_btts_prob(btts_clf, feat_dict)
    if btts_raw is not None:
        gg_prob = apply_btts_calibration(btts_cal, btts_raw)
    else:
        gg_prob = float(feat_dict.get("poisson_btts", 0.5))

    goals_prediction = "OVER" if over_p >= 0.5 else "UNDER"
    btts_prediction  = "GG" if gg_prob >= _get_btts_threshold() else "NG"
    max_result_prob  = max(home_win_p, draw_p, away_win_p)

    return {
        "match_id":    match_id,
        "home_team":   home_team,
        "away_team":   away_team,
        "league":      league,
        "match_date":  str(match_date),
        "win_probabilities": {
            "home_win": round(home_win_p, 4),
            "draw":     round(draw_p, 4),
            "away_win": round(away_win_p, 4),
        },
        "goals": {
            "over_2_5_probability": round(over_p, 4),
            "prediction":           goals_prediction,
        },
        "btts": {
            "gg_probability": round(gg_prob, 4),
            "prediction":     btts_prediction,
        },
        # Poisson λ — persisted with the prediction so serve-time extended stats
        # (O/U 1.5/3.5, correct scores, combos) work for on-the-fly rows too.
        "poisson_lambda_home": round(float(feat_dict.get("poisson_lambda_home", 1.5)), 4),
        "poisson_lambda_away": round(float(feat_dict.get("poisson_lambda_away", 1.2)), 4),
        "model_version": MODEL_VERSION,
        "confidence":    confidence_for(league, max_result_prob, over_p),
    }
