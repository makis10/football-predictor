#!/usr/bin/env python3
"""One club, or two? Audit every team name in the training CSVs.

Team identity is a bare string here, and four feeds spell it four ways. Two
failures follow, and both corrupt Elo silently:

  · ONE CLUB, TWO NAMES — football-data.co.uk writes "Freiburg" in the
    Bundesliga file, API-Football writes "SC Freiburg" in the 2. Bundesliga
    one. The club's history splits, and the thinner half runs on near-default
    features while taking real matches away from the other.

  · TWO CLUBS, ONE NAME — "Arsenal" is a club in Belarus as well as England,
    "Olympiakos" one in Cyprus as well as Greece. Their results are fused into
    a single rating.

The rule, strongest evidence first:

  1. they played each other          → two clubs. No club plays itself.
  2. different country               → two clubs
  3. a full season each in one table → two clubs (one club under two names
                                        splits a season; two clubs each play one)
  4. same season, different division → two clubs (a B side, or a namesake)
  5. otherwise, same country         → one club, two spellings

Usage:
    python scripts/audit_team_identity.py           # report
    python scripts/audit_team_identity.py --json    # machine-readable
"""
from __future__ import annotations

import argparse
import collections
import csv
import difflib
import glob
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.ml.league_registry import (  # noqa: E402
    LEAGUE_COUNTRY_TIER, are_known_distinct, season_scheme, start_year,
)

RAW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "backend", "data", "raw")

# A club that plays this many league games in a season had a real campaign.
# Two names each clearing it in one table are two clubs; below it, the second
# name is a mid-season rename (Romania_2526 switches "Din. Bucuresti" to
# "Dinamo Bucuresti" partway through).
FULL_SEASON = 14

# More games than a two-legged play-off tie. Below this a club's presence in a
# division is an appearance in someone else's competition, not a campaign in it.
PLAYOFF_TIE = 3


def _slug(s: str) -> str:
    ascii_s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_s.lower())


def _tokens(s: str) -> list[str]:
    ascii_s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return [w for w in re.split(r"[^a-z0-9]+", ascii_s.lower()) if w]


def _truncated_words(short: list[str], long_: list[str]) -> bool:
    """Is `short` `long_` with its words cut off? "For Sittard" ↔ "Fortuna Sittard".

    football-data.co.uk truncates names to fit a column — "Ein Frankfurt",
    "Nott'm Forest", "Sp Braga", "Ath Bilbao" — while the second-tier imports
    spell them out. The edit-distance rule cannot see these: "forsittard" and
    "fortunasittard" differ by four characters, one past its length guard, so
    Fortuna Sittard and Hamburger SV both stayed split until the display-name
    work tripped over them.

    Each of `short`'s words must be a prefix of a word in `long_`, in order,
    with at least one genuinely shortened. Three characters minimum, or "S"
    matches everything.
    """
    if not short or len(short) > len(long_):
        return False
    i, shortened = 0, False
    for word in short:
        while i < len(long_):
            other = long_[i]
            i += 1
            if word == other:
                break
            if len(word) >= 3 and other.startswith(word):
                shortened = True
                break
        else:
            return False
    return shortened


def _abbreviated_word(a: list[str], b: list[str]) -> bool:
    """Same words but one, and that one is an abbreviation of the other.

    "Atletico GO" / "Atletico Goianiense", "Gornik Z." / "Gornik Zabrze",
    "America MG" / "America Mineiro" — a state code or an initial standing in
    for a word. The truncated-words rule cannot see these because "go" is not a
    prefix of "goianiense" in any useful sense, and a plain shared-prefix rule
    is far too loose: "Hapoel" alone would pair Tel Aviv with Acre.

    Requiring the same word COUNT and exactly one differing position, with the
    short side at most three characters, keeps it to real abbreviations.
    """
    # At least two words, or the "shared" part is nothing at all and every
    # three-letter club in the data pairs with every long one: CRB with
    # Nautico, AIK with Brage.
    if len(a) != len(b) or len(a) < 2:
        return False
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    if len(diff) != 1:
        return False
    x, y = diff[0]
    short, long_ = sorted((x, y), key=len)
    return len(short) <= 3 and len(long_) >= 4


def _canon(name: str) -> str:
    """Follow features._CSV_TEAM_CANON to the spelling the model actually uses."""
    from backend.app.ml.features import _CSV_TEAM_CANON

    seen = {name}
    while name in _CSV_TEAM_CANON:
        name = _CSV_TEAM_CANON[name]
        if name in seen:
            break
        seen.add(name)
    return name


