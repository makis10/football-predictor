"""Registration validation + bcrypt password hashing."""
import pytest
from pydantic import ValidationError

from backend.app.routers.auth import RegisterRequest, _hash, _verify


def test_valid_registration_normalizes_email():
    r = RegisterRequest(email="  User@Example.COM ", password="longenough", name="X")
    assert r.email == "user@example.com"


def test_short_password_rejected():
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@b.co", password="short")


def test_bad_email_rejected():
    with pytest.raises(ValidationError):
        RegisterRequest(email="not-an-email", password="longenough")


def test_password_hash_roundtrip():
    h = _hash("correct horse battery")
    assert _verify("correct horse battery", h)
    assert not _verify("wrong", h)


def test_password_over_72_bytes_does_not_crash():
    # bcrypt only uses the first 72 bytes; hashing/verifying must stay consistent.
    pw = "a" * 200
    h = _hash(pw)
    assert _verify(pw, h)
    # First 72 bytes identical → still verifies (documents the truncation).
    assert _verify("a" * 72, h)
