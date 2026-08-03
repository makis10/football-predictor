from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel, field_validator

from backend.app.display_names import display_name, display_names


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

    # The stored name is a join key, not a label — see app.display_names. This
    # is a response-only model (nothing is created through MatchBase), so
    # rewriting here cannot leak a display spelling back into the database.
    @field_validator("home_team", "away_team")
    @classmethod
    def _spell_for_the_reader(cls, v: str) -> str:
        return display_name(v) or v


class MatchResponse(MatchBase):
    id: int
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
    result: Optional[str] = None
    created_at: datetime
    prediction: Optional[PredictionEmbed] = None
    # Which side(s) we hold no history for. Populated only when the prediction
    # is flagged insufficient_data, so the card can say WHICH club is missing
    # instead of calling a PAOK or Benfica tie "unknown teams".
    unknown_teams: list[str] = []

    @field_validator("unknown_teams")
    @classmethod
    def _spell_unknowns_for_the_reader(cls, v: list[str]) -> list[str]:
        return display_names(v)

    model_config = {"from_attributes": True}
