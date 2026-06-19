"""
Feature engineering for match outcome prediction.

All features are computed using only information available *before* the match
(strict time-ordering). The DataFrame passed in must have a 'Date' column and
be sorted ascending by date before calling build_features().

Output columns (prefix h_ = home team, a_ = away team):
  Rolling 5 + 10-match windows for scored/conceded (all venues + venue-split)
  Rolling form (points) over 5 and 10 matches
  Head-to-head record (last 5 meetings)
  Elo ratings and diff
  Pi-Ratings: 4 ratings per team (home/away × attack/defense) — goal-based,
              more predictive than Elo because they use the margin of victory.
  League one-hot encoding
  Derived: goal diff rolling avg, attack/defence strength ratio
"""

from __future__ import annotations

import os
from collections import defaultdict, deque
from typing import Optional

import numpy as np
import pandas as pd

from backend.app.ml.poisson import (
    PoissonState,
    POISSON_FEATURE_COLS,
    _nan_poisson,
    season_from_date,
)

# ── Elo constants ─────────────────────────────────────────────────────────────
ELO_K     = 32      # K-factor
ELO_START = 1500    # Starting rating

# ── Pi-Rating constants (Constantinou & Fenton 2012) ─────────────────────────
# Each team has 4 ratings: home_att, home_def, away_att, away_def — all start at 0.
# Expected goals = PI_BASE × 10^((att − opp_def) / PI_K)
# At equal ratings (0 vs 0): expected goals = 1.5 each side.
PI_C     = 0.1   # learning rate — how fast ratings adjust after each match
PI_K     = 3.0   # scaling — sensitivity to rating differences
PI_BASE  = 1.5   # baseline expected goals at zero rating differential
PI_DECAY = 0.85  # season-boundary decay — reduce carry-over of stale ratings

_W5   = 5
_W10  = 10
_H2H_W = 10   # H2H window — wider than rolling because fixtures are less frequent
EWMA_ALPHA = 0.3   # exponential smoothing factor (~3.3-match effective window)

# ── Standings motivation config ────────────────────────────────────────────────
# cl         = number of top positions that grant CL / promotion
# relegation = number of bottom positions that are relegated / face playoff
LEAGUE_STAKES: dict[str, dict[str, int]] = {
    "EPL":          {"cl": 4,  "relegation": 3},
    "LaLiga":       {"cl": 4,  "relegation": 3},
    "SerieA":       {"cl": 4,  "relegation": 3},
    "Bundesliga":   {"cl": 4,  "relegation": 3},
    "Ligue1":       {"cl": 3,  "relegation": 3},
    "Championship": {"cl": 6,  "relegation": 3},   # top 2 auto + 4 playoff spots
    "GreekSL":      {"cl": 3,  "relegation": 4},
    "Eredivisie":   {"cl": 2,  "relegation": 3},
    "LeagueOne":    {"cl": 2,  "relegation": 4},
    "PrimeiraLiga": {"cl": 3,  "relegation": 3},
}

# Minimum referee-observed matches before we trust the rolling stats.
# Below this threshold all three ref features are returned as NaN.
_MIN_REF_MATCHES = 20


# ── Internal helpers ──────────────────────────────────────────────────────────

def _elo_expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))


def _elo_update(
    rating_home: float,
    rating_away: float,
    home_goals: int,
    away_goals: int,
) -> tuple[float, float]:
    """Return updated (home_rating, away_rating) after a match."""
    exp_home = _elo_expected(rating_home, rating_away)
    score_home = 1.0 if home_goals > away_goals else (0.5 if home_goals == away_goals else 0.0)
    new_home = rating_home + ELO_K * (score_home - exp_home)
    new_away = rating_away + ELO_K * ((1 - score_home) - (1 - exp_home))
    return new_home, new_away


def _pi_exp_goals(att: float, opp_def: float) -> float:
    """Pi-Rating expected goals: PI_BASE × 10^((att − opp_def) / PI_K)."""
    return PI_BASE * (10.0 ** ((att - opp_def) / PI_K))


# ── Season-phase features ─────────────────────────────────────────────────────

def _season_phase_features(date: "pd.Timestamp") -> dict:
    """
    Compute season-progress features from a match date.

    European football seasons run roughly August → May.
    week 0-11  → phase 1 (early season)
    week 12-23 → phase 2 (mid season)
    week 24+   → phase 3 (late season / run-in)
    """
    month, year = date.month, date.year
    # Season start = previous August
    season_start_year = year if month >= 8 else year - 1
    season_start = pd.Timestamp(season_start_year, 8, 1)
    days = max(0, (date - season_start).days)
    week = days // 7
    if week < 12:
        phase = 1
    elif week < 24:
        phase = 2
    else:
        phase = 3
    return {
        "season_week":              float(week),
        "season_phase":             float(phase),
        "days_since_season_start":  float(days),
    }


# ── Standings motivation helper ───────────────────────────────────────────────

_MOTIVATION_WINDOW = 6.0   # pts: within this gap from boundary → high jeopardy


def _motivation_feats(
    h: str,
    a: str,
    ranked: list,            # teams sorted best→worst (before this match)
    pts_dict: dict,          # {(league, season, team): pts}
    league: str,
    season: int,
    season_week: float,
) -> dict:
    """
    Compute 5 standings-motivation features for a match.

    h_pts_vs_cl         — home pts minus pts of team at CL/promotion cutoff rank
                          negative = home team is outside CL zone
    a_pts_vs_cl         — same for away team
    h_pts_vs_relegation — home pts minus pts of team at relegation cutoff rank
                          negative = home team is IN relegation zone
    a_pts_vs_relegation — same for away team
    motivation_diff     — composite (home stake − away stake) × season phase
                          positive = home team has more to play for

    Returns NaN dict when league not configured or < 3 teams ranked.
    """
    nan5: dict = {
        "h_pts_vs_cl": np.nan,        "a_pts_vs_cl": np.nan,
        "h_pts_vs_relegation": np.nan, "a_pts_vs_relegation": np.nan,
        "motivation_diff": np.nan,
    }
    stakes = LEAGUE_STAKES.get(league)
    n = len(ranked)
    if not stakes or n < 3:
        return nan5

    cl_rank  = min(stakes["cl"],  n) - 1          # 0-indexed
    rel_rank = max(0, n - stakes["relegation"]) - 1  # 0-indexed: first relegated spot

    cl_cutoff_pts  = pts_dict.get((league, season, ranked[cl_rank]),  0.0)
    rel_cutoff_pts = pts_dict.get((league, season, ranked[rel_rank]), 0.0)

    h_pts = pts_dict.get((league, season, h), np.nan)
    a_pts = pts_dict.get((league, season, a), np.nan)
    if np.isnan(h_pts) or np.isnan(a_pts):
        return nan5

    h_vs_cl  = float(h_pts - cl_cutoff_pts)
    a_vs_cl  = float(a_pts - cl_cutoff_pts)
    h_vs_rel = float(h_pts - rel_cutoff_pts)
    a_vs_rel = float(a_pts - rel_cutoff_pts)

    # Season phase: 0 (week 0) → 1 (week 38+)
    phase = min(1.0, season_week / 38.0) if (not np.isnan(season_week) and season_week >= 0) else 0.5

    def _stake(vs_cl: float, vs_rel: float) -> float:
        """Jeopardy score: high when close to or beyond a boundary."""
        # Rises from 0 (6+ pts above cutoff) to 1 (at cutoff) to >1 (below cutoff)
        s_cl  = max(0.0, _MOTIVATION_WINDOW - vs_cl)  / _MOTIVATION_WINDOW
        s_rel = max(0.0, _MOTIVATION_WINDOW - vs_rel) / _MOTIVATION_WINDOW
        return max(s_cl, s_rel) * phase

    return {
        "h_pts_vs_cl":          h_vs_cl,
        "a_pts_vs_cl":          a_vs_cl,
        "h_pts_vs_relegation":  h_vs_rel,
        "a_pts_vs_relegation":  a_vs_rel,
        "motivation_diff":      float(_stake(h_vs_cl, h_vs_rel) - _stake(a_vs_cl, a_vs_rel)),
    }


# ── Public API ────────────────────────────────────────────────────────────────

XG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "xg")


# Understat team name → our training-data name
_XG_TEAM_MAP: dict[str, str] = {
    # EPL
    "Manchester City":        "Man City",
    "Manchester United":      "Man United",
    "Newcastle United":       "Newcastle",
    "Nottingham Forest":      "Nott'm Forest",
    "Wolverhampton Wanderers":"Wolves",
    "Tottenham":              "Spurs",
    "West Ham":               "West Ham",
    "Sheffield United":       "Sheffield United",
    "Luton":                  "Luton",
    # LaLiga
    "Athletic Club":          "Ath Bilbao",
    "Atletico Madrid":        "Ath Madrid",
    "Barcelona":              "Barça",
    "Celta Vigo":             "Celta",
    "Rayo Vallecano":         "Vallecano",
    "Real Betis":             "Betis",
    "Real Sociedad":          "Sociedad",
    # SerieA
    "AC Milan":               "Milan",
    "Inter":                  "Inter",
    # Bundesliga
    "Bayern Munich":          "Bayern Munich",
    "Borussia Dortmund":      "B. Dortmund",
    "Borussia M.Gladbach":    "M'gladbach",
    "Eintracht Frankfurt":    "Ein Frankfurt",
    "FC Cologne":             "FC Koln",
    "RasenBallsport Leipzig": "RB Leipzig",
    "Mainz 05":               "Mainz",
    # Ligue1
    "Paris Saint Germain":    "Paris SG",
}


def _map_xg_team(name: str) -> str:
    return _XG_TEAM_MAP.get(name, name)


