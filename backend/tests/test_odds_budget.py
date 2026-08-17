"""Does the odds poller stay inside The Odds API's monthly budget?

The plan is 20,000 credits a MONTH — 645/day if it is to survive 31 days. On
2026-08-15 the account was found exhausted since the 13th: ~1,540/day, so the
site ran with NO live odds for roughly 18 days of every month, silently. The
fixes are three, and each has a guard here because each is one careless edit
away from coming back:

  1. `poll_odds` must not fetch BTTS. It costs one request PER GAME, and
     `odds_history` has no column to put it in — ~1,100 credits a day were
     fetched, parsed and dropped. This is the single biggest saving and the
     easiest to undo by "simplifying" the call.
  2. Matches are re-priced on a tier, not a fixed cadence.
  3. A league The Odds API is not pricing yet backs off — but only after
     REPEATED empty answers, never a single one (see the Eredivisie note).

Offline: no network, no API key, no database.
"""
from __future__ import annotations

import inspect
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

import scripts.poll_odds as poll
from backend.app.ml.odds_analysis_service import fetch_all_league_odds

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _match(*, days_out: float, mid: int = 1, league: str = "EPL") -> SimpleNamespace:
    """A stand-in Match. Only the four fields the tier logic reads."""
    ko = NOW + timedelta(days=days_out)
    return SimpleNamespace(
        id=mid, league=league, match_date=ko.date(),
        kickoff_time=time(ko.hour, ko.minute),
    )


# ── 1. the BTTS saving ───────────────────────────────────────────────────────

def test_poller_does_not_pay_for_btts():
    """odds_history stores 1×2 + over/under only. BTTS is billed per GAME, so
    fetching it in the poller buys nothing at the price of the whole plan."""
    src = inspect.getsource(poll)
    call = re.search(r"fetch_all_league_odds\((.*?)\)", src, re.S)
    assert call, "poll_odds must still call fetch_all_league_odds"
    assert "with_btts=False" in call.group(1), (
        "poll_odds must pass with_btts=False — BTTS costs one request per game "
        "and odds_history has no column for it"
    )


def test_odds_history_still_has_no_btts_column():
    """The guard above is only correct while this stays true. If a BTTS column
    is ever added, the poller SHOULD start fetching it — and this test is where
    that decision gets made, rather than silently diverging."""
    from backend.app.models.odds_history import OddsHistory

    cols = set(OddsHistory.__table__.columns.keys())
    assert not {c for c in cols if "btts" in c.lower()}, (
        "odds_history grew a BTTS column — revisit with_btts=False in poll_odds"
    )


def test_with_btts_false_makes_no_per_event_calls(monkeypatch):
    """The flag has to actually suppress the request, not merely drop its
    result — the credit is spent at the call, not at the assignment."""
    import backend.app.ml.odds_analysis_service as svc

    games = [{"id": f"evt{i}", "home_team": "Arsenal", "away_team": "Chelsea",
              "bookmakers": []} for i in range(5)]
    monkeypatch.setattr(svc, "_fetch_league_games_cached", lambda league: games)
    monkeypatch.setattr(svc, "_active_sport_key", lambda league: "soccer_epl")

    calls: list[str] = []
    monkeypatch.setattr(svc, "_fetch_event_btts",
                        lambda eid, key: calls.append(eid) or {})

    svc.fetch_all_league_odds("EPL", with_btts=False)
    assert calls == [], f"with_btts=False still made {len(calls)} per-event calls"

    svc.fetch_all_league_odds("EPL")           # default must be unchanged
    assert len(calls) == 5, "the default must still fetch BTTS (compute_predictions needs it)"


def test_btts_default_is_on():
    """compute_predictions reads fair_probs['btts_yes'] — flipping the default
    would silently strip a feature out of the model's input."""
    sig = inspect.signature(fetch_all_league_odds)
    assert sig.parameters["with_btts"].default is True


# ── 2. tiered polling ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "days_out, hours_since, expected, why",
    [
        (1,  7,  True,  "kickoff tomorrow, 7h old → every run"),
        (1,  5,  False, "kickoff tomorrow but priced 5h ago → not yet"),
        (4,  21, True,  "4 days out, a day old → daily tier fires"),
        (4,  9,  False, "4 days out, 9h old → daily tier not due"),
        (6,  45, True,  "6 days out, 2 days old → far tier fires"),
        (6,  21, False, "6 days out, 21h old → far tier not due"),
    ],
)
def test_tier_cadence(days_out, hours_since, expected, why):
    m = _match(days_out=days_out)
    last = NOW - timedelta(hours=hours_since)
    assert poll._is_due(m, last, NOW) is expected, why


