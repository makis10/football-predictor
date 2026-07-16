"""
League standings computed from the `matches` table.

No API call and no new table: the played results we already store ARE the table.
Recomputed on request (cheap — one indexed query per league) and cached briefly.

Two things this has to get right:

1. SEASON LABELS ARE INCONSISTENT IN THE DB.
   The CSV importer writes "2025/2026"; the API fetchers write "2025/26" — for
   the SAME season. Bundesliga 2025-26 is stored as 261 rows under "2025/2026"
   (Aug→Apr) plus 44 rows under "2025/26" (Apr→May). Grouping by the raw label
   would split one league table in two, each with half the matches. Everything
   here goes through _canon_season() first.

2. WHICH SEASON TO SHOW.
   The current season is the one with the latest fixtures. Between seasons it
   has no results yet (in July, EPL 2026/27 is all upcoming), and an all-zero
   table is useless — so we fall back to the last season that was actually
   played and flag it `is_final`, letting the UI say "final table" rather than
   pretending it is live.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

# Zone sizes (how many top / bottom places matter) come from the ML config, so
# the table and the "motivation" features can never disagree about them.
from backend.app.ml.features import LEAGUE_STAKES

# What the top zone MEANS, per competition — the colour is the same, the promise
# is not: 4th in the Premier League is a Champions League ticket, 4th in the
# Championship is a promotion play-off.
TOP_ZONE_LABEL: dict[str, str] = {
    "EPL":          "Champions League",
    "LaLiga":       "Champions League",
    "SerieA":       "Champions League",
    "Bundesliga":   "Champions League",
    "Ligue1":       "Champions League",
    "Eredivisie":   "Champions League",
    "PrimeiraLiga": "Champions League",
    "GreekSL":      "Europe",
    "Championship": "Promotion",
    "LeagueOne":    "Promotion",
    "BrazilSerieA": "Libertadores",
}
BOTTOM_ZONE_LABEL = "Relegation"

# UEFA competitions (2024 format): one 36-team league phase, then
#   1–8   → straight to the last 16
#   9–24  → knockout play-off round
#   25–36 → eliminated
# A UEFA season also contains a July qualifying knockout and a spring bracket
# under the SAME league id, so the table must be built from league-phase
# fixtures ONLY — hence the `round` column (migration 0030). API-Football names
# those rounds "League Phase - 1" … "League Phase - 8".
EUROPEAN_STRUCTURE: dict[str, dict[str, int]] = {
    "CL":  {"direct": 8, "playoff": 24},
    "EL":  {"direct": 8, "playoff": 24},
    "ECL": {"direct": 8, "playoff": 24},
}
_LEAGUE_PHASE_PREFIX = "league phase"


def is_league_phase(round_name: str | None) -> bool:
    return bool(round_name) and round_name.strip().lower().startswith(_LEAGUE_PHASE_PREFIX)

# Tie-breakers after points. Most leagues: goal difference, then goals scored.
# Brazil breaks ties on WINS first (CBF regulation), which reorders the table —
# not a cosmetic detail when it decides who goes down.
_WINS_FIRST = {"BrazilSerieA"}

_SEASON_RE = re.compile(r"^(\d{4})/(\d{2,4})$")


def _canon_season(season: str) -> str:
    """'2025/2026' and '2025/26' both → '2025/26'. Unknown formats pass through."""
    m = _SEASON_RE.match(season or "")
    if not m:
        return season
    start, end = m.group(1), m.group(2)
    return f"{start}/{end[-2:]}"


@dataclass
class StandingRow:
    position: int
    team: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_diff: int
    points: int
    # "top" | "playoff" (UEFA league phase only) | "bottom" | None — row colour
    zone: str | None


def _fetch_played(db, league: str) -> list[tuple]:
    from sqlalchemy import text

    rows = db.execute(text(
        "SELECT season, home_team, away_team, home_goals, away_goals, round "
        "FROM matches "
        "WHERE league = :lg AND home_goals IS NOT NULL AND away_goals IS NOT NULL"
    ), {"lg": league}).fetchall()

    # A UEFA season stacks a qualifying knockout, a league phase and a final
    # bracket under one league id. Only the league phase is a table; counting a
    # qualifier or a semi-final into it would be nonsense.
    if league in EUROPEAN_STRUCTURE:
        rows = [r for r in rows if is_league_phase(r[5])]
    return [(r[0], r[1], r[2], r[3], r[4]) for r in rows]


def _latest_season(db, league: str) -> str | None:
    """Canonical label of the season holding this league's latest fixture."""
    from sqlalchemy import text

    row = db.execute(text(
        "SELECT season FROM matches WHERE league = :lg "
        "ORDER BY match_date DESC LIMIT 1"
    ), {"lg": league}).fetchone()
    return _canon_season(row[0]) if row else None


