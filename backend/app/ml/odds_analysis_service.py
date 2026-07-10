"""
Odds Analysis Service
=====================
Fetches live bookmaker odds from The Odds API, compares them with the ML
model's probabilities, fetches injury/suspension data from API-Football,
and generates a Groq (Llama-3.3-70B) analysis.

Dependencies:
  pip install groq  (already in requirements.txt)
  ODDS_API_KEY  → free tier at the-odds-api.com  (500 req/month)
  GROQ_API_KEY  → free tier at console.groq.com
  API_SPORTS_KEY → api-football.com (api-sports.io) — for injuries

Flow:
  run_comparison()
    ├── fetch_bookmaker_odds()   → The Odds API
    │     └── _parse_game_odds() → fair probabilities (vig removed)
    ├── fetch_injuries()         → API-Football (injuries + suspensions)
    └── _get_llm_analysis()      → Groq Llama-3.3-70B
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

from backend.app.cache import CACHE_MISS, cache_get, cache_set

log = logging.getLogger("odds")

ODDS_API_KEY   = os.getenv("ODDS_API_KEY", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY", "")  # api-football.com

# llama-3.3-70b-versatile is deprecated on GroqCloud (decommission 2026-08-16).
# Default to its recommended replacement; override with the GROQ_MODEL env var
# (e.g. "qwen/qwen3.6-27b" for a faster/cheaper option). Verify availability at
# GET https://api.groq.com/openai/v1/models.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# ── League → The Odds API sport key ──────────────────────────────────────────
LEAGUE_SPORT_KEY: dict[str, str] = {
    "EPL":          "soccer_epl",
    "Championship": "soccer_england_championship",
    "LeagueOne":    "soccer_england_league1",
    "LaLiga":       "soccer_spain_la_liga",
    "SerieA":       "soccer_italy_serie_a",
    "Bundesliga":   "soccer_germany_bundesliga",
    "Ligue1":       "soccer_france_ligue_one",
    "GreekSL":      "soccer_greece_super_league",
    "PrimeiraLiga": "soccer_portugal_primeira_liga",
    "Eredivisie":   "soccer_netherlands_eredivisie",
    "EL":           "soccer_uefa_europa_league",
    "ECL":          "soccer_uefa_europa_conference_league",
    "CL":           "soccer_uefa_champs_league",
}

# ── National tournament → The Odds API sport key (substring match) ────────────
# Keys verified against the live /v4/sports list. Order matters: the more
# specific "qualification" entries must precede the tournament-proper ones so a
# "FIFA World Cup qualification" tournament doesn't match the "world cup" rule.
_NATIONAL_TOURNAMENT_KEYS: list[tuple[list[str], str]] = [
    (["world cup qualification", "world cup qualifier"], "soccer_fifa_world_cup_qualifiers_europe"),
    (["euro qualification", "euro qualifier"],  "soccer_uefa_euro_qualification"),
    (["world cup"],                             "soccer_fifa_world_cup"),
    (["european championship", "uefa euro"],    "soccer_uefa_european_championship"),
    (["nations league", "nations cup"],         "soccer_uefa_nations_league"),
    (["copa america", "copa américa"],          "soccer_conmebol_copa_america"),
    (["africa cup", "afcon", "can 20"],         "soccer_africa_cup_of_nations"),
    (["asian cup", "afc championship"],         "soccer_afc_asian_cup"),
    (["gold cup"],                              "soccer_concacaf_gold_cup"),
    (["concacaf nations"],                      "soccer_concacaf_nations_league"),
    # NOTE: The Odds API has no international-friendlies key, so friendlies get
    # no bookmaker odds — this maps to nothing and returns None.
]


def get_national_sport_key(tournament: str) -> Optional[str]:
    """Map a tournament name (from DB) to an Odds API sport key via substring match."""
    t = tournament.lower()
    for keywords, sport_key in _NATIONAL_TOURNAMENT_KEYS:
        if any(kw in t for kw in keywords):
            return sport_key
    return None


def _fetch_national_games_cached(sport_key: str) -> list:
    """
    Same as _fetch_league_games_cached but keyed by sport_key directly.
    Used for national team tournaments where we have no league code.
    """
    if not ODDS_API_KEY or not sport_key:
        return []

    cache_key = f"league_odds:national:{sport_key}"
    cached = cache_get(cache_key)
    if cached is not CACHE_MISS:
        return cached

    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/",
            params={
                "apiKey":     ODDS_API_KEY,
                "regions":    "eu",
                "markets":    "h2h,totals",
                "dateFormat": "iso",
                "oddsFormat": "decimal",
            },
            timeout=10,
        )
        resp.raise_for_status()
        games = resp.json()
        if not isinstance(games, list):
            games = []
        remaining = resp.headers.get("x-requests-remaining", "?")
        log.info(f"[odds] Fetched {len(games)} games for {sport_key}  (quota remaining: {remaining})")
    except Exception as e:
        log.warning(f"[odds] National fetch failed for {sport_key}: {e}")
        games = []

    cache_set(cache_key, games, LEAGUE_ODDS_TTL)
    return games


def fetch_bookmaker_odds_national(
    home_team: str,
    away_team: str,
    sport_key: str,
) -> Optional[dict]:
    """
    Like fetch_bookmaker_odds() but uses sport_key directly (for national matches).

    Also matches fixtures whose home/away designation is REVERSED vs our data
    (FIFA's administrative bracket position can differ from the dataset's
    orientation — observed in 3 WC-2026 group games). In that case home/away
    odds are swapped so they describe OUR orientation.
    """
    games = _fetch_national_games_cached(sport_key)

    def _enrich(parsed: dict, game: dict) -> dict:
        parsed["commence_time"] = game.get("commence_time")   # UTC ISO string
        event_id = game.get("id", "")
        if event_id:
            btts = _fetch_event_btts(event_id, sport_key)
            if btts:
                parsed["fair_probs"]["btts_yes"] = btts.get("fair_btts_yes")
                parsed["fair_probs"]["btts_no"]  = btts.get("fair_btts_no")
                if btts.get("raw_btts_yes"):
                    parsed["raw_odds"]["btts_yes"] = btts["raw_btts_yes"]
                if btts.get("raw_btts_no"):
                    parsed["raw_odds"]["btts_no"] = btts["raw_btts_no"]
        return parsed

    for game in games:
        if _teams_match(game.get("home_team", ""), home_team) and \
           _teams_match(game.get("away_team", ""), away_team):
            return _enrich(_parse_game_odds(game), game)

    # Reversed orientation fallback
    for game in games:
        if _teams_match(game.get("home_team", ""), away_team) and \
           _teams_match(game.get("away_team", ""), home_team):
            parsed = _parse_game_odds(game)
            for d in (parsed.get("fair_probs", {}), parsed.get("raw_odds", {})):
                d["home_win"], d["away_win"] = d.get("away_win"), d.get("home_win")
            return _enrich(parsed, game)
    return None


def run_national_comparison(
    prediction_id: int,
    home_team: str,
    away_team: str,
    tournament: str,
    model_probs: dict,
    match_date=None,
) -> dict:
    """
    Entry point for national team match analysis.
    Like run_comparison() but uses tournament name → sport key lookup
    and skips injury fetching (not available for national teams via API-Football).
    """
    probs_fp = (
        round(model_probs.get("home_win", 0), 3),
        round(model_probs.get("draw",     0), 3),
        round(model_probs.get("away_win", 0), 3),
        round(model_probs.get("over_2_5", 0), 3),
    )
    redis_key = (
        f"national_analysis:{prediction_id}:"
        f"{probs_fp[0]}:{probs_fp[1]}:{probs_fp[2]}:{probs_fp[3]}"
    )
    cached = cache_get(redis_key)
    if cached is not CACHE_MISS:
        return cached

    sport_key = get_national_sport_key(tournament)
    bm_data = fetch_bookmaker_odds_national(home_team, away_team, sport_key) if sport_key else None

    # A BTTS prob within epsilon of the 0.50 fallback carries no real signal —
    # drop it so a fake "GG @ high-odds" EV isn't computed or shown.
    model_probs = _strip_default_btts(model_probs)

    ev         = _compute_ev(model_probs, bm_data)
    raw_odds   = (bm_data or {}).get("raw_odds", {})
    fair_probs = (bm_data or {}).get("fair_probs", {})

    # Dynamic, data-driven suggestable set for the national path (see
    # proven_markets). Markets that qualify but aren't proven yet are surfaced as
    # "watch" instead of being silently hidden — so e.g. a real GG edge is shown
    # and shadow-tracked, but never headlined until the new model's record earns it.
    try:
        from backend.app.database import SessionLocal
        _db = SessionLocal()
        try:
            proven = proven_markets(_db, "national")
        finally:
            _db.close()
    except Exception:
        proven = set(BASE_SUGGESTABLE)

    ev_markets = _top_ev_markets(ev, raw_odds, fair_probs=fair_probs,
                                 model_probs=model_probs, n=2, suggestable=proven)
    watch_markets = _watch_markets(ev, raw_odds, fair_probs=fair_probs,
                                   model_probs=model_probs, n=3, suggestable=proven)
    ev_best    = ev_markets[0] if ev_markets else None

    analysis = _get_llm_analysis(
        home_team, away_team, tournament, model_probs, bm_data,
        injury_data=None, watch_markets=watch_markets,
    )

    # Proven markets are the canonical suggestion; watch markets are shown
    # separately as unproven (data-collection), never as the headline pick.
    suggested = ev_best
    suggested_markets = ev_markets

    result = {
        "prediction_id":    prediction_id,
        "home_team":        home_team,
        "away_team":        away_team,
        "model":            model_probs,
        "bookmakers":       bm_data,
        "injuries":         None,
        "analysis":         analysis["text"],
        "suggested_market": suggested,
        "suggested_markets": suggested_markets,
        "watch_markets":     watch_markets,
        "has_odds_data":    bm_data is not None,
        "has_injury_data":  False,
    }

    cache_set(redis_key, result, CACHE_TTL)
    return result

# ── API-Football (api-sports.io) — injuries & suspensions ────────────────────

# League ID on api-football.com
_LEAGUE_API_SPORTS_ID: dict[str, int] = {
    "EPL":          39,
    "Championship": 40,
    "LeagueOne":    41,
    "LaLiga":       140,
    "SerieA":       135,
    "Bundesliga":   78,
    "Ligue1":       61,
    "GreekSL":      197,
    "PrimeiraLiga": 94,
    "Eredivisie":   88,
    "CL":           2,
    "EL":           3,
    "ECL":          848,
}

# Current season year (start year of the season, e.g. 2025 for 2025/26)
def _current_season(match_date: Optional[str] = None) -> int:
    """Return the season start year for a given date (or today)."""
    import datetime
    if match_date:
        try:
            d = datetime.date.fromisoformat(str(match_date))
        except Exception:
            d = datetime.date.today()
    else:
        d = datetime.date.today()
    # Season starts in July/August — if month < 7 we're in the second half
    return d.year if d.month >= 7 else d.year - 1


def _fetch_squad_positions(team_id: int) -> dict[int, str]:
    """
    Return {player_id: position} for an entire squad.
    Uses /players/squads?team={id} — cached 24 h in Redis.
    Position values from API: "Goalkeeper", "Defender", "Midfielder", "Attacker".
    """
    cache_key = f"squad_positions:{team_id}"
    cached = cache_get(cache_key)
    if cached is not CACHE_MISS:
        return cached or {}

    try:
        resp = requests.get(
            "https://v3.football.api-sports.io/players/squads",
            headers={"x-apisports-key": API_SPORTS_KEY},
            params={"team": team_id},
            timeout=8,
        )
        resp.raise_for_status()
        response = resp.json().get("response", [])
        # Store as str keys so JSON round-trip through Redis preserves lookups.
        positions: dict[str, str] = {}
        for squad in response:
            for p in squad.get("players", []):
                pid = p.get("id")
                pos = p.get("position", "")
                if pid and pos:
                    positions[str(pid)] = pos
        cache_set(cache_key, positions, 24 * 3600)
        log.info(f"[injuries] Squad positions fetched for team {team_id}: {len(positions)} players")
        return positions
    except Exception as e:
        log.warning(f"[injuries] Squad fetch failed for team {team_id}: {e}")
        cache_set(cache_key, {}, 24 * 3600)
        return {}


def fetch_injuries(
    home_team: str,
    away_team: str,
    league: str,
    match_date,
) -> Optional[dict]:
    """
    Fetch injury and suspension data from API-Football for both teams.

    Returns a dict:
      {
        "home": [{"name": str, "type": str, "reason": str, "position": str|None}, ...],
        "away": [...],
      }
    or None if API key missing / league not supported / request fails.

    Position is enriched from /players/squads (cached 24 h) so that
    adjust_probabilities can apply position-aware goal impact.
    """
    if not API_SPORTS_KEY:
        return None

    league_id = _LEAGUE_API_SPORTS_ID.get(league)
    if not league_id:
        return None

    season = _current_season(match_date)
    date_str = str(match_date)[:10] if match_date else ""

    try:
        resp = requests.get(
            "https://v3.football.api-sports.io/injuries",
            headers={"x-apisports-key": API_SPORTS_KEY},
            params={
                "league":  league_id,
                "season":  season,
                "date":    date_str,
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json().get("response", [])
    except Exception as e:
        log.warning(f"[injuries] API request failed: {e}")
        return None

    # Collect team IDs from response so we can fetch squad positions in one
    # extra call per team (cached 24 h — positions don't change mid-season).
    home_team_id: Optional[int] = None
    away_team_id: Optional[int] = None
    for entry in data:
        t = entry.get("team", {})
        t_name = t.get("name", "")
        t_id   = t.get("id")
        if t_id:
            if _teams_match(t_name, home_team):
                home_team_id = t_id
            elif _teams_match(t_name, away_team):
                away_team_id = t_id

    # Fetch positions for both teams (each cached 24 h, so typically a Redis hit)
    home_positions: dict[int, str] = (
        _fetch_squad_positions(home_team_id) if home_team_id else {}
    )
    away_positions: dict[int, str] = (
        _fetch_squad_positions(away_team_id) if away_team_id else {}
    )

    home_injuries: list[dict] = []
    away_injuries: list[dict] = []
    # Track seen players per team to deduplicate — API-Football sometimes
    # returns the same player twice (multiple injury records, one per fixture).
    home_seen: set[str] = set()
    away_seen: set[str] = set()

    for entry in data:
        team_name  = entry.get("team", {}).get("name", "")
        player     = entry.get("player", {})
        # API-Football nests type inside player; reason can also signal suspension
        raw_type   = player.get("type", "")         # e.g. "Missing Fixture"
        reason     = player.get("reason", "")       # e.g. "Muscle Injury" / "Yellow Cards"
        name       = player.get("name", "Unknown")
        player_id  = player.get("id")

        # Normalise to our three categories
        reason_lc = reason.lower()
        if "card" in reason_lc or "suspension" in reason_lc or "ban" in reason_lc:
            inj_type = "Suspended"
        elif "doubt" in reason_lc or "question" in reason_lc or "50%" in reason_lc:
            inj_type = "Questionable"
        else:
            inj_type = "Injured"

        if _teams_match(team_name, home_team):
            if name not in home_seen:
                home_seen.add(name)
                position = home_positions.get(str(player_id)) if player_id else None
                home_injuries.append({"name": name, "type": inj_type,
                                      "reason": reason, "position": position})
        elif _teams_match(team_name, away_team):
            if name not in away_seen:
                away_seen.add(name)
                position = away_positions.get(str(player_id)) if player_id else None
                away_injuries.append({"name": name, "type": inj_type,
                                      "reason": reason, "position": position})

    if not home_injuries and not away_injuries:
        return None

    return {"home": home_injuries, "away": away_injuries}


def _get_fixture_id(
    home_team: str,
    away_team: str,
    league: str,
    match_date,
) -> Optional[int]:
    """
    Look up the API-Football fixture ID for a specific match.
    Cached 24 h in Redis — fixture IDs never change after the match.
    """
    if not API_SPORTS_KEY:
        return None
    league_id = _LEAGUE_API_SPORTS_ID.get(league)
    if not league_id:
        return None

    date_str = str(match_date)[:10]
    season   = _current_season(match_date)

    # Cache the entire fixtures list for the league+date so multiple postmortems
    # on the same day only cost 1 API credit.
    fixtures_key = f"api_fixtures:{league}:{date_str}"
    cached_fixtures = cache_get(fixtures_key)
    if cached_fixtures is CACHE_MISS:
        try:
            resp = requests.get(
                "https://v3.football.api-sports.io/fixtures",
                headers={"x-apisports-key": API_SPORTS_KEY},
                params={"league": league_id, "season": season, "date": date_str},
                timeout=8,
            )
            resp.raise_for_status()
            cached_fixtures = resp.json().get("response", [])
            remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
            log.info(f"[events] Fetched {len(cached_fixtures)} fixtures for {league} {date_str} (remaining: {remaining})")
        except Exception as exc:
            log.warning(f"[events] Fixture lookup failed: {exc}")
            return None
        cache_set(fixtures_key, cached_fixtures, 24 * 3600)

    for fixture in cached_fixtures:
        fix_home = fixture.get("teams", {}).get("home", {}).get("name", "")
        fix_away = fixture.get("teams", {}).get("away", {}).get("name", "")
        if _teams_match(fix_home, home_team) and _teams_match(fix_away, away_team):
            return fixture.get("fixture", {}).get("id")
    return None


def fetch_match_events(
    home_team: str,
    away_team: str,
    league: str,
    match_date,
) -> Optional[str]:
    """
    Fetch key match events (goals, cards, penalties) from API-Football and
    return them as a formatted text block for inclusion in the postmortem prompt.

    Returns None if API key missing, league not supported, or events unavailable.
    Cached 24 h in Redis.
    """
    fixture_id = _get_fixture_id(home_team, away_team, league, match_date)
    if not fixture_id:
        return None

    events_key = f"match_events:{fixture_id}"
    cached = cache_get(events_key)
    if cached is not CACHE_MISS:
        return cached  # pre-formatted string or None

    try:
        resp = requests.get(
            "https://v3.football.api-sports.io/fixtures/events",
            headers={"x-apisports-key": API_SPORTS_KEY},
            params={"fixture": fixture_id},
            timeout=8,
        )
        resp.raise_for_status()
        raw_events = resp.json().get("response", [])
        remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
        log.info(f"[events] {len(raw_events)} events for fixture {fixture_id} (remaining: {remaining})")
    except Exception as exc:
        log.warning(f"[events] Events fetch failed for fixture {fixture_id}: {exc}")
        cache_set(events_key, None, 24 * 3600)
        return None

    lines: list[str] = []
    for ev in raw_events:
        minute  = ev.get("time", {}).get("elapsed", "?")
        extra   = ev.get("time", {}).get("extra")
        ev_type = ev.get("type", "")
        detail  = ev.get("detail", "")
        team    = ev.get("team", {}).get("name", "")
        player  = ev.get("player", {}).get("name", "")
        assist  = ev.get("assist", {}).get("name")

        min_str = f"{minute}+{extra}'" if extra else f"{minute}'"

        if ev_type == "Goal":
            if detail == "Own Goal":
                lines.append(f"⚽ {min_str} OWN GOAL — {player} ({team})")
            elif detail == "Missed Penalty":
                lines.append(f"❌ {min_str} MISSED PENALTY — {player} ({team})")
            elif detail == "Penalty":
                assist_str = f", assist: {assist}" if assist else ""
                lines.append(f"⚽ {min_str} PENALTY GOAL — {player} ({team}{assist_str})")
            else:
                assist_str = f", assist: {assist}" if assist else ""
                lines.append(f"⚽ {min_str} GOAL — {player} ({team}{assist_str})")
        elif ev_type == "Card":
            icon = "🟥" if "Red" in detail else "🟨"
            lines.append(f"{icon} {min_str} {detail.upper()} — {player} ({team})")
        elif ev_type == "Var":
            lines.append(f"📺 {min_str} VAR: {detail} — {team}")

    text = "\n".join(lines) if lines else None
    cache_set(events_key, text, 24 * 3600)
    return text


def _format_injuries(injury_data: Optional[dict], home_team: str, away_team: str) -> str:
    """Format injury data into a concise text block for the Claude prompt."""
    if not injury_data:
        return "No injury/suspension data available."

    lines = []
    for side, team_name in [("home", home_team), ("away", away_team)]:
        players = injury_data.get(side, [])
        if not players:
            lines.append(f"  {team_name}: No reported injuries or suspensions.")
        else:
            suspended = [p for p in players if p["type"] == "Suspended"]
            injured   = [p for p in players if p["type"] == "Injured"]
            quest     = [p for p in players if p["type"] == "Questionable"]
            unknown   = [p for p in players if p["type"] not in ("Suspended", "Injured", "Questionable")]

            parts = []
            if suspended:
                parts.append("Suspended: " + ", ".join(p["name"] for p in suspended))
            if injured:
                names = [f"{p['name']} ({p['reason']})" if p["reason"] else p["name"]
                         for p in injured]
                parts.append("Injured: " + ", ".join(names))
            if quest:
                parts.append("Questionable: " + ", ".join(p["name"] for p in quest))
            if unknown:
                parts.append("Unavailable: " + ", ".join(p["name"] for p in unknown))

            if parts:
                lines.append(f"  {team_name}: {' | '.join(parts)}")
            else:
                lines.append(f"  {team_name}: No reported injuries or suspensions.")

    return "\n".join(lines)


# TTLs (seconds) — Redis handles expiry natively, no timestamp bookkeeping needed.
#
# The analysis TTL also sets how often scripts/warmup_analysis.py has to pay for
# a Groq call: the warm-up re-primes each entry once per expiry, so the daily
# LLM spend is (86400 / CACHE_TTL) × upcoming_fixtures. At 30 min that was ~800
# calls/day for ~17 fixtures; 1 h halves it. The cost of the longer TTL is odds
# freshness inside the analysis panel (≤ 1 h stale), and the bookmaker odds it
# quotes were never fresher than LEAGUE_ODDS_TTL anyway.
CACHE_TTL      = int(os.getenv("ANALYSIS_CACHE_TTL", "3600"))  # 1 h — Groq analysis
LEAGUE_ODDS_TTL = 1800  # 30 min — league odds batch

# Don't suggest a market when bookmakers price it below this probability.
# At <10% implied probability (~10.00 odds) the model almost certainly lacks
# context (squad quality, rotation, two-legged tie, etc.) that sharps have.
MIN_BM_PROB = 0.10

# Minimum MODEL probability for a market to be suggested.
# A value bet must not only have positive EV but also a meaningful chance of
# occurring. Without this, the model can suggest a Draw with 27% probability
# just because bookmaker odds are high — which is rarely actionable.
#
#   MIN_MODEL_PROB_1X2 — for Home Win / Draw / Away Win.
#     Draw is historically ~25-28%; we require the model gives it ≥25% before
#     treating it as a realistic outcome worth suggesting.
#     Home / Away Win require ≥28% — below that they are clear underdogs and
#     the model likely lacks edge over sharp money.
#
#   MIN_MODEL_PROB_GOALS — for Over 2.5 / Under 2.5 / GG / NG.
#     Goals markets are more symmetric; allow suggestion at ≥35%.
MIN_MODEL_PROB_1X2   = 0.25   # 25% minimum model probability for 1x2 markets
MIN_MODEL_PROB_GOALS = 0.35   # 35% minimum model probability for goals markets

# Two-tier EV thresholds:
#
#   MIN_EV_FAVORITE   – required edge when the suggested market IS the model's
#                       top-probability outcome (e.g. "Home Win" when we give the
#                       home side 60%+).  Kept high because this is the "obvious"
#                       pick; bookmakers rarely misprice clear favourites enough to
#                       offer real value, so we need a meaningful edge to signal it.
#
#   MIN_EV_ALT        – required edge when the suggestion is an ALTERNATIVE market.
#                       Raised from 3% to 5% to compensate for the known tendency
#                       of our model to overestimate draw probability (class-balanced
#                       training inflates draw probabilities vs market-implied).
MIN_EV_FAVORITE = 0.05   # 5 % — for suggesting the model's own top pick
MIN_EV_ALT      = 0.05   # 5 % — raised from 3% to reduce spurious draw suggestions

# ── Pure-model value gate ─────────────────────────────────────────────────────
# 2026-06-17 directive: predictions are now 100% market-independent — bookmaker
# odds are NOT model features and NOT a serve-time anchor. The value gate is the
# ONE place the market is allowed, purely as the thing we compare against:
#   EV = P_model · decimal_odds − 1
# i.e. "where our independent model disagrees with the sharp price". This is the
# whole point — a genuine edge can only come from disagreement.
#
# The old anti-selection finding (suggestions −14.4% ROI) was an artefact of the
# previous design: the model HAD the de-vig fair probs as its #1/#2 features, so
# model−market disagreement was mostly noise. With the market fully removed from
# the model, that no longer holds, so the market-shrinkage safeguard is disabled
# (SHRINKAGE=0 → p′ = pure model prob). Re-measure ROI on the retrained model
# before deciding whether any shrinkage should come back.
MARKET_SHRINKAGE = 0.0

# Fix 2 — kill-switch: per-market tracked ROI of suggested bets was
#   Draw +36.6%, Home Win +15.1%  vs  NG −15.5%, Over −24.3%,
#   Away Win −28.9%, GG −32.8%.
# Only the profitable markets stay suggestable; re-enable others only after a
# positive rolling-90-day record.
SUGGESTABLE_MARKETS = {"Home Win", "Draw"}

# ── Dynamic, data-driven suggestable set (national) ──────────────────────────
# The static set above was calibrated on the OLD (pre-2026-06-17, market-anchored)
# model — and once a market was excluded it never got tracked, so the exclusion
# could never be re-evaluated (self-fulfilling). Instead, for the national path
# we now SHADOW-TRACK every market that clears the EV/sanity filters and let the
# NEW model's own settled record decide what becomes a headline suggestion:
#
#   proven_markets = BASE_SUGGESTABLE ∪ {market : post-cutoff settled n ≥ MIN
#                                                 and ROI ≥ FLOOR}
#
# A qualifying market that isn't proven yet is surfaced as "watch" (unproven) —
# shown and recorded, but never staked with conviction until the data backs it.
#
# Base markets are NOT exempt forever: they start trusted (old-model record) but
# are DEMOTED to watch once the new model's own record says they lose —
# early (n ≥ DEMOTE_MIN_SAMPLES) only for clear bleeders (ROI ≤ DEMOTE_ROI_CEIL),
# and at full sample size (n ≥ PROVEN_MIN_SAMPLES) by the same ROI floor as
# everyone else. Stateless: a demoted market re-enters as soon as its cumulative
# post-cutoff record no longer trips the rule.
BASE_SUGGESTABLE   = {"Home Win", "Draw"}
NEW_MODEL_CUTOFF   = "2026-06-17"   # market-independent retrain — see methodology
PROVEN_MIN_SAMPLES = 30             # settled tickets before a market can promote
PROVEN_ROI_FLOOR   = 0.0            # must at least break even on the new model
DEMOTE_MIN_SAMPLES = 15             # settled tickets before a base market can demote early
DEMOTE_ROI_CEIL    = -0.20          # early demotion only for clear bleeders, not noise
_PROVEN_TTL        = 1800           # 30 min cache


def _market_won(market: str, res: Optional[str], hg, ag) -> Optional[bool]:
    """Did a single-market ticket win, given the actual result + goals?"""
    if res is None and (hg is None or ag is None):
        return None
    total = (hg or 0) + (ag or 0)
    return {
        "Home Win":  res == "H",
        "Draw":      res == "D",
        "Away Win":  res == "A",
        "Over 2.5":  total > 2.5,
        "Under 2.5": total < 2.5,
        "GG":        (hg or 0) > 0 and (ag or 0) > 0,
        "NG":        not ((hg or 0) > 0 and (ag or 0) > 0),
    }.get(market)


def _market_is_proven(market: str, n: int, roi: Optional[float]) -> bool:
    """The single promotion/demotion rule — shared by the live gate and the
    admin market-record endpoint so they can never disagree.

    Non-base markets promote at n ≥ PROVEN_MIN_SAMPLES with ROI ≥ floor.
    Base markets start proven, demote early only as clear bleeders
    (n ≥ DEMOTE_MIN_SAMPLES, ROI ≤ DEMOTE_ROI_CEIL), and are held to the same
    ROI floor as everyone else once at full sample size."""
    if market in BASE_SUGGESTABLE:
        if roi is None:            # no settled record yet → keep trusted
            return True
        early_bleeder = n >= DEMOTE_MIN_SAMPLES and roi <= DEMOTE_ROI_CEIL
        failed_full   = n >= PROVEN_MIN_SAMPLES and roi < PROVEN_ROI_FLOOR
        return not (early_bleeder or failed_full)
    return n >= PROVEN_MIN_SAMPLES and roi is not None and roi >= PROVEN_ROI_FLOOR


def proven_markets(db, source: str = "national") -> set[str]:
    """Markets allowed as headline suggestions = the base trusted set plus any
    whose NEW-model (post-cutoff) settled record clears the bar — minus any base
    market whose post-cutoff record has demoted it. Cached 30 min.

    Only implemented for the national ledger; other sources keep the static set
    (their gate passes no `suggestable`, so this isn't consulted)."""
    if source != "national":
        return set(BASE_SUGGESTABLE)
    ck = f"proven_markets:{source}"
    cached = cache_get(ck)
    if cached is not CACHE_MISS:
        return set(cached)

    from sqlalchemy import text
    proven = set(BASE_SUGGESTABLE)
    try:
        rows = db.execute(text("""
            SELECT vb.market, vb.odds,
                   np.actual_result, np.actual_home_goals, np.actual_away_goals
            FROM value_bets vb
            JOIN national_predictions np ON np.id = vb.national_prediction_id
            WHERE vb.source = 'national'
              AND vb.created_at >= :cutoff
              AND np.actual_result IS NOT NULL
        """), {"cutoff": NEW_MODEL_CUTOFF}).fetchall()
    except Exception:
        return proven

    agg: dict[str, list] = {}   # market → [n, pnl]
    for market, odds, res, hg, ag in rows:
        won = _market_won(market, res, hg, ag)
        if won is None or not odds:
            continue
        a = agg.setdefault(market, [0, 0.0])
        a[0] += 1
        a[1] += (float(odds) - 1.0) if won else -1.0

    for market, (n, pnl) in agg.items():
        if _market_is_proven(market, n, pnl / n):
            proven.add(market)
        else:
            proven.discard(market)   # demoted base market falls back to watch

    cache_set(ck, list(proven), _PROVEN_TTL)
    return proven


# ── Team name matching ────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    """Lowercase, strip punctuation/spaces for fuzzy comparison.

    Unicode characters are first normalised with NFKD decomposition and the
    combining diacritical marks are dropped (ö→o, ü→u, é→e, etc.) so that
    team names like '1. FC Köln' (API) and 'FC Koln' (our DB) still match.
    """
    import re
    import unicodedata
    # Decompose accented characters then drop the combining marks
    nfkd = unicodedata.normalize("NFKD", name.lower())
    ascii_name = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", ascii_name)


# Common name variants: our DB name → list of possible API name substrings
_ALIASES: dict[str, list[str]] = {
    "Man City":        ["manchestercity", "mancity"],
    "Man United":      ["manchesterunited", "manunited"],
    "Nott'm Forest":   ["nottinghamforest", "nottmforest"],
    "Wolves":          ["wolverhampton"],
    "Spurs":           ["tottenham"],
    "Brighton":        ["brighton"],
    "Newcastle":       ["newcastle"],
    "West Ham":        ["westham"],
    "Ath Bilbao":      ["athleticclub", "athleticbilbao"],
    "Ath Madrid":      ["atleticomadrid", "atletico"],
    "Barça":           ["barcelona", "fcbarcelona"],
    "Bayern Munich":   ["bayernmunchen", "bayernmunich", "fcbayern"],
    "Ein Frankfurt":   ["eintrachtfrankfurt", "eintracht"],
    "B. Dortmund":     ["borussiadortmund", "bvb"],
    "M'gladbach":      ["monchengladbach", "gladbach"],
    "Paris SG":        ["parissaint", "parissg", "psg"],
    "St Pauli":        ["stpauli"],
    "FC Koln":         ["fckoln", "koln", "cologne"],
    "Nantes":          ["fcnantes"],
    "Rennes":          ["staderennais"],
    "Lens":            ["rclens"],
    "Marseille":       ["olympiquedemarseille"],
    "Lyon":            ["olympiquelyonnais"],
    "Monaco":          ["asmonaco"],
    "Inter":           ["internazionale", "intermilan"],
    # Greek Super League — The Odds API uses different names / spellings
    "Larisa":          ["ael"],           # AE Larissa → "AEL" on The Odds API
    "Levadeiakos":     ["levadiakos"],    # spelling: Levad-ei-akos vs Levad-i-akos
    "Volos NFC":       ["volosfc", "volos"],  # API drops the "N" in NFC
    "Napoli":          ["sscnapoli"],
    "Juventus":        ["juventusfc"],
    "Fiorentina":      ["acffiorentina"],
    "Lazio":           ["sslazio"],
    "Roma":            ["asroma"],
    "Atalanta":        ["atalantabc"],
    "Torino":          ["torinofc"],
    "Udinese":         ["udinesecalcio"],
    "Sassuolo":        ["ussassuolo"],
    "Como":            ["como1907"],
    "Parma":           ["parmafc"],
    "Cagliari":        ["cagliaricalcio"],
    "Empoli":          ["empolifc"],
    "Monza":           ["acmonza"],
    # ── National teams — martj42/DB name → The Odds API spelling ──────────────
    "United States":         ["usa", "unitedstates"],
    "Bosnia and Herzegovina":["bosnia"],
    "Ivory Coast":           ["cotedivoire", "ivorycoast"],
    "DR Congo":              ["drcongo", "congodr", "democraticrepublic"],
    "Republic of Ireland":   ["ireland", "republicofireland"],
    "Czech Republic":        ["czechia", "czechrepublic"],
    "South Korea":           ["southkorea", "korearepublic"],
    "North Macedonia":       ["northmacedonia", "macedonia"],
    "Cape Verde":            ["capeverde", "caboverde"],
    "Curacao":               ["curacao"],
    "China PR":              ["china"],
}


def _teams_match(api_name: str, db_name: str) -> bool:
    """Fuzzy match: slug equality OR alias substring check OR difflib ratio."""
    api_slug = _slug(api_name)
    db_slug  = _slug(db_name)

    # Direct slug match
    if api_slug == db_slug:
        return True
    # Substring containment (handles "FC Barcelona" vs "Barcelona", "AS Roma"
    # vs "Roma"). Guard against false positives: only when BOTH slugs are ≥ 4
    # chars, so a stray 1–3 char slug can't match half the league.
    if len(api_slug) >= 4 and len(db_slug) >= 4:
        if api_slug.startswith(db_slug) or db_slug.startswith(api_slug):
            return True
        if db_slug in api_slug or api_slug in db_slug:
            return True
    # Alias table
    for alias_list in _ALIASES.get(db_name, []):
        if alias_list in api_slug or api_slug.startswith(alias_list[:8]):
            return True
    # Difflib fallback — catches near-identical spellings like
    # "Espanyol" vs "Espanol", "Athletico" vs "Atletico", etc.
    from difflib import SequenceMatcher
    if SequenceMatcher(None, api_slug, db_slug).ratio() >= 0.85:
        return True
    return False


# ── Odds API helpers ──────────────────────────────────────────────────────────

def _fetch_league_games_cached(league: str) -> list:
    """
    Fetch the raw list of game dicts from The Odds API for an entire league,
    with a 30-minute in-memory cache.  One call per league per 30 min —
    shared by both fetch_all_league_odds() and fetch_bookmaker_odds() so that
    every match-detail page view does NOT burn a separate API credit.

    Returns [] on error / unsupported league.
    """
    if not ODDS_API_KEY:
        return []
    sport_key = LEAGUE_SPORT_KEY.get(league)
    if not sport_key:
        return []

    cached = cache_get(f"league_odds:{league}")
    if cached is not CACHE_MISS:
        return cached

    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/",
            params={
                "apiKey":     ODDS_API_KEY,
                "regions":    "eu",
                # NOTE: "btts" is an "additional market" on The Odds API and
                # returns 422 on this bulk endpoint. It is fetched separately
                # via _fetch_event_btts() using the event ID from this response.
                "markets":    "h2h,totals",
                "dateFormat": "iso",
                "oddsFormat": "decimal",
            },
            timeout=10,
        )
        resp.raise_for_status()
        games = resp.json()
        if not isinstance(games, list):
            log.warning(f"[odds] Unexpected response for {league}: {games}")
            games = []
        remaining = resp.headers.get("x-requests-remaining", "?")
        log.info(f"[odds] Fetched {len(games)} games for {league}  (quota remaining: {remaining})")
    except Exception as e:
        log.warning(f"[odds] League fetch failed for {league}: {e}")
        games = []

    cache_set(f"league_odds:{league}", games, LEAGUE_ODDS_TTL)
    return games




def _fetch_event_btts(event_id: str, sport_key: str) -> dict:
    """
    Fetch GG/NG (both-teams-to-score) odds for a single event from The Odds API.

    Costs 1 API credit per event per 30 minutes (cached).  Only called when a
    user opens a specific match detail page — not during bulk prediction compute.

    Returns a dict with keys "btts_yes" / "btts_no" (fair probs and raw odds),
    or an empty dict if the market is unavailable / API key missing.
    """
    if not ODDS_API_KEY or not event_id or not sport_key:
        return {}

    cached = cache_get(f"btts:{event_id}")
    if cached is not CACHE_MISS:
        return cached

    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/events/{event_id}/odds/",
            params={
                "apiKey":     ODDS_API_KEY,
                "regions":    "eu",
                "markets":    "btts",
                "dateFormat": "iso",
                "oddsFormat": "decimal",
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        remaining = resp.headers.get("x-requests-remaining", "?")
        log.info(f"[odds] BTTS fetch for event {event_id}  (quota remaining: {remaining})")
    except Exception as e:
        log.warning(f"[odds] BTTS fetch failed for event {event_id}: {e}")
        cache_set(f"btts:{event_id}", {}, LEAGUE_ODDS_TTL)
        return {}

    btts_yes_odds: list[float] = []
    btts_no_odds:  list[float] = []

    for bm in data.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != "btts":
                continue
            for o in market.get("outcomes", []):
                if o.get("name") == "Yes":
                    btts_yes_odds.append(float(o["price"]))
                elif o.get("name") == "No":
                    btts_no_odds.append(float(o["price"]))

    def _avg(lst: list) -> Optional[float]:
        return sum(lst) / len(lst) if lst else None

    avg_yes = _avg(btts_yes_odds)
    avg_no  = _avg(btts_no_odds)

    result: dict = {}
    if avg_yes and avg_no:
        p_yes = 1.0 / avg_yes
        p_no  = 1.0 / avg_no
        total = p_yes + p_no
        result["fair_btts_yes"] = round(p_yes / total, 4)
        result["fair_btts_no"]  = round(p_no  / total, 4)
        result["raw_btts_yes"]  = round(avg_yes, 2)
        result["raw_btts_no"]   = round(avg_no,  2)
    elif avg_yes:
        result["raw_btts_yes"] = round(avg_yes, 2)
    elif avg_no:
        result["raw_btts_no"] = round(avg_no, 2)

    cache_set(f"btts:{event_id}", result, LEAGUE_ODDS_TTL)
    return result


def fetch_all_league_odds(league: str) -> list:
    """
    Fetch odds for ALL upcoming matches in a league with ONE API call.

    Returns a list of dicts, each with:
        {
          "api_home": str,   # team name as The Odds API returns it
          "api_away": str,
          "fair_probs": {"home_win": float|None, "draw": ..., "away_win": ...,
                         "over_2_5": float|None, "under_2_5": float|None,
                         "btts_yes": float|None, "btts_no": float|None},
          "raw_odds":  {"home_win": ..., "draw": ..., "away_win": ...,
                        "over_2_5": ..., "btts_yes": ..., "btts_no": ...},
        }

    Used by compute_predictions.py to inject live bookmaker odds into the
    feature vector for upcoming matches — the two most important ML features.
    BTTS is fetched via a per-event call (cached 30min) since the bulk endpoint
    does not support the btts market.
    Returns [] if API key missing, league unsupported, or request fails.
    """
    sport_key = LEAGUE_SPORT_KEY.get(league, "")
    games = _fetch_league_games_cached(league)
    results = []
    for game in games:
        parsed = _parse_game_odds(game)
        fp = parsed.get("fair_probs", {})
        ro = parsed.get("raw_odds", {})

        # Fetch BTTS per-event (cached 30min — same cache as analysis page)
        event_id = game.get("id", "")
        if event_id and sport_key:
            btts = _fetch_event_btts(event_id, sport_key)
            if btts:
                fp["btts_yes"] = btts.get("fair_btts_yes")
                fp["btts_no"]  = btts.get("fair_btts_no")
                if btts.get("raw_btts_yes"):
                    ro["btts_yes"] = btts["raw_btts_yes"]
                if btts.get("raw_btts_no"):
                    ro["btts_no"] = btts["raw_btts_no"]

        results.append({
            "api_home":   game.get("home_team", ""),
            "api_away":   game.get("away_team", ""),
            "fair_probs": fp,
            "raw_odds":   ro,
        })
    return results


def fetch_bookmaker_odds(
    home_team: str,
    away_team: str,
    league: str,
) -> Optional[dict]:
    """
    Return parsed odds for a single match, looked up from the league-level
    cache.  Costs 0 extra credits for 1×2 / totals (already cached league-wide).
    Makes 1 additional credit call for BTTS via the per-event endpoint —
    cached 30 min, so repeated page views are free.
    """
    sport_key = LEAGUE_SPORT_KEY.get(league, "")
    games = _fetch_league_games_cached(league)
    for game in games:
        if _teams_match(game.get("home_team", ""), home_team) and \
           _teams_match(game.get("away_team", ""), away_team):
            parsed = _parse_game_odds(game)

            # Fetch BTTS separately (additional market, per-event endpoint)
            event_id = game.get("id", "")
            if event_id and sport_key:
                btts = _fetch_event_btts(event_id, sport_key)
                if btts:
                    # Merge into fair_probs and raw_odds
                    parsed["fair_probs"]["btts_yes"] = btts.get("fair_btts_yes")
                    parsed["fair_probs"]["btts_no"]  = btts.get("fair_btts_no")
                    if btts.get("raw_btts_yes"):
                        parsed["raw_odds"]["btts_yes"] = btts["raw_btts_yes"]
                    if btts.get("raw_btts_no"):
                        parsed["raw_odds"]["btts_no"] = btts["raw_btts_no"]

            return parsed
    return None


def _parse_game_odds(game: dict) -> dict:
    """
    Aggregate odds across all bookmakers, remove margin (vig), and return
    fair probabilities + raw average decimal odds.
    Markets fetched: h2h (1×2), totals (over/under 2.5), btts (GG/NG).
    """
    h2h_home, h2h_draw, h2h_away = [], [], []
    over25, under25 = [], []
    btts_yes, btts_no = [], []
    bookmaker_names: list[str] = []

    api_home = game["home_team"]
    api_away = game["away_team"]

    for bm in game.get("bookmakers", []):
        bookmaker_names.append(bm["title"])
        for market in bm.get("markets", []):
            outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}

            if market["key"] == "h2h":
                if api_home in outcomes and api_away in outcomes:
                    h2h_home.append(outcomes[api_home])
                    h2h_away.append(outcomes[api_away])
                    if "Draw" in outcomes:
                        h2h_draw.append(outcomes["Draw"])

            elif market["key"] == "totals":
                for o in market.get("outcomes", []):
                    if o.get("point") == 2.5:
                        if o["name"] == "Over":
                            over25.append(o["price"])
                        elif o["name"] == "Under":
                            under25.append(o["price"])

            elif market["key"] == "btts":
                for o in market.get("outcomes", []):
                    if o["name"] == "Yes":
                        btts_yes.append(o["price"])
                    elif o["name"] == "No":
                        btts_no.append(o["price"])

    def _avg(lst: list) -> Optional[float]:
        return sum(lst) / len(lst) if lst else None

    def _prob(odd: Optional[float]) -> Optional[float]:
        return (1.0 / odd) if odd else None

    avg_h, avg_d, avg_a = _avg(h2h_home), _avg(h2h_draw), _avg(h2h_away)
    avg_o, avg_u         = _avg(over25),   _avg(under25)

    h_p, d_p, a_p = _prob(avg_h), _prob(avg_d), _prob(avg_a)
    o_p, u_p       = _prob(avg_o), _prob(avg_u)

    # Remove vig — normalise to sum = 1
    fair: dict = {}
    res_total = (h_p or 0) + (d_p or 0) + (a_p or 0)
    if res_total > 0:
        fair["home_win"] = round(h_p / res_total, 4) if h_p else None
        fair["draw"]     = round(d_p / res_total, 4) if d_p else None
        fair["away_win"] = round(a_p / res_total, 4) if a_p else None

    g_total = (o_p or 0) + (u_p or 0)
    if g_total > 0:
        fair["over_2_5"]  = round(o_p / g_total, 4) if o_p else None
        fair["under_2_5"] = round(u_p / g_total, 4) if u_p else None

    raw: dict = {}
    if avg_h: raw["home_win"]  = round(avg_h, 2)
    if avg_d: raw["draw"]      = round(avg_d, 2)
    if avg_a: raw["away_win"]  = round(avg_a, 2)
    if avg_o: raw["over_2_5"]  = round(avg_o, 2)
    if avg_u: raw["under_2_5"] = round(avg_u, 2)

    avg_by = _avg(btts_yes)
    avg_bn = _avg(btts_no)
    by_p, bn_p = _prob(avg_by), _prob(avg_bn)

    btts_total = (by_p or 0) + (bn_p or 0)
    if btts_total > 0:
        fair["btts_yes"] = round(by_p / btts_total, 4) if by_p else None
        fair["btts_no"]  = round(bn_p / btts_total, 4) if bn_p else None

    if avg_by: raw["btts_yes"] = round(avg_by, 2)
    if avg_bn: raw["btts_no"]  = round(avg_bn, 2)

    return {
        "fair_probs":      fair,
        "raw_odds":        raw,
        "bookmakers":      bookmaker_names[:6],
        "num_bookmakers":  len(h2h_home),
    }


# ── Claude analysis ───────────────────────────────────────────────────────────

def _pct(v) -> str:
    if v is None:
        return "N/A"
    return f"{float(v)*100:.0f}%"


def _compute_ev(model_probs: dict, bm_data: Optional[dict]) -> dict:
    """
    Expected value = model_probability × bookmaker_decimal_odds − 1.

    A positive EV means our model thinks the outcome is more likely than the
    odds imply, and by how much relative to the stake.
    Returns a dict of {market_label: ev_float} for every market with data.
    """
    if not bm_data:
        return {}
    raw = bm_data.get("raw_odds", {})
    under_prob = 1.0 - model_probs.get("over_2_5", 0.5)   # was `or 0.5` — falsy trap when prob==0.0
    btts_prob  = model_probs.get("btts")
    ng_prob    = (1.0 - btts_prob) if btts_prob is not None else None
    mappings = [
        ("Home Win",  "home_win",  model_probs.get("home_win")),
        ("Draw",      "draw",      model_probs.get("draw")),
        ("Away Win",  "away_win",  model_probs.get("away_win")),
        ("Over 2.5",  "over_2_5",  model_probs.get("over_2_5")),
        ("Under 2.5", "under_2_5", under_prob),
        ("GG",        "btts_yes",  btts_prob),
        ("NG",        "btts_no",   ng_prob),
    ]
    ev: dict = {}
    for label, key, prob in mappings:
        odds = raw.get(key)
        if odds and prob is not None:
            ev[label] = round(float(prob) * float(odds) - 1, 4)
    return ev


_MARKET_MODEL_KEY = {
    "Home Win":  "home_win", "Draw":     "draw",
    "Away Win":  "away_win", "Over 2.5": "over_2_5",
    "Under 2.5": "over_2_5",  # complement
    "GG":        "btts",     "NG":       "btts",
}
_MARKET_ODDS_KEY = {
    "Home Win":  "home_win",  "Draw":     "draw",
    "Away Win":  "away_win",  "Over 2.5": "over_2_5",
    "Under 2.5": "under_2_5", "GG":       "btts_yes",
    "NG":        "btts_no",
}


def _strip_default_btts(model_probs: dict, eps: float = 0.02) -> dict:
    """Return a copy with btts set to None when it's within eps of the 0.50
    fallback (i.e. the BTTS model produced no real signal). Prevents bogus
    GG/NG expected-value from a default probability × long odds."""
    btts = model_probs.get("btts")
    if btts is not None and abs(float(btts) - 0.5) <= eps:
        mp = dict(model_probs)
        mp["btts"] = None
        return mp
    return model_probs


def shrunk_ev(
    market: str,
    model_probs: Optional[dict],
    fair_probs: Optional[dict],
    raw_odds: dict,
) -> Optional[float]:
    """
    Expected value at the market-shrunk probability p′ = (1−S)·model + S·fair.

    This is the honest EV: the raw model EV systematically overstated edge
    (tracked suggestions anti-selected), so both the suggestion gate and the
    stored/displayed ev_score use this quantity. None when the market can't be
    validated (missing model prob, fair prob, or odds).
    """
    if not model_probs or not fair_probs:
        return None
    m = model_probs.get(_MARKET_MODEL_KEY.get(market, ""))
    if m is None:
        return None
    if market in ("Under 2.5", "NG"):
        m = 1.0 - m
    fk   = _MARKET_ODDS_KEY.get(market, "")
    k    = fair_probs.get(fk)
    odds = raw_odds.get(fk)
    if k is None or not odds:
        return None
    p_shrunk = (1.0 - MARKET_SHRINKAGE) * float(m) + MARKET_SHRINKAGE * float(k)
    return p_shrunk * float(odds) - 1.0


_ODDS_KEY = {
    "Home Win":  "home_win",  "Draw":     "draw",
    "Away Win":  "away_win",  "Over 2.5": "over_2_5",
    "Under 2.5": "under_2_5", "GG":       "btts_yes",
    "NG":        "btts_no",
}
_MODEL_KEY = {
    "Home Win":  "home_win", "Draw":     "draw",
    "Away Win":  "away_win", "Over 2.5": "over_2_5",
    "Under 2.5": "over_2_5",   # complement
    "GG":        "btts",     "NG":       "btts",
}


def _qualifying_markets(
    ev: dict,
    raw_odds: dict,
    fair_probs: Optional[dict] = None,
    model_probs: Optional[dict] = None,
) -> dict:
    """Markets passing the EV + sanity filters (1–4) — WITHOUT the suggestable
    kill-switch. Returns {market: raw_ev}. Callers apply the kill-switch:
    _top_ev_markets keeps only proven markets, _watch_markets keeps the rest.

    Filters: 1) EV ≥ threshold (favorite vs alt) at the market-shrunk prob,
    2) bookmaker prob ≥ MIN_BM_PROB (no longshots), 3) model prob ≥ the per-type
    floor (plausible outcome), 4) never the model's least-likely 1×2 outcome."""
    model_favorite = model_last = None
    if model_probs:
        result_probs = {
            "Home Win": model_probs.get("home_win", 0),
            "Draw":     model_probs.get("draw",     0),
            "Away Win": model_probs.get("away_win", 0),
        }
        model_favorite = max(result_probs, key=result_probs.__getitem__)
        model_last     = min(result_probs, key=result_probs.__getitem__)

    def _threshold(market: str) -> float:
        return MIN_EV_FAVORITE if market == model_favorite else MIN_EV_ALT

    # Filter 1 — EV ≥ threshold at the market-shrunk probability
    positive = {}
    for k, v in ev.items():
        sev = shrunk_ev(k, model_probs, fair_probs, raw_odds)
        if sev is not None and sev >= _threshold(k):
            positive[k] = v

    # Filter 2 — bookmaker probability (longshot exclusion)
    if fair_probs:
        positive = {k: v for k, v in positive.items()
                    if (fair_probs.get(_ODDS_KEY.get(k, "")) or 1.0) >= MIN_BM_PROB}

    # Filter 3 — model probability (plausible outcome)
    goals_markets = {"Over 2.5", "Under 2.5", "GG", "NG"}
    if model_probs:
        def _model_prob(market: str) -> float:
            p = model_probs.get(_MODEL_KEY.get(market, ""), 0.0) or 0.0
            if market in ("Under 2.5", "NG"):
                p = 1.0 - p
            return p
        positive = {k: v for k, v in positive.items()
                    if _model_prob(k) >= (MIN_MODEL_PROB_GOALS if k in goals_markets
                                          else MIN_MODEL_PROB_1X2)}

    # Filter 4 — never the model's least-likely 1×2 outcome (if alternatives exist)
    if model_last and model_last in positive:
        alt = {k: v for k, v in positive.items() if k != model_last}
        if alt:
            positive = alt
    return positive


