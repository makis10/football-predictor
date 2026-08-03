"""Do our team names line up with each other, and with the ids we store?

Team identity in this project is a STRING, spelled differently by every feed:
football-data.co.uk, The Odds API, API-Football and our own CSVs all disagree.
Six tables bridge them. Nothing checked that they agree, and every one of these
assertions is a defect that reached production:

  · one club filed under two names, splitting its Elo and form in half
  · two of our names pointing at the same API team, only one of them right
  · an alias resolving a senior club onto its women's or reserve side
  · a cached id belonging to a same-named club in another country

Offline: CSVs and JSON only, so CI runs it on every push. The wrong-country
check needs live rosters and lives in fetch_club_team_stats' own guard.
"""
from __future__ import annotations

import collections
import json
import os
import re
import unicodedata

import pytest

from backend.app.ml.club_props import NAME_OVERRIDES
from backend.app.ml.features import _CSV_TEAM_CANON, _SNAP_NAME_MAP, load_raw_csvs
from scripts.team_resolver import COMMON_ALIASES, is_youth_side

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RAW = os.path.join(_ROOT, "backend", "data", "raw")
_ID_CACHE = os.path.join(_ROOT, "backend", "data", "models", "club_team_ids.json")


def _slug(s: str) -> str:
    ascii_s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_s.lower())


@pytest.fixture(scope="module")
def csv_teams() -> set[str]:
    if not os.path.isdir(_RAW):
        pytest.skip("no raw CSV directory in this checkout")
    df = load_raw_csvs(_RAW)
    return set(df["home_team"].dropna()) | set(df["away_team"].dropna())


@pytest.fixture(scope="module")
def id_cache() -> dict:
    if not os.path.isfile(_ID_CACHE):
        pytest.skip("club_team_ids.json not present (no ingestion run yet)")
    return {k: v for k, v in json.load(open(_ID_CACHE)).items() if v}


# ── One club, one name ────────────────────────────────────────────────────────

def test_no_club_is_filed_under_two_names_with_the_same_id(id_cache, csv_teams):
    """Two of OUR names sharing an API id means one club split in two.

    Found five live on 2026-08-02: Stuttgart/VfB Stuttgart (106 matches vs 3),
    Como/como, Espanol/Espanyol, FC Koln/1. FC Koln, Nijmegen/NEC Nijmegen. The
    thin side is a phantom — near-default features, its own Elo, and it takes
    real matches away from the club's actual record.

    A pair is only a problem when BOTH names carry history; a fixture-feed
    spelling that never reached the CSVs is handled by the alias tables.
    """
    by_id: dict[int, list[str]] = collections.defaultdict(list)
    for team, tid in id_cache.items():
        by_id[tid].append(team)

    canon = {**_CSV_TEAM_CANON}
    split = []
    for tid, names in by_id.items():
        # Names the canonicaliser already collapses are not a split.
        distinct = {canon.get(n, n) for n in names}
        if len(distinct) < 2:
            continue
        with_history = [n for n in distinct if n in csv_teams]
        if len(with_history) > 1:
            split.append((tid, sorted(with_history)))
    assert not split, (
        "one club under two names, both with CSV history — add the thin one to "
        f"features._CSV_TEAM_CANON: {split}")


def test_canonicalisation_targets_are_real_teams(csv_teams):
    """`_CSV_TEAM_CANON` must fold onto a name the history actually uses."""
    missing = {src: dst for src, dst in _CSV_TEAM_CANON.items() if dst not in csv_teams}
    assert not missing, f"canonical target absent from the CSVs: {missing}"


