"""Keep our API keys out of anything we print.

The Odds API takes its key as a QUERY PARAMETER, and requests puts the whole
request URL into the text of an HTTPError. So every handler that prints an
exception is a place the live key can reach a log file — and log files get
tailed, pasted into chat and committed by accident.

This is not hypothetical. The Odds API ran out of credits on 2026-08-17 and
every call started failing; by the next morning the key was in
odds-poll.log and daily.log dozens of times over, in full:

    ERROR: 401 Client Error: Unauthorized for url:
    https://api.the-odds-api.com/v4/sports/soccer_greece_super_league/scores/
    ?apiKey=<the real key>&daysFrom=3

Read from the environment at call time rather than captured at import, so a
test that patches the environment is covered too. Deliberately not a logging
filter: half of these are bare print() to stdout, which a filter never sees.
"""
from __future__ import annotations

import os

# Every credential that can end up in a URL or an error message. Header-based
# keys (football-data.org) are here too — cheap, and one less thing to get
# wrong the day an upstream starts echoing headers back in its error body.
_SECRET_ENV_VARS = (
    "ODDS_API_KEY",
    "API_SPORTS_KEY",
    "GROQ_API_KEY",
    "FOOTBALL_DATA_API_KEY",
    "INTERNAL_API_SECRET",
    "NEXTAUTH_SECRET",
)


def redact(value: object) -> str:
    """str(value) with any of our secrets replaced by ***.

    Never raises: it is called from except blocks, where a second failure
    would replace the diagnosis with a stack trace about the redactor.
    """
    try:
        text = str(value)
    except Exception:
        return "<unprintable>"
    for var in _SECRET_ENV_VARS:
        secret = os.getenv(var, "")
        # A one- or two-character value is not a key; replacing it would
        # shred the message.
        if len(secret) > 6:
            text = text.replace(secret, "***")
    return text
