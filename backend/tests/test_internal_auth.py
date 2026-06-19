"""Guard that protects identity endpoints from direct/spoofed callers."""
import pytest
from fastapi import HTTPException

from backend.app import internal_auth as ia


def _call(secret_value, header_value):
    """Run require_internal_secret with a given configured secret + header."""
    orig = ia._SECRET
    ia._SECRET = secret_value
    try:
        ia.require_internal_secret(header_value)
        return "allowed"
    except HTTPException as e:
        return e.status_code
    finally:
        ia._SECRET = orig


def test_correct_secret_allows():
    assert _call("s3cr3t", "s3cr3t") == "allowed"


def test_wrong_secret_forbidden():
    assert _call("s3cr3t", "nope") == 403


def test_missing_secret_forbidden():
    assert _call("s3cr3t", "") == 403


def test_disabled_when_unset_allows_anything():
    # No secret configured (dev mode) → never blocks.
    assert _call("", "") == "allowed"
    assert _call("", "whatever") == "allowed"