def test_canonicalisation_folds_thin_into_fat_not_the_reverse(csv_teams):
    """Direction matters: collapsing the well-populated name into the sparse one
    would throw away the history instead of merging it."""
    if not _CSV_TEAM_CANON:
        pytest.skip("nothing to canonicalise")
    df = load_raw_csvs(_RAW)
    counts = collections.Counter()
    for col in ("home_team", "away_team"):
        counts.update(df[col].dropna())
    backwards = {
        src: (counts.get(src, 0), dst, counts.get(dst, 0))
        for src, dst in _CSV_TEAM_CANON.items()
        # counts here are POST-canonicalisation, so the source should be gone.
        if counts.get(src, 0) > counts.get(dst, 0)
    }
    assert not backwards, f"canonicalising the fat name into the thin one: {backwards}"


# ── Alias hygiene ─────────────────────────────────────────────────────────────

def test_no_alias_resolves_onto_a_youth_reserve_or_womens_side():
    """Their stats would be charged to the first team's cards and corners."""
    bad = {src: dst
           for src, dst in {**COMMON_ALIASES, **NAME_OVERRIDES, **_SNAP_NAME_MAP}.items()
           if is_youth_side(dst) and not is_youth_side(src)}
    assert not bad, f"alias points at a non-senior side: {bad}"


def test_every_override_is_for_a_club_we_actually_see(csv_teams):
    """`NAME_OVERRIDES` keys must be names we really use.

    (There is deliberately NO round-trip check against COMMON_ALIASES. They
    answer different questions: COMMON_ALIASES bridges EVERY feed's spelling —
    The Odds API, football-data.org, API-Football — onto our CSV name, while
    NAME_OVERRIDES maps our name onto API-Football's /teams spelling
    specifically. "Braga"→"Sp Braga"→"SC Braga" is three correct names for one
    club, not a contradiction, and asserting they round-trip fails on healthy
    data.)
    """
    known = set(csv_teams) | set(COMMON_ALIASES.values()) | set(_CSV_TEAM_CANON.values())
    stale = sorted(k for k in NAME_OVERRIDES if k not in known)
    # Fixture feeds legitimately introduce names before any CSV carries them
    # (a newly promoted club), so this is a smell, not a hard failure.
    assert len(stale) < 15, (
        f"{len(stale)} NAME_OVERRIDES entries reference clubs that appear "
        f"nowhere in our data — likely stale: {stale[:15]}")


def test_no_alias_is_a_no_op():
    """A key equal to its value is dead weight that hides a real gap."""
    for name, table in (("COMMON_ALIASES", COMMON_ALIASES),
                        ("NAME_OVERRIDES", NAME_OVERRIDES),
                        ("_SNAP_NAME_MAP", _SNAP_NAME_MAP),
                        ("_CSV_TEAM_CANON", _CSV_TEAM_CANON)):
        noop = {k for k, v in table.items() if k == v}
        # NAME_OVERRIDES deliberately pins a few identities so the search
        # fallback cannot wander ("Inter", "Wolves", "Ipswich", "PAOK").
        if name == "NAME_OVERRIDES":
            continue
        assert not noop, f"{name} has self-mapping entries: {sorted(noop)}"


def test_snapshot_map_targets_exist_in_the_history(csv_teams):
    """`_SNAP_NAME_MAP` exists to reach the Elo snapshot; a target that isn't in
    the CSVs silently leaves the club unrated."""
    missing = {src: dst for src, dst in _SNAP_NAME_MAP.items() if dst not in csv_teams}
    assert not missing, (
        f"_SNAP_NAME_MAP target not in the training data: {missing}")


# ── Cached ids ────────────────────────────────────────────────────────────────

def test_cached_ids_are_plausible(id_cache):
    """Positive integers, and no team mapped to null.

    A null used to be cached for unresolved teams, which permanently blocked
    re-resolution — the Greek league outage of 2026-07-11.
    """
    bad = {t: i for t, i in id_cache.items() if not isinstance(i, int) or i <= 0}
    assert not bad, f"implausible team ids: {bad}"


