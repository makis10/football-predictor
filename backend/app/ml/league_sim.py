"""
Monte Carlo projection of a league season: title / Europe / relegation odds.

Same idea as the World Cup simulator, applied to a round-robin: take the points
already on the board, replay every match still to come thousands of times from
the clubs' current Elo, and count how often each team finishes where.

Why the remaining fixtures are DERIVED, not read from the DB
------------------------------------------------------------
We only ingest fixtures ~60 days ahead, so the DB holds e.g. 37 of the Premier
League's 380 matches. Simulating those 37 and stopping would answer a question
nobody asked. A domestic league is a double round-robin — every club hosts every
other exactly once — so the complete fixture set is just the ordered pairs of the
team list, and "remaining" = that set minus what has been played. Scheduling and
dates are irrelevant to a season-long projection; only the set of matches is.

For PLAYOFF_LEAGUES (below) the round-robin is only the season's FIRST phase:
the simulated table then splits into position-based groups (championship /
qualifying / relegation), points carry over, and each group plays its own
double round-robin — see PLAYOFF_SPECS. Title and relegation are counted from
the group outcomes, so a team 13th after the regular season can still climb out
of the drop inside the relegation group, exactly as in the real format.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

from backend.app.ml.features import LEAGUE_STAKES
from backend.app.ml.standings import _canon_season, _latest_season

# Elo → goals. Same shape as the national engine; MU is a touch higher because
# club football outscores international football.
MU_TOTAL   = 2.75
ELO_SCALE  = 220.0
HOME_ADV   = 60.0    # Elo points, club-level (smaller than the national 100)

# Leagues whose season is a double round-robin followed by a play-off phase,
# with regular-season points CARRIED OVER into position-based groups that each
# play their own double round-robin. Greek Super League (14 teams, 26 rounds):
#   1–4  → championship group (6 more games each; its winner is champion)
#   5–8  → qualifying group   (6 more games; ECL qualifier — no zone shown)
#   9–14 → relegation group   (10 more games; its bottom N are relegated)
# Verified against the 2025/26 final table: AEK 60 pts after 26 rounds → 72
# after the 6 championship-round games (P32).
#
# Each simulation therefore plays the WHOLE season: remaining regular-season
# fixtures, then the groups the simulated table produces. Title and relegation
# come from the group outcomes — not from the round-robin order, which in this
# format decides only who enters which group.
PLAYOFF_SPECS: dict[str, dict] = {
    "GreekSL": {
        "groups": [(1, 4), (5, 8), (9, 14)],   # 1-indexed position ranges
        "title_group": 0,
        "relegation_group": 2,
        "relegation_n": 2,
    },
}
PLAYOFF_LEAGUES = set(PLAYOFF_SPECS)
PLAYOFF_NOTE = (
    "Προσομοιώνεται ολόκληρη η σεζόν: κανονική περίοδος και στη συνέχεια τα "
    "play-offs (βαθμοί μεταφέρονται στους ομίλους θέσεων)."
)

DEFAULT_SIMS = 10_000


def _lambdas(elo_h: float, elo_a: float) -> tuple[float, float]:
    gd = (elo_h + HOME_ADV - elo_a) / ELO_SCALE
    return max(0.15, MU_TOTAL / 2 + gd / 2), max(0.15, MU_TOTAL / 2 - gd / 2)


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth. Fine for the small λ (~1-2) a football scoreline lives at."""
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1
        if k > 12:            # goals beyond this don't change any placing
            return k


def _season_rows(db, league: str) -> tuple[str | None, list[tuple]]:
    from sqlalchemy import text

    season = _latest_season(db, league)
    rows = db.execute(text(
        "SELECT season, home_team, away_team, home_goals, away_goals "
        "FROM matches WHERE league = :lg"
    ), {"lg": league}).fetchall()
    return season, [r for r in rows if _canon_season(r[0]) == season]


