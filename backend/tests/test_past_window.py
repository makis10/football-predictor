"""Pages of past matches must tile the calendar.

Every past-matches window reached one day too far at both ends —
`>= today-(K+N)` and `<= today-K` — so each window was N+1 days long and the
boundary day of every /recent page was listed on the next page too. The same
formula was written out three times in routers/matches.py (the listing, the
export's clubs, the export's internationals), which is how a fix to one would
have left the others wrong.
"""
from __future__ import annotations

import inspect
from datetime import date, timedelta

import pytest

import backend.app.routers.matches as m

TODAY = date(2026, 9, 10)


@pytest.fixture(autouse=True)
def _frozen_today(monkeypatch):
    monkeypatch.setattr(m, "_utc_today", lambda: TODAY)


def test_first_page_is_the_last_n_days_including_today():
    assert m._past_window(7, None) == (TODAY - timedelta(days=6), None)
    assert m._past_window(7, 0) == (TODAY - timedelta(days=6), None)


def test_consecutive_pages_tile_the_calendar():
    covered: list[date] = []
    for page in range(12):
        lower, upper = m._past_window(7, page * 7)
        upper = upper or TODAY
        span = (upper - lower).days + 1
        assert span == 7, f"page {page + 1} spans {span} days"
        covered.extend(upper - timedelta(days=i) for i in range(span))
    assert len(covered) == len(set(covered)), "a day is listed on two pages"
    assert sorted(covered) == [TODAY - timedelta(days=i) for i in range(83, -1, -1)], (
        "a day is listed on no page")


def test_no_bounds_without_the_parameters():
    assert m._past_window(None, None) == (None, None)
    assert m._past_window(None, 14) == (None, TODAY - timedelta(days=14))


def test_every_endpoint_uses_the_one_window():
    src = inspect.getsource(m)
    assert "(days_offset or 0) + days_back" not in src, "the old N+1-day formula is back"
    assert src.count("_past_window(days_back, days_offset)") == 3, (
        "the listing, the export's clubs and the export's internationals must "
        "all take their window from _past_window")


def test_listing_accepts_an_explicit_date_window():
    """/recent computes one Athens-day window and hands it to both the club and
    the national endpoints, instead of each side deriving its own."""
    route = next(r for r in m.router.routes
                 if getattr(r, "path", "") == "/matches" and "GET" in r.methods)
    params = inspect.signature(route.endpoint).parameters
    assert {"date_from", "date_to"} <= set(params)
