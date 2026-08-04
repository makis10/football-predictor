"""Every Groq call must survive the model actually being a reasoning model.

`GROQ_MODEL` defaults to openai/gpt-oss-120b, which emits a hidden chain of
thought that is billed against `max_tokens` BEFORE the first word of the answer.
With the budget tuned for a plain chat model the whole allowance went on
reasoning: the request returned HTTP 200, `finish_reason="length"` and
`content=""`.

Nothing caught it. The narrative cache stored the empty string for 24 hours and
the site rendered a prediction card with no analysis under it — no error, no log
line, no failing test. 91 of 184 cached narratives were blank before anyone
noticed, and only because the probabilities changed in a retrain and every
narrative regenerated at once.

These are source-level assertions on purpose: they must hold in CI, where there
is no API key and no network.
"""
from __future__ import annotations

import ast
import os

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# file → the smallest max_tokens that leaves room for an answer once the
# reasoning budget is capped at "low" (~10 tokens observed, but the model is
# free to spend more on a harder prompt).
_CALL_SITES = [
    "backend/app/ml/odds_analysis_service.py",
    "backend/app/routers/predictions.py",
    "backend/app/routers/chat.py",
]
_MIN_MAX_TOKENS = 600


def _groq_calls(path: str) -> list[ast.Call]:
    """Every `*.chat.completions.create(...)` in the file."""
    tree = ast.parse(open(os.path.join(_ROOT, path), encoding="utf-8").read())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr == "create"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "completions"):
            out.append(node)
    return out


def _kwarg(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


@pytest.mark.parametrize("path", _CALL_SITES)
def test_every_groq_call_caps_the_reasoning_budget(path):
    calls = _groq_calls(path)
    assert calls, f"no Groq call found in {path} — did it move?"
    for call in calls:
        effort = _kwarg(call, "reasoning_effort")
        assert effort is not None, (
            f"{path}:{call.lineno} calls Groq without reasoning_effort — a "
            "reasoning model will spend max_tokens thinking and return "
            "content=''")
        assert isinstance(effort, ast.Constant) and effort.value in ("low", "medium"), (
            f"{path}:{call.lineno} reasoning_effort must be 'low' or 'medium'")


@pytest.mark.parametrize("path", _CALL_SITES)
def test_every_groq_call_leaves_room_for_an_answer(path):
    for call in _groq_calls(path):
        tokens = _kwarg(call, "max_tokens")
        assert isinstance(tokens, ast.Constant) and isinstance(tokens.value, int), (
            f"{path}:{call.lineno} has no literal max_tokens")
        assert tokens.value >= _MIN_MAX_TOKENS, (
            f"{path}:{call.lineno} max_tokens={tokens.value} is below "
            f"{_MIN_MAX_TOKENS}; reasoning tokens come out of this budget first")


@pytest.mark.parametrize("path", _CALL_SITES)
def test_an_empty_completion_is_treated_as_a_failure(path):
    """`.content` can be None or "". Both must raise rather than be stored.

    Reading `.content.strip()` straight off the response is the shape of the
    original bug: on None it throws something unrelated, and on "" it silently
    produces a valid-looking empty answer that gets cached.
    """
    source = open(os.path.join(_ROOT, path), encoding="utf-8").read()
    assert ".message.content.strip()" not in source, (
        f"{path} reads .content.strip() directly — use "
        '`(… .content or "").strip()` and raise when the result is empty')
    assert "empty completion" in source, (
        f"{path} has no guard raising on an empty completion")
