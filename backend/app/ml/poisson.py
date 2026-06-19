"""
Poisson expected-goals model — stacked features for XGBoost.

Theory (Dixon & Coles 1997):
  λ_home = home_attack × away_defense × avg_home_goals(season, league)
  λ_away = away_attack × home_defense × avg_away_goals(season, league)
  P(score i-j) ∝ Poisson(i; λ_home) × Poisson(j; λ_away) × τ(i,j)

where τ(i,j) is the Dixon-Coles low-score correction that fixes the known
positive correlation in near-zero scores (0-0, 1-0, 0-1, 1-1 occur more
often than independent Poisson predicts).

All strengths are season-specific and computed ONLY from matches played BEFORE
the target match (expanding window — no data leakage).

Why this adds value on top of Pi-Ratings already in features.py:
  - Pi-Ratings are cumulative across seasons; Poisson resets each season.
  - Season-specific normalisation captures relative strength THIS season.
  - Poisson gives BTTS and over/under from proper distributions (not just rolling avg).
  - λ values capture a different signal than Pi-Rating expected-goal estimates.
  - XGBoost can learn when to trust each model by seeing both as features.

Usage (same expand-window pattern as Elo / Pi-Ratings):
    state = PoissonState()
    for _, row in df.sort_values("Date").iterrows():
        season = season_from_date(row["Date"])
        feat.update(state.features(home, away, league, season))  # BEFORE update
        # ... other features ...
        state.update(home, away, hg, ag, league, season)          # AFTER snapshot
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

# ── Constants ─────────────────────────────────────────────────────────────────

# Minimum league-wide matches before attack/defense strengths are meaningful.
# Below this → NaN features; XGBoost uses its learned NaN direction natively.
MIN_SEASON_MATCHES = 5

# Poisson truncation: P(k > MAX_GOALS) ≈ 0 for normal football λ values.
MAX_GOALS = 8

# Dixon-Coles (1997) low-score correlation correction.
# Football goals are NOT independent: 0-0, 1-1 occur ~10-15% more than
# independent Poisson predicts due to tactical adjustments, time-wasting, etc.
# ρ = -0.13 is the value estimated by Dixon & Coles on English league data;
# subsequent studies find -0.10 to -0.15 across European leagues.
DC_RHO = -0.13

# ── Helpers ───────────────────────────────────────────────────────────────────


def season_from_date(dt) -> str:
    """
    Return season string from a date. Season boundary = August.
    Any date Aug 2024 – Jul 2025  →  '2024/25'.
    Works with pandas Timestamp, datetime.date, or ISO string.
    """
    import datetime as _dt

    if hasattr(dt, "month"):
        month, year = int(dt.month), int(dt.year)
    else:
        d = _dt.date.fromisoformat(str(dt)[:10])
        month, year = d.month, d.year

    if month >= 8:
        return f"{year}/{str(year + 1)[-2:]}"
    return f"{year - 1}/{str(year)[-2:]}"


def _poisson_pmf(k: int, lam: float) -> float:
    """P(X = k) for Poisson(λ). Numerically stable for k ≤ MAX_GOALS."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _dc_tau(i: int, j: int, lam_h: float, lam_a: float, rho: float = DC_RHO) -> float:
    """
    Dixon-Coles correction factor τ(i,j) for low-score cells.

    Fixes the positive correlation between near-zero scores that independent
    Poisson underestimates.  Scores with i+j > 2 are unaffected (τ = 1.0).
    """
    if i == 0 and j == 0:
        return 1.0 - lam_h * lam_a * rho
    elif i == 1 and j == 0:
        return 1.0 + lam_a * rho
    elif i == 0 and j == 1:
        return 1.0 + lam_h * rho
    elif i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


def compute_poisson_probs(
    lambda_home: float,
    lambda_away: float,
    max_goals: int = MAX_GOALS,
    rho: float = DC_RHO,
) -> dict:
    """
    Compute match outcome probabilities from two Poisson λ parameters.

    Applies the Dixon-Coles (1997) low-score correction (τ factor) to fix the
    positive correlation in near-zero scores, then renormalises the score
    matrix to account for MAX_GOALS truncation.

    Returns dict with keys:
        home_win, draw, away_win  — 1×2 probabilities
        over_2_5                  — P(total goals > 2.5)
        btts                      — P(both teams score ≥ 1)
    """
    home_pmf = [_poisson_pmf(i, lambda_home) for i in range(max_goals + 1)]
    away_pmf = [_poisson_pmf(j, lambda_away) for j in range(max_goals + 1)]

    # Build corrected score matrix and normalise (truncation at MAX_GOALS means
    # the raw sum is slightly < 1; DC correction shifts mass among low scores).
    matrix_total = 0.0
    p_home = p_draw = p_away = p_over = p_btts = 0.0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = home_pmf[i] * away_pmf[j] * _dc_tau(i, j, lambda_home, lambda_away, rho)
            matrix_total += p
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
            if i + j > 2.5:
                p_over += p
            if i >= 1 and j >= 1:
                p_btts += p

    # Normalise so probabilities sum to 1 despite truncation + DC correction.
    if matrix_total > 0:
        p_home /= matrix_total
        p_draw /= matrix_total
        p_away /= matrix_total
        p_over /= matrix_total
        p_btts /= matrix_total

    return {
        "home_win": p_home,
        "draw":     p_draw,
        "away_win": p_away,
        "over_2_5": p_over,
        "btts":     p_btts,
    }


