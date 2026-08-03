"""
Shared API-Football → training-data team-name resolution.

One resolver for every fetcher (friendlies, CL/EL/ECL), because the failure
modes below were found the hard way and must not be re-derived per script.

Two distinct things the old per-script resolvers conflated:

1. YOUTH / RESERVE SIDES — "Fiorentina U20", "Borussia Dortmund II".
   Same club, different team. They must NEVER resolve to the senior side: doing
   so charges an U20 friendly to the first team's Elo, form and player stats.
   They keep their full API name and are priced from neutral default features.
   A fixture where BOTH sides are the same club (Fiorentina vs Fiorentina U20)
   is not a real match-up and is skipped.

2. DIFFERENT CLUBS SHARING A TOWN NAME — "Lincoln United" vs "Lincoln" (City),
   "Plymouth Parkway" vs "Plymouth" (Argyle), "Cambridge City" vs "Cambridge
   United", "Peterborough Sports" vs "Peterborough".
   The previous resolver matched by SUBSTRING CONTAINMENT ("lincoln" ⊂
   "lincolnunited"), so both sides collapsed onto one training-data name and we
   stored self-fixtures like "Lincoln vs Lincoln" — with a phantom prediction
   and corrupted club Elo. Containment is gone. The same bug mapped "Inter Club
   d'Escaldes" (Andorra) onto Inter Milan.

A similarity threshold alone does NOT protect against (1): the longer the club
name, the more a "U20" suffix disappears into the ratio —
"Borussia Dortmund II" vs "Borussia Dortmund" scores 0.94. Hence the explicit
guard, applied before any matching.

Unresolved names are kept verbatim (full API name). Wrong-but-neutral beats
confidently-wrong: confidence_for(has_history=False) already forces "low".
"""
from __future__ import annotations

import re

# Trailing token(s) marking a youth or reserve side rather than the first team.
# Anchored at the end so a club genuinely called "Union B..." can't trip it.
_YOUTH_SUFFIX = re.compile(
    r"\s+(?:"
    r"u\.?\s?\d{1,2}"          # U20, U-19, U 18
    r"|ii|iii"                  # Dortmund II
    r"|b|c"                     # Barcelona B
    r"|res(?:erves?)?"
    r"|reserve"
    r"|acad(?:emy)?"
    r"|youth"
    r"|jr|junior[s]?"
    # Women's sides — same trap as youth: a different team at the same club.
    # API-Football suffixes them " W"; other feeds spell it out. Without this,
    # a /teams?search for "SK Rapid" returned "SK Rapid W" as its only hit and
    # the id cache pointed the men's club at the women's team's match stats.
    r"|w|women|womens|ladies|feminin[ea]?|femenino|femminile|frauen"
    r")\s*$",
    re.IGNORECASE,
)


# Senior clubs whose real name ends in something the pattern above reads as a
# youth or reserve marker. Without an exception the resolver refuses to match
# them, so they never get an API id (no cards, corners or player props), and
# `same_club()` treats their fixtures as a club playing itself.
#
# Every one of these plays a first division in our history, which is how
# test_no_first_division_club_reads_as_a_reserve_side finds them: reserve sides
# are confined to second tiers, so a non-senior name in a top flight is always
# a false positive, never a real B team.
_NOT_YOUTH = {
    "willem ii",        # Eredivisie — named after King William II
    "inverness c",      # Inverness Caledonian Thistle, Scottish top flight
    "puskas academy",   # Puskás Akadémia FC — "Academy" is the club's own name
    "boca juniors",     # both the Gibraltar and the Argentine club
    "if ii",            # ÍF Fuglafjørður, 8 Faroese top-flight seasons
}


def strip_youth(name: str) -> tuple[str, bool]:
    """('Fiorentina U20') → ('Fiorentina', True). Idempotent for senior sides."""
    if (name or "").strip().lower() in _NOT_YOUTH:
        return name, False
    stripped = _YOUTH_SUFFIX.sub("", name).strip()
    if stripped and stripped != name:
        return stripped, True
    return name, False


def is_youth_side(name: str) -> bool:
    return strip_youth(name)[1]


def same_club(home: str, away: str) -> bool:
    """True when both sides are the same club (first team vs its own U20/B side).

    Not a real match-up: identical features on both sides, so any prediction is
    pure home-advantage noise and the club's Elo would update against itself.
    """
    from backend.app.ml.odds_analysis_service import _slug

    return _slug(strip_youth(home)[0]) == _slug(strip_youth(away)[0])


# ── The one place fixtures are checked against the training data ──────────────

