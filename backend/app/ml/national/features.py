"""
National team feature engineering.

Computes chronological features for each international match:
  - Team Elo (separate from club Elo; K-factor varies by match importance)
  - Rolling form (last 5/10 matches) — goals, points, BTTS, over2.5
  - Competitive-only rolling form (excludes friendlies)
  - H2H history (last 10 meetings)
  - Match context: neutral venue, tournament tier, days rest
  - Targets: result (H/D/A), goals (over 2.5), BTTS

Data source: martj42/international_results results.csv
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ── Elo constants ──────────────────────────────────────────────────────────────
ELO_START   = 1500.0
HOME_ADV    = 100.0    # Elo points added to home team (non-neutral matches)
ELO_SCALE   = 400.0

# K-factor by match tier
K_BY_TIER = {3: 60, 2: 50, 1: 35, 0: 15}

# ── Talent-adjusted Elo (squad league strength) ───────────────────────────────
# The results-Elo is confederation-siloed and blind to player quality, so it
# over-rates teams that farm wins vs weak regional opponents (e.g. CONCACAF) and
# under-rates strong squads with a brutal schedule. We blend it with a "talent
# Elo" derived from the LEAGUES the called-up squad actually plays in
# (league_strength.py + scripts/fetch_squad_strength.py → squad_strength.json).
# This is sporting data, NOT the betting market. INFERENCE-ONLY: training keeps
# pure results-Elo (no historical squad data). TALENT_BLEND_W=0 disables it.
TALENT_BLEND_W = 0.45   # weight on squad-talent Elo; (1−w) on results-Elo

_SQUAD_STRENGTH_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "raw" / "international" / "squad_strength.json"
)
_squad_strength_cache: Optional[dict] = None


def _load_squad_strength() -> dict:
    """team → strength (0..1) from squad_strength.json (cached). {} if absent."""
    global _squad_strength_cache
    if _squad_strength_cache is None:
        try:
            import json
            raw = json.loads(_SQUAD_STRENGTH_PATH.read_text())
            # Skip low-confidence teams (too few rated players → noisy strength);
            # they fall back to pure results-Elo.
            _squad_strength_cache = {
                k: v["strength"] for k, v in raw.items()
                if isinstance(v, dict) and v.get("strength") is not None
                and not v.get("low_confidence")
            }
        except Exception:
            _squad_strength_cache = {}
    return _squad_strength_cache


def _talent_stats(snapshot: dict) -> Optional[dict]:
    """Mean/std of results-Elo and squad strength over the cohort with BOTH, so
    the two are normalised on the same population. Cached on the snapshot.
    Returns None when squad data is unavailable (→ no adjustment)."""
    if "_talent_stats" in snapshot:
        return snapshot["_talent_stats"] or None
    strengths = _load_squad_strength()
    elo = snapshot.get("elo", {})
    pairs = [(elo[t], strengths[t]) for t in strengths if t in elo]
    if len(pairs) < 8:
        snapshot["_talent_stats"] = {}      # sentinel: unavailable
        return None
    es = np.array([p[0] for p in pairs], dtype=float)
    ss = np.array([p[1] for p in pairs], dtype=float)
    stats = {
        "mu_e": float(es.mean()), "sd_e": float(es.std() or 1.0),
        "mu_s": float(ss.mean()), "sd_s": float(ss.std() or 1.0),
    }
    snapshot["_talent_stats"] = stats
    return stats


def talent_adjusted_elo(snapshot: dict, team: str, w: float = TALENT_BLEND_W) -> float:
    """Blend results-Elo with a squad-talent Elo (squad strength expressed in
    Elo units via z-score). Falls back to pure results-Elo when w<=0 or the team
    has no squad-strength data."""
    results_elo = snapshot.get("elo", {}).get(team, ELO_START)
    if w <= 0:
        return results_elo
    stats = _talent_stats(snapshot)
    if not stats:
        return results_elo
    s = _load_squad_strength().get(team)
    if s is None:
        return results_elo
    elo_talent = stats["mu_e"] + stats["sd_e"] * (s - stats["mu_s"]) / stats["sd_s"]
    return (1.0 - w) * results_elo + w * elo_talent

# ── Match classification ───────────────────────────────────────────────────────
_TIER3 = {
    "FIFA World Cup",
}
_TIER2 = {
    "UEFA Euro", "UEFA European Championship",
    "Copa América", "Copa America",
    "African Cup of Nations", "Africa Cup of Nations",
    "AFC Asian Cup",
    "Gold Cup", "CONCACAF Gold Cup",
    "CONCACAF Nations League",
    "UEFA Nations League",
    "Oceania Nations Cup", "OFC Nations Cup",
    "COSAFA Cup",  # actually tier 1 but leave here
    "FIFA Confederations Cup",
}
_TIER1_KW = {          # keywords that mark qualifiers / competitive
    "qualif", "qualifier", "qualification",
    "nations league", "gold cup qualifier",
}

# Sample weight by tier (for training)
WEIGHT_BY_TIER = {3: 1.0, 2: 0.95, 1: 0.75, 0: 0.30}

# Rolling window sizes
_W5  = 5
_W10 = 10
_H2H_W = 10   # H2H history window


def classify_tournament(tournament: str) -> tuple[int, bool]:
    """Return (tier, is_competitive).
    tier: 0=friendly, 1=qualifier/other competitive, 2=major continental, 3=WC
    """
    t = tournament.strip()
    tl = t.lower()

    if t in _TIER3:
        return 3, True
    if t in _TIER2:
        return 2, True
    if "friendly" in tl or "four nations" in tl or "peace cup" in tl:
        return 0, False
    # qualifier keyword
    for kw in ("qualif", "qualification"):
        if kw in tl:
            return 1, True
    # Nations league variants
    if "nations league" in tl or "nations cup" in tl:
        return 2, True
    # Other competitive
    return 1, True


def _elo_expected(elo_a: float, elo_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / ELO_SCALE))


def elo_three_way(
    adj_diff: float,
    scale: float = 110.0,
    draw_base: float = 0.26,
    draw_decay: float = 0.7,
) -> tuple[float, float, float]:
    """Map a (home-advantage-adjusted) talent-Elo difference to a calibrated
    1×2 distribution (P_home, P_draw, P_away).

    The trained international result model is flat — it under-rates clear
    favourites and over-predicts draws on a thin dataset. This Elo-derived 1×2 is
    used to sharpen the served probabilities toward the (market-independent)
    talent-Elo signal. Draw probability peaks for even games and decays as the
    sides diverge; the win/loss split follows a logistic on the Elo gap.
    """
    # Constants FITTED on the cal window by scripts/fit_national_blend.py
    # (persisted in models/national/blend.json); defaults = pre-fit fallbacks.
    ws = 1.0 / (1.0 + math.exp(-adj_diff / scale))            # win share of decisive
    p_draw = draw_base * math.exp(-((adj_diff / 400.0) ** 2) * draw_decay)
    p_home = (1.0 - p_draw) * ws
    p_away = (1.0 - p_draw) * (1.0 - ws)
    return p_home, p_draw, p_away


def _elo_update(
    elo_h: float, elo_a: float,
    hg: int, ag: int,
    is_neutral: bool,
    tier: int,
) -> tuple[float, float]:
    K = K_BY_TIER[tier]
    adj_h = elo_h + (0.0 if is_neutral else HOME_ADV)
    exp_h = _elo_expected(adj_h, elo_a)
    if hg > ag:
        actual = 1.0
    elif hg == ag:
        actual = 0.5
    else:
        actual = 0.0
    delta = K * (actual - exp_h)
    return elo_h + delta, elo_a - delta


def _elo_win_prob(elo_h: float, elo_a: float, is_neutral: bool) -> float:
    adj_h = elo_h + (0.0 if is_neutral else HOME_ADV)
    return _elo_expected(adj_h, elo_a)


def _safe_mean(lst: list) -> float:
    return float(np.mean(lst)) if lst else np.nan


def _safe_rate(lst: list, condition) -> float:
    return float(sum(condition(x) for x in lst) / len(lst)) if lst else np.nan


# ── Public API ─────────────────────────────────────────────────────────────────

def load_results(data_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load martj42 results.csv, return (historical, upcoming).

    historical: matches with actual scores
    upcoming:   matches with NA scores (future fixtures)
    """
    path = Path(data_dir) / "results.csv"
    df = pd.read_csv(path, dtype=str)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["neutral"] = df["neutral"].str.upper().isin({"TRUE", "1", "YES"})

    # Drop rows without BOTH team names. Knockout-slot fixtures (WC final /
    # 3rd-place match) sit in the dataset with empty teams until the previous
    # round settles them — predicting "nan vs nan" crashed the DB save.
    has_teams = (df["home_team"].notna() & (df["home_team"].str.upper() != "NA") &
                 df["away_team"].notna() & (df["away_team"].str.upper() != "NA"))
    df = df[has_teams].copy()

    # Split: upcoming = NA scores
    mask_played = df["home_score"].notna() & (df["home_score"] != "NA")
    historical = df[mask_played].copy()
    upcoming   = df[~mask_played].copy()

    # A row with NA scores whose date is well in the PAST is not a "future
    # fixture" — it's a dataset defect (minor friendly the source scheduled but
    # never recorded a result for). Left in `upcoming`, predict_national re-saves
    # it every run, producing DB predictions that can never settle (they clutter
    # the national view and keep the post-tournament "has upcoming?" logic true
    # forever). Floor to a 2-day grace so genuinely-just-kicked-off games survive
    # for same-day prediction, but 6-week-old ghosts are dropped.
    floor = pd.Timestamp.now().normalize() - pd.Timedelta(days=2)
    upcoming = upcoming[upcoming["date"] >= floor].copy()

    historical["home_goals"] = pd.to_numeric(historical["home_score"], errors="coerce").fillna(0).astype(int)
    historical["away_goals"] = pd.to_numeric(historical["away_score"], errors="coerce").fillna(0).astype(int)
    historical = historical.sort_values("date").reset_index(drop=True)

    return historical, upcoming


