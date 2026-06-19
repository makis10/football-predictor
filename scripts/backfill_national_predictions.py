"""
Backfill historical national-team predictions (out-of-sample only).

For every played international from --from onward, recompute the model's
prediction using ONLY pre-match state (build_features computes features
before the state update — no leakage), then store predicted + actual in
national_predictions. This gives an honest predicted-vs-actual track record
for matches we never predicted live.

IMPORTANT — leakage guard:
  The model is trained on data < 2023 and calibrated on 2023. Only matches
  from 2024-01-01 onward are genuinely out-of-sample. The default --from is
  therefore 2024-01-01; backfilling earlier dates would report optimistic
  (in-sample) accuracy, so it is blocked unless --allow-insample is passed.

Usage:
  docker compose exec backend python scripts/backfill_national_predictions.py
  docker compose exec backend python scripts/backfill_national_predictions.py --from 2025-01-01
  docker compose exec backend python scripts/backfill_national_predictions.py --tournament Friendly
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.ml.national.features import (
    load_results, build_features,
    NATIONAL_FEATURE_COLS, DRAW_FEATURE_COLS,
)
from backend.app.ml.national.train import blend_draw_probability

# Reuse the exact inference path used for live predictions
from scripts.predict_national import (
    DATA_DIR, _load_models,
    _apply_calibration_result, _apply_calibration_binary, _confidence_label,
)

OUT_OF_SAMPLE_START = pd.Timestamp("2024-01-01")
RESULT_LABELS = {0: "H", 1: "D", 2: "A"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill historical national predictions")
    ap.add_argument("--from", dest="from_date", type=str, default="2024-01-01",
                    help="Backfill played matches from this date (YYYY-MM-DD)")
    ap.add_argument("--to", dest="to_date", type=str, default=None,
                    help="Up to this date (default: today)")
    ap.add_argument("--tournament", type=str, default=None,
                    help="Filter by tournament (partial, case-insensitive)")
    ap.add_argument("--allow-insample", action="store_true",
                    help="Permit --from earlier than 2024-01-01 (biased, in-sample)")
    ap.add_argument("--skip-existing", action="store_true",
                    help="Only INSERT missing rows — never overwrite an existing "
                         "prediction (protects live pre-match predictions/odds). "
                         "Used by the daily cron to catch never-anticipated fixtures.")
    args = ap.parse_args()

    from_ts = pd.Timestamp(args.from_date)
    if from_ts < OUT_OF_SAMPLE_START and not args.allow_insample:
        print(f"[abort] --from {args.from_date} is before {OUT_OF_SAMPLE_START.date()} "
              f"(model's training era). Results would be in-sample / optimistic.\n"
              f"        Pass --allow-insample to override.")
        sys.exit(1)

    print("Loading models …")
    models = _load_models()

    print("Building pre-match features for full history (no leakage) …")
    historical, _ = load_results(DATA_DIR)
    feats = build_features(historical)
    feats["date"] = pd.to_datetime(feats["date"])

    # ── Filter to requested window ───────────────────────────────────────────
    mask = feats["date"] >= from_ts
    if args.to_date:
        mask &= feats["date"] <= pd.Timestamp(args.to_date)
    if args.tournament:
        mask &= feats["tournament"].str.contains(args.tournament, case=False, na=False)
    feats = feats[mask].reset_index(drop=True)
    print(f"  {len(feats)} played matches to backfill "
          f"({from_ts.date()} → {args.to_date or 'today'}).")
    if len(feats) == 0:
        return

    # ── Batch predict (vectorised) ───────────────────────────────────────────
    X  = feats.reindex(columns=NATIONAL_FEATURE_COLS)
    Xd = feats.reindex(columns=DRAW_FEATURE_COLS)

    cal_result = _apply_calibration_result(models["model_result"], models["cal_result"], X)   # (n,3)
    draw_raw   = models["model_draw_clf"].predict_proba(Xd)[:, 1]
    draw_cal   = models["cal_draw_clf"].predict(draw_raw)
    p_over_all = _apply_calibration_binary(models["model_goals"], models["cal_goals"], X)
    p_btts_all = _apply_calibration_binary(models["model_btts"],  models["cal_btts"],  X)
    alpha      = models.get("draw_alpha", 0.35)

    # ── Persist ──────────────────────────────────────────────────────────────
    from backend.app.database import SessionLocal
    from backend.app.models.national_prediction import NationalPrediction
    from sqlalchemy import and_

    db = SessionLocal()
    inserted = updated = correct = 0
    try:
        for i, row in feats.iterrows():
            p_h, p_d, p_a = blend_draw_probability(
                float(cal_result[i, 0]), float(cal_result[i, 1]), float(cal_result[i, 2]),
                float(draw_cal[i]), alpha=alpha,
            )
            pred  = max(("H", "D", "A"), key=lambda x: {"H": p_h, "D": p_d, "A": p_a}[x])
            p_max = max(p_h, p_d, p_a)

            hg, ag = int(row["home_goals"]), int(row["away_goals"])
            actual = RESULT_LABELS[int(row["target_result"])]
            if pred == actual:
                correct += 1

            match_date = row["date"].strftime("%Y-%m-%d")
            existing = db.query(NationalPrediction).filter(and_(
                NationalPrediction.match_date == match_date,
                NationalPrediction.home_team  == row["home_team"],
                NationalPrediction.away_team  == row["away_team"],
            )).first()
            if existing is None:
                # Reversed orientation (sources disagree on home/away
                # designation) — don't create a mirrored duplicate.
                existing = db.query(NationalPrediction).filter(and_(
                    NationalPrediction.match_date == match_date,
                    NationalPrediction.home_team  == row["away_team"],
                    NationalPrediction.away_team  == row["home_team"],
                )).first()
                if existing is not None and args.skip_existing:
                    continue

            fields = dict(
                tournament    = row["tournament"],
                neutral       = bool(row["neutral"]),
                home_win_prob = round(p_h, 4),
                draw_prob     = round(p_d, 4),
                away_win_prob = round(p_a, 4),
                prediction    = pred,
                confidence    = _confidence_label(p_max),
                over_2_5_prob = round(float(p_over_all[i]), 4),
                btts_prob     = round(float(p_btts_all[i]), 4),
                h_elo         = round(float(row["h_elo"]), 1),
                a_elo         = round(float(row["a_elo"]), 1),
                actual_result      = actual,
                actual_home_goals  = hg,
                actual_away_goals  = ag,
            )

            if existing:
                if args.skip_existing:
                    continue
                for k, v in fields.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                db.add(NationalPrediction(
                    match_date=match_date, home_team=row["home_team"],
                    away_team=row["away_team"], **fields,
                ))
                inserted += 1

        db.commit()
        n = len(feats)
        print(f"\n  DB: {inserted} inserted, {updated} updated")
        print(f"  Out-of-sample accuracy on backfilled set: {correct}/{n} = {correct/n:.1%}")
    except Exception as e:
        db.rollback()
        print(f"  [error] {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
