"""
Fetch bookmaker odds + compute value-bet EV for upcoming national-team
predictions, and store them on the national_predictions rows.

Mirrors the club pipeline (compute_predictions.py): pulls odds from The Odds
API, removes vig, computes expected value with the same _compute_ev /
_best_ev_market path, and writes bm_*_odds + ev_score + suggested_market.

Odds exist only for tournaments The Odds API covers (World Cup, EURO, Copa
América, AFCON, Nations League, qualifiers). Friendlies have no odds source and
are skipped — their odds columns stay NULL.

Cost: 1 API credit per active tournament per 30 min (games list is cached),
plus 1 credit per matched event for the GG/NG market.

Usage:
  docker compose exec backend python scripts/fetch_national_odds.py
  docker compose exec backend python scripts/fetch_national_odds.py --days-ahead 14
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.database import SessionLocal
from backend.app.models.national_prediction import NationalPrediction
from backend.app.ml.odds_analysis_service import (
    get_national_sport_key,
    fetch_bookmaker_odds_national,
    _compute_ev,
    _best_ev_market,
    _qualifying_markets,
    proven_markets,
    shrunk_ev,
    _MARKET_ODDS_KEY,
    _MARKET_MODEL_KEY,
)
from backend.app.ml.value_ledger import record_ticket


def _confidence_label(p_max: float) -> str:
    if p_max >= 0.65:
        return "HIGH"
    if p_max >= 0.55:
        return "MEDIUM"
    return "LOW"


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch odds + EV for national predictions")
    ap.add_argument("--days-ahead", type=int, default=None,
                    help="Only fixtures within N days (default: all upcoming)")
    args = ap.parse_args()

    today = date.today().isoformat()
    upper = ((date.today() + timedelta(days=args.days_ahead)).isoformat()
             if args.days_ahead else None)

    db = SessionLocal()
    matched = no_key = no_odds = 0
    try:
        q = db.query(NationalPrediction).filter(
            NationalPrediction.actual_result.is_(None),
            NationalPrediction.match_date >= today,
        )
        if upper:
            q = q.filter(NationalPrediction.match_date <= upper)
        rows = q.order_by(NationalPrediction.match_date.asc()).all()
        print(f"{len(rows)} upcoming prediction(s) to price.")

        # Dynamic proven set (new-model record). Markets that qualify but aren't
        # proven yet are still recorded as shadow tickets below — that's how they
        # accumulate the evidence to eventually promote.
        proven = proven_markets(db, "national")
        print(f"proven suggestable markets: {sorted(proven)}")
        from backend.app.ml.gate_alerts import alert_gate_change
        alert_gate_change("national", proven)   # log + webhook on promote/demote

        # Skip whole tournaments with no Odds API coverage (e.g. Friendly) up front.
        skipped_tournaments: set[str] = set()

        for r in rows:
            sport_key = get_national_sport_key(r.tournament)
            if not sport_key:
                no_key += 1
                if r.tournament not in skipped_tournaments:
                    skipped_tournaments.add(r.tournament)
                    print(f"  [skip] no Odds API key for tournament: {r.tournament!r}")
                continue

            bm = fetch_bookmaker_odds_national(r.home_team, r.away_team, sport_key)
            if not bm or not bm.get("raw_odds"):
                no_odds += 1
                continue

            raw = bm.get("raw_odds", {})
            fair = bm.get("fair_probs", {})

            r.bm_home_odds     = raw.get("home_win")
            r.bm_draw_odds     = raw.get("draw")
            r.bm_away_odds     = raw.get("away_win")
            r.bm_over_odds     = raw.get("over_2_5")
            r.bm_btts_yes_odds = raw.get("btts_yes")
            r.bm_btts_no_odds  = raw.get("btts_no")
            r.num_bookmakers   = bm.get("num_bookmakers")

            # Kick-off instant (UTC) from the matched event
            ct = bm.get("commence_time")
            if ct:
                from datetime import datetime as _dt
                try:
                    r.kickoff_utc = _dt.fromisoformat(ct.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # ── Value-bet EV — identical path to compute_predictions.py ──────────
            # Always measure EV against the PURE model probs (raw_*), never the
            # already-anchored served columns, or the value would double-shrink.
            rh = r.raw_home_prob if r.raw_home_prob is not None else r.home_win_prob
            rd = r.raw_draw_prob if r.raw_draw_prob is not None else r.draw_prob
            ra = r.raw_away_prob if r.raw_away_prob is not None else r.away_win_prob
            r_over = r.raw_over_prob if r.raw_over_prob is not None else r.over_2_5_prob
            # Backfill raw_* for rows created before this column existed.
            if r.raw_home_prob is None:
                r.raw_home_prob, r.raw_draw_prob, r.raw_away_prob, r.raw_over_prob = rh, rd, ra, r_over
            model_probs = {
                "home_win": rh,
                "draw":     rd,
                "away_win": ra,
                "over_2_5": r_over,
                "btts":     r.btts_prob,
            }
            ev_map = _compute_ev(model_probs, {"raw_odds": raw})
            raw_nz = {k: v for k, v in raw.items() if v}
            suggested = None
            ev_score = None
            if ev_map:
                # Headline suggestion = best PROVEN market only.
                suggested = _best_ev_market(
                    ev_map, raw_nz, fair_probs=fair, model_probs=model_probs,
                    suggestable=proven,
                )
                if suggested:
                    # Store the market-shrunk EV — the honest edge estimate the
                    # gate validated, not the inflated raw model EV.
                    ev_score = shrunk_ev(suggested.split(" @ ")[0],
                                         model_probs, fair, raw)
            # Keep the FIRST suggestion (matches the immutable ticket) — later
            # runs see market-drifted odds and would clear/replace it.
            if r.suggested_market is None:
                r.suggested_market = suggested
                r.ev_score         = ev_score

            # Shadow-track EVERY qualifying market (proven + watch) as an
            # insert-once ticket. This is how previously-killed markets (GG,
            # Over/Under, Away) accumulate a NEW-model record so the dynamic gate
            # can eventually promote (or keep rejecting) them on data, not on a
            # stale assumption. Tickets are immutable; CLV is measured later.
            if ev_map:
                qualifying = _qualifying_markets(ev_map, raw_nz, fair, model_probs)
                for _mname in qualifying:
                    _okey = _MARKET_ODDS_KEY.get(_mname, "")
                    if not raw.get(_okey):
                        continue
                    _mprob = model_probs.get(_MARKET_MODEL_KEY.get(_mname, ""))
                    if _mname in ("Under 2.5", "NG") and _mprob is not None:
                        _mprob = 1.0 - _mprob
                    _sev = shrunk_ev(_mname, model_probs, fair, raw)
                    if record_ticket(
                        db, source="national", national_prediction_id=r.id,
                        market=_mname, odds=raw[_okey], ev=_sev,
                        model_prob=_mprob, market_prob=fair.get(_okey),
                    ):
                        tier = "proven" if _mname in proven else "watch"
                        print(f"    🎫 [{tier}] {r.home_team} vs {r.away_team} — {_mname} @ {raw[_okey]}")
            # ── NO market anchoring (2026-06-17 directive) ──────────────────────
            # Served probabilities stay exactly as the pure international model
            # produced them in predict_national.py. The bookmaker is used above
            # only for the EV/value comparison (raw model vs de-vig odds), never
            # to shift the served numbers. market_anchored is forced False so any
            # row anchored by a previous build is reset on the next predict pass.
            r.market_anchored = False

            matched += 1

            tag = f"  ✓ {r.match_date} {r.home_team} vs {r.away_team}"
            tag += f"  [{r.num_bookmakers}bm] → {r.prediction}"
            if suggested:
                tag += f"  ⚡ {suggested} (EV {ev_score:+.1%})"
            print(tag)

        db.commit()
        print(f"\nPriced: {matched}   No odds match: {no_odds}   No-coverage tournament: {no_key}")
    except Exception as e:
        db.rollback()
        print(f"[error] {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
