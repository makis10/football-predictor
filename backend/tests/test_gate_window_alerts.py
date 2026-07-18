"""Rolling-window market aggregation + dynamic-gate change alerting.

Pure-logic, no DB/network. Covers the recovery mechanism (old losses age out of
the window) and the alert diff (seed silent, fire only on change)."""
from pathlib import Path

import backend.app.ml.gate_alerts as ga
from backend.app.ml.odds_analysis_service import (
    _window_market_records, _market_is_proven, PROVEN_ROLLING_WINDOW,
)


# ── Rolling window ────────────────────────────────────────────────────────────

def _row(market, won, odds=2.0):
    # won → a result tuple _market_won reads. Use Home Win: res 'H' wins, 'A' loses.
    if market == "Home Win":
        return (market, odds, "H" if won else "A", 1, 0 if won else 1)
    if market == "Over 2.5":
        return (market, odds, "H", (2 if won else 0), (2 if won else 0))  # 4 goals win / 0 lose
    raise ValueError(market)


def test_window_caps_at_rolling_window():
    # 60 tickets but window is 40 → only 40 counted.
    rows = [_row("Home Win", True) for _ in range(60)]
    rec = _window_market_records(rows)["Home Win"]
    assert rec["n"] == PROVEN_ROLLING_WINDOW
    assert rec["wins"] == PROVEN_ROLLING_WINDOW


def test_window_keeps_most_recent_first():
    # Rows are most-recent-first. 40 recent WINS then 20 old LOSSES → window is all wins.
    rows = [_row("Home Win", True) for _ in range(40)] + \
           [_row("Home Win", False) for _ in range(20)]
    rec = _window_market_records(rows)["Home Win"]
    assert rec["n"] == 40 and rec["wins"] == 40      # old losses aged out
    assert rec["pnl"] > 0


def test_window_enables_demotion_recovery():
    # A base market that bled early then recovered: recent wins dominate the window
    # once the old losses fall past it → passes _market_is_proven again.
    recent_wins = [_row("Home Win", True) for _ in range(40)]
    old_losses = [_row("Home Win", False) for _ in range(16)]
    rec = _window_market_records(recent_wins + old_losses)["Home Win"]
    roi = rec["pnl"] / rec["n"]
    assert _market_is_proven("Home Win", rec["n"], roi) is True


# ── Alerting ──────────────────────────────────────────────────────────────────

def test_alert_seeds_silently_then_fires_on_change(tmp_path, monkeypatch):
    monkeypatch.setattr(ga, "_STATE_PATH", Path(tmp_path) / "gate_state.json")
    monkeypatch.setattr(ga, "_HISTORY_PATH", Path(tmp_path) / "gate_changes.jsonl")
    monkeypatch.delenv("GATE_ALERT_URL", raising=False)

    assert ga.alert_gate_change("national", {"Home Win"}) is None        # seed
    assert ga.alert_gate_change("national", {"Home Win"}) is None        # unchanged

    diff = ga.alert_gate_change("national", {"Home Win", "Over 2.5"})    # promote
    assert diff == {"promoted": ["Over 2.5"], "demoted": []}

    diff = ga.alert_gate_change("national", {"Over 2.5"})                # demote base
    assert diff == {"promoted": [], "demoted": ["Home Win"]}

    assert ga.alert_gate_change("national", {"Over 2.5"}) is None        # unchanged


def test_alert_state_is_per_source(tmp_path, monkeypatch):
    monkeypatch.setattr(ga, "_STATE_PATH", Path(tmp_path) / "gate_state.json")
    monkeypatch.setattr(ga, "_HISTORY_PATH", Path(tmp_path) / "gate_changes.jsonl")
    monkeypatch.delenv("GATE_ALERT_URL", raising=False)
    ga.alert_gate_change("national", {"Home Win"})
    ga.alert_gate_change("club", {"Home Win", "Draw"})
    # A change in club must not be masked by national's baseline.
    assert ga.alert_gate_change("club", {"Home Win"}) == {"promoted": [], "demoted": ["Draw"]}
    # National unchanged.
    assert ga.alert_gate_change("national", {"Home Win"}) is None


def test_history_records_changes_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(ga, "_STATE_PATH", Path(tmp_path) / "gate_state.json")
    monkeypatch.setattr(ga, "_HISTORY_PATH", Path(tmp_path) / "gate_changes.jsonl")
    monkeypatch.delenv("GATE_ALERT_URL", raising=False)

    ga.alert_gate_change("club", {"Home Win", "Draw"})           # seed → no history
    ga.alert_gate_change("club", {"Home Win", "Draw", "GG"})     # promote GG
    ga.alert_gate_change("club", {"Home Win", "GG"})             # demote Draw

    hist = ga.load_history(source="club")
    assert len(hist) == 2                       # seed didn't log
    assert hist[0]["demoted"] == ["Draw"]       # newest first
    assert hist[1]["promoted"] == ["GG"]
    assert all("at" in e and e["source"] == "club" for e in hist)
    # A source filter for national must return nothing here.
    assert ga.load_history(source="national") == []
