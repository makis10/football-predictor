"""
Compute and cache ML predictions for all upcoming matches that don't have one.

Fast batch mode: builds team state (Elo, Pi-Ratings, rolling stats) ONCE from
the full history, then computes features for all upcoming fixtures in O(1)
each instead of replaying 32k rows per match.

Uses INSERT ... ON CONFLICT DO NOTHING so it is safe to run concurrently
with the backend API and safe to re-run at any time.

Usage:
  docker compose exec backend python scripts/compute_predictions.py
  docker compose exec backend python scripts/compute_predictions.py --force
    # --force: delete and recompute predictions for FUTURE matches only
    #          (match_date > today). Today's matches are never touched —
    #          once a match has kicked off the stored prediction is sacred.
"""
from __future__ import annotations

import argparse
import os
import sys
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _PROJECT_ROOT)

import numpy as np
import pandas as pd
from datetime import date
from sqlalchemy import select, text, delete

from backend.app.database import SessionLocal, engine
from backend.app.models.match import Match
from backend.app.models.prediction import Prediction
from backend.app.models.odds_history import OddsHistory
from backend.app.ml.features import (
    load_raw_csvs, build_team_snapshot, compute_match_features,
    FEATURE_COLS, RESULT_FEATURE_COLS, GOALS_FEATURE_COLS,
)
from backend.app.ml.european import load_european_data, EUROPEAN_DIR
from backend.app.ml.predict import SoftVoteEnsemble, _get_models, confidence_for, _get_draw_alpha, _get_btts_threshold
from backend.app.ml.calibration import load_calibrators, apply_calibration, apply_recent_calibration
from backend.app.ml.draw_classifier import (
    load_draw_classifier, load_draw_calibrator,
    predict_draw_prob, apply_draw_calibration, blend_draw_probability,
)
from backend.app.ml.btts_classifier import (
    load_btts_classifier, load_btts_calibrator,
    predict_btts_prob, apply_btts_calibration,
)
from backend.app.ml.odds_analysis_service import fetch_all_league_odds, _teams_match, _best_ev_market, _compute_ev, shrunk_ev

MODEL_VERSION = "1.0.0"

parser = argparse.ArgumentParser(description="Compute ML predictions for upcoming matches")
parser.add_argument(
    "--force", action="store_true",
    help="Delete existing predictions for upcoming matches before recomputing (use after retraining)",
)
parser.add_argument(
    "--force-today", action="store_true",
    help=(
        "Delete and recompute predictions for today's matches that have not yet kicked off. "
        "Run 1-2h before kick-off to use closing-line odds (sharper market signal)."
    ),
)
args = parser.parse_args()

# ── Optionally clear existing predictions ─────────────────────────────────────
if args.force:
    db = SessionLocal()
    # Only delete predictions for matches that have NOT kicked off yet.
    # match_date > today  →  strictly future fixtures are safe to recompute.
    # match_date == today →  match may already be in progress; we keep the
    #                        pre-kick-off prediction so accuracy tracking is
    #                        not corrupted by mid-game retraining.
    future_ids = db.scalars(
        select(Match.id)
        .where(Match.result.is_(None))
        .where(Match.match_date > date.today())   # strictly tomorrow onwards
    ).all()
    deleted = db.execute(
        delete(Prediction).where(Prediction.match_id.in_(future_ids))
    )
    db.commit()
    db.close()
    print(f"--force: deleted {deleted.rowcount} predictions "
          f"(future only — today's matches untouched)", flush=True)