def simulate_league(db, league: str, sims: int = DEFAULT_SIMS, seed: int = 12345) -> dict | None:
    """Return title / top-zone / relegation probabilities for the current season.

    None when the competition can't be projected honestly: no fixtures, or a
    season that is already over.
    """
    season, rows = _season_rows(db, league)
    if not season or not rows:
        return None

    teams = sorted({t for _, h, a, _, _ in rows for t in (h, a)})
    if len(teams) < 4:
        return None

    # Points already banked, and the set of pairings already settled.
    base_pts: dict[str, int] = {t: 0 for t in teams}
    base_gd:  dict[str, int] = {t: 0 for t in teams}
    base_gf:  dict[str, int] = {t: 0 for t in teams}
    played_pairs: set[tuple[str, str]] = set()

    for _, h, a, hg, ag in rows:
        if hg is None or ag is None:
            continue
        played_pairs.add((h, a))
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

    # Full double round-robin minus what's already been played.
    remaining = [
        (h, a) for h in teams for a in teams
        if h != a and (h, a) not in played_pairs
    ]
    if not remaining:
        return None                      # season complete — the table IS the answer

    from backend.app.ml.club_elo import club_elo
    elo = club_elo(db)
    ratings = {t: elo.get(t, 1500.0) for t in teams}

    # Pre-compute each fixture's λ once instead of per simulation.
    fixtures = [(h, a, *_lambdas(ratings[h], ratings[a])) for h, a in remaining]

    stakes   = LEAGUE_STAKES.get(league, {})
    top_n    = int(stakes.get("cl", 0))
    bottom_n = int(stakes.get("relegation", 0))
    n_teams  = len(teams)

    spec = PLAYOFF_SPECS.get(league)

    title_ct = defaultdict(int)
    top_ct   = defaultdict(int)
    rel_ct   = defaultdict(int)          # bottom of the round-robin order
    playoff_rel_ct = defaultdict(int)    # relegated OUT of the relegation group
    pts_sum  = defaultdict(int)

    rng = random.Random(seed)
    for _ in range(sims):
        pts = dict(base_pts)
        gd  = dict(base_gd)
        gf  = dict(base_gf)
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

        # Ties inside a single simulation are broken the way the league does it;
        # the residual random.random() only splits teams identical on every
        # criterion, which real leagues settle by play-off or coin toss anyway.
        order = sorted(teams, key=lambda t: (pts[t], gd[t], gf[t], rng.random()), reverse=True)

        # Regular-season zones (championship-group entry / relegation-group
        # entry for playoff formats; final zones otherwise) are counted from
        # the round-robin order either way.
        for i, t in enumerate(order):
            pos = i + 1
            if top_n and pos <= top_n:
                top_ct[t] += 1
            if bottom_n and pos > n_teams - bottom_n:
                rel_ct[t] += 1

        if spec:
            # Play the play-off phase: position-based groups, points carried,
            # double round-robin inside each group.
            group_orders: list[list[str]] = []
            for lo, hi in spec["groups"]:
                members = order[lo - 1: min(hi, n_teams)]
                for h in members:
                    for a in members:
                        if h == a:
                            continue
                        lh, la = _lambdas(ratings[h], ratings[a])
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
                group_orders.append(sorted(
                    members, key=lambda t: (pts[t], gd[t], gf[t], rng.random()),
                    reverse=True))
            title_ct[group_orders[spec["title_group"]][0]] += 1
            rel_grp = group_orders[spec["relegation_group"]]
            for t in rel_grp[len(rel_grp) - spec["relegation_n"]:]:
                playoff_rel_ct[t] += 1
        else:
            title_ct[order[0]] += 1

        for t in teams:
            pts_sum[t] += pts[t]

    from backend.app.ml.standings import TOP_ZONE_LABEL

    # In a playoff format relegation is settled inside the relegation group, not
    # by the round-robin order — a team 13th after 26 rounds can climb out.
    effective_rel = playoff_rel_ct if spec else rel_ct

    projection = sorted(
        [
            {
                "team":        t,
                "p_title":     round(title_ct[t] / sims, 4),
                "p_top":       round(top_ct[t] / sims, 4),
                "p_relegated": round(effective_rel[t] / sims, 4),
                "exp_points":  round(pts_sum[t] / sims, 1),
            }
            for t in teams
        ],
        key=lambda r: (-r["p_title"], -r["exp_points"]),
    )

    return {
        "league":            league,
        "season":            season,
        "sims":              sims,
        "matches_played":    len(played_pairs),
        "matches_remaining": len(remaining),
        "top_zone":          TOP_ZONE_LABEL.get(league, "Europe"),
        "top_n":             top_n,
        "bottom_n":          bottom_n,
        "note":              PLAYOFF_NOTE if league in PLAYOFF_LEAGUES else None,
        "teams":             projection,
    }