def compute_standings(db, league: str, season: str | None = None) -> dict | None:
    """Return {league, season, is_final, top_zone, top_n, bottom_n, rows[]}.

    `season` (canonical or raw) pins a specific season; otherwise the current one
    is used, falling back to the last played season while the new one is empty.
    """
    played = _fetch_played(db, league)
    if not played:
        return None

    by_season: dict[str, list[tuple]] = {}
    for s, h, a, hg, ag in played:
        by_season.setdefault(_canon_season(s), []).append((h, a, hg, ag))

    if season:
        target = _canon_season(season)
    else:
        target = _latest_season(db, league)
        # The new season is on the fixture list but hasn't kicked off — show the
        # last completed table instead of 20 rows of zeros.
        if target not in by_season:
            target = max(by_season) if by_season else None
    if target not in by_season:
        return None

    # A season is "final" once it has no unplayed fixtures left.
    from sqlalchemy import text
    remaining = db.execute(text(
        "SELECT COUNT(*) FROM matches WHERE league = :lg AND home_goals IS NULL"
    ), {"lg": league}).scalar() or 0
    latest = _latest_season(db, league)
    is_final = (target != latest) or remaining == 0

    tbl: dict[str, dict] = {}

    def _row(team: str) -> dict:
        return tbl.setdefault(team, {
            "team": team, "played": 0, "won": 0, "drawn": 0, "lost": 0,
            "goals_for": 0, "goals_against": 0, "points": 0,
        })

    for home, away, hg, ag in by_season[target]:
        h, a = _row(home), _row(away)
        h["played"] += 1
        a["played"] += 1
        h["goals_for"] += hg
        h["goals_against"] += ag
        a["goals_for"] += ag
        a["goals_against"] += hg
        if hg > ag:
            h["won"] += 1;  h["points"] += 3;  a["lost"] += 1
        elif ag > hg:
            a["won"] += 1;  a["points"] += 3;  h["lost"] += 1
        else:
            h["drawn"] += 1; h["points"] += 1
            a["drawn"] += 1; a["points"] += 1

    wins_first = league in _WINS_FIRST
    ordered = sorted(
        tbl.values(),
        key=lambda r: (
            r["points"],
            r["won"] if wins_first else (r["goals_for"] - r["goals_against"]),
            (r["goals_for"] - r["goals_against"]) if wins_first else r["goals_for"],
            r["goals_for"],
        ),
        reverse=True,
    )

    n = len(ordered)
    euro = EUROPEAN_STRUCTURE.get(league)
    if euro:
        # Positional, not "bottom N": the zones are fixed by the format (top 8 /
        # 9–24 / 25–36), so a partial table mid-league-phase shades correctly
        # instead of marking whoever happens to be last as eliminated.
        top_n, playoff_to = euro["direct"], euro["playoff"]
        bottom_n = 0
    else:
        stakes  = LEAGUE_STAKES.get(league, {})
        top_n    = int(stakes.get("cl", 0))
        bottom_n = int(stakes.get("relegation", 0))
        playoff_to = 0

    rows: list[StandingRow] = []
    for i, r in enumerate(ordered):
        pos = i + 1
        zone = None
        if top_n and pos <= top_n:
            zone = "top"
        elif euro:
            zone = "playoff" if pos <= playoff_to else "bottom"
        elif bottom_n and pos > n - bottom_n:
            zone = "bottom"
        rows.append(StandingRow(
            position=pos, team=r["team"], played=r["played"],
            won=r["won"], drawn=r["drawn"], lost=r["lost"],
            goals_for=r["goals_for"], goals_against=r["goals_against"],
            goal_diff=r["goals_for"] - r["goals_against"],
            points=r["points"], zone=zone,
        ))

    return {
        "league":        league,
        "season":        target,
        "is_final":      is_final,
        "top_zone":      "Round of 16" if euro else TOP_ZONE_LABEL.get(league, "Europe"),
        "playoff_zone":  "Play-off" if euro else None,
        "bottom_zone":   "Eliminated" if euro else BOTTOM_ZONE_LABEL,
        "top_n":         top_n,
        "playoff_to":    playoff_to,
        "bottom_n":      bottom_n,
        "rows":          [asdict(r) for r in rows],
    }