def known_team_names() -> frozenset[str]:
    """Team names as they appear in the training CSVs — the canonical spelling.

    Elo, form and every rolling feature are keyed on these, so a fixture stored
    under any other spelling is invisible to the model. Cached; the CSVs don't
    change within a run.
    """
    import os

    from backend.app.ml.features import load_raw_csvs

    global _KNOWN_CACHE
    if _KNOWN_CACHE is None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        h = load_raw_csvs(os.path.join(root, "backend", "data", "raw"))
        _KNOWN_CACHE = frozenset(set(h["home_team"]) | set(h["away_team"]))
    return _KNOWN_CACHE


_KNOWN_CACHE: frozenset[str] | None = None


def warn_unknown_teams(fixtures: list[dict], *, domestic: bool) -> set[str]:
    """Print a warning for every fixture team missing from the training data and
    return the offending names.

    A DOMESTIC-league team that isn't in the CSVs is almost always a name we
    failed to map (the "Bayer Leverkusen"/"AC Milan" phantom-team bug): it gets
    default features (Elo 1500, junk prediction) and splits the real club's
    record. For cup fetchers (`domestic=False`) an unknown is usually a genuine
    minnow we have no history for, so it's reported quietly as an FYI, not a bug.
    """
    known = known_team_names()
    fixture_teams = {
        t for f in fixtures for t in (f.get("home_team"), f.get("away_team")) if t
    }
    unknown = {t for t in fixture_teams if t not in known}
    if unknown:
        tag = "[warn]" if domestic else "[info]"
        why = ("not in training data — likely an unmapped name; add it to TEAM_MAP"
               if domestic else "no training history — will use default features")
        sample = ", ".join(sorted(unknown)[:20])
        print(f"  {tag} {len(unknown)} unresolved team(s) — {why}: {sample}"
              + (" …" if len(unknown) > 20 else ""))

    # Membership alone misses the subtler phantom: a name that IS in the CSVs but
    # holds almost no history, while a near-identical name holds the club's real
    # record ("OFI" 1 match vs "OFI Crete" 97). That still yields default
    # features, just without tripping the check above.
    if domestic:
        thin = _thin_duplicates(fixture_teams - unknown, known)
        if thin:
            pairs = ", ".join(f"{a!r}→{b!r}" for a, b in sorted(thin)[:10])
            print(f"  [warn] {len(thin)} team(s) look like a thin duplicate of an "
                  f"existing club — add to COMMON_ALIASES: {pairs}")
            unknown |= {a for a, _ in thin}
    return unknown


def _thin_duplicates(names: set[str], known: set[str]) -> set[tuple[str, str]]:
    """{(thin_name, fat_name)} for names whose near-twin has far more history."""
    from difflib import SequenceMatcher

    from backend.app.ml.odds_analysis_service import _slug

    counts = _csv_match_counts()
    out: set[tuple[str, str]] = set()
    for n in names:
        n_hist = counts.get(n, 0)
        if n_hist > 20:                      # a well-established name is not thin
            continue
        for other in known:
            if other == n or counts.get(other, 0) < 20:
                continue
            a, b = _slug(n), _slug(other)
            if a and (a in b or SequenceMatcher(None, a, b).ratio() > 0.85):
                out.add((n, other))
                break
    return out


def _csv_match_counts() -> dict[str, int]:
    """{team: matches in the training CSVs} — how much history a name really has."""
    import os

    from backend.app.ml.features import load_raw_csvs

    global _COUNTS_CACHE
    if _COUNTS_CACHE is None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        h = load_raw_csvs(os.path.join(root, "backend", "data", "raw"))
        c: dict[str, int] = {}
        for col in ("home_team", "away_team"):
            for team, n in h[col].value_counts().items():
                c[team] = c.get(team, 0) + int(n)
        _COUNTS_CACHE = c
    return _COUNTS_CACHE


_COUNTS_CACHE: dict[str, int] | None = None


