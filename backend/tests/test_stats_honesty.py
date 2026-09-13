"""Every number on /stats is measured against the right thing.

Found by the 2026-09-13 audit, each confirmed on live data:
- O/U and BTTS were compared with always-OVER / always-GG, so where UNDER or NG
  is the majority a model below the no-model floor printed a green "+Xpp"
  (Serie A O/U: "+6.7pp vs always OVER 46%" while always-UNDER scores 54.4%).
- "Last 7 days" held eight match days, "Last 30" thirty-one.
- The last methodology era pooled unanchored and market-anchored predictions.
- The "value strategy" ROI pooled three selection rules; EV and fair-value
  "model quality" read the served (85% market) probabilities; CLV was one global
  ledger figure on every league page.
- National accuracy was graded by the stored label on one page and by the
  probabilities on another.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from backend.app.routers.stats import _accuracy_slice

ROOT = Path(__file__).resolve().parents[2]
STATS = (ROOT / "backend/app/routers/stats.py").read_text(encoding="utf-8")


def _row(hg, ag, result, over=0.6):
    return dict(home_goals=hg, away_goals=ag, result=result, match_date=date(2026, 9, 1),
                home_win_prob=0.5, draw_prob=0.25, away_win_prob=0.25,
                over_2_5_prob=over, goals_prediction="OVER" if over >= 0.5 else "UNDER")


def test_the_goals_floor_is_the_more_common_side():
    rows = [_row(1, 0, "H")] * 7 + [_row(2, 1, "H")] * 3   # 70% under
    s = _accuracy_slice(rows)
    assert s.goals_baseline == 0.7 and s.goals_baseline_side == "UNDER"
    rows = [_row(2, 2, "D")] * 6 + [_row(0, 0, "D")] * 4   # 60% over
    s = _accuracy_slice(rows)
    assert s.goals_baseline == 0.6 and s.goals_baseline_side == "OVER"


def test_the_btts_floor_is_the_more_common_side():
    assert "max(n_actual_gg, n_actual_ng) / n_bt" in STATS
    assert 'gg_baseline_side="GG" if n_actual_gg >= n_actual_ng else "NG"' in STATS


def test_rolling_windows_are_n_days_including_today():
    assert "timedelta(days=6)" in STATS and "timedelta(days=29)" in STATS
    assert "timedelta(days=7)" not in STATS and "timedelta(days=30)" not in STATS


def test_the_anchored_eras_are_their_own_rows():
    assert '("pure-unified",   date(2026, 7, 10),  date(2026, 9, 1))' in STATS
    assert '"anchored-all"' in STATS


def test_the_value_strategy_counts_only_ev_gated_picks():
    assert 'if sm and " @ " in sm and r.get("ev_score") is not None:' in STATS


def test_ev_and_model_quality_read_the_models_own_numbers():
    body = STATS.split("for r in rows:\n        d_str")[1].split("roi: Optional[ROIStats]")[0]
    for raw in ("raw_home_prob", "raw_over_prob", "raw_btts_prob"):
        assert raw in body, raw
    assert "Prediction.raw_home_prob" in STATS


def test_clv_is_measured_on_the_slice_not_the_whole_ledger():
    clv = STATS.split("def _compute_clv")[1].split("\ndef ")[0]
    assert "ValueBet.match_id.in_(settled_ids)" in clv


def test_per_league_and_per_version_rows_carry_their_floor():
    assert STATS.count("base = _accuracy_slice(") == 2


def test_national_accuracy_is_graded_by_the_probabilities():
    nat = (ROOT / "backend/app/routers/national.py").read_text(encoding="utf-8")
    fn = nat.split("def national_stats(")[1].split("\n@router.")[0]
    assert "_pick(r)" in fn
    assert "r.prediction ==" not in fn and "r.prediction)" not in fn


def test_the_analysis_panel_shows_the_served_numbers_and_the_stored_pick():
    pred = (ROOT / "backend/app/routers/predictions.py").read_text(encoding="utf-8")
    assert "model=ModelProbs(home_win=hw, draw=d, away_win=aw, over_2_5=ov, btts=btts)" in pred
    assert "suggested_market=pred.suggested_market," in pred


def test_admin_figures_follow_the_live_rules():
    admin = (ROOT / "backend/app/routers/admin_users.py").read_text(encoding="utf-8")
    assert "WHERE vb.source = 'club' AND m.void_reason IS NULL" in admin
    users_sql = admin.split("def list_users")[1].split("def delete_user")[0]
    assert "SUM(ub.profit)" not in users_sql, "profit summed over a tracked × bets fan-out"


def test_tracked_matches_show_the_served_confidence():
    users = (ROOT / "backend/app/routers/users.py").read_text(encoding="utf-8")
    fn = users.split("def get_tracked")[1].split("\n@router.")[0]
    assert "confidence_for(" in fn and "p.confidence" not in fn
