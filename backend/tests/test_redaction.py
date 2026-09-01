"""Credentials must not survive into anything we print.

The Odds API takes its key as a query parameter and requests copies the whole
URL into the text of an HTTPError, so every `print(f"ERROR: {e}")` in a fetch
script is a place the live key can reach a log file. It did: when the month's
credits ran out on 2026-08-17 the key was written into daily.log and
odds-poll.log in full, once per failing league per poll.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from backend.app.redaction import redact

ROOT = pathlib.Path(__file__).resolve().parents[2]


# The fixture below is a MADE-UP key. The first version of this test used the
# real one, copied out of the log it was written to stop appearing in logs —
# and committed it to a public repository, where it sat for a week. Redaction
# tests are exactly the place that mistake is easiest to make.


def test_a_failing_url_loses_the_key_but_keeps_the_diagnosis(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "fake-key-for-this-test-only-0000")
    exc = Exception(
        "401 Client Error: Unauthorized for url: "
        "https://api.the-odds-api.com/v4/sports/soccer_greece_super_league/"
        "scores/?apiKey=fake-key-for-this-test-only-0000&daysFrom=3")

    out = redact(exc)

    assert "fake-key-for-this-test-only-0000" not in out
    assert "401" in out and "soccer_greece_super_league" in out


def test_every_credential_we_hold_is_covered(monkeypatch):
    for var in ("ODDS_API_KEY", "API_SPORTS_KEY", "GROQ_API_KEY",
                "FOOTBALL_DATA_API_KEY", "INTERNAL_API_SECRET"):
        monkeypatch.setenv(var, f"secret-value-for-{var}")
        assert f"secret-value-for-{var}" not in redact(
            Exception(f"boom secret-value-for-{var} boom")), var


def test_a_short_env_value_is_not_treated_as_a_secret(monkeypatch):
    """Replacing a 1–2 character value would shred the message instead of
    protecting anything — no real key is that short."""
    monkeypatch.setenv("ODDS_API_KEY", "x")

    assert redact(Exception("connection refused")) == "connection refused"


def test_redact_never_raises_from_inside_an_except_block():
    class Hostile:
        def __str__(self):
            raise RuntimeError("nope")

    assert redact(Hostile()) == "<unprintable>"


@pytest.mark.parametrize("script", [
    "update_european_results.py", "update_results.py",
    "fetch_upcoming.py", "download_xg.py",
])
def test_no_fetch_script_prints_a_bare_exception(script):
    """The regression guard. Each of these calls an API whose failure text can
    carry a URL; printing the exception unfiltered is what leaked the key."""
    src = (ROOT / "scripts" / script).read_text()
    bare = re.findall(r'print\(f"[^"]*\{e\}[^"]*"\)', src)

    assert not bare, f"{script} prints a raw exception: {bare}"


def test_no_test_hardcodes_a_real_looking_api_key():
    """The mistake this file exists to prevent, made inside this file.

    A 32-character hex string in the suite is either a real credential or
    indistinguishable from one, and a redaction test is the likeliest place to
    paste a live key by accident — the failing log line is right there.
    """
    import re
    from pathlib import Path

    tests = Path(__file__).resolve().parent
    hexkey = re.compile(r"\b[0-9a-f]{32}\b")
    offenders = {}
    for path in tests.glob("test_*.py"):
        hits = hexkey.findall(path.read_text(encoding="utf-8"))
        if hits:
            offenders[path.name] = hits[:3]

    assert not offenders, (
        f"32-char hex literals that look like live keys: {offenders}")
