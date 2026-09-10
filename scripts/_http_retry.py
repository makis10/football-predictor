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


# Exit code for "API-Football refused this machine's IP". Deliberately the value
# preflight_api_football.py exits with, so run_daily.sh reads a block the same
# way whether the pre-flight caught it at 06:00 or a step ran into it mid-run
# (the line dropped and came back on a new address).
API_FOOTBALL_BLOCKED_RC = 2


class IpNotWhitelisted(SystemExit):
    """API-Football's IP whitelist refused this machine, carried as exit 2.

    The block is answered as HTTP 200 with `{"errors": {"Ip": ...}}`, so it
    never raised: every caller logged it as one more per-league "API error" and
    carried on. Between 2026-08-01 and 2026-09-10 the odds poll wrote that line
    167 times and finished every one of those runs with exit 0. Nothing a caller
    does next can succeed — every request from this address gets the same answer
    — so the process ends here, before any caller can read the empty payload as
    "this competition has no fixtures".
    """

    def __init__(self, msg: str) -> None:
        self.msg = msg
        print(msg, flush=True)
        super().__init__(API_FOOTBALL_BLOCKED_RC)

    def __str__(self) -> str:
        return self.msg


def _ip_block_message(detail: object) -> str:
    return ("[fatal] API-Football refused this machine's IP: "
            f"{detail} — whitelist the current public IP "
            "(curl -s https://api.ipify.org) at https://dashboard.api-football.com. "
            "scripts/run_af_recovery.sh then replays what the block skipped.")


def raise_for_api_football_errors(body: object) -> None:
    """Raise API-Football's two account-level refusals as their exit codes.

    For callers that read the body themselves instead of going through
    get_with_retry. Both refusals hold for the rest of the process: an IP block
    exits 2 (IpNotWhitelisted), the daily cap exits 4 (QuotaExhausted). Any other
    error — a bad parameter for one league — is left to the caller.
    """
    if not isinstance(body, dict):
        return
    errors = body.get("errors")
    if not isinstance(errors, dict):
        return
    if "Ip" in errors:
        raise IpNotWhitelisted(_ip_block_message(errors["Ip"]))
    if "requests" in errors:
        raise QuotaExhausted(
            f"[fatal] API-Football daily quota exhausted: {errors['requests']}")


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


def _af_errors(resp: requests.Response) -> dict | None:
    """API-Football's `errors` mapping on an HTTP-200 reply, else None.

    A healthy response carries `errors` as an empty LIST; failures use a dict.
    Other hosts' bodies are never read — only API-Football speaks this dialect.
    """
    if resp.status_code != 200:
        return None
    if urlparse(resp.url).netloc not in _RATE_LIMITED_HOSTS:
        return None
    try:
        errors = resp.json().get("errors")
    except Exception:
        return None
    return errors if isinstance(errors, dict) else None


def _is_rate_limited(resp: requests.Response) -> bool:
    """True for API-Football's HTTP-200 rate-limit reply.

    Deliberately narrow: only an `errors` MAPPING carrying a `rateLimit` key
    counts. The other error kinds (`Ip`, `requests`, `token`) are not
    transient — retrying those would spend the daily quota re-asking a question
    already answered.
    """
    errors = _af_errors(resp)
    return errors is not None and "rateLimit" in errors


def _raise_if_ip_blocked(resp: requests.Response) -> None:
    """End the process on API-Football's HTTP-200 IP-whitelist refusal."""
    errors = _af_errors(resp)
    if errors is not None and "Ip" in errors:
        raise IpNotWhitelisted(_ip_block_message(errors["Ip"]))


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

    An API-Football IP-whitelist refusal is not retried: it raises
    IpNotWhitelisted (SystemExit, code 2), which the callers' `except Exception`
    does not catch — the process ends instead of reading the empty payload as
    data.
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
                # Never retried: a refused address stays refused for every
                # remaining attempt, and each attempt spends a request.
                _raise_if_ip_blocked(resp)
                return resp

        if attempt < attempts:
            # A rate limit clears on a clock, not on a backoff curve — waiting
            # 2s then 4s just spends two more requests inside the same minute.
            # Sit out enough of the window for it to actually drain.
            time.sleep(_WINDOW_S / 2 if rate_limited
                       else backoff * (2 ** (attempt - 1)))

    assert last_exc is not None
    raise last_exc