def build_features(historical: pd.DataFrame, min_year: int = 1990) -> pd.DataFrame:
    """
    Walk through historical matches chronologically, computing features
    for each match from all data preceding it (no leakage).

    Filters to min_year+ for training (older data is noisy).
    Returns DataFrame with feature columns + targets.
    """
    # Process ALL history for state (Elo continuity), but only keep rows ≥ min_year
    df = historical.sort_values("date").reset_index(drop=True)

    elo: dict[str, float] = defaultdict(lambda: ELO_START)

    # Rolling windows — tuples of (goals_scored, goals_conceded, points, is_competitive)
    team_all:  dict[str, deque] = defaultdict(lambda: deque(maxlen=_W10))  # last 10 all
    team_comp: dict[str, deque] = defaultdict(lambda: deque(maxlen=_W5))   # last 5 competitive

    # H2H: key = frozenset({h, a})
    h2h: dict[frozenset, deque] = defaultdict(lambda: deque(maxlen=_H2H_W))

    # Last match date per team
    last_date: dict[str, pd.Timestamp] = {}

    feature_rows = []

    for _, row in df.iterrows():
        h = row["home_team"]
        a = row["away_team"]
        hg = int(row["home_goals"])
        ag = int(row["away_goals"])
        date = row["date"]
        tournament = row["tournament"]
        neutral = bool(row["neutral"])
        tier, is_comp = classify_tournament(tournament)

        # ── Feature extraction (BEFORE state update) ─────────────────────────
        feat: dict = {}
        feat["date"]       = date
        feat["home_team"]  = h
        feat["away_team"]  = a
        feat["tournament"] = tournament
        feat["neutral"]    = float(neutral)

        # Elo
        feat["h_elo"] = elo[h]
        feat["a_elo"] = elo[a]
        feat["elo_diff"]         = elo[h] - elo[a]
        feat["elo_home_win_prob"] = _elo_win_prob(elo[h], elo[a], neutral)

        # Rolling all matches (last 10)
        h_all = list(team_all[h]);  a_all = list(team_all[a])
        h_all5 = h_all[-5:];        a_all5 = a_all[-5:]

        def _mean_stat(records, key):
            vals = [r[key] for r in records]
            return _safe_mean(vals)

        feat["h_form_10"]     = _mean_stat(h_all, "pts")
        feat["a_form_10"]     = _mean_stat(a_all, "pts")
        feat["h_form_5"]      = _mean_stat(h_all5, "pts")
        feat["a_form_5"]      = _mean_stat(a_all5, "pts")
        feat["h_scored_10"]   = _mean_stat(h_all, "gs")
        feat["a_scored_10"]   = _mean_stat(a_all, "gs")
        feat["h_scored_5"]    = _mean_stat(h_all5, "gs")
        feat["a_scored_5"]    = _mean_stat(a_all5, "gs")
        feat["h_conceded_10"] = _mean_stat(h_all, "gc")
        feat["a_conceded_10"] = _mean_stat(a_all, "gc")
        feat["h_conceded_5"]  = _mean_stat(h_all5, "gc")
        feat["a_conceded_5"]  = _mean_stat(a_all5, "gc")
        feat["h_btts_5"]      = _mean_stat(h_all5, "btts")
        feat["a_btts_5"]      = _mean_stat(a_all5, "btts")
        feat["h_over25_5"]    = _mean_stat(h_all5, "over25")
        feat["a_over25_5"]    = _mean_stat(a_all5, "over25")
        feat["h_btts_10"]     = _mean_stat(h_all, "btts")
        feat["a_btts_10"]     = _mean_stat(a_all, "btts")
        feat["h_over25_10"]   = _mean_stat(h_all, "over25")
        feat["a_over25_10"]   = _mean_stat(a_all, "over25")
        feat["h_draw_rate_5"]  = _mean_stat(h_all5, "drew")
        feat["a_draw_rate_5"]  = _mean_stat(a_all5, "drew")
        feat["h_draw_rate_10"] = _mean_stat(h_all, "drew")
        feat["a_draw_rate_10"] = _mean_stat(a_all, "drew")

        # Draw-closeness derived features
        feat["elo_closeness"] = 1.0 / (1.0 + abs(elo[h] - elo[a]))
        feat["form_closeness"] = (
            1.0 / (1.0 + abs(_mean_stat(h_all5, "pts") - _mean_stat(a_all5, "pts")))
            if h_all5 and a_all5 else np.nan
        )
        feat["goals_asymmetry_5"] = (
            abs(_mean_stat(h_all5, "gs") - _mean_stat(a_all5, "gs"))
            if h_all5 and a_all5 else np.nan
        )

        # Competitive-only form (last 5 competitive)
        h_comp = list(team_comp[h]); a_comp = list(team_comp[a])
        feat["h_comp_form_5"]     = _mean_stat(h_comp, "pts")
        feat["a_comp_form_5"]     = _mean_stat(a_comp, "pts")
        feat["h_comp_scored_5"]   = _mean_stat(h_comp, "gs")
        feat["a_comp_scored_5"]   = _mean_stat(a_comp, "gs")
        feat["h_comp_conceded_5"] = _mean_stat(h_comp, "gc")
        feat["a_comp_conceded_5"] = _mean_stat(a_comp, "gc")

        # H2H
        key = frozenset({h, a})
        h2h_list = list(h2h[key])
        feat["h2h_count"] = len(h2h_list)
        if h2h_list:
            h_wins = sum(1 for r in h2h_list if (r["home"] == h and r["result"] == 1) or
                         (r["home"] != h and r["result"] == -1))
            draws  = sum(1 for r in h2h_list if r["result"] == 0)
            feat["h2h_h_win_rate"]  = h_wins / len(h2h_list)
            feat["h2h_draw_rate"]   = draws  / len(h2h_list)
            feat["h2h_draws"]       = float(draws)
            feat["h2h_avg_goals"]   = _safe_mean([r["total_g"] for r in h2h_list])
            feat["h2h_btts_rate"]   = _safe_mean([r["btts"]    for r in h2h_list])
        else:
            feat["h2h_h_win_rate"] = np.nan
            feat["h2h_draw_rate"]  = np.nan
            feat["h2h_draws"]      = np.nan
            feat["h2h_avg_goals"]  = np.nan
            feat["h2h_btts_rate"]  = np.nan

        # Days rest
        h_rest = (date - last_date[h]).days if h in last_date else np.nan
        a_rest = (date - last_date[a]).days if a in last_date else np.nan
        feat["h_days_rest"] = float(h_rest) if not (isinstance(h_rest, float) and math.isnan(h_rest)) else np.nan
        feat["a_days_rest"] = float(a_rest) if not (isinstance(a_rest, float) and math.isnan(a_rest)) else np.nan
        feat["rest_diff"]   = (feat["h_days_rest"] - feat["a_days_rest"]
                               if pd.notna(feat["h_days_rest"]) and pd.notna(feat["a_days_rest"])
                               else np.nan)

        # Match context
        feat["tournament_tier"] = float(tier)
        feat["is_competitive"]  = float(is_comp)
        feat["match_weight"]    = WEIGHT_BY_TIER[tier]

        # Targets
        if hg > ag:
            feat["target_result"] = 0   # Home win
            h_pts, a_pts = 3, 0
        elif hg == ag:
            feat["target_result"] = 1   # Draw
            h_pts = a_pts = 1
        else:
            feat["target_result"] = 2   # Away win
            h_pts, a_pts = 0, 3
        feat["target_goals"] = int((hg + ag) > 2.5)
        feat["target_btts"]  = int(hg > 0 and ag > 0)
        feat["home_goals"]   = hg
        feat["away_goals"]   = ag

        if date.year >= min_year:
            feature_rows.append(feat)

        # ── State update (AFTER feature extraction — no leakage) ─────────────
        record_h = {"gs": hg, "gc": ag, "pts": h_pts,
                    "btts": int(hg > 0 and ag > 0),
                    "over25": int(hg + ag > 2.5),
                    "drew": int(hg == ag)}
        record_a = {"gs": ag, "gc": hg, "pts": a_pts,
                    "btts": int(hg > 0 and ag > 0),
                    "over25": int(hg + ag > 2.5),
                    "drew": int(hg == ag)}
        team_all[h].append(record_h); team_all[a].append(record_a)
        if is_comp:
            team_comp[h].append(record_h); team_comp[a].append(record_a)

        h2h[key].append({
            "home": h, "result": 1 if hg > ag else (-1 if ag > hg else 0),
            "total_g": hg + ag, "btts": int(hg > 0 and ag > 0),
        })

        new_h_elo, new_a_elo = _elo_update(elo[h], elo[a], hg, ag, neutral, tier)
        elo[h] = new_h_elo; elo[a] = new_a_elo
        last_date[h] = date; last_date[a] = date

    result = pd.DataFrame(feature_rows)
    return result


