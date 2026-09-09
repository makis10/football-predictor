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
    Real client IP, from a header the CLIENT cannot write.

    2026-09-09: this took the FIRST entry of X-Forwarded-For, and that entry is
    attacker-controlled. Cloudflare APPENDS the connecting IP to any
    X-Forwarded-For the caller sends, so `X-Forwarded-For: 203.0.113.99` arrives
    as "203.0.113.99, <real ip>" and the first entry is whatever the caller
    typed. Verified against the live site with one request: the bucket landed in
    Redis as `rl:chat:203.0.113.99`.

    Every IP-keyed limit on the site was therefore bypassable by rotating that
    header — the public LLM endpoint (real money per call), login and register
    (brute force), and the CSV export (scraping).

    CF-Connecting-IP is the fix: Cloudflare sets it to the connecting address and
    OVERWRITES any value the caller supplies, so it cannot be forged from
    outside. The Next proxy forwards it (see app/api/proxy/[...path]/route.ts).

    X-Forwarded-For is deliberately no longer consulted. The rightmost entry
    would be the nearest proxy rather than the client, and counting hops from the
    right is a guess about deployment topology that silently rots. Without
    CF-Connecting-IP we fall back to the socket peer, which behind the proxy is
    one shared address — that limits everyone together, which is the safe
    direction to be wrong in.
    """
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        cf = cf.strip()
        if cf:
            return cf
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
