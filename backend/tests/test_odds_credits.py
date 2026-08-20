"""What a request to The Odds API actually costs, and what the schedule spends.

The plan is 20,000 credits a MONTH. In August it was gone by the 13th, and the
site spent the other 18 days with no bookmaker odds, no EV, no value gate and no
tickets. The cause was never measured at the time, only reasoned about — so
these pin the two things the reasoning depended on.
"""
from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from backend.app.odds_budget import cost_of

ROOT = Path(__file__).resolve().parents[2]
PLAN_CREDITS = 20_000
DAILY_BUDGET = PLAN_CREDITS / 31          # 645


# ── the billing rules ─────────────────────────────────────────────────────────
# Cost is markets × regions, NOT one per call. `markets=h2h,totals` doubles
# every league request, which is why a 23-league sweep costs 46 and not 23 —
# the single fact that made the August burn twice what anyone assumed.

@pytest.mark.parametrize("url,params,expected", [
    ("https://api.the-odds-api.com/v4/sports/", None, 0),
    ("https://api.the-odds-api.com/v4/sports/soccer_epl/events", {}, 0),
    ("https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
     {"regions": "eu", "markets": "h2h,totals"}, 2),
    ("https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
     {"regions": "eu,uk", "markets": "h2h,totals"}, 4),
    ("https://api.the-odds-api.com/v4/sports/soccer_epl/events/x/odds",
     {"regions": "eu", "markets": "btts"}, 1),
    ("https://api.the-odds-api.com/v4/sports/soccer_epl/scores", {"daysFrom": 3}, 2),
    ("https://api.the-odds-api.com/v4/sports/soccer_epl/scores", {}, 1),
    ("https://api.the-odds-api.com/v4/historical/sports/soccer_epl/odds",
     {"regions": "eu", "markets": "h2h"}, 10),
])
def test_credit_cost_follows_the_published_formula(url, params, expected):
    assert cost_of(url, params) == expected


def test_the_seam_check_and_fixture_fetches_are_free():
    """/events is free, which is why the odds-seam check can run daily and why
    Greek fixtures still arrived with the plan at zero credits."""
    assert cost_of("https://api.the-odds-api.com/v4/sports/soccer_greece_super_league/events", {}) == 0


# ── the schedule ──────────────────────────────────────────────────────────────

def _hours(name: str) -> list[int]:
    data = plistlib.loads((ROOT / "launchd" / f"com.football-predictor.{name}.plist").read_bytes())
    entries = data["StartCalendarInterval"]
    entries = entries if isinstance(entries, list) else [entries]
    return sorted(e.get("Hour", 0) for e in entries)


def test_the_odds_poll_runs_eight_hourly_not_three_hourly():
    """The repo plist had been left on the old 3-hourly schedule after the burn
    fix moved the INSTALLED one to 8-hourly. Nothing was broken day to day —
    but re-running launchd/install.sh would have quietly restored a schedule
    that costs 368 credits a day instead of 138, and the drift was invisible
    because the running job was fine.
    """
    assert _hours("odds-poll") == [0, 8, 16]


def test_the_scheduled_burn_fits_inside_the_plan():
    """A full sweep is 46 credits (23 leagues x h2h,totals x 1 region), the
    European scores poll is 2 per competition per run, and the daily and
    prematch runs each take one sweep. Written out rather than imported so a
    change to the schedule has to change this number too.
    """
    sweep = 46
    per_day = (
        len(_hours("odds-poll")) * sweep          # 3 x 46
        + len(_hours("results-poll")) * 3 * 2     # 11 runs x 3 competitions x 2
        + sweep + 2                               # daily run
        + sweep                                   # prematch
    )
    assert per_day < DAILY_BUDGET, (
        f"scheduled burn is {per_day}/day against a budget of {DAILY_BUDGET:.0f}")


# ── billed vs refused ─────────────────────────────────────────────────────────
# With the plan out of credits every request comes back 401 and bills nothing.
# The first version of the report counted those as spend, so the daily health
# section showed "992 credits — OVER budget" on a day the account was charged
# zero. That reads as an argument for an upgrade nobody needs.

def _ledger(tmp_path, rows):
    import json
    p = tmp_path / "odds_usage.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(p)


def _row(status, cost=2, caller="club_league_odds"):
    from datetime import datetime, timezone
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "caller": caller, "endpoint": "/sports/x/odds/",
            "markets": "h2h,totals", "regions": "eu", "cost": cost,
            "status": status}


def test_refused_calls_are_not_counted_as_spend(tmp_path, monkeypatch, capsys):
    import scripts.odds_budget_report as rep

    monkeypatch.setattr(rep, "PATH", _ledger(tmp_path, [_row(401) for _ in range(50)]))
    monkeypatch.setattr("sys.argv", ["odds_budget_report.py", "--days", "7"])
    rep.main()

    out = capsys.readouterr().out
    assert "No BILLED calls" in out
    assert "refused" in out
    assert "OVER" not in out, "an outage was reported as an overspend"


def test_refused_calls_still_report_what_they_would_have_cost(tmp_path, monkeypatch, capsys):
    """Worth knowing: it is what the same schedule bills once credits return."""
    import scripts.odds_budget_report as rep

    monkeypatch.setattr(rep, "PATH", _ledger(tmp_path, [_row(401) for _ in range(10)]))
    monkeypatch.setattr("sys.argv", ["odds_budget_report.py", "--days", "7"])
    rep.main()

    assert "20 credits" in capsys.readouterr().out


def test_successful_calls_are_counted(tmp_path, monkeypatch, capsys):
    import scripts.odds_budget_report as rep

    monkeypatch.setattr(rep, "PATH", _ledger(tmp_path, [_row(200) for _ in range(10)]))
    monkeypatch.setattr("sys.argv", ["odds_budget_report.py", "--days", "7"])
    rep.main()

    out = capsys.readouterr().out
    assert "20" in out and "club_league_odds" in out
