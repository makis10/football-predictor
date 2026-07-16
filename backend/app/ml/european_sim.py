"""
Monte Carlo projection of a UEFA competition: who lifts the trophy.

The 2024 format is three competitions in a trench coat, all under one league id:

  1. Qualifying knockout   (July–August)  — most entrants aren't known yet
  2. League phase          (Sept–Jan)     — 36 teams, ONE table, 8 games each
  3. Knockout bracket      (Feb–May)      — play-off, R16, QF, SF, final

This simulates from the league phase onwards:
    replay the remaining league-phase games → final 36-team table →
    9–24 contest the play-off round → winners join the top 8 in the R16 →
    bracket down to a champion.

WHY IT REFUSES TO RUN DURING QUALIFYING
---------------------------------------
Before the league-phase draw, the 36 participants literally do not exist yet —
half the field is still playing to get in. A "title chance" computed over the
qualifying field would be invented, not estimated, so this returns None until
league-phase fixtures appear (they carry round = "League Phase - N"; see
migration 0030). It then lights up on its own.

THE BRACKET IS A MODEL, NOT A FIXTURE LIST
------------------------------------------
UEFA seeds the play-off and R16 from the league-phase finishing positions, but
the exact pairings come out of a draw with its own constraints. We pair by seed
(9v24, 10v23 …; then 1 v the 16/17 winner, 2 v the 15/18 winner …), which
reproduces the format's structure — a top-8 finish is worth a bye and an easier
R16 — without pretending to know a draw that hasn't happened. Ties are settled
on aggregate over two legs, as in the real thing.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

from backend.app.ml.standings import (
    EUROPEAN_STRUCTURE,
    _canon_season,
    _latest_season,
    is_league_phase,
)

MU_TOTAL  = 2.75
ELO_SCALE = 220.0
HOME_ADV  = 60.0

DEFAULT_SIMS = 10_000


def _lambdas(elo_h: float, elo_a: float) -> tuple[float, float]:
    gd = (elo_h + HOME_ADV - elo_a) / ELO_SCALE
    return max(0.15, MU_TOTAL / 2 + gd / 2), max(0.15, MU_TOTAL / 2 - gd / 2)


def _poisson(rng: random.Random, lam: float) -> int:
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1
        if k > 12:
            return k


def _two_legged(rng: random.Random, a: str, b: str, elo: dict) -> str:
    """Aggregate over two legs, one home each. Coin-flip on a dead-level tie
    (the real thing goes to extra time and penalties, which is a coin flip at
    this level of modelling)."""
    l1h, l1a = _lambdas(elo[a], elo[b])       # leg 1: a at home
    l2h, l2a = _lambdas(elo[b], elo[a])       # leg 2: b at home
    agg_a = _poisson(rng, l1h) + _poisson(rng, l2a)
    agg_b = _poisson(rng, l1a) + _poisson(rng, l2h)
    if agg_a != agg_b:
        return a if agg_a > agg_b else b
    return a if rng.random() < 0.5 else b


def _single_leg(rng: random.Random, a: str, b: str, elo: dict) -> str:
    """Neutral-venue one-off (the final). No home advantage."""
    lh, la = _lambdas(elo[a], elo[b] + HOME_ADV)   # cancel the home bump
    ga, gb = _poisson(rng, lh), _poisson(rng, la)
    if ga != gb:
        return a if ga > gb else b
    return a if rng.random() < 0.5 else b


def simulate_european(db, league: str, sims: int = DEFAULT_SIMS, seed: int = 4242) -> dict | None:
    """Champion / final / R16 probabilities. None while the competition is still
    in its qualifying rounds (see the module docstring)."""
    from sqlalchemy import text

    if league not in EUROPEAN_STRUCTURE:
        return None

    season = _latest_season(db, league)
    if not season:
        return None

    rows = db.execute(text(
        "SELECT season, home_team, away_team, home_goals, away_goals, round "
        "FROM matches WHERE league = :lg"
    ), {"lg": league}).fetchall()

    lp = [r for r in rows if _canon_season(r[0]) == season and is_league_phase(r[5])]
    if not lp:
        return None                       # still in qualifying — nothing to model

    teams = sorted({t for _, h, a, _, _, _ in lp for t in (h, a)})
    if len(teams) < 8:
        return None

    # Points / goals already banked in the league phase.
    base_pts: dict[str, int] = {t: 0 for t in teams}
    base_gd:  dict[str, int] = {t: 0 for t in teams}
    base_gf:  dict[str, int] = {t: 0 for t in teams}
    remaining: list[tuple[str, str]] = []
    played = 0

    for _, h, a, hg, ag, _r in lp:
        if hg is None or ag is None:
            remaining.append((h, a))
            continue
        played += 1
        base_gd[h] += hg - ag
        base_gd[a] += ag - hg
        base_gf[h] += hg
        base_gf[a] += ag
        if hg > ag:
            base_pts[h] += 3
        elif ag > hg:
            base_pts[a] += 3
        else:
            base_pts[h] += 1
            base_pts[a] += 1

    from backend.app.ml.club_elo import club_elo
    table = club_elo(db)
    elo = {t: table.get(t, 1500.0) for t in teams}

    fixtures = [(h, a, *_lambdas(elo[h], elo[a])) for h, a in remaining]

    direct   = EUROPEAN_STRUCTURE[league]["direct"]     # 8
    playoff_to = EUROPEAN_STRUCTURE[league]["playoff"]  # 24

    champ_ct = defaultdict(int)
    final_ct = defaultdict(int)
    r16_ct   = defaultdict(int)

    rng = random.Random(seed)
    for _ in range(sims):
        pts, gd, gf = dict(base_pts), dict(base_gd), dict(base_gf)
        for h, a, lh, la in fixtures:
            hg, ag = _poisson(rng, lh), _poisson(rng, la)
            gd[h] += hg - ag
            gd[a] += ag - hg
            gf[h] += hg
            gf[a] += ag
            if hg > ag:
                pts[h] += 3
            elif ag > hg:
                pts[a] += 3
            else:
                pts[h] += 1
                pts[a] += 1

        order = sorted(teams, key=lambda t: (pts[t], gd[t], gf[t], rng.random()), reverse=True)
        seeded  = order[:direct]                 # 1–8: straight to the R16
        po      = order[direct:playoff_to]       # 9–24: play-off round
        # 25–36 are out; teams beyond the field (a partial draw) are ignored.

        # Play-off: 9v24, 10v23 … highest seed hosts the second leg, which our
        # two-legged helper already reflects by giving the second leg to `b`.
        po_winners = []
        for i in range(len(po) // 2):
            hi, lo = po[i], po[len(po) - 1 - i]
            po_winners.append(_two_legged(rng, lo, hi, elo))

        # R16: 1 v the lowest-seeded survivor, 2 v the next … the standard
        # "reward for finishing high" shape.
        bracket = seeded + po_winners[::-1]
        if len(bracket) < 2:
            continue
        for t in bracket:
            r16_ct[t] += 1

        # Straight bracket from here: R16 → QF → SF → final.
        rnd = bracket
        while len(rnd) > 2:
            nxt = []
            for i in range(len(rnd) // 2):
                nxt.append(_two_legged(rng, rnd[i], rnd[len(rnd) - 1 - i], elo))
            rnd = nxt
        if len(rnd) == 2:
            for t in rnd:
                final_ct[t] += 1
            champ_ct[_single_leg(rng, rnd[0], rnd[1], elo)] += 1
        elif rnd:
            champ_ct[rnd[0]] += 1

    projection = sorted(
        [
            {
                "team":      t,
                "p_champion": round(champ_ct[t] / sims, 4),
                "p_final":    round(final_ct[t] / sims, 4),
                "p_r16":      round(r16_ct[t] / sims, 4),
            }
            for t in teams
        ],
        key=lambda r: -r["p_champion"],
    )

    return {
        "league":            league,
        "season":            season,
        "sims":              sims,
        "matches_played":    played,
        "matches_remaining": len(remaining),
        "teams":             projection,
    }
