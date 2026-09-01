"""
Cut the day's suggested accumulators, and settle yesterday's.

Run once a day from run_daily.sh, AFTER predictions are computed.

Two jobs, in this order:

  1. **Settle** every open ticket whose fixtures have all finished. A leg is
     graded from the final score by ml.tickets.settle_market; the ticket wins
     only if every leg does.
  2. **Generate** today's slips from the upcoming card and freeze them.

Why frozen and not computed on request: a slip that silently reshuffles as odds
move can never be graded, and a hit rate over retroactively-rewritten slips is
not a hit rate. See backend/app/models/ticket.py.

Horizon: starts at the configured window (72h) and widens to 5 then 7 days only
if the shorter card cannot fill all five profiles. A midweek August card really
does leave 17 usable fixtures, which fills three. The window actually used is
stored on every ticket and shown on the page, so a leg five days out is never a
surprise.

Idempotent: re-running on the same day replaces that day's slips (they are keyed
(generated_for, profile)) as long as they are still open. Settled slips are
never touched — rewriting a graded ticket would launder a loss into a win.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import delete, select                       # noqa: E402
from sqlalchemy.orm import selectinload                     # noqa: E402

from backend.app.database import SessionLocal               # noqa: E402
from backend.app.ml.poisson import (                        # noqa: E402
    compute_extended_poisson_stats, fit_lambdas_to_probs,
)
from backend.app.ml.tickets import (                        # noqa: E402
    PROFILES, build_tickets, candidate_legs, settle_market,
)
from backend.app.models.match import Match                  # noqa: E402
from backend.app.models.prediction import Prediction        # noqa: E402
from backend.app.models.ticket import Ticket, TicketLeg     # noqa: E402

# Widen only when the shorter card cannot fill the ladder.
HORIZON_STEPS = (3, 5, 7)

# How far past its own horizon a slip's leg may be pushed before the slip is
# voided rather than left open. A day or two of TV rescheduling is normal; a
# month is a different fixture in every way that matters to the reader.
STALE_LEG_GRACE_DAYS = 7


# ── Settling ──────────────────────────────────────────────────────────────────

def settle_open_tickets(db) -> tuple[int, int]:
    """Grade every open ticket whose legs have all finished.

    Returns (tickets_settled, legs_graded). A ticket with even one unfinished
    leg is left open — a slip is not lost until it is actually lost, and
    grading it early would show the reader a loss that has not happened.
    """
    open_tickets = list(db.scalars(
        select(Ticket).options(selectinload(Ticket.legs))
        .where(Ticket.outcome.is_(None))
    ).all())
    if not open_tickets:
        return 0, 0

    match_ids = {l.match_id for t in open_tickets for l in t.legs}
    matches = {m.id: m for m in db.scalars(
        select(Match).where(Match.id.in_(match_ids))).all()}

    settled = graded = voided = 0
    for t in open_tickets:
        # A leg row disappears when its fixture is deleted — a cancellation, or
        # prune_vanished reaping a feed no-show (ON DELETE CASCADE). Grading the
        # survivors would settle a 4-fold on three legs while `total_odds` still
        # prices four, quietly inflating the record. Void it instead; voids are
        # excluded from every hit-rate and ROI figure.
        if len(t.legs) != t.num_legs:
            t.outcome = "void"
            t.settled_at = datetime.now(timezone.utc)
            voided += 1
            print(f"  [void] ticket {t.id} ({t.profile}): {t.num_legs} legs cut, "
                  f"{len(t.legs)} remain — a fixture was deleted.")
            continue

        # A leg whose fixture has been POSTPONED out of the slip's own window
        # is not the bet the reader was shown. Jagiellonia–Pogoń moved from 16
        # Aug to 16 December, and the two slips carrying it sat "still running"
        # on the page while every other slip from those days had long been
        # graded — a 15 August accumulator advertised as live in September, and
        # it would have stayed there until Christmas.
        #
        # The slip's own horizon is the standard: it was offered as "fixtures
        # over the next N days", so a leg beyond that plus a week of ordinary
        # rescheduling is a different proposition. Void, not lose — nothing
        # about it was wrong, it simply cannot be settled as offered.
        stale_leg = next(
            (matches[l.match_id] for l in t.legs
             if l.match_id in matches
             and matches[l.match_id].result is None
             and (matches[l.match_id].match_date - t.generated_for).days
                 > (t.horizon_days or 7) + STALE_LEG_GRACE_DAYS),
            None)
        if stale_leg is not None:
            t.outcome = "void"
            t.settled_at = datetime.now(timezone.utc)
            voided += 1
            print(f"  [void] ticket {t.id} ({t.profile}) cut {t.generated_for}: "
                  f"{stale_leg.home_team} v {stale_leg.away_team} was postponed "
                  f"to {stale_leg.match_date} — beyond the slip's "
                  f"{t.horizon_days}d horizon.")
            continue

        all_done = True
        for leg in t.legs:
            m = matches.get(leg.match_id)
            if m is None or m.home_goals is None or m.away_goals is None:
                all_done = False
                continue
            if leg.won is None:
                leg.won = settle_market(leg.market, m.home_goals, m.away_goals)
                graded += 1
        if all_done and t.legs:
            t.outcome = "won" if all(l.won for l in t.legs) else "lost"
            t.settled_at = datetime.now(timezone.utc)
            settled += 1

    db.commit()
    if voided:
        print(f"  {voided} ticket(s) voided (deleted or postponed fixture).")
    return settled, graded


# ── Generating ────────────────────────────────────────────────────────────────

def collect_legs(db, horizon_days: int) -> dict[int, list]:
    """Candidate legs for every fixture kicking off inside the window.

    Excluded, and why:
      • insufficient_data — both teams unknown to the model, so every such
        fixture carries the identical default prediction. Not a selection.
      • confidence 'low'  — includes all club friendlies, whose training
        distribution we do not cover (rotation, 3×30' halves, trialists).
      • already kicked off — a slip nobody can still place.
    """
    today = date.today()
    now_utc = datetime.now(timezone.utc)

    rows = db.execute(
        select(Match, Prediction)
        .join(Prediction, Prediction.match_id == Match.id)
        .where(Match.result.is_(None))
        .where(Match.match_date >= today)
        .where(Match.match_date < today + timedelta(days=horizon_days))
        .order_by(Match.match_date, Match.id)
    ).all()

    legs_by_match: dict[int, list] = {}
    for m, p in rows:
        if p.insufficient_data or p.confidence == "low":
            continue
        if m.kickoff_time is not None:
            ko = datetime.combine(m.match_date, m.kickoff_time, tzinfo=timezone.utc)
            if ko <= now_utc:
                continue

        # λ must be FITTED to the served probabilities. The λ stored on the
        # prediction row are feature-state values and are a global constant for
        # upcoming fixtures — using them would give every fixture on the card
        # the same goal lines.
        poisson = None
        fitted = fit_lambdas_to_probs(
            p.home_win_prob, p.away_win_prob, p.over_2_5_prob, p_btts=p.btts_prob)
        if fitted:
            lam_h, lam_a, rho, diag, diag0 = fitted
            poisson = compute_extended_poisson_stats(
                lam_h, lam_a, rho=rho, diag=diag, diag0=diag0)

        legs = candidate_legs(
            match_id=m.id, league=m.league,
            home_team=m.home_team, away_team=m.away_team,
            kickoff=m.match_date.isoformat(), confidence=p.confidence,
            home_win_prob=p.home_win_prob, draw_prob=p.draw_prob,
            away_win_prob=p.away_win_prob, over_2_5_prob=p.over_2_5_prob,
            btts_prob=p.btts_prob, poisson=poisson,
            bm_home=p.bm_home_odds, bm_draw=p.bm_draw_odds, bm_away=p.bm_away_odds,
            bm_over=p.bm_over_odds, bm_under=p.bm_under_odds,
            bm_btts_yes=p.bm_btts_yes_odds, bm_btts_no=p.bm_btts_no_odds,
        )
        if legs:
            legs_by_match[m.id] = legs
    return legs_by_match


def generate(db, *, replace: bool) -> tuple[int, int]:
    """Build and store today's slips. Returns (built, horizon_days_used)."""
    today = date.today()

    existing = list(db.scalars(
        select(Ticket).where(Ticket.generated_for == today)).all())
    if existing and not replace:
        print(f"  {len(existing)} ticket(s) already exist for {today} — "
              f"pass --replace to rebuild. Nothing to do.")
        return len(existing), existing[0].horizon_days
    if existing:
        # A VOID is not a result. The rule being protected here is "never
        # rewrite a graded ticket", because turning a lost slip into a won one
        # launders the record — but a void was never won or lost: it is what we
        # do when a leg's fixture disappears underneath it (a duplicate row
        # merged away, a cancelled match). Treating it as locked meant a data
        # repair could leave the day showing a voided slip and no replacement,
        # which is exactly what happened on 2026-08-17 after PAOK–Levadiakos
        # was collapsed back into one fixture.
        locked = [t for t in existing if t.outcome not in (None, "void")]
        if locked:
            # Should not happen the same day, but if it does, refuse rather
            # than overwrite a graded result.
            print(f"  [skip] {len(locked)} of today's tickets are already "
                  f"settled — refusing to rebuild the day.")
            return len(existing), existing[0].horizon_days
        voided = sum(1 for t in existing if t.outcome == "void")
        db.execute(delete(Ticket).where(Ticket.generated_for == today))
        db.commit()
        print(f"  Cleared {len(existing)} ticket(s) for {today}"
              + (f" ({voided} voided by a deleted fixture)" if voided else "")
              + ".")

    best: tuple[list, int, int] = ([], HORIZON_STEPS[0], 0)
    for horizon in HORIZON_STEPS:
        legs_by_match = collect_legs(db, horizon)
        built = build_tickets(legs_by_match)
        print(f"  horizon {horizon}d → {len(legs_by_match)} usable fixture(s), "
              f"{len(built)}/{len(PROFILES)} ticket(s)")
        if len(built) > best[2]:
            best = (built, horizon, len(built))
        if len(built) == len(PROFILES):
            break

    built, horizon, _ = best
    if not built:
        print("  No ticket could be built from any horizon — card too thin.")
        return 0, horizon

    for t in built:
        row = Ticket(
            generated_for=today, profile=t.profile,
            total_odds=t.total_odds, combined_prob=t.combined_prob,
            num_legs=len(t.legs), horizon_days=horizon,
        )
        row.legs = [
            TicketLeg(match_id=l.match_id, market=l.market, prob=l.prob,
                      odds=l.odds, estimated=l.estimated)
            for l in t.legs
        ]
        db.add(row)
        print(f"    {t.profile:<9} {len(t.legs)} legs  odds {t.total_odds:7.2f}  "
              f"P {t.combined_prob*100:5.2f}%  "
              f"({t.estimated_legs} estimated price(s))")
    db.commit()
    return len(built), horizon


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--replace", action="store_true",
                    help="rebuild today's slips if they already exist (open ones only)")
    ap.add_argument("--settle-only", action="store_true",
                    help="grade finished tickets and stop")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        print("Settling finished tickets …")
        settled, graded = settle_open_tickets(db)
        print(f"  {settled} ticket(s) settled, {graded} leg(s) graded.")

        if args.settle_only:
            return 0

        print("Generating today's tickets …")
        built, horizon = generate(db, replace=args.replace)
        print(f"Done — {built} ticket(s) for {date.today()} "
              f"(horizon {horizon}d).")

        # The endpoint caches for 5 minutes; drop it so a manual run shows up
        # immediately instead of leaving the operator wondering.
        try:
            from backend.app.cache import cache_delete
            cache_delete("tickets:current")
        except Exception:  # noqa: BLE001 — cache is best-effort
            pass
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
