"""Where each league is played, and at what level.

Two questions in this project need this and nothing else answers them:

  · WHICH COUNTRY — a bare club name is not unique in the world. "Porto" is a
    club in Brazil as well as Portugal, "Arsenal" one in Belarus as well as
    England. `odds_analysis_service.LEAGUE_COUNTRY` uses the same fact to
    disambiguate an API-Football search; this table extends it to the
    history-only leagues, which the search never touches but the training data
    very much does.

  · WHICH TIER — reserve sides ("Benfica B", "PAOK II") play second tiers only.
    A club appearing in two tiers in one season is therefore two teams, while
    the same club appearing in two tiers across seasons is just promotion.
    That distinction decides every merge in `features._CSV_TEAM_CANON`.

`scripts/audit_team_identity.py` runs the rule; `test_team_name_mapping.py`
asserts it stays true.
"""
from __future__ import annotations

# league key → (country, tier). Tier 1 is the top flight.
LEAGUE_COUNTRY_TIER: dict[str, tuple[str, int]] = {
    # predicted
    "EPL": ("England", 1), "Championship": ("England", 2), "LeagueOne": ("England", 3),
    "LaLiga": ("Spain", 1), "SerieA": ("Italy", 1), "Bundesliga": ("Germany", 1),
    "Ligue1": ("France", 1), "GreekSL": ("Greece", 1), "PrimeiraLiga": ("Portugal", 1),
    "Eredivisie": ("Netherlands", 1), "BrazilSerieA": ("Brazil", 1),
    "Belgium": ("Belgium", 1), "Turkey": ("Turkey", 1), "Scotland": ("Scotland", 1),
    "Denmark": ("Denmark", 1), "Sweden": ("Sweden", 1), "Norway": ("Norway", 1),
    "Poland": ("Poland", 1), "Austria": ("Austria", 1), "Switzerland": ("Switzerland", 1),
    "Romania": ("Romania", 1), "Ireland": ("Ireland", 1), "Finland": ("Finland", 1),
    # second tiers of leagues we predict — history only
    "Spain2": ("Spain", 2), "Italy2": ("Italy", 2), "Germany2": ("Germany", 2),
    "France2": ("France", 2), "Portugal2": ("Portugal", 2),
    "Netherlands2": ("Netherlands", 2), "Belgium2": ("Belgium", 2),
    "Turkey2": ("Turkey", 2), "Greece2": ("Greece", 2), "GreeceFL": ("Greece", 3),
    "Poland2": ("Poland", 2), "Romania2": ("Romania", 2), "Sweden2": ("Sweden", 2),
    "BrazilSerieB": ("Brazil", 2),
    # foreign top flights, reached through European qualifying — history only
    "Croatia": ("Croatia", 1), "Czechia": ("Czechia", 1), "Hungary": ("Hungary", 1),
    "Serbia": ("Serbia", 1), "Ukraine": ("Ukraine", 1), "Israel": ("Israel", 1),
    "Bulgaria": ("Bulgaria", 1), "Cyprus": ("Cyprus", 1), "Slovenia": ("Slovenia", 1),
    "Slovakia": ("Slovakia", 1), "Bosnia": ("Bosnia", 1), "Estonia": ("Estonia", 1),
    "Latvia": ("Latvia", 1), "Lithuania": ("Lithuania", 1), "Armenia": ("Armenia", 1),
    "Georgia": ("Georgia", 1), "Azerbaijan": ("Azerbaijan", 1),
    "Kazakhstan": ("Kazakhstan", 1), "Belarus": ("Belarus", 1), "Albania": ("Albania", 1),
    "Kosovo": ("Kosovo", 1), "NMacedonia": ("NMacedonia", 1), "Moldova": ("Moldova", 1),
    "FaroeIslands": ("FaroeIslands", 1), "Iceland": ("Iceland", 1), "Malta": ("Malta", 1),
    "NorthernIreland": ("NorthernIreland", 1), "Wales": ("Wales", 1),
    "Andorra": ("Andorra", 1), "Luxembourg": ("Luxembourg", 1),
    "Montenegro": ("Montenegro", 1), "Gibraltar": ("Gibraltar", 1),
}


