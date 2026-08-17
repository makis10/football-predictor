"""
Poll bookmaker odds for upcoming matches and store snapshots in odds_history.

One row per match per poll cycle.  The last two rows per match are compared
by the /predictions/{id}/analysis endpoint to compute movement arrows.
Rows older than 72 hours are pruned to keep the table lean.

Budget
------
The Odds API bills per market per region, and the plan is 20,000 credits a
MONTH — 645/day if it is to last 31 days.  Until 2026-08-15 this job spent
~1,540/day and the plan ran dry on the 13th of every month, leaving the site
with no live odds for the other ~18 days.  Three things fixed that, all of them
in this file or the launchd schedule:

  1. `with_btts=False` on the league fetch.  BTTS is an "additional market" and
     costs one request PER GAME.  `odds_history` has no BTTS column, so every
     one of those credits was fetched, parsed and dropped — ~1,100/day.
  2. Tiered polling (below): a match five days out does not need re-pricing
     every eight hours.
  3. The launchd schedule went 3-hourly → 8-hourly (00:00 / 08:00 / 16:00).

The remaining cost is one batch request per league that has something due,
2 credits each (1 region × 2 markets), so a full sweep of 27 leagues is 54.
"""
import os
import sys
from datetime import datetime, time as dtime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.app.cache import CACHE_MISS, cache_delete, cache_get, cache_set
from backend.app.database import SessionLocal
from backend.app.models.match import Match
from backend.app.models.odds_history import OddsHistory
from backend.app.ml.odds_analysis_service import (
    fetch_all_league_odds,
    _teams_match,
)
from sqlalchemy import func

# Only poll matches within this horizon (no point storing odds for matches
# more than 7 days away — the odds aren't reliable that far out anyway).
HORIZON_DAYS = 7
PRUNE_AFTER_HOURS = 72  # delete snapshots older than this

# ── Tiered polling ───────────────────────────────────────────────────────────
# A match is re-priced on a cadence set by how close its kickoff is. Odds move
# sharply in the last day and barely at all a week out, so polling both at the
# same rate spends most of the budget on the half that isn't moving.
#
# Read as: (hours until kickoff, minimum hours since that match's last
# snapshot). First row whose horizon matches wins. Thresholds sit just under
# the intended cadence — 6 < 8 so the near tier fires on EVERY 8-hourly run,
# 20 < 24 so the mid tier fires once a day, 44 < 48 so the far tier fires every
# other day. Without that slack a run starting a minute late would skip a tier
# and silently halve its cadence.
TIERS: tuple[tuple[float, float], ...] = (
    (48.0,    6.0),   # ≤2 days out  → every run
    (120.0,  20.0),   # ≤5 days out  → once a day
    (float("inf"), 44.0),   # further out → every other day
)

# ── Dry-league back-off ──────────────────────────────────────────────────────
# We hold fixtures for leagues The Odds API is not pricing yet — European
# qualifiers before the group stage, a domestic league still in its off-season.
# Those cost a wasted request on every single poll.
#
# They are NOT skipped by a hardcoded list: EL / ECL / Switzerland have no
# market today and will have one within weeks, and a list would have to be
# maintained by hand for every league twice a season.  Instead the league backs
# itself off after repeated empty answers and retries automatically.
#
# DRY_STRIKES is 3, not 1, on purpose. An empty response is usually a blip, not
# the truth: on 2026-08-04 the Eredivisie batch came back with zero games while
# the same request made by hand returned nine.  One bad answer must not blank a
# live league — three consecutive ones across a whole day is a real signal.
DRY_STRIKES   = 3
DRY_BACKOFF_S = 24 * 3600   # retry a dry league once a day
_DRY_COUNT    = "poll:dry_count:{}"
_DRY_UNTIL    = "poll:dry_until:{}"


def _lookup(home: str, away: str, league_odds: list) -> dict | None:
    for entry in league_odds:
        if _teams_match(entry["api_home"], home) and \
           _teams_match(entry["api_away"], away):
            ro = entry.get("raw_odds", {})
            if ro.get("home_win") or ro.get("away_win"):
                return ro
    return None


def _kickoff(match: Match, now: datetime) -> datetime:
    """Kickoff as an aware UTC datetime. Matches with no time on record are
    treated as kicking off at 20:00 — late enough that a fixture whose time is
    still unknown is not mistaken for one about to start."""
    t = match.kickoff_time or dtime(20, 0)
    return datetime.combine(match.match_date, t, tzinfo=timezone.utc)


def _is_due(match: Match, last_seen: datetime | None, now: datetime) -> bool:
    """True when this match's tier says it is time to re-price it."""
    if last_seen is None:
        return True                      # never priced — always worth one look
    hours_out = (_kickoff(match, now) - now).total_seconds() / 3600
    age_hours = (now - last_seen).total_seconds() / 3600
    for horizon, min_age in TIERS:
        if hours_out <= horizon:
            return age_hours >= min_age
    return False


def _dry_skip(league: str) -> bool:
    """True while a league is backed off. Presence of the key IS the flag —
    it expires on its own, so a league can never be parked permanently."""
    return cache_get(_DRY_UNTIL.format(league)) is not CACHE_MISS


def _record_dry(league: str) -> int:
    """Count an empty answer; back the league off once it has enough strikes."""
    key = _DRY_COUNT.format(league)
    got = cache_get(key)
    strikes = (got if isinstance(got, int) else 0) + 1
    cache_set(key, strikes, 7 * 24 * 3600)
    if strikes >= DRY_STRIKES:
        cache_set(_DRY_UNTIL.format(league), 1, DRY_BACKOFF_S)
    return strikes


