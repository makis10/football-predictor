"""
League standings + season projection.

The traps these lock down, all found on real data:

1. SEASON LABELS ARE INCONSISTENT. The CSV importer writes "2025/2026", the API
   fetchers write "2025/26" — for the same season. Bundesliga 2025-26 lives as
   261 rows under one label and 44 under the other. Group by the raw string and
   one league table becomes two half-tables.
2. ZONE SIZES ARE PER-COMPETITION, and the top zone means different things:
   4th in the Premier League is a Champions League place, 4th in the
   Championship is a promotion play-off.
3. THE PROJECTION MUST REFUSE FORMATS IT CANNOT MODEL. It derives the remaining
   fixtures as a double round-robin minus what's played (we only ingest ~60 days
   of fixtures, so the DB's fixture list is not the season). The Greek Super
   League splits into play-off groups, so that derivation would invent matches
   that never get played — it must return None rather than guess.
"""
import pytest

from backend.app.ml.league_sim import PLAYOFF_LEAGUES, simulate_league
from backend.app.ml.standings import TOP_ZONE_LABEL, _canon_season


# ── 1. season-label normalisation ────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("2025/2026", "2025/26"),
    ("2025/26",   "2025/26"),
    ("2026/27",   "2026/27"),
    ("2023/2024", "2023/24"),
])
def test_season_labels_collapse_to_one_form(raw, expected):
    assert _canon_season(raw) == expected


def test_both_labels_for_one_season_agree():
    # The actual defect: these two spellings must land in the same bucket, or
    # the season's matches are split across two tables.
    assert _canon_season("2025/2026") == _canon_season("2025/26")


def test_unknown_format_passes_through_untouched():
    assert _canon_season("2026") == "2026"
    assert _canon_season("") == ""


# ── 2. zone semantics ────────────────────────────────────────────────────────

def test_top_zone_label_is_competition_specific():
    assert TOP_ZONE_LABEL["EPL"] == "Champions League"
    assert TOP_ZONE_LABEL["Championship"] == "Promotion"
    assert TOP_ZONE_LABEL["BrazilSerieA"] == "Libertadores"


# ── 3. the projection refuses what it cannot model ───────────────────────────

def test_playoff_league_simulates_the_playoff_phase(monkeypatch):
    """Greek SL: after the regular-season round-robin the simulated table splits
    into carried-points groups (championship 1-4 / qualifying 5-8 / relegation
    9-14) and the title/relegation come from the GROUP outcomes. The invariants
    are the cheapest proof the group phase neither drops nor duplicates a team.
    """
    assert "GreekSL" in PLAYOFF_LEAGUES

    import backend.app.ml.club_elo as club_elo_mod
    teams = [f"G{i:02d}" for i in range(1, 15)]        # 14-team season
    elo = {t: 1750 - 25 * i for i, t in enumerate(teams)}   # G01 strongest
    monkeypatch.setattr(club_elo_mod, "club_elo", lambda db: elo)

    class _Res:
        def __init__(s, r): s._r = r
        def fetchall(s): return s._r
        def fetchone(s): return s._r[0] if s._r else None

    class _DB:
        def execute(s, stmt, params=None):
            if "ORDER BY match_date DESC" in str(stmt):
                return _Res([("2026/27",)])
            if "COUNT(*)" in str(stmt):
                return _Res([(182,)])
            return _Res([("2026/27", h, a, None, None) for h in teams for a in teams if h != a])

    out = simulate_league(_DB(), "GreekSL", sims=800)
    assert out is not None
    assert out["note"]                                  # playoff explainer present
    assert len(out["teams"]) == 14

    # Partitions: exactly one champion, exactly two relegated per simulation.
    assert abs(sum(t["p_title"] for t in out["teams"]) - 1.0) < 0.02
    assert abs(sum(t["p_relegated"] for t in out["teams"]) - 2.0) < 0.02

    by = {t["team"]: t for t in out["teams"]}
    # Strength ordering must survive both phases.
    assert by["G01"]["p_title"] > by["G14"]["p_title"]
    assert by["G14"]["p_relegated"] > by["G01"]["p_relegated"]
    # The strongest side effectively can't go down through the group phase.
    assert by["G01"]["p_relegated"] < 0.01
    # Expected points include the play-off games: a champion's season is 26
    # regular rounds + 6 championship-group games, so the leader must project
    # clearly past the 26-round ceiling for a run-of-the-mill winner (~55).
    assert by["G01"]["exp_points"] > 50