def _fmt_market(market: str, raw_odds: dict) -> str:
    odds = raw_odds.get(_ODDS_KEY.get(market, ""), "")
    return f"{market} @ {odds}" if odds else market


def _top_ev_markets(
    ev: dict,
    raw_odds: dict,
    fair_probs: Optional[dict] = None,
    model_probs: Optional[dict] = None,
    n: int = 2,
    suggestable: Optional[set] = None,
) -> list:
    """Up to `n` 'Market @ odds' strings ranked by EV that pass the sanity
    filters AND are in the suggestable set. `suggestable` defaults to the static
    SUGGESTABLE_MARKETS (back-compat for the club path); the national path passes
    a dynamic proven_markets() set."""
    allow = SUGGESTABLE_MARKETS if suggestable is None else suggestable
    q = {k: v for k, v in _qualifying_markets(ev, raw_odds, fair_probs, model_probs).items()
         if k in allow}
    ranked = sorted(q, key=q.__getitem__, reverse=True)[:n]
    return [_fmt_market(m, raw_odds) for m in ranked]


def _watch_markets(
    ev: dict,
    raw_odds: dict,
    fair_probs: Optional[dict] = None,
    model_probs: Optional[dict] = None,
    n: int = 3,
    suggestable: Optional[set] = None,
) -> list:
    """Markets that clear the sanity filters but are NOT yet proven — surfaced as
    'unproven/watch' (shown + shadow-tracked, never staked with conviction until
    the new model's record promotes them). Returns dicts for the UI."""
    allow = SUGGESTABLE_MARKETS if suggestable is None else suggestable
    q = {k: v for k, v in _qualifying_markets(ev, raw_odds, fair_probs, model_probs).items()
         if k not in allow}
    ranked = sorted(q, key=q.__getitem__, reverse=True)[:n]
    out = []
    for m in ranked:
        ok = _ODDS_KEY.get(m, "")
        out.append({
            "market":     _fmt_market(m, raw_odds),
            # EV = return per unit staked (prob × odds − 1). NOT a probability —
            # keep it distinct from model_pct/market_pct, which are probabilities.
            "ev_pct":     round(q[m] * 100, 1),
            "model_pct":  _model_prob_pct(m, model_probs),
            "market_pct": round((fair_probs or {}).get(ok, 0) * 100, 1) if fair_probs else None,
        })
    return out


