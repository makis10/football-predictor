"""Expected team props (corners + cards) for a CLUB fixture, computed on demand
from team_match_stats — mirrors the national logic (player_props.load_team_*),
so club match pages can show the same Expected Cards / Expected Corners blocks.

team_match_stats stores API-Football team names for club rows, so we translate
our DB name → the API name at query time (slug + a small override table).
"""
from __future__ import annotations

import math
import re
import unicodedata

HALF_LIFE_DAYS = 540.0
_MAX_AGE_DAYS = 365 * 3

# our DB name → the exact name API-Football uses (= the name stored in
# team_match_stats / player_match_stats rows).
#
# ONE table, imported by both sides. It used to exist twice — here for reading
# and again in scripts/fetch_club_team_stats.py for writing — and they drifted:
# the 2026-07-30 expansion was added only to the writer, so stats WERE ingested
# for Sion, Thun, LASK, Rakow, Univ. Craiova and CFR Cluj but the match page
# could not find them and showed "—" for cards and corners.
#
# Several entries here are load-bearing against a WRONG match, not just a
# missing one, because club_props' containment fallback would otherwise guess:
#   Rakow   — "rakow" is a substring of "krakow" (Wisla/Cracovia Krakow)
#   Wisla   — Wisła Kraków and Wisła Płock are different clubs
#   LASK    — "lask" is a substring of "Slask Wroclaw"
#   CFR Cluj / U. Cluj — two different Cluj clubs
NAME_OVERRIDES: dict[str, str] = {
    'AC Milan': 'AC Milan',
    'AEK': 'AEK Athens FC',
    'Accrington': 'Accrington ST',
    'Almere City FC': 'Almere City FC',
    'Aris': 'Aris Thessalonikis',
    'Ath Bilbao': 'Athletic Club',
    'Ath Madrid': 'Atletico Madrid',
    'Athletico-PR': 'Atletico Paranaense',
    'Augsburg': 'FC Augsburg',
    'Basel': 'FC Basel 1893',
    'Bayern Munich': 'Bayern München',
    'Betis': 'Real Betis',
    'Vfl Bochum': 'VfL Bochum',
    'Botafogo RJ': 'Botafogo',
    'Bragantino': 'RB Bragantino',
    'CFR Cluj': 'CFR 1907 Cluj',
    'SV Darmstadt 98': 'SV Darmstadt 98',
    'Den Haag': 'ADO Den Haag',
    'Dortmund': 'Borussia Dortmund',
    'Ein Frankfurt': 'Eintracht Frankfurt',
    'Espanol': 'Espanyol',
    'Gladbach': 'Borussia Mönchengladbach',
    'Go Ahead': 'GO Ahead Eagles',
    'De Graafschap': 'De Graafschap',
    'SpVgg Greuther Furth': 'SpVgg Greuther Fürth',
    'FC Heidenheim': '1. FC Heidenheim',
    'Hoffenheim': '1899 Hoffenheim',
    'Horsens': 'AC Horsens',
    'FC Ingolstadt 04': 'FC Ingolstadt 04',
    'Inter': 'Inter',
    'Ipswich': 'Ipswich',
    'Jaro': 'FF Jaro',
    'FC Kaiserslautern': '1. FC Kaiserslautern',
    'LASK': 'Lask Linz',
    'Leganes': 'Leganes',
    'Levadeiakos': 'Levadiakos',
    'Leverkusen': 'Bayer Leverkusen',
    'Luzern': 'FC Luzern',
    'Mainz': 'FSV Mainz 05',
    'Man City': 'Manchester City',
    'Man United': 'Manchester United',
    'Nijmegen': 'NEC Nijmegen',
    "Nott'm Forest": 'Nottingham Forest',
    'FC Nurnberg': '1. FC Nürnberg',
    'OFI Crete': 'OFI',
    'Olympiakos': 'Olympiakos Piraeus',
    'PAOK': 'PAOK',
    'Paris SG': 'Paris Saint Germain',
    # 2026-08-02. Without these the league sweep misses them on a slug compare
    # ("porto" vs "fcporto") and the per-team /teams?search fallback takes over —
    # which found a Brazilian club also called "Porto" (id 20782) and charged
    # FC Porto's cards and corners to it. Same-name-different-country is a hole
    # the youth/women's guard cannot see.
    # Same class, found by validating the whole cache against league rosters:
    # "Milan" matched a club in GAMBIA (16803), "Roma" one in SLOVENIA (22590),
    # "Lugano" one in ARGENTINA (8396). None had corrupted the DB yet — they
    # would have on the next stats fetch for those clubs.
    'Milan': 'AC Milan',
    'Roma': 'AS Roma',
    'Lugano': 'FC Lugano',
    'Iraklis 1908': 'Iraklis 1908',
    'Porto': 'FC Porto',
    'Sp Lisbon': 'Sporting CP',
    'Vitoria SC': 'Guimaraes',
    'Mechelen': 'KV Mechelen',
    'For Sittard': 'Fortuna Sittard',
    'Flamengo RJ': 'Flamengo',
    'Peterboro': 'Peterborough',
    'Rakow': 'Raków Częstochowa',
    'Sepsi Sf. Gheorghe': 'Sepsi OSK Sfantu Gheorghe',
    'Sheffield United': 'Sheffield Utd',
    'Sion': 'FC Sion',
    'Sittard': 'Fortuna Sittard',
    'Sociedad': 'Real Sociedad',
    'Sp Braga': 'SC Braga',
    'Sparta': 'Sparta Rotterdam',
    'Spurs': 'Tottenham',
    'Stuttgart': 'VfB Stuttgart',
    'Thun': 'FC Thun',
    'U. Cluj': 'Universitatea Cluj',
    'Univ. Craiova': 'Universitatea Craiova',
    'Vasco': 'Vasco DA Gama',
    'Volendam': 'FC Volendam',
    'Widzew Lodz': 'Widzew Łódź',
    'Wisla': 'Wisla Krakow',
    'Wolfsburg': 'VfL Wolfsburg',
    'Wolves': 'Wolves',
    'Zurich': 'FC Zurich',
    'Zwolle': 'PEC Zwolle',

    # 2026-08-10, raised by the daily completeness check on the leagues added in
    # August (Turkey, Denmark, Belgium, Finland) plus one long-standing
    # Championship gap. Every one of these already HAS ingested stats — they sit
    # in team_match_stats under the API's spelling and the read side could not
    # find them, so the cards/corners panel rendered "—" on a club we cover.
    # Row counts waiting at the time of the fix are noted per line.
    'Kasimpasa':           'Kasımpaşa',        # 4 rows
    'Nordsjaelland':       'FC Nordsjaelland', # 7 rows
    'Oud-Heverlee Leuven': 'OH Leuven',        # 2 rows
    'Stoke':               'Stoke City',       # 6 rows
    'TPS':                 'Turku PS',         # 4 rows
    'Waasland-Beveren':    'SK Beveren',       # 1 row
}


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", (name or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", s.lower())


