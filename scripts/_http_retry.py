"""Shared retry-with-backoff wrapper for the scripts/ fetch_* jobs.

These run unattended via launchd; a bare `requests.get` has no protection
against a transient timeout/connection error or a 429/5xx right after the
machine wakes up — that silently drops the day's data for that source with
no second attempt. `get_with_retry` retries a few times with exponential
backoff before giving up, mirroring the ad-hoc single-retry-on-429 pattern a
couple of these scripts already had.
"""
from __future__ import annotations

import time

import requests

DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF = 2.0  # seconds; doubles each retry


def get_with_retry(
    url: str,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff: float = DEFAULT_BACKOFF,
    **kwargs,
) -> requests.Response:
    """requests.get with exponential-backoff retry on timeouts/connection
    errors/429/5xx. Raises (via raise_for_status or the last exception) if
    every attempt fails."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
        else:
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = requests.exceptions.HTTPError(
                    f"{resp.status_code} for {url}", response=resp
                )
            else:
                return resp

        if attempt < attempts:
            time.sleep(backoff * (2 ** (attempt - 1)))

    assert last_exc is not None
    raise last_exc
