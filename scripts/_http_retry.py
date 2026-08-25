"""Shared retry-with-backoff wrapper for the scripts/ fetch_* jobs.

These run unattended via launchd; a bare `requests.get` has no protection
against a transient timeout/connection error or a 429/5xx right after the
machine wakes up — that silently drops the day's data for that source with
no second attempt. `get_with_retry` retries a few times with exponential
backoff before giving up, mirroring the ad-hoc single-retry-on-429 pattern a
couple of these scripts already had.

API-Football's per-minute limit needs two extra mechanisms, added 2026-08-16
after a day in which 139 teams were dropped without a single error surfacing:

  · It reports "too many requests" as **HTTP 200** with
    `{"errors": {"rateLimit": "..."}}` in the body — the same silent-200 shape
    as the IP block that `preflight_api_football.py` exists to catch. Nothing
    raised, so the retry above never fired and every caller just logged a
    warning and moved on. `_is_rate_limited` now looks inside the body.

  · Retrying is the safety net, not the fix: a retry that fires inside the same
    minute burns another request off the DAILY quota to be told the same thing.
    `_throttle` keeps a sliding one-minute window per host and waits before the
    call instead, so the limit is never reached.

Both are scoped to the hosts in `_RATE_LIMITED_HOSTS`. Every other caller keeps
exactly the behaviour it had.
"""
from __future__ import annotations

import time
from collections import deque
from urllib.parse import urlparse

import requests

DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF = 2.0  # seconds; doubles each retry

# Exit code the fetch_* jobs use when API-Football refuses on its DAILY cap.
# run_daily.sh treats it as "the account is out of requests" — skip the rest of
# the API-Football steps — rather than "this step is broken", which pages and
# suppresses the heartbeat. On 2026-08-25 a mid-run cap turned three healthy
# steps into an urgent alert nobody could act on until the counter reset.
API_FOOTBALL_QUOTA_RC = 4


class QuotaExhausted(SystemExit):
    """API-Football's daily cap, carried as its own exit code.

    Python prints nothing when SystemExit carries an int, so the message is
    echoed here — the log line is what a reader needs, and every raise site
    would otherwise have to remember to print it first.
    """

    def __init__(self, msg: str) -> None:
        self.msg = msg
        print(msg, flush=True)
        super().__init__(API_FOOTBALL_QUOTA_RC)

    def __str__(self) -> str:
        return self.msg

# host → requests allowed per rolling minute.
# API-Football Pro is documented at 300/min; 270 leaves headroom for the clock
# skew between our timestamps and theirs, and for the fact that each script
# runs in its own process with its own window (run_daily runs them back to
# back, so two can briefly overlap at a boundary).
_RATE_LIMITED_HOSTS: dict[str, int] = {
    "v3.football.api-sports.io": 270,
}
_WINDOW_S = 60.0

# host → timestamps of recent requests. Process-local by design: these jobs are
# separate short-lived processes, and a shared store would be more machinery
# than the problem needs.
_calls: dict[str, deque] = {}


def _throttle(url: str) -> None:
    """Block until another request to `url`'s host fits inside the window."""
    host = urlparse(url).netloc
    cap = _RATE_LIMITED_HOSTS.get(host)
    if not cap:
        return

    q = _calls.setdefault(host, deque())
    now = time.monotonic()
    while q and now - q[0] >= _WINDOW_S:
        q.popleft()

    if len(q) >= cap:
        # Wait for the oldest call to age out, plus a hair so it definitely has.
        sleep_for = _WINDOW_S - (now - q[0]) + 0.05
        if sleep_for > 0:
            time.sleep(sleep_for)
        now = time.monotonic()
        while q and now - q[0] >= _WINDOW_S:
            q.popleft()

    q.append(time.monotonic())


def _is_rate_limited(resp: requests.Response) -> bool:
    """True for API-Football's HTTP-200 rate-limit reply.

    Deliberately narrow: only an `errors` MAPPING carrying a `rateLimit` key
    counts. A healthy response returns `errors` as an empty LIST, and the other
    error kinds (`Ip`, `requests`, `token`) are not transient — retrying those
    would spend the daily quota re-asking a question already answered.
    """
    if resp.status_code != 200:
        return False
    if urlparse(resp.url).netloc not in _RATE_LIMITED_HOSTS:
        return False
    try:
        errors = resp.json().get("errors")
    except Exception:
        return False
    return isinstance(errors, dict) and "rateLimit" in errors


def get_with_retry(
    url: str,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff: float = DEFAULT_BACKOFF,
    **kwargs,
) -> requests.Response:
    """requests.get with exponential-backoff retry on timeouts/connection
    errors/429/5xx, plus API-Football's HTTP-200 rate-limit body.

    Raises (via the last exception) if every attempt fails. A rate-limited
    response is raised as an HTTPError like a 429 would be, so callers that
    already handle transport failures need no change.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        _throttle(url)
        rate_limited = False
        try:
            resp = requests.get(url, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
        else:
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = requests.exceptions.HTTPError(
                    f"{resp.status_code} for {url}", response=resp
                )
            elif _is_rate_limited(resp):
                rate_limited = True
                last_exc = requests.exceptions.HTTPError(
                    f"rate limited (HTTP 200 body) for {url}", response=resp
                )
            else:
                return resp

        if attempt < attempts:
            # A rate limit clears on a clock, not on a backoff curve — waiting
            # 2s then 4s just spends two more requests inside the same minute.
            # Sit out enough of the window for it to actually drain.
            time.sleep(_WINDOW_S / 2 if rate_limited
                       else backoff * (2 ** (attempt - 1)))

    assert last_exc is not None
    raise last_exc
