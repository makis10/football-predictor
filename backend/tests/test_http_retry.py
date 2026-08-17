"""Does the shared fetch wrapper survive API-Football's rate limit?

On 2026-08-16 a single daily run logged 139 `{"errors":{"rateLimit":...}}`
replies and dropped 139 teams' stats. Not one of them raised: API-Football
reports the per-minute limit as **HTTP 200** with the complaint in the body, and
`get_with_retry` only ever inspected the status code. Same silent-200 shape as
the IP block, which is why `preflight_api_football.py` had to be written.

Two mechanisms are guarded here, and the distinction matters:
  · detection — the body is now read, so a rate limit retries instead of
    surfacing as "this team has no data";
  · throttling — the retry is a net, not a fix. Retrying inside the same minute
    spends another request off the DAILY quota to be told the same thing, so
    the window is respected BEFORE the call goes out.

Offline: requests.get and time.sleep are both stubbed, no network, no waiting.
"""
from __future__ import annotations

import time
from collections import deque

import pytest
import requests

import scripts._http_retry as hr

AF = "https://v3.football.api-sports.io/fixtures"
OTHER = "https://api.the-odds-api.com/v4/sports/"


class FakeResp:
    def __init__(self, url=AF, status=200, payload=None):
        self.url, self.status_code, self._payload = url, status, payload or {}

    def json(self):
        if self._payload is _BAD_JSON:
            raise ValueError("not json")
        return self._payload


_BAD_JSON = object()

RATE_LIMITED = {"errors": {"rateLimit": "Too many requests. Your rate limit is "
                                        "300 requests per minute."}}
HEALTHY = {"errors": [], "response": [{"id": 1}]}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Each test starts with an empty window and instant sleeps."""
    hr._calls.clear()
    slept: list[float] = []
    monkeypatch.setattr(hr.time, "sleep", lambda s: slept.append(s))
    yield slept
    hr._calls.clear()


# ── detection ────────────────────────────────────────────────────────────────

def test_http_200_rate_limit_body_is_detected():
    """The exact reply that dropped 139 teams."""
    assert hr._is_rate_limited(FakeResp(payload=RATE_LIMITED)) is True


def test_healthy_response_is_not_rate_limited():
    """A good API-Football reply carries `errors` as an empty LIST. Reading it
    as truthy would make every successful call retry."""
    assert hr._is_rate_limited(FakeResp(payload=HEALTHY)) is False


@pytest.mark.parametrize("errors", [
    {"Ip": "This IP is not allowed to call the API"},
    {"requests": "You have reached the request limit for the day"},
    {"token": "Invalid API key"},
])
def test_other_api_football_errors_are_not_retried(errors):
    """These are permanent for the run. Retrying an IP block or an exhausted
    DAILY quota spends two more requests to be told the same thing — and the
    day quota is the scarce resource the throttle exists to protect."""
    assert hr._is_rate_limited(FakeResp(payload={"errors": errors})) is False


def test_other_hosts_bodies_are_not_inspected():
    """Only API-Football speaks this dialect. Parsing every host's body would
    make an unrelated service's `rateLimit` field change our control flow."""
    assert hr._is_rate_limited(
        FakeResp(url=OTHER, payload=RATE_LIMITED)) is False


def test_unparseable_body_is_not_treated_as_rate_limited():
    assert hr._is_rate_limited(FakeResp(payload=_BAD_JSON)) is False


def test_non_200_is_not_a_body_rate_limit():
    """A real 429 is already handled by status code; this path is only for the
    200 that lies."""
    assert hr._is_rate_limited(
        FakeResp(status=429, payload=RATE_LIMITED)) is False


# ── retry behaviour ──────────────────────────────────────────────────────────

def test_rate_limited_call_retries_and_then_succeeds(monkeypatch):
    seq = [FakeResp(payload=RATE_LIMITED), FakeResp(payload=HEALTHY)]
    monkeypatch.setattr(hr.requests, "get", lambda *a, **k: seq.pop(0))
    assert hr.get_with_retry(AF).json() == HEALTHY
    assert seq == [], "the second attempt should have been made"


def test_persistent_rate_limit_raises_rather_than_returning_empty(monkeypatch):
    """The whole bug was that this returned a response the caller read as
    'no data'. It must raise so the caller's error path runs."""
    monkeypatch.setattr(hr.requests, "get",
                        lambda *a, **k: FakeResp(payload=RATE_LIMITED))
    with pytest.raises(requests.exceptions.HTTPError):
        hr.get_with_retry(AF, attempts=2)


def test_rate_limit_waits_long_enough_for_the_window_to_drain(_clean, monkeypatch):
    """A 2s exponential backoff fires inside the same minute and burns another
    request. The wait has to be a real slice of the window."""
    monkeypatch.setattr(hr.requests, "get",
                        lambda *a, **k: FakeResp(payload=RATE_LIMITED))
    with pytest.raises(requests.exceptions.HTTPError):
        hr.get_with_retry(AF, attempts=2)
    waits = [s for s in _clean if s >= 1]
    assert waits and max(waits) >= hr._WINDOW_S / 2, (
        f"waited {waits} — too short for a per-minute limit to clear"
    )


def test_healthy_call_makes_no_extra_requests(monkeypatch):
    calls = []
    monkeypatch.setattr(hr.requests, "get",
                        lambda *a, **k: calls.append(1) or FakeResp(payload=HEALTHY))
    hr.get_with_retry(AF)
    assert len(calls) == 1


# ── throttle ─────────────────────────────────────────────────────────────────

def test_throttle_waits_once_the_window_is_full(_clean):
    host = "v3.football.api-sports.io"
    cap = hr._RATE_LIMITED_HOSTS[host]
    now = time.monotonic()
    hr._calls[host] = deque([now] * cap)      # window already full
    hr._throttle(AF)
    assert any(s > 0 for s in _clean), "a full window must block before calling"


def test_throttle_stays_under_the_documented_limit():
    """API-Football documents 300/min. The cap must sit below it: our window is
    process-local and run_daily starts these scripts back to back, so two can
    overlap at a boundary."""
    for host, cap in hr._RATE_LIMITED_HOSTS.items():
        assert cap < 300, f"{host} cap {cap} leaves no headroom under 300/min"


def test_throttle_does_not_touch_other_hosts(_clean):
    for _ in range(1000):
        hr._throttle(OTHER)
    assert _clean == [], "only rate-limited hosts should ever be throttled"
    assert "api.the-odds-api.com" not in hr._calls


def test_old_calls_leave_the_window(_clean):
    """Timestamps older than the window must be discarded, or the throttle
    would sleep forever after a long-running job."""
    host = "v3.football.api-sports.io"
    cap = hr._RATE_LIMITED_HOSTS[host]
    hr._calls[host] = deque([time.monotonic() - hr._WINDOW_S - 1] * cap)
    hr._throttle(AF)
    assert _clean == [], "expired timestamps must not cause a wait"
    assert len(hr._calls[host]) == 1, "the window should have been swept"


def test_every_attempt_is_throttled(monkeypatch):
    """A retry is another request against the same limit. Throttling only the
    first attempt would let the retries burst straight through it."""
    import inspect
    src = inspect.getsource(hr.get_with_retry)
    body = src[src.index("for attempt in"):]
    assert "_throttle(url)" in body, "the throttle must sit inside the retry loop"
