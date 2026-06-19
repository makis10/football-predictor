"""
League-strength coefficients — the ONE place where structural football
knowledge is injected into the national model, as auditable DATA (not odds).

WHY THIS EXISTS
---------------
The international Elo is built only on national-team RESULTS, which are
confederation-siloed: CONCACAF/Asian/African sides bank wins vs weak regional
opponents → inflated Elo, while a strong squad with a brutal schedule looks
weak. The market prices the *players on the pitch*; our results-Elo can't see
them. This table lets us transfer "Ghana's players are in the Premier League,
Panama's are not" into the model — using the objective fact of WHICH LEAGUE each
called-up player plays in, weighted by a strength coefficient per league.

EPISTEMICS (read before editing)
---------------------------------
- The coefficients encode aggregated, slow-moving football knowledge (which
  leagues are strong). They are anchored to objective references (UEFA country
  coefficients, transfer-market reality) and are deliberately STATIC + auditable
  — they do NOT rot with any model's knowledge cutoff because league strength
  changes over years, not weeks.
- This is NOT the betting market. It is the sporting reality the market also
  knows. We inject the reality (player → league), never the price.
- It is a PRIOR, not gospel. The match model still blends it with form/H2H, and
  results can override it. Override any value here freely if it looks wrong.

SCALE: 0.0 (amateur) … 1.0 (best league in the world). Used downstream to build
a per-squad strength score and a talent-adjusted Elo delta.
"""
from __future__ import annotations

import re
from typing import Optional

# ── Exact, high-confidence league_id → coefficient ────────────────────────────
# API-Football v3 top-division ids we are sure about. The (country, tier)
# fallback below covers everything else, so this only needs the big ones.
LEAGUE_ID_STRENGTH: dict[int, float] = {
    39:  1.00,   # England — Premier League
    140: 0.97,   # Spain — La Liga
    135: 0.95,   # Italy — Serie A
    78:  0.94,   # Germany — Bundesliga
    61:  0.88,   # France — Ligue 1
    88:  0.80,   # Netherlands — Eredivisie
    94:  0.79,   # Portugal — Primeira Liga
    203: 0.74,   # Turkey — Süper Lig
    144: 0.73,   # Belgium — Jupiler Pro League
    71:  0.72,   # Brazil — Serie A
    128: 0.70,   # Argentina — Liga Profesional
    307: 0.66,   # Saudi Arabia — Pro League
    179: 0.62,   # Scotland — Premiership
    218: 0.62,   # Austria — Bundesliga
    207: 0.62,   # Switzerland — Super League
    197: 0.60,   # Greece — Super League
    253: 0.58,   # USA — MLS
    262: 0.57,   # Mexico — Liga MX
    98:  0.56,   # Japan — J1 League
    119: 0.56,   # Denmark — Superliga
    292: 0.50,   # South Korea — K League 1
    113: 0.52,   # Sweden — Allsvenskan
    103: 0.52,   # Norway — Eliteserien
}

