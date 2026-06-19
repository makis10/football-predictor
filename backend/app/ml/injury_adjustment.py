"""
Position-aware, diminishing-returns injury probability adjustment.

Applied AFTER XGBoost + isotonic calibration, at serve-time only.
The raw calibrated prediction stays unchanged in the DB (for accuracy tracking);
the adjusted values are returned by the API and shown to the user.

Why rule-based rather than ML features:
  - Injuries are published ~6-12 h before kickoff — no historical data to train on
    without an expensive API backfill (thousands of requests)
  - Bookmaker odds (our #1 and #2 XGBoost features) already price in known
    injuries — this adjustment is intentionally conservative to avoid
    double-counting with odds-informed predictions
  - Without minutes-played data we use position + injury type as impact proxies

Position-based goal impact:
  Attacker injured   → team scores fewer goals → over_2_5 decreases
  Midfielder injured → mixed: slight scoring drop, slight defending drop
  Defender injured   → opponent scores more goals → over_2_5 increases
  Goalkeeper injured → opponent scores more goals → over_2_5 increases

Diminishing returns:
  1st injured player of a position: full weight (likely a starter)
  2nd: 0.65× (may be a rotation player)
  3rd+: 0.40× (squad depth — minimal impact)

Severity weights:
  Suspended    1.1  — certain absence; likely an important player (card accumulation)
  Injured      1.0  — certain absence
  Questionable 0.35 — uncertain; may start or be on the bench
"""
from __future__ import annotations

# ── Configuration ─────────────────────────────────────────────────────────────

_TYPE_WEIGHT: dict[str, float] = {
    "Suspended":    1.1,
    "Injured":      1.0,
    "Questionable": 0.35,
}
_DEFAULT_WEIGHT = 0.8       # for unknown/unlabelled injury types

_NUDGE_PER_UNIT = 0.033     # 3.3% win-prob shift per "key player equivalent"
_MAX_IMPACT     = 0.13      # cap total 1×2 impact at 13% per team

# Fraction of each position's impact that flows to over_2_5.
# Sign: negative = reduces over_2_5 (fewer goals), positive = increases it.
_GOALS_SIGN: dict[str, float] = {
    "Attacker":   -0.70,   # injured striker → team scores less
    "Midfielder": -0.25,   # mild dual effect
    "Defender":   +0.55,   # opponent gets easier chances
    "Goalkeeper": +0.65,   # weakened keeping → opponent scores more
}
_GOALS_SIGN_UNKNOWN = -0.30  # conservative fallback when position unknown

# Diminishing-returns multipliers for the Nth injured player of the same position.
# Assumption: first absence is a likely starter, subsequent are rotations/bench.
_DEPTH_SCALE = [1.0, 0.65, 0.40]   # index 0 = 1st, 1 = 2nd, 2 = 3rd+


# ── Helpers ───────────────────────────────────────────────────────────────────

def _severity(p: dict) -> float:
    """Severity weight for a single player (pre-depth-scaling)."""
    return _TYPE_WEIGHT.get(p.get("type", "Unknown"), _DEFAULT_WEIGHT)


def _position_group(p: dict) -> str:
    """Normalise position string to one of the four canonical groups."""
    raw = (p.get("position") or "").strip()
    if raw in ("Attacker", "Forward"):
        return "Attacker"
    if raw in ("Midfielder",):
        return "Midfielder"
    if raw in ("Defender",):
        return "Defender"
    if raw in ("Goalkeeper",):
        return "Goalkeeper"
    return "Unknown"