# Cross-source aliases: API spelling → our CSV name. Every fetcher's resolver
# falls back to these, because the same club is spelled differently by
# football-data.org, The Odds API and API-Football, and fixing it in one
# fetcher's private map left the others generating phantom teams.
#
# Only entries where the club VERIFIABLY exists in the training CSVs under the
# target name. A club we genuinely have no history for (Le Mans, Academico
# Viseu, Kalamata — newly promoted or lower-division) belongs nowhere in here:
# it keeps its own name and is priced from default features, which is honest.
# Mapping it onto a similar-looking club would be far worse.
#
# "Verifiably" means grepping the CSVs for the club, NOT for the feed's
# spelling of it — see the Elversberg entry below for what the weaker check
# costs.
COMMON_ALIASES: dict[str, str] = {
    # ── 2026-08-03: promoted side whose CSV name carries a legal-form affix ──
    #
    # Elversberg was listed above, for three months, as a club we have no
    # history for. We have 102 matches of it — the 2. Bundesliga CSVs file it
    # as "SV Elversberg", and only the bare feed spelling was ever searched
    # for. Promotion then put it in the Bundesliga under the bare name, with
    # 1500 Elo and default features: Schalke 04 vs Elversberg priced
    # 0.378/0.304/0.319, a promoted side reading as mid-table.
    #
    # build_resolver() bridges this pair unaided (rule 4, spelling drift), but
    # fetch_upcoming.py — the only fixture writer that resolved through
    # canonical() alone — never ran it. That gap is closed there too, so the
    # next promoted "SV/1. FC/VfL <town>" doesn't need its own line here.
    "Elversberg": "SV Elversberg",

    # ── 2026-08-03: fixture-feed spellings that had no CSV counterpart ───────
    #
    # Found by asking what each stored name would be PRINTED as: seven pairs
    # collapsed onto one label, which meant the database was already holding
    # the same club twice — once under our ASCII training-data name and once
    # under the feed's accented one. The second copy carries no history at all,
    # so a European tie priced off it ran on default features.
    #
    # Direction is feed spelling → the name the CSVs use, as everywhere here.
    "Egnatia Rrogozhinë": "Egnatia Rrogozhine",
    "Hradec Králové": "Hradec Kralove",
    "Kauno Žalgiris": "Kauno Zalgiris",
    "Rīgas FS": "Rigas FS",
    "Çorum FK": "Corum FK",
    "Sporting CP": "Sp Lisbon",
    # Glasgow Rangers. Andorra's FC Ranger's is renamed at the source
    # (league_registry.NAME_DISAMBIGUATION), so this spelling is unambiguous.
    "Ranger's": "Rangers",
    # Fixture-feed short form; the CSVs have always said NAC Breda.
    "NAC": "NAC Breda",

    # ── 2026-07-30 league expansion (Belgium, Turkey, Scotland, Denmark,
    # Sweden, Norway, Poland, Austria, Switzerland, Romania, Ireland, Finland).
    # These live here rather than in the fetcher that needed them first: the
    # SAME club arrives from the domestic feed and from the European one, and a
    # fetcher-local map left "Hearts" and "Heart Of Midlothian" as two clubs.
    # Checked against each league's own CSV team list. Two pairs are left
    # deliberately uncollapsed because they are different clubs that read alike:
    # Romania's "Univ. Craiova" vs "U Craiova 1948", Poland's "Wisla" (Kraków)
    # vs "Wisla Plock". Newly promoted sides with no history (Lommel, SK
    # Beveren, Amed, Erzurumspor, Çorum) stay unmapped on purpose.
    # Belgium
    "KVC Westerlo": "Westerlo", "OH Leuven": "Oud-Heverlee Leuven",
    "Standard Liege": "Standard", "Union St. Gilloise": "St. Gilloise",
    "Zulte Waregem": "Waregem",
    # Turkey — the CSV still files Başakşehir under its old municipal name
    "Başakşehir": "Buyuksehyr",
    # Accents and legal-form prefixes the European feed carries but the CSVs
    # don't. These MUST live here and not only in features._SNAP_NAME_MAP: the
    # snapshot map fixes the model's lookup, but leaves the DB holding two
    # spellings of one club, which is two fixtures and two cards on the site.
    # Greek feeds disagree on the suffix, which had Kalamata in the DB twice.
    "Kalamata FC": "Kalamata",
    # Abbreviation, not an affix — the rule can't bridge "Acad." → "Academico".
    "Acad. Viseu": "Academico Viseu",
    "Beşiktaş": "Besiktas", "Fenerbahçe": "Fenerbahce",
    "FC Midtjylland": "Midtjylland", "FC Nordsjaelland": "Nordsjaelland",
    "FC ST. Gallen": "St. Gallen", "FC Vaduz": "Vaduz",
    # "Gais" → "GAIS" removed 2026-08-03: the Sweden2 import made "Gais" the
    # fatter spelling, features._CSV_TEAM_CANON folds GAIS into it, and the
    # alias now pointed at a name the CSVs no longer hold.
    "Hammarby FF": "Hammarby",
    # Scotland
    "Dundee Utd": "Dundee United", "Heart Of Midlothian": "Hearts",
    # Sweden
    "AIK Stockholm": "AIK", "Djurgardens IF": "Djurgarden",
    "IFK Goteborg": "Goteborg", "Mjallby AIF": "Mjallby",
    # Poland
    "Cracovia Krakow": "Cracovia", "Legia Warszawa": "Legia",
    "Raków Częstochowa": "Rakow", "Wisla Krakow": "Wisla",
    "Zaglebie Lubin": "Zaglebie",
    # Austria — WSG Wattens renamed itself WSG Tirol
    "Austria Lustenau": "A. Lustenau", "Lask Linz": "LASK",
    "Rapid Vienna": "SK Rapid", "Red Bull Salzburg": "Salzburg",
    "SCR Altach": "Altach", "WSG Wattens": "Tirol",
    "TSV Hartberg": "Hartberg",
    # Switzerland
    "BSC Young Boys": "Young Boys", "FC Sion": "Sion", "FC Thun": "Thun",
    # Romania
    "Arges Pitesti": "FC Arges", "CFR 1907 Cluj": "CFR Cluj",
    # "Corvinul Hunedoara" → "Corvinul" removed 2026-08-03: the Romania2 import
    # brought 86 rows under the full name, so it is now the canonical one and
    # the feed spelling needs no alias at all.
    "Csikszereda": "Csikszereda M. Ciuc",
    "Petrolul Ploiesti": "Petrolul", "Rapid": "FC Rapid Bucuresti",
    "Sepsi OSK Sfantu Gheorghe": "Sepsi Sf. Gheorghe",
    "Universitatea Cluj": "U. Cluj", "Universitatea Craiova": "Univ. Craiova",
    # Ireland
    "Drogheda United": "Drogheda", "Galway United": "Galway",
    "St Patrick's Athl.": "St. Patricks",
    # Finland
    "HJK Helsinki": "HJK", "Turku PS": "TPS", "FF Jaro": "Jaro",
    # Portugal
    "Braga":              "Sp Braga",
    "SC Braga":           "Sp Braga",
    "CD Nacional":        "Nacional",
    "Marítimo":           "Maritimo",
    "Vitoria SC":         "Vitoria",
    "Amadora":            "Estrela",          # Estrela da Amadora
    # Spain
    "Málaga":             "Malaga",
    "Deportivo":          "La Coruna",        # Deportivo La Coruña
    # Germany
    "Schalke":            "Schalke 04",
    "SC Paderborn":       "SC Paderborn 07",   # canonical since 2026-08-02
    # Netherlands
    "NEC Nijmegen":       "Nijmegen",
    "Go Ahead":           "Go Ahead Eagles",
    "Sittard":            "For Sittard",      # Fortuna Sittard
    "Sparta":             "Sparta Rotterdam",
    # Greece — three feeds, three spellings of the same four clubs
    "AEK Athens":         "AEK",
    "AEK Athens FC":      "AEK",
    "Olympiakos Piraeus": "Olympiakos",
    "Aris Thessaloniki":  "Aris",
    "Aris Thessalonikis": "Aris",
    "PAOK Thessaloniki":  "PAOK",
    "Iraklis FC":         "Iraklis 1908",      # canonical since 2026-08-02
    "Volos NPS":          "Volos NFC",
    # ⚠ "OFI" is ALSO in the CSVs (1 match) while "OFI Crete" holds the club's
    # real 97-match history — so the membership guard could not see it was a
    # duplicate. Pin the thin spelling onto the fat one.
    "OFI":                "OFI Crete",
}


