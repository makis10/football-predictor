"""
UEFA competition projection (champion / final / last-16).

A UEFA season stacks three formats under one league id: a July qualifying
knockout, a 36-team league phase, then a spring bracket. Two things must hold:

1. IT REFUSES TO RUN DURING QUALIFYING. Before the league-phase draw the field
   literally doesn't exist — half of it is still playing to get in — so a title
   probability would be invented, not estimated. It returns None until fixtures
   carrying round = "League Phase - N" appear, then lights up on its own.
2. THE PROBABILITIES ARE A PARTITION. Exactly one team lifts the trophy, two
   reach the final, sixteen reach the last 16 (8 seeded + 8 play-off winners).
   Those sums are the cheapest possible check that the bracket doesn't drop or
   duplicate a team.
"""
import random

import backend.app.ml.club_elo as club_elo_mod
from backend.app.ml.european_sim import simulate_european
from backend.app.ml.standings import is_league_phase

TEAMS = [f"T{i:02d}" for i in range(1, 37)]
# Strictly descending strength, so "stronger ⇒ better odds" is checkable.
ELO = {t: 1900 - 10 * i for i, t in enumerate(TEAMS)}


def _league_phase_rows(played: int = 0):
    """8 fixtures per team, as the real league phase has. `played` rounds settled."""
    rng = random.Random(11)
    rows = []
    for i, t in enumerate(TEAMS):
        for j in range(1, 5):
            opp = TEAMS[(i + j * 3) % 36]
            if opp == t:
                continue
            if j <= played:
                hg, ag = rng.randint(0, 3), rng.randint(0, 3)
            else:
                hg = ag = None
            rows.append(("2026/27", t, opp, hg, ag, f"League Phase - {j}"))
    return rows


class _Res:
    def __init__(self, r): self._r = r
    def fetchall(self): return self._r
    def fetchone(self): return self._r[0] if self._r else None


class _DB:
    def __init__(self, rows): self._rows = rows
    def execute(self, stmt, params=None):
        # _latest_season() asks for the newest fixture's season label.
        if "ORDER BY match_date DESC" in str(stmt):
            return _Res([("2026/27",)])
        return _Res(self._rows)


def _patch_elo(monkeypatch):
    monkeypatch.setattr(club_elo_mod, "club_elo", lambda db: ELO)


# ── 1. phase detection / refusal ─────────────────────────────────────────────

def test_league_phase_round_detection():
    assert is_league_phase("League Phase - 3")
    assert is_league_phase("league phase - 8")
    assert not is_league_phase("1st Qualifying Round")
    assert not is_league_phase("Round of 16")
    assert not is_league_phase(None)


def test_no_projection_while_still_in_qualifying(monkeypatch):
    _patch_elo(monkeypatch)
    quali = [("2026/27", "A", "B", 1, 0, "1st Qualifying Round")]
    assert simulate_european(_DB(quali), "CL") is None


def test_domestic_league_is_not_a_uefa_competition(monkeypatch):
    _patch_elo(monkeypatch)
    assert simulate_european(_DB(_league_phase_rows()), "EPL") is None


# ── 2. the bracket is a partition ────────────────────────────────────────────

def test_probabilities_partition_the_bracket(monkeypatch):
    _patch_elo(monkeypatch)
    out = simulate_european(_DB(_league_phase_rows()), "CL", sims=2000)

    assert out["matches_remaining"] == 144
    assert len(out["teams"]) == 36

    champions = sum(t["p_champion"] for t in out["teams"])
    finalists = sum(t["p_final"] for t in out["teams"])
    last16    = sum(t["p_r16"] for t in out["teams"])

    assert champions == pytest_approx(1.0)    # exactly one winner
    assert finalists == pytest_approx(2.0)    # two reach the final
    assert last16    == pytest_approx(16.0)   # 8 seeded + 8 play-off winners


def test_stronger_teams_get_better_odds(monkeypatch):
    _patch_elo(monkeypatch)
    out = simulate_european(_DB(_league_phase_rows()), "CL", sims=2000)
    by_team = {t["team"]: t for t in out["teams"]}
    # Top of the Elo range vs the bottom — a gap this wide must survive the noise.
    assert by_team["T01"]["p_champion"] > by_team["T36"]["p_champion"]
    assert by_team["T01"]["p_r16"] > by_team["T36"]["p_r16"]


def test_played_rounds_are_counted_not_replayed(monkeypatch):
    _patch_elo(monkeypatch)
    out = simulate_european(_DB(_league_phase_rows(played=2)), "CL", sims=500)
    assert out["matches_played"] == 72
    assert out["matches_remaining"] == 72


def pytest_approx(v: float, tol: float = 0.02):
    class _Approx:
        def __eq__(self, other): return abs(other - v) <= tol
        def __repr__(self): return f"~{v}"
    return _Approx()
