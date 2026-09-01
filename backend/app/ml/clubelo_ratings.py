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
_CSV_LEAGUES: list | None = None

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

# ClubElo spelling -> ours, for clubs the federation-scoped matcher still
# cannot bridge. Each was checked against the snapshot's own country field
# before being written here; the federation is in the comment so the next
# reader can re-check without guessing.
#
# Deliberately NOT here, and why — every one of these looks like an easy win
# and is a different club:
#   Ararat (ARM)                 Ararat Yerevan, not Ararat-Armenia
#   Escaldes / Atletic Club      two Andorran clubs, neither is Inter d'Escaldes
#   AEK (GRE)                    not PAEEK, which is Cypriot
# and OFI Crete, Torreense and PAEEK are simply absent from the snapshot.
# A wrong rating is worse than a missing one: missing shows as the floor and
# reads as uncertainty, wrong reads as fact.
_CLUBELO_ALIASES = {
    "Braga":             "Sp Braga",             # POR
    "FC Kobenhavn":      "FC Copenhagen",        # DEN
    "PSV":               "PSV Eindhoven",        # NED
    "Paphos":            "Pafos",                # CYP
    "Kuopio":            "KuPS",                 # FIN
    "Atletico":          "Ath Madrid",           # ESP — never Atlético Mineiro
    "Craiova":           "Univ. Craiova",        # ROM
    "Sabah":             "Sabah FA",             # AZE
    "Lincoln":           "Lincoln Red Imps FC",  # GIB — not Lincoln City
    "Shakhtar":          "Shakhtar Donetsk",     # UKR
    "Levski":            "Levski Sofia",         # BUL
    "Sociedad B":        "Real Sociedad II",     # ESP — the reserve side
    # Ambiguous inside their own federation, so the unique-match rule declines
    # them and they need naming: "Brugge" also matches Cercle Brugge, "Omonia"
    # also matches Omonia Aradippou.
    "Brugge":            "Club Brugge",          # BEL
    "Omonia":            "Omonia Nicosia",       # CYP
    "Sporting":          "Sp Lisbon",            # POR — not Sporting Gijón
}
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


def _csv_team_leagues() -> list[tuple[str, str]]:
    """(club, league) pairs from the training CSVs. Cached for the process.

    Read through the same loader features.py uses, so the club names are the
    canonical ones the rest of the system stores.
    """
    global _CSV_LEAGUES
    if _CSV_LEAGUES is not None:
        return _CSV_LEAGUES
    try:
        import os

        from backend.app.ml.features import load_raw_csvs
        raw = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "raw")
        df = load_raw_csvs(raw)
        pairs = set()
        for col in ("home_team", "away_team"):
            pairs.update(zip(df[col], df["League"]))
        _CSV_LEAGUES = sorted(pairs)
    except Exception:
        _CSV_LEAGUES = []
    return _CSV_LEAGUES


