"""
Live per-player prop probabilities (scorer / shots-on-target / assist) for a
CLUB fixture — the club counterpart of the national player_props table.

Unlike the national side (which persists rows in player_props keyed on
national_prediction_id), club props are computed at request time straight from
player_match_stats. That needs no schema change and no nightly compute step:
the same recency-weighted + shrunk rate engine (national.player_props) is reused,
and our team names are mapped to the API-Football club names under which the
club rows are stored (via club_props._api_name).

Returns the same shape the frontend PlayerPropsPanel already consumes:
    {"teams": {display_name: [prop, …]}, "finished": bool}
For FINISHED matches each prop is settled against player_match_stats actuals.
"""
from __future__ import annotations

from datetime import datetime, timedelta

# Club goal environment for the Elo→λ fallback (national uses 2.65; club scoring
# runs a touch higher). Only used when the model's Poisson λ are unavailable.
MU_TOTAL, ELO_SCALE = 2.70, 220.0


def _date_window(d, days: int = 1) -> tuple[str, str]:
    base = datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
    return (base - timedelta(days=days)).isoformat(), (base + timedelta(days=days)).isoformat()


def club_player_props(db, match, prediction=None) -> dict:
    """Compute club player props for `match`. `prediction` (if given) supplies the
    model's Poisson λ; otherwise λ is derived from current club Elo."""
    from sqlalchemy import bindparam, text

    from backend.app.ml.club_props import _api_name
    from backend.app.ml.national.player_props import compute_props, load_player_rates

    ah = _api_name(db, match.home_team)
    aa = _api_name(db, match.away_team)
    if not ah and not aa:
        return {"teams": {}, "finished": False}

    # λ: prefer the model's Poisson lambdas; else derive from club Elo.
    lam_h = getattr(prediction, "poisson_lambda_home", None) if prediction else None
    lam_a = getattr(prediction, "poisson_lambda_away", None) if prediction else None
    if not lam_h or not lam_a or lam_h <= 0 or lam_a <= 0:
        from backend.app.ml.club_elo import club_elo_pair
        pair = club_elo_pair(db, match.home_team, match.away_team)
        if pair:
            gd = (pair[0] - pair[1]) / ELO_SCALE
            lam_h = max(0.2, MU_TOTAL / 2 + gd / 2)
            lam_a = max(0.2, MU_TOTAL / 2 - gd / 2)
        else:
            lam_h = lam_a = MU_TOTAL / 2

    rates = load_player_rates(db)
    teams: dict[str, list[dict]] = {}
    for our_name, api_name, team_xg in ((match.home_team, ah, lam_h), (match.away_team, aa, lam_a)):
        if not api_name:
            continue
        props = []
        for p in compute_props(rates.get(api_name, []), team_xg):
            props.append({
                "team":        our_name,
                "player_name": p["player"],
                "player_id":   p["player_id"],
                "exp_minutes": p["exp_minutes"],
                "exp_goals":   p["exp_goals"],
                "p_score":     p["p_score"],
                "p_sot_1":     p["p_sot_1"],
                "p_sot_2":     p["p_sot_2"],
                "p_assist":    p["p_assist"],
            })
        if props:
            teams[our_name] = props

    finished = match.home_goals is not None and match.away_goals is not None
    if finished and teams:
        lo, hi = _date_window(match.match_date)
        api_teams = [t for t in (ah, aa) if t]
        stmt = text(
            "SELECT player_id, minutes, goals, shots_on, assists "
            "FROM player_match_stats WHERE match_date BETWEEN :lo AND :hi AND team IN :teams"
        ).bindparams(bindparam("teams", expanding=True))
        actuals: dict[int, dict] = {
            s.player_id: {"minutes": s.minutes, "goals": s.goals,
                          "shots_on": s.shots_on, "assists": s.assists}
            for s in db.execute(stmt, {"lo": lo, "hi": hi, "teams": api_teams}).fetchall()
        }
        settled = bool(actuals)
        for plist in teams.values():
            for p in plist:
                a = actuals.get(p["player_id"])
                if a:
                    p["played"]         = (a["minutes"] or 0) > 0
                    p["actual_minutes"] = a["minutes"]
                    p["actual_goals"]   = a["goals"]
                    p["actual_sot"]     = a["shots_on"]
                    p["actual_assists"] = a["assists"]
                    p["score_hit"]      = (a["goals"]    or 0) >= 1
                    p["sot_hit"]        = (a["shots_on"] or 0) >= 1
                    p["assist_hit"]     = (a["assists"]  or 0) >= 1
                elif settled:
                    p["played"] = False   # match over but this player didn't appear
        finished = settled

    # Drop the internal player_id before returning (frontend keys on player_name).
    for plist in teams.values():
        for p in plist:
            p.pop("player_id", None)
    return {"teams": teams, "finished": finished}