def compute_extended_poisson_stats(
    lambda_home: float,
    lambda_away: float,
    max_goals: int = MAX_GOALS,
    top_n_scores: int = 6,
) -> dict:
    """
    Compute extended Poisson-derived stats from two λ parameters.

    Builds the full (max_goals+1)² score matrix once and extracts:
      • Over/Under 1.5 and 3.5 goal lines
      • Team-specific Over/Under 1.5 (home/away scores 2+)
      • Top-N most likely correct scores
      • Combo markets: BTTS+O2.5, BTTS+U2.5, HomeWin+BTTS, AwayWin+BTTS

    Returns a dict ready for JSON serialisation.
    """
    home_pmf = [_poisson_pmf(i, lambda_home) for i in range(max_goals + 1)]
    away_pmf = [_poisson_pmf(j, lambda_away) for j in range(max_goals + 1)]

    over_1_5 = over_3_5 = 0.0
    home_over_1_5 = away_over_1_5 = 0.0
    btts_and_over = btts_and_under = 0.0
    home_win_btts = away_win_btts = 0.0
    home_win_ng = away_win_ng = 0.0
    score_probs: dict[str, float] = {}

    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = home_pmf[i] * away_pmf[j]
            total = i + j
            btts  = i >= 1 and j >= 1

            if total >= 2:          over_1_5      += p
            if total >= 4:          over_3_5      += p
            if i >= 2:              home_over_1_5 += p
            if j >= 2:              away_over_1_5 += p
            if btts and total >= 3: btts_and_over += p
            if btts and total <= 2: btts_and_under += p  # only (1,1)
            if btts and i > j:          home_win_btts += p
            if btts and j > i:          away_win_btts += p
            if not btts and i > j:      home_win_ng   += p   # home wins, only home scores (e.g. 1-0, 2-0)
            if not btts and j > i:      away_win_ng   += p   # away wins, only away scores (e.g. 0-1, 0-2)

            score_probs[f"{i}-{j}"] = score_probs.get(f"{i}-{j}", 0.0) + p

    ranked_scores = sorted(score_probs.items(), key=lambda x: x[1], reverse=True)
    top_scores = [
        {"score": s, "prob": round(p, 4)}
        for s, p in ranked_scores[:top_n_scores]
    ]

    # Over 2.5 from the score matrix (Poisson-consistent, used in Goals Lines
    # so all three lines come from the same model and numbers add up correctly).
    over_2_5 = sum(
        home_pmf[i] * away_pmf[j]
        for i in range(max_goals + 1)
        for j in range(max_goals + 1)
        if i + j > 2.5
    )

    return {
        "over_1_5":          round(over_1_5,       4),
        "under_1_5":         round(1 - over_1_5,   4),
        "over_2_5":          round(over_2_5,        4),
        "under_2_5":         round(1 - over_2_5,   4),
        "over_3_5":          round(over_3_5,        4),
        "under_3_5":         round(1 - over_3_5,   4),
        "home_over_1_5":     round(home_over_1_5,  4),
        "home_under_1_5":    round(1 - home_over_1_5, 4),
        "away_over_1_5":     round(away_over_1_5,  4),
        "away_under_1_5":    round(1 - away_over_1_5, 4),
        "top_scores":        top_scores,
        "most_likely_score": top_scores[0]["score"] if top_scores else None,
        "btts_and_over_2_5": round(btts_and_over,  4),
        "btts_and_under_2_5":round(btts_and_under, 4),
        "home_win_and_btts": round(home_win_btts,  4),
        "away_win_and_btts": round(away_win_btts,  4),
        "home_win_and_ng":   round(home_win_ng,    4),   # e.g. 1-0, 2-0, 3-0
        "away_win_and_ng":   round(away_win_ng,    4),   # e.g. 0-1, 0-2, 0-3
    }


def _nan_poisson() -> dict:
    """NaN Poisson feature dict — returned when data is insufficient."""
    return {
        "poisson_lambda_home":  np.nan,
        "poisson_lambda_away":  np.nan,
        "poisson_home_attack":  np.nan,
        "poisson_away_defense": np.nan,
        "poisson_home_win":     np.nan,
        "poisson_draw":         np.nan,
        "poisson_away_win":     np.nan,
        "poisson_over_2_5":     np.nan,
        "poisson_btts":         np.nan,
    }


# ── PoissonState ──────────────────────────────────────────────────────────────