def _team_impact(injuries: list[dict]) -> tuple[float, float]:
    """
    Compute (win_impact, goals_delta) for one team's injury list.

    win_impact  — how much the team's win probability should decrease (positive).
    goals_delta — signed over_2_5 adjustment from this team's injuries.
                  Negative = fewer goals scored/allowed; positive = more.

    Applies:
      • Severity weight per player
      • Depth-scaling (diminishing returns per position group)
      • Per-position goals sign
      • Global win_impact cap (_MAX_IMPACT)
    """
    # Count absences per position group to apply depth scaling
    pos_count: dict[str, int] = {}
    raw_win = 0.0
    raw_goals = 0.0

    for p in injuries:
        sev = _severity(p)
        pos = _position_group(p)
        idx = pos_count.get(pos, 0)
        pos_count[pos] = idx + 1

        depth = _DEPTH_SCALE[min(idx, len(_DEPTH_SCALE) - 1)]
        effective = sev * depth

        raw_win += effective * _NUDGE_PER_UNIT

        goal_sign = _GOALS_SIGN.get(pos, _GOALS_SIGN_UNKNOWN)
        raw_goals += effective * _NUDGE_PER_UNIT * goal_sign   # abs(x)*(1 if x>0 else -1) == x

    win_impact = min(raw_win, _MAX_IMPACT)
    # Scale goals delta proportionally if win was capped
    scale = (win_impact / raw_win) if raw_win > 1e-9 else 1.0
    goals_delta = raw_goals * scale

    return win_impact, goals_delta


# ── Public API ────────────────────────────────────────────────────────────────

def adjust_probabilities(
    home_win: float,
    draw:     float,
    away_win: float,
    over_2_5: float,
    home_injuries: list[dict],
    away_injuries: list[dict],
) -> tuple[float, float, float, float]:
    """
    Nudge match probabilities based on position-aware injury severity.

    Returns (home_win, draw, away_win, over_2_5) — 1×2 renormalized to 1.0.

    1×2 logic (unchanged from v1):
      Home injuries → lower home_win; draw absorbs 40%, away_win 60% of freed mass.
      Away injuries → lower away_win; draw absorbs 40%, home_win 60% of freed mass.

    Over/Under logic (new):
      Each injured player contributes a signed goals delta based on position:
        Attacker  → team scores less    → over_2_5 ↓
        Defender  → opponent scores more → over_2_5 ↑
        GK        → opponent scores more → over_2_5 ↑
        Midfielder → mild negative effect
      Deltas from both teams are summed and applied to over_2_5.
    """
    h_win_impact, h_goals_delta = _team_impact(home_injuries)
    a_win_impact, a_goals_delta = _team_impact(away_injuries)

    # ── 1×2 adjustment ────────────────────────────────────────────────────────
    new_home = home_win - h_win_impact + a_win_impact * 0.60
    new_away = away_win - a_win_impact + h_win_impact * 0.60
    new_draw = draw + (h_win_impact + a_win_impact) * 0.40

    new_home = max(0.02, new_home)
    new_draw  = max(0.02, new_draw)
    new_away  = max(0.02, new_away)

    total = new_home + new_draw + new_away
    new_home /= total
    new_draw  /= total
    new_away  /= total

    # ── O/U adjustment (position-aware) ───────────────────────────────────────
    # h_goals_delta: signed effect of HOME team injuries on total goals
    #   (attacker injured → home scores less → negative)
    # a_goals_delta: signed effect of AWAY team injuries on total goals
    #   (attacker injured → away scores less → negative)
    # Both are summed: combined injuries always reduce or adjust total goals.
    net_goals = h_goals_delta + a_goals_delta
    new_over = max(0.05, min(0.95, over_2_5 + net_goals))

    return (
        round(float(new_home), 4),
        round(float(new_draw),  4),
        round(float(new_away),  4),
        round(float(new_over),  4),
    )


def has_significant_injuries(
    home_injuries: list[dict],
    away_injuries: list[dict],
    min_severity: float = 0.5,
) -> bool:
    """
    Returns True when combined severity clears the threshold.
    Prevents cluttering the UI with trivial Questionable squad fillers.
    """
    total = sum(_severity(p) for p in home_injuries + away_injuries)
    return total >= min_severity