def clubelo_by_our_name() -> dict[str, float]:
    """ClubElo ratings keyed by the club names WE store.

    Matched WITHIN a federation, never across. ClubElo's spellings change with
    the snapshot — one had "Bayern", the next "Bayern München" — so hard-coding
    them breaks the moment upstream reformats, which is exactly what happened
    the first time this was written. Comparing only against our own clubs from
    the same country makes the name matcher's job small enough to be reliable,
    and makes the classic failure impossible: a bare "Atletico" filed under ESP
    can no longer reach Atlético MINEIRO in Brazil.
    """
    global _CACHE
    if _CACHE and time.time() - _CACHE[0] < _TTL:
        return _CACHE[1]

    clubs: dict = _load().get("clubs", {})
    if not clubs:
        return {}

    from backend.app.ml.league_registry import LEAGUE_COUNTRY_TIER
    from backend.app.ml.odds_analysis_service import _slug, _teams_match

    # Our clubs, grouped by the country of the leagues they appear in.
    ours_by_country: dict[str, set[str]] = {}
    try:
        from sqlalchemy import text

        from backend.app.database import SessionLocal
        db = SessionLocal()
        try:
            rows = db.execute(text(
                "SELECT home_team AS team, league FROM matches "
                "UNION SELECT away_team AS team, league FROM matches")).fetchall()
        finally:
            db.close()
        for r in rows:
            entry = LEAGUE_COUNTRY_TIER.get(r.league)
            if entry:
                ours_by_country.setdefault(entry[0], set()).add(r.team)
    except Exception:
        ours_by_country = {}

    # The fixture table only knows a club's country if we track its domestic
    # league. Crvena Zvezda, Ferencváros, Hajduk, Copenhagen and thirty others
    # appear in our data ONLY through CL/EL/ECL, whose "country" is the
    # competition — so they had no bucket, could never be matched inside one,
    # and sat on the floor rating while being perfectly present in ClubElo.
    #
    # The training CSVs do know: we import Serbia, Croatia, Czechia, Hungary
    # and the rest as history-only leagues precisely so these clubs have a
    # record. Same source the model trains on, so no new dependency.
    for team, league in _csv_team_leagues():
        entry = LEAGUE_COUNTRY_TIER.get(league)
        if entry:
            ours_by_country.setdefault(entry[0], set()).add(team)

    by_slug = {_slug(n): n for names in ours_by_country.values() for n in names}

    out: dict[str, float] = {}
    for name, info in clubs.items():
        elo = info.get("elo")
        if elo is None:
            continue

        hit = _CLUBELO_ALIASES.get(name) or by_slug.get(_slug(name))
        if hit is None:
            country = _FED_TO_COUNTRY.get(info.get("country") or "")
            candidates = ours_by_country.get(country or "", set())
            # Fuzzy only inside the federation. Across the whole table this
            # both costs a million difflib calls and produces the cross-country
            # collisions the country guard exists to stop.
            # UNIQUE match only. Taking the first was letting iteration order
            # decide: "Brugge" matched both Club Brugge and Cercle Brugge, and
            # whichever the set happened to yield first won the rating. Two
            # candidates means we do not know, and the alias table below is
            # where a known answer belongs.
            found = [o for o in candidates if _teams_match(name, o)]
            if len(found) == 1:
                hit = found[0]
        if hit is None:
            # Its federation has no bucket: the club appears in our data only
            # through CL/EL/ECL, whose "country" is the competition rather than
            # a nation. Crvena Zvezda, Ferencváros, Hajduk and Copenhagen are
            # all in this position, and leaving them on the floor rating is a
            # visible error on the page.
            #
            # Compare against everything, but accept ONLY a unique match. An
            # ambiguous name is exactly the case that produced Atlético Madrid
            # in Brazil, and one rating is not worth reopening that door.
            matches_all = [n for n in by_slug.values() if _teams_match(name, n)]
            if len(matches_all) == 1:
                hit = matches_all[0]

        if hit:
            out.setdefault(hit, float(elo))

    _CACHE = (time.time(), out)
    return out


def european_strength(teams: list[str]) -> dict[str, float]:
    """A rating for every team on ONE cross-league scale.

    Covered clubs get their ClubElo. Everyone else gets the same low value.

    Ordering the uncovered by our own Elo was tried and reverted: our Elo is
    wrong precisely BECAUSE it is per-pool, so ranking clubs from different
    federations with it reproduces the original bug in miniature — it put
    Lincoln Red Imps above Dinamo Zagreb, Ferencváros and Copenhagen. A flat
    value says "we do not know how these compare", which is true, instead of
    asserting an order we have no basis for.

    The value is the 15th percentile of ClubElo's own distribution: below every
    serious side, above nothing in particular. Two consequences worth being
    clear about — an uncovered European regular is understated, and uncovered
    clubs are indistinguishable from each other. Both are visible in the
    projection as a cluster of equal probabilities, which is honest about the
    uncertainty in a way that 1500-for-everyone never was.
    """
    table = clubelo_by_our_name()
    if not table:
        return {t: 1500.0 for t in teams}

    values = sorted(table.values())
    floor = values[min(len(values) - 1, int(len(values) * 0.15))]

    return {t: table.get(t, floor) for t in teams}
