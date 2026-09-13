"""
Monte Carlo projection of a league season: title / Europe / relegation odds.

Same idea as the World Cup simulator, applied to a round-robin: take the points
already on the board, replay every match still to come thousands of times from
the clubs' current Elo, and count how often each team finishes where.

Where the remaining fixtures come from
--------------------------------------
We only ingest fixtures ~60 days ahead, so the DB holds e.g. 37 of the Premier
League's 380 matches. Simulating those 37 and stopping would answer a question
nobody asked. So "remaining" is the real unplayed rows we hold — repeat meetings
included — plus, for every ordered pairing we hold no row for yet, the meeting
a double round-robin still owes. Deriving the whole set from the team list
alone (the old rule) dropped real repeat meetings in split and triple
round-robin leagues (Finland, Scotland, Ireland) and declared their seasons
over with a third still to play.

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
    """(season, rows) for the league's current season, ordered by date.

    Each row is (home, away, home_goals, away_goals, match_date)."""
    from sqlalchemy import text

    season = _latest_season(db, league)
    rows = db.execute(text(
        "SELECT season, home_team, away_team, home_goals, away_goals, match_date "
        "FROM matches WHERE league = :lg ORDER BY match_date, id"
    ), {"lg": league}).fetchall()
    return season, [tuple(r[1:]) for r in rows if _canon_season(r[0]) == season]


def _split_fixtures(rows, teams, playoff: bool):
    """(regular_played, phase_played, regular_remaining) for one season.

    regular_remaining is every regular-season match still to play: the real
    unplayed rows we hold, plus each ordered pairing we hold no row for yet —
    the meeting a double round-robin still owes (fixtures are only ingested
    ~60 days ahead). It used to be the second part alone, every ordered pair
    minus the SET of pairs played, which silently dropped real repeat meetings.

    For play-off formats (PLAYOFF_SPECS) the regular season is exactly one
    meeting per ordered pair; a later meeting of the same pair belongs to the
    play-off phase the spec simulates, so it is returned in phase_played once
    played and never simulated as a regular fixture.
    """
    seen: set[tuple[str, str]] = set()
    regular_played, phase_played, scheduled = [], [], []
    for h, a, hg, ag, _d in rows:
        is_phase = playoff and (h, a) in seen
        seen.add((h, a))
        if hg is None or ag is None:
            if not is_phase:
                scheduled.append((h, a))
        elif is_phase:
            phase_played.append((h, a, hg, ag))
        else:
            regular_played.append((h, a, hg, ag))
    unseen = [(h, a) for h in teams for a in teams if h != a and (h, a) not in seen]
    return regular_played, phase_played, scheduled + unseen


def _group_ranges(groups, n_teams: int) -> list[tuple[int, int]]:
    """1-indexed (lo, hi) position ranges, the last group open-ended.

    With the GreekSL spec's fixed (9, 14), a 15th team — the state a
    club-name split produces — fell outside every group and was shown 0%
    relegated while finishing bottom."""
    last = len(groups) - 1
    return [(lo, n_teams if i == last else min(hi, n_teams))
            for i, (lo, hi) in enumerate(groups)]


def _tally(pts, gd, gf, h, a, hg, ag) -> None:
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


def simulate_league(db, league: str, sims: int = DEFAULT_SIMS, seed: int = 12345) -> dict | None:
    """Return title / top-zone / relegation probabilities for the current season.

    None when the competition can't be projected honestly: no fixtures, or a
    season that is already over.
    """
    season, rows = _season_rows(db, league)
    if not season or not rows:
        return None

    teams = sorted({t for h, a, *_ in rows for t in (h, a)})
    if len(teams) < 4:
        return None

    spec = PLAYOFF_SPECS.get(league)
    regular_played, phase_played, remaining = _split_fixtures(rows, teams, playoff=bool(spec))

    # Regular-season points banked so far; for play-off formats, the group
    # games already played are banked separately and carried on top.
    reg_pts = {t: 0 for t in teams}
    reg_gd, reg_gf = dict(reg_pts), dict(reg_pts)
    for h, a, hg, ag in regular_played:
        _tally(reg_pts, reg_gd, reg_gf, h, a, hg, ag)
    ph_pts = {t: 0 for t in teams}
    ph_gd, ph_gf = dict(ph_pts), dict(ph_pts)
    for h, a, hg, ag in phase_played:
        _tally(ph_pts, ph_gd, ph_gf, h, a, hg, ag)
    phase_done = {(h, a) for h, a, _, _ in phase_played}

    n_teams = len(teams)
    ranges = _group_ranges(spec["groups"], n_teams) if spec else []
    phase_left = 0
    if not remaining:
        if not spec:
            return None                  # season complete — the table IS the answer
        # Regular season over: the real table fixes the groups. Nothing is left
        # to project once every group game has been played as well.
        order0 = sorted(teams, key=lambda t: (reg_pts[t], reg_gd[t], reg_gf[t]), reverse=True)
        phase_left = sum(1 for lo, hi in ranges
                         for h in order0[lo - 1:hi] for a in order0[lo - 1:hi]
                         if h != a and (h, a) not in phase_done)
        if not phase_left:
            return None

    from backend.app.ml.club_elo import club_elo
    elo = club_elo(db)
    ratings = {t: elo.get(t, 1500.0) for t in teams}

    # Pre-compute each fixture's λ once instead of per simulation.
    fixtures = [(h, a, *_lambdas(ratings[h], ratings[a])) for h, a in remaining]

    stakes   = LEAGUE_STAKES.get(league, {})
    top_n    = int(stakes.get("cl", 0))
    bottom_n = int(stakes.get("relegation", 0))

    title_ct = defaultdict(int)
    top_ct   = defaultdict(int)
    rel_ct   = defaultdict(int)          # bottom of the round-robin order
    playoff_rel_ct = defaultdict(int)    # relegated OUT of the relegation group
    pts_sum  = defaultdict(int)

    rng = random.Random(seed)
    for _ in range(sims):
        pts, gd, gf = dict(reg_pts), dict(reg_gd), dict(reg_gf)
        for h, a, lh, la in fixtures:
            _tally(pts, gd, gf, h, a, _poisson(rng, lh), _poisson(rng, la))

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
            # The play-off phase: position-based groups, points carried, a
            # double round-robin inside each group — minus the group games
            # already played, whose real results are banked instead.
            for t in teams:
                pts[t] += ph_pts[t]
                gd[t] += ph_gd[t]
                gf[t] += ph_gf[t]
            group_orders: list[list[str]] = []
            for lo, hi in ranges:
                members = order[lo - 1:hi]
                for h in members:
                    for a in members:
                        if h == a or (h, a) in phase_done:
                            continue
                        lh, la = _lambdas(ratings[h], ratings[a])
                        _tally(pts, gd, gf, h, a, _poisson(rng, lh), _poisson(rng, la))
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
        "matches_played":    len(regular_played) + len(phase_played),
        "matches_remaining": len(remaining) + phase_left,
        "top_zone":          TOP_ZONE_LABEL.get(league, "Europe"),
        "top_n":             top_n,
        "bottom_n":          bottom_n,
        "note":              PLAYOFF_NOTE if league in PLAYOFF_LEAGUES else None,
        "teams":             projection,
    }
