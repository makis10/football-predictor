"""The corpus was 17.7% in the wrong month, silently, for as long as it existed.

`pd.to_datetime(..., dayfirst=True, format="mixed")` reads an ISO string as
%Y-%d-%m whenever both components are <= 12. No error, no warning:

    2021-12-05  (5 December)  ->  2021-05-12  (12 May)

491 of 848 raw CSVs use ISO dates and 37,385 of their rows were swapped. The
top-five leagues use football-data.co.uk's dd/mm/yyyy and parsed correctly,
which is why nothing ever looked wrong on the pages anyone reads.

It mattered because build_features SORTS BY DATE and walks the rows in order.
Elo, Pi-Ratings, the rolling form deques, EWMA, H2H, league position and the
season-boundary decay are all accumulated in that order, so a December match
processed as May is a training row built from matches not yet played, and every
later row in that league inherits the corrupted state. build_team_snapshot sorts
the same way, so it reached what we serve.
"""
from __future__ import annotations

import pandas as pd
import pytest

from backend.app.ml.features import parse_match_dates


@pytest.mark.parametrize("raw,expected", [
    # ISO, both parts <= 12 — the ones that silently swapped.
    ("2021-12-05", "2021-12-05"),
    ("2021-11-07", "2021-11-07"),
    ("2026-01-10", "2026-01-10"),
    ("2026-10-01", "2026-10-01"),
    # ISO, unambiguous because the day cannot be a month.
    ("2026-01-13", "2026-01-13"),
    # football-data.co.uk's day-first format, which must keep working.
    ("05/12/2021", "2021-12-05"),
    ("13/01/2026", "2026-01-13"),
    ("01/10/2026", "2026-10-01"),
])
def test_both_formats_parse_to_the_day_they_name(raw, expected):
    assert str(parse_match_dates(pd.Series([raw]))[0].date()) == expected


def test_the_old_parser_really_did_swap_them():
    """Non-vacuity: if pandas ever stops doing this, the guard above is dead
    weight and this test says so instead of quietly passing forever."""
    swapped = pd.to_datetime(pd.Series(["2021-12-05"]), dayfirst=True,
                             format="mixed", errors="coerce")[0]
    assert str(swapped.date()) == "2021-05-12", (
        "pandas no longer swaps ISO dates under dayfirst=True; parse_match_dates "
        "may be simplifiable, but check every caller before removing it")


def test_a_played_match_cannot_be_dated_in_the_future():
    """The tell that was there to be seen for months.

    568 rows carried a final score and a date in the future, the latest three
    months out — Cesena 0-1 Empoli filed under 1 October 2026 when it was played
    on 10 January. A result cannot exist for a match that has not happened.
    """
    from backend.app.ml.features import load_raw_csvs

    df = load_raw_csvs("backend/data/raw")
    today = pd.Timestamp.today().normalize()
    future = df[df["Date"] > today]
    assert future.empty, (
        f"{len(future)} played matches are dated in the future; the newest is "
        f"{future['Date'].max().date()}. Sample:\n" +
        "\n".join(f"  {r.Date.date()} {r.home_team} {r.home_goals}-{r.away_goals} {r.away_team}"
                  for r in future.head(5).itertuples()))


def test_every_writer_of_a_match_date_uses_the_same_parser():
    """Three call sites parsed CSV dates, and each would have had to be found
    separately. features.py, scripts/seed_db.py and scripts/backfill_bm_odds.py
    now share one function; a fourth appearing with `dayfirst` and no ISO pass
    reintroduces the whole thing."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    offenders = []
    for py in list((root / "backend").rglob("*.py")) + list((root / "scripts").rglob("*.py")):
        if "/cache/" in str(py) or "/tests/" in str(py):
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        # parse_match_dates itself uses dayfirst as its FALLBACK, which is the
        # point of it. Cut its body out before scanning, rather than trying to
        # recognise it line by line.
        if "def parse_match_dates(" in text:
            start = text.index("def parse_match_dates(")
            nxt = text.find("\ndef ", start + 10)
            text = text[:start] + text[nxt if nxt != -1 else len(text):]
        for m in re.finditer(r"^.*dayfirst\s*=\s*True.*$", text, re.M):
            offenders.append(f"{py.relative_to(root)}: {m.group(0).strip()[:80]}")
    assert not offenders, (
        "a CSV date is parsed with dayfirst=True outside parse_match_dates:\n  "
        + "\n  ".join(offenders))
