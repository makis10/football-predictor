"""
Club player-props logic — the club counterpart of the national player_props,
computed LIVE (no persistence) in backend/app/ml/club_player_props.py.

DB and API are stubbed: we monkeypatch the two DB-touching helpers
(`_api_name`, `load_player_rates`) and feed a fake session, so these tests
exercise the pure transformation/settlement logic without Postgres.
"""
from types import SimpleNamespace

import backend.app.ml.club_props as club_props_mod
import backend.app.ml.national.player_props as pp_mod
from backend.app.ml.club_player_props import club_player_props
from backend.app.ml.national.player_props import PlayerRate, compute_props


def _rate(pid, name, team, apps=5, exp_min=90.0, g90=0.5, position=None):
    return PlayerRate(
        player_id=pid, player=name, team=team,
        g90=g90, sot90=1.0, ast90=0.2,
        exp_minutes=exp_min, wmin=exp_min * apps, apps=apps,
        position=position,
    )


class _FakeResult:
    def __init__(self, rows): self._rows = rows
    def fetchall(self): return self._rows


class _FakeDB:
    """Only `execute(...).fetchall()` is used (the settlement query)."""
    def __init__(self, actual_rows=None): self._rows = actual_rows or []
    def execute(self, *a, **k): return _FakeResult(self._rows)


def _patch(monkeypatch, rates_by_api, name_map):
    monkeypatch.setattr(club_props_mod, "_api_name", lambda db, n: name_map.get(n))
    # club_player_props imports `_api_name` from club_props at call time.
    monkeypatch.setattr(pp_mod, "load_player_rates", lambda db, **k: rates_by_api)


NAME_MAP = {"Alpha FC": "Alpha", "Beta FC": "Beta"}


def test_upcoming_uses_prediction_lambda_and_display_names(monkeypatch):
    rates = {
        "Alpha": [_rate(1, "Striker A", "Alpha"), _rate(2, "Mid A", "Alpha")],
        "Beta":  [_rate(3, "Striker B", "Beta")],
    }
    _patch(monkeypatch, rates, NAME_MAP)
    match = SimpleNamespace(home_team="Alpha FC", away_team="Beta FC",
                            home_goals=None, away_goals=None, match_date="2026-08-01")
    pred = SimpleNamespace(poisson_lambda_home=1.8, poisson_lambda_away=1.1)

    out = club_player_props(_FakeDB(), match, pred)

    assert out["finished"] is False
    # Teams keyed by OUR display names, not the API names used for storage.
    assert set(out["teams"]) == {"Alpha FC", "Beta FC"}
    p = out["teams"]["Alpha FC"][0]
    assert "player_name" in p and "player_id" not in p     # renamed + internal id dropped
    assert 0.0 <= p["p_score"] <= 1.0
    # Upcoming → no settlement keys leak in.
    assert "score_hit" not in p and "played" not in p


def test_finished_settles_against_actuals(monkeypatch):
    rates = {"Alpha": [_rate(1, "Scorer", "Alpha"), _rate(2, "Blank", "Alpha")]}
    _patch(monkeypatch, rates, {"Alpha FC": "Alpha", "Beta FC": "Beta"})
    match = SimpleNamespace(home_team="Alpha FC", away_team="Beta FC",
                            home_goals=2, away_goals=1, match_date="2026-05-24")
    # Player 1 played + scored; player 2 has no actual row → DNP.
    actual = SimpleNamespace(player_id=1, minutes=90, goals=1, shots_on=3, assists=0)
    pred = SimpleNamespace(poisson_lambda_home=1.6, poisson_lambda_away=1.0)

    out = club_player_props(_FakeDB([actual]), match, pred)

    assert out["finished"] is True
    players = {p["player_name"]: p for p in out["teams"]["Alpha FC"]}
    assert players["Scorer"]["played"] is True
    assert players["Scorer"]["score_hit"] is True
    assert players["Scorer"]["actual_goals"] == 1
    assert players["Blank"]["played"] is False    # settled match, no appearance