# ── Names that mean two different clubs ───────────────────────────────────────
#
# A club name is not unique in the world, and the importers store a bare string.
# Seven names each ended up holding two unrelated clubs whose matches, Elo and
# form were fused into one rating — including Arsenal and Olympiacos, both of
# which we serve predictions for.
#
# The fix is per league: rename the side in the league we do NOT predict, so the
# name the site displays is untouched. Where neither league is predicted, the
# one with less history is renamed. (league, name-as-imported) → stored name.
NAME_DISAMBIGUATION: dict[tuple[str, str], str] = {
    ("Belarus", "Arsenal"): "Arsenal Dzyarzhynsk",      # not Arsenal FC, London
    ("Cyprus", "Olympiakos"): "Olympiakos Nicosia",     # not Olympiacos Piraeus
    ("Cyprus", "Aris"): "Aris Limassol",                # not Aris Thessaloniki
    ("Kazakhstan", "Altay"): "Altai Oskemen",           # not Altay SK, Izmir
    ("Kosovo", "Flamurtari"): "Flamurtari Prishtina",   # not Flamurtari Vlore
    ("Moldova", "Iskra"): "Iskra Ribnita",              # not Iskra Danilovgrad
    # Montenegro is a double fault: the source files label Rudar Pljevlja
    # "Rudar Velenje" for four seasons — NK Rudar Velenje is Slovenian and has
    # never played in Montenegro — and then switch to a bare "Rudar" for the
    # same club. Both spellings are the Pljevlja side; Slovenia's bare "Rudar"
    # is the real Velenje.
    ("Montenegro", "Rudar"): "Rudar Pljevlja",
    ("Montenegro", "Rudar Velenje"): "Rudar Pljevlja",
    ("Slovenia", "Rudar"): "Rudar Velenje",
    # FC Ranger's of Andorra. The near-miss spelling is worse than a duplicate:
    # "Ranger's" was a real CSV name, so the resolver matched the Scottish
    # feed's "Ranger's" straight onto it, and four 2026 Premiership fixtures —
    # against Aberdeen, St Mirren, Motherwell and Falkirk — were filed as the
    # Andorran club, to be priced off Andorran form.
    ("Andorra", "Ranger's"): "Ranger's Andorra",
    # Not an ambiguous name but a malformed one: the feed glued the club's
    # former and current names together into a single cell. One row, and the
    # club it belongs to is not in doubt — AFC Eskilstuna played Superettan in
    # 2020 and Örgryte's opponent that day was them. Handled here so a re-import
    # of Sweden2_2020 cannot bring it back.
    ("Sweden2", "Vasby UnitedAFC Eskilstuna"): "AFC Eskilstuna",
}


# ── Look-alikes that really are two clubs ─────────────────────────────────────
#
# The identity rule in scripts/audit_team_identity.py proposes a merge whenever
# two similar names never appear in a season together — which is what one club
# looks like when two feeds spell it differently. It is also what a club that
# went bankrupt looks like, seen next to the one that took its place.
#
# These 14 were reviewed club by club and are genuinely separate. Recording
# them stops the audit re-proposing a merge that would permanently fuse two
# clubs' Elo — the one mistake here that cannot be undone from the data.
KNOWN_DISTINCT: frozenset[tuple[str, str]] = frozenset({
    # phoenix clubs: the old entity was liquidated, the new one is not it
    ("Lierse", "K. Lierse S.K."),        # Lierse SK (1906) died 2018; the
                                         # Belgium2 side is Oosterzonen's licence
    ("Lokeren", "Lokeren-Temse"),        # Lokeren bankrupt 2020; the successor
                                         # kept KSV Temse's matricule 4297
    ("Metalist 1925 Kharkiv", "Metalist"),   # Metalist Kharkiv barred 2016;
                                             # Metalist 1925 founded separately
    ("Belenenses", "CF Os Belenenses"),  # B-SAD (the 2018 breakaway) vs the
                                         # historic club that restarted below it
    ("Speranta Nisporeni", "Speranis Nisporeni"),   # one died 2021, the other
                                                    # took the name in 2022
    # rivals or namesakes in the same town
    ("U Craiova", "U Craiova 1948"),     # they play each other; the 2014-2020
                                         # gap is a mid-file rename artefact
    ("Lviv", "Ruh Lviv"),                # FC Lviv and FC Rukh Lviv
    ("Iraklis", "Iraklis Larissa"),      # Thessaloniki and Larissa
    ("Ferizaj", "Dinamo Ferizaj"),       # both in Kosovo in 2025-26
    ("Shkendija", "Shkendija Haracine"), # Tetovo and Haracine, both in the
                                         # 2026 First League team list
    ("Dacia-Buiucani", "Dacia"),         # Buiucani was Dacia's feeder, then
                                         # went independent
    ("Ungheni", "FCM Ungheni"),          # two Ungheni clubs, coexisting
    ("Jelgava", "FS Jelgava"),           # FK Jelgava and the ex-Albatroz SC
    ("Rudar", "Rudar Velenje"),          # resolved by NAME_DISAMBIGUATION
                                         # above; kept so it cannot come back
    # FK Rad Beograd left the SuperLiga in 2020, FK Radnički 1923 of Kragujevac
    # came up in 2021, so the two never share a season and "RAD" reads as a
    # truncation of "Radnicki". Different cities, different clubs — and a third,
    # Radnički Niš, is in the data as "Radnicki NIS".
    ("RAD", "Radnicki 1923"),
    # Same city, different clubs. Gaziantepspor (1969) was relegated out of the
    # professional game in 2019; Gaziantep FK — Gazişehir until 2019 — is the
    # Süper Lig side, so the two never overlap and "Gaziantep" reads as a
    # truncation of "Gaziantepspor".
    ("Gaziantepspor", "Gaziantep"),
    # Östersunds FK (1996, Östersund) against Östers IF (1930, Växjö). Nothing
    # in common but the first five letters.
    ("Ostersunds", "Oster"),
    ("Ostersunds", "Osters"),
    # ── 2026-08-03, after the Poland2/Romania2/Sweden2/BrazilSerieB import ──
    # The Superettan history introduced "Ostersunds FK" as a third spelling, so
    # the guard above no longer covered the pair the audit actually proposes.
    # Östers IF's real counterpart is "Osters IF" (257 rows), not this one.
    ("Ostersunds FK", "Osters"),
    ("Ostersunds FK", "Oster"),
    # Paraná Clube (Curitiba, 1989) against Athletico Paranaense (1924). Both
    # from Paraná state, neither is the other; "Parana" is not a truncation.
    ("Parana", "Atletico Paranaense"),
    # Botafogo-SP (Ribeirão Preto) against Botafogo-RJ. The bare "Botafogo"
    # rows are Série B 2015 and 2021 — Botafogo-RJ's two relegated seasons —
    # and are folded into "Botafogo RJ" by features._CSV_TEAM_CANON. Without
    # this line the audit keeps proposing the Ribeirão Preto club instead.
    ("Botafogo", "Botafogo SP"),
    ("Botafogo RJ", "Botafogo SP"),
    # ── 2026-08-04, from the historical remainder of that same import ───────
    # Romanian phoenix clubs. The original was liquidated in each case and the
    # side playing today inherited nothing but the name, so the two strings sit
    # either side of a multi-season hole — which is also exactly what one club
    # looks like when two feeds spell it differently. Only club history
    # separates them.
    ("Targu Mures", "ASA Targu Mures"),      # ASA 2013 dissolved 2018;
                                             # AFC ASA re-established 2021
    ("Bistrita", "Gloria Bistrita"),         # ACF Gloria bankrupt 2015; FC
                                             # Gloria Bistrița-Năsăud born 2018
    ("Ceahlaul", "Ceahlaul Piatra Neamt"),   # FC Ceahlăul dissolved 2016; CSM
                                             # Ceahlăul restarted in Liga V
    # Hammarby Talang FF is a separate feeder club: Hammarby IF bought IK Frej
    # Täby's senior team in 2021 and rebranded it to inherit Frej's league
    # place. Merging would put a third-tier side's results on the Allsvenskan
    # club's Elo.
    ("Hammarby", "Hammarby Talang"),
    # ── 2026-08-04, false positives of the abbreviation rule ────────────────
    # Same first word, different town or different club entirely.
    ("Atletico Goianiense", "Athletico-PR"),         # Goiânia vs Curitiba
    ("Unirea Dej", "Unirea Ungheni"),                # two different towns
    ("Vorskla Poltava", "SK Poltava"),               # two Poltava clubs
    ("NFK Minsk", "Torpedo Minsk"),
    ("Metal Kharkiv", "FC Kharkiv"),
    ("Aerostar Bacau", "FC Bacau"),
    # FC Dnipro Dnipropetrovsk was liquidated in 2019; SC Dnipro-1 was founded
    # separately in 2017 and is not its legal successor.
    ("Dnipro-1", "Dnipro Dnipropetrovsk"),
})