def test_never_priced_match_is_always_due():
    """A fixture with no snapshot at all has no movement history to protect —
    it must get its first price whatever tier it falls in."""
    assert poll._is_due(_match(days_out=6), None, NOW) is True


def test_near_tier_fires_on_every_run_of_an_8_hourly_schedule():
    """The thresholds must sit UNDER the schedule interval. At exactly 8.0 the
    near tier would skip a run whenever launchd fired a minute late, halving
    the cadence on precisely the matches that move most."""
    near_min_age = poll.TIERS[0][1]
    assert near_min_age < 8.0, (
        f"near tier needs re-pricing every {near_min_age}h but the job only "
        "runs every 8h — it would skip runs"
    )
    mid_min_age = poll.TIERS[1][1]
    assert mid_min_age < 24.0, "mid tier must fire once a day, with slack"


def test_tiers_are_ordered_and_closed():
    """First matching row wins, so an out-of-order table would apply the wrong
    cadence; an unbounded last row would leave far-out matches unmatched."""
    horizons = [h for h, _ in poll.TIERS]
    assert horizons == sorted(horizons), "TIERS must be ordered by horizon"
    assert horizons[-1] == float("inf"), "the last tier must catch everything"


def test_match_with_no_kickoff_time_is_not_treated_as_imminent():
    """kickoff_time is nullable. Defaulting it to midnight would put a fixture
    whose time is merely unknown into the every-run tier."""
    m = _match(days_out=2)
    m.kickoff_time = None
    assert poll._kickoff(m, NOW).hour >= 12


# ── 3. dry-league back-off ───────────────────────────────────────────────────

class _FakeCache(dict):
    """Redis stand-in. TTLs are irrelevant to what these tests assert."""


@pytest.fixture
def cache(monkeypatch):
    store = _FakeCache()
    from backend.app.cache import CACHE_MISS
    monkeypatch.setattr(poll, "cache_get",
                        lambda k: store.get(k, CACHE_MISS))
    monkeypatch.setattr(poll, "cache_set",
                        lambda k, v, ttl: store.__setitem__(k, v))
    monkeypatch.setattr(poll, "cache_delete", lambda k: store.pop(k, None))
    return store


def test_one_empty_answer_does_not_park_a_league(cache):
    """2026-08-04: the Eredivisie batch returned zero games while the same
    request made by hand returned nine. Backing off on a single blip blanks a
    live league for a day."""
    poll._record_dry("Eredivisie")
    assert poll._dry_skip("Eredivisie") is False
    poll._record_dry("Eredivisie")
    assert poll._dry_skip("Eredivisie") is False, "two strikes is still a blip"


def test_three_consecutive_empties_park_the_league(cache):
    for _ in range(poll.DRY_STRIKES):
        poll._record_dry("ECL")
    assert poll._dry_skip("ECL") is True


def test_a_league_that_answers_resumes_immediately(cache):
    """EL / ECL / Switzerland have no market TODAY and will have one within
    weeks. The back-off must clear the moment the season starts, without anyone
    editing a list."""
    for _ in range(poll.DRY_STRIKES):
        poll._record_dry("EL")
    assert poll._dry_skip("EL") is True

    poll._record_live("EL")
    assert poll._dry_skip("EL") is False
    poll._record_dry("EL")
    assert poll._dry_skip("EL") is False, "strike count must have reset too"


def test_backoff_expires_rather_than_being_permanent(monkeypatch):
    """The skip flag is the PRESENCE of a key with a TTL. Storing it without
    one — or with a huge one — would park a league until someone noticed."""
    values: dict[str, object] = {}
    ttls: dict[str, int] = {}
    from backend.app.cache import CACHE_MISS

    def _set(k, v, ttl):
        values[k] = v
        ttls[k] = ttl

    monkeypatch.setattr(poll, "cache_get", lambda k: values.get(k, CACHE_MISS))
    monkeypatch.setattr(poll, "cache_set", _set)
    monkeypatch.setattr(poll, "cache_delete", lambda k: values.pop(k, None))
    seen = ttls

    for _ in range(poll.DRY_STRIKES):
        poll._record_dry("Switzerland")

    ttl = seen.get(poll._DRY_UNTIL.format("Switzerland"))
    assert ttl, "the skip marker must be written with a TTL"
    assert 0 < ttl <= 48 * 3600, f"back-off of {ttl}s is too long to self-heal"