if args.force_today:
    from datetime import datetime, timezone, timedelta
    # Refresh predictions for today's matches that have not kicked off yet.
    # Grace window: keep any match whose kick-off was within the last 30 minutes
    # (it may already be in progress — don't corrupt accuracy tracking).
    #
    # NOTE: compare full datetimes, not time-of-day. Taking .time() of
    # (now − 30min) wraps around midnight (e.g. at 00:15 UTC the cutoff became
    # 23:45 "today"), which silently excluded almost every match.
    cutoff_dt = datetime.now(timezone.utc) - timedelta(minutes=30)
    today = date.today()
    db = SessionLocal()
    candidates = db.execute(
        select(Match.id, Match.kickoff_time)
        .where(Match.result.is_(None))
        .where(Match.match_date == today)
    ).all()
    today_ids = [
        mid for mid, ko in candidates
        if ko is None
        or datetime.combine(today, ko, tzinfo=timezone.utc) > cutoff_dt
    ]
    deleted = db.execute(
        delete(Prediction).where(Prediction.match_id.in_(today_ids))
    )
    db.commit()
    db.close()
    print(f"--force-today: deleted {deleted.rowcount} predictions "
          f"for today's unstarted matches (cutoff UTC {cutoff_dt:%H:%M})", flush=True)

# ── Fetch matches that need predictions ───────────────────────────────────────
db = SessionLocal()
unpredicted = db.scalars(
    select(Match)
    .outerjoin(Prediction, Prediction.match_id == Match.id)
    .where(Match.result.is_(None))
    .where(Match.match_date >= date.today())
    .where(Prediction.id.is_(None))
    .order_by(Match.match_date, Match.id)
).all()

match_snapshots = [
    (m.id, m.home_team, m.away_team, m.match_date, m.league)
    for m in unpredicted
]
db.close()

print(f"Matches needing predictions: {len(match_snapshots)}", flush=True)
if not match_snapshots:
    print("Nothing to do.")
    sys.exit(0)

# ── Build odds drift map from odds_history (one query) ────────────────────────
# For each match, compute drift = current_raw_odds - earliest_stored_odds.
# Negative drift = odds shortened = sharp money (steam move).
# Matches with no history get {0.0, 0.0, 0.0, 0.0} (neutral baseline).
match_ids = [mid for mid, *_ in match_snapshots]
odds_drift_by_match: dict[int, dict] = {}
if match_ids:
    db2 = SessionLocal()
    from sqlalchemy import func as _func
    # Earliest snapshot per match
    first_rows = db2.execute(
        select(
            OddsHistory.match_id,
            _func.min(OddsHistory.fetched_at).label("first_at"),
        )
        .where(OddsHistory.match_id.in_(match_ids))
        .group_by(OddsHistory.match_id)
    ).all()
    first_times = {r.match_id: r.first_at for r in first_rows}

    # Fetch first and latest snapshots per match in one query
    if first_times:
        all_history = db2.execute(
            select(OddsHistory)
            .where(OddsHistory.match_id.in_(list(first_times.keys())))
        ).scalars().all()

        from collections import defaultdict as _dd
        _by_match: dict = _dd(list)
        for row in all_history:
            _by_match[row.match_id].append(row)

        for mid, rows in _by_match.items():
            rows_sorted = sorted(rows, key=lambda r: r.fetched_at)
            first, latest = rows_sorted[0], rows_sorted[-1]
            # Only compute drift when we have at least 2 snapshots (meaningful movement)
            if len(rows_sorted) >= 2:
                odds_drift_by_match[mid] = {
                    "drift_home": (latest.home_odds or 0) - (first.home_odds or 0) if (latest.home_odds and first.home_odds) else 0.0,
                    "drift_draw": (latest.draw_odds or 0) - (first.draw_odds or 0) if (latest.draw_odds and first.draw_odds) else 0.0,
                    "drift_away": (latest.away_odds or 0) - (first.away_odds or 0) if (latest.away_odds and first.away_odds) else 0.0,
                    "drift_over": (latest.over_odds or 0) - (first.over_odds or 0) if (latest.over_odds and first.over_odds) else 0.0,
                }
    db2.close()
    n_drift = sum(1 for v in odds_drift_by_match.values() if any(abs(v[k]) > 0.01 for k in v))
    print(f"Odds drift: {len(odds_drift_by_match)} matches with history, {n_drift} with movement >0.01", flush=True)

# ── Load history + build team snapshot ONCE ───────────────────────────────────
RAW_DIR = os.path.join(_PROJECT_ROOT, "backend", "data", "raw")
print("Loading history …", flush=True)
history_df = load_raw_csvs(RAW_DIR)
print(f"History: {len(history_df):,} rows", flush=True)

