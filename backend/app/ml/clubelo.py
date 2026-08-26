"""
ClubElo cold-start fallback for club-team Elo.

Teams absent from our historical CSVs default to Elo 1500 (ELO_START) in the
snapshot — i.e. the model treats a newly-promoted side, a lower-division cup /
friendly opponent, or a European-qualifier minnow as perfectly average. ClubElo
rates ~1,050 clubs across every UEFA federation (fetched by
scripts/fetch_clubelo.py into backend/data/clubelo.json).

We do NOT inject the raw ClubElo number: it is on its own scale, and not a fixed
one — the 2026-08 source change moved San Marino's Tre Fiori from 736 to 947
without either number being wrong. Instead `fit_clubelo_map` fits a linear
ClubElo→our-Elo map on the OVERLAP of teams present in both sources, and
`seed_cold_start` applies it to cold-start teams, clamped to our observed range.
Refitting daily is what makes the seam survive an upstream rescale: no constant
here or in the fetcher encodes what a ClubElo point is worth.

Everything degrades gracefully: a missing/short clubelo.json or a degenerate fit
means "no seeding" and the pipeline behaves exactly as before (flat 1500).
"""
from __future__ import annotations

import json
import os
from typing import Iterable, Optional

from backend.app.ml.features import _slug

_CLUBELO_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "clubelo.json")

# Need a stable 2-parameter fit; below this the map is untrustworthy → skip.
_MIN_OVERLAP = 20


def load_clubelo_index(
    path: Optional[str] = None,
) -> tuple[dict[str, float], dict[str, str]]:
    """Return ({slug: elo}, {slug: spelling}) from clubelo.json, or ({}, {}).

    Each club is indexed under its own name and under every alternative spelling
    the fetcher recorded in `aka` (the club's URL slug, the name minus a leading
    "KF"/"PFK"-style token, hand-curated cases). Names win over aka: an alias only
    claims a slug no real name took, so "Lincoln Red Imps" can never displace a
    club actually called that.

    A slug two DIFFERENT clubs answer to is dropped rather than resolved. The
    shared `_slug` is lossy enough to make that a real risk — it strips "city"
    and "united", so Man City and Man United both reduce to "man", and Lincoln
    City to Gibraltar's Lincoln — and a confidently wrong Elo is worse than the
    flat-1500 default this whole seam exists to improve on. Dropping costs a
    handful of the ~1,200 slugs and every one of them is a club with CSV history
    anyway, so it touches the regression fit and never a cold-start seed.

    The second map keeps the un-slugged spelling that claimed each slug, because
    `_slug` throws away the word boundaries `seed_cold_start`'s fuzzy rule needs
    to stay honest.
    """
    p = path or _CLUBELO_PATH
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}, {}
    clubs = data.get("clubs", {})

    # slug → {rounded elo: (elo, spelling)}. More than one key means two clubs.
    tiers: list[dict[str, dict[int, tuple[float, str]]]] = [{}, {}]
    for name, info in clubs.items():
        try:
            elo = float(info["elo"])
        except (KeyError, TypeError, ValueError):
            continue
        aka = info.get("aka") or [] if isinstance(info, dict) else []
        for tier, spellings in ((0, [name]), (1, aka)):
            for spelling in spellings:
                s = _slug(spelling)
                if s:
                    tiers[tier].setdefault(s, {})[round(elo)] = (elo, spelling)

    by_slug: dict[str, float] = {}
    spelling_by_slug: dict[str, str] = {}
    for tier in tiers:
        for s, values in tier.items():
            if s not in by_slug and len(values) == 1:
                by_slug[s], spelling_by_slug[s] = next(iter(values.values()))
    return by_slug, spelling_by_slug


def load_clubelo(path: Optional[str] = None) -> dict[str, float]:
    """Return {slug: elo} from clubelo.json, or {} if absent/unreadable."""
    return load_clubelo_index(path)[0]


def _token_prefixes(name: str) -> set[str]:
    """Slugs of every leading run of whole words in `name`.

    "Gornik Zabrze" → {"gornik", "gornikzabrze"}; "Vikingur Gota" →
    {"vikingur", "vikingurgota"}. Built by slugging progressively longer token
    joins rather than by cutting the finished slug, so noise words `_slug`
    deletes ("Sheffield United" → "sheffield") never create a phantom boundary.
    """
    tokens = name.split()
    out = set()
    for k in range(1, len(tokens) + 1):
        s = _slug(" ".join(tokens[:k]))
        if s:
            out.add(s)
    return out


def fit_clubelo_map(
    our_elo: dict[str, float],
    clubelo_by_slug: dict[str, float],
) -> Optional[tuple[float, float, float, float]]:
    """Least-squares fit our_elo ≈ a·clubelo + b over teams in both sources.

    Returns (a, b, lo, hi) where [lo, hi] is our observed Elo range (for clamping),
    or None when the overlap is too small / degenerate to trust.
    """
    xs: list[float] = []
    ys: list[float] = []
    for team, e in our_elo.items():
        s = _slug(team)
        c = clubelo_by_slug.get(s)
        if c is not None:
            xs.append(c)
            ys.append(float(e))
    if len(xs) < _MIN_OVERLAP:
        return None

    import numpy as np

    x = np.asarray(xs)
    y = np.asarray(ys)
    if float(x.std()) < 1e-6:            # no spread → can't fit a slope
        return None
    a, b = np.polyfit(x, y, 1)
    if not (np.isfinite(a) and np.isfinite(b)) or a <= 0:
        return None                       # nonsensical (Elo must be monotone)
    return float(a), float(b), float(y.min()), float(y.max())