def build_snapshot(historical: pd.DataFrame) -> dict:
    """
    Walk through ALL historical matches and return state snapshot
    (Elo, rolling windows, H2H, last_date) for use in prediction.
    """
    df = historical.sort_values("date").reset_index(drop=True)

    elo: dict[str, float]        = defaultdict(lambda: ELO_START)
    team_all:  dict[str, deque]  = defaultdict(lambda: deque(maxlen=_W10))
    team_comp: dict[str, deque]  = defaultdict(lambda: deque(maxlen=_W5))
    h2h: dict[frozenset, deque]  = defaultdict(lambda: deque(maxlen=_H2H_W))
    last_date: dict[str, pd.Timestamp] = {}

    for _, row in df.iterrows():
        h = row["home_team"]; a = row["away_team"]
        hg = int(row["home_goals"]); ag = int(row["away_goals"])
        date = row["date"]
        neutral = bool(row["neutral"])
        tier, is_comp = classify_tournament(row["tournament"])

        if hg > ag:   h_pts, a_pts = 3, 0
        elif hg == ag: h_pts = a_pts = 1
        else:          h_pts, a_pts = 0, 3

        record_h = {"gs": hg, "gc": ag, "pts": h_pts,
                    "btts": int(hg > 0 and ag > 0),
                    "over25": int(hg + ag > 2.5), "drew": int(hg == ag)}
        record_a = {"gs": ag, "gc": hg, "pts": a_pts,
                    "btts": int(hg > 0 and ag > 0),
                    "over25": int(hg + ag > 2.5), "drew": int(hg == ag)}

        team_all[h].append(record_h); team_all[a].append(record_a)
        if is_comp:
            team_comp[h].append(record_h); team_comp[a].append(record_a)

        h2h[frozenset({h, a})].append({
            "home": h, "result": 1 if hg > ag else (-1 if ag > hg else 0),
            "total_g": hg + ag, "btts": int(hg > 0 and ag > 0),
        })

        new_h_elo, new_a_elo = _elo_update(elo[h], elo[a], hg, ag, neutral, tier)
        elo[h] = new_h_elo; elo[a] = new_a_elo
        last_date[h] = date; last_date[a] = date

    return dict(
        elo=dict(elo),
        team_all=dict(team_all),
        team_comp=dict(team_comp),
        h2h=dict(h2h),
        last_date=last_date,
    )