def test_exhausted_plan_does_not_park_every_league():
    """The failure that started all of this: with 0 credits left, EVERY call
    401s and `_fetch_league_games_cached` returns [] for each. Recording
    strikes then parks all 27 leagues for 24h over an account problem — and
    they stay parked into the day the plan resets."""
    fetched = ["EPL", "LaLiga", "SerieA", "EL", "ECL"]
    all_empty = {k: [] for k in fetched}
    assert poll._account_level_failure(fetched, all_empty) is True


def test_one_live_league_means_the_empties_are_genuinely_dry():
    """The escape hatch must be narrow. If anything at all came back, the plan
    works and an empty league really has no market."""
    fetched = ["EPL", "EL", "ECL"]
    mixed = {"EPL": [{"id": "x"}], "EL": [], "ECL": []}
    assert poll._account_level_failure(fetched, mixed) is False


def test_no_leagues_fetched_is_not_an_account_failure():
    """A run where everything was already backed off calls nothing. Zero
    fetches is not evidence of anything."""
    assert poll._account_level_failure([], {}) is False


def test_transport_errors_do_not_count_as_dry():
    """A timeout says nothing about whether the league is priced. Counting it
    would let three flaky polls park a live league for a day."""
    import ast

    tree = ast.parse(inspect.getsource(poll.main).lstrip())
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    assert handlers, "the league sweep must still guard against transport errors"
    for h in handlers:
        called = {n.func.id for n in ast.walk(h)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "_record_dry" not in called, (
            "an exception handler must not record a dry strike — a timeout says "
            "nothing about whether the league is priced"
        )


# ── 4. the schedule itself ───────────────────────────────────────────────────

def test_launchd_schedule_matches_the_tiers():
    """The tiers assume an 8-hourly job. If the plist goes back to 3-hourly the
    budget blows again; if it goes slower than 8h the near tier stops firing
    every run and the guard above becomes a lie."""
    plist = os.path.expanduser(
        "~/Library/LaunchAgents/com.football-predictor.odds-poll.plist")
    if not os.path.exists(plist):
        pytest.skip("launchd plist not present (CI / container)")

    hours = [int(h) for h in re.findall(
        r"<key>Hour</key><integer>(\d+)</integer>", open(plist).read())]
    assert hours, "no schedule found in the plist"
    gaps = [b - a for a, b in zip(hours, hours[1:])] + [24 - hours[-1] + hours[0]]
    assert min(gaps) >= 8, f"job runs every {min(gaps)}h — tiers assume 8h"


# ── Credentials must never reach the log ──────────────────────────────────────
# The Odds API takes its key as a query parameter, and requests puts the whole
# URL into the text of an HTTPError. When the month's credits ran out on
# 2026-08-17 every league logged the live key in plaintext, once per poll.

def test_a_failed_odds_call_does_not_log_the_api_key(monkeypatch):
    import requests

    from backend.app.ml import odds_analysis_service as oas

    monkeypatch.setattr(oas, "ODDS_API_KEY", "sekrit-odds-key")
    exc = requests.HTTPError(
        "401 Client Error: Unauthorized for url: "
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
        "?apiKey=sekrit-odds-key&regions=eu")

    text = oas._redact_key(exc)

    assert "sekrit-odds-key" not in text
    assert "401" in text and "soccer_epl" in text, "redaction ate the diagnosis"


def test_redaction_covers_every_key_we_hold(monkeypatch):
    from backend.app.ml import odds_analysis_service as oas

    monkeypatch.setattr(oas, "ODDS_API_KEY", "odds-key")
    monkeypatch.setattr(oas, "GROQ_API_KEY", "groq-key")
    monkeypatch.setattr(oas, "API_SPORTS_KEY", "sports-key")

    text = oas._redact_key(Exception("odds-key groq-key sports-key"))

    assert text == "*** *** ***"
