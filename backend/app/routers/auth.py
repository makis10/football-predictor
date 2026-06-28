"""
Auth router — register, login, OAuth upsert.

NextAuth.js calls:
  POST /auth/oauth    — create/update user from OAuth (Google)
  POST /auth/register — create user from email+password
  POST /auth/login    — verify email+password, return user dict

All endpoints return a minimal user dict that NextAuth stores in the JWT.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.internal_auth import require_internal_secret
from backend.app.models.user import User
from backend.app.rate_limit import client_ip, rate_limit_check

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(require_internal_secret)],
)

# 10 attempts/min per IP — blocks credential stuffing / brute force while
# leaving plenty of headroom for legitimate retries.
_AUTH_RATE_LIMIT  = 10
_AUTH_RATE_WINDOW = 60  # seconds

# bcrypt only hashes the first 72 BYTES of a password; encode and truncate
# explicitly so hashing and verification stay consistent (and never raise on
# very long inputs).
_BCRYPT_MAX_BYTES = 72

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _hash(password: str) -> str:
    return _bcrypt.hashpw(password.encode()[:_BCRYPT_MAX_BYTES], _bcrypt.gensalt()).decode()


def _verify(password: str, hashed: str) -> bool:
    return _bcrypt.checkpw(password.encode()[:_BCRYPT_MAX_BYTES], hashed.encode())


def _rate_limit(request: Request, bucket: str) -> None:
    if not rate_limit_check(f"auth:{bucket}:{client_ip(request)}", _AUTH_RATE_LIMIT, _AUTH_RATE_WINDOW):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.")


# ── Schemas ───────────────────────────────────────────────────────────────────

class OAuthUpsertRequest(BaseModel):
    email: str
    name:  Optional[str] = None
    image: Optional[str] = None
    provider:    str = "google"
    provider_id: str


class RegisterRequest(BaseModel):
    email:    str
    password: str
    name:     Optional[str] = None

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v

    @field_validator("password")
    @classmethod
    def _valid_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email:    str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    id:       int
    email:    str
    name:     Optional[str]
    image:    Optional[str]
    is_admin: bool = False

    model_config = {"from_attributes": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "image": u.image, "is_admin": getattr(u, "is_admin", False)}


def _record_login(user: User, db: Session) -> None:
    """
    Bump login_count and set last_login_at to now (UTC). Also set last_seen_at:
    a login IS activity, and a user who only browses public pages never triggers
    the middleware's authenticated-request bump — so without this their last_seen
    would stay NULL ("—" in the admin panel).
    Does NOT commit — callers are responsible for committing so we avoid
    double-commits (one for the upsert, one for the login tracking).
    """
    now = datetime.now(timezone.utc)
    user.last_login_at = now
    user.last_seen_at  = now
    user.login_count   = (user.login_count or 0) + 1
    # intentionally no db.commit() here


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/oauth", response_model=UserOut, status_code=status.HTTP_200_OK)
def oauth_upsert(body: OAuthUpsertRequest, db: Session = Depends(get_db)):
    """Create or update OAuth user. Called by NextAuth credentials callback."""
    user = db.query(User).filter(User.email == body.email).first()
    if user:
        # Update name/image from OAuth provider in case they changed
        if body.name:
            user.name = body.name
        if body.image:
            user.image = body.image
        user.provider    = body.provider
        user.provider_id = body.provider_id
    else:
        user = User(
            email=body.email,
            name=body.name,
            image=body.image,
            provider=body.provider,
            provider_id=body.provider_id,
        )
        db.add(user)
    _record_login(user, db)
    db.commit()          # single commit covers upsert + login tracking
    db.refresh(user)
    return _user_out(user)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    _rate_limit(request, "register")
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=body.email,
        name=body.name,
        hashed_password=_hash(body.password),
        provider="credentials",
    )
    db.add(user)
    db.flush()          # assign user.id without closing the transaction
    _record_login(user, db)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    _rate_limit(request, "login")
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not _verify(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _record_login(user, db)
    db.commit()          # single commit for login tracking
    return _user_out(user)
