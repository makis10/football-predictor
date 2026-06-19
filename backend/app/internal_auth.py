"""
Shared-secret guard for internal-only endpoints.

The backend is only meant to be reached through the Next.js proxy (which injects
the verified user identity as X-User-Id). Identity/auth endpoints therefore trust
X-User-Id — but that trust is only safe if the caller is genuinely the proxy.

This dependency requires a shared secret header (X-Internal-Secret) that only the
Next.js server knows (INTERNAL_API_SECRET env var, injected by the proxy route and
server-side fetch helpers). A direct caller to the backend port cannot forge it.

Defense-in-depth: combined with binding the backend port to 127.0.0.1 in
docker-compose, an external attacker can neither reach the port nor forge identity.

No-op when INTERNAL_API_SECRET is unset (local dev) — logs one warning so the
weakened posture is visible.
"""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import Header, HTTPException

log = logging.getLogger("internal_auth")

_SECRET = os.getenv("INTERNAL_API_SECRET", "")
_warned = False


def require_internal_secret(x_internal_secret: str = Header(default="")) -> None:
    """Reject requests that don't carry the shared proxy secret (when configured)."""
    global _warned
    if not _SECRET:
        if not _warned:
            log.warning(
                "INTERNAL_API_SECRET not set — internal endpoint auth is DISABLED. "
                "Set it in .env (and ensure the backend port is not publicly exposed)."
            )
            _warned = True
        return
    # Constant-time compare to avoid leaking the secret via timing.
    if not hmac.compare_digest(x_internal_secret, _SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")
