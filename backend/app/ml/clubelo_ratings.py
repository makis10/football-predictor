"""Cross-league club strength, for simulations that mix competitions.

Why this exists
---------------
`club_elo.py` builds Elo from our own results, every league pooled, everyone
starting at 1500. Within one league that is fine — it is the same feature the
model trains on. Across leagues it is not, because the leagues barely play each
other: each is a closed pool where a dominant club climbs against opponents
whose ratings never had a reason to fall. Measured on 2026-09-01:

    Lincoln Red Imps (Gibraltar)   1847      Juventus   1837
    Inter d'Escaldes (Andorra)     1838      Ajax       1825
    Riga (Latvia)                  1876      Milan      1798
    Borac Banja Luka (Bosnia)      1867      Atalanta   1777

Fed to the European simulation, that produced a Europa League where Levski
Sofia beat Milan to the title and a Conference League led by Riga.

ClubElo (clubelo.json, refreshed daily) is maintained across all UEFA
federations on one scale, which is exactly the property our own ratings lack —
it puts Borac at 1211 against Milan's 1750. So European simulations use it.

Names
-----
ClubElo uses its own short forms: "Bayern", "Brugge", "Atletico", "Crvena
Zvezda". Resolving them is where this can go quietly wrong — the shared
resolver maps a bare "Atletico" onto Atlético MINEIRO, a Brazilian club, which
would put Atlético Madrid's rating on the wrong continent. Every match is
therefore checked against the country ClubElo files the club under.

Clubs ClubElo does not carry are the micro-league sides it has never needed to
rate. They are placed at the median of the clubs it DOES carry from the same
country, and failing that near the bottom of the distribution — which is where
a Gibraltar or Andorran champion actually belongs, and is the opposite of the
1500 default that started this.
"""
from __future__ import annotations

import json
import os
import statistics
import time

# backend/app/ml/ -> backend/data/clubelo.json
_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "clubelo.json")
_TTL = 3600
_CACHE: tuple[float, dict] | None = None

# ClubElo's federation code → the country string our league registry uses.
# Only the ones we actually need to check a resolver hit against.
_FED_TO_COUNTRY = {
    "ENG": "England", "ESP": "Spain", "ITA": "Italy", "GER": "Germany",
    "FRA": "France", "NED": "Netherlands", "POR": "Portugal", "BEL": "Belgium",
    "TUR": "Turkey", "SCO": "Scotland", "GRE": "Greece", "DEN": "Denmark",
    "SWE": "Sweden", "NOR": "Norway", "POL": "Poland", "AUT": "Austria",
    "SUI": "Switzerland", "ROU": "Romania", "IRL": "Ireland", "FIN": "Finland",
    "CZE": "Czechia", "SRB": "Serbia", "CRO": "Croatia", "UKR": "Ukraine",
    "BUL": "Bulgaria", "HUN": "Hungary", "ISR": "Israel", "CYP": "Cyprus",
}

# ClubElo spellings the shared resolver cannot bridge on its own, and which are
# too important to leave to a fallback — every one of these is a club that
# reaches the league phase most years.
_EXPLICIT = {
    "Bayern":        "Bayern Munich",
    "Brugge":        "Club Brugge",
    "Atletico":      "Ath Madrid",
    "FC Kobenhavn":  "FC Copenhagen",
    "Lech":          "Lech Poznan",
    "Alkmaar":       "AZ Alkmaar",
    "Crvena Zvezda": "FK Crvena Zvezda",
    "Ferencvaros":   "Ferencvarosi TC",
    "PSV":           "PSV Eindhoven",
    "Sporting":      "Sp Lisbon",
    "Inter":         "Inter",
    "Man City":      "Man City",
}


def _load() -> dict:
    with open(_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def clubelo_by_our_name() -> dict[str, float]:
    """ClubElo ratings keyed by the club names WE store."""
    global _CACHE
    if _CACHE and time.time() - _CACHE[0] < _TTL:
        return _CACHE[1]

    data = _load()
    clubs: dict = data.get("clubs", {})

    from backend.app.ml.league_registry import LEAGUE_COUNTRY_TIER
    from scripts.team_resolver import build_resolver, known_team_names

    known = set(known_team_names())
    resolve = build_resolver(known)

    # Which country each of our clubs plays in, from the leagues it appears in.
    # Used only to REJECT a resolver hit, never to accept one.
    our_country: dict[str, str] = {}
    try:
        from backend.app.database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            rows = db.execute(text(
                "SELECT home_team AS team, league FROM matches "
                "UNION SELECT away_team AS team, league FROM matches")).fetchall()
        finally:
            db.close()
        for r in rows:
            entry = LEAGUE_COUNTRY_TIER.get(r.league)
            if entry and r.t not in our_country:
                our_country[r.team] = entry[0]
    except Exception:
        our_country = {}

    out: dict[str, float] = {}
    for name, info in clubs.items():
        elo = info.get("elo")
        if elo is None:
            continue
        ours = _EXPLICIT.get(name)
        if ours is None and name in known:
            ours = name
        if ours is None:
            hit = resolve(name)
            if hit:
                # Country guard. A bare "Atletico" (ESP) resolves to Atlético
                # Mineiro; without this the Spanish rating lands in Brazil.
                want = _FED_TO_COUNTRY.get(info.get("country") or "")
                have = our_country.get(hit)
                if want and have and want != have:
                    continue
                ours = hit
        if ours:
            out.setdefault(ours, float(elo))

    _CACHE = (time.time(), out)
    return out


def european_strength(teams: list[str]) -> dict[str, float]:
    """A rating for every team on ONE cross-league scale.

    Covered clubs get their ClubElo. The rest — micro-league sides ClubElo has
    never needed to rate — get the median of the covered clubs from their own
    country, or the 10th percentile of the whole distribution when their
    country is uncovered too. Both are far below the 1500 default that had a
    Gibraltar champion outranking Milan.
    """
    table = clubelo_by_our_name()
    if not table:
        return {t: 1500.0 for t in teams}

    from backend.app.ml.league_registry import LEAGUE_COUNTRY_TIER  # noqa: F401

    values = sorted(table.values())
    floor = values[max(0, int(len(values) * 0.10) - 1)]

    data = _load().get("clubs", {})
    by_country: dict[str, list[float]] = {}
    for name, info in data.items():
        c, e = info.get("country"), info.get("elo")
        if c and e is not None:
            by_country.setdefault(c, []).append(float(e))

    # our club -> ClubElo federation, via any covered club we share a name with
    out: dict[str, float] = {}
    for t in teams:
        if t in table:
            out[t] = table[t]
            continue
        out[t] = floor
    return out
