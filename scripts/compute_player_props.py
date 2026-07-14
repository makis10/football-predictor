"""
Compute player-prop probabilities for upcoming national-team fixtures and store
them in player_props.

For each upcoming match:
  • team expected goals λ_home / λ_away from the snapshot Elo (same engine as
    the WC simulator),
  • per-player recency-weighted + shrunk rates from player_match_stats,
  • anytime-scorer / SoT 1+/2+ / assist probabilities.

Idempotent upsert keyed on (national_prediction_id, player_id).

Usage:
  docker compose exec backend python scripts/compute_player_props.py
  docker compose exec backend python scripts/compute_player_props.py --tournament "FIFA World Cup"
"""
from __future__ import annotations

import argparse
import pickle
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SNAP = ROOT / "backend" / "data" / "models" / "national" / "snapshot.pkl"
ELO_START, MU_TOTAL, ELO_SCALE = 1500.0, 2.65, 220.0


def _lambdas(elo_h: float, elo_a: float) -> tuple[float, float]:
    gd = (elo_h - elo_a) / ELO_SCALE
    return max(0.2, MU_TOTAL / 2 + gd / 2), max(0.2, MU_TOTAL / 2 - gd / 2)


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute player props for upcoming nationals")
    ap.add_argument("--tournament", type=str, default=None, help="Filter (partial match)")
    ap.add_argument("--from", dest="from_date", type=str, default=None)
    args = ap.parse_args()

    from sqlalchemy import and_
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from backend.app.database import SessionLocal
    from backend.app.models.national_prediction import NationalPrediction
    from backend.app.models.player_prop import PlayerProp
    from backend.app.ml.national.player_props import (
        load_player_rates, compute_props, load_team_card_rates,
        load_team_corner_rates, corners_over_prob,
    )

    elo = pickle.load(open(SNAP, "rb"))["elo"] if SNAP.exists() else {}

    db = SessionLocal()
    written = fixtures = 0
    try:
        rates_by_team = load_player_rates(db)
        card_rates = load_team_card_rates(db)
        corner_rates = load_team_corner_rates(db)
        if not rates_by_team:
            print("[skip] No player_match_stats yet — run fetch_player_stats.py first.")
            return

        from_date = args.from_date or date.today().isoformat()
        q = db.query(NationalPrediction).filter(
            NationalPrediction.actual_result.is_(None),
            NationalPrediction.match_date >= from_date,
        )
        if args.tournament:
            q = q.filter(NationalPrediction.tournament.ilike(f"%{args.tournament}%"))
        upcoming = q.order_by(NationalPrediction.match_date.asc()).all()
        print(f"{len(upcoming)} upcoming fixtures to price.")

        for np_row in upcoming:
            lam_h, lam_a = _lambdas(
                elo.get(np_row.home_team, ELO_START),
                elo.get(np_row.away_team, ELO_START),
            )
            sides = [
                (np_row.home_team, np_row.away_team, lam_h),
                (np_row.away_team, np_row.home_team, lam_a),
            ]
            any_props = False
            for team, opp, team_xg in sides:
                props = compute_props(rates_by_team.get(team, []), team_xg)
                for p in props:
                    stmt = pg_insert(PlayerProp).values(
                        national_prediction_id=np_row.id,
                        match_date=np_row.match_date,
                        team=team, opponent=opp,
                        player_id=p["player_id"], player_name=p["player"],
                        exp_minutes=p["exp_minutes"], exp_goals=p["exp_goals"],
                        p_score=p["p_score"], p_sot_1=p["p_sot_1"],
                        p_sot_2=p["p_sot_2"], p_assist=p["p_assist"],
                    ).on_conflict_do_update(
                        constraint="uq_player_props",
                        set_=dict(
                            exp_minutes=p["exp_minutes"], exp_goals=p["exp_goals"],
                            p_score=p["p_score"], p_sot_1=p["p_sot_1"],
                            p_sot_2=p["p_sot_2"], p_assist=p["p_assist"],
                            match_date=np_row.match_date, team=team, opponent=opp,
                        ),
                    )
                    db.execute(stmt)
                    written += 1
                    any_props = True
            # Team expected cards (independent of player-prop availability)
            if np_row.home_team in card_rates:
                np_row.exp_home_cards = round(card_rates[np_row.home_team], 2)
            if np_row.away_team in card_rates:
                np_row.exp_away_cards = round(card_rates[np_row.away_team], 2)

            # Team expected corners + P(total corners over 9.5)
            ch = corner_rates.get(np_row.home_team)
            ca = corner_rates.get(np_row.away_team)
            if ch is not None:
                np_row.exp_home_corners = round(ch, 2)
            if ca is not None:
                np_row.exp_away_corners = round(ca, 2)
            if ch is not None and ca is not None:
                np_row.corners_over_9_5_prob = round(corners_over_prob(ch + ca, 9.5), 4)

            # Correct-score market — λ + ρ fitted to the prediction's own served
            # probabilities so the stored most-likely score / top-scores cohere
            # with the headline 1×2 / Over / BTTS (Elo λ only as fallback).
            from backend.app.ml.poisson import compute_extended_poisson_stats, fit_lambdas_to_probs, DC_RHO
            import json as _json
            _rho, _diag, _diag0 = DC_RHO, 1.0, 1.0
            _fit = fit_lambdas_to_probs(
                np_row.home_win_prob, np_row.away_win_prob, np_row.over_2_5_prob,
                p_btts=getattr(np_row, "btts_prob", None),
            )
            if _fit:
                _clh, _cla, _rho, _diag, _diag0 = _fit
            else:
                _clh, _cla = lam_h, lam_a
            cs = compute_extended_poisson_stats(_clh, _cla, top_n_scores=6, rho=_rho, diag=_diag, diag0=_diag0)
            np_row.most_likely_score = cs.get("most_likely_score")
            np_row.top_scores = _json.dumps(cs.get("top_scores", []))

            if any_props:
                fixtures += 1
            db.commit()
        print(f"\nDone. {written} player-prop rows across {fixtures} fixtures.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
