import os
import time
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.app.routers import admin, admin_users, auth, chat, matches, national, predictions, stats, users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("api")

# ── Optional Sentry error tracking ──────────────────────────────────────────────
# Inert unless SENTRY_DSN is set, so local/dev runs need no extra config.
if os.getenv("SENTRY_DSN"):
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=os.getenv("SENTRY_DSN"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
            environment=os.getenv("SENTRY_ENV", "production"),
        )
        logger.info("Sentry error tracking enabled.")
    except Exception as exc:  # pragma: no cover - never block startup on telemetry
        logger.warning("Sentry init failed (%s) — continuing without it.", exc)

app = FastAPI(
    title="Football Predictor API",
    description="ML-powered football match outcome predictions (over/under 2.5 goals + W/D/L probabilities).",
    version="1.0.0",
)

# Browsers never call the backend directly — all traffic goes through the
# server-side Next.js proxy (no CORS preflight). So the default is locked to the
# local frontend origin; override with CORS_ALLOWED_ORIGINS=https://site.com,...
# (or "*" to explicitly opt into wide-open, e.g. for ad-hoc API testing).
_CORS_ORIGINS_RAW = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
_CORS_ORIGINS = (
    ["*"] if _CORS_ORIGINS_RAW.strip() == "*"
    else [o.strip() for o in _CORS_ORIGINS_RAW.split(",") if o.strip()]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request logger ─────────────────────────────────────────────────────────────
# Skips noisy health-check + session polling endpoints.
_SKIP_PATHS = {"/health", "/api/auth/session"}

@app.middleware("http")
async def log_requests(request: Request, call_next):
    path = request.url.path
    if path in _SKIP_PATHS:
        return await call_next(request)

    # NOTE: X-User-Id / X-User-Email are client-supplied and untrusted — for
    # log correlation only, never used for access-control decisions.
    user_id    = request.headers.get("X-User-Id", "")
    user_email = request.headers.get("X-User-Email", "")
    user       = user_email or (f"id={user_id}" if user_id else "anon")

    t0 = time.monotonic()
    response = await call_next(request)
    ms = round((time.monotonic() - t0) * 1000)

    logger.info("%s %s [%s] → %d (%dms)", request.method, path, user, response.status_code, ms)
    return response

app.include_router(matches.router)
app.include_router(predictions.router)
app.include_router(national.router)
app.include_router(admin.router)
app.include_router(stats.router)
app.include_router(chat.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(admin_users.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
