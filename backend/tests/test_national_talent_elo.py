"""National talent-adjusted Elo must adjust a pairing, not a team.

The squad-talent correction is normalised on the cohort of teams with squad
data (the 2026 World Cup squads). For two covered teams the cohort mean cancels
in their difference. For a pairing where only one side was covered it dragged
that side toward the cohort mean (~1806) while the opponent stayed on raw
results-Elo — up to 16 points of win probability on pairings replayed on
2026-09-12, and 314 of the last year's 968 national predictions were one-sided.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import backend.app.ml.national.features as F

# Strength anti-correlated with Elo on purpose: collinear data would make the
# correction zero and hide the bug.
COVERED = {f"C{i}": 0.87 - 0.03 * i for i in range(10)}


@pytest.fixture()
def snapshot(monkeypatch):
    monkeypatch.setattr(F, "_squad_strength_cache", dict(COVERED))
    return {"elo": {**{f"C{i}": 1700.0 + 25 * i for i in range(10)}, "U": 1650.0},
            "team_all": {}, "team_comp": {}, "h2h": {}, "last_date": {}}


def _features(snap, home, away):
    return F.compute_match_features(snap, home, away, "Friendly", True,
                                    pd.Timestamp("2026-10-10"))


@pytest.mark.parametrize("home, away", [("C0", "U"), ("U", "C0")])
def test_a_one_sided_pairing_stays_on_results_elo(snapshot, home, away):
    elo = snapshot["elo"]
    f = _features(snapshot, home, away)
    assert (f["h_elo"], f["a_elo"]) == (elo[home], elo[away])
    assert f["elo_diff"] == elo[home] - elo[away]
    assert f["elo_closeness"] == pytest.approx(1.0 / (1.0 + abs(elo[home] - elo[away])))


def test_a_low_confidence_team_counts_as_uncovered(snapshot, monkeypatch, tmp_path):
    raw = {t: {"strength": s} for t, s in COVERED.items()}
    raw["J"] = {"strength": 0.99, "low_confidence": True}
    path = tmp_path / "squad_strength.json"
    path.write_text(json.dumps(raw))
    monkeypatch.setattr(F, "_SQUAD_STRENGTH_PATH", path)
    monkeypatch.setattr(F, "_squad_strength_cache", None)
    snapshot["elo"]["J"] = 1600.0
    f = _features(snapshot, "C0", "J")
    assert (f["h_elo"], f["a_elo"]) == (1700.0, 1600.0)


def test_two_covered_teams_get_the_relative_correction(snapshot):
    """Passes before and after the fix: guards against an over-fix that drops
    the adjustment altogether."""
    w = F.TALENT_BLEND_W
    st = F._talent_stats(snapshot)
    r0, r9 = snapshot["elo"]["C0"], snapshot["elo"]["C9"]
    expected = (1 - w) * (r0 - r9) + w * (st["sd_e"] / st["sd_s"]) * (COVERED["C0"] - COVERED["C9"])
    assert _features(snapshot, "C0", "C9")["elo_diff"] == pytest.approx(expected)

    # A constant added to every rating cannot change a relative correction.
    shifted = {k: v for k, v in snapshot.items() if k != "_talent_stats"}
    shifted["elo"] = {t: e + 300.0 for t, e in snapshot["elo"].items()}
    assert _features(shifted, "C0", "C9")["elo_diff"] == pytest.approx(expected)