def are_known_distinct(a: str, b: str) -> bool:
    return (a, b) in KNOWN_DISTINCT or (b, a) in KNOWN_DISTINCT


def disambiguate(league: str, name: str) -> str:
    """The unambiguous name to store for a club in this league."""
    return NAME_DISAMBIGUATION.get((league, (name or "").strip()), name)


def country_of(league: str) -> str | None:
    entry = LEAGUE_COUNTRY_TIER.get(league)
    return entry[0] if entry else None


def tier_of(league: str) -> int | None:
    entry = LEAGUE_COUNTRY_TIER.get(league)
    return entry[1] if entry else None


# ── Season encoding ───────────────────────────────────────────────────────────
#
# Filenames carry the season two ways and they collide. football-data.co.uk
# files are named for both halves — "2021" is the 2020/21 season — while the
# API-Football imports use the start year, so their "2021" is 2021/22. Read the
# token without knowing the source and Schalke appears in the Bundesliga and
# the 2. Bundesliga in the same season, which is how a legitimate merge first
# looked like two clubs.
#
# The encoding is a property of the league, decided by majority vote over all
# of its files: a run like 1011…2526 is consecutive halves throughout, while a
# run like 2015…2025 is not.

def _looks_like_split_season(token: str) -> bool:
    value = int(token)
    return (value // 100 + 1) % 100 == value % 100


def season_scheme(tokens: list[str]) -> str:
    """'split' for 2010/11-style tokens, 'start' for plain start years."""
    usable = [t for t in tokens if t.isdigit() and len(t) == 4]
    if not usable:
        return "start"
    split = sum(_looks_like_split_season(t) for t in usable)
    return "split" if split > len(usable) / 2 else "start"


def start_year(token: str, scheme: str) -> int:
    value = int(token)
    return 2000 + value // 100 if scheme == "split" else value
