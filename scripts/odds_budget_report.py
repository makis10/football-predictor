#!/usr/bin/env python3
"""Where the Odds API credits go, per caller and per day.

Reads the ledger backend/app/odds_budget.py writes. Answers the only question
that matters before paying for a bigger plan: is the burn justified, or is some
job spending the month's allowance on data nothing reads?

    docker compose exec -T backend python scripts/odds_budget_report.py
    docker compose exec -T backend python scripts/odds_budget_report.py --days 30
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "backend", "data", "odds_usage.jsonl")

PLAN_CREDITS = 20_000          # the 20K plan
DAILY_BUDGET = PLAN_CREDITS / 31


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    if not os.path.isfile(PATH):
        print(f"No ledger yet at {PATH} — nothing has been metered.")
        return 0

    cutoff = date.today() - timedelta(days=args.days)
    by_day: dict[date, int] = collections.Counter()
    by_caller: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    free_calls = 0
    refused = refused_cost = 0

    with open(PATH, encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
                day = datetime.fromisoformat(row["at"]).date()
            except Exception:
                continue
            if day < cutoff:
                continue
            cost = row.get("cost", 0)
            status = row.get("status")
            # A refused call is not a charged one. With the plan out of credits
            # every request comes back 401 OUT_OF_USAGE_CREDITS and bills
            # nothing — counting those as spend turns an outage into a fake
            # overspend and would have argued for an upgrade nobody needs.
            # They are still worth showing: they are what the same schedule
            # WOULD cost once credits return.
            billed = status is not None and 200 <= status < 300
            if not billed:
                refused += 1
                refused_cost += cost
                continue
            by_day[day] += cost
            slot = by_caller[row.get("caller", "?")]
            slot[0] += cost
            slot[1] += 1
            if not cost:
                free_calls += 1

    if not by_day:
        print(f"No BILLED calls in the last {args.days}d.")
        if refused:
            print(f"  {refused} call(s) were refused (would have cost "
                  f"{refused_cost:,} credits on a live plan) — the account is "
                  f"out of credits, so nothing was charged.")
        return 0

    print(f"── credits by caller (last {args.days}d) " + "─" * 28)
    print(f"  {'caller':22s} {'calls':>7s} {'credits':>9s} {'per call':>9s}")
    for caller, (cost, calls) in sorted(by_caller.items(), key=lambda kv: -kv[1][0]):
        print(f"  {caller:22s} {calls:7d} {cost:9d} {cost / calls:9.2f}")

    print(f"\n── credits by day " + "─" * 44)
    for day in sorted(by_day):
        bar = "█" * min(50, round(by_day[day] / 20))
        flag = "  OVER" if by_day[day] > DAILY_BUDGET else ""
        print(f"  {day}  {by_day[day]:6d}  {bar}{flag}")

    days = len(by_day)
    total = sum(by_day.values())
    mean = total / days
    print(f"\n  {total:,} credits over {days} day(s) — mean {mean:,.0f}/day")
    print(f"  budget is {DAILY_BUDGET:,.0f}/day ({PLAN_CREDITS:,}/month)")
    print(f"  projected month: {mean * 31:,.0f}  "
          f"({'FITS' if mean * 31 <= PLAN_CREDITS else 'OVER BY '
              + format(mean * 31 - PLAN_CREDITS, ',.0f')})")
    if refused:
        print(f"\n  {refused} call(s) refused and NOT charged (would have been "
              f"{refused_cost:,} credits on a live plan).")
    if free_calls:
        print(f"\n  ({free_calls} free call(s) recorded — /sports and /events "
              f"cost nothing and are not counted above)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