print("Building team snapshot …", flush=True)
snapshot = build_team_snapshot(history_df)
print("Snapshot ready. Loading European data …", flush=True)

european_df = load_european_data(EUROPEAN_DIR)
print(f"European fixtures: {len(european_df) if european_df is not None else 0}", flush=True)

# ── Load models ───────────────────────────────────────────────────────────────
print("Loading models …", flush=True)
result_model, goals_model = _get_models()
result_cals, goals_cal, league_goals_cals = load_calibrators()
draw_clf  = load_draw_classifier()
draw_cal  = load_draw_calibrator()
btts_clf  = load_btts_classifier()
btts_cal  = load_btts_calibrator()
print("Models loaded. Computing predictions …", flush=True)

# ── Fetch live bookmaker odds (one API call per league) ───────────────────────
# market_home_prob and market_away_prob are the #1 and #2 most important
# features by XGBoost importance. Fetching live odds at prediction time
# instead of using static defaults gives the model its most powerful signal.
print("Fetching live bookmaker odds …", flush=True)
leagues_needed = list({league for _, _, _, _, league in match_snapshots})

# odds_by_league: league → list of {api_home, api_away, fair_probs}
odds_by_league: dict[str, list] = {}
for league in leagues_needed:
    games = fetch_all_league_odds(league)
    odds_by_league[league] = games
    print(f"  {league}: {len(games)} games with odds", flush=True)


def _lookup_odds(league: str, home_team: str, away_team: str) -> "dict | None":
    """Find fair_probs (for ML features) + raw odds (for ROI storage) by fuzzy team match."""
    for entry in odds_by_league.get(league, []):
        if _teams_match(entry["api_home"], home_team) and \
           _teams_match(entry["api_away"], away_team):
            fp = entry["fair_probs"]
            ro = entry.get("raw_odds", {})
            # Return only if we have at least 1x2 data
            if fp.get("home_win") and fp.get("away_win"):
                return {
                    # Fair probabilities — injected as ML features
                    "home_win": fp.get("home_win"),
                    "draw":     fp.get("draw"),
                    "away_win": fp.get("away_win"),
                    "over_2_5": fp.get("over_2_5"),
                    "btts_yes": fp.get("btts_yes"),
                    "btts_no":  fp.get("btts_no"),
                    # Raw decimal odds (with vig) — stored for ROI/EV tracking
                    "raw_home":     ro.get("home_win"),
                    "raw_draw":     ro.get("draw"),
                    "raw_away":     ro.get("away_win"),
                    "raw_over":     ro.get("over_2_5"),
                    "raw_btts_yes": ro.get("btts_yes"),
                    "raw_btts_no":  ro.get("btts_no"),
                }
    print(f"  [warn] no odds match for {home_team} vs {away_team} in {league} — market features will be NaN", flush=True)
    return None


