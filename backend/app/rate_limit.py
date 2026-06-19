"""
Sliding-window rate limiter.

Backed by Redis (shared across processes/replicas) when available, falling back
to a per-process in-memory window when Redis is down. Both implement the same
sliding-window semantics.

Usage:
    from backend.app.rate_limit import rate_limit_check, client_ip
    if not rate_limit_check(f"chat:{client_ip(request)}", max_calls=30, window=60):
        raise HTTPException(status_code=429, detail="Too many requests.")
"""
from __future__ import annotations

import threading
import time
from collections import deque

# ── Real client IP ──────────────────────────────────────────────────────────────

def client_ip(request) -> str:
    """
    Best-effort real client IP.

    All browser traffic reaches the backend through the Next.js proxy, so
    request.client.host is the proxy/container IP — identical for every user.
    The proxy forwards the original client in X-Forwarded-For; take the FIRST
    entry (the original client; subsequent hops are appended by each proxy).
    Falls back to the socket peer when the header is absent.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


# ── In-memory fallback ──────────────────────────────────────────────────────────

_lock: threading.Lock = threading.Lock()
_windows: dict[str, deque] = {}

_check_count = 0
_PRUNE_EVERY  = 5_000
_PRUNE_MAX_IDLE = 300  # seconds — evict a key not seen for 5 min


def _rate_limit_memory(key: str, max_calls: int, window: int) -> bool:
    global _check_count
    now    = time.monotonic()
    cutoff = now - window
    with _lock:
        _check_count += 1
        if _check_count % _PRUNE_EVERY == 0:
            _prune_stale(now)
        dq = _windows.setdefault(key, deque())
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= max_calls:
            return False
        dq.append(now)
        return True


def _prune_stale(now: float) -> None:
    idle_cutoff = now - _PRUNE_MAX_IDLE
    stale = [k for k, dq in _windows.items() if not dq or dq[-1] < idle_cutoff]
    for k in stale:
        del _windows[k]


# ── Redis sliding window ─────────────────────────────────────────────────────────

def _rate_limit_redis(redis, key: str, max_calls: int, window: int) -> bool:
    """
    Sliding-window counter using a Redis sorted set of request timestamps.
    Atomic via a pipeline: evict old, count, add, expire. Returns False when the
    count already at/over the limit (the just-added entry is rolled back).
    """
    now = time.time()
    rkey = f"rl:{key}"
    cutoff = now - window
    member = f"{now}:{time.monotonic_ns()}"   # unique per call
    try:
        pipe = redis.pipeline()
        pipe.zremrangebyscore(rkey, 0, cutoff)
        pipe.zcard(rkey)
        pipe.zadd(rkey, {member: now})
        pipe.expire(rkey, window + 1)
        _, count, _, _ = pipe.execute()
        if count >= max_calls:
            # Roll back ONLY the entry we just added (not concurrent ones that
            # happen to share this timestamp).
            redis.zrem(rkey, member)
            return False
        return True
    except Exception:
        # Any Redis hiccup → fall back to the in-memory window for this call.
        return _rate_limit_memory(key, max_calls, window)


def rate_limit_check(key: str, max_calls: int, window: int) -> bool:
    """Return True (allowed) or False (rate-limited). Redis-backed when available."""
    from backend.app.cache import _get_redis
    r = _get_redis()
    if r is not None:
        return _rate_limit_redis(r, key, max_calls, window)
    return _rate_limit_memory(key, max_calls, window)