class PoissonState:
    """
    Tracks season-level Poisson attack/defense strengths for all teams.

    State is keyed by (league, season) so it resets at each new season,
    capturing how teams are performing THIS season relative to league average.
    This is complementary to Pi-Ratings, which carry over between seasons.

    All dictionaries use composite tuple keys:
        league-wide:  (league, season)
        per-team:     (league, season, team)
    """

    def __init__(self, min_season_matches: int = MIN_SEASON_MATCHES):
        self._min = min_season_matches

        # League-wide running totals keyed by (league, season)
        self._lg_home_goals: dict = defaultdict(float)
        self._lg_away_goals: dict = defaultdict(float)
        self._lg_matches:    dict = defaultdict(int)

        # Per-team home performance keyed by (league, season, team)
        self._h_scored:   dict = defaultdict(float)   # goals scored at home
        self._h_conceded: dict = defaultdict(float)   # goals conceded at home
        self._h_n:        dict = defaultdict(int)     # home matches played

        # Per-team away performance keyed by (league, season, team)
        self._a_scored:   dict = defaultdict(float)   # goals scored away
        self._a_conceded: dict = defaultdict(float)   # goals conceded away
        self._a_n:        dict = defaultdict(int)     # away matches played

    # ── Public: snapshot (call BEFORE updating) ───────────────────────────────

    def features(
        self,
        home_team: str,
        away_team: str,
        league: str,
        season: str,
    ) -> dict:
        """
        Compute Poisson feature dict for a match.
        Returns NaN features when not enough season data exists yet.
        Must be called BEFORE update() for correct no-leakage behaviour.
        """
        ls = (league, season)
        n = self._lg_matches[ls]

        if n < self._min:
            return _nan_poisson()

        avg_h = self._lg_home_goals[ls] / n
        avg_a = self._lg_away_goals[ls] / n
        if avg_h <= 0 or avg_a <= 0:
            return _nan_poisson()

        lh = (league, season, home_team)
        la = (league, season, away_team)

        # Attack strength = goals scored per match / league avg (venue-specific)
        # Defense strength = goals conceded per match / league avg
        h_att = self._att(self._h_scored, self._h_n, lh, avg_h)
        a_def = self._def(self._a_conceded, self._a_n, la, avg_h)
        a_att = self._att(self._a_scored, self._a_n, la, avg_a)
        h_def = self._def(self._h_conceded, self._h_n, lh, avg_a)

        lam_h = float(np.clip(h_att * a_def * avg_h, 0.1, 6.0))
        lam_a = float(np.clip(a_att * h_def * avg_a, 0.1, 6.0))

        probs = compute_poisson_probs(lam_h, lam_a)

        return {
            "poisson_lambda_home":  lam_h,
            "poisson_lambda_away":  lam_a,
            "poisson_home_attack":  h_att,
            "poisson_away_defense": a_def,
            "poisson_home_win":     probs["home_win"],
            "poisson_draw":         probs["draw"],
            "poisson_away_win":     probs["away_win"],
            "poisson_over_2_5":     probs["over_2_5"],
            "poisson_btts":         probs["btts"],
        }

    # ── Public: update (call AFTER snapshotting) ──────────────────────────────

    def update(
        self,
        home_team: str,
        away_team: str,
        home_goals: int,
        away_goals: int,
        league: str,
        season: str,
    ) -> None:
        """
        Update running totals after a match result.
        Must be called AFTER features() for the same match row.
        """
        ls = (league, season)
        lh = (league, season, home_team)
        la = (league, season, away_team)

        self._lg_home_goals[ls] += home_goals
        self._lg_away_goals[ls] += away_goals
        self._lg_matches[ls]    += 1

        self._h_scored[lh]   += home_goals
        self._h_conceded[lh] += away_goals
        self._h_n[lh]        += 1

        self._a_scored[la]   += away_goals
        self._a_conceded[la] += home_goals
        self._a_n[la]        += 1

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _att(scored: dict, n_dict: dict, key: tuple, avg: float) -> float:
        """
        Attack strength relative to league average.
        Falls back to 1.0 (league average) when team has no venue-specific matches.
        """
        n = n_dict[key]
        if n > 0:
            return (scored[key] / n) / avg
        return 1.0  # neutral: assume league-average attack

    @staticmethod
    def _def(conceded: dict, n_dict: dict, key: tuple, avg: float) -> float:
        """
        Defense strength relative to league average.
        >1.0 means leaky defense; <1.0 means solid defense.
        Falls back to 1.0 when team has no venue-specific matches.
        """
        n = n_dict[key]
        if n > 0:
            return (conceded[key] / n) / avg
        return 1.0  # neutral: assume league-average defense


# ── Feature column list ────────────────────────────────────────────────────────

POISSON_FEATURE_COLS = [
    # Expected goals (the key inputs to Poisson)
    "poisson_lambda_home",   # λ for home team — expected goals scored at home
    "poisson_lambda_away",   # λ for away team — expected goals scored away
    # Intermediate strengths (useful as independent features too)
    "poisson_home_attack",   # home team attack vs league avg (>1 = strong attack)
    "poisson_away_defense",  # away team defense vs league avg (>1 = leaky defense)
    # Outcome probabilities from Poisson distribution
    "poisson_home_win",      # P(home wins) via Poisson score matrix
    "poisson_draw",          # P(draw) via Poisson score matrix
    "poisson_away_win",      # P(away wins) via Poisson score matrix
    "poisson_over_2_5",      # P(total goals > 2.5)
    "poisson_btts",          # P(both teams score ≥ 1 goal)
]