# ── Impute defaults for missing rolling stats (new teams / no history) ────────
DEFAULTS = {
    "h_goals_scored_5": 1.5, "h_goals_conceded_5": 1.5,
    "a_goals_scored_5": 1.5, "a_goals_conceded_5": 1.5,
    "h_home_scored_5": 1.5,  "h_home_conceded_5": 1.5,
    "a_away_scored_5": 1.5,  "a_away_conceded_5": 1.5,
    "h_form_5": 1.0,          "a_form_5": 1.0,
    "h_goal_diff_5": 0.0,    "a_goal_diff_5": 0.0,
    "h_goals_scored_10": 1.5, "h_goals_conceded_10": 1.5,
    "a_goals_scored_10": 1.5, "a_goals_conceded_10": 1.5,
    "h_home_scored_10": 1.5,  "h_home_conceded_10": 1.5,
    "a_away_scored_10": 1.5,  "a_away_conceded_10": 1.5,
    "h_form_10": 1.0,         "a_form_10": 1.0,
    "h_goal_diff_10": 0.0,   "a_goal_diff_10": 0.0,
    "expected_home_goals_5": 1.5, "expected_away_goals_5": 1.5, "expected_goals_5": 3.0,
    "expected_home_goals_10": 1.5,"expected_away_goals_10": 1.5,"expected_goals_10": 3.0,
    "h_total_goals_5": 3.0,   "a_total_goals_5": 3.0,
    "h_total_goals_10": 3.0,  "a_total_goals_10": 3.0,
    "h_over25_rate_5": 0.5,   "a_over25_rate_5": 0.5,
    "h_over25_rate_10": 0.5,  "a_over25_rate_10": 0.5,
    "h_draw_rate_5": 0.26,    "a_draw_rate_5": 0.26,
    "h_draw_rate_10": 0.26,   "a_draw_rate_10": 0.26,
    "h_shots_ot_5": 0.0, "h_shots_otc_5": 0.0,
    "a_shots_ot_5": 0.0, "a_shots_otc_5": 0.0,
    # xG defaults — league median (top-5 leagues average ~1.35 xG per team)
    "h_xg_scored_5": 1.35,   "h_xg_conceded_5": 1.35,
    "a_xg_scored_5": 1.35,   "a_xg_conceded_5": 1.35,
    "h_xg_scored_10": 1.35,  "h_xg_conceded_10": 1.35,
    "a_xg_scored_10": 1.35,  "a_xg_conceded_10": 1.35,
    # Note: market_home_prob / market_draw_prob / market_away_prob / market_over_prob
    # are now injected from live The Odds API data via market_probs= parameter.
    # No default here — XGBoost handles NaN natively when odds are unavailable.

    # H2H draw rate and season phase defaults
    "h2h_draw_rate": 0.26,
    "season_week": 15, "season_phase": 2, "days_since_season_start": 105,
    # Poisson features — neutral league-average defaults for cold-start matches
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
    # Odds movement / steam (0.0 = no movement / not available)
    "odds_drift_home": 0.0, "odds_drift_draw": 0.0,
    "odds_drift_away": 0.0, "odds_drift_over": 0.0,
    "is_steam_home":   0.0, "is_steam_away":   0.0,
    # EWMA momentum defaults (league-average goals, league-average form=1pt/game)
    "h_ewma_scored": 1.5, "h_ewma_conceded": 1.5,
    "a_ewma_scored": 1.5, "a_ewma_conceded": 1.5,
    "h_ewma_form": 1.0,   "a_ewma_form": 1.0,
    # League position defaults (neutral = middle of table)
    "h_league_pos_norm": 0.5, "a_league_pos_norm": 0.5, "league_pos_diff": 0.0,
}

# ── Compute + insert ──────────────────────────────────────────────────────────
ok = skipped = fail = 0