def compute_match_features(
    snapshot: dict,
    home_team: str,
    away_team: str,
    tournament: str,
    neutral: bool,
    match_date: pd.Timestamp,
) -> dict:
    """Compute features for a single upcoming match from a frozen snapshot."""
    elo      = snapshot["elo"]
    team_all = snapshot["team_all"]
    team_comp= snapshot["team_comp"]
    h2h_snap = snapshot["h2h"]
    last_date= snapshot["last_date"]

    tier, is_comp = classify_tournament(tournament)
    h, a = home_team, away_team

    feat: dict = {}
    feat["home_team"]  = h
    feat["away_team"]  = a
    feat["tournament"] = tournament
    feat["neutral"]    = float(neutral)
    feat["tournament_tier"] = float(tier)
    feat["is_competitive"]  = float(is_comp)
    feat["match_weight"]    = WEIGHT_BY_TIER[tier]

    # Talent-adjusted Elo (blends results-Elo with squad league strength).
    # Inference-only; falls back to pure results-Elo when no squad data.
    h_elo = talent_adjusted_elo(snapshot, h)
    a_elo = talent_adjusted_elo(snapshot, a)
    feat["h_elo"] = h_elo
    feat["a_elo"] = a_elo
    feat["elo_diff"]          = h_elo - a_elo
    feat["elo_home_win_prob"] = _elo_win_prob(h_elo, a_elo, neutral)

    h_all  = list(team_all.get(h, deque(maxlen=_W10)))
    a_all  = list(team_all.get(a, deque(maxlen=_W10)))
    h_all5 = h_all[-5:]; a_all5 = a_all[-5:]
    h_comp = list(team_comp.get(h, deque(maxlen=_W5)))
    a_comp = list(team_comp.get(a, deque(maxlen=_W5)))

    def _m(records, key):
        vals = [r[key] for r in records]
        return _safe_mean(vals)

    feat["h_form_10"]      = _m(h_all,  "pts")
    feat["a_form_10"]      = _m(a_all,  "pts")
    feat["h_form_5"]       = _m(h_all5, "pts")
    feat["a_form_5"]       = _m(a_all5, "pts")
    feat["h_scored_10"]    = _m(h_all,  "gs")
    feat["a_scored_10"]    = _m(a_all,  "gs")
    feat["h_scored_5"]     = _m(h_all5, "gs")
    feat["a_scored_5"]     = _m(a_all5, "gs")
    feat["h_conceded_10"]  = _m(h_all,  "gc")
    feat["a_conceded_10"]  = _m(a_all,  "gc")
    feat["h_conceded_5"]   = _m(h_all5, "gc")
    feat["a_conceded_5"]   = _m(a_all5, "gc")
    feat["h_btts_5"]       = _m(h_all5, "btts")
    feat["a_btts_5"]       = _m(a_all5, "btts")
    feat["h_over25_5"]     = _m(h_all5, "over25")
    feat["a_over25_5"]     = _m(a_all5, "over25")
    feat["h_btts_10"]      = _m(h_all,  "btts")
    feat["a_btts_10"]      = _m(a_all,  "btts")
    feat["h_over25_10"]    = _m(h_all,  "over25")
    feat["a_over25_10"]    = _m(a_all,  "over25")
    feat["h_draw_rate_5"]  = _m(h_all5, "drew")
    feat["a_draw_rate_5"]  = _m(a_all5, "drew")
    feat["h_draw_rate_10"] = _m(h_all,  "drew")
    feat["a_draw_rate_10"] = _m(a_all,  "drew")

    # Draw-closeness derived features
    feat["elo_closeness"]    = 1.0 / (1.0 + abs(h_elo - a_elo))
    feat["form_closeness"]   = (
        1.0 / (1.0 + abs(_m(h_all5, "pts") - _m(a_all5, "pts")))
        if h_all5 and a_all5 else np.nan
    )
    feat["goals_asymmetry_5"] = (
        abs(_m(h_all5, "gs") - _m(a_all5, "gs"))
        if h_all5 and a_all5 else np.nan
    )

    feat["h_comp_form_5"]     = _m(h_comp, "pts")
    feat["a_comp_form_5"]     = _m(a_comp, "pts")
    feat["h_comp_scored_5"]   = _m(h_comp, "gs")
    feat["a_comp_scored_5"]   = _m(a_comp, "gs")
    feat["h_comp_conceded_5"] = _m(h_comp, "gc")
    feat["a_comp_conceded_5"] = _m(a_comp, "gc")

    key = frozenset({h, a})
    h2h_list = list(h2h_snap.get(key, deque()))
    feat["h2h_count"] = len(h2h_list)
    if h2h_list:
        h_wins = sum(1 for r in h2h_list if (r["home"] == h and r["result"] == 1) or
                     (r["home"] != h and r["result"] == -1))
        draws  = sum(1 for r in h2h_list if r["result"] == 0)
        feat["h2h_h_win_rate"]  = h_wins / len(h2h_list)
        feat["h2h_draw_rate"]   = draws  / len(h2h_list)
        feat["h2h_draws"]       = float(draws)
        feat["h2h_avg_goals"]   = _safe_mean([r["total_g"] for r in h2h_list])
        feat["h2h_btts_rate"]   = _safe_mean([r["btts"]    for r in h2h_list])
    else:
        feat["h2h_h_win_rate"] = np.nan
        feat["h2h_draw_rate"]  = np.nan
        feat["h2h_draws"]      = np.nan
        feat["h2h_avg_goals"]  = np.nan
        feat["h2h_btts_rate"]  = np.nan

    if match_date is not None:
        h_rest = (match_date - last_date[h]).days if h in last_date else np.nan
        a_rest = (match_date - last_date[a]).days if a in last_date else np.nan
    else:
        h_rest = a_rest = np.nan
    feat["h_days_rest"] = float(h_rest) if pd.notna(h_rest) else np.nan
    feat["a_days_rest"] = float(a_rest) if pd.notna(a_rest) else np.nan
    feat["rest_diff"]   = (feat["h_days_rest"] - feat["a_days_rest"]
                           if pd.notna(feat["h_days_rest"]) and pd.notna(feat["a_days_rest"])
                           else np.nan)

    return feat


