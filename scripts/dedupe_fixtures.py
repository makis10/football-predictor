"""
Collapse the same fixture stored twice under two spellings of a club.

How this happens: several feeds name the same club differently, and a fixture
is keyed by (league, date, home, away). Until an alias exists, "SC Braga vs
Železničar Pančevo" and "Sp Braga vs Železničar Pančevo" are two rows — two
predictions, two cards on the site, and the club's Elo split across both. Adding
the alias fixes future ingests but leaves the rows already written, so this
reconciles them.

Which row wins: the OLDEST one. It is the row odds_history snapshots, tracked
matches and user bets point at, and losing those is worse than losing a
prediction that compute_predictions.py regenerates for free. The keeper is
renamed to the canonical training-data spelling; the newer twins are deleted
(their predictions go with them via ON DELETE CASCADE).

Refuses to touch any group where more than one row already has a result — that
is not a spelling duplicate, it is two genuinely different matches, and merging
them would corrupt the accuracy record.

Dry run by default. Nothing is written without --apply.

Usage:
  docker compose exec -T backend python scripts/dedupe_fixtures.py
  docker compose exec -T backend python scripts/dedupe_fixtures.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


# Two unsettled rows for the same ORDERED pairing are one fixture: in a
# round-robin a club hosts another once a season, and a two-legged cup tie
# swaps the venue, so the ordered pair stays unique either way.
#
# This is what catches the postponements no window can reach. Jagiellonia–Pogoń
# moved from 16 Aug to 16 DECEMBER; the old row predated migration 0033 so it
# carried no feed id, the 14-day reschedule could not span four months, and it
# sat unplayable for ever — keeping two accumulators "still running" on the site
# a fortnight after every other slip from those days had been graded.
#
# Friendlies are the exception: the same clubs really can meet twice at the same
# ground in one pre-season.
_REPEATABLE_PAIRINGS = {"ClubFriendly"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge duplicate fixtures caused by name drift")
    ap.add_argument("--days-back", type=int, default=45,
                    help="How far back to look (default 45)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually write. Without this the script only reports.")
    args = ap.parse_args()

    from backend.app.database import SessionLocal
    from backend.app.models.match import Match
    from scripts.team_resolver import canonical as canon

    db = SessionLocal()
    try:
        rows = db.query(Match).filter(
            Match.match_date >= date.today() - timedelta(days=args.days_back)
        ).all()

        # The key is the tie, NOT the ordered pair: a fixture written before the
        # draw settled the venue and again afterwards differs only by which
        # side is home. Four such pairs sat in the DB on 2026-08-07 — the site
        # listed "Pafos v RB Salzburg" and "RB Salzburg v Pafos" on the same
        # day, with different predictions on each.
        groups: dict[tuple, list[Match]] = defaultdict(list)
        for m in rows:
            # Same feed id is the same match, whatever the dates say. This is
            # the one grouping that needs no date at all: on 2026-08-23
            # "Kifisia vs AEK" sat on both the 29th and the 30th, and both rows
            # carried API-Football id 1593299 — the day-keyed grouping below
            # could never see it, and the daily alert had to catch it instead.
            if m.result is None and m.league not in _REPEATABLE_PAIRINGS:
                # EVERY unsettled row gets a pairing key, including ones that
                # carry a feed id. The stale row and the real fixture must land
                # in the SAME group or they never meet — filing the id-carrying
                # half under its id and the other half under its pairing was the
                # first attempt at this, and it found nothing at all.
                groups[(m.league, "pairing",
                        _slug(canon(m.home_team)) + "|" + _slug(canon(m.away_team)))].append(m)
                continue
            if m.api_fixture_id and m.result is None:
                groups[(m.league, "apiid", m.api_fixture_id)].append(m)
                continue
            sides = frozenset((_slug(canon(m.home_team)), _slug(canon(m.away_team))))
            groups[(m.league, m.match_date, sides)].append(m)

        dupes = {k: v for k, v in groups.items() if len(v) > 1}
        if not dupes:
            print("No duplicate fixtures found.")
            return

        renamed = deleted = skipped = 0
        for key, members in sorted(dupes.items(), key=lambda kv: str(kv[0][1])):
            members.sort(key=lambda m: m.id)
            settled = [m for m in members if m.result is not None]
            if len(settled) > 1:
                print(f"  [skip] {key[0]} {key[1]} — {len(settled)} rows already have a "
                      f"result; these are different matches, not a spelling duplicate")
                skipped += 1
                continue

            # Prefer a settled row as the keeper (it carries the real outcome),
            # otherwise the oldest — the one other tables reference.
            keeper = settled[0] if settled else members[0]
            # Grouped by feed id, the members disagree about the DATE and the
            # newest row carries the correction the feed just published. Move
            # the keeper onto it rather than keeping the stale day.
            if key[1] in ("apiid", "pairing"):
                newest = max(members, key=lambda m: m.id)
                if keeper.match_date != newest.match_date:
                    print(f"    ↻ {keeper.match_date} → {newest.match_date} "
                          f"({key[1]} {key[2]})")
                    if args.apply:
                        keeper.match_date   = newest.match_date
                        keeper.kickoff_time = newest.kickoff_time
                # Adopt the feed id too. Without it the surviving row is still
                # the id-less one, so the next postponement past the reschedule
                # window splits it again and we are back here.
                if args.apply and newest.api_fixture_id and not keeper.api_fixture_id:
                    keeper.api_fixture_id = newest.api_fixture_id
            losers = [m for m in members if m.id != keeper.id]
            want_h, want_a = canon(keeper.home_team), canon(keeper.away_team)

            print(f"  {key[0]} {key[1] if key[1] != 'apiid' else f'{key[1]} {key[2]}'}: keep id={keeper.id} "
                  f"({keeper.home_team!r} vs {keeper.away_team!r})"
                  + (f" → rename to ({want_h!r} vs {want_a!r})"
                     if (want_h, want_a) != (keeper.home_team, keeper.away_team) else "")
                  + f"; drop {', '.join(str(m.id) for m in losers)}")

            if args.apply:
                if (want_h, want_a) != (keeper.home_team, keeper.away_team):
                    keeper.home_team, keeper.away_team = want_h, want_a
                    renamed += 1
                for m in losers:
                    db.delete(m)
                    deleted += 1

        if args.apply:
            db.commit()
            print(f"\nApplied: {renamed} renamed, {deleted} deleted, {skipped} skipped.")
            print("Run compute_predictions.py to re-price anything left without a prediction.")
        else:
            print(f"\nDRY RUN — {len(dupes)} duplicate group(s), {skipped} unsafe to merge. "
                  f"Re-run with --apply to write.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
