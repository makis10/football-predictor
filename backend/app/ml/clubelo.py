"""
ClubElo cold-start fallback for club-team Elo.

Teams absent from our historical CSVs default to Elo 1500 (ELO_START) in the
snapshot — i.e. the model treats a newly-promoted side, a lower-division cup /
friendly opponent, or a European-qualifier minnow as perfectly average. ClubElo.com
publishes a daily rating for ~600 European clubs (fetched by scripts/fetch_clubelo.py
into backend/data/clubelo.json).

We do NOT inject the raw ClubElo number: its scale is wider than ours (top club
~2060 vs our max ~1990). Instead `fit_clubelo_map` fits a linear ClubElo→our-Elo
map on the OVERLAP of teams present in both sources, and `seed_cold_start` applies
it to cold-start teams, clamped to our observed range. This lands seeded values on
the distribution the models were trained on.

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


def load_clubelo(path: Optional[str] = None) -> dict[str, float]:
    """Return {slug: elo} from clubelo.json, or {} if absent/unreadable."""
    p = path or _CLUBELO_PATH
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    clubs = data.get("clubs", {})
    out: dict[str, float] = {}
    for name, info in clubs.items():
        try:
            elo = float(info["elo"])
        except (KeyError, TypeError, ValueError):
            continue
        s = _slug(name)
        # On a slug collision keep the higher rating (matches fetch_clubelo).
        if s and (s not in out or elo > out[s]):
            out[s] = elo
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
) -> dict[str, float]:
    """Seed snapshot['elo'] for cold-start fixture teams from ClubElo.

    Only teams that are (a) in the fixtures being predicted, (b) NOT already known
    (no CSV history), and (c) present in ClubElo are seeded. Mutates
    snapshot['elo'] in place and returns {team: seeded_elo} for logging.

    `known_teams` must be the set frozen BEFORE seeding, so insufficient_data
    classification (which reads that frozen set) is unaffected — seeding sharpens
    the Elo signal without ever marking a no-history fixture as suggestable.
    """
    elo = snapshot.get("elo")
    if elo is None:
        return {}
    clubelo_by_slug = load_clubelo() if clubelo_by_slug is None else clubelo_by_slug
    if not clubelo_by_slug:
        return {}

    fit = fit_clubelo_map(dict(elo), clubelo_by_slug)
    if fit is None:
        return {}
    a, b, lo, hi = fit

    # Our fixture name → ClubElo's (often truncated) name, where neither the
    # exact slug nor the unique-prefix rule can bridge them safely.
    _SEED_ALIASES = {
        "lechpoznan": "lech",
        "heartofmidlothian": "hearts",
        "kiklaksvik": "klaksvik",
    }

    def _lookup(team_slug: str) -> "float | None":
        alias = _SEED_ALIASES.get(team_slug)
        if alias is not None and alias in clubelo_by_slug:
            return clubelo_by_slug[alias]
        """Exact slug match first; else a UNIQUE prefix match (ClubElo often
        stores truncated names — 'Lech' for Lech Poznan, 'Gornik' for Gornik
        Zabrze). ≥5 chars and exactly one candidate, so 'riga' can never
        swallow 'rigasfs'."""
        hit = clubelo_by_slug.get(team_slug)
        if hit is not None:
            return hit
        if len(team_slug) < 5:
            return None
        cands = [v for cs, v in clubelo_by_slug.items()
                 if len(cs) >= 5 and (cs.startswith(team_slug) or team_slug.startswith(cs))]
        return cands[0] if len(cands) == 1 else None

    known = set(known_teams)
    seeded: dict[str, float] = {}
    for team in set(fixtures_teams):
        if team in known:
            continue
        c = _lookup(_slug(team))
        if c is None:
            continue
        val = a * c + b
        val = max(lo, min(hi, val))       # never extrapolate past our range
        elo[team] = val
        seeded[team] = val
    return seeded