_NAME_MAP_PATH = None  # resolved lazily; module lives under backend/app/ml
_name_map_cache: "tuple[float, dict] | None" = None


def _learned_name_map() -> dict:
    """club_name_map.json — exact our-name → API-name mapping learned by
    fetch_club_team_stats.py from fixture responses. Reloaded every 30 min."""
    global _NAME_MAP_PATH, _name_map_cache
    import json
    import os
    import time
    if _NAME_MAP_PATH is None:
        _NAME_MAP_PATH = os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "models", "club_name_map.json")
    now = time.time()
    if _name_map_cache is not None and now - _name_map_cache[0] < 1800:
        return _name_map_cache[1]
    try:
        with open(_NAME_MAP_PATH) as f:
            m = json.load(f)
    except Exception:
        m = {}
    _name_map_cache = (now, m)
    return m


def _api_name(db, our_name: str) -> str | None:
    """Resolve our DB team name → the name stored in team_match_stats (API name)."""
    from sqlalchemy import text
    # 1. Exact learned mapping (written by the ingestion script) — no guessing.
    learned = _learned_name_map().get(our_name)
    if learned:
        hit = db.execute(text("SELECT 1 FROM team_match_stats WHERE team = :t LIMIT 1"),
                         {"t": learned}).fetchone()
        if hit:
            return learned
    if our_name in NAME_OVERRIDES:
        target = NAME_OVERRIDES[our_name]
    else:
        target = our_name
    tslug = _slug(target)
    # Fast path: exact stored name.
    hit = db.execute(text("SELECT 1 FROM team_match_stats WHERE team = :t LIMIT 1"),
                     {"t": target}).fetchone()
    if hit:
        return target
    stored_names = [s for (s,) in db.execute(
        text("SELECT DISTINCT team FROM team_match_stats")).fetchall()]
    # Exact slug match.
    for stored in stored_names:
        if _slug(stored) == tslug:
            return stored
    # Uniqueness-guarded containment: recover "Roma"→"AS Roma", "Stoke"→
    # "Stoke City", "Vallecano"→"Rayo Vallecano". Only accept when EXACTLY ONE
    # stored name contains/is-contained-by ours — otherwise it's ambiguous
    # ("Roma" also matches "Romania") and a wrong match is worse than None.
    # The ≥5-char guard blocks short-slug noise.
    if len(tslug) >= 5:
        cands = [s for s in stored_names
                 if tslug in _slug(s) or _slug(s) in tslug]
        if len(cands) == 1:
            return cands[0]
    return None


