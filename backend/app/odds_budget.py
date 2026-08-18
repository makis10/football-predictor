"""Count what each caller spends on The Odds API.

The plan is 20,000 credits a MONTH — 645/day to last 31 days. It ran dry on the
13th in August, and the fixes that followed (dropping the per-game BTTS market,
tiered polling, an 8-hourly schedule) were reasoned about on paper: nobody ever
measured where the credits actually went, before or after. This does.

Cost is not "one credit per call". Per the published rules:

    /sports                       free
    /sports/{key}/events          free
    /sports/{key}/odds            markets × regions
    /sports/{key}/events/{id}/odds  markets × regions
    /sports/{key}/scores          1, or 2 when daysFrom is passed
    /historical/...               10 × markets × regions

So `markets=h2h,totals&regions=eu` is 2 credits a call, not 1 — which is why a
27-league sweep costs 54 and not 27. Free endpoints are recorded too, at cost 0:
knowing a call was free is worth as much as knowing one was not, and it stops
anyone "optimising" away the seam check, which costs nothing.

Append-only JSONL. One line per request, a few hundred bytes a day. Never
raises: a metering bug must not take down the fetch it is measuring.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "odds_usage.jsonl")
_LOCK = threading.Lock()

FREE = 0


def cost_of(url: str, params: dict | None) -> int:
    """Credits a request bills, from its URL shape and parameters."""
    params = params or {}
    markets = len([m for m in (params.get("markets") or "").split(",") if m])
    regions = len([r for r in (params.get("regions") or "").split(",") if r])
    if "/historical/" in url:
        return 10 * max(markets, 1) * max(regions, 1)
    if "/scores" in url:
        return 2 if params.get("daysFrom") is not None else 1
    if "/odds" in url:
        return max(markets, 1) * max(regions, 1)
    return FREE          # /sports and /sports/{key}/events


def record(caller: str, url: str, params: dict | None = None,
           status: int | None = None) -> int:
    """Log one request and return what it cost. Safe to call from anywhere."""
    try:
        credits = cost_of(url, params)
        # The key rides in `params`; never let it reach the ledger.
        endpoint = url.split("the-odds-api.com/v4", 1)[-1].split("?", 1)[0]
        row = {
            "at":      datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "caller":  caller,
            "endpoint": endpoint,
            "markets": (params or {}).get("markets", ""),
            "regions": (params or {}).get("regions", ""),
            "cost":    credits,
            "status":  status,
        }
        with _LOCK:
            with open(_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return credits
    except Exception:
        return 0


def get(caller: str, url: str, **kwargs):
    """requests.get, metered. Records the cost whether or not the call works.

    A 401 is not billed, and a timeout may be — the ledger records the ATTEMPT,
    which is what a working plan would have been charged. That is the number
    worth planning around.
    """
    import requests

    status = None
    try:
        resp = requests.get(url, **kwargs)
        status = resp.status_code
        return resp
    finally:
        record(caller, url, kwargs.get("params"), status)
