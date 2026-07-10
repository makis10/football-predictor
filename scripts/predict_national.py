"""
Generate predictions for upcoming international matches.

Loads trained national team models and snapshot from models/national/,
then predicts for all upcoming fixtures in results.csv (score = NA).

Usage:
  python scripts/predict_national.py                      # all upcoming
  python scripts/predict_national.py --tournament "FIFA World Cup"
  python scripts/predict_national.py --from 2026-06-11
  python scripts/predict_national.py --csv out.csv        # export to CSV
  python scripts/predict_national.py --top 20             # only top 20 by confidence
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT       = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import json

from backend.app.ml.national.features import (
    load_results, compute_match_features, classify_tournament,
    NATIONAL_FEATURE_COLS, NATIONAL_OPTIONAL_COLS, DRAW_FEATURE_COLS,
)
from backend.app.ml.national.train import blend_draw_probability

DATA_DIR   = ROOT / "backend" / "data" / "raw" / "international"
MODELS_DIR = ROOT / "backend" / "data" / "models" / "national"

# Elo-blend parameters. FITTED on the calibration window by
# scripts/fit_national_blend.py → models/national/blend.json; the literals
# below are only the pre-fit fallbacks (the old hand-picked values).
_BLEND_DEFAULTS = {"elo_blend_w": 0.5, "scale": 110.0, "draw_base": 0.26, "draw_decay": 0.7}


def _load_blend() -> dict:
    path = MODELS_DIR / "blend.json"
    try:
        with open(path) as f:
            d = json.load(f)
        return {k: float(d.get(k, v)) for k, v in _BLEND_DEFAULTS.items()}
    except FileNotFoundError:
        return dict(_BLEND_DEFAULTS)


BLEND = _load_blend()
ELO_BLEND_W = BLEND["elo_blend_w"]


def _load_models() -> dict:
    objects = {}
    for fname in ["model_result.pkl", "model_goals.pkl", "model_btts.pkl",
                  "model_draw_clf.pkl",
                  "calibrator_result.pkl", "calibrator_goals.pkl", "calibrator_btts.pkl",
                  "calibrator_draw_clf.pkl",
                  "snapshot.pkl"]:
        path = MODELS_DIR / fname
        if not path.exists():
            print(f"[error] Missing {path}. Run: python scripts/train_national.py")
            sys.exit(1)
        with open(path, "rb") as f:
            objects[fname.replace(".pkl", "").replace("calibrator_", "cal_")] = pickle.load(f)
    # Load draw blend alpha
    alpha_path = MODELS_DIR / "draw_alpha.json"
    if alpha_path.exists():
        with open(alpha_path) as f:
            objects["draw_alpha"] = json.load(f).get("draw_blend_alpha", 0.35)
    else:
        objects["draw_alpha"] = 0.35
    return objects


def _apply_calibration_result(ensemble, calibrators, X):
    raw = ensemble.predict_proba(X)
    cal = np.zeros_like(raw)
    for c, iso in enumerate(calibrators):
        cal[:, c] = iso.predict(raw[:, c])
    row_sum = cal.sum(axis=1, keepdims=True)
    cal /= np.maximum(row_sum, 1e-9)
    return cal


def _apply_calibration_binary(ensemble, calibrator, X):
    raw = ensemble.predict_proba(X)[:, 1]
    return calibrator.predict(raw)


def _confidence_label(p_max: float) -> str:
    if p_max >= 0.65: return "HIGH"
    if p_max >= 0.55: return "MEDIUM"
    return "LOW"


def _feats_df(feat: dict) -> pd.DataFrame:
    row = {c: feat.get(c, np.nan) for c in NATIONAL_FEATURE_COLS}
    return pd.DataFrame([row])


def _draw_feats_df(feat: dict) -> pd.DataFrame:
    row = {c: feat.get(c, np.nan) for c in DRAW_FEATURE_COLS}
    return pd.DataFrame([row])


def predict_fixture(
    models: dict,
    home_team: str,
    away_team: str,
    tournament: str,
    neutral: bool,
    match_date: pd.Timestamp,
) -> dict:
    snapshot = models["snapshot"]
    feat = compute_match_features(snapshot, home_team, away_team, tournament, neutral, match_date)
    X  = _feats_df(feat)
    Xd = _draw_feats_df(feat)

    # Result (raw calibrated)
    cal_result = _apply_calibration_result(
        models["model_result"], models["cal_result"], X
    )[0]
    p_home_raw, p_draw_raw, p_away_raw = float(cal_result[0]), float(cal_result[1]), float(cal_result[2])

    # Draw specialist blend
    draw_raw = models["model_draw_clf"].predict_proba(Xd)[0, 1]
    draw_cal = float(models["cal_draw_clf"].predict([draw_raw])[0])
    alpha = models.get("draw_alpha", 0.35)
    p_home, p_draw, p_away = blend_draw_probability(p_home_raw, p_draw_raw, p_away_raw,
                                                     draw_cal, alpha=alpha)

    # Sharpen toward the talent-Elo. The trained international model is flat —
    # it converts even a strong Elo gap into a near-toss-up with inflated draws
    # (e.g. France +208 Elo → 33/37/30 raw). Blend its 1×2 with an Elo-derived
    # 1×2 so clear favourites look like favourites. ELO_BLEND_W on the Elo side.
    from backend.app.ml.national.features import elo_three_way, HOME_ADV
    adj_diff = feat["h_elo"] - feat["a_elo"] + (0.0 if neutral else HOME_ADV)
    eh, ed, ea = elo_three_way(adj_diff, scale=BLEND["scale"],
                               draw_base=BLEND["draw_base"], draw_decay=BLEND["draw_decay"])
    w = ELO_BLEND_W
    p_home = (1 - w) * p_home + w * eh
    p_draw = (1 - w) * p_draw + w * ed
    p_away = (1 - w) * p_away + w * ea
    _s = p_home + p_draw + p_away
    p_home, p_draw, p_away = p_home / _s, p_draw / _s, p_away / _s

    # Goals
    p_over = float(_apply_calibration_binary(models["model_goals"], models["cal_goals"], X)[0])

    # BTTS
    p_btts = float(_apply_calibration_binary(models["model_btts"], models["cal_btts"], X)[0])

    prediction = max(["H", "D", "A"], key=lambda x: {"H": p_home, "D": p_draw, "A": p_away}[x])
    p_max = max(p_home, p_draw, p_away)

    return {
        "date":         match_date.date() if hasattr(match_date, "date") else match_date,
        "home_team":    home_team,
        "away_team":    away_team,
        "tournament":   tournament,
        "neutral":      neutral,
        "p_home":       round(p_home, 4),
        "p_draw":       round(p_draw, 4),
        "p_away":       round(p_away, 4),
        "prediction":   prediction,
        "confidence":   _confidence_label(p_max),
        "p_over25":     round(p_over, 4),
        "p_btts":       round(p_btts, 4),
        "h_elo":        round(feat.get("h_elo", 0), 1),
        "a_elo":        round(feat.get("a_elo", 0), 1),
    }


def print_predictions(rows: list[dict], sort_by: str = "confidence") -> None:
    df = pd.DataFrame(rows)
    if sort_by == "confidence":
        df["_pmax"] = df[["p_home", "p_draw", "p_away"]].max(axis=1)
        df = df.sort_values(["date", "_pmax"], ascending=[True, False])
        df = df.drop(columns="_pmax")

    hdr = (f"{'Date':<12} {'Home team':<25} {'Away team':<25} "
           f"{'H':>6} {'D':>6} {'A':>6}  {'Pred':<5} {'Conf':<7}  "
           f"{'O2.5':>5} {'BTTS':>5}")
    sep = "─" * len(hdr)
    print(f"\n{sep}")
    print(hdr)
    print(sep)

    current_group = None
    for _, r in df.iterrows():
        group = str(r["date"])[:10]
        if group != current_group:
            if current_group is not None:
                print()
            current_group = group

        print(
            f"{str(r['date']):<12} {r['home_team']:<25} {r['away_team']:<25} "
            f"{r['p_home']:>6.3f} {r['p_draw']:>6.3f} {r['p_away']:>6.3f}  "
            f"{'['+r['prediction']+']':<5} {r['confidence']:<7}  "
            f"{r['p_over25']:>5.3f} {r['p_btts']:>5.3f}"
        )
    print(sep)
    print(f"\n{len(df)} fixtures predicted.\n")


def save_to_db(predictions: list[dict]) -> None:
    """Upsert predictions into national_predictions table."""
    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    from backend.app.database import SessionLocal
    from backend.app.models.national_prediction import NationalPrediction
    from sqlalchemy import and_

    db = SessionLocal()
    inserted = updated = 0
    try:
        for pred in predictions:
            match_date = str(pred["date"])
            existing = db.query(NationalPrediction).filter(
                and_(
                    NationalPrediction.match_date == match_date,
                    NationalPrediction.home_team  == pred["home_team"],
                    NationalPrediction.away_team  == pred["away_team"],
                )
            ).first()

            if existing:
                # Served columns ALWAYS = pure model output (no market anchoring,
                # per 2026-06-17 directive). raw_* mirror the served probs; the
                # market is used only downstream for the EV/value comparison.
                existing.raw_home_prob = pred["p_home"]
                existing.raw_draw_prob = pred["p_draw"]
                existing.raw_away_prob = pred["p_away"]
                existing.raw_over_prob = pred["p_over25"]
                existing.home_win_prob = pred["p_home"]
                existing.draw_prob     = pred["p_draw"]
                existing.away_win_prob = pred["p_away"]
                existing.prediction    = pred["prediction"]
                existing.confidence    = pred["confidence"]
                existing.market_anchored = False
                existing.over_2_5_prob = pred["p_over25"]
                existing.btts_prob     = pred["p_btts"]
                existing.h_elo         = pred.get("h_elo")
                existing.a_elo         = pred.get("a_elo")
                updated += 1
            else:
                row = NationalPrediction(
                    match_date    = match_date,
                    home_team     = pred["home_team"],
                    away_team     = pred["away_team"],
                    tournament    = pred["tournament"],
                    neutral       = bool(pred.get("neutral", True)),
                    home_win_prob = pred["p_home"],
                    draw_prob     = pred["p_draw"],
                    away_win_prob = pred["p_away"],
                    raw_home_prob = pred["p_home"],
                    raw_draw_prob = pred["p_draw"],
                    raw_away_prob = pred["p_away"],
                    raw_over_prob = pred["p_over25"],
                    prediction    = pred["prediction"],
                    confidence    = pred["confidence"],
                    over_2_5_prob = pred["p_over25"],
                    btts_prob     = pred["p_btts"],
                    h_elo         = pred.get("h_elo"),
                    a_elo         = pred.get("a_elo"),
                )
                db.add(row)
                inserted += 1
        db.commit()
        print(f"  DB: {inserted} inserted, {updated} updated")
    except Exception as e:
        db.rollback()
        print(f"  [warn] DB save failed: {e}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="National team match predictions")
    parser.add_argument("--tournament", type=str, default=None,
                        help="Filter by tournament name (partial match)")
    parser.add_argument("--from",      dest="from_date", type=str, default=None,
                        help="Only fixtures from this date (YYYY-MM-DD)")
    parser.add_argument("--to",        dest="to_date",   type=str, default=None,
                        help="Only fixtures up to this date (YYYY-MM-DD)")
    parser.add_argument("--top",       type=int, default=None,
                        help="Show only top N by max probability")
    parser.add_argument("--csv",       type=str, default=None,
                        help="Export results to CSV")
    parser.add_argument("--save-db",   action="store_true",
                        help="Upsert predictions into national_predictions DB table")
    args = parser.parse_args()

    print("Loading models …")
    models = _load_models()
    print("  Models loaded.")

    print("Loading upcoming fixtures …")
    _, upcoming = load_results(DATA_DIR)
    print(f"  {len(upcoming)} upcoming fixtures found")

    # Filters
    if args.tournament:
        mask = upcoming["tournament"].str.contains(args.tournament, case=False, na=False)
        upcoming = upcoming[mask]
    if args.from_date:
        upcoming = upcoming[upcoming["date"] >= pd.Timestamp(args.from_date)]
    if args.to_date:
        upcoming = upcoming[upcoming["date"] <= pd.Timestamp(args.to_date)]

    print(f"  {len(upcoming)} fixtures after filters\n")

    if len(upcoming) == 0:
        print("No fixtures to predict.")
        return

    print("Computing predictions …")
    results = []
    for _, row in upcoming.iterrows():
        try:
            pred = predict_fixture(
                models,
                home_team  = row["home_team"],
                away_team  = row["away_team"],
                tournament = row["tournament"],
                neutral    = bool(row["neutral"]),
                match_date = pd.Timestamp(row["date"]),
            )
            results.append(pred)
        except Exception as e:
            print(f"  [warn] {row['home_team']} vs {row['away_team']}: {e}")

    if args.top:
        results_df = pd.DataFrame(results)
        results_df["_pmax"] = results_df[["p_home", "p_draw", "p_away"]].max(axis=1)
        results_df = results_df.nlargest(args.top, "_pmax").drop(columns="_pmax")
        results = results_df.to_dict("records")

    print_predictions(results)

    if args.csv:
        pd.DataFrame(results).to_csv(args.csv, index=False)
        print(f"Exported → {args.csv}")

    if args.save_db:
        print("Saving to DB …")
        save_to_db(results)


if __name__ == "__main__":
    main()
