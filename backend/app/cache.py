"""
Thin Redis wrapper used by all in-process caches.

Falls back to a no-op NullCache when Redis is unavailable so the backend
stays functional (just without persistent caching).  All values are stored
as JSON strings — callers pass/receive plain Python dicts, lists, or strings.

Cache miss vs stored-None distinction
--------------------------------------
cache_get() returns CACHE_MISS (a singleton) on a miss, and the actual value
(which may be None / null) on a hit.  Callers check `if result is CACHE_MISS`
instead of `if result is None`, which allows caching None/null legitimately
(e.g. "no injuries found" is a valid cacheable result).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

# Sentinel returned by cache_get() on a cache MISS.
# Distinct from None so callers can cache None values (e.g. "no injuries").
CACHE_MISS: object = object()

# ── Redis client (lazy singleton) ─────────────────────────────────────────────

_redis = None
_redis_ok = False


def _get_redis():
    """
    Return a live Redis client, or None if unavailable.
    Retries the connection lazily: after a failure, reconnects on the next call
    so a Redis restart is picked up without a process restart.
    If an existing client is present but appears unhealthy, clears it for retry.
    """
    global _redis, _redis_ok
    if _redis is not None and _redis_ok:
        # Quick liveness check — resets if Redis became unavailable mid-deploy.
        try:
            _redis.ping()
            return _redis
        except Exception:
            log.warning("Redis ping failed — will reconnect on next call.")
            _redis = None
            _redis_ok = False

    if _redis is not None and not _redis_ok:
        # Previous attempt failed; retry connection.
        _redis = None

    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis as _lib
        client = _lib.from_url(url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        _redis = client
        _redis_ok = True
        log.info("Redis connected at %s", url)
    except Exception as exc:
        log.warning("Redis unavailable (%s) — falling back to no-op cache", exc)
        _redis = object()   # non-None sentinel so we don't retry on every single call
        _redis_ok = False
    return _redis if _redis_ok else None


# ── Public API ─────────────────────────────────────────────────────────────────

def cache_get(key: str) -> Any:
    """
    Return the deserialized value for key, or CACHE_MISS on miss/error.
    The returned value may legitimately be None (stored JSON null).
    """
    r = _get_redis()
    if r is None:
        return CACHE_MISS
    try:
        raw = r.get(key)
        if raw is None:
            return CACHE_MISS
        return json.loads(raw)
    except Exception as exc:
        log.debug("cache_get(%s) error: %s", key, exc)
        return CACHE_MISS


def cache_set(key: str, value: Any, ttl: int) -> None:
    """Serialize value and store with TTL (seconds). Silently skips on error."""
    r = _get_redis()
    if r is None:
        return
    try:
        r.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception as exc:
        log.debug("cache_set(%s) error: %s", key, exc)


def cache_delete(key: str) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.delete(key)
    except Exception as exc:
        log.debug("cache_delete(%s) error: %s", key, exc)


def cache_delete_pattern(pattern: str) -> None:
    """Delete all keys matching a glob pattern (e.g. 'stats:*')."""
    r = _get_redis()
    if r is None:
        return
    try:
        keys = r.keys(pattern)
        if keys:
            r.delete(*keys)
    except Exception as exc:
        log.debug("cache_delete_pattern(%s) error: %s", pattern, exc)
