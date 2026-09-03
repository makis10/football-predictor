"""Not every league starts its season in August.

`season_from_date` used a fixed August boundary for every competition. Correct
for the six autumn-spring leagues this project launched with; wrong for the
spring-autumn ones added in July 2026 (Brazil) and the four that followed a
fortnight later (Sweden, Norway, Finland, Ireland). For those, 1 August lands in
the MIDDLE of the campaign, and three things fire at once: the Poisson
attack/defence state resets to nothing, Pi-Ratings take the 0.85 season-boundary
decay, and the league table empties — with a third of the season still to play.

Measured 2026-09-03: 27-34% of the evidence behind an August-bucket Poisson
estimate for those leagues came from a different campaign, against 0% for an
autumn-spring league; the median share of the campaign surviving the wipe was
0.34 (Ireland) to 0.59 (Brazil).

The start month is derived from each league's own fixture calendar rather than a
hand-kept list, because a list of exceptions is precisely what rotted the last
four times a league was added.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.ml.features import (
    _season_phase_features,
    infer_season_start_months,
    season_start_month,
)
from backend.app.ml.poisson import DEFAULT_SEASON_START_MONTH, season_from_date


def _league(name: str, months: list[int], years=(2016, 2027), per_month: int = 6):
    """Synthetic fixture list playing only in `months`, every year in range."""
    rows = []
    for y in range(*years):
        for m in months:
            for d in range(per_month):
                rows.append({"League": name,
                             "Date": pd.Timestamp(y, m, 1 + d)})
    return rows


@pytest.fixture(scope="module")
def calendars() -> pd.DataFrame:
    rows = []
    rows += _league("AugustLeague",   [8, 9, 10, 11, 12, 1, 2, 3, 4, 5])
    rows += _league("CalendarLeague", [3, 4, 5, 6, 7, 8, 9, 10, 11])
    rows += _league("TinyLeague",     [3, 4], per_month=2)          # under the row floor
    return pd.DataFrame(rows)


def test_a_spring_autumn_league_is_detected_from_its_own_fixtures(calendars):
    starts = infer_season_start_months(calendars)
    assert starts.get("CalendarLeague") == 1, (
        "a league that plays March-November and never in December-February was "
        "not recognised as spring-autumn")
    assert "AugustLeague" not in starts, (
        "an autumn-spring league was reclassified — the August default must win "
        "unless the evidence is clear")


def test_a_thin_league_keeps_the_safe_default(calendars):
    """Below the row floor there is not enough calendar to read, and a wrong
    boundary is worse than the status quo."""
    starts = infer_season_start_months(calendars)
    assert "TinyLeague" not in starts
    assert season_start_month("TinyLeague", starts) == DEFAULT_SEASON_START_MONTH
    assert season_start_month(None, starts) == DEFAULT_SEASON_START_MONTH
    assert season_start_month("NeverSeen", starts) == DEFAULT_SEASON_START_MONTH


def test_a_calendar_season_does_not_roll_over_mid_campaign():
    """The bug, stated directly: two matches in the same Swedish season must
    carry the same season label. Under the August rule they did not."""
    july   = season_from_date("2026-07-20", 1)
    august = season_from_date("2026-08-20", 1)
    assert july == august == "2026", (july, august)

    # …and the August rule is exactly what split them.
    assert season_from_date("2026-07-20", 8) != season_from_date("2026-08-20", 8)


def test_an_autumn_spring_season_is_unchanged():
    """The default path must behave exactly as before — most of the book uses it."""
    assert season_from_date("2024-08-01", 8) == "2024/25"
    assert season_from_date("2025-05-31", 8) == "2024/25"
    assert season_from_date("2025-07-31", 8) == "2024/25"
    assert season_from_date("2025-08-01", 8) == "2025/26"
    # The default argument is still August, so untouched callers are unaffected.
    assert season_from_date("2025-08-01") == "2025/26"


def test_season_week_tracks_the_real_campaign():
    """September is week 4 of an English season and week 3x of a Swedish one.

    With one shared August boundary the model was told the opposite: that a
    Swedish match in the run-in was the opening weeks of a new season, which
    inverts the only thing season_phase exists to express.
    """
    sept = pd.Timestamp("2026-09-15")
    english = _season_phase_features(sept, 8)
    swedish = _season_phase_features(sept, 1)

    assert english["season_phase"] == 1.0, "September is early season in England"
    assert swedish["season_phase"] == 3.0, "September is the run-in in Sweden"
    assert swedish["season_week"] > english["season_week"] + 20


def test_the_detector_is_not_fooled_by_the_real_league_calendars():
    """Against the actual CSVs: every league we PRICE that is spring-autumn must
    be found, and no autumn-spring league may be misclassified."""
    from backend.app.ml.features import load_raw_csvs

    import os
    raw_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    if not os.path.isdir(raw_dir):
        pytest.skip("no raw CSVs on disk")

    df = load_raw_csvs(raw_dir)
    starts = infer_season_start_months(df)

    must_be_calendar = {"BrazilSerieA", "Sweden", "Norway", "Finland", "Ireland"}
    missing = sorted(must_be_calendar - set(starts))
    assert not missing, f"spring-autumn leagues we price were not detected: {missing}"

    must_be_august = {"EPL", "LaLiga", "SerieA", "Bundesliga", "Ligue1", "GreekSL",
                      "Championship", "Eredivisie", "PrimeiraLiga", "Scotland"}
    wrong = sorted(must_be_august & set(starts))
    assert not wrong, f"autumn-spring leagues misread as spring-autumn: {wrong}"
