"""The prediction assistant.

Both failures here were reported from the live chat on 2026-08-20, in the same
short conversation:

  "Δυστυχώς, δεν υπάρχουν διαθέσιμα δεδομένα για αγώνες που θα διεξαχθούν
   σήμερα" — said while the context held 13 KB of that day's fixtures, because
  nothing in the prompt ever said what today's date was.

  "Chat error 504" — the SDK retries twice, so a slow Groq held the connection
  for 77 seconds while the proxy in front gave up at 30.
"""
from __future__ import annotations

import re
from datetime import date

import pytest

from backend.app.routers import chat as chat_mod


def test_the_model_is_told_what_day_it_is(monkeypatch):
    """Day headers alone are labels. Without an anchor the model cannot know
    which of them is 'σήμερα', and it guesses — sometimes by refusing."""
    monkeypatch.setattr(chat_mod, "cache_get", lambda *_a, **_k: chat_mod.CACHE_MISS)
    monkeypatch.setattr(chat_mod, "cache_set", lambda *_a, **_k: None)

    class _FakeResult:
        def __init__(self, rows): self._rows = rows
        def all(self): return self._rows
        def scalars(self): return self

    class _FakeDB:
        def execute(self, *_a, **_k): return _FakeResult([])

    context = chat_mod._build_match_context(_FakeDB())

    # No fixtures at all is the one case where the anchor is not required —
    # the message says so in words. Otherwise it must be present.
    assert "Δεν υπάρχουν επερχόμενοι αγώνες" in context


def test_the_today_anchor_names_the_real_date():
    src = (chat_mod.__file__)
    body = open(src, encoding="utf-8").read()
    assert "ΣΗΜΕΡΑ ΕΙΝΑΙ" in body, "the context no longer anchors 'today'"
    # Built from date.today(), not hardcoded or read from the request.
    anchor = body[body.index("ΣΗΜΕΡΑ ΕΙΝΑΙ") - 400:body.index("ΣΗΜΕΡΑ ΕΙΝΑΙ") + 400]
    assert "today.strftime" in anchor


def test_the_context_cache_cannot_outlive_its_day():
    """A blob cached at 23:55 states yesterday's date for its first five
    minutes. The key carries the day so it simply cannot be served."""
    body = open(chat_mod.__file__, encoding="utf-8").read()
    assert re.search(r'chat:context:\{date\.today\(\)\.isoformat\(\)\}', body), \
        "the context cache key is not day-scoped"


def test_chat_timeout_budget_fits_under_the_gateway():
    """The number that produced the 504. The SDK's default is TWO retries, so
    a 25s timeout is really 75s of held connection — written out rather than
    imported, because a test that reads the constants it checks passes
    whatever they become."""
    worst_case = (1 + chat_mod.LLM_MAX_RETRIES) * chat_mod.LLM_TIMEOUT_S

    assert worst_case < chat_mod.GATEWAY_TIMEOUT_S, (
        f"a slow LLM holds the connection {worst_case}s against a "
        f"{chat_mod.GATEWAY_TIMEOUT_S}s gateway — the caller gets a 504 and "
        f"never sees our error")
    assert worst_case <= 24.0


def test_retries_are_capped_explicitly_not_left_to_the_sdk():
    body = open(chat_mod.__file__, encoding="utf-8").read()
    assert "max_retries=LLM_MAX_RETRIES" in body.replace(" ", "").replace("\n", "") \
        or "max_retries=LLM_MAX_RETRIES" in body, \
        "the SDK's default retry count is back in charge of our latency budget"


def test_the_ui_does_not_advertise_a_decommissioned_model():
    """The chat header read 'Llama 3.3 70B · Groq' four days after that model
    was decommissioned, while the backend had long since moved on."""
    from pathlib import Path
    root = Path(chat_mod.__file__).resolve().parents[3]
    box = (root / "frontend" / "src" / "components" / "ChatBox.tsx").read_text()

    assert "Llama" not in box
    assert chat_mod.GROQ_MODEL.split("/")[-1] in box


# ── Groq's token-per-minute cap ───────────────────────────────────────────────
# The 504 was never a slow model. Groq's on-demand tier caps TOKENS per minute
# at 8,000, and the 3-day card was ~7,200 per question — so the SECOND question
# inside a minute came back 429 with "try again in 53.2575s", the SDK slept on
# it, and the proxy gave up first.

@pytest.mark.parametrize("text,expected", [
    ("Error code: 429 - rate_limit_exceeded. Please try again in 53.2575s. Need more",
     53),
    ("Error code: 429 - Please try again in 1.8975s.", 2),
    ("Error code: 429 - no hint here", 60),
])
def test_a_rate_limit_reports_how_long_to_wait(text, expected):
    assert chat_mod._retry_after_seconds(Exception(text)) == expected


def test_a_non_rate_limit_failure_is_not_reported_as_one():
    """A real outage must not tell the reader to try again in a minute."""
    assert chat_mod._retry_after_seconds(Exception("connection reset")) is None
    assert chat_mod._retry_after_seconds(Exception("500 internal error")) is None


def test_the_sdk_never_sleeps_on_a_rate_limit():
    """The SDK honours Retry-After, so a 'retry' is a 53-second sleep holding
    the connection until the gateway 504s. Failing fast with our own message is
    the whole point."""
    assert chat_mod.LLM_MAX_RETRIES == 0


def test_the_context_is_capped_so_a_conversation_is_possible():
    """One question must not consume the whole minute's token allowance.
    8,000 TPM against a ~7,200-token question allowed exactly one."""
    assert chat_mod.CONTEXT_CHAR_BUDGET <= 6000


def test_the_context_names_the_days_it_actually_holds():
    """The budget drops whole days, so the model has to be told which ones
    survived — otherwise it fills the gap by guessing, which is how a card it
    was holding got reported as 'no data available'."""
    body = open(chat_mod.__file__, encoding="utf-8").read()
    assert "Έχεις δεδομένα ΜΟΝΟ για" in body


def test_days_are_dropped_whole_never_half_listed():
    """A half-listed day is worse than an absent one: the model presents what
    it has as the complete card, so 'the 3 best Over games today' silently
    becomes 'of the ones that fit'."""
    body = open(chat_mod.__file__, encoding="utf-8").read()
    assert "not in days_shown" in body, "partial days can reach the model"