def test_clubs_we_model_have_an_id(csv_teams, id_cache):
    """Spot-check that the big clubs resolved.

    Not exhaustive — a club with no upcoming fixture is legitimately absent —
    but if these are missing the cache has been truncated, which `--refresh-ids`
    used to do silently (530 entries → 303).
    """
    big = ["Man City", "Arsenal", "Real Madrid", "Barcelona", "Bayern Munich",
           "Juventus", "Paris SG", "Olympiakos"]
    present = [t for t in big if t in csv_teams]
    if len(present) < 4:
        pytest.skip("training data does not contain the reference clubs")
    missing = [t for t in present if t not in id_cache]
    assert len(missing) <= len(present) // 2, (
        f"most reference clubs have no cached id ({missing}) — cache truncated?")


# ── Country disambiguation ────────────────────────────────────────────────────

def test_every_predicted_league_has_a_country():
    """The search fallback needs a country to disambiguate a bare club name.

    "Porto" is a club in Brazil as well as Portugal, "Milan" one in Gambia,
    "Roma" one in Slovenia, "Lugano" one in Argentina — all four were accepted
    into the id cache before the country check existed.
    """
    from backend.app.ml.features import ONE_HOT_LEAGUES
    from backend.app.ml.odds_analysis_service import LEAGUE_COUNTRY

    missing = [lg for lg in ONE_HOT_LEAGUES if lg not in LEAGUE_COUNTRY]
    assert not missing, (
        f"leagues with no country — their clubs cannot be disambiguated: {missing}")


def test_european_cups_have_no_country():
    """CL/EL/ECL draw clubs from everywhere; pinning a country would reject
    every legitimate result."""
    from backend.app.ml.odds_analysis_service import LEAGUE_COUNTRY

    for cup in ("CL", "EL", "ECL"):
        assert cup not in LEAGUE_COUNTRY, f"{cup} must not be country-restricted"


def test_senior_clubs_named_like_a_reserve_side_are_not_misread():
    """Willem II is an Eredivisie FIRST team, named after King William II.

    The youth/reserve pattern reads a trailing "II" as a second string, so
    without an explicit exception the resolver refuses to match the club and
    `same_club()` treats a Willem II fixture as a club playing itself.
    """
    assert not is_youth_side("Willem II")
    # …while the genuine reserve sides must still be caught.
    for reserve in ("Real Sociedad II", "Sporting CP B", "Barcelona B",
                    "SK Rapid W", "Flamengo RJ U17"):
        assert is_youth_side(reserve), f"{reserve} should read as a non-senior side"


# Second tiers are the only divisions that admit B teams — Portugal2 alone
# fields five of them. Everywhere else a reserve marker is a misread name.
_SECOND_TIERS = frozenset({
    "Championship", "LeagueOne", "Greece2", "GreeceFL", "Turkey2", "Belgium2",
    "Germany2", "France2", "Portugal2", "Spain2", "Italy2", "Netherlands2",
})


def test_no_first_division_club_reads_as_a_reserve_side():
    """A top-flight club is never anybody's second string.

    Enumerating exceptions by hand does not scale — every new league brings its
    own. This derives them: a name playing a FIRST division cannot be a reserve
    side, so anything the pattern flags there is a false positive, and the club
    silently loses its API id, its cards and corners, and its player props.

    Four were live on 2026-08-02, one of them in a league we predict:
    Inverness C (Inverness Caledonian Thistle, Scotland — 266 appearances),
    Puskas Academy (Hungary, 332), Boca Juniors (Gibraltar), IF II
    (ÍF Fuglafjørður, 8 Faroese seasons). Add real ones to
    `team_resolver._NOT_YOUTH`.
    """
    import csv
    import glob

    if not os.path.isdir(_RAW):
        pytest.skip("no raw CSV directory in this checkout")

    offenders: dict[str, set[str]] = collections.defaultdict(set)
    for path in glob.glob(os.path.join(_RAW, "*.csv")):
        league = os.path.basename(path).rsplit("_", 1)[0]
        if league in _SECOND_TIERS:
            continue
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            cols = reader.fieldnames or []
            home = "home_team" if "home_team" in cols else "HomeTeam"
            away = "away_team" if "away_team" in cols else "AwayTeam"
            if home not in cols or away not in cols:
                continue
            for row in reader:
                for team in (row.get(home), row.get(away)):
                    # load_raw_csvs strips; a handful of CSV rows carry a
                    # trailing space and would otherwise show up here.
                    team = (team or "").strip()
                    if team and is_youth_side(team):
                        offenders[league].add(team)

    assert not offenders, (
        "clubs playing a first division read as reserve/youth sides — add the "
        f"real ones to team_resolver._NOT_YOUTH: {dict(sorted(offenders.items()))}")


