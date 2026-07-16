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
    r")\s*$",
    re.IGNORECASE,
)


def strip_youth(name: str) -> tuple[str, bool]:
    """('Fiorentina U20') → ('Fiorentina', True). Idempotent for senior sides."""
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
    unknown = {
        t for f in fixtures for t in (f.get("home_team"), f.get("away_team"))
        if t and t not in known
    }
    if unknown:
        tag = "[warn]" if domestic else "[info]"
        why = ("not in training data — likely an unmapped name; add it to TEAM_MAP"
               if domestic else "no training history — will use default features")
        sample = ", ".join(sorted(unknown)[:20])
        print(f"  {tag} {len(unknown)} unresolved team(s) — {why}: {sample}"
              + (" …" if len(unknown) > 20 else ""))
    return unknown


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

    team_map = team_map or {}
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