_ALIAS_CACHE: dict[str, str] | None = None


def alias_map() -> dict[str, str]:
    """`COMMON_ALIASES` plus every spelling `_CSV_TEAM_CANON` folds away.

    Both tables answer "which club is this string", and the fixture side needs
    both. When "Bochum" and "Vfl Bochum" were merged in the training data,
    `known_team_names()` — which loads the CSVs through the canonicaliser —
    stopped containing "Bochum", so the fixture feed's "Bochum" resolved to
    nothing and its next match would have rendered as an insufficient-data
    card. Every merge has that effect on whichever spelling loses.

    COMMON_ALIASES wins on a conflict: it is curated per feed, while the canon
    table only knows what the CSVs contain.
    """
    global _ALIAS_CACHE
    if _ALIAS_CACHE is None:
        from backend.app.ml.features import _CSV_TEAM_CANON
        _ALIAS_CACHE = {**_CSV_TEAM_CANON, **COMMON_ALIASES}
    return _ALIAS_CACHE


def canonical(name: str) -> str:
    """The single spelling the training data uses for this club."""
    return alias_map().get((name or "").strip(), name)


# Legal / corporate affixes that decorate a club name without changing which
# club it is: "1. FC Heidenheim" is Heidenheim, "SC Freiburg" is Freiburg.
# Containment is only accepted when everything left over after removing our
# known name consists of these (or digits).
# Deliberately excludes words that IDENTIFY a club rather than decorate it —
# "real", "athletic", "club", "united", "city", "sports" — because "Real
# Madrid" and "Madrid CF" are not the same club.
_AFFIXES = {
    "fc", "afc", "cfc", "sc", "ac", "cf", "cd", "ud", "sd", "rc", "rcd",
    "sv", "tsv", "tsg", "vfb", "vfl", "vfr", "fsv", "msv", "spvgg", "borussia",
    "ssc", "ss", "as", "ogc", "osc", "losc", "calcio",
    "fk", "sk", "nk", "hnk", "bk", "if", "ik", "gks", "mfk", "cp",
    # Nordic club affixes — added with the 2026-07-30 league expansion.
    # "ff" = Fotbollsförening (Hammarby FF), "ifk" = Idrottsföreningen
    # Kamraterna (IFK Göteborg). Both are legal-form noise, never the club.
    "ff", "ifk",
}


