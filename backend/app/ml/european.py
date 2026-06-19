"""
European competition feature engineering.

Computes "schedule congestion" features for each domestic match:
  - Did the home/away team play a European game in the last N days?
  - Was it an away leg? (away travel is more taxing)
  - What was the result? (elimination hangover vs. winning momentum)

These features are NaN when no European data is available (e.g. pre-2023
seasons where the free API tier has no data, or teams not in Europe).
XGBoost handles NaN natively — no imputation needed.

DATA COVERAGE (football-data.org free tier):
  - Champions League: 2023/24, 2024/25, 2025/26 ✅
  - Europa League:    not available (paid plan needed)
  - Conference Lg:    not available (paid plan needed)
"""

from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd

EUROPEAN_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "european")
CONGESTION_WINDOW = 4   # days — if team played Europe within this window, fatigue applies


def load_european_data(european_dir: str = EUROPEAN_DIR) -> pd.DataFrame | None:
    """
    Load all European fixture CSVs and return a single normalised DataFrame.
    Returns None if no files are found (graceful degradation).

    Columns: date, competition, stage, home_team, away_team,
             home_goals, away_goals, status
    """
    files = glob.glob(os.path.join(european_dir, "*.csv"))
    if not files:
        return None

    frames = []
    for path in sorted(files):
        try:
            df = pd.read_csv(path)
            df["date"] = pd.to_datetime(df["date"])
            frames.append(df)
        except Exception as e:
            print(f"[warn] Could not load {path}: {e}")

    if not frames:
        return None

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("date").reset_index(drop=True)
    return combined


def add_european_features(
    domestic: pd.DataFrame,
    european: pd.DataFrame | None,
    window_days: int = CONGESTION_WINDOW,
) -> pd.DataFrame:
    """
    Attach European congestion features to the domestic match DataFrame.

    domestic  : DataFrame with at minimum columns [Date, home_team, away_team]
                Row order must be chronological (build_features guarantees this).
    european  : Output of load_european_data(). May be None.

    Returns domestic with 6 new columns appended (NaN = no Europe game in
    window; the fatigue flags are only ever set to 1.0, never 0.0 — absence of
    fatigue is represented by NaN, which XGBoost handles natively):
        h_eur_fatigue  (1/NaN)    — home team played Europe in last <window> days
        a_eur_fatigue  (1/NaN)    — away team played Europe in last <window> days
        h_eur_away     (0/1/NaN)  — home team's last Europe game was an away leg
        a_eur_away     (0/1/NaN)  — away team's last Europe game was an away leg
        h_eur_result   (-1/0/1/NaN) — result for home team in last Europe game
        a_eur_result   (-1/0/1/NaN) — result for away team in last Europe game
    """
    # Initialise all six columns as NaN
    for col in ["h_eur_fatigue", "a_eur_fatigue",
                "h_eur_away",    "a_eur_away",
                "h_eur_result",  "a_eur_result"]:
        domestic[col] = np.nan

    if european is None or european.empty:
        return domestic

    # Only use FINISHED matches for fatigue calculation
    # (SCHEDULED matches are included in the file for upcoming-match context,
    #  but they haven't been played yet and must not inflate fatigue counts.)
    eur = european[european["status"] == "FINISHED"].copy()
    eur = eur.sort_values("date").reset_index(drop=True)

    # Pre-group by team for O(1) lookup instead of O(n×m) full scan per row.
    # Each team's rows (both home and away legs) are stored sorted by date.
    _eur_by_team: dict[str, list] = {}
    for _, erow in eur.iterrows():
        for side_team in (erow["home_team"], erow["away_team"]):
            _eur_by_team.setdefault(side_team, []).append(erow)

    def _team_last_euro(team: str, before_date: pd.Timestamp) -> pd.Series | None:
        """Most recent FINISHED European match for <team> strictly before <before_date>
        and within the congestion window."""
        cutoff = before_date - pd.Timedelta(days=window_days)
        candidates = [
            r for r in _eur_by_team.get(team, [])
            if cutoff <= r["date"] < before_date
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r["date"])

    def _result_for_team(row: pd.Series, team: str) -> float:
        """Returns 1=win, 0=draw, -1=loss, NaN=not finished."""
        if row["status"] != "FINISHED":
            return np.nan
        hg = row["home_goals"]
        ag = row["away_goals"]
        if pd.isna(hg) or pd.isna(ag):
            return np.nan
        hg, ag = int(hg), int(ag)
        if row["home_team"] == team:
            if hg > ag: return 1.0
            if hg == ag: return 0.0
            return -1.0
        else:  # team is away
            if ag > hg: return 1.0
            if ag == hg: return 0.0
            return -1.0

    # Vectorised-ish approach: iterate domestic rows but cache european lookups
    for idx, dom_row in domestic.iterrows():
        date = dom_row["Date"]
        home = dom_row["home_team"]
        away = dom_row["away_team"]

        for side, team, fat_col, away_col, res_col in [
            ("home", home, "h_eur_fatigue", "h_eur_away", "h_eur_result"),
            ("away", away, "a_eur_fatigue", "a_eur_away", "a_eur_result"),
        ]:
            euro_match = _team_last_euro(team, date)
            if euro_match is None:
                continue   # NaN stays

            domestic.at[idx, fat_col] = 1.0
            domestic.at[idx, away_col] = float(euro_match["away_team"] == team)
            domestic.at[idx, res_col]  = _result_for_team(euro_match, team)

    return domestic


# Feature column names — used by train.py / predict.py
EUROPEAN_FEATURE_COLS = [
    "h_eur_fatigue",
    "a_eur_fatigue",
    "h_eur_away",
    "a_eur_away",
    "h_eur_result",
    "a_eur_result",
]