def _model_prob_pct(market: str, model_probs: Optional[dict]) -> Optional[float]:
    """Our model's probability (%) for a market — the like-for-like counterpart
    of the de-vigged market_pct. Under 2.5 / NG are complements."""
    if not model_probs:
        return None
    p = model_probs.get(_MARKET_MODEL_KEY.get(market, ""))
    if p is None:
        return None
    if market in ("Under 2.5", "NG"):
        p = 1.0 - p
    return round(float(p) * 100, 1)


def _best_ev_market(
    ev: dict,
    raw_odds: dict,
    fair_probs: Optional[dict] = None,
    model_probs: Optional[dict] = None,
    suggestable: Optional[set] = None,
) -> Optional[str]:
    """Return top-1 qualifying+proven market string, or None."""
    results = _top_ev_markets(ev, raw_odds, fair_probs=fair_probs,
                              model_probs=model_probs, n=1, suggestable=suggestable)
    return results[0] if results else None


def _get_llm_analysis(
    home_team: str,
    away_team: str,
    league: str,
    model_probs: dict,
    bm_data: Optional[dict],
    injury_data: Optional[dict] = None,
    watch_markets: Optional[list] = None,
) -> dict:
    """
    Ask Groq (Llama-3.3-70B) for a 2–3 sentence analysis + 1 suggested market.
    Returns {"text": str, "suggested_market": str | None}.

    `watch_markets` are markets with a real model edge that aren't yet a proven
    suggestion (being shadow-tracked on the new model) — the analysis should
    acknowledge them honestly rather than claim "no opportunity exists".
    """
    if not GROQ_API_KEY:
        return {
            "text": "LLM analysis not available — add GROQ_API_KEY to .env.",
            "suggested_market": None,
        }

    # Build bookmaker + EV section of the prompt
    ev: dict = {}
    best_market: Optional[str] = None

    if bm_data and bm_data.get("fair_probs"):
        fp  = bm_data["fair_probs"]
        raw = bm_data.get("raw_odds", {})

        ev = _compute_ev(model_probs, bm_data)
        best_market = _best_ev_market(ev, raw, fair_probs=fp, model_probs=model_probs)

        def _ev_str(label: str) -> str:
            v = ev.get(label)
            if v is None:
                return "N/A"
            sign = "+" if v >= 0 else ""
            return f"{sign}{v*100:.1f}%"

        # Build BTTS section only when bookmaker odds are available
        btts_line = ""
        if fp.get("btts_yes") is not None or fp.get("btts_no") is not None:
            btts_line = (
                f"\n  GG (both score): {_pct(fp.get('btts_yes'))}  "
                f"(avg odds {raw.get('btts_yes','—')}, EV {_ev_str('GG')})"
                f"\n  NG (not both):   {_pct(fp.get('btts_no'))}  "
                f"(avg odds {raw.get('btts_no','—')}, EV {_ev_str('NG')})"
            )

        bm_section = (
            f"Bookmaker consensus ({bm_data['num_bookmakers']} bookmakers, vig removed):\n"
            f"  Home Win: {_pct(fp.get('home_win'))}  (avg odds {raw.get('home_win','—')}, EV {_ev_str('Home Win')})\n"
            f"  Draw:     {_pct(fp.get('draw'))}  (avg odds {raw.get('draw','—')}, EV {_ev_str('Draw')})\n"
            f"  Away Win: {_pct(fp.get('away_win'))}  (avg odds {raw.get('away_win','—')}, EV {_ev_str('Away Win')})\n"
            f"  Over 2.5: {_pct(fp.get('over_2_5'))}  (avg odds {raw.get('over_2_5','—')}, EV {_ev_str('Over 2.5')})\n"
            f"  Under 2.5:{_pct(fp.get('under_2_5'))}  (avg odds {raw.get('under_2_5','—')}, EV {_ev_str('Under 2.5')})"
            f"{btts_line}\n"
            f"  Sources: {', '.join(bm_data.get('bookmakers', []))}"
        )
    else:
        bm_section = "No bookmaker odds available for this match."

    # Tell Claude which market to suggest (computed deterministically from EV).
    # Two-tier EV filter applied before we arrive here:
    #   • Model's own top-pick market requires EV ≥ 5% (bookmakers rarely misprice
    #     clear favourites enough to offer real value at tight odds).
    #   • Alternative markets (not the model's top pick) require EV ≥ 3% — a
    #     non-obvious value bet is worth surfacing even at a smaller edge.
    #   • Any market with bookmaker-implied probability < 10% is excluded regardless.
    if best_market:
        suggested_rule = (
            f"The market with the highest positive expected value is: {best_market}.\n"
            f"Your SUGGESTED line MUST use this market exactly as written.\n"
            f"If this market is NOT the match result that corresponds to the model's "
            f"highest-probability team, explicitly say so in your analysis — e.g. "
            f"'While [team] is our top pick, their odds are already priced in by bookmakers; "
            f"the better value lies in [suggested market].' "
            f"Do NOT suggest markets with bookmaker-implied probability below 10%."
        )
    else:
        suggested_rule = (
            "No PROVEN market clears both EV and probability filters. "
            "Omit the SUGGESTED line entirely — do not invent a suggestion. "
            "If a team is a clear model favourite but their odds offer no value, "
            "say so explicitly in your analysis."
        )

    # Watch markets — a real model edge that is NOT a proven suggestion yet.
    # The model must NOT claim 'no value anywhere' when these exist; it should
    # name them and explain they're being tracked, not yet trusted to stake.
    watch_section = ""
    if watch_markets:
        # EV is return-per-stake, not a probability — state both so the LLM
        # doesn't narrate "the model gives it 55%" when 55% is the EV.
        items = ", ".join(
            f"{w['market']} (EV {w['ev_pct']:+.0f}% per unit staked; model "
            f"{w['model_pct']:.0f}% vs market {w['market_pct']:.0f}%)"
            if w.get("model_pct") is not None and w.get("market_pct") is not None
            else f"{w['market']} (EV {w['ev_pct']:+.0f}% per unit staked)"
            for w in watch_markets
        )
        watch_section = (
            f"\nWATCH markets (model shows an edge, but this market is not yet a proven "
            f"suggestion on the current model — we are tracking it, not staking it): {items}.\n"
            f"In your analysis, acknowledge the strongest watch market by name and state plainly "
            f"that the model rates it higher than the bookmakers but it stays UNPROVEN until its "
            f"tracked record earns it — do NOT present it as a recommended bet, and do NOT say "
            f"there is no edge anywhere if a watch market exists."
        )

    injury_section = _format_injuries(injury_data, home_team, away_team)

    # Build a mandatory injury instruction when real player data is present
    has_real_injuries = bool(
        injury_data and (injury_data.get("home") or injury_data.get("away"))
    )
    if has_real_injuries:
        injury_rule = (
            "ΥΠΟΧΡΕΩΤΙΚΟ: Η παραπάνω λίστα τραυματιών/αποκλεισμένων περιέχει πραγματικά δεδομένα. "
            "Πρέπει ΑΠΑΡΑΙΤΗΤΩΣ να αναφέρεις τους συγκεκριμένους παίκτες που λείπουν στην ανάλυσή σου "
            "και να εξηγήσεις πώς επηρεάζουν τις πιθανότητες. "
            "ΜΗΝ πεις ότι δεν υπάρχουν τραυματίες — υπάρχουν."
        )
    else:
        injury_rule = (
            "Δεν υπάρχουν δεδομένα τραυματιών — μην αναφέρεις τραυματισμούς."
        )

    prompt = f"""Είσαι αναλυτής αθλητικού στοιχήματος. Ανάλυσε τον αγώνα {home_team} vs {away_team} ({league}).

Πιθανότητες μοντέλου ML (XGBoost, εκπαιδευμένο σε ιστορικά δεδομένα):
  Νίκη γηπεδούχου: {_pct(model_probs.get('home_win'))}
  Ισοπαλία:        {_pct(model_probs.get('draw'))}
  Νίκη φιλοξενούμενου: {_pct(model_probs.get('away_win'))}
  Over 2.5 γκολ:   {_pct(model_probs.get('over_2_5'))}

{bm_section}

Τραυματίες & αποκλεισμένοι (από API-Football):
{injury_section}

{injury_rule}

Αναμενόμενη αξία (EV) = πιθανότητα_μοντέλου × απόδοση_bookmaker − 1. \
Θετικό EV σημαίνει ότι το μοντέλο πιστεύει ότι η έκβαση είναι υποτιμημένη από τα γραφεία. \
Σημείωση: το μοντέλο βασίζεται σε ομαδικά στατιστικά και ΔΕΝ λαμβάνει υπόψη \
απουσίες μεμονωμένων παικτών.

{suggested_rule}
{watch_section}

Γράψε ακριβώς 2-3 προτάσεις στα ΕΛΛΗΝΙΚΑ: περιέγραψε τη μεγαλύτερη απόκλιση \
μοντέλου-bookmakers, ανέφερε τους τραυματίες/αποκλεισμένους (αν υπάρχουν στη λίστα), \
και εξήγησε σύντομα γιατί η προτεινόμενη αγορά έχει το καλύτερο συνδυασμό \
πλεονεκτήματος και απόδοσης. \
Μετά, σε ΝΕΑ ΓΡΑΜΜΗ, γράψε ΑΚΡΙΒΩΣ (στα αγγλικά, αμετάβλητο format):
SUGGESTED: <market name> @ <decimal odds>

Να είσαι αναλυτικός, όχι διαφημιστικός. Χωρίς εισαγωγικές φράσεις."""

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY, timeout=20.0)
        msg = client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=450,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = msg.choices[0].message.content.strip()

        # Split analysis from SUGGESTED line
        lines = raw_text.splitlines()
        analysis_lines = []
        suggested = None
        for line in lines:
            if line.startswith("SUGGESTED:"):
                val = line.replace("SUGGESTED:", "").strip()
                # Groq sometimes outputs "None" / "N/A" / "-" when no suggestion
                if val.lower() not in ("none", "n/a", "-", "", "no suggestion"):
                    suggested = val
            elif line.strip():
                analysis_lines.append(line.strip())

        return {
            "text":              " ".join(analysis_lines),
            "suggested_market":  suggested,
        }

    except Exception as e:
        log.warning(f"[groq] Analysis error: {e}")
        return {
            "text":              "Analysis temporarily unavailable.",
            "suggested_market":  None,
        }