def test_no_resolvable_teams_returns_empty(monkeypatch):
    _patch(monkeypatch, {}, {})   # _api_name returns None for both sides
    match = SimpleNamespace(home_team="X", away_team="Y",
                            home_goals=None, away_goals=None, match_date="2026-08-01")
    out = club_player_props(_FakeDB(), match, SimpleNamespace(
        poisson_lambda_home=1.5, poisson_lambda_away=1.5))
    assert out == {"teams": {}, "finished": False}


def test_compute_props_requires_min_apps():
    """Regression for the ingestion gotcha: props only appear once a player has
    ≥3 appearances, so `--last` must be ≥6-8 or the panel comes back empty."""
    two = compute_props([_rate(1, "P", "T", apps=2)], team_xg=1.5)
    three = compute_props([_rate(1, "P", "T", apps=3)], team_xg=1.5)
    assert two == []          # apps < min_apps → excluded
    assert len(three) == 1    # apps == min_apps → included


def test_goalkeepers_excluded_from_scorer_props():
    """A keeper must never surface in an anytime-scorer list — these are
    goal/SoT markets and keepers score about once per 160,000 minutes."""
    outfield = _rate(1, "Striker", "T", position="F")
    keeper   = _rate(2, "Keeper",  "T", position="G")
    out = compute_props([outfield, keeper], team_xg=1.5)
    assert [p["player"] for p in out] == ["Striker"]


def test_keeper_share_does_not_dilute_outfield_xg():
    """Keepers used to absorb part of team_xg in the normalisation, deflating
    the real scorers' numbers — dropping them must hand that share back."""
    striker = _rate(1, "Striker", "T", position="F")
    keeper  = _rate(2, "Keeper",  "T", position="G")
    alone = compute_props([striker], team_xg=1.5)[0]
    with_gk = compute_props([striker, keeper], team_xg=1.5)[0]
    assert with_gk["exp_goals"] == alone["exp_goals"]


def test_unknown_position_still_included():
    """Position is nullable in player_match_stats — an unknown position must
    not silently drop a player from the props."""
    out = compute_props([_rate(1, "P", "T", position=None)], team_xg=1.5)
    assert len(out) == 1


def test_roster_filter_drops_transferred_player(monkeypatch, tmp_path):
    """A player in the match log but no longer in the club's squad must be
    dropped — the log alone can never correct a transfer."""
    import backend.app.ml.club_player_props as cpp

    squads = tmp_path / "club_squads.json"
    squads.write_text('{"Home FC": {"team_id": 1, "player_ids": [1]}}')
    monkeypatch.setattr(cpp, "_SQUADS_PATH", squads)
    monkeypatch.setattr(cpp, "_squads_cache", None)

    _patch(monkeypatch,
           {"Home API": [_rate(1, "Stayed", "Home API"),
                         _rate(2, "Transferred", "Home API")]},
           {"Home FC": "Home API"})
    match = SimpleNamespace(home_team="Home FC", away_team="Away FC",
                            home_goals=None, away_goals=None, match_date="2026-08-04")
    out = club_player_props(_FakeDB(), match, SimpleNamespace(
        poisson_lambda_home=1.5, poisson_lambda_away=1.5))
    assert [p["player_name"] for p in out["teams"]["Home FC"]] == ["Stayed"]


def test_missing_squad_file_leaves_props_unfiltered(monkeypatch, tmp_path):
    """No roster data must mean "no filter", never "filter everyone out"."""
    import backend.app.ml.club_player_props as cpp

    monkeypatch.setattr(cpp, "_SQUADS_PATH", tmp_path / "does_not_exist.json")
    monkeypatch.setattr(cpp, "_squads_cache", None)

    _patch(monkeypatch,
           {"Home API": [_rate(1, "A", "Home API"), _rate(2, "B", "Home API")]},
           {"Home FC": "Home API"})
    match = SimpleNamespace(home_team="Home FC", away_team="Away FC",
                            home_goals=None, away_goals=None, match_date="2026-08-04")
    out = club_player_props(_FakeDB(), match, SimpleNamespace(
        poisson_lambda_home=1.5, poisson_lambda_away=1.5))
    assert len(out["teams"]["Home FC"]) == 2