def _leftover_is_affixes_only(leftover: str) -> bool:
    """True when what remains is just corporate noise ("1fc", "sc", "1899").

    "united", "city", "parkway", "sports", "redimpsfc" are NOT affixes — they
    name a DIFFERENT club that merely shares a town with one of ours.
    """
    rest = leftover
    changed = True
    while rest and changed:
        changed = False
        if rest.isdigit():
            return True
        for a in _AFFIXES:
            if rest.startswith(a):
                rest, changed = rest[len(a):], True
                break
            if rest.endswith(a):
                rest, changed = rest[: -len(a)], True
                break
        if not changed:
            # strip a leading/trailing digit run ("1899hoffenheim" → "1899")
            stripped = rest.lstrip("0123456789").rstrip("0123456789")
            if stripped != rest:
                rest, changed = stripped, True
    return rest == ""


def build_resolver(known_teams: set[str], team_map: dict[str, str] | None = None):
    """API-Football club name → our training-data name, or None.

    Accepts: an explicit `team_map` entry, an exact slug, a curated alias,
    affix-only containment, or near-identical spelling ("Bayern München" →
    "Bayern Munich"). Youth/reserve sides never resolve.
    """
    from difflib import SequenceMatcher

    from backend.app.ml.odds_analysis_service import _ALIASES, _slug

    # Caller's map wins over the shared aliases (a fetcher may know that its
    # feed means something different by the same string), but every caller
    # inherits COMMON_ALIASES so one source's fix covers the others too.
    team_map = {**alias_map(), **(team_map or {})}
    slug_to_name = {_slug(t): t for t in known_teams}
    cache: dict[str, str | None] = {}

    def _resolve(api_name: str) -> str | None:
        # (1) Youth/reserve sides are a different team — never the senior club.
        if is_youth_side(api_name):
            return None
        if api_name in team_map:
            return team_map[api_name]
        api_slug = _slug(api_name)
        if api_slug in slug_to_name:
            return slug_to_name[api_slug]

        scored: list[tuple[float, str]] = []
        for team in known_teams:
            team_slug = _slug(team)
            best = 0.0
            # (2) Containment, but ONLY when the remainder is corporate noise.
            #     "1fcheidenheim" − "heidenheim" = "1fc"      → same club.
            #     "lincolnunited" − "lincoln"    = "united"   → other club.
            #     Guarded at ≥5 chars so "aek"/"roma" can't hijack a longer name.
            if len(team_slug) >= 5 and team_slug in api_slug:
                if _leftover_is_affixes_only(api_slug.replace(team_slug, "", 1)):
                    best = max(best, 50.0 + len(team_slug))
            # (3) Curated aliases ("olympiquelyonnais" → Lyon).
            for alias in _ALIASES.get(team, []):
                if len(alias) >= 5 and alias in api_slug:
                    best = max(best, 50.0 + len(alias))
            # (4) Spelling drift ("Espanyol" vs "Espanol").
            ratio = SequenceMatcher(None, api_slug, team_slug).ratio()
            if ratio >= 0.87:
                best = max(best, 40.0 + ratio * 10)
            if best > 0:
                scored.append((best, team))

        if not scored:
            return None
        scored.sort(reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            print(f"  [warn] '{api_name}' ambiguous between "
                  f"'{scored[0][1]}' and '{scored[1][1]}' — skipped. "
                  f"Add it to the caller's TEAM_MAP.")
            return None
        return scored[0][1]

    def resolve(api_name: str) -> str | None:
        if api_name not in cache:
            cache[api_name] = _resolve(api_name)
        return cache[api_name]

    return resolve
