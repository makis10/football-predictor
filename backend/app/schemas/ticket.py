from __future__ import annotations

from datetime import date, time
from typing import List, Optional

from pydantic import BaseModel


class TicketLegOut(BaseModel):
    match_id:     int
    market:       str            # "1X" / "O2.5" / "GG" …
    prob:         float          # our model's probability for this selection
    odds:         float
    estimated:    bool           # True → our fair price, no bookmaker market
    won:          Optional[bool] = None

    league:       str
    home_team:    str
    away_team:    str
    match_date:   date
    kickoff_time: Optional[time] = None
    home_goals:   Optional[int] = None
    away_goals:   Optional[int] = None


class TicketOut(BaseModel):
    id:            int
    profile:       str           # safe / treble / fourfold / fivefold / longshot
    generated_for: date
    horizon_days:  int
    total_odds:    float
    combined_prob: float         # product of leg probabilities
    num_legs:      int
    outcome:       Optional[str] = None   # "won" | "lost" | None (open)
    legs:          List[TicketLegOut] = []


class ProfileRecord(BaseModel):
    """Settled record for one rung of the ladder."""
    profile:  str
    settled:  int
    won:      int
    hit_rate: float          # won / settled, 0–1
    # Return per 1 unit staked across every settled slip of this profile.
    # Plain arithmetic on stored odds — no projection, no EV.
    staked:   float
    returned: float
    roi_pct:  float


class TicketsResponse(BaseModel):
    generated_for: Optional[date] = None
    horizon_days:  Optional[int]  = None
    tickets:       List[TicketOut] = []
    # How many of the five profiles the card could actually fill. Shown so a
    # short list reads as "the card was thin", not "the page is broken".
    profiles_total: int = 0
    profiles_built: int = 0
    record:        List[ProfileRecord] = []
    overall:       Optional[ProfileRecord] = None


class SettledTicketsResponse(BaseModel):
    tickets: List[TicketOut] = []