# ── One club, or two? ─────────────────────────────────────────────────────────
#
# The checks below run the rule in scripts/audit_team_identity.py: two spellings
# are one club unless they played each other, sit in different countries, each
# played a full season in one table, or were in different divisions at once.

@pytest.fixture(scope="module")
def corpus():
    if not os.path.isdir(_RAW):
        pytest.skip("no raw CSV directory in this checkout")
    from scripts.audit_team_identity import Corpus
    return Corpus(_RAW)


def test_no_merge_fuses_two_different_clubs(corpus):
    """Every canonicalisation must survive the rule.

    Merging two real clubs is the expensive mistake: their match histories and
    Elo ratings fuse permanently, and nothing downstream can tell them apart
    again. Splitting one club is recoverable by comparison.
    """
    wrong = {}
    for src, dst in _CSV_TEAM_CANON.items():
        if src not in corpus.where or dst not in corpus.where:
            continue          # a fixture-feed spelling with no CSV history
        same, why = corpus.verdict(src, dst)
        if not same:
            wrong[f"{src} → {dst}"] = why
    assert not wrong, f"_CSV_TEAM_CANON merges names the data says are two clubs: {wrong}"


def test_no_team_name_belongs_to_two_countries(corpus):
    """One string holding two clubs fuses their ratings.

    "Arsenal" was Arsenal FC and FC Arsenal Dzerzhinsk of Belarus; "Olympiakos"
    was Olympiacos Piraeus and Olympiakos Nicosia. Both are clubs we serve
    predictions for, and both were running on a rating that included a foreign
    club's results.
    """
    collisions = corpus.collisions()
    assert not collisions, (
        "these names each cover two clubs in two countries — rename the "
        f"smaller side in its league's CSVs: {collisions}")


def test_every_league_file_maps_to_a_country_and_tier(corpus):
    """A league missing from the registry is invisible to the rule above, so
    its clubs can be merged or collide unchecked."""
    assert not corpus.unmapped, (
        f"CSV leagues absent from LEAGUE_COUNTRY_TIER: {sorted(corpus.unmapped)}")


def test_the_two_country_maps_agree():
    """`LEAGUE_COUNTRY` drives the API-Football search, `LEAGUE_COUNTRY_TIER`
    the identity audit. They are separate because they answer different
    questions, but where they overlap they must not disagree."""
    from backend.app.ml.league_registry import LEAGUE_COUNTRY_TIER
    from backend.app.ml.odds_analysis_service import LEAGUE_COUNTRY

    clash = {lg: (c, LEAGUE_COUNTRY_TIER[lg][0])
             for lg, c in LEAGUE_COUNTRY.items()
             if lg in LEAGUE_COUNTRY_TIER and LEAGUE_COUNTRY_TIER[lg][0] != c}
    assert not clash, f"the two country maps disagree: {clash}"
    missing = sorted(set(LEAGUE_COUNTRY) - set(LEAGUE_COUNTRY_TIER))
    assert not missing, f"predicted leagues absent from the registry: {missing}"