# ── Feature column list (used to subset DataFrame for model input) ─────────────
NATIONAL_FEATURE_COLS = [
    # Elo
    "h_elo", "a_elo", "elo_diff", "elo_home_win_prob",
    # Rolling all matches
    "h_form_5",     "a_form_5",     "h_form_10",     "a_form_10",
    "h_scored_5",   "a_scored_5",   "h_scored_10",   "a_scored_10",
    "h_conceded_5", "a_conceded_5", "h_conceded_10", "a_conceded_10",
    "h_btts_5",     "a_btts_5",     "h_btts_10",     "a_btts_10",
    "h_over25_5",   "a_over25_5",   "h_over25_10",   "a_over25_10",
    "h_draw_rate_5",  "a_draw_rate_5",
    "h_draw_rate_10", "a_draw_rate_10",
    # Draw-closeness
    "elo_closeness", "form_closeness", "goals_asymmetry_5",
    # Competitive-only form
    "h_comp_form_5",     "a_comp_form_5",
    "h_comp_scored_5",   "a_comp_scored_5",
    "h_comp_conceded_5", "a_comp_conceded_5",
    # H2H
    "h2h_count", "h2h_h_win_rate", "h2h_draw_rate", "h2h_draws",
    "h2h_avg_goals", "h2h_btts_rate",
    # Context
    "neutral", "tournament_tier", "is_competitive",
    # Rest
    "h_days_rest", "a_days_rest", "rest_diff",
]