for i, (mid, home, away, match_date, league) in enumerate(match_snapshots, 1):
    try:
        # Live bookmaker odds for this match (None if unavailable)
        live_odds = _lookup_odds(league, home, away)

        feat = compute_match_features(
            snapshot=snapshot,
            home_team=home,
            away_team=away,
            league=league,
            match_date=match_date,
            european_df=european_df,
            market_probs=live_odds,  # injects the #1 and #2 most important features
            odds_movement=odds_drift_by_match.get(mid),
        )

        # Impute NaN values
        for col, default in DEFAULTS.items():
            if col in feat and (feat[col] is None or (isinstance(feat[col], float) and np.isnan(feat[col]))):
                feat[col] = default

        # Build feature rows per model (full row for slicing)
        feat_row        = pd.DataFrame([feat])[FEATURE_COLS]
        feat_row_result = feat_row[RESULT_FEATURE_COLS]
        feat_row_goals  = feat_row[GOALS_FEATURE_COLS]

        # Raw XGBoost probabilities (stored for regression diagnostics)
        result_probs = result_model.predict_proba(feat_row_result)[0]
        goals_probs  = goals_model.predict_proba(feat_row_goals)[0]
        raw_over     = float(goals_probs[1])
        xgb_raw_h    = float(result_probs[0])
        xgb_raw_d    = float(result_probs[1])
        xgb_raw_a    = float(result_probs[2])

        # Apply isotonic calibration (pass-through when calibrators not found)
        home_win_p, draw_p, away_win_p, over_p = apply_calibration(
            result_probs, raw_over,
            result_cals, goals_cal,
            league=league,
            league_goals_cals=league_goals_cals,
        )

        # Draw specialist blend with auto-tuned alpha
        if draw_clf is not None:
            draw_raw = predict_draw_prob(draw_clf, feat)
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

        # Served probabilities = PURE model output — no market anchoring.
        # The bookmaker is used only below, for the EV/value comparison.
        pre_anchor = (home_win_p, draw_p, away_win_p, over_p)

        # BTTS classifier (replaces raw Poisson BTTS)
        btts_raw = predict_btts_prob(btts_clf, feat)
        if btts_raw is not None:
            gg_prob = apply_btts_calibration(btts_cal, btts_raw)
        else:
            gg_prob = float(feat.get("poisson_btts", 0.5))
        btts_prediction = "GG" if gg_prob >= _get_btts_threshold() else "NG"

        goals_prediction = "OVER" if over_p >= 0.5 else "UNDER"
        max_result_prob = max(home_win_p, draw_p, away_win_p)

        # Extract Poisson λ values from the feature dict for later serve-time use
        lambda_home: float | None = feat.get("poisson_lambda_home")
        lambda_away: float | None = feat.get("poisson_lambda_away")
        if lambda_home is not None and (np.isnan(lambda_home) or lambda_home <= 0):
            lambda_home = None
        if lambda_away is not None and (np.isnan(lambda_away) or lambda_away <= 0):
            lambda_away = None

        # ── Value-bet EV computation ──────────────────────────────────────────
        # Uses _compute_ev() + _best_ev_market() — same path as the analysis
        # endpoint — so DB-stored suggestions are consistent with the live page.
        # Includes GG/NG (BTTS) markets alongside 1x2, Over/Under.
        suggested_market: str | None = None
        ev_score: float | None = None
        if live_odds:
            bm_data = {
                "raw_odds": {
                    "home_win":  live_odds.get("raw_home"),
                    "draw":      live_odds.get("raw_draw"),
                    "away_win":  live_odds.get("raw_away"),
                    "over_2_5":  live_odds.get("raw_over"),
                    "btts_yes":  live_odds.get("raw_btts_yes"),
                    "btts_no":   live_odds.get("raw_btts_no"),
                }
            }
            # Pure model probabilities (pre-anchor) — the value gate measures
            # genuine model-vs-market disagreement, then shrinks it itself.
            model_probs_map = {
                "home_win": pre_anchor[0],
                "draw":     pre_anchor[1],
                "away_win": pre_anchor[2],
                "over_2_5": pre_anchor[3],
                "btts":     gg_prob,
            }
            fair_probs = {
                "home_win": live_odds.get("home_win"),
                "draw":     live_odds.get("draw"),
                "away_win": live_odds.get("away_win"),
                "over_2_5": live_odds.get("over_2_5"),
                "btts_yes": live_odds.get("btts_yes"),
                "btts_no":  live_odds.get("btts_no"),
            }
            raw_odds_map = {k: v for k, v in bm_data["raw_odds"].items() if v}

            ev_map = _compute_ev(model_probs_map, bm_data)
            if ev_map:
                suggested_market = _best_ev_market(
                    ev_map, raw_odds_map,
                    fair_probs=fair_probs,
                    model_probs=model_probs_map,
                )
                if suggested_market:
                    # Store the market-shrunk EV — the honest edge estimate the
                    # gate validated, not the inflated raw model EV.
                    market_name = suggested_market.split(" @ ")[0]
                    ev_score = shrunk_ev(market_name, model_probs_map,
                                         fair_probs, raw_odds_map)

    except Exception as e:
        fail += 1
        print(f"  [warn] ML failed for {home} vs {away}: {e}", flush=True)
        continue

    with engine.begin() as conn:
        res = conn.execute(
            text("""
                INSERT INTO predictions
                    (match_id, home_win_prob, draw_prob, away_win_prob,
                     over_2_5_prob, goals_prediction, model_version, confidence,
                     bm_home_odds, bm_draw_odds, bm_away_odds, bm_over_odds,
                     bm_btts_yes_odds, bm_btts_no_odds,
                     suggested_market, ev_score,
                     poisson_lambda_home, poisson_lambda_away,
                     raw_home_prob, raw_draw_prob, raw_away_prob, raw_over_prob,
                     btts_prob, btts_prediction)
                VALUES
                    (:match_id, :home_win_prob, :draw_prob, :away_win_prob,
                     :over_2_5_prob, :goals_prediction, :model_version, :confidence,
                     :bm_home_odds, :bm_draw_odds, :bm_away_odds, :bm_over_odds,
                     :bm_btts_yes_odds, :bm_btts_no_odds,
                     :suggested_market, :ev_score,
                     :poisson_lambda_home, :poisson_lambda_away,
                     :raw_home_prob, :raw_draw_prob, :raw_away_prob, :raw_over_prob,
                     :btts_prob, :btts_prediction)
                ON CONFLICT (match_id) DO NOTHING
            """),
            {
                "match_id":         mid,
                "home_win_prob":    round(home_win_p, 4),
                "draw_prob":        round(draw_p, 4),
                "away_win_prob":    round(away_win_p, 4),
                "over_2_5_prob":    round(over_p, 4),
                "goals_prediction": goals_prediction,
                "model_version":    MODEL_VERSION,
                "confidence":       confidence_for(league, max_result_prob, over_p),
                # Store bookmaker odds for ROI/EV tracking (NULL when unavailable)
                "bm_home_odds":     live_odds.get("raw_home")     if live_odds else None,
                "bm_draw_odds":     live_odds.get("raw_draw")     if live_odds else None,
                "bm_away_odds":     live_odds.get("raw_away")     if live_odds else None,
                "bm_over_odds":     live_odds.get("raw_over")     if live_odds else None,
                "bm_btts_yes_odds": live_odds.get("raw_btts_yes") if live_odds else None,
                "bm_btts_no_odds":  live_odds.get("raw_btts_no")  if live_odds else None,
                "suggested_market":    suggested_market,
                "ev_score":            ev_score,
                "poisson_lambda_home": lambda_home,
                "poisson_lambda_away": lambda_away,
                "raw_home_prob": round(xgb_raw_h, 4),
                "raw_draw_prob": round(xgb_raw_d, 4),
                "raw_away_prob": round(xgb_raw_a, 4),
                "raw_over_prob": round(raw_over,   4),
                "btts_prob":       round(gg_prob, 4),
                "btts_prediction": btts_prediction,
            },
        )
        if res.rowcount == 1:
            ok += 1
        else:
            skipped += 1

        # Value-bet ticket — written ONCE at the first (softest) odds the
        # suggestion appeared at; later recomputes never modify it.
        if suggested_market and live_odds:
            from backend.app.ml.odds_analysis_service import _MARKET_ODDS_KEY, _MARKET_MODEL_KEY
            from backend.app.ml.value_ledger import record_ticket
            _mname = suggested_market.split(" @ ")[0]
            _okey  = _MARKET_ODDS_KEY.get(_mname, "")
            _ticket_odds = {k: v for k, v in {
                "home_win": live_odds.get("raw_home"), "draw": live_odds.get("raw_draw"),
                "away_win": live_odds.get("raw_away"), "over_2_5": live_odds.get("raw_over"),
                "under_2_5": None,
                "btts_yes": live_odds.get("raw_btts_yes"), "btts_no": live_odds.get("raw_btts_no"),
            }.items()}.get(_okey)
            if _ticket_odds:
                _mprob = model_probs_map.get(_MARKET_MODEL_KEY.get(_mname, ""))
                if _mname in ("Under 2.5", "NG") and _mprob is not None:
                    _mprob = 1.0 - _mprob
                if record_ticket(
                    conn, source="club", match_id=mid, market=_mname,
                    odds=_ticket_odds, ev=ev_score, model_prob=_mprob,
                    market_prob=fair_probs.get(_okey),
                ):
                    print(f"  🎫 ticket: {home} vs {away} — {suggested_market}", flush=True)

    if i % 20 == 0:
        print(f"  {i}/{len(match_snapshots)} done "
              f"(inserted={ok} skipped={skipped} failed={fail}) …", flush=True)

print(f"\nDone: {ok} inserted, {skipped} already existed, {fail} ML errors.", flush=True)
