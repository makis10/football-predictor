from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class WinProbabilities(BaseModel):
    home_win: float
    draw: float
    away_win: float


class GoalsPrediction(BaseModel):
    over_2_5_probability: float
    prediction: str  # "OVER" / "UNDER"


class PredictionResponse(BaseModel):
    match_id: int
    home_team: str
    away_team: str
    league: str
    match_date: date
    win_probabilities: WinProbabilities
    goals: GoalsPrediction
    btts_prob: Optional[float] = None   # Both Teams To Score — Poisson-derived
    model_version: str
    confidence: str

    model_config = {"from_attributes": True, "protected_namespaces": ()}


# ── Odds / Analysis schemas ───────────────────────────────────────────────────

class BookmakerFairProbs(BaseModel):
    home_win:  Optional[float] = None
    draw:      Optional[float] = None
    away_win:  Optional[float] = None
    over_2_5:  Optional[float] = None
    under_2_5: Optional[float] = None
    btts_yes:  Optional[float] = None   # GG — both teams score
    btts_no:   Optional[float] = None   # NG — not both teams score


class BookmakerRawOdds(BaseModel):
    home_win:  Optional[float] = None
    draw:      Optional[float] = None
    away_win:  Optional[float] = None
    over_2_5:  Optional[float] = None
    under_2_5: Optional[float] = None
    btts_yes:  Optional[float] = None   # GG avg decimal odds
    btts_no:   Optional[float] = None   # NG avg decimal odds


class BookmakerData(BaseModel):
    fair_probs:     BookmakerFairProbs
    raw_odds:       BookmakerRawOdds
    bookmakers:     List[str]
    num_bookmakers: int


class ModelProbs(BaseModel):
    home_win: float
    draw:     float
    away_win: float
    over_2_5: float
    btts:     Optional[float] = None   # Both Teams To Score (Poisson-derived)


class InjuredPlayer(BaseModel):
    name:     str
    type:     str              # "Injured" / "Suspended" / "Questionable"
    reason:   str
    position: Optional[str] = None   # "Attacker" / "Midfielder" / "Defender" / "Goalkeeper"


class InjuryData(BaseModel):
    home: List[InjuredPlayer] = []
    away: List[InjuredPlayer] = []


class OddsMovement(BaseModel):
    """Delta between the two most recent odds snapshots (latest − previous).
    Positive = odds drifted out (bookmaker less confident).
    Negative = odds shortened (steam / smart-money signal)."""
    home_delta:         Optional[float] = None
    draw_delta:         Optional[float] = None
    away_delta:         Optional[float] = None
    over_delta:         Optional[float] = None
    snapshot_age_hours: Optional[float] = None   # age of the *previous* snapshot


class CorrectScoreProb(BaseModel):
    score: str    # e.g. "1-0"
    prob: float   # e.g. 0.18


class PoissonStats(BaseModel):
    """Extended Poisson-derived stats computed at serve-time from λ_home, λ_away."""
    over_1_5:           float
    under_1_5:          float
    over_2_5:           float   # Poisson-derived — used in Goals Lines for internal consistency
    under_2_5:          float
    over_3_5:           float
    under_3_5:          float
    home_over_1_5:      float   # P(home team scores 2+)
    home_under_1_5:     float
    away_over_1_5:      float   # P(away team scores 2+)
    away_under_1_5:     float
    top_scores:         List[CorrectScoreProb]
    most_likely_score:  Optional[str] = None
    btts_and_over_2_5:  float
    btts_and_under_2_5: float
    home_win_and_btts:  float   # home wins AND both score
    away_win_and_btts:  float   # away wins AND both score
    home_win_and_ng:    float   # home wins AND only home scores (1-0, 2-0…)
    away_win_and_ng:    float   # away wins AND only away scores (0-1, 0-2…)


class WatchMarket(BaseModel):
    market:     str                       # "GG @ 2.33"
    ev_pct:     float                     # model edge in pp, e.g. 21.2
    market_pct: Optional[float] = None    # de-vigged bookmaker probability


class AnalysisResponse(BaseModel):
    match_id:          int
    home_team:         str
    away_team:         str
    model:             ModelProbs
    bookmakers:        Optional[BookmakerData] = None
    injuries:          Optional[InjuryData]    = None
    analysis:          str
    suggested_market:  Optional[str] = None          # primary pick (backwards compat)
    suggested_markets: List[str]     = []             # ranked list, up to 2
    watch_markets:     List[WatchMarket] = []         # model edge, unproven (shadow-tracked)
    poisson_stats:     Optional[PoissonStats] = None  # extended stats from λ_home/λ_away
    has_odds_data:     bool
    has_injury_data:   bool = False
    odds_movement:     Optional[OddsMovement] = None