def _account_level_failure(fetched: list[str], odds_by_league: dict) -> bool:
    """True when EVERY league we actually called came back empty.

    `_fetch_league_games_cached` swallows its own HTTP errors and returns [],
    so an exhausted plan (every call 401) is indistinguishable, one league at a
    time, from "this competition has no market yet".  Nothing real makes every
    league on earth go unpriced in the same minute, so a total blank is our
    problem, not theirs — and must not be written into the back-off state.
    """
    return bool(fetched) and not any(odds_by_league.get(x) for x in fetched)


def _record_live(league: str) -> None:
    """A league that answered is not dry — clear both markers so a league
    coming into season resumes full cadence immediately."""
    cache_delete(_DRY_COUNT.format(league))
    cache_delete(_DRY_UNTIL.format(league))


def main() -> None:
    now = datetime.now(timezone.utc)
    horizon = now.date() + timedelta(days=HORIZON_DAYS)
    prune_before = now - timedelta(hours=PRUNE_AFTER_HOURS)

    db = SessionLocal()
    try:
        # Prune old rows first
        deleted = db.query(OddsHistory).filter(
            OddsHistory.fetched_at < prune_before
        ).delete()
        if deleted:
            print(f"Pruned {deleted} stale odds snapshots", flush=True)

        # Upcoming matches within horizon
        upcoming: list[Match] = (
            db.query(Match)
            .filter(
                Match.match_date >= now.date(),
                Match.match_date <= horizon,
                Match.result.is_(None),   # skip already-finished
            )
            .all()
        )

        if not upcoming:
            print("No upcoming matches to poll", flush=True)
            db.commit()
            return

        # When each match was last snapshotted — one query, not one per match.
        last_seen: dict[int, datetime] = dict(
            db.query(OddsHistory.match_id, func.max(OddsHistory.fetched_at))
            .filter(OddsHistory.match_id.in_([m.id for m in upcoming]))
            .group_by(OddsHistory.match_id)
            .all()
        )

        due = [m for m in upcoming if _is_due(m, last_seen.get(m.id), now)]
        print(f"{len(upcoming)} upcoming match(es); {len(due)} due for a "
              f"snapshot this run", flush=True)
        if not due:
            print("Nothing due — no API calls made.", flush=True)
            db.commit()
            return

        # One fetch per league that has something due. A league we fetch for is
        # then matched against ALL its in-horizon matches, not just the due
        # ones: the response is already paid for, so pricing the rest is free.
        leagues = sorted({m.league for m in due})
        odds_by_league: dict[str, list] = {}
        skipped_dry: list[str] = []
        fetched: list[str] = []
        empty: list[str] = []
        for league in leagues:
            if _dry_skip(league):
                skipped_dry.append(league)
                odds_by_league[league] = []
                continue
            try:
                # with_btts=False: odds_history stores 1×2 + over only, and
                # BTTS costs one request PER GAME. See the module docstring.
                games = fetch_all_league_odds(league, with_btts=False)
                odds_by_league[league] = games
                fetched.append(league)
                if games:
                    print(f"  {league}: {len(games)} games", flush=True)
                else:
                    empty.append(league)
            except Exception as exc:
                # An exception is a transport failure, not evidence the league
                # is unpriced — it must not count toward the dry strikes.
                print(f"  {league}: error — {exc}", flush=True)
                odds_by_league[league] = []

        # Strikes are recorded only AFTER the whole sweep, because one empty
        # league and every empty league mean different things.
        #
        # `_fetch_league_games_cached` swallows its own HTTP errors and returns
        # [], so an exhausted account — every call 401 — is indistinguishable
        # per league from "this competition has no market yet". Recording
        # strikes then would park all 27 leagues for 24h over an account
        # problem, and they would stay parked into the day the plan resets.
        # Nothing real makes every league on earth go unpriced at once, so
        # treat a total blank as OUR fault and record nothing.
        if _account_level_failure(fetched, odds_by_league):
            print(f"  [warn] all {len(fetched)} league(s) returned nothing — "
                  f"treating as an account/transport failure, not as dry "
                  f"leagues. No back-off recorded. Check the plan's remaining "
                  f"credits.", flush=True)
        else:
            for league in fetched:
                if odds_by_league[league]:
                    _record_live(league)
                    continue
                strikes = _record_dry(league)
                note = (f" — backing off {DRY_BACKOFF_S // 3600}h"
                        if strikes >= DRY_STRIKES else "")
                print(f"  {league}: 0 games "
                      f"(strike {strikes}/{DRY_STRIKES}){note}", flush=True)

        if skipped_dry:
            print(f"  [dry] skipped {len(skipped_dry)} league(s) with no market: "
                  f"{', '.join(skipped_dry)}", flush=True)

        # Store a snapshot for each matched game
        stored = 0
        for match in upcoming:
            ro = _lookup(match.home_team, match.away_team,
                         odds_by_league.get(match.league, []))
            if not ro:
                continue

            snapshot = OddsHistory(
                match_id=match.id,
                home_odds=ro.get("home_win"),
                draw_odds=ro.get("draw"),
                away_odds=ro.get("away_win"),
                over_odds=ro.get("over_2_5"),
                fetched_at=now,
            )
            db.add(snapshot)
            stored += 1

        db.commit()
        print(f"Stored {stored} snapshot(s) across {len(leagues)} league(s)",
              flush=True)

    finally:
        db.close()


if __name__ == "__main__":
    main()
