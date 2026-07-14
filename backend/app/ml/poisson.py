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


def _score_matrix(
    lam_h: float,
    lam_a: float,
    rho: float = 0.0,
    diag: float = 1.0,
    diag0: float = 1.0,
    max_goals: int = MAX_GOALS,
) -> "list[list[float]]":
    """Normalised score matrix: independent Poisson × Dixon-Coles τ × two draw
    adjustment factors — `diag0` scales the 0-0 cell (NG draw), `diag` scales
    the scoring draws (1-1, 2-2, …). The split gives fit_lambdas_to_probs()
    independent control over P(draw) and P(btts), which a single uniform
    diagonal factor (or ρ alone) cannot reconcile."""
    hp = [_poisson_pmf(i, lam_h) for i in range(max_goals + 1)]
    ap = [_poisson_pmf(j, lam_a) for j in range(max_goals + 1)]

    def _f(i: int, j: int) -> float:
        if i != j:
            return 1.0
        return diag0 if i == 0 else diag

    m = [[hp[i] * ap[j] * _dc_tau(i, j, lam_h, lam_a, rho) * _f(i, j)
          for j in range(max_goals + 1)] for i in range(max_goals + 1)]
    total = sum(sum(r) for r in m)
    if total > 0:
        m = [[v / total for v in r] for r in m]
    return m


def _matrix_summary(m: "list[list[float]]") -> dict:
    n = len(m)
    s = {"home_win": 0.0, "draw": 0.0, "away_win": 0.0, "over_2_5": 0.0, "btts": 0.0}
    for i in range(n):
        for j in range(n):
            p = m[i][j]
            if i > j:   s["home_win"] += p
            elif i == j: s["draw"]    += p
            else:        s["away_win"] += p
            if i + j > 2.5:      s["over_2_5"] += p
            if i >= 1 and j >= 1: s["btts"]    += p
    return s


def fit_lambdas_to_probs(
    p_home: float,
    p_away: float,
    p_over: float,
    p_btts: "float | None" = None,
    max_goals: int = MAX_GOALS,
) -> "tuple[float, float, float, float, float] | None":
    """
    Solve (λ_home, λ_away, ρ, diag, diag0) so the score matrix REPRODUCES the
    served match probabilities. Used by the analysis panels so the correct-score
    grid / combo markets / goal lines cohere with the headline 1×2 / Over / BTTS
    numbers instead of coming from an independent engine (raw Elo or
    feature-state λ), which made e.g. "GG+Over 41%" sit next to "NG 65%".

    Four knobs ↔ four targets, each 1-D monotone, solved by coordinate
    bisection sweeps (weakly coupled — 3 sweeps converge):
      total T = λh+λa      ←  P(over 2.5)
      diff  D = λh−λa      ←  P(home) − P(away)
      diag  (1-1, 2-2, …)  ←  P(btts)   (scoring draws; optional target)
      diag0 (0-0)          ←  P(draw)   (the btts-neutral draw mass)

    ρ is fixed at 0 — the two diagonal factors supersede it here. Returns None
    when inputs are unusable (NaN / degenerate).
    """
    try:
        p_home, p_away, p_over = float(p_home), float(p_away), float(p_over)
    except (TypeError, ValueError):
        return None
    if not (0.0 < p_over < 1.0) or math.isnan(p_home) or math.isnan(p_away):
        return None
    p_draw = 1.0 - p_home - p_away
    if not (0.005 < p_draw < 0.95):
        return None
    supremacy = p_home - p_away
    want_btts = None
    if p_btts is not None:
        try:
            b = float(p_btts)
            if 0.0 < b < 1.0 and not math.isnan(b):
                want_btts = b
        except (TypeError, ValueError):
            pass

    def _summary(T, D, diag, diag0):
        lh = max(0.05, (T + D) / 2.0)
        la = max(0.05, (T - D) / 2.0)
        return _matrix_summary(_score_matrix(lh, la, 0.0, diag, diag0, max_goals))

    T, D, diag, diag0 = 2.6, 0.0, 1.0, 1.0
    for _ in range(3):  # coordinate sweeps
        lo, hi = 0.3, 8.0                      # T ← over 2.5
        for _i in range(28):
            mid = (lo + hi) / 2.0
            if _summary(mid, D, diag, diag0)["over_2_5"] < p_over: lo = mid
            else: hi = mid
        T = (lo + hi) / 2.0
        lo, hi = -(T - 0.1), (T - 0.1)         # D ← supremacy
        for _i in range(28):
            mid = (lo + hi) / 2.0
            s = _summary(T, mid, diag, diag0)
            if s["home_win"] - s["away_win"] < supremacy: lo = mid
            else: hi = mid
        D = (lo + hi) / 2.0
        if want_btts is not None:              # diag ← btts (btts ↑ as diag ↑)
            lo, hi = 0.15, 4.0
            for _i in range(26):
                mid = (lo + hi) / 2.0
                if _summary(T, D, mid, diag0)["btts"] < want_btts: lo = mid
                else: hi = mid
            diag = (lo + hi) / 2.0
        lo, hi = 0.15, 6.0                     # diag0 ← draw (0-0 is btts-neutral)
        for _i in range(26):
            mid = (lo + hi) / 2.0
            if _summary(T, D, diag, mid)["draw"] < p_draw: lo = mid
            else: hi = mid
        diag0 = (lo + hi) / 2.0

    lam_h = max(0.05, (T + D) / 2.0)
    lam_a = max(0.05, (T - D) / 2.0)
    return lam_h, lam_a, 0.0, diag, diag0


def compute_extended_poisson_stats(
    lambda_home: float,
    lambda_away: float,
    max_goals: int = MAX_GOALS,
    top_n_scores: int = 6,
    rho: float = 0.0,
    diag: float = 1.0,
    diag0: float = 1.0,
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
    # Same normalised Dixon-Coles(+draw-inflation) matrix as the fitter — the
    # combo/low-score numbers here must agree with the probabilities the λ/ρ/diag
    # were solved against.
    m = _score_matrix(lambda_home, lambda_away, rho, diag, diag0, max_goals)

    over_1_5 = over_2_5 = over_3_5 = 0.0
    home_over_1_5 = away_over_1_5 = 0.0
    btts_and_over = btts_and_under = 0.0
    home_win_btts = away_win_btts = 0.0
    home_win_ng = away_win_ng = 0.0
    score_probs: dict[str, float] = {}

    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = m[i][j]
            total = i + j
            btts  = i >= 1 and j >= 1

            if total >= 2:          over_1_5      += p
            if total >= 3:          over_2_5      += p
            if total >= 4:          over_3_5      += p
            if i >= 2:              home_over_1_5 += p
            if j >= 2:              away_over_1_5 += p
            if btts and total >= 3: btts_and_over += p
            if btts and total <= 2: btts_and_under += p  # only (1,1)
            if btts and i > j:          home_win_btts += p
            if btts and j > i:          away_win_btts += p
            if not btts and i > j:      home_win_ng   += p   # home wins, only home scores (e.g. 1-0, 2-0)
            if not btts and j > i:      away_win_ng   += p   # away wins, only away scores (e.g. 0-1, 0-2)

            score_probs[f"{i}-{j}"] = p

    ranked_scores = sorted(score_probs.items(), key=lambda x: x[1], reverse=True)
    top_scores = [
        {"score": s, "prob": round(p, 4)}
        for s, p in ranked_scores[:top_n_scores]
    ]

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