def corners_over_prob(exp_total: float, line: float = 9.5) -> float:
    if exp_total <= 0:
        return 0.0
    k_max = math.floor(line)
    cdf = sum(math.exp(-exp_total) * exp_total ** k / math.factorial(k) for k in range(k_max + 1))
    return max(0.0, min(1.0, 1.0 - cdf))


def _team_rate(db, api_name: str, metric_sql: str) -> float | None:
    """Recency-weighted per-match rate for one team from team_match_stats.
    `metric_sql` is a trusted internal expression (not user input)."""
    from sqlalchemy import text
    import numpy as np
    import pandas as pd
    rows = db.execute(text(
        f"SELECT match_date, {metric_sql} AS v FROM team_match_stats WHERE team = :t"
    ), {"t": api_name}).fetchall()
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date", "v"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "v"])
    if df.empty:
        return None
    age = (pd.Timestamp.today() - df["date"]).dt.days.clip(lower=0)
    df = df[age <= _MAX_AGE_DAYS]
    if df.empty:
        return None
    w = np.exp(-np.log(2) * (pd.Timestamp.today() - df["date"]).dt.days.clip(lower=0) / HALF_LIFE_DAYS)
    wsum = float(w.sum())
    return float((df["v"] * w).sum() / wsum) if wsum > 0 else None


def club_team_props(db, home: str, away: str) -> dict | None:
    """{exp_home_corners, exp_away_corners, corners_over_9_5_prob,
        exp_home_cards, exp_away_cards} — None when we have no club stats."""
    ah, aa = _api_name(db, home), _api_name(db, away)
    if not ah and not aa:
        return None
    hc = _team_rate(db, ah, "corners") if ah else None
    ac = _team_rate(db, aa, "corners") if aa else None
    hcards = _team_rate(db, ah, "COALESCE(yellow_cards,0)+COALESCE(red_cards,0)") if ah else None
    acards = _team_rate(db, aa, "COALESCE(yellow_cards,0)+COALESCE(red_cards,0)") if aa else None
    if hc is None and ac is None and hcards is None and acards is None:
        return None
    # Over/Under 9.5 needs the MATCH total — only meaningful when BOTH teams'
    # corner rates are known. With one side missing (e.g. a name-map miss) the
    # "total" is half a match and the probability is garbage (e.g. 4%), so
    # return None instead of a misleading number.
    both_corners = hc is not None and ac is not None
    return {
        "exp_home_corners": round(hc, 1) if hc is not None else None,
        "exp_away_corners": round(ac, 1) if ac is not None else None,
        "corners_over_9_5_prob": round(corners_over_prob(hc + ac), 3) if both_corners else None,
        "exp_home_cards": round(hcards, 1) if hcards is not None else None,
        "exp_away_cards": round(acards, 1) if acards is not None else None,
    }