class Corpus:
    """Every name in the CSVs, with where it played, when, and against whom."""

    def __init__(self, raw_dir: str = RAW):
        self.where: dict[str, set[tuple[str, int]]] = collections.defaultdict(set)
        self.table: dict[tuple[str, int], collections.Counter] = collections.defaultdict(
            collections.Counter)
        self.opponents: dict[str, set[str]] = collections.defaultdict(set)
        self.counts: collections.Counter = collections.Counter()
        self.unmapped: set[str] = set()

        files = sorted(glob.glob(os.path.join(raw_dir, "*.csv")))
        tokens_by_league: dict[str, list[str]] = collections.defaultdict(list)
        for path in files:
            league, _, season = os.path.basename(path)[:-4].rpartition("_")
            if league in LEAGUE_COUNTRY_TIER and season.isdigit():
                tokens_by_league[league].append(season)
        self.scheme = {lg: season_scheme(ts) for lg, ts in tokens_by_league.items()}

        for path in files:
            league, _, season = os.path.basename(path)[:-4].rpartition("_")
            if not season.isdigit():
                continue
            if league not in LEAGUE_COUNTRY_TIER:
                self.unmapped.add(league)
                continue
            year = start_year(season, self.scheme[league])
            # latin-1, because that is the codec `features.load_raw_csvs` uses.
            # Reading these as UTF-8 shows names the model never sees: Malta's
            # files are latin-1 and decode to "Santa Luc�a" here but to
            # "Santa Lucía" there, which invented an encoding bug that was not
            # in the data.
            with open(path, newline="", encoding="latin-1") as fh:
                reader = csv.DictReader(fh)
                cols = reader.fieldnames or []
                home = "home_team" if "home_team" in cols else "HomeTeam"
                away = "away_team" if "away_team" in cols else "AwayTeam"
                if home not in cols or away not in cols:
                    continue
                for row in reader:
                    h, a = (row.get(home) or "").strip(), (row.get(away) or "").strip()
                    if not h or not a:
                        continue
                    for team, opp in ((h, a), (a, h)):
                        self.where[team].add((league, year))
                        self.table[(league, year)][team] += 1
                        self.opponents[team].add(opp)
                        self.counts[team] += 1

        self.names = sorted(self.where)

    def countries(self, name: str) -> set[str]:
        return {LEAGUE_COUNTRY_TIER[lg][0] for lg, _ in self.where[name]}

    # ── the rule ──────────────────────────────────────────────────────────────
    def verdict(self, a: str, b: str) -> tuple[bool, str]:
        """(same_club, why)."""
        # KNOWN_DISTINCT names CLUBS, not spellings, so resolve both sides
        # through the canon table first: "Atletico GO" and "Atletico Paranaense"
        # are recorded as distinct under their surviving names.
        if are_known_distinct(a, b) or are_known_distinct(_canon(a), _canon(b)):
            return False, "reviewed: two clubs (league_registry.KNOWN_DISTINCT)"
        if b in self.opponents[a]:
            return False, "they played each other"
        ca, cb = self.countries(a), self.countries(b)
        if not (ca & cb):
            return False, f"different countries: {sorted(ca)} vs {sorted(cb)}"
        shared, cross_tier = [], []
        for lg_a, yr_a in self.where[a]:
            for lg_b, yr_b in self.where[b]:
                if yr_a != yr_b:
                    continue
                if lg_a == lg_b:
                    ga = self.table[(lg_a, yr_a)][a]
                    gb = self.table[(lg_a, yr_a)][b]
                    if ga >= FULL_SEASON and gb >= FULL_SEASON:
                        shared.append((yr_a, lg_a, ga, gb))
                elif LEAGUE_COUNTRY_TIER[lg_a][1] != LEAGUE_COUNTRY_TIER[lg_b][1]:
                    # A promotion/relegation play-off is a first-division club
                    # against a second-division one, and the tie is filed in
                    # the TOP flight's season file — so the second-tier club
                    # appears in both divisions in the same year, on two rows,
                    # without ever having been in two divisions. Dinamo
                    # București's June 2023 baraj against FC Argeș is exactly
                    # that, and it made the audit call one club two.
                    # Require a real presence on each side instead.
                    ga = self.table[(lg_a, yr_a)][a]
                    gb = self.table[(lg_b, yr_b)][b]
                    if ga >= PLAYOFF_TIE and gb >= PLAYOFF_TIE:
                        cross_tier.append((yr_a, lg_a, lg_b))
        if shared:
            yr, lg, ga, gb = sorted(shared)[0]
            return False, f"{lg} {yr}: a full season each ({ga} and {gb} games)"
        if cross_tier:
            yr, la, lb = sorted(cross_tier)[0]
            return False, f"{yr}: {la} vs {lb} — different divisions at once"
        return True, f"{sorted(ca & cb)[0]}, never apart in a season"

    # ── candidates ────────────────────────────────────────────────────────────
    def candidate_pairs(self) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()

        by_slug: dict[str, list[str]] = collections.defaultdict(list)
        for name in self.names:
            by_slug[_slug(name)].append(name)
        for group in by_slug.values():                 # accents and punctuation only
            for i, x in enumerate(group):
                for y in group[i + 1:]:
                    pairs.add(tuple(sorted((x, y))))

        toks = {n: _tokens(n) for n in self.names}
        for i, x in enumerate(self.names):
            tx, sx, cx = toks[x], _slug(x), self.countries(x)
            if not tx:
                continue
            for y in self.names[i + 1:]:
                ty = toks[y]
                if not ty or tx == ty or not (cx & self.countries(y)):
                    continue
                short, long_ = (tx, ty) if len(tx) < len(ty) else (ty, tx)
                if all(w in long_ for w in short):     # whole-token subset
                    pairs.add(tuple(sorted((x, y))))
                    continue
                # Both ways round: with equal token counts, which list is
                # "short" is arbitrary, and calling it once had For Sittard and
                # Fortuna Sittard fail the very rule written for them.
                if _truncated_words(tx, ty) or _truncated_words(ty, tx):
                    pairs.add(tuple(sorted((x, y))))
                    continue
                # A long shared prefix. The truncated-words rule needs every
                # word of the short name to line up, so it missed pairs whose
                # LAST word differs — "Erzurum BB" / "Erzurumspor FK" and
                # "Atletico GO" / "Atletico Goianiense" both stayed split, and
                # each is one club. False candidates from a shared city name
                # ("Atletico MG" / "Atletico GO") are what the verdict rule is
                # for: those two played each other.
                sy = _slug(y)
                if _abbreviated_word(tx, ty):
                    pairs.add(tuple(sorted((x, y))))
                    continue
                if (len(sx) >= 5 and len(sy) >= 5 and abs(len(sx) - len(sy)) <= 3
                        and difflib.SequenceMatcher(None, sx, sy).ratio() >= 0.88):
                    pairs.add(tuple(sorted((x, y))))
        return pairs

    def collisions(self) -> dict[str, list[str]]:
        """One name, two countries — two clubs sharing a single rating."""
        return {n: sorted(self.countries(n))
                for n in self.names if len(self.countries(n)) > 1}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from backend.app.ml.features import _CSV_TEAM_CANON

    def resolve(name: str) -> str:
        """Follow the canon table to its end — merges chain.

        "Kaiserslautern" and "1. FC Nurnberg" both fold onto a third spelling,
        so comparing each pair to a single table entry reported them as still
        split when they were already one club.
        """
        seen = {name}
        while name in _CSV_TEAM_CANON:
            name = _CSV_TEAM_CANON[name]
            if name in seen:
                break
            seen.add(name)
        return name

    corpus = Corpus()
    same, separate = [], []
    for x, y in sorted(corpus.candidate_pairs()):
        is_same, why = corpus.verdict(x, y)
        fat, thin = (x, y) if corpus.counts[x] >= corpus.counts[y] else (y, x)
        rec = {"fat": fat, "thin": thin, "why": why,
               "fat_n": corpus.counts[fat], "thin_n": corpus.counts[thin],
               "merged": resolve(fat) == resolve(thin)}
        (same if is_same else separate).append(rec)

    collisions = corpus.collisions()

    if args.json:
        json.dump({"same": same, "separate": separate, "collisions": collisions},
                  sys.stdout, ensure_ascii=False, indent=1)
        return 0

    if corpus.unmapped:
        print(f"!! leagues missing from LEAGUE_COUNTRY_TIER: {sorted(corpus.unmapped)}")
    print(f"{len(corpus.names)} names, {sum(corpus.counts.values()) // 2} matches\n")

    wrong = [r for r in separate if r["merged"]]
    todo = [r for r in same if not r["merged"]]

    print(f"── two clubs merged into one  ({len(wrong)}) " + "─" * 40)
    for r in wrong:
        print(f"  {r['fat']!r} + {r['thin']!r} — {r['why']}")
    print(f"\n── one club still under two names  ({len(todo)}) " + "─" * 34)
    for r in sorted(todo, key=lambda r: -(r["fat_n"] + r["thin_n"])):
        print(f"  {r['fat']!r} ({r['fat_n']})  ←  {r['thin']!r} ({r['thin_n']})")
    print(f"\n── one name, two countries  ({len(collisions)}) " + "─" * 41)
    for name, cs in sorted(collisions.items(), key=lambda kv: -corpus.counts[kv[0]]):
        print(f"  {name!r} ({corpus.counts[name]}) — {', '.join(cs)}")

    return 1 if (wrong or collisions) else 0


if __name__ == "__main__":
    raise SystemExit(main())