def seed_cold_start(
    snapshot: dict,
    known_teams: Iterable[str],
    fixtures_teams: Iterable[str],
    clubelo_by_slug: Optional[dict[str, float]] = None,
    clubelo_names: Optional[dict[str, str]] = None,
) -> dict[str, float]:
    """Seed snapshot['elo'] for cold-start fixture teams from ClubElo.

    Only teams that are (a) in the fixtures being predicted, (b) NOT already known
    (no CSV history), and (c) present in ClubElo are seeded. Mutates
    snapshot['elo'] in place and returns {team: seeded_elo} for logging.

    `known_teams` must be the set frozen BEFORE seeding, so insufficient_data
    classification (which reads that frozen set) is unaffected — seeding sharpens
    the Elo signal without ever marking a no-history fixture as suggestable.

    `clubelo_names` is the slug→spelling half of `load_clubelo_index`; both are
    loaded from disk when neither is passed. Without it the fuzzy rule below can
    only run in the direction that needs our own name, which is the safe half.
    """
    elo = snapshot.get("elo")
    if elo is None:
        return {}
    if clubelo_by_slug is None:
        clubelo_by_slug, loaded_names = load_clubelo_index()
        if clubelo_names is None:
            clubelo_names = loaded_names
    if not clubelo_by_slug:
        return {}
    clubelo_names = clubelo_names or {}

    fit = fit_clubelo_map(dict(elo), clubelo_by_slug)
    if fit is None:
        return {}
    a, b, lo, hi = fit

    # Our fixture name → ClubElo's name, for the cases neither the exact slug
    # nor the unique-prefix rule below can bridge safely. The fetcher's `aka`
    # list handles everything mechanical (URL slugs, "KF "-style prefixes) and
    # everything that needs to know the club's federation; what is left here is
    # our OWN spellings, which the fetcher has no way to know about.
    _SEED_ALIASES = {
        "lechpoznan": "lech",
        "heartofmidlothian": "hearts",
        "kiklaksvik": "klaksvik",
        # Same shape as Lille/Lillestrom — one word, differing mid-word — so the
        # prefix rule below refuses it, correctly. Only a human knows that this
        # particular pair IS one club.
        "debrecenivsc": "debrecen",
    }

    def _lookup(team: str) -> "float | None":
        """Alias, then exact slug, then a UNIQUE prefix match.

        The prefix rule exists because the two sources abbreviate differently:
        ClubElo says "Gornik" where a fixture says "Gornik Zabrze", says
        "Ilves Tampere" where a fixture says "Ilves", and truncates every display
        name at 16 characters ("Egnatia Rrogozhi" for "Egnatia Rrogozhinë").

        It is only safe when the shorter name stops at a WORD boundary of the
        longer one. Dropped separators make "Lille" a prefix of "Lillestrom",
        "Viking" of "Vikingur Gota", "Sparta" of "Spartak Trnava" and "Braga" of
        "Bragantino" — four different clubs each, and each one a seed we would
        state with confidence. Uniqueness alone does not catch them: there is
        exactly one "Lille". The 16-char truncations are the deliberate
        exception, admitted only in the direction that produces them.
        """
        team_slug = _slug(team)
        alias = _SEED_ALIASES.get(team_slug)
        if alias is not None and alias in clubelo_by_slug:
            return clubelo_by_slug[alias]
        hit = clubelo_by_slug.get(team_slug)
        if hit is not None:
            return hit
        if len(team_slug) < 5:
            return None

        ours = _token_prefixes(team)
        cands = []
        for cs, v in clubelo_by_slug.items():
            if len(cs) < 5:
                continue
            if team_slug.startswith(cs):
                # ClubElo's name is the shorter one: accept a whole-word prefix
                # of ours, or a name the page cut off mid-word at 16 characters.
                if cs in ours or len(clubelo_names.get(cs, "")) == 16:
                    cands.append(v)
            elif cs.startswith(team_slug):
                # Ours is the shorter one: it has to stop at a word boundary of
                # theirs, so "Naval" cannot claim "CDA Navalcarnero".
                if team_slug in _token_prefixes(clubelo_names.get(cs, "")):
                    cands.append(v)
        return cands[0] if len(cands) == 1 else None

    known = set(known_teams)
    seeded: dict[str, float] = {}
    for team in set(fixtures_teams):
        if team in known:
            continue
        c = _lookup(team)
        if c is None:
            continue
        val = a * c + b
        val = max(lo, min(hi, val))       # never extrapolate past our range
        elo[team] = val
        seeded[team] = val
    return seeded
