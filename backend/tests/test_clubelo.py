"""ClubElo cold-start fallback: load, linear fit, and cold-start seeding.

Pure-logic tests — no network, no artifacts required. A synthetic overlap fixes
the fit so the assertions are deterministic.
"""
from collections import defaultdict

from backend.app.ml.clubelo import fit_clubelo_map, seed_cold_start


def _snapshot(elo: dict) -> dict:
    d = defaultdict(lambda: 1500.0)
    d.update(elo)
    return {"elo": d}


def test_fit_requires_minimum_overlap():
    # Only 3 overlapping teams → below _MIN_OVERLAP → no fit.
    our = {f"Team {i}": 1500 + i for i in range(3)}
    clubelo = {f"team{i}": 1500 + i for i in range(3)}
    assert fit_clubelo_map(our, clubelo) is None


def test_fit_recovers_known_linear_relationship():
    # our = 0.5*clubelo + 800 by construction; fit must recover it.
    our, clubelo = {}, {}
    for i in range(40):
        c = 1400 + i * 15
        our[f"Team {i}"] = 0.5 * c + 800
        clubelo[f"team{i}"] = c
    fit = fit_clubelo_map(our, clubelo)
    assert fit is not None
    a, b, lo, hi = fit
    assert abs(a - 0.5) < 1e-6
    assert abs(b - 800) < 1e-3
    assert lo == min(our.values()) and hi == max(our.values())


def test_fit_rejects_zero_spread():
    # All clubelo identical → cannot fit a slope → None (not a crash).
    our = {f"Team {i}": 1500 + i for i in range(40)}
    clubelo = {f"team{i}": 1600.0 for i in range(40)}
    assert fit_clubelo_map(our, clubelo) is None


def _overlap(n=40):
    our, clubelo = {}, {}
    for i in range(n):
        c = 1400 + i * 15
        our[f"Known {i}"] = 0.6 * c + 500
        clubelo[f"known{i}"] = c
    return our, clubelo


def test_seed_only_touches_cold_start_fixture_teams():
    our, clubelo = _overlap()
    snap = _snapshot(our)
    known = set(our)
    clubelo["coldteam"] = 1700.0            # a team absent from `our`
    seeded = seed_cold_start(snap, known, ["Cold Team", "Known 0"], clubelo)
    # Known 0 is skipped (already has history); Cold Team is seeded.
    assert "Known 0" not in seeded
    assert "Cold Team" in seeded
    assert snap["elo"]["Cold Team"] == seeded["Cold Team"]
    # Value follows the fitted map (0.6*1700 + 500 = 1520), inside clamp range.
    assert abs(seeded["Cold Team"] - (0.6 * 1700 + 500)) < 1e-6


def test_seed_clamps_to_observed_range():
    our, clubelo = _overlap()
    snap = _snapshot(our)
    known = set(our)
    hi = max(our.values())
    clubelo["monster"] = 9000.0             # absurd → maps far above our range
    seeded = seed_cold_start(snap, known, ["Monster"], clubelo)
    assert seeded["Monster"] == hi          # clamped, never extrapolated


def test_seed_no_clubelo_is_noop():
    our, _ = _overlap()
    snap = _snapshot(our)
    seeded = seed_cold_start(snap, set(our), ["Whoever"], {})
    assert seeded == {}


def test_seed_unmatched_team_stays_default():
    our, clubelo = _overlap()
    snap = _snapshot(our)
    seeded = seed_cold_start(snap, set(our), ["Totally Unknown XYZ"], clubelo)
    assert seeded == {}
    assert snap["elo"]["Totally Unknown XYZ"] == 1500.0   # defaultdict fallback