# ── Public entry point ────────────────────────────────────────────────────────

def run_comparison(
    match_id: int,
    home_team: str,
    away_team: str,
    league: str,
    model_probs: dict,
    match_date=None,
) -> dict:
    """
    Main entry point called by the FastAPI endpoint.

    Returns:
        {
          match_id, home_team, away_team,
          model: {home_win, draw, away_win, over_2_5},
          bookmakers: {fair_probs, raw_odds, bookmakers, num_bookmakers} | None,
          analysis: str,
          suggested_market: str | None,
          has_odds_data: bool,
        }

    Results are cached in memory for CACHE_TTL seconds to conserve API quota.
    Cache key includes a fingerprint of model_probs so retraining the model
    (which changes the stored probabilities) automatically busts the cache.
    """
    # Fingerprint: probs + injury presence — changes when model is retrained or
    # injury status flips (None → data), forcing a fresh Groq analysis.
    # fetch_bookmaker_odds and fetch_injuries are both internally cached for
    # 30 min so this pre-fetch is cheap on repeated calls.
    probs_fp = (
        round(model_probs.get("home_win", 0), 3),
        round(model_probs.get("draw",     0), 3),
        round(model_probs.get("away_win", 0), 3),
        round(model_probs.get("over_2_5", 0), 3),
    )

    bm_data      = fetch_bookmaker_odds(home_team, away_team, league)
    injury_data  = fetch_injuries(home_team, away_team, league, match_date)

    has_injuries_flag = bool(
        injury_data and (injury_data.get("home") or injury_data.get("away"))
    )
    redis_key = (
        f"analysis:{match_id}:"
        f"{probs_fp[0]}:{probs_fp[1]}:{probs_fp[2]}:{probs_fp[3]}:"
        f"{int(has_injuries_flag)}"
    )
    cached = cache_get(redis_key)
    if cached is not CACHE_MISS:
        return cached

    # Drop a no-signal default BTTS prob so it can't produce a fake GG/NG edge.
    model_probs = _strip_default_btts(model_probs)

    # Pre-compute top EV markets (up to 2) for deterministic suggestion
    ev = _compute_ev(model_probs, bm_data)
    raw_odds   = (bm_data or {}).get("raw_odds", {})
    fair_probs = (bm_data or {}).get("fair_probs", {})
    ev_markets = _top_ev_markets(ev, raw_odds, fair_probs=fair_probs, model_probs=model_probs, n=2)
    ev_best    = ev_markets[0] if ev_markets else None

    analysis = _get_llm_analysis(
        home_team, away_team, league, model_probs, bm_data, injury_data
    )

    # Deterministic EV pick is canonical — it passes all probability filters.
    # Groq's pick is used ONLY when the deterministic algorithm found nothing
    # (ev_best is None), meaning there's no market that clears both EV and
    # probability thresholds and the LLM may still have useful qualitative context.
    # When ev_best exists, always prefer it — prevents Groq from suggesting a Draw
    # just because the odds are attractive even if the model ranks it last.
    #
    # Groq's fallback pick must ALSO respect the kill-switch: the LLM must not
    # reintroduce a market (Over/Away Win/GG/…) that the deterministic gate
    # excludes for having an unprofitable tracked record.
    groq_pick = analysis["suggested_market"]
    if groq_pick:
        groq_market = groq_pick.split(" @ ")[0].strip()
        if groq_market not in SUGGESTABLE_MARKETS:
            groq_pick = None
    suggested = ev_best or groq_pick

    # suggested_markets: full ranked list (up to 2) for display on analysis page.
    # Falls back to [suggested] when deterministic algo found nothing but Groq did.
    if ev_markets:
        suggested_markets = ev_markets
    elif suggested:
        suggested_markets = [suggested]
    else:
        suggested_markets = []

    result = {
        "match_id":          match_id,
        "home_team":         home_team,
        "away_team":         away_team,
        "model":             model_probs,
        "bookmakers":        bm_data,
        "injuries":          injury_data,
        "analysis":          analysis["text"],
        "suggested_market":  suggested,
        "suggested_markets": suggested_markets,
        "has_odds_data":     bm_data is not None,
        "has_injury_data":   injury_data is not None,
    }

    cache_set(redis_key, result, CACHE_TTL)
    return result