def load_xg_data(xg_dir: str) -> "pd.DataFrame | None":
    """
    Load all understat xG CSVs and return a single DataFrame with columns:
      date (datetime), league, home_team, away_team, home_xg, away_xg

    Team names are mapped to our training-data naming convention.
    Returns None if the xg_dir doesn't exist or contains no files.
    """
    import glob
    import os as _os

    if not _os.path.isdir(xg_dir):
        return None

    frames = []
    for path in sorted(glob.glob(_os.path.join(xg_dir, "*.csv"))):
        try:
            df = pd.read_csv(path)
            df["home_team"] = df["home_team"].map(_map_xg_team)
            df["away_team"] = df["away_team"].map(_map_xg_team)
            frames.append(df)
        except Exception as _xg_err:
            print(f"[warn] load_xg_data: skipping {path}: {_xg_err}")

    if not frames:
        return None

    combined = pd.concat(frames, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce")
    combined = combined.dropna(subset=["date", "home_team", "away_team", "home_xg", "away_xg"])
    combined["home_xg"] = pd.to_numeric(combined["home_xg"], errors="coerce")
    combined["away_xg"] = pd.to_numeric(combined["away_xg"], errors="coerce")
    return combined


def _slug(name: str) -> str:
    """
    Normalise a team name for fuzzy comparison.
    Strips accents, lower-cases, removes common suffixes (FC, CF, SC, AC, AS,
    AFC, RFC, FK, SK, BK, SV, VfB, 1., …) and keeps only alphanumeric chars.

    Examples:
      "Olympiacos FC"        → "olympiacos"
      "Borussia Dortmund"    → "borussiadortmund"
      "1. FC Köln"           → "fckoln"      (leading "1." stripped)
      "Paris Saint-Germain"  → "parisaintgermain"
    """
    import re
    import unicodedata

    # Remove accents
    nfkd = unicodedata.normalize("NFKD", name.lower())
    s = "".join(c for c in nfkd if not unicodedata.combining(c))

    # Remove common suffixes/prefixes that vary across data sources
    _noise = re.compile(
        r"\b(fc|cf|sc|ac|as|afc|rfc|fk|sk|bk|sv|vfb|vfl|fsv|ssv|tsg|"
        r"1\.|ssd|calcio|football|club|united|city|town|athletic|sport)\b"
    )
    s = _noise.sub("", s)

    # Keep alphanumeric only
    return re.sub(r"[^a-z0-9]", "", s)


def merge_xg(df: pd.DataFrame, xg_df: pd.DataFrame) -> pd.DataFrame:
    """
    Left-join xG data onto the main training DataFrame by date + team names.
    Adds home_xg / away_xg columns (NaN where no xG data exists).

    Matching strategy (per date+league):
      1. Exact match on team names (fast — covers understat CSVs perfectly).
      2. Slug (normalised) match as fallback — catches API-Football vs CSV name
         differences such as "Olympiacos FC" vs "Olympiacos" or
         "Borussia Dortmund" vs "B. Dortmund".
    """
    # ── Build exact-match lookup ──────────────────────────────────────────────
    xg_exact: dict[tuple, tuple] = {}
    for _, row in xg_df.iterrows():
        key = (row["date"].date(), row["league"], row["home_team"], row["away_team"])
        xg_exact[key] = (row["home_xg"], row["away_xg"])

    # ── Build slug-match lookup (date, league) → list of (h_slug, a_slug, pair) ─
    from collections import defaultdict
    xg_slug: dict[tuple, list] = defaultdict(list)
    for _, row in xg_df.iterrows():
        dk = (row["date"].date(), row["league"])
        xg_slug[dk].append((
            _slug(row["home_team"]),
            _slug(row["away_team"]),
            (row["home_xg"], row["away_xg"]),
        ))

    home_xg_vals, away_xg_vals = [], []
    fuzzy_hits = 0

    for _, row in df.iterrows():
        date_d  = row["Date"].date()
        league  = row["League"]
        home    = row["home_team"]
        away    = row["away_team"]

        # 1. Exact match
        key   = (date_d, league, home, away)
        pair  = xg_exact.get(key)

        # 2. Slug fallback
        if pair is None:
            h_slug = _slug(home)
            a_slug = _slug(away)
            for xh, xa, xpair in xg_slug.get((date_d, league), []):
                if xh == h_slug and xa == a_slug:
                    pair = xpair
                    fuzzy_hits += 1
                    break

        if pair:
            home_xg_vals.append(pair[0])
            away_xg_vals.append(pair[1])
        else:
            home_xg_vals.append(np.nan)
            away_xg_vals.append(np.nan)

    if fuzzy_hits:
        print(f"  [merge_xg] {fuzzy_hits} matches resolved via slug fallback "
              f"(API-Football name variants)")

    df = df.copy()
    df["home_xg"] = home_xg_vals
    df["away_xg"] = away_xg_vals
    return df


def load_raw_csvs(raw_dir: str) -> pd.DataFrame:
    """
    Read all CSVs in raw_dir, normalise column names, and return a single
    DataFrame sorted by date.
    """
    import glob
    import os

    frames = []
    for path in sorted(glob.glob(os.path.join(raw_dir, "*.csv"))):
        try:
            df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip")
        except Exception as e:
            print(f"[warn] Could not read {path}: {e}")
            continue

        basename = os.path.basename(path)
        league   = basename.split("_")[0]
        df["League"] = league
        frames.append(df)

    if not frames:
        raise RuntimeError(f"No CSV files found in {raw_dir}")

    data = pd.concat(frames, ignore_index=True)
    return _normalise(data)


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Standardise column names and types across football-data.co.uk CSVs."""
    rename = {
        "HomeTeam": "home_team",
        "AwayTeam": "away_team",
        "FTHG":     "home_goals",
        "FTAG":     "away_goals",
        "FTR":      "result",
    }
    df = df.rename(columns=rename)

    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, format="mixed", errors="coerce")
    # Strip whitespace from team names (some older CSVs have trailing spaces)
    for col in ("home_team", "away_team"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    df = df.dropna(subset=["Date", "home_team", "away_team", "home_goals", "away_goals"])
    df["home_goals"] = df["home_goals"].astype(int)
    df["away_goals"] = df["away_goals"].astype(int)

    for col, new in [("HST", "home_shots_ot"), ("AST", "away_shots_ot"),
                     ("HS",  "home_shots"),    ("AS",  "away_shots")]:
        df[new] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else np.nan

    # ── Pinnacle 1X2 odds (available ~2012/13+; NaN for older seasons) ─────────
    for src, dst in [("PSH", "psh"), ("PSD", "psd"), ("PSA", "psa")]:
        df[dst] = pd.to_numeric(df[src], errors="coerce") if src in df.columns else np.nan

    # ── Over/Under 2.5 odds — Pinnacle from 2019/20; avg market for 2012–2019 ──
    df["p_over"]  = pd.to_numeric(df["P>2.5"],  errors="coerce") if "P>2.5"  in df.columns else np.nan
    df["p_under"] = pd.to_numeric(df["P<2.5"],  errors="coerce") if "P<2.5"  in df.columns else np.nan
    # Back-fill with BbAv market average for seasons before Pinnacle OU existed
    if "BbAv>2.5" in df.columns:
        mask = df["p_over"].isna()
        df.loc[mask, "p_over"]  = pd.to_numeric(df.loc[mask, "BbAv>2.5"], errors="coerce")
    if "BbAv<2.5" in df.columns:
        mask = df["p_under"].isna()
        df.loc[mask, "p_under"] = pd.to_numeric(df.loc[mask, "BbAv<2.5"], errors="coerce")

    # ── Referee and card columns (EPL only; NaN for other leagues) ────────────
    for src, dst in [("Referee", "referee"),
                     ("HY", "h_yellow"), ("AY", "a_yellow"),
                     ("HR", "h_red"),    ("AR", "a_red")]:
        if src in df.columns:
            df[dst] = df[src]
        else:
            df[dst] = np.nan

    required = ["Date", "home_team", "away_team", "home_goals", "away_goals", "League",
                "home_shots_ot", "away_shots_ot", "home_shots", "away_shots",
                "psh", "psd", "psa", "p_over", "p_under",
                "referee", "h_yellow", "a_yellow", "h_red", "a_red"]
    df = df[required + [c for c in ["result"] if c in df.columns]].copy()
    return df.sort_values("Date").reset_index(drop=True)


def build_features(
    df: pd.DataFrame,
    european_df: "pd.DataFrame | None" = None,
) -> pd.DataFrame:
    """
    Walk through df in chronological order and compute features for every row
    using only past data.  Returns a new DataFrame with feature columns appended.

    Pi-Ratings are computed alongside Elo — they maintain separate attack and
    defense ratings for home and away contexts, updated after every match
    by the difference between actual and model-expected goals.

    european_df : optional European competition fixtures for congestion features.
    """
    df = df.sort_values("Date").reset_index(drop=True)

    def _dq(w): return lambda: deque(maxlen=w)

    # Rolling stats
    team_all_scored:    dict[str, deque] = defaultdict(_dq(_W5))
    team_all_conceded:  dict[str, deque] = defaultdict(_dq(_W5))
    team_home_scored:   dict[str, deque] = defaultdict(_dq(_W5))
    team_home_conceded: dict[str, deque] = defaultdict(_dq(_W5))
    team_away_scored:   dict[str, deque] = defaultdict(_dq(_W5))
    team_away_conceded: dict[str, deque] = defaultdict(_dq(_W5))
    team_points_5:      dict[str, deque] = defaultdict(_dq(_W5))
    team_total_goals_5: dict[str, deque] = defaultdict(_dq(_W5))
    team_over25_5:      dict[str, deque] = defaultdict(_dq(_W5))
    team_shots_ot_5:    dict[str, deque] = defaultdict(_dq(_W5))
    team_shots_ot_c_5:  dict[str, deque] = defaultdict(_dq(_W5))

    team_all_scored_10:    dict[str, deque] = defaultdict(_dq(_W10))
    team_all_conceded_10:  dict[str, deque] = defaultdict(_dq(_W10))
    team_home_scored_10:   dict[str, deque] = defaultdict(_dq(_W10))
    team_home_conceded_10: dict[str, deque] = defaultdict(_dq(_W10))
    team_away_scored_10:   dict[str, deque] = defaultdict(_dq(_W10))
    team_away_conceded_10: dict[str, deque] = defaultdict(_dq(_W10))
    team_points_10:        dict[str, deque] = defaultdict(_dq(_W10))
    team_total_goals_10:   dict[str, deque] = defaultdict(_dq(_W10))
    team_over25_10:        dict[str, deque] = defaultdict(_dq(_W10))

    # Draw-rate rolling windows (fraction of matches ending in a draw)
    team_draw_5:   dict[str, deque] = defaultdict(_dq(_W5))
    team_draw_10:  dict[str, deque] = defaultdict(_dq(_W10))

    # Elo
    elo: dict[str, float] = defaultdict(lambda: ELO_START)

    # Pi-Ratings — 4 floats per team, all starting at 0.0
    pi_home_att: dict[str, float] = defaultdict(float)  # home attack
    pi_home_def: dict[str, float] = defaultdict(float)  # home defense
    pi_away_att: dict[str, float] = defaultdict(float)  # away attack
    pi_away_def: dict[str, float] = defaultdict(float)  # away defense

    # H2H — stores tuples: (result_val, h_goals, a_goals, home_team)
    # result_val: 1=home win, 0=draw, -1=away win (from that match's home perspective)
    # home_team: the team playing at home IN THAT SPECIFIC PAST MATCH
    # Using _H2H_W=10 because H2H meetings are less frequent than regular league matches
    h2h: dict[frozenset, deque] = defaultdict(lambda: deque(maxlen=_H2H_W))

    # Poisson expected-goals state (season-specific, resets each new season)
    poisson = PoissonState()

    # Season tracking for Pi-Rating decay at season boundaries (D)
    _prev_season: Optional[str] = None

    # EWMA momentum (exponentially weighted moving average of goals and points)
    team_ewma_scored:   dict[str, float] = {}
    team_ewma_conceded: dict[str, float] = {}
    team_ewma_form:     dict[str, float] = {}

    # League standings (season-specific) — for normalized league position feature
    season_lg_pts:   dict = defaultdict(int)   # (league, season, team)
    season_lg_gd:    dict = defaultdict(int)   # (league, season, team)
    season_lg_teams: dict = defaultdict(set)   # (league, season) → set[team]

    # xG rolling windows (NaN-safe: only updated when understat data is present)
    team_xg_scored_5:    dict[str, deque] = defaultdict(_dq(_W5))
    team_xg_conceded_5:  dict[str, deque] = defaultdict(_dq(_W5))
    team_xg_scored_10:   dict[str, deque] = defaultdict(_dq(_W10))
    team_xg_conceded_10: dict[str, deque] = defaultdict(_dq(_W10))

    # Card / discipline rolling windows — suspension proxy
    # red_last1 = reds in most-recent match; rolling_5 = last 5 matches
    team_reds_5:    dict[str, deque] = defaultdict(_dq(_W5))
    team_yellows_5: dict[str, deque] = defaultdict(_dq(_W5))
    # Season-cumulative yellows keyed by (season, team) — resets each new season
    team_season_yellows: dict = defaultdict(int)  # (season, team) → int

    # Per-referee running totals (EPL only; other leagues have no Referee column)
    ref_matches:   dict[str, int]   = defaultdict(int)
    ref_home_wins: dict[str, int]   = defaultdict(int)
    ref_draws:     dict[str, int]   = defaultdict(int)
    ref_cards:     dict[str, float] = defaultdict(float)

    known_leagues = ["EPL", "LaLiga", "SerieA", "Bundesliga", "Ligue1", "GreekSL"]

    feature_rows = []

    for _, row in df.iterrows():
        h, a = row["home_team"], row["away_team"]
        hg, ag = row["home_goals"], row["away_goals"]
        league = row.get("League", "Unknown")

        feat: dict = {}

        def _mean(dq: deque) -> Optional[float]:
            return float(np.mean(list(dq))) if dq else np.nan

        # ── 5-match rolling ───────────────────────────────────────────────────
        feat["h_goals_scored_5"]   = _mean(team_all_scored[h])
        feat["h_goals_conceded_5"] = _mean(team_all_conceded[h])
        feat["a_goals_scored_5"]   = _mean(team_all_scored[a])
        feat["a_goals_conceded_5"] = _mean(team_all_conceded[a])

        feat["h_home_scored_5"]    = _mean(team_home_scored[h])
        feat["h_home_conceded_5"]  = _mean(team_home_conceded[h])
        feat["a_away_scored_5"]    = _mean(team_away_scored[a])
        feat["a_away_conceded_5"]  = _mean(team_away_conceded[a])

        feat["h_form_5"] = _mean(team_points_5[h])
        feat["a_form_5"] = _mean(team_points_5[a])

        # ── 10-match rolling ──────────────────────────────────────────────────
        feat["h_goals_scored_10"]   = _mean(team_all_scored_10[h])
        feat["h_goals_conceded_10"] = _mean(team_all_conceded_10[h])
        feat["a_goals_scored_10"]   = _mean(team_all_scored_10[a])
        feat["a_goals_conceded_10"] = _mean(team_all_conceded_10[a])

        feat["h_home_scored_10"]    = _mean(team_home_scored_10[h])
        feat["h_home_conceded_10"]  = _mean(team_home_conceded_10[h])
        feat["a_away_scored_10"]    = _mean(team_away_scored_10[a])
        feat["a_away_conceded_10"]  = _mean(team_away_conceded_10[a])

        feat["h_form_10"] = _mean(team_points_10[h])
        feat["a_form_10"] = _mean(team_points_10[a])

        # ── Derived goal diff ─────────────────────────────────────────────────
        def _gdiff(sc, cc):
            s, c = _mean(sc), _mean(cc)
            return (s - c) if (not np.isnan(s) and not np.isnan(c)) else np.nan

        feat["h_goal_diff_5"]  = _gdiff(team_all_scored[h], team_all_conceded[h])
        feat["a_goal_diff_5"]  = _gdiff(team_all_scored[a], team_all_conceded[a])
        feat["h_goal_diff_10"] = _gdiff(team_all_scored_10[h], team_all_conceded_10[h])
        feat["a_goal_diff_10"] = _gdiff(team_all_scored_10[a], team_all_conceded_10[a])

        # ── Expected goals (rolling-average based) ────────────────────────────
        hs5, hs10 = _mean(team_all_scored[h]),    _mean(team_all_scored_10[h])
        as5, as10 = _mean(team_all_scored[a]),    _mean(team_all_scored_10[a])
        hc5, hc10 = _mean(team_all_conceded[h]),  _mean(team_all_conceded_10[h])
        ac5, ac10 = _mean(team_all_conceded[a]),  _mean(team_all_conceded_10[a])

        def _avg(x, y):
            return (x + y) / 2 if (not np.isnan(x) and not np.isnan(y)) else np.nan

        feat["expected_home_goals_5"]  = _avg(hs5, ac5)
        feat["expected_away_goals_5"]  = _avg(as5, hc5)
        feat["expected_goals_5"]       = _avg(_avg(hs5, ac5), _avg(as5, hc5))
        feat["expected_home_goals_10"] = _avg(hs10, ac10)
        feat["expected_away_goals_10"] = _avg(as10, hc10)
        feat["expected_goals_10"]      = _avg(_avg(hs10, ac10), _avg(as10, hc10))

        feat["h_total_goals_5"]  = _mean(team_total_goals_5[h])
        feat["a_total_goals_5"]  = _mean(team_total_goals_5[a])
        feat["h_total_goals_10"] = _mean(team_total_goals_10[h])
        feat["a_total_goals_10"] = _mean(team_total_goals_10[a])

        feat["h_over25_rate_5"]  = _mean(team_over25_5[h])
        feat["a_over25_rate_5"]  = _mean(team_over25_5[a])
        feat["h_over25_rate_10"] = _mean(team_over25_10[h])
        feat["a_over25_rate_10"] = _mean(team_over25_10[a])

        # Draw-rate rolling windows
        feat["h_draw_rate_5"]  = _mean(team_draw_5[h])
        feat["a_draw_rate_5"]  = _mean(team_draw_5[a])
        feat["h_draw_rate_10"] = _mean(team_draw_10[h])
        feat["a_draw_rate_10"] = _mean(team_draw_10[a])

        feat["h_shots_ot_5"]  = _mean(team_shots_ot_5[h])
        feat["h_shots_otc_5"] = _mean(team_shots_ot_c_5[h])
        feat["a_shots_ot_5"]  = _mean(team_shots_ot_5[a])
        feat["a_shots_otc_5"] = _mean(team_shots_ot_c_5[a])

        # ── Pi-Rating decay at season boundaries (D) ──────────────────────────
        # Applied BEFORE any Pi-Rating read so the first match of a new season
        # sees decayed ratings (reflecting pre-season squad uncertainty).
        season = season_from_date(row["Date"])
        if _prev_season is not None and season != _prev_season:
            # Decay ALL known teams — union of home_att and away_att keys so
            # teams that only appeared as away side are not skipped.
            _all_teams = set(pi_home_att.keys()) | set(pi_away_att.keys())
            for _team in _all_teams:
                pi_home_att[_team] *= PI_DECAY
                pi_home_def[_team] *= PI_DECAY
                pi_away_att[_team] *= PI_DECAY
                pi_away_def[_team] *= PI_DECAY
        _prev_season = season

        # ── Elo ───────────────────────────────────────────────────────────────
        feat["h_elo"]           = elo[h]
        feat["a_elo"]           = elo[a]
        feat["elo_diff"]        = elo[h] - elo[a]
        feat["elo_home_win_prob"] = _elo_expected(elo[h], elo[a])

        # ── Pi-Ratings ────────────────────────────────────────────────────────
        # Snapshot ratings BEFORE the match (no leakage).
        h_att = pi_home_att[h]
        h_def = pi_home_def[h]
        a_att = pi_away_att[a]
        a_def = pi_away_def[a]

        feat["h_pi_att"] = h_att
        feat["h_pi_def"] = h_def
        feat["a_pi_att"] = a_att
        feat["a_pi_def"] = a_def

        # Attack vs opponent defense differential — key signal for result model
        feat["pi_att_diff"] = h_att - a_def   # positive → home has edge
        feat["pi_def_diff"] = a_att - h_def   # positive → away has edge

        # Model-implied expected goals — key signal for goals model
        pi_exp_h = _pi_exp_goals(h_att, a_def)
        pi_exp_a = _pi_exp_goals(a_att, h_def)
        feat["pi_exp_home"]  = pi_exp_h
        feat["pi_exp_away"]  = pi_exp_a
        feat["pi_exp_diff"]  = pi_exp_h - pi_exp_a  # home advantage in expected goals
        feat["pi_exp_total"] = pi_exp_h + pi_exp_a  # total expected goals (over/under signal)

        # ── H2H ──────────────────────────────────────────────────────────────
        # Each entry: (result_val, h_goals, a_goals, home_team_in_that_match)
        # Features computed from CURRENT home team's perspective (h = current home).
        key    = frozenset({h, a})
        h2h_hist = list(h2h[key])
        n_h2h  = len(h2h_hist)

        feat["h2h_count"] = n_h2h

        # Result counts: how many times has the CURRENT home team (h) won/lost/drawn
        feat["h2h_home_wins"] = sum(
            1 for (v, _, _, ht) in h2h_hist
            if (ht == h and v == 1) or (ht == a and v == -1)
        )
        feat["h2h_away_wins"] = sum(
            1 for (v, _, _, ht) in h2h_hist
            if (ht == a and v == 1) or (ht == h and v == -1)
        )
        h2h_draw_n        = sum(1 for (v, _, _, _) in h2h_hist if v == 0)
        feat["h2h_draws"]     = h2h_draw_n
        feat["h2h_draw_rate"] = (h2h_draw_n / n_h2h) if n_h2h else np.nan

        # Goals in H2H — perspective-aware
        if n_h2h:
            # h_sc: goals scored by current home team in each past H2H meeting
            h_sc     = [hg2 if ht == h else ag2 for (_, hg2, ag2, ht) in h2h_hist]
            a_sc     = [ag2 if ht == h else hg2 for (_, hg2, ag2, ht) in h2h_hist]
            totals   = [hg2 + ag2               for (_, hg2, ag2, _)  in h2h_hist]
            btts_arr = [1 if hg2 > 0 and ag2 > 0 else 0 for (_, hg2, ag2, _) in h2h_hist]
            feat["h2h_home_goals_avg"]  = float(np.mean(h_sc))
            feat["h2h_away_goals_avg"]  = float(np.mean(a_sc))
            feat["h2h_total_goals_avg"] = float(np.mean(totals))
            feat["h2h_btts_rate"]       = float(np.mean(btts_arr))
            feat["h2h_over25_rate"]     = float(np.mean([1 if t > 2.5 else 0 for t in totals]))
        else:
            feat["h2h_home_goals_avg"]  = np.nan
            feat["h2h_away_goals_avg"]  = np.nan
            feat["h2h_total_goals_avg"] = np.nan
            feat["h2h_btts_rate"]       = np.nan
            feat["h2h_over25_rate"]     = np.nan

        # ── Season phase (F) ──────────────────────────────────────────────────
        feat.update(_season_phase_features(row["Date"]))

        # ── League one-hot ────────────────────────────────────────────────────
        for lg in known_leagues:
            feat[f"league_{lg}"] = 1 if league == lg else 0

        # ── Referee features (EPL only; NaN for other leagues) ───────────────
        ref_name = row.get("referee")
        ref_name = ref_name if (isinstance(ref_name, str) and ref_name.strip()) else None
        if ref_name and ref_matches[ref_name] >= _MIN_REF_MATCHES:
            n = ref_matches[ref_name]
            feat["ref_home_win_rate"]  = ref_home_wins[ref_name] / n
            feat["ref_draw_rate"]      = ref_draws[ref_name] / n
            feat["ref_cards_per_game"] = ref_cards[ref_name] / n
        else:
            feat["ref_home_win_rate"]  = np.nan
            feat["ref_draw_rate"]      = np.nan
            feat["ref_cards_per_game"] = np.nan

        # ── xG rolling features (understat data, 2014/15+ for top-5 leagues) ──
        feat["h_xg_scored_5"]   = _mean(team_xg_scored_5[h])
        feat["h_xg_conceded_5"] = _mean(team_xg_conceded_5[h])
        feat["a_xg_scored_5"]   = _mean(team_xg_scored_5[a])
        feat["a_xg_conceded_5"] = _mean(team_xg_conceded_5[a])
        feat["h_xg_scored_10"]  = _mean(team_xg_scored_10[h])
        feat["h_xg_conceded_10"]= _mean(team_xg_conceded_10[h])
        feat["a_xg_scored_10"]  = _mean(team_xg_scored_10[a])
        feat["a_xg_conceded_10"]= _mean(team_xg_conceded_10[a])

        # ── Pinnacle market fair probabilities (vig removed) ──────────────────
        # Available ~2012/13+; NaN for older seasons and leagues without coverage.
        # No data leakage: bookmakers post these BEFORE kick-off.
        psh = row.get("psh", np.nan)
        psd = row.get("psd", np.nan)
        psa = row.get("psa", np.nan)
        if pd.notna(psh) and pd.notna(psd) and pd.notna(psa) and psh > 1 and psd > 1 and psa > 1:
            inv_h, inv_d, inv_a = 1.0 / psh, 1.0 / psd, 1.0 / psa
            tot = inv_h + inv_d + inv_a
            feat["market_home_prob"] = inv_h / tot
            feat["market_draw_prob"] = inv_d / tot
            feat["market_away_prob"] = inv_a / tot
        else:
            feat["market_home_prob"] = feat["market_draw_prob"] = feat["market_away_prob"] = np.nan

        po, pu = row.get("p_over", np.nan), row.get("p_under", np.nan)
        if pd.notna(po) and pd.notna(pu) and po > 1 and pu > 1:
            feat["market_over_prob"] = (1.0 / po) / (1.0 / po + 1.0 / pu)
        else:
            feat["market_over_prob"] = np.nan

        # ── Poisson features (snapshot BEFORE state update — no leakage) ──────
        feat.update(poisson.features(h, a, league, season))

        # ── Poisson fallback for missing market probs ─────────────────────────
        if np.isnan(feat.get("market_home_prob", np.nan)):
            feat["market_home_prob"] = feat.get("poisson_home_win", np.nan)
            feat["market_draw_prob"] = feat.get("poisson_draw",     np.nan)
            feat["market_away_prob"] = feat.get("poisson_away_win", np.nan)
        if np.isnan(feat.get("market_over_prob", np.nan)):
            feat["market_over_prob"] = feat.get("poisson_over_2_5", np.nan)

        # ── Draw-balance features ─────────────────────────────────────────────
        _h_sc5 = feat.get("h_goals_scored_5", np.nan)
        _a_sc5 = feat.get("a_goals_scored_5", np.nan)
        feat["goals_asymmetry_5"] = (
            abs(_h_sc5 - _a_sc5) if not (np.isnan(_h_sc5) or np.isnan(_a_sc5)) else np.nan
        )
        _h_dr5 = feat.get("h_draw_rate_5", np.nan)
        _a_dr5 = feat.get("a_draw_rate_5", np.nan)
        feat["combined_draw_tendency"] = (
            (_h_dr5 * _a_dr5) ** 0.5 if not (np.isnan(_h_dr5) or np.isnan(_a_dr5)) else np.nan
        )
        _pi_att_d = feat.get("pi_att_diff", np.nan)
        _pi_def_d = feat.get("pi_def_diff", np.nan)
        feat["pi_closeness"] = (
            1.0 / (1.0 + abs(_pi_att_d) + abs(_pi_def_d))
            if not (np.isnan(_pi_att_d) or np.isnan(_pi_def_d)) else np.nan
        )
        _mkt_d = feat.get("market_draw_prob", np.nan)
        _poi_d = feat.get("poisson_draw",     np.nan)
        feat["market_draw_edge"] = (
            _mkt_d - _poi_d if not (np.isnan(_mkt_d) or np.isnan(_poi_d)) else np.nan
        )
        _pi_total = feat.get("pi_exp_total", np.nan)
        # Use NaN when pi_exp_total is unknown — signals "no data", not "low goals".
        # 0.0 was a bug: the model read it as "definitely not a low-scoring game".
        feat["low_total_xg"] = (1.0 if _pi_total < 2.0 else 0.0) if not np.isnan(_pi_total) else np.nan
        _elo_d = feat.get("elo_diff", np.nan)
        feat["elo_closeness"] = (
            1.0 / (1.0 + abs(_elo_d)) if not np.isnan(_elo_d) else np.nan
        )

        # Odds drift: always 0.0 in training (no historical opening odds in CSVs).
        # Real values injected at inference from odds_history via compute_match_features.
        feat["odds_drift_home"] = 0.0
        feat["odds_drift_draw"] = 0.0
        feat["odds_drift_away"] = 0.0
        feat["odds_drift_over"] = 0.0
        feat["is_steam_home"]   = 0.0
        feat["is_steam_away"]   = 0.0

        # ── EWMA momentum features ────────────────────────────────────────────
        feat["h_ewma_scored"]   = team_ewma_scored.get(h, np.nan)
        feat["h_ewma_conceded"] = team_ewma_conceded.get(h, np.nan)
        feat["a_ewma_scored"]   = team_ewma_scored.get(a, np.nan)
        feat["a_ewma_conceded"] = team_ewma_conceded.get(a, np.nan)
        feat["h_ewma_form"]     = team_ewma_form.get(h, np.nan)
        feat["a_ewma_form"]     = team_ewma_form.get(a, np.nan)

        # ── Card / suspension proxy features ─────────────────────────────────
        # red_last1: 1 if team got a red card in their most recent match →
        #   at least one player is likely suspended this match.
        # reds_5: pattern of disciplinary issues / cumulative suspension risk.
        # discipline_5: (yellows + 2×reds) / 5 — cards-per-game rate over last 5.
        # season_yellows: accumulated yellows this season (threshold risk).
        # suspension_diff: home advantage/disadvantage from recent red cards.
        # NOTE: these are card-level proxies only; player-level injury data
        #       requires an external API (e.g. API-Football).
        _h_reds5 = list(team_reds_5[h])
        _a_reds5 = list(team_reds_5[a])
        _h_yels5 = list(team_yellows_5[h])
        _a_yels5 = list(team_yellows_5[a])
        feat["h_red_last1"]      = float(_h_reds5[-1]) if _h_reds5 else 0.0
        feat["a_red_last1"]      = float(_a_reds5[-1]) if _a_reds5 else 0.0
        feat["h_reds_5"]         = float(sum(_h_reds5))
        feat["a_reds_5"]         = float(sum(_a_reds5))
        feat["h_discipline_5"]   = (float(sum(_h_yels5)) + 2.0 * float(sum(_h_reds5))) / max(1, len(_h_reds5))
        feat["a_discipline_5"]   = (float(sum(_a_yels5)) + 2.0 * float(sum(_a_reds5))) / max(1, len(_a_reds5))
        feat["h_season_yellows"] = float(team_season_yellows.get((season, h), 0))
        feat["a_season_yellows"] = float(team_season_yellows.get((season, a), 0))
        feat["suspension_diff"]  = feat["h_red_last1"] - feat["a_red_last1"]

        # ── League position (current season table) ────────────────────────────
        _ls = (league, season)
        _ls_teams = season_lg_teams[_ls]
        if len(_ls_teams) >= 3:
            _ranked = sorted(
                _ls_teams,
                key=lambda t: (-season_lg_pts[(league, season, t)],
                               -season_lg_gd[(league, season, t)])
            )
            _n = len(_ranked)
            _h_rank = (_ranked.index(h) + 1) if h in _ranked else None
            _a_rank = (_ranked.index(a) + 1) if a in _ranked else None
            feat["h_league_pos_norm"] = _h_rank / _n if _h_rank is not None else np.nan
            feat["a_league_pos_norm"] = _a_rank / _n if _a_rank is not None else np.nan
            feat["league_pos_diff"]   = (
                feat["h_league_pos_norm"] - feat["a_league_pos_norm"]
                if (_h_rank and _a_rank) else np.nan
            )
            feat.update(_motivation_feats(
                h, a, _ranked, season_lg_pts,
                league, season, feat.get("season_week", np.nan),
            ))
        else:
            feat["h_league_pos_norm"] = np.nan
            feat["a_league_pos_norm"] = np.nan
            feat["league_pos_diff"]   = np.nan
            feat["h_pts_vs_cl"]          = np.nan
            feat["a_pts_vs_cl"]          = np.nan
            feat["h_pts_vs_relegation"]  = np.nan
            feat["a_pts_vs_relegation"]  = np.nan
            feat["motivation_diff"]      = np.nan

        feature_rows.append(feat)

        # ── Update state AFTER snapshot (no data leakage) ─────────────────────
        if hg > ag:
            result_val = 1;  h_pts, a_pts = 3, 0
        elif hg == ag:
            result_val = 0;  h_pts = a_pts = 1
        else:
            result_val = -1; h_pts, a_pts = 0, 3

        # Rolling windows
        for sc, cc, gs, gc in [
            (team_all_scored[h],    team_all_conceded[h],    hg, ag),
            (team_all_scored_10[h], team_all_conceded_10[h], hg, ag),
        ]:
            sc.append(gs); cc.append(gc)
        for sc, cc, gs, gc in [
            (team_all_scored[a],    team_all_conceded[a],    ag, hg),
            (team_all_scored_10[a], team_all_conceded_10[a], ag, hg),
        ]:
            sc.append(gs); cc.append(gc)

        team_home_scored[h].append(hg);    team_home_conceded[h].append(ag)
        team_home_scored_10[h].append(hg); team_home_conceded_10[h].append(ag)
        team_away_scored[a].append(ag);    team_away_conceded[a].append(hg)
        team_away_scored_10[a].append(ag); team_away_conceded_10[a].append(hg)

        team_points_5[h].append(h_pts);  team_points_5[a].append(a_pts)
        team_points_10[h].append(h_pts); team_points_10[a].append(a_pts)

        total_g = hg + ag
        team_total_goals_5[h].append(total_g);  team_total_goals_5[a].append(total_g)
        team_total_goals_10[h].append(total_g); team_total_goals_10[a].append(total_g)

        over25 = 1 if total_g > 2.5 else 0
        team_over25_5[h].append(over25);  team_over25_5[a].append(over25)
        team_over25_10[h].append(over25); team_over25_10[a].append(over25)

        drew = 1 if hg == ag else 0
        team_draw_5[h].append(drew);  team_draw_5[a].append(drew)
        team_draw_10[h].append(drew); team_draw_10[a].append(drew)

        hsot = row.get("home_shots_ot", np.nan)
        asot = row.get("away_shots_ot", np.nan)
        if pd.notna(hsot) and pd.notna(asot):
            team_shots_ot_5[h].append(float(hsot));  team_shots_ot_c_5[h].append(float(asot))
            team_shots_ot_5[a].append(float(asot));  team_shots_ot_c_5[a].append(float(hsot))

        hxg = row.get("home_xg", np.nan)
        axg = row.get("away_xg", np.nan)
        if pd.notna(hxg) and pd.notna(axg):
            team_xg_scored_5[h].append(float(hxg));  team_xg_conceded_5[h].append(float(axg))
            team_xg_scored_5[a].append(float(axg));  team_xg_conceded_5[a].append(float(hxg))
            team_xg_scored_10[h].append(float(hxg)); team_xg_conceded_10[h].append(float(axg))
            team_xg_scored_10[a].append(float(axg)); team_xg_conceded_10[a].append(float(hxg))

        h2h[key].append((result_val, int(hg), int(ag), h))

        # Referee state update (after snapshot — no leakage)
        if ref_name:
            ref_matches[ref_name] += 1
            if hg > ag:
                ref_home_wins[ref_name] += 1
            elif hg == ag:
                ref_draws[ref_name] += 1
            hy = float(row.get("h_yellow", 0) or 0)
            ay = float(row.get("a_yellow", 0) or 0)
            hr = float(row.get("h_red",    0) or 0)
            ar = float(row.get("a_red",    0) or 0)
            # Weight reds more heavily (2× yellow equivalent)
            ref_cards[ref_name] += hy + ay + 2 * hr + 2 * ar

        # Card / discipline state update (after snapshot — no leakage)
        _h_ry = float(row.get("h_red",    0) or 0) if pd.notna(row.get("h_red",    0)) else 0.0
        _a_ry = float(row.get("a_red",    0) or 0) if pd.notna(row.get("a_red",    0)) else 0.0
        _h_yy = float(row.get("h_yellow", 0) or 0) if pd.notna(row.get("h_yellow", 0)) else 0.0
        _a_yy = float(row.get("a_yellow", 0) or 0) if pd.notna(row.get("a_yellow", 0)) else 0.0
        team_reds_5[h].append(_h_ry);    team_reds_5[a].append(_a_ry)
        team_yellows_5[h].append(_h_yy); team_yellows_5[a].append(_a_yy)
        team_season_yellows[(season, h)] += int(_h_yy)
        team_season_yellows[(season, a)] += int(_a_yy)

        # Elo update
        new_h_elo, new_a_elo = _elo_update(elo[h], elo[a], hg, ag)
        elo[h] = new_h_elo
        elo[a] = new_a_elo

        # Pi-Rating update (goal-based, home/away specific)
        # err_h = actual home goals − expected home goals
        # err_a = actual away goals − expected away goals
        err_h = hg - pi_exp_h
        err_a = ag - pi_exp_a
        pi_home_att[h] += PI_C * err_h   # home team scored more/less than expected
        pi_away_def[a] -= PI_C * err_h   # away defense conceded more/less
        pi_away_att[a] += PI_C * err_a   # away team scored more/less than expected
        pi_home_def[h] -= PI_C * err_a   # home defense conceded more/less

        # Poisson state update (after snapshot — no data leakage)
        poisson.update(h, a, hg, ag, league, season)

        # EWMA update (after snapshot — no leakage)
        for _t, _gs, _gc, _pts in [(h, hg, ag, h_pts), (a, ag, hg, a_pts)]:
            team_ewma_scored[_t] = (
                float(_gs) if _t not in team_ewma_scored
                else EWMA_ALPHA * _gs + (1 - EWMA_ALPHA) * team_ewma_scored[_t]
            )
            team_ewma_conceded[_t] = (
                float(_gc) if _t not in team_ewma_conceded
                else EWMA_ALPHA * _gc + (1 - EWMA_ALPHA) * team_ewma_conceded[_t]
            )
            team_ewma_form[_t] = (
                float(_pts) if _t not in team_ewma_form
                else EWMA_ALPHA * _pts + (1 - EWMA_ALPHA) * team_ewma_form[_t]
            )

        # League standings update (after snapshot — no leakage)
        season_lg_teams[(league, season)].add(h)
        season_lg_teams[(league, season)].add(a)
        season_lg_pts[(league, season, h)] += h_pts
        season_lg_pts[(league, season, a)] += a_pts
        season_lg_gd[(league, season, h)] += hg - ag
        season_lg_gd[(league, season, a)] += ag - hg

    feat_df = pd.DataFrame(feature_rows, index=df.index)
    result = pd.concat([df, feat_df], axis=1)

    # ── European congestion features (optional) ────────────────────────────────
    if european_df is not None:
        from backend.app.ml.european import add_european_features
        result = add_european_features(result, european_df)

    return result


# ── Batch-prediction helpers ──────────────────────────────────────────────────

def build_team_snapshot(history_df: pd.DataFrame) -> dict:
    """
    Walk through history_df in chronological order and return a snapshot of all
    team state (Elo, Pi-Ratings, rolling deques, H2H) as of the last row.

    This is the fast path for batch predictions: call this ONCE on the full
    history, then call compute_match_features() for each upcoming fixture
    without replaying history each time.
    """
    df = history_df.sort_values("Date").reset_index(drop=True)

    def _dq(w): return lambda: deque(maxlen=w)

    team_all_scored:    dict = defaultdict(_dq(_W5))
    team_all_conceded:  dict = defaultdict(_dq(_W5))
    team_home_scored:   dict = defaultdict(_dq(_W5))
    team_home_conceded: dict = defaultdict(_dq(_W5))
    team_away_scored:   dict = defaultdict(_dq(_W5))
    team_away_conceded: dict = defaultdict(_dq(_W5))
    team_points_5:      dict = defaultdict(_dq(_W5))
    team_total_goals_5: dict = defaultdict(_dq(_W5))
    team_over25_5:      dict = defaultdict(_dq(_W5))
    team_shots_ot_5:    dict = defaultdict(_dq(_W5))
    team_shots_ot_c_5:  dict = defaultdict(_dq(_W5))

    team_all_scored_10:    dict = defaultdict(_dq(_W10))
    team_all_conceded_10:  dict = defaultdict(_dq(_W10))
    team_home_scored_10:   dict = defaultdict(_dq(_W10))
    team_home_conceded_10: dict = defaultdict(_dq(_W10))
    team_away_scored_10:   dict = defaultdict(_dq(_W10))
    team_away_conceded_10: dict = defaultdict(_dq(_W10))
    team_points_10:        dict = defaultdict(_dq(_W10))
    team_total_goals_10:   dict = defaultdict(_dq(_W10))
    team_over25_10:        dict = defaultdict(_dq(_W10))

    # Draw-rate rolling windows
    team_draw_5:  dict = defaultdict(_dq(_W5))
    team_draw_10: dict = defaultdict(_dq(_W10))

    elo: dict = defaultdict(lambda: ELO_START)
    pi_home_att: dict = defaultdict(float)
    pi_home_def: dict = defaultdict(float)
    pi_away_att: dict = defaultdict(float)
    pi_away_def: dict = defaultdict(float)
    h2h: dict = defaultdict(lambda: deque(maxlen=_H2H_W))

    # Poisson season-level state
    poisson = PoissonState()

    # xG rolling windows (only updated when understat data present)
    team_xg_scored_5:    dict = defaultdict(_dq(_W5))
    team_xg_conceded_5:  dict = defaultdict(_dq(_W5))
    team_xg_scored_10:   dict = defaultdict(_dq(_W10))
    team_xg_conceded_10: dict = defaultdict(_dq(_W10))

    # Card / discipline rolling windows — suspension proxy
    snap_reds_5:    dict = defaultdict(_dq(_W5))
    snap_yellows_5: dict = defaultdict(_dq(_W5))
    snap_season_yellows: dict = defaultdict(int)  # (season, team) → int

    # Per-referee running totals (EPL only)
    ref_matches:   dict = defaultdict(int)
    ref_home_wins: dict = defaultdict(int)
    ref_draws:     dict = defaultdict(int)
    ref_cards:     dict = defaultdict(float)

    _prev_season_snap: Optional[str] = None

    # EWMA momentum
    snap_ewma_scored:   dict[str, float] = {}
    snap_ewma_conceded: dict[str, float] = {}
    snap_ewma_form:     dict[str, float] = {}

    # League standings (season-specific)
    snap_lg_pts:   dict = defaultdict(int)   # (league, season, team)
    snap_lg_gd:    dict = defaultdict(int)   # (league, season, team)
    snap_lg_teams: dict = defaultdict(set)   # (league, season) → set[team]

    for _, row in df.iterrows():
        h, a = row["home_team"], row["away_team"]
        hg, ag = int(row["home_goals"]), int(row["away_goals"])

        # Pi-Rating decay at season boundaries (D) — same logic as build_features
        _snap_season = season_from_date(row["Date"])
        if _prev_season_snap is not None and _snap_season != _prev_season_snap:
            # Decay ALL known teams — union of home_att and away_att keys so
            # teams that only appeared as away side are not skipped.
            _all_snap_teams = set(pi_home_att.keys()) | set(pi_away_att.keys())
            for _team in _all_snap_teams:
                pi_home_att[_team] *= PI_DECAY
                pi_home_def[_team] *= PI_DECAY
                pi_away_att[_team] *= PI_DECAY
                pi_away_def[_team] *= PI_DECAY
        _prev_season_snap = _snap_season

        # Snapshot pi-expected before update (needed for update step)
        h_att = pi_home_att[h]; h_def = pi_home_def[h]
        a_att = pi_away_att[a]; a_def = pi_away_def[a]
        pi_exp_h = _pi_exp_goals(h_att, a_def)
        pi_exp_a = _pi_exp_goals(a_att, h_def)

        if hg > ag:
            result_val = 1; h_pts, a_pts = 3, 0
        elif hg == ag:
            result_val = 0; h_pts = a_pts = 1
        else:
            result_val = -1; h_pts, a_pts = 0, 3

        for sc, cc, gs, gc in [
            (team_all_scored[h], team_all_conceded[h], hg, ag),
            (team_all_scored_10[h], team_all_conceded_10[h], hg, ag),
        ]:
            sc.append(gs); cc.append(gc)
        for sc, cc, gs, gc in [
            (team_all_scored[a], team_all_conceded[a], ag, hg),
            (team_all_scored_10[a], team_all_conceded_10[a], ag, hg),
        ]:
            sc.append(gs); cc.append(gc)

        team_home_scored[h].append(hg);    team_home_conceded[h].append(ag)
        team_home_scored_10[h].append(hg); team_home_conceded_10[h].append(ag)
        team_away_scored[a].append(ag);    team_away_conceded[a].append(hg)
        team_away_scored_10[a].append(ag); team_away_conceded_10[a].append(hg)

        team_points_5[h].append(h_pts);  team_points_5[a].append(a_pts)
        team_points_10[h].append(h_pts); team_points_10[a].append(a_pts)

        total_g = hg + ag
        team_total_goals_5[h].append(total_g);  team_total_goals_5[a].append(total_g)
        team_total_goals_10[h].append(total_g); team_total_goals_10[a].append(total_g)

        over25 = 1 if total_g > 2.5 else 0
        team_over25_5[h].append(over25);  team_over25_5[a].append(over25)
        team_over25_10[h].append(over25); team_over25_10[a].append(over25)

        drew = 1 if hg == ag else 0
        team_draw_5[h].append(drew);  team_draw_5[a].append(drew)
        team_draw_10[h].append(drew); team_draw_10[a].append(drew)

        hsot = row.get("home_shots_ot", np.nan)
        asot = row.get("away_shots_ot", np.nan)
        if pd.notna(hsot) and pd.notna(asot):
            team_shots_ot_5[h].append(float(hsot));  team_shots_ot_c_5[h].append(float(asot))
            team_shots_ot_5[a].append(float(asot));  team_shots_ot_c_5[a].append(float(hsot))

        hxg = row.get("home_xg", np.nan)
        axg = row.get("away_xg", np.nan)
        if pd.notna(hxg) and pd.notna(axg):
            team_xg_scored_5[h].append(float(hxg));  team_xg_conceded_5[h].append(float(axg))
            team_xg_scored_5[a].append(float(axg));  team_xg_conceded_5[a].append(float(hxg))
            team_xg_scored_10[h].append(float(hxg)); team_xg_conceded_10[h].append(float(axg))
            team_xg_scored_10[a].append(float(axg)); team_xg_conceded_10[a].append(float(hxg))

        h2h[frozenset({h, a})].append((result_val, int(hg), int(ag), h))

        # Referee update
        ref_name = row.get("referee")
        ref_name = ref_name if (isinstance(ref_name, str) and ref_name.strip()) else None
        if ref_name:
            ref_matches[ref_name] += 1
            if hg > ag:   ref_home_wins[ref_name] += 1
            elif hg == ag: ref_draws[ref_name] += 1
            hy = float(row.get("h_yellow", 0) or 0)
            ay = float(row.get("a_yellow", 0) or 0)
            hr = float(row.get("h_red",    0) or 0)
            ar = float(row.get("a_red",    0) or 0)
            ref_cards[ref_name] += hy + ay + 2 * hr + 2 * ar

        # Card / discipline state update
        _s_hry = float(row.get("h_red",    0) or 0) if pd.notna(row.get("h_red",    0)) else 0.0
        _s_ary = float(row.get("a_red",    0) or 0) if pd.notna(row.get("a_red",    0)) else 0.0
        _s_hyy = float(row.get("h_yellow", 0) or 0) if pd.notna(row.get("h_yellow", 0)) else 0.0
        _s_ayy = float(row.get("a_yellow", 0) or 0) if pd.notna(row.get("a_yellow", 0)) else 0.0
        snap_reds_5[h].append(_s_hry);    snap_reds_5[a].append(_s_ary)
        snap_yellows_5[h].append(_s_hyy); snap_yellows_5[a].append(_s_ayy)
        _snap_season_key = season_from_date(row["Date"])
        snap_season_yellows[(_snap_season_key, h)] += int(_s_hyy)
        snap_season_yellows[(_snap_season_key, a)] += int(_s_ayy)

        new_h_elo, new_a_elo = _elo_update(elo[h], elo[a], hg, ag)
        elo[h] = new_h_elo; elo[a] = new_a_elo

        err_h = hg - pi_exp_h; err_a = ag - pi_exp_a
        pi_home_att[h] += PI_C * err_h; pi_away_def[a] -= PI_C * err_h
        pi_away_att[a] += PI_C * err_a; pi_home_def[h] -= PI_C * err_a

        # Poisson state update
        league = row.get("League", "Unknown")
        _season = season_from_date(row["Date"])
        poisson.update(h, a, hg, ag, league, _season)

        # EWMA update
        for _t, _gs, _gc, _pts in [(h, hg, ag, h_pts), (a, ag, hg, a_pts)]:
            snap_ewma_scored[_t] = (
                float(_gs) if _t not in snap_ewma_scored
                else EWMA_ALPHA * _gs + (1 - EWMA_ALPHA) * snap_ewma_scored[_t]
            )
            snap_ewma_conceded[_t] = (
                float(_gc) if _t not in snap_ewma_conceded
                else EWMA_ALPHA * _gc + (1 - EWMA_ALPHA) * snap_ewma_conceded[_t]
            )
            snap_ewma_form[_t] = (
                float(_pts) if _t not in snap_ewma_form
                else EWMA_ALPHA * _pts + (1 - EWMA_ALPHA) * snap_ewma_form[_t]
            )

        # League standings update
        snap_lg_teams[(league, _season)].add(h)
        snap_lg_teams[(league, _season)].add(a)
        snap_lg_pts[(league, _season, h)] += h_pts
        snap_lg_pts[(league, _season, a)] += a_pts
        snap_lg_gd[(league, _season, h)] += hg - ag
        snap_lg_gd[(league, _season, a)] += ag - hg

    # Store last season seen for snap_season_yellows lookup in compute_match_features
    _last_snap_season = _prev_season_snap

    return dict(
        team_all_scored=team_all_scored, team_all_conceded=team_all_conceded,
        team_home_scored=team_home_scored, team_home_conceded=team_home_conceded,
        team_away_scored=team_away_scored, team_away_conceded=team_away_conceded,
        team_points_5=team_points_5, team_total_goals_5=team_total_goals_5,
        team_over25_5=team_over25_5, team_shots_ot_5=team_shots_ot_5,
        team_shots_ot_c_5=team_shots_ot_c_5,
        team_draw_5=team_draw_5, team_draw_10=team_draw_10,
        team_all_scored_10=team_all_scored_10, team_all_conceded_10=team_all_conceded_10,
        team_home_scored_10=team_home_scored_10, team_home_conceded_10=team_home_conceded_10,
        team_away_scored_10=team_away_scored_10, team_away_conceded_10=team_away_conceded_10,
        team_points_10=team_points_10, team_total_goals_10=team_total_goals_10,
        team_over25_10=team_over25_10,
        elo=elo, pi_home_att=pi_home_att, pi_home_def=pi_home_def,
        pi_away_att=pi_away_att, pi_away_def=pi_away_def, h2h=h2h,
        team_xg_scored_5=team_xg_scored_5, team_xg_conceded_5=team_xg_conceded_5,
        team_xg_scored_10=team_xg_scored_10, team_xg_conceded_10=team_xg_conceded_10,
        ref_matches=ref_matches, ref_home_wins=ref_home_wins,
        ref_draws=ref_draws, ref_cards=ref_cards,
        poisson_state=poisson,
        last_season=_prev_season_snap,  # season of last history row — used for inference-time Pi-Rating decay
        # EWMA momentum
        team_ewma_scored=snap_ewma_scored,
        team_ewma_conceded=snap_ewma_conceded,
        team_ewma_form=snap_ewma_form,
        # League standings (season-specific)
        season_lg_pts=snap_lg_pts,
        season_lg_gd=snap_lg_gd,
        season_lg_teams=snap_lg_teams,
        # Card / discipline rolling windows
        team_reds_5=snap_reds_5,
        team_yellows_5=snap_yellows_5,
        team_season_yellows=snap_season_yellows,
        last_snap_season=_last_snap_season,
    )


# Maps DB team names (from football-data.org API short names) to the names
# used in the raw training CSVs (from football-data.co.uk).  Only entries
# that actually differ are listed here.  add new ones whenever fetch_upcoming
# stores a name that doesn't match the CSV convention.
_SNAP_NAME_MAP: dict[str, str] = {
    # Serie A
    "AC Milan":          "Milan",
    # Bundesliga
    "Bayer Leverkusen":  "Leverkusen",
    # PrimeiraLiga
    "Braga":             "Sp Braga",
    "SC Braga":          "Sp Braga",
    "Sporting CP":       "Sp Lisbon",
    "Vitoria SC":        "Guimaraes",
    "CD Nacional":       "Nacional",
    # Eredivisie
    "NAC":               "NAC Breda",
    "Go Ahead":          "Go Ahead Eagles",
    "Sparta":            "Sparta Rotterdam",
    "Sittard":           "For Sittard",
    "NEC":               "Nijmegen",
    "NEC Nijmegen":      "Nijmegen",
    "PSV":               "PSV Eindhoven",
    "AZ":                "AZ Alkmaar",
    # Championship
    "Hull City":         "Hull",
    "Coventry City":     "Coventry",
    "Sheffield Utd":     "Sheffield United",
    "Sheffield Wednesday": "Sheffield Weds",
    "Ipswich Town":      "Ipswich",
    "Leicester City":    "Leicester",
    "Derby County":      "Derby",
    "Oxford United":     "Oxford",
    "Preston NE":        "Preston",
}


def compute_match_features(
    snapshot: dict,
    home_team: str,
    away_team: str,
    league: str,
    match_date=None,
    european_df=None,
    market_probs: "dict | None" = None,
    referee: "str | None" = None,
    odds_movement: "dict | None" = None,
) -> dict:
    """
    Compute feature dict for a single upcoming match from a frozen team snapshot.
    Does NOT update the snapshot — safe to call for many matches in parallel.

    referee: optional referee name (EPL only, typically unknown for future fixtures).
             When None, ref_* features are NaN and XGBoost uses its learned prior.
    """
    s = snapshot
    # Translate DB names → CSV names so snapshot lookups find real Elo/stats
    h = _SNAP_NAME_MAP.get(home_team, home_team)
    a = _SNAP_NAME_MAP.get(away_team, away_team)

    # Warn when neither the original nor the mapped name is in the Elo snapshot —
    # this means the team will silently default to Elo=1500 (ELO_START).
    # Add the missing name to _SNAP_NAME_MAP to fix it.
    _elo_snap = s.get("elo", {})
    if h not in _elo_snap and home_team not in _elo_snap:
        print(f"[snap_warn] '{home_team}' not in Elo snapshot (no CSV history). "
              f"Add to _SNAP_NAME_MAP if this team has a different CSV name.")
    if a not in _elo_snap and away_team not in _elo_snap:
        print(f"[snap_warn] '{away_team}' not in Elo snapshot (no CSV history). "
              f"Add to _SNAP_NAME_MAP if this team has a different CSV name.")

    def _mean(dq: deque) -> Optional[float]:
        return float(np.mean(list(dq))) if dq else np.nan

    def _avg(x, y):
        return (x + y) / 2 if (not np.isnan(x) and not np.isnan(y)) else np.nan

    def _gdiff(sc, cc):
        sm, cm = _mean(sc), _mean(cc)
        return (sm - cm) if (not np.isnan(sm) and not np.isnan(cm)) else np.nan

    feat: dict = {}

    feat["h_goals_scored_5"]   = _mean(s["team_all_scored"][h])
    feat["h_goals_conceded_5"] = _mean(s["team_all_conceded"][h])
    feat["a_goals_scored_5"]   = _mean(s["team_all_scored"][a])
    feat["a_goals_conceded_5"] = _mean(s["team_all_conceded"][a])
    feat["h_home_scored_5"]    = _mean(s["team_home_scored"][h])
    feat["h_home_conceded_5"]  = _mean(s["team_home_conceded"][h])
    feat["a_away_scored_5"]    = _mean(s["team_away_scored"][a])
    feat["a_away_conceded_5"]  = _mean(s["team_away_conceded"][a])
    feat["h_form_5"]           = _mean(s["team_points_5"][h])
    feat["a_form_5"]           = _mean(s["team_points_5"][a])

    feat["h_goals_scored_10"]   = _mean(s["team_all_scored_10"][h])
    feat["h_goals_conceded_10"] = _mean(s["team_all_conceded_10"][h])
    feat["a_goals_scored_10"]   = _mean(s["team_all_scored_10"][a])
    feat["a_goals_conceded_10"] = _mean(s["team_all_conceded_10"][a])
    feat["h_home_scored_10"]    = _mean(s["team_home_scored_10"][h])
    feat["h_home_conceded_10"]  = _mean(s["team_home_conceded_10"][h])
    feat["a_away_scored_10"]    = _mean(s["team_away_scored_10"][a])
    feat["a_away_conceded_10"]  = _mean(s["team_away_conceded_10"][a])
    feat["h_form_10"]           = _mean(s["team_points_10"][h])
    feat["a_form_10"]           = _mean(s["team_points_10"][a])

    feat["h_goal_diff_5"]  = _gdiff(s["team_all_scored"][h], s["team_all_conceded"][h])
    feat["a_goal_diff_5"]  = _gdiff(s["team_all_scored"][a], s["team_all_conceded"][a])
    feat["h_goal_diff_10"] = _gdiff(s["team_all_scored_10"][h], s["team_all_conceded_10"][h])
    feat["a_goal_diff_10"] = _gdiff(s["team_all_scored_10"][a], s["team_all_conceded_10"][a])

    hs5  = _mean(s["team_all_scored"][h]);     as5  = _mean(s["team_all_scored"][a])
    hc5  = _mean(s["team_all_conceded"][h]);   ac5  = _mean(s["team_all_conceded"][a])
    hs10 = _mean(s["team_all_scored_10"][h]);  as10 = _mean(s["team_all_scored_10"][a])
    hc10 = _mean(s["team_all_conceded_10"][h]);ac10 = _mean(s["team_all_conceded_10"][a])

    feat["expected_home_goals_5"]  = _avg(hs5, ac5)
    feat["expected_away_goals_5"]  = _avg(as5, hc5)
    feat["expected_goals_5"]       = _avg(_avg(hs5, ac5), _avg(as5, hc5))
    feat["expected_home_goals_10"] = _avg(hs10, ac10)
    feat["expected_away_goals_10"] = _avg(as10, hc10)
    feat["expected_goals_10"]      = _avg(_avg(hs10, ac10), _avg(as10, hc10))

    feat["h_total_goals_5"]  = _mean(s["team_total_goals_5"][h])
    feat["a_total_goals_5"]  = _mean(s["team_total_goals_5"][a])
    feat["h_total_goals_10"] = _mean(s["team_total_goals_10"][h])
    feat["a_total_goals_10"] = _mean(s["team_total_goals_10"][a])

    feat["h_over25_rate_5"]  = _mean(s["team_over25_5"][h])
    feat["a_over25_rate_5"]  = _mean(s["team_over25_5"][a])
    feat["h_over25_rate_10"] = _mean(s["team_over25_10"][h])
    feat["a_over25_rate_10"] = _mean(s["team_over25_10"][a])

    feat["h_draw_rate_5"]  = _mean(s["team_draw_5"][h])
    feat["a_draw_rate_5"]  = _mean(s["team_draw_5"][a])
    feat["h_draw_rate_10"] = _mean(s["team_draw_10"][h])
    feat["a_draw_rate_10"] = _mean(s["team_draw_10"][a])

    feat["h_shots_ot_5"]  = _mean(s["team_shots_ot_5"][h])
    feat["h_shots_otc_5"] = _mean(s["team_shots_ot_c_5"][h])
    feat["a_shots_ot_5"]  = _mean(s["team_shots_ot_5"][a])
    feat["a_shots_otc_5"] = _mean(s["team_shots_ot_c_5"][a])

    feat["h_elo"]           = s["elo"][h]
    feat["a_elo"]           = s["elo"][a]
    feat["elo_diff"]        = s["elo"][h] - s["elo"][a]
    feat["elo_home_win_prob"] = _elo_expected(s["elo"][h], s["elo"][a])

    # Apply PI_DECAY when predicting into a new season (train/inference consistency).
    # During training build_features() decays ratings at season boundaries; here we
    # replicate that for the first season the snapshot has not yet seen.
    _snap_last_season = s.get("last_season")
    _match_season = season_from_date(match_date) if match_date is not None else _snap_last_season
    _pi_decay_factor = PI_DECAY if (_snap_last_season and _match_season != _snap_last_season) else 1.0

    h_att = s["pi_home_att"][h] * _pi_decay_factor; h_def = s["pi_home_def"][h] * _pi_decay_factor
    a_att = s["pi_away_att"][a] * _pi_decay_factor; a_def = s["pi_away_def"][a] * _pi_decay_factor
    feat["h_pi_att"] = h_att; feat["h_pi_def"] = h_def
    feat["a_pi_att"] = a_att; feat["a_pi_def"] = a_def
    feat["pi_att_diff"] = h_att - a_def
    feat["pi_def_diff"] = a_att - h_def
    pi_exp_h = _pi_exp_goals(h_att, a_def)
    pi_exp_a = _pi_exp_goals(a_att, h_def)
    feat["pi_exp_home"]  = pi_exp_h
    feat["pi_exp_away"]  = pi_exp_a
    feat["pi_exp_diff"]  = pi_exp_h - pi_exp_a
    feat["pi_exp_total"] = pi_exp_h + pi_exp_a

    key      = frozenset({h, a})
    h2h_hist = list(s["h2h"].get(key, []))
    n_h2h    = len(h2h_hist)

    feat["h2h_count"] = n_h2h

    feat["h2h_home_wins"] = sum(
        1 for (v, _, _, ht) in h2h_hist
        if (ht == h and v == 1) or (ht == a and v == -1)
    )
    feat["h2h_away_wins"] = sum(
        1 for (v, _, _, ht) in h2h_hist
        if (ht == a and v == 1) or (ht == h and v == -1)
    )
    _h2h_draw_n       = sum(1 for (v, _, _, _) in h2h_hist if v == 0)
    feat["h2h_draws"]     = _h2h_draw_n
    feat["h2h_draw_rate"] = (_h2h_draw_n / n_h2h) if n_h2h else np.nan

    if n_h2h:
        _h_sc     = [hg2 if ht == h else ag2 for (_, hg2, ag2, ht) in h2h_hist]
        _a_sc     = [ag2 if ht == h else hg2 for (_, hg2, ag2, ht) in h2h_hist]
        _totals   = [hg2 + ag2               for (_, hg2, ag2, _)  in h2h_hist]
        _btts_arr = [1 if hg2 > 0 and ag2 > 0 else 0 for (_, hg2, ag2, _) in h2h_hist]
        feat["h2h_home_goals_avg"]  = float(np.mean(_h_sc))
        feat["h2h_away_goals_avg"]  = float(np.mean(_a_sc))
        feat["h2h_total_goals_avg"] = float(np.mean(_totals))
        feat["h2h_btts_rate"]       = float(np.mean(_btts_arr))
        feat["h2h_over25_rate"]     = float(np.mean([1 if t > 2.5 else 0 for t in _totals]))
    else:
        feat["h2h_home_goals_avg"]  = np.nan
        feat["h2h_away_goals_avg"]  = np.nan
        feat["h2h_total_goals_avg"] = np.nan
        feat["h2h_btts_rate"]       = np.nan
        feat["h2h_over25_rate"]     = np.nan

    # Season phase features (F)
    if match_date is not None:
        feat.update(_season_phase_features(pd.Timestamp(match_date)))
    else:
        feat["season_week"]             = np.nan
        feat["season_phase"]            = np.nan
        feat["days_since_season_start"] = np.nan

    known_leagues = ["EPL", "LaLiga", "SerieA", "Bundesliga", "Ligue1", "GreekSL"]
    for lg in known_leagues:
        feat[f"league_{lg}"] = 1 if league == lg else 0

    # ── Referee features (EPL only; NaN for other leagues / unknown referee) ──────
    ref_m = s.get("ref_matches", {})
    ref_hw = s.get("ref_home_wins", {})
    ref_dr = s.get("ref_draws", {})
    ref_ca = s.get("ref_cards", {})
    ref_name = referee if (isinstance(referee, str) and referee.strip()) else None
    if ref_name and ref_m.get(ref_name, 0) >= _MIN_REF_MATCHES:
        n = ref_m[ref_name]
        feat["ref_home_win_rate"]  = ref_hw.get(ref_name, 0) / n
        feat["ref_draw_rate"]      = ref_dr.get(ref_name, 0) / n
        feat["ref_cards_per_game"] = ref_ca.get(ref_name, 0.0) / n
    else:
        feat["ref_home_win_rate"]  = np.nan
        feat["ref_draw_rate"]      = np.nan
        feat["ref_cards_per_game"] = np.nan

    # ── xG rolling features (understat 2014/15+; NaN for older / non-top-5) ──────
    def _xg_mean(dq_dict: dict, team: str) -> float:
        dq = dq_dict.get(team)
        return float(np.mean(list(dq))) if dq else np.nan

    feat["h_xg_scored_5"]   = _xg_mean(s.get("team_xg_scored_5",   {}), h)
    feat["h_xg_conceded_5"] = _xg_mean(s.get("team_xg_conceded_5", {}), h)
    feat["a_xg_scored_5"]   = _xg_mean(s.get("team_xg_scored_5",   {}), a)
    feat["a_xg_conceded_5"] = _xg_mean(s.get("team_xg_conceded_5", {}), a)
    feat["h_xg_scored_10"]  = _xg_mean(s.get("team_xg_scored_10",  {}), h)
    feat["h_xg_conceded_10"]= _xg_mean(s.get("team_xg_conceded_10",{}), h)
    feat["a_xg_scored_10"]  = _xg_mean(s.get("team_xg_scored_10",  {}), a)
    feat["a_xg_conceded_10"]= _xg_mean(s.get("team_xg_conceded_10",{}), a)

    # ── Poisson features ──────────────────────────────────────────────────────
    # Use the PoissonState from the snapshot (built from all history up to today).
    # For inference there is no leakage: we use all available historical data
    # to predict a future match.
    poisson_state: Optional[PoissonState] = s.get("poisson_state")
    if poisson_state is not None and match_date is not None:
        _season = season_from_date(match_date)
        feat.update(poisson_state.features(h, a, league, _season))
    else:
        feat.update(_nan_poisson())

    # European congestion features
    if european_df is not None and match_date is not None:
        from backend.app.ml.european import EUROPEAN_FEATURE_COLS
        try:
            match_row = pd.DataFrame([{
                "Date": pd.Timestamp(match_date),
                "home_team": h,
                "away_team": a,
                "home_goals": 0,
                "away_goals": 0,
                "League": league,
                **feat,
            }])
            from backend.app.ml.european import add_european_features
            match_row = add_european_features(match_row, european_df)
            for col in EUROPEAN_FEATURE_COLS:
                feat[col] = float(match_row[col].iloc[0]) if col in match_row.columns else 0.0
        except Exception:
            for col in ["h_eur_fatigue", "a_eur_fatigue", "h_eur_away",
                        "a_eur_away", "h_eur_result", "a_eur_result"]:
                feat[col] = 0.0
    else:
        for col in ["h_eur_fatigue", "a_eur_fatigue", "h_eur_away",
                    "a_eur_away", "h_eur_result", "a_eur_result"]:
            feat[col] = 0.0

    # ── Market probabilities (live odds at prediction time) ───────────────────
    # Supply a dict {home_win, draw, away_win, over_2_5} with vig-removed fair
    # probabilities from The Odds API. When None, XGBoost uses its learned NaN
    # direction — equivalent to the model's prior for unpriced matches.
    if market_probs:
        def _mfloat(v):
            """Convert market prob value to float, falling back to NaN for None/non-numeric."""
            try:
                return float(v) if v is not None else np.nan
            except (TypeError, ValueError):
                return np.nan
        feat["market_home_prob"] = _mfloat(market_probs.get("home_win"))
        feat["market_draw_prob"] = _mfloat(market_probs.get("draw"))
        feat["market_away_prob"] = _mfloat(market_probs.get("away_win"))
        feat["market_over_prob"] = _mfloat(market_probs.get("over_2_5"))
    else:
        feat["market_home_prob"] = np.nan
        feat["market_draw_prob"] = np.nan
        feat["market_away_prob"] = np.nan
        feat["market_over_prob"] = np.nan

    # ── Poisson fallback for missing market probs (H) ─────────────────────────
    # When live bookmaker odds are unavailable (NaN), substitute Poisson-derived
    # probability estimates. These are in the same ballpark as market odds for
    # most matches, and provide a concrete signal rather than leaving NaN.
    # Market features still take priority when present (applied above).
    if np.isnan(feat.get("market_home_prob", np.nan)):
        feat["market_home_prob"] = feat.get("poisson_home_win", np.nan)
        feat["market_draw_prob"] = feat.get("poisson_draw",     np.nan)
        feat["market_away_prob"] = feat.get("poisson_away_win", np.nan)
    if np.isnan(feat.get("market_over_prob", np.nan)):
        feat["market_over_prob"] = feat.get("poisson_over_2_5", np.nan)

    # ── Draw-balance features ─────────────────────────────────────────────────
    # Capture how "symmetric" / balanced a match is — the primary driver of draws
    # that existing individual-team features don't encode directly.

    # Absolute difference in scoring rate: 0 = perfectly matched offences
    h_sc5 = feat.get("h_goals_scored_5", np.nan)
    a_sc5 = feat.get("a_goals_scored_5", np.nan)
    feat["goals_asymmetry_5"] = (
        abs(h_sc5 - a_sc5) if not (np.isnan(h_sc5) or np.isnan(a_sc5)) else np.nan
    )

    # Geometric mean of draw rates: high only when BOTH teams draw often
    h_dr5 = feat.get("h_draw_rate_5", np.nan)
    a_dr5 = feat.get("a_draw_rate_5", np.nan)
    feat["combined_draw_tendency"] = (
        (h_dr5 * a_dr5) ** 0.5 if not (np.isnan(h_dr5) or np.isnan(a_dr5)) else np.nan
    )

    # Pi-Rating closeness: small total absolute diff = evenly matched teams
    pi_att_d = feat.get("pi_att_diff", np.nan)
    pi_def_d = feat.get("pi_def_diff", np.nan)
    feat["pi_closeness"] = (
        1.0 / (1.0 + abs(pi_att_d) + abs(pi_def_d))
        if not (np.isnan(pi_att_d) or np.isnan(pi_def_d)) else np.nan
    )

    # Market − Poisson draw gap: positive = market prices draw more than model expects
    mkt_d  = feat.get("market_draw_prob", np.nan)
    poi_d  = feat.get("poisson_draw",     np.nan)
    feat["market_draw_edge"] = (
        mkt_d - poi_d if not (np.isnan(mkt_d) or np.isnan(poi_d)) else np.nan
    )

    # Low expected total goals flag: defensive matches skew 0-0 / 1-0 / 1-1
    pi_total = feat.get("pi_exp_total", np.nan)
    feat["low_total_xg"] = (
        (1.0 if pi_total < 2.0 else 0.0) if not np.isnan(pi_total) else np.nan
    )

    # Elo closeness: teams with similar ratings → more unpredictable → more draws
    elo_d = feat.get("elo_diff", np.nan)
    feat["elo_closeness"] = (
        1.0 / (1.0 + abs(elo_d)) if not np.isnan(elo_d) else np.nan
    )

    # ── Odds movement / steam features ───────────────────────────────────────
    # odds_movement dict: {drift_home, drift_draw, drift_away, drift_over}
    # where drift = current_raw_odds - earliest_stored_odds (negative = steam).
    # Historical training rows always get 0.0 (neutral). Real drift is injected
    # at inference time from odds_history. Model learns "when drift ≠ 0, adjust."
    # Steam threshold: -0.15 raw odds (e.g. 2.00 → 1.85 = sharp money signal).
    STEAM_THRESHOLD = -0.15
    if odds_movement:
        feat["odds_drift_home"]  = float(odds_movement.get("drift_home",  0.0) or 0.0)
        feat["odds_drift_draw"]  = float(odds_movement.get("drift_draw",  0.0) or 0.0)
        feat["odds_drift_away"]  = float(odds_movement.get("drift_away",  0.0) or 0.0)
        feat["odds_drift_over"]  = float(odds_movement.get("drift_over",  0.0) or 0.0)
        feat["is_steam_home"]    = 1.0 if feat["odds_drift_home"] < STEAM_THRESHOLD else 0.0
        feat["is_steam_away"]    = 1.0 if feat["odds_drift_away"] < STEAM_THRESHOLD else 0.0
    else:
        feat["odds_drift_home"]  = 0.0
        feat["odds_drift_draw"]  = 0.0
        feat["odds_drift_away"]  = 0.0
        feat["odds_drift_over"]  = 0.0
        feat["is_steam_home"]    = 0.0
        feat["is_steam_away"]    = 0.0

    # ── EWMA momentum features ────────────────────────────────────────────────
    feat["h_ewma_scored"]   = s.get("team_ewma_scored",   {}).get(h, np.nan)
    feat["h_ewma_conceded"] = s.get("team_ewma_conceded", {}).get(h, np.nan)
    feat["a_ewma_scored"]   = s.get("team_ewma_scored",   {}).get(a, np.nan)
    feat["a_ewma_conceded"] = s.get("team_ewma_conceded", {}).get(a, np.nan)
    feat["h_ewma_form"]     = s.get("team_ewma_form",     {}).get(h, np.nan)
    feat["a_ewma_form"]     = s.get("team_ewma_form",     {}).get(a, np.nan)

    # ── Card / suspension proxy features ─────────────────────────────────────
    _snap_r5 = s.get("team_reds_5",    {})
    _snap_y5 = s.get("team_yellows_5", {})
    _snap_sy = s.get("team_season_yellows", {})
    _snap_last_season = s.get("last_snap_season")
    _card_season = _match_season if match_date is not None else _snap_last_season

    _h_reds5_snap = list(_snap_r5.get(h, deque()))
    _a_reds5_snap = list(_snap_r5.get(a, deque()))
    _h_yels5_snap = list(_snap_y5.get(h, deque()))
    _a_yels5_snap = list(_snap_y5.get(a, deque()))

    feat["h_red_last1"]      = float(_h_reds5_snap[-1]) if _h_reds5_snap else 0.0
    feat["a_red_last1"]      = float(_a_reds5_snap[-1]) if _a_reds5_snap else 0.0
    feat["h_reds_5"]         = float(sum(_h_reds5_snap))
    feat["a_reds_5"]         = float(sum(_a_reds5_snap))
    feat["h_discipline_5"]   = (float(sum(_h_yels5_snap)) + 2.0 * float(sum(_h_reds5_snap))) / max(1, len(_h_reds5_snap))
    feat["a_discipline_5"]   = (float(sum(_a_yels5_snap)) + 2.0 * float(sum(_a_reds5_snap))) / max(1, len(_a_reds5_snap))
    feat["h_season_yellows"] = float(_snap_sy.get((_card_season, h), 0))
    feat["a_season_yellows"] = float(_snap_sy.get((_card_season, a), 0))
    feat["suspension_diff"]  = feat["h_red_last1"] - feat["a_red_last1"]

    # ── League position (current season table) ────────────────────────────────
    _sl_pts   = s.get("season_lg_pts",   {})
    _sl_gd    = s.get("season_lg_gd",    {})
    _sl_teams = s.get("season_lg_teams", {})
    _ls_m     = (league, _match_season)
    _ls_teams_m = _sl_teams.get(_ls_m, set())
    if len(_ls_teams_m) >= 3:
        _ranked_m = sorted(
            _ls_teams_m,
            key=lambda t: (-_sl_pts.get((_ls_m[0], _ls_m[1], t), 0),
                           -_sl_gd.get((_ls_m[0], _ls_m[1], t), 0))
        )
        _nm = len(_ranked_m)
        _h_rank_m = (_ranked_m.index(h) + 1) if h in _ranked_m else None
        _a_rank_m = (_ranked_m.index(a) + 1) if a in _ranked_m else None
        feat["h_league_pos_norm"] = _h_rank_m / _nm if _h_rank_m is not None else np.nan
        feat["a_league_pos_norm"] = _a_rank_m / _nm if _a_rank_m is not None else np.nan
        feat["league_pos_diff"]   = (
            feat["h_league_pos_norm"] - feat["a_league_pos_norm"]
            if (_h_rank_m and _a_rank_m) else np.nan
        )
        feat.update(_motivation_feats(
            h, a, _ranked_m, _sl_pts,
            _ls_m[0], _ls_m[1], feat.get("season_week", np.nan),
        ))
    else:
        feat["h_league_pos_norm"] = np.nan
        feat["a_league_pos_norm"] = np.nan
        feat["league_pos_diff"]   = np.nan
        feat["h_pts_vs_cl"]          = np.nan
        feat["a_pts_vs_cl"]          = np.nan
        feat["h_pts_vs_relegation"]  = np.nan
        feat["a_pts_vs_relegation"]  = np.nan
        feat["motivation_diff"]      = np.nan

    return feat


# ── Feature column list ────────────────────────────────────────────────────────
# CatBoost will receive ALL of these. Optional features (shots, European)
# are imputed to 0 before training — train.py handles this.

FEATURE_COLS = [
    # 5-match rolling
    "h_goals_scored_5",   "h_goals_conceded_5",
    "a_goals_scored_5",   "a_goals_conceded_5",
    "h_home_scored_5",    "h_home_conceded_5",
    "a_away_scored_5",    "a_away_conceded_5",
    "h_form_5",           "a_form_5",
    "h_goal_diff_5",      "a_goal_diff_5",
    # 10-match rolling
    "h_goals_scored_10",  "h_goals_conceded_10",
    "a_goals_scored_10",  "a_goals_conceded_10",
    "h_home_scored_10",   "h_home_conceded_10",
    "a_away_scored_10",   "a_away_conceded_10",
    "h_form_10",          "a_form_10",
    "h_goal_diff_10",     "a_goal_diff_10",
    # Expected goals (rolling-average based)
    "expected_home_goals_5",  "expected_away_goals_5",  "expected_goals_5",
    "expected_home_goals_10", "expected_away_goals_10", "expected_goals_10",
    "h_total_goals_5",        "a_total_goals_5",
    "h_total_goals_10",       "a_total_goals_10",
    "h_over25_rate_5",        "a_over25_rate_5",
    "h_over25_rate_10",       "a_over25_rate_10",
    "h_draw_rate_5",          "a_draw_rate_5",
    "h_draw_rate_10",         "a_draw_rate_10",
    "h_shots_ot_5",           "h_shots_otc_5",
    "a_shots_ot_5",           "a_shots_otc_5",
    # Elo
    "h_elo",              "a_elo",   "elo_diff",  "elo_home_win_prob",
    # Pi-Ratings (Constantinou & Fenton 2012)
    # Goal-based, home/away split — richer signal than Elo alone.
    "h_pi_att",           "h_pi_def",           # home team: attack / defense when at home
    "a_pi_att",           "a_pi_def",           # away team: attack / defense when away
    "pi_att_diff",        "pi_def_diff",        # differentials
    "pi_exp_home",        "pi_exp_away",        # model-implied expected goals
    "pi_exp_diff",        "pi_exp_total",       # margin + total (key for over/under)
    # H2H — last 10 meetings between this specific pair
    # count/result features
    "h2h_count",          "h2h_home_wins",  "h2h_away_wins",  "h2h_draws",  "h2h_draw_rate",
    # goals features (perspective-aware: from current home team's viewpoint)
    "h2h_home_goals_avg", "h2h_away_goals_avg", "h2h_total_goals_avg",
    "h2h_btts_rate",      "h2h_over25_rate",
    # Season phase (F) — early / mid / late season signal
    "season_week",        "season_phase",   "days_since_season_start",
    # League
    "league_EPL",         "league_LaLiga",  "league_SerieA",
    "league_Bundesliga",  "league_Ligue1",  "league_GreekSL",
    # European competition schedule (0 when no data / team not in Europe)
    "h_eur_fatigue",      "a_eur_fatigue",
    "h_eur_away",         "a_eur_away",
    "h_eur_result",       "a_eur_result",
    # xG rolling features (understat 2014/15+; top-5 leagues only).
    # NaN for GreekSL and pre-2014/15 seasons — XGBoost handles missing natively.
    "h_xg_scored_5",      "h_xg_conceded_5",
    "a_xg_scored_5",      "a_xg_conceded_5",
    "h_xg_scored_10",     "h_xg_conceded_10",
    "a_xg_scored_10",     "a_xg_conceded_10",
    # Pinnacle market fair probabilities (vig removed) — available ~2012/13+.
    # NaN for older seasons / unpriced leagues; XGBoost handles missing natively.
    "market_home_prob",   "market_draw_prob",
    "market_away_prob",   "market_over_prob",
    # Referee features (EPL only; NaN for all other leagues).
    # ref_home_win_rate and ref_draw_rate capture referee-specific match patterns.
    # ref_cards_per_game captures strictness (affects game flow and open play).
    # All three are NaN for upcoming matches where referee is not yet known.
    "ref_home_win_rate",  "ref_draw_rate",  "ref_cards_per_game",
    # Poisson expected-goals features (season-specific, no cross-season bleed).
    # Complement Pi-Ratings: season-normalised attack/defense strengths + outcome
    # probabilities from proper Poisson distribution.  NaN for first 5 matches.
    *POISSON_FEATURE_COLS,
    # Draw-balance features — capture match symmetry, both teams' draw tendency,
    # and market vs model disagreement on draw probability.
    "goals_asymmetry_5",    # abs(h_scored_5 - a_scored_5): 0 = matched offences
    "combined_draw_tendency",  # sqrt(h_draw_rate_5 * a_draw_rate_5): both draw-prone
    "pi_closeness",         # 1/(1+|pi_att_diff|+|pi_def_diff|): evenly matched
    "market_draw_edge",     # market_draw_prob - poisson_draw: market vs model
    "low_total_xg",         # 1 if pi_exp_total < 2.0: defensive match flag
    "elo_closeness",        # 1/(1+|elo_diff|): close ratings
    # Odds movement / steam — direction of market shift since first stored snapshot.
    # 0 in training (no historical opening odds); real drift at inference.
    "odds_drift_home",      # current_odds - first_odds (negative = shortened = steam)
    "odds_drift_draw",
    "odds_drift_away",
    "odds_drift_over",
    "is_steam_home",        # 1 if drift_home < -0.15 (sharp money on home)
    "is_steam_away",        # 1 if drift_away < -0.15 (sharp money on away)
    # EWMA momentum — exponentially weighted recent goals/points (α=0.3).
    # More weight on last 3-4 matches vs flat rolling averages.
    "h_ewma_scored",        "h_ewma_conceded",
    "a_ewma_scored",        "a_ewma_conceded",
    "h_ewma_form",          "a_ewma_form",
    # League position — normalized rank in current season table (0=1st, 1=last).
    # NaN for first few matches of a season (< 3 teams played).
    "h_league_pos_norm",    "a_league_pos_norm",
    "league_pos_diff",      # h_pos - a_pos: positive = home team ranked worse
    # Standings motivation — competitive interest based on CL/relegation proximity.
    # pts_vs_cl: home/away pts minus pts of team at CL cutoff rank.
    #   negative = outside CL zone; positive = inside.
    # pts_vs_relegation: home/away pts minus pts of team at relegation cutoff.
    #   negative = IN relegation zone; positive = safely above.
    # motivation_diff: (home stake − away stake) × season phase. Positive = home
    #   has more to fight for. NaN early-season (< 3 teams) or unknown league.
    "h_pts_vs_cl",          "a_pts_vs_cl",
    "h_pts_vs_relegation",  "a_pts_vs_relegation",
    "motivation_diff",
    # Card / discipline features — suspension proxy (no player-level data)
    # red_last1: red card in most recent match → likely key suspension next game.
    # reds_5: cumulative red cards over last 5 games → systematic discipline issues.
    # discipline_5: (yellows + 2×reds) / games over last 5 → card rate per game.
    # season_yellows: accumulated yellows this season → threshold suspension risk.
    # suspension_diff: home − away red_last1 → relative suspension advantage.
    "h_red_last1",      "a_red_last1",
    "h_reds_5",         "a_reds_5",
    "h_discipline_5",   "a_discipline_5",
    "h_season_yellows", "a_season_yellows",
    "suspension_diff",
]

# Draw-balance features used only by result model (hurt goals model when shared)
DRAW_BALANCE_COLS = [
    "goals_asymmetry_5",
    "combined_draw_tendency",
    "pi_closeness",
    "market_draw_edge",
    "low_total_xg",
    "elo_closeness",
]

# ── Market-derived features — EXCLUDED from every model ───────────────────────
# User directive (2026-06-17): predictions must be 100% market-independent. The
# bookmaker is used ONLY for post-hoc comparison (EV/value gate, ROI vs sharps),
# never as a model input and never as a serve-time anchor. This covers BOTH the
# de-vig price probabilities AND the odds-microstructure signals (drift/steam),
# since all of them are derived from bookmaker odds. build_features still
# computes them (cheap, harmless); the model feature lists below drop them so
# the trained models never see them. To re-enable, remove names here + retrain.
MARKET_DERIVED_COLS = {
    "market_home_prob", "market_draw_prob", "market_away_prob", "market_over_prob",
    "market_draw_edge",
    "odds_drift_home", "odds_drift_draw", "odds_drift_away", "odds_drift_over",
    "is_steam_home", "is_steam_away",
}

# Result model: all features EXCEPT market-derived ones (and we keep draw-balance)
RESULT_FEATURE_COLS = [f for f in FEATURE_COLS if f not in MARKET_DERIVED_COLS]

# Goals model excludes draw-balance features (noise for O/U) AND market-derived
GOALS_FEATURE_COLS = [
    f for f in FEATURE_COLS
    if f not in set(DRAW_BALANCE_COLS) and f not in MARKET_DERIVED_COLS
]

# BTTS classifier features — goals-scoring focused
BTTS_FEATURE_COLS = [
    "h_goals_scored_5",    "h_goals_scored_10",
    "a_goals_scored_5",    "a_goals_scored_10",
    "h_goals_conceded_5",  "h_goals_conceded_10",
    "a_goals_conceded_5",  "a_goals_conceded_10",
    "h_home_scored_5",     "h_home_conceded_5",
    "a_away_scored_5",     "a_away_conceded_5",
    "h_over25_rate_5",     "a_over25_rate_5",
    "h_over25_rate_10",    "a_over25_rate_10",
    "h_xg_scored_5",       "h_xg_conceded_5",
    "a_xg_scored_5",       "a_xg_conceded_5",
    "pi_exp_home",         "pi_exp_away",         "pi_exp_total",
    "poisson_btts",        "poisson_over_2_5",
    "market_over_prob",
    "h_form_5",            "a_form_5",
    "h_form_10",           "a_form_10",
    "season_phase",        "season_week",
    "elo_diff",            "elo_home_win_prob",
    "league_EPL",          "league_LaLiga",       "league_SerieA",
    "league_Bundesliga",   "league_Ligue1",       "league_GreekSL",
    # H2H goals history — direct signal for BTTS and over/under between this specific pair
    "h2h_count",           "h2h_btts_rate",
    "h2h_total_goals_avg", "h2h_over25_rate",
    "h2h_home_goals_avg",  "h2h_away_goals_avg",
    # Motivation — teams chasing CL / avoiding relegation tend to press harder
    "h_pts_vs_cl",         "a_pts_vs_cl",
    "h_pts_vs_relegation", "a_pts_vs_relegation",
    "motivation_diff",
]

# Drop market-derived features (e.g. market_over_prob) from the BTTS model too —
# market-independent by directive.
BTTS_FEATURE_COLS = [c for c in BTTS_FEATURE_COLS if c not in MARKET_DERIVED_COLS]
