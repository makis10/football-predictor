"""
Shared reschedule-aware fixture upsert used by all fixture-fetch scripts
(fetch_upcoming.py, fetch_greek_fixtures.py, fetch_european_fixtures.py,
fetch_club_friendlies.py).

Why it exists
-------------
Fixtures get rescheduled (weather, TV slots, cup clashes). The old per-script
logic matched on the EXACT (date, home, away, league) tuple, so a rescheduled
match never matched its DB row: the stale row stayed "pending" forever (its
result-updater lookup also uses the date) and a duplicate row appeared under
the new date. Observed in production: Panserraikos–Panetolikos stored on
2026-05-16 while the real kick-off was 05-17.

Matching order per incoming fixture:
  1. Exact (league, home, away, date)            → backfill/refresh kickoff_time
  2. Same (league, home, away), result IS NULL,
     date within ±window days                    → RESCHEDULE: update date+time
                                                   in place (preserves match id,
                                                   predictions, user tracking)
  3. No match                                    → INSERT new row

Returns (new_matches, touched_ids) so callers can optionally prune unplayed
rows of the same leagues that vanished from the source feed without touching
anything they didn't fetch.

Why the window is 14 days, not 5
--------------------------------
The common reschedule is not a TV slot moving a game by a day — it is a league
postponing its European entrants and refixing them in the next midweek, which
is ten to twelve days later. With a 5-day window every one of those inserted a
SECOND row and left the original sitting on a date the match will not be played
on. On 2026-08-17 five ties were stored twice this way (Anderlecht–Kortrijk,
Gent–OH Leuven, Lech–Jagiellonia, Raków–Górnik, Wolfsberger–LASK), all moved
from the 22–23 Aug weekend to 1–3 Sep.

Widening is safe because the key is the ORDERED pair. Two clubs meet twice in a
season, but never twice at the same ground inside a fortnight — and a two-legged
cup tie swaps the venue, so its second leg is a different key, not a reschedule.
The one case that could break it is a feed genuinely listing the same pairing
twice inside the window; `_ambiguous_pairs` detects that in the incoming batch
and refuses to treat either as a reschedule.

Authoritative vs corroborating feeds
------------------------------------
Two sources may cover the same league. GreekSL arrives from both API-Football
(step 4b of run_daily) and The Odds API (step 4), and they do not always agree:
on 2026-08-17 The Odds API had PAOK–Levadiakos on 22 Aug while API-Football —
and the actual schedule — said the 23rd. Both rows existed, both got a
prediction, and the day's accumulator ended up carrying the SAME match twice,
which multiplies a probability by itself and quietly overstates the slip.

So a feed that is not authoritative for a league passes `authoritative=False`:
it may still INSERT a fixture nobody else has, and it may fill in a kickoff time
on an exact match, but when it disagrees about the DATE of a fixture we already
hold it defers instead of either moving the row or adding a second one. Without
that, widening the window above would have been actively worse: the two feeds
would take turns dragging the same row between the 22nd and the 23rd every day.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select


def _ambiguous_pairs(fixtures: list[dict]) -> set[tuple]:
    """Pairings the incoming batch itself lists more than once.

    If a feed hands us two fixtures for the same (league, home, away), they are
    two real matches — collapsing the second onto the first as a "reschedule"
    would delete a fixture. Such pairings skip the reschedule branch entirely
    and are matched by exact date only.
    """
    from collections import Counter
    counts = Counter((f["league"], f["home_team"], f["away_team"]) for f in fixtures)
    return {k for k, n in counts.items() if n > 1}


def upsert_fixtures(
    db,
    fixtures: list[dict],
    reschedule_window_days: int = 14,
    authoritative: bool = True,
) -> tuple[list, set[int]]:
    """Insert or update fixtures; reschedule-aware. See module docstring.

    `authoritative=False` marks a corroborating feed: it never moves a fixture
    another source already dated, and never adds a second row for one. See the
    module docstring for why GreekSL needs this.
    """
    from backend.app.models.match import Match

    new_matches: list = []
    touched_ids: set[int] = set()
    skipped = backfilled = rescheduled = deferred = 0
    ambiguous = _ambiguous_pairs(fixtures)

    for f in fixtures:
        # 1. Exact match
        exists = db.scalars(
            select(Match).where(
                Match.match_date == f["match_date"],
                Match.home_team  == f["home_team"],
                Match.away_team  == f["away_team"],
                Match.league     == f["league"],
            )
        ).first()
        if exists:
            if f.get("kickoff_time") is not None and exists.kickoff_time != f["kickoff_time"]:
                exists.kickoff_time = f["kickoff_time"]
                backfilled += 1
            # Backfill the stage onto rows inserted before we stored it — without
            # this, existing cup fixtures stay NULL forever and the league-phase
            # table can't tell them apart from a qualifier.
            if f.get("round") and exists.round != f["round"]:
                exists.round = f["round"]
            skipped += 1
            touched_ids.add(exists.id)
            continue

        # 2. Reschedule: same pairing, unresolved, nearby date
        pair = (f["league"], f["home_team"], f["away_team"])
        candidate = None
        if pair not in ambiguous:
            window = timedelta(days=reschedule_window_days)
            candidate = db.scalars(
                select(Match).where(
                    Match.home_team  == f["home_team"],
                    Match.away_team  == f["away_team"],
                    Match.league     == f["league"],
                    Match.result.is_(None),
                    Match.match_date >= f["match_date"] - window,
                    Match.match_date <= f["match_date"] + window,
                )
            ).first()
        if candidate is not None and not authoritative:
            # We hold this tie on another date from a source that outranks this
            # one. Moving it would corrupt a correct date; inserting would give
            # the fixture two rows and let one accumulator carry it twice.
            deferred += 1
            touched_ids.add(candidate.id)
            print(f"  = deferred {f['home_team']} vs {f['away_team']} "
                  f"({f['league']}): keeping {candidate.match_date}, "
                  f"feed says {f['match_date']}")
            continue
        if candidate is not None:
            old_date = candidate.match_date
            candidate.match_date   = f["match_date"]
            candidate.kickoff_time = f.get("kickoff_time")
            rescheduled += 1
            touched_ids.add(candidate.id)
            print(f"  ↻ rescheduled {f['home_team']} vs {f['away_team']} "
                  f"({f['league']}): {old_date} → {f['match_date']}")
            continue

        # 3. New fixture
        m = Match(
            match_date=f["match_date"],
            kickoff_time=f.get("kickoff_time"),
            league=f["league"],
            season=f["season"],
            round=f.get("round"),      # cups only; NULL for domestic leagues
            home_team=f["home_team"],
            away_team=f["away_team"],
        )
        db.add(m)
        new_matches.append(m)

    db.commit()
    for m in new_matches:
        db.refresh(m)
        touched_ids.add(m.id)

    print(f"  Inserted {len(new_matches)} new, {skipped} unchanged, "
          f"{rescheduled} rescheduled"
          + (f", {deferred} deferred to the authoritative feed" if deferred else "")
          + (f", kickoff updated on {backfilled}" if backfilled else "")
          + ".")
    return new_matches, touched_ids


# Minimum share of a league's held, unplayed, in-window fixtures that a feed
# response must account for before we believe the rest were cancelled.
#
# 0.5 sits far above every honest case and far below every observed failure. On
# 2026-08-17 BSA answered for 5 of 71 (7%); a real round of cancellations is one
# or two fixtures out of dozens (95%+ coverage). Raising this toward 1.0 would
# start refusing to prune genuinely cancelled matches; lowering it toward 0
# restores the bug.
MIN_FEED_COVERAGE = 0.5


def prune_vanished(
    db,
    leagues: list[str],
    touched_ids: set[int],
    horizon_days: int = 60,
) -> int:
    """
    Delete unplayed fixtures of the given leagues that the source feed no
    longer lists (cancelled / moved beyond recognition). Scope is strictly
    [today, today + horizon_days] — the window the feed actually covered —
    and only the given leagues; fixtures beyond the horizon, other leagues,
    past matches, and anything seen in this run are never touched, so user
    tracking and predictions on live fixtures survive.

    CALLER CONTRACT: `leagues` must contain ONLY leagues this run actually
    received fixtures for, and `touched_ids` the rows it matched. An empty
    response is not evidence that a league's fixtures were cancelled — it is
    almost always the feed declining to answer.

    2026-08-09: football-data.org returned "0 fixtures" for PrimeiraLiga,
    Eredivisie and CL while answering normally for the other seven leagues. The
    caller passed all ten league codes regardless, so every unplayed fixture of
    those three inside a 60-day window was deleted as "vanished" — 129 real
    matches, including a Groningen–Utrecht kicking off three hours later. The
    two guards below make that unrepeatable even if a caller gets it wrong.

    2026-08-17: the SAME failure, one level subtler, and the guards above let it
    straight through. BSA answered with **5 fixtures** while we held 71 unplayed
    in the window, so BrazilSerieA was legitimately "a league the feed answered
    for" — and 66 real fixtures were deleted, the whole Brazilian schedule out to
    October. Re-querying the same endpoint by hand minutes later returned 81.

    A partial answer is not a cancellation notice. Guard 3 therefore checks
    COVERAGE PER LEAGUE: if the run matched less than MIN_FEED_COVERAGE of the
    unplayed fixtures we hold for that league in this window, the answer is
    treated as unreliable and that league is not pruned at all. Threshold, not
    absolute count, because leagues differ in size by 10×; and per league,
    because one flaky competition must not shield or doom the other nine.
    """
    from datetime import date as _date

    from sqlalchemy import delete, func, select

    from backend.app.models.match import Match

    # Guard 1 — the landmine. `notin_(empty)` is a no-op, so the WHERE collapsed
    # to `True` and the statement became "delete every unplayed fixture of these
    # leagues in the window". Nothing seen means nothing to reconcile against.
    if not touched_ids:
        print("  Prune skipped: this run matched no fixtures at all "
              "(treating as a feed failure, not mass cancellation).")
        return 0

    if not leagues:
        return 0

    today = _date.today()
    hi = today + timedelta(days=horizon_days)

    def _in_window():
        return (
            Match.result.is_(None),
            Match.match_date >= today,
            Match.match_date <= hi,
        )

    # Guard 3 — coverage. How much of each league did this run actually match?
    held = dict(db.execute(
        select(Match.league, func.count())
        .where(*_in_window())
        .where(Match.league.in_(leagues))
        .group_by(Match.league)
    ).all())
    matched = dict(db.execute(
        select(Match.league, func.count())
        .where(*_in_window())
        .where(Match.league.in_(leagues))
        .where(Match.id.in_(touched_ids))
        .group_by(Match.league)
    ).all())

    prunable, withheld = [], []
    for lg in leagues:
        n_held = held.get(lg, 0)
        if n_held == 0:
            continue                      # nothing to prune either way
        coverage = matched.get(lg, 0) / n_held
        if coverage < MIN_FEED_COVERAGE:
            withheld.append((lg, matched.get(lg, 0), n_held, coverage))
        else:
            prunable.append(lg)

    for lg, m, h, cov in withheld:
        print(f"  [warn] {lg}: the feed accounted for only {m}/{h} "
              f"({cov:.0%}) of the fixtures we hold in this window — treating "
              f"that as a partial answer, NOT {h - m} cancellations. "
              f"Not pruned.")

    if not prunable:
        return 0

    result = db.execute(
        delete(Match)
        .where(*_in_window())
        .where(Match.league.in_(prunable))
        .where(Match.id.notin_(touched_ids))
    )
    db.commit()
    if result.rowcount:
        print(f"  Pruned {result.rowcount} vanished fixture(s) in {prunable}.")
    return result.rowcount
