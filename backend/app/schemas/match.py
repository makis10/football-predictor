from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel


class PredictionEmbed(BaseModel):
    """Flat prediction data embedded inside a MatchResponse."""

    home_win_prob: float
    draw_prob: float
    away_win_prob: float
    over_2_5_prob: float
    goals_prediction: str  # "OVER" / "UNDER"
    model_version: str
    confidence: str  # "high" / "medium" / "low"
    suggested_market: Optional[str] = None
    ev_score: Optional[float] = None
    insufficient_data: bool = False   # both teams unknown → not a real prediction

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class MatchBase(BaseModel):
    league: str
    season: str
    match_date: date
    kickoff_time: Optional[time] = None  # UTC scheduled kick-off; NULL if unknown
    home_team: str
    away_team: str
    round: Optional[str] = None           # e.g. "1st Qualifying Round" (European ties only)


class MatchResponse(MatchBase):
    id: int
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
    result: Optional[str] = None
    created_at: datetime
    prediction: Optional[PredictionEmbed] = None

    model_config = {"from_attributes": True}