# Draw specialist features — focused on signals that distinguish draws from decisive outcomes
DRAW_FEATURE_COLS = [
    "h_draw_rate_5",   "a_draw_rate_5",
    "h_draw_rate_10",  "a_draw_rate_10",
    "h2h_draw_rate",   "h2h_draws",
    "elo_diff",        "elo_home_win_prob", "elo_closeness",
    "form_closeness",  "goals_asymmetry_5",
    "h_form_5",        "a_form_5",
    "h_comp_form_5",   "a_comp_form_5",
    "h_scored_5",      "a_scored_5",
    "h_conceded_5",    "a_conceded_5",
    "neutral",         "tournament_tier",
]

# Optional (NaN-possible): H2H (new pairs), days_rest (first match), comp form (new teams)
NATIONAL_OPTIONAL_COLS = {
    "h2h_h_win_rate", "h2h_draw_rate", "h2h_draws", "h2h_avg_goals", "h2h_btts_rate",
    "h_days_rest", "a_days_rest", "rest_diff",
    "h_comp_form_5", "a_comp_form_5",
    "h_comp_scored_5", "a_comp_scored_5",
    "h_comp_conceded_5", "a_comp_conceded_5",
    "h_form_5", "a_form_5", "h_form_10", "a_form_10",
    "h_scored_5", "a_scored_5", "h_scored_10", "a_scored_10",
    "h_conceded_5", "a_conceded_5", "h_conceded_10", "a_conceded_10",
    "h_btts_5", "a_btts_5", "h_btts_10", "a_btts_10",
    "h_over25_5", "a_over25_5", "h_over25_10", "a_over25_10",
    "h_draw_rate_5", "a_draw_rate_5", "h_draw_rate_10", "a_draw_rate_10",
    "elo_closeness", "form_closeness", "goals_asymmetry_5",
}
