"""Rate limiter: real-client-IP extraction + in-memory sliding window."""
from types import SimpleNamespace

from backend.app.rate_limit import client_ip, _rate_limit_memory


def _req(xff=None, host="10.0.0.1", cf=None):
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    if cf is not None:
        headers["cf-connecting-ip"] = cf
    return SimpleNamespace(
        headers=SimpleNamespace(get=lambda k, d=None: headers.get(k, d)),
        client=SimpleNamespace(host=host),
    )


def test_client_ip_ignores_the_forwarded_chain_entirely():
    """This test used to assert the opposite, and the opposite was the bug.

    It read `client_ip(xff="203.0.113.7, 70.0.0.1") == "203.0.113.7"` — taking
    the first entry — and that entry is written by the CALLER. Cloudflare appends
    the connecting address rather than replacing the header, so a request sent
    with `X-Forwarded-For: 203.0.113.99` arrives as "203.0.113.99, <real ip>".
    Confirmed against the live site on 2026-09-09: the bucket landed in Redis as
    `rl:chat:203.0.113.99`, an address that does not exist. Every IP-keyed limit
    — the public LLM endpoint, login, register, the CSV export — was bypassable
    by rotating one header.

    A test can encode a vulnerability as a requirement, and this one did for as
    long as it existed.
    """
    assert client_ip(_req(xff="203.0.113.7, 70.0.0.1", host="10.0.0.1")) == "10.0.0.1"


def test_client_ip_uses_the_header_cloudflare_controls():
    """CF-Connecting-IP is set by Cloudflare to the connecting address and
    OVERWRITES anything the caller supplies, so it is the only forwarded address
    worth trusting. Verified live: a request carrying a forged CF-Connecting-IP
    still bucketed under the real one."""
    assert client_ip(_req(cf="203.0.113.7", xff="1.2.3.4, 5.6.7.8")) == "203.0.113.7"


def test_client_ip_falls_back_to_socket_peer():
    """Without Cloudflare — local dev, or a direct call — the socket peer is all
    there is. Behind the proxy that is one shared address for everyone, which
    limits every caller together: the safe direction to be wrong in."""
    assert client_ip(_req(xff=None, host="192.168.1.9")) == "192.168.1.9"


def test_memory_window_blocks_after_limit():
    key = "test:unit:blocks"
    assert _rate_limit_memory(key, max_calls=3, window=60)
    assert _rate_limit_memory(key, max_calls=3, window=60)
    assert _rate_limit_memory(key, max_calls=3, window=60)
    # 4th within window → blocked.
    assert not _rate_limit_memory(key, max_calls=3, window=60)


def test_separate_keys_have_independent_budgets():
    assert _rate_limit_memory("a:ip", max_calls=1, window=60)
    assert not _rate_limit_memory("a:ip", max_calls=1, window=60)
    # Different key (different user) still allowed.
    assert _rate_limit_memory("b:ip", max_calls=1, window=60)
