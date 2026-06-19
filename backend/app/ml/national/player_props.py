"""
Player-prop model for national-team fixtures.

From per-player match logs (player_match_stats) we estimate recency-weighted
per-90 rates for goals, shots-on-target and assists, then convert them into
match probabilities given the team's expected goals.

Two modelling safeguards:
  • Recency weighting — exponential half-life (form matters more than 2y-old data).
  • Empirical-Bayes shrinkage — a player's rate is pulled toward a positional
    prior with strength K (pseudo-minutes); small samples (a sub who scored once)
    regress to the prior instead of topping the charts.

Match probabilities:
  scorer    λ = team_xg × player_goal_share         → P(≥1) = 1 − e^−λ
  SoT       λ = sot/90 × expected_minutes/90        → P(≥1), P(≥2)
  assist    λ = ast/90 × expected_minutes/90 × team_xg/avg_team_goals → P(≥1)

Team expected goals come from the Elo engine shared with the WC simulator, so
the player layer is consistent with the match model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

HALF_LIFE_DAYS = 540.0          # form recency
PRIOR_G90      = 0.18           # league-wide outfield goal rate (per 90)
PRIOR_SOT90    = 0.55
PRIOR_AST90    = 0.13
SHRINK_MINUTES = 360.0          # pseudo-minutes of prior evidence (≈4 matches)
MIN_WEIGHTED_MIN = 90.0         # below this we basically return the prior
AVG_TEAM_GOALS = 1.35           # reference for assist scaling


@dataclass
class PlayerRate:
    player_id: int
    player: str
    team: str
    g90: float
    sot90: float
    ast90: float
    exp_minutes: float          # expected minutes next match (recent avg, capped)
    wmin: float                 # weighted minutes of evidence
    apps: int


def _shrink(weighted_events: float, weighted_minutes: float, prior_per90: float) -> float:
    """Empirical-Bayes per-90 rate: add SHRINK_MINUTES of prior evidence."""
    num = weighted_events + prior_per90 / 90.0 * SHRINK_MINUTES
    den = weighted_minutes + SHRINK_MINUTES
    return 90.0 * num / den if den > 0 else prior_per90


def load_player_rates(db, as_of: date | None = None) -> dict[str, list[PlayerRate]]:
    """Return {team: [PlayerRate, …]} from player_match_stats, recency+shrinkage."""
    from sqlalchemy import text

    rows = db.execute(text(
        "SELECT player_id, player_name, team, match_date, minutes, goals, shots_on, assists "
        "FROM player_match_stats"
    )).fetchall()
    if not rows:
        return {}

    df = pd.DataFrame(rows, columns=["pid", "player", "team", "date", "min", "g", "sot", "a"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["min"] = df["min"].fillna(0).clip(lower=0)
    ref = pd.Timestamp(as_of) if as_of else pd.Timestamp.today()
    age = (ref - df["date"]).dt.days.clip(lower=0)
    df = df[age <= 365 * 3]                       # ignore very old logs
    age = (ref - df["date"]).dt.days.clip(lower=0)
    df["w"] = np.exp(-np.log(2) * age / HALF_LIFE_DAYS)

    out: dict[str, list[PlayerRate]] = {}
    for (pid, player, team), g in df.groupby(["pid", "player", "team"]):
        wmin = float((g["min"] * g["w"]).sum())
        wg   = float((g["g"]   * g["w"]).sum())
        wsot = float((g["sot"] * g["w"]).sum())
        wast = float((g["a"]   * g["w"]).sum())
        # expected minutes = recency-weighted average minutes, capped at 90
        exp_min = float(min(90.0, (g["min"] * g["w"]).sum() / max(g["w"].sum(), 1e-9)))
        out.setdefault(team, []).append(PlayerRate(
            player_id=int(pid), player=player, team=team,
            g90=_shrink(wg, wmin, PRIOR_G90),
            sot90=_shrink(wsot, wmin, PRIOR_SOT90),
            ast90=_shrink(wast, wmin, PRIOR_AST90),
            exp_minutes=exp_min, wmin=wmin, apps=int(len(g)),
        ))
    return out


def load_team_card_rates(db, as_of: date | None = None) -> dict[str, float]:
    """{team: recency-weighted expected yellow+red cards per match}."""
    from sqlalchemy import text

    rows = db.execute(text(
        "SELECT team, fixture_id, match_date, "
        "       SUM(COALESCE(yellow,0)) + SUM(COALESCE(red,0)) AS cards "
        "FROM player_match_stats GROUP BY team, fixture_id, match_date"
    )).fetchall()
    if not rows:
        return {}
    df = pd.DataFrame(rows, columns=["team", "fixture", "date", "cards"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    ref = pd.Timestamp(as_of) if as_of else pd.Timestamp.today()
    age = (ref - df["date"]).dt.days.clip(lower=0)
    df = df[age <= 365 * 3]
    df["w"] = np.exp(-np.log(2) * (ref - df["date"]).dt.days.clip(lower=0) / HALF_LIFE_DAYS)
    out: dict[str, float] = {}
    for team, g in df.groupby("team"):
        wsum = g["w"].sum()
        if wsum > 0:
            # Shrink toward a 2.0-cards prior with ~3 matches of evidence.
            out[team] = float((( g["cards"] * g["w"]).sum() + 2.0 * 3) / (wsum + 3))
    return out


def load_team_corner_rates(db, as_of: date | None = None) -> dict[str, float]:
    """{team: recency-weighted expected corners per match} from team_match_stats."""
    from sqlalchemy import text

    rows = db.execute(text(
        "SELECT team, match_date, corners FROM team_match_stats "
        "WHERE corners IS NOT NULL"
    )).fetchall()
    if not rows:
        return {}
    df = pd.DataFrame(rows, columns=["team", "date", "corners"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    ref = pd.Timestamp(as_of) if as_of else pd.Timestamp.today()
    age = (ref - df["date"]).dt.days.clip(lower=0)
    df = df[age <= 365 * 3]
    df["w"] = np.exp(-np.log(2) * (ref - df["date"]).dt.days.clip(lower=0) / HALF_LIFE_DAYS)
    out: dict[str, float] = {}
    for team, g in df.groupby("team"):
        wsum = g["w"].sum()
        if wsum > 0:
            # Shrink toward a 5.0-corners prior with ~3 matches of evidence.
            out[team] = float(((g["corners"] * g["w"]).sum() + 5.0 * 3) / (wsum + 3))
    return out


def corners_over_prob(exp_total: float, line: float = 9.5) -> float:
    """Poisson P(total corners > line) given the expected total corners."""
    if exp_total <= 0:
        return 0.0
    k_max = math.floor(line)                      # P(X > 9.5) = 1 − P(X ≤ 9)
    cdf = sum(math.exp(-exp_total) * exp_total ** k / math.factorial(k)
              for k in range(k_max + 1))
    return max(0.0, min(1.0, 1.0 - cdf))


def _p_at_least_1(lmbda: float) -> float:
    return 1.0 - math.exp(-max(lmbda, 0.0))


def _p_at_least_2(lmbda: float) -> float:
    lmbda = max(lmbda, 0.0)
    return 1.0 - math.exp(-lmbda) * (1.0 + lmbda)


def compute_props(
    rates: list[PlayerRate],
    team_xg: float,
    min_exp_minutes: float = 35.0,
    min_apps: int = 3,
) -> list[dict]:
    """
    Convert a team's player rates into match props given team expected goals.

    Goal share: a player's shrunk g90 weighted by expected minutes, normalised
    across the squad, then × team_xg → expected goals this match.
    """
    pool = [r for r in rates if r.exp_minutes >= min_exp_minutes and r.apps >= min_apps]
    if not pool:
        return []

    # Expected goal contribution ∝ g90 × minutes share → normalise to team_xg.
    raw = [r.g90 * (r.exp_minutes / 90.0) for r in pool]
    tot = sum(raw) or 1.0
    props = []
    for r, contrib in zip(pool, raw):
        player_xg = team_xg * contrib / tot
        m = r.exp_minutes / 90.0
        sot_lambda = r.sot90 * m
        ast_lambda = r.ast90 * m * (team_xg / AVG_TEAM_GOALS)
        props.append({
            "player_id":   r.player_id,
            "player":      r.player,
            "team":        r.team,
            "exp_minutes": round(r.exp_minutes, 1),
            "exp_goals":   round(player_xg, 3),
            "p_score":     round(_p_at_least_1(player_xg), 4),
            "p_sot_1":     round(_p_at_least_1(sot_lambda), 4),
            "p_sot_2":     round(_p_at_least_2(sot_lambda), 4),
            "p_assist":    round(_p_at_least_1(ast_lambda), 4),
        })
    props.sort(key=lambda x: x["p_score"], reverse=True)
    return props