def test_team_names_survived_their_csv_encoding(corpus):
    """`load_raw_csvs` decodes every league CSV as latin-1, so a file written
    in UTF-8 arrives mangled: "Pietà Hotspurs" becomes "PietÃ  Hotspurs", which
    slugs to something no fixture will ever match, and the club splits in two.

    football-data.co.uk has begun publishing UTF-8 for the current seasons —
    harmless so far only because its club names happen to be plain ASCII. The
    day one carries an accent this fires.
    """
    mangled = sorted(n for n in corpus.names
                     if "Ã" in n or "Â" in n or "�" in n)
    assert not mangled, (
        "club names mangled by a UTF-8 file read as latin-1 — re-encode the "
        f"source CSV, or teach load_raw_csvs to sniff the codec: {mangled}")


# ── What the reader sees ──────────────────────────────────────────────────────

def _identities(corpus) -> set[str]:
    """The names a club can actually be stored under, after canonicalisation.

    `Corpus` reads the raw CSVs, so it still holds every pre-merge spelling —
    "ADO Den Haag" as well as "Den Haag". Those are not separate clubs and must
    not be treated as ones a display name could collide with.
    """
    def resolve(name: str) -> str:
        seen = {name}
        while name in _CSV_TEAM_CANON:
            name = _CSV_TEAM_CANON[name]
            if name in seen:
                break
            seen.add(name)
        return name

    return {resolve(n) for n in corpus.names}


def test_no_two_clubs_are_printed_under_the_same_name(corpus):
    """Display names must stay one-to-one with stored names.

    The map exists because the stored string is a join key, not a label. If two
    keys resolved to one label the site would show two different clubs as the
    same club — worse than the ugly spelling it fixes, and invisible in the
    data. Building this map is what exposed seven real cases: the database was
    holding "Corum FK" and "Çorum FK", "Sp Lisbon" and "Sporting CP", as
    separate clubs.
    """
    from backend.app.display_names import DISPLAY_NAMES, display_name

    seen: dict[str, str] = {}
    clash = {}
    for stored in sorted(_identities(corpus) | set(DISPLAY_NAMES)):
        shown = display_name(stored)
        if shown in seen and seen[shown] != stored:
            clash.setdefault(shown, [seen[shown]]).append(stored)
        seen.setdefault(shown, stored)
    assert not clash, f"two stored names print identically: {clash}"


def test_a_display_name_is_never_another_clubs_stored_name(corpus):
    """Renaming "Aris" to "Aris Thessaloniki" is safe only while no other club
    is stored under that second string; otherwise the label points at a club
    the row is not about."""
    from backend.app.display_names import DISPLAY_NAMES

    stored = _identities(corpus)
    bad = {src: dst for src, dst in DISPLAY_NAMES.items()
           if dst in stored and dst != src}
    assert not bad, f"display name is another stored club: {bad}"


def test_display_map_has_no_dead_or_empty_entries():
    from backend.app.display_names import DISPLAY_NAMES

    noop = {k for k, v in DISPLAY_NAMES.items() if k == v or not v.strip()}
    assert not noop, f"entries that change nothing: {sorted(noop)}"


def test_reserve_sides_stay_separate_from_their_first_team(id_cache):
    """The B teams we keep must never share an id with the senior club.

    We hold their history on purpose — Portugal2 and Spain2 are in
    `HISTORY_ONLY_LEAGUES`, and dropping FC Porto B or Real Sociedad II would
    take a quarter of those divisions' matches away from the senior clubs they
    played against. What must not happen is the two collapsing into one: the
    B side's results would land on the first team's Elo, and its cards and
    corners would be served on the first team's card.
    """
    by_id: dict[int, list[str]] = collections.defaultdict(list)
    for team, tid in id_cache.items():
        by_id[tid].append(team)

    merged = {tid: names for tid, names in by_id.items()
              if any(is_youth_side(n) for n in names)
              and any(not is_youth_side(n) for n in names)}
    assert not merged, f"a reserve side shares an API id with a senior club: {merged}"

    folded = {src: dst for src, dst in {**_CSV_TEAM_CANON, **_SNAP_NAME_MAP}.items()
              if is_youth_side(src) != is_youth_side(dst)}
    assert not folded, f"a reserve side is canonicalised onto a senior club: {folded}"
