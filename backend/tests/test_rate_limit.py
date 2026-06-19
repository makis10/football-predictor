"""Rate limiter: real-client-IP extraction + in-memory sliding window."""
from types import SimpleNamespace

from backend.app.rate_limit import client_ip, _rate_limit_memory


def _req(xff=None, host="10.0.0.1"):
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    return SimpleNamespace(
        headers=SimpleNamespace(get=lambda k, d=None: headers.get(k, d)),
        client=SimpleNamespace(host=host),
    )


def test_client_ip_prefers_first_forwarded_for():
    assert client_ip(_req(xff="203.0.113.7, 70.0.0.1")) == "203.0.113.7"


def test_client_ip_falls_back_to_socket_peer():
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
