#!/usr/bin/env python3
"""Would anchoring our probabilities to the market make them more accurate?

Market anchoring was removed on 2026-06-17 by directive, and the served
probabilities have been the pure model output since. The stats page then showed
the pure-model regime doing WORSE on the result than the anchored one it
replaced — 47.6% over 1,284 matches against 50.9% over 499 — which is a reason
to ask the question properly rather than argue about it.

This does not restore anchoring. It replays settled matches we already hold:
every one that carries BOTH our raw model probabilities and the bookmaker's
1x2, blended at a range of weights.

    p_blended = (1 - w) * p_model  +  w * p_market

w=0 is exactly what we serve today; w=1 is the bookmaker's own de-vigged
opinion. The bookmaker line is de-vigged by normalising the three implied
probabilities, which removes the margin but keeps the shape.

What the answer does NOT tell you: an anchored model cannot beat the market by
construction, so a higher number here buys accuracy and forecloses edge. That is
a decision about what the site is for, not a measurement.

    docker compose exec -T backend python scripts/compare_anchoring.py
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default=None,
                    help="only matches on/after this date (YYYY-MM-DD)")
    args = ap.parse_args()

    from sqlalchemy import text

    from backend.app.database import SessionLocal

    where = ["m.result IS NOT NULL",
             "p.raw_home_prob IS NOT NULL",
             "p.bm_home_odds IS NOT NULL",
             "p.bm_draw_odds IS NOT NULL",
             "p.bm_away_odds IS NOT NULL"]
    params: dict = {}
    if args.since:
        where.append("m.match_date >= :since")
        params["since"] = args.since

    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT p.raw_home_prob h, p.raw_draw_prob d, p.raw_away_prob a, "
            "       p.bm_home_odds oh, p.bm_draw_odds od, p.bm_away_odds oa, "
            "       m.result, m.match_date "
            "FROM predictions p JOIN matches m ON m.id = p.match_id "
            f"WHERE {' AND '.join(where)} ORDER BY m.match_date"), params).fetchall()
    finally:
        db.close()

    if not rows:
        print("No settled matches carry both our probabilities and a 1x2 line.")
        return 0

    print(f"{len(rows)} settled match(es)"
          + (f" since {args.since}" if args.since else "")
          + f", {rows[0].match_date} → {rows[-1].match_date}\n")

    print(f"  {'weight':>7s}  {'hit rate':>9s}  {'log loss':>9s}   what it is")
    best = None
    for w in (0.0, 0.15, 0.25, 0.35, 0.5, 0.65, 0.75, 1.0):
        hits = 0
        logloss = 0.0
        for r in rows:
            model = (float(r.h), float(r.d), float(r.a))
            # De-vig: the three implied probabilities sum to >1 by the margin;
            # normalising removes it and leaves the bookmaker's actual shape.
            raw = (1 / float(r.oh), 1 / float(r.od), 1 / float(r.oa))
            tot = sum(raw)
            market = tuple(x / tot for x in raw)

            p = tuple((1 - w) * m + w * k for m, k in zip(model, market))
            pick = "HDA"[max(range(3), key=lambda i: p[i])]
            if pick == r.result:
                hits += 1
            actual = "HDA".index(r.result)
            import math
            logloss -= math.log(max(p[actual], 1e-9))

        rate = hits / len(rows)
        ll = logloss / len(rows)
        label = ("what we serve today" if w == 0
                 else "the bookmaker alone" if w == 1 else "")
        print(f"  {w:7.2f}  {rate:9.1%}  {ll:9.4f}   {label}")
        if best is None or rate > best[1]:
            best = (w, rate, ll)

    print(f"\n  best hit rate at w={best[0]:.2f}: {best[1]:.1%} "
          f"(log loss {best[2]:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