# ── Country top-flight tier (fallback when league_id unknown) ─────────────────
# Coefficient for the FIRST division of each country. Lower divisions / cups get
# downgraded by _division_factor below. Country name as API-Football returns it.
COUNTRY_TOP_FLIGHT: dict[str, float] = {
    "England": 1.00, "Spain": 0.97, "Italy": 0.95, "Germany": 0.94, "France": 0.88,
    "Netherlands": 0.80, "Portugal": 0.79, "Turkey": 0.74, "Belgium": 0.73,
    "Brazil": 0.72, "Argentina": 0.70, "Saudi Arabia": 0.66, "Scotland": 0.62,
    "Austria": 0.62, "Switzerland": 0.62, "Greece": 0.60, "Croatia": 0.60,
    "Ukraine": 0.60, "Russia": 0.62, "Czech-Republic": 0.58, "Czechia": 0.58,
    "Serbia": 0.56, "USA": 0.58, "Mexico": 0.57, "Japan": 0.56, "Denmark": 0.56,
    "Poland": 0.55, "Norway": 0.52, "Sweden": 0.52, "South-Korea": 0.50,
    "South Korea": 0.50, "Romania": 0.50, "Hungary": 0.48, "Qatar": 0.50,
    "United-Arab-Emirates": 0.50, "UAE": 0.50, "Egypt": 0.48, "Morocco": 0.48,
    "Algeria": 0.46, "Tunisia": 0.45, "South-Africa": 0.45, "South Africa": 0.45,
    "Ivory-Coast": 0.44, "Australia": 0.50, "China": 0.50, "Colombia": 0.55,
    "Uruguay": 0.55, "Chile": 0.54, "Paraguay": 0.52, "Ecuador": 0.52, "Peru": 0.50,
    "Iran": 0.46, "Iraq": 0.40, "Uzbekistan": 0.44, "Jordan": 0.38, "Panama": 0.38,
    "Israel": 0.44, "Cyprus": 0.42, "Bulgaria": 0.42, "Finland": 0.40,
    "Ireland": 0.44, "Kazakhstan": 0.38, "Slovakia": 0.46, "Honduras": 0.40,
    "Venezuela": 0.48, "Costa-Rica": 0.42, "Canada": 0.50, "Curacao": 0.35, "Curaçao": 0.35,
    "Cape-Verde": 0.35, "Cape Verde": 0.35, "Haiti": 0.35, "Senegal": 0.44,
    "Ghana": 0.44, "Nigeria": 0.45, "New-Zealand": 0.40, "New Zealand": 0.40,
}

# Strongest fallback when even the country is unknown (amateur / tiny league).
DEFAULT_STRENGTH = 0.35

# Lower divisions / cups relative to their country's top flight.
_SECOND_TIER_RE = re.compile(
    r"\b(2|ii|b|segund|serie\s*b|championship|league\s*one|league\s*two|"
    r"2\.?\s*bundesliga|ligue\s*2|liga\s*2|segunda|smartbank|2nd)\b", re.I
)
_CUP_RE = re.compile(r"\b(cup|copa|coppa|pokal|coupe|trophy|super\s*cup|shield)\b", re.I)


def _division_factor(league_name: str) -> float:
    """Multiplier for non-top divisions / cups (top flight = 1.0)."""
    n = league_name or ""
    if _CUP_RE.search(n):
        return 0.0          # cups carry no league-strength signal; skip them
    if _SECOND_TIER_RE.search(n):
        return 0.62         # second tier ≈ a notch below the top flight
    return 1.0


def league_coef(
    league_id: Optional[int] = None,
    league_name: str = "",
    country: str = "",
) -> Optional[float]:
    """Strength coefficient (0..1) for a league. None for cups (skip in agg).

    Resolution order: exact league_id → (country top-flight × division factor)
    → DEFAULT. Cup competitions return None so callers drop them from the squad
    aggregate (a player's domestic LEAGUE is the talent signal, not cup runs).
    """
    # Continental / international club comps + friendlies (API country "World":
    # Champions League, Libertadores, club friendlies) are not a domestic league
    # — skip them so the player's actual league (picked by minutes) is used.
    if (country or "").strip().lower() == "world":
        return None

    df = _division_factor(league_name)
    if df == 0.0:
        return None  # cup → no signal

    if league_id is not None and league_id in LEAGUE_ID_STRENGTH:
        return round(LEAGUE_ID_STRENGTH[league_id] * df, 4)

    base = COUNTRY_TOP_FLIGHT.get((country or "").strip())
    if base is None:
        # try a normalised key (API sometimes uses dashes)
        base = COUNTRY_TOP_FLIGHT.get((country or "").strip().replace(" ", "-"))
    if base is None:
        return round(DEFAULT_STRENGTH * df, 4)
    return round(base * df, 4)
