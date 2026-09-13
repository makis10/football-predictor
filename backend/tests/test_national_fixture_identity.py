"""One national match, one prediction row.

When the source moved Argentina–Egypt and Switzerland–Colombia from 6 to 7 July
2026, the backfill missed their rows on the exact date and inserted both again,
and /national/wc-review counted 106 World Cup matches instead of 104. Every
national writer now takes its identity from fixture_identity.find_national_row.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.ml.national import fixture_identity as fi
from backend.app.models.national_prediction import NationalPrediction as NP

# A calendar large enough not to read as a truncated download.
FILLER = {(f"2025-01-{d:02d}", f"T{i}", f"U{i}") for d in range(1, 29) for i in range(40)}
WC = "FIFA World Cup"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[NP.__table__])
    with Session(engine) as session:
        yield session


def _row(db, d, home, away, tournament=WC, **kw):
    fields = dict(match_date=d, home_team=home, away_team=away, tournament=tournament,
                  neutral=True, home_win_prob=0.5, draw_prob=0.25, away_win_prob=0.25,
                  prediction="H", confidence="MEDIUM", over_2_5_prob=0.5)
    fields.update(kw)
    r = NP(**fields)
    db.add(r)
    db.commit()
    return r


def _find(db, d, home, away, keys, tournament=WC, allow_reversed=True):
    return fi.find_national_row(db, d, home, away, tournament, keys,
                                allow_reversed=allow_reversed)


def test_the_exact_row_is_found(db):
    r = _row(db, "2026-07-07", "Argentina", "Egypt")
    assert _find(db, "2026-07-07", "Argentina", "Egypt", FILLER) == (r, "exact")


def test_the_reversed_orientation_only_where_the_writer_allows_it(db):
    r = _row(db, "2026-07-07", "Egypt", "Argentina")
    assert _find(db, "2026-07-07", "Argentina", "Egypt", FILLER) == (r, "reversed")
    assert _find(db, "2026-07-07", "Argentina", "Egypt", FILLER,
                 allow_reversed=False) == (None, "none")


def test_a_re_dated_fixture_is_found_on_its_old_row(db):
    """The World Cup duplicates: the source now lists 7 July only."""
    r = _row(db, "2026-07-06", "Argentina", "Egypt")
    keys = FILLER | {("2026-07-07", "Argentina", "Egypt")}
    assert _find(db, "2026-07-07", "Argentina", "Egypt", keys) == (r, "moved")


def test_a_real_double_header_is_not_merged(db):
    """Two meetings days apart are both in the source: neither is an orphan."""
    _row(db, "2024-04-06", "Northern Mariana Islands", "Guam", tournament="Marianas Cup")
    keys = FILLER | {("2024-04-06", "Northern Mariana Islands", "Guam"),
                     ("2024-04-07", "Northern Mariana Islands", "Guam")}
    assert _find(db, "2024-04-07", "Northern Mariana Islands", "Guam", keys,
                 tournament="Marianas Cup") == (None, "none")


def test_a_truncated_source_never_moves_anything(db):
    _row(db, "2026-07-06", "Argentina", "Egypt")
    keys = {("2026-07-07", "Argentina", "Egypt")}          # a handful of rows
    assert _find(db, "2026-07-07", "Argentina", "Egypt", keys) == (None, "none")


def test_another_tournament_is_not_the_same_match(db):
    _row(db, "2026-07-06", "Argentina", "Egypt", tournament="Friendly")
    keys = FILLER | {("2026-07-07", "Argentina", "Egypt")}
    assert _find(db, "2026-07-07", "Argentina", "Egypt", keys) == (None, "none")


def test_the_nearest_orphan_is_the_one_moved(db):
    _row(db, "2026-07-04", "Argentina", "Egypt")
    near = _row(db, "2026-07-06", "Argentina", "Egypt")
    keys = FILLER | {("2026-07-07", "Argentina", "Egypt")}
    assert _find(db, "2026-07-07", "Argentina", "Egypt", keys) == (near, "moved")


# ── predict_national.save_to_db, the daily writer ────────────────────────────

def _pred(d, home, away, p_home):
    return {"date": d, "home_team": home, "away_team": away, "tournament": WC,
            "neutral": True, "p_home": p_home, "p_draw": 0.2, "p_away": 0.8 - p_home,
            "p_over25": 0.5, "p_btts": 0.45, "prediction": "H", "confidence": "HIGH",
            "h_elo": 2000.0, "a_elo": 1700.0}


def test_save_moves_a_re_dated_fixture_instead_of_adding_a_row(db):
    from scripts.predict_national import save_to_db

    _row(db, "2026-07-06", "Argentina", "Egypt")
    keys = FILLER | {("2026-07-07", "Argentina", "Egypt")}
    save_to_db([_pred("2026-07-07", "Argentina", "Egypt", 0.6)], keys, db=db)
    rows = db.query(NP).filter(NP.home_team == "Argentina").all()
    assert [(r.match_date, r.home_win_prob) for r in rows] == [("2026-07-07", 0.6)]


def test_save_never_rewrites_a_settled_prediction(db):
    """A settled row is the published pre-match record."""
    from scripts.predict_national import save_to_db

    _row(db, "2026-07-07", "Argentina", "Egypt", actual_result="H", home_win_prob=0.5)
    save_to_db([_pred("2026-07-07", "Argentina", "Egypt", 0.9)], FILLER, db=db)
    (row,) = db.query(NP).all()
    assert row.home_win_prob == 0.5


def test_save_refreshes_the_venue_and_tournament_the_source_revised(db):
    """Set only at insert, 19 of the 2026 rows said "home" for a match the
    source lists as neutral, and a Tri-Nations Cup tie sat in the Friendly
    bucket of /national/stats."""
    from scripts.predict_national import save_to_db

    _row(db, "2026-06-06", "Myanmar", "Guam", tournament="Friendly", neutral=False)
    pred = {**_pred("2026-06-06", "Myanmar", "Guam", 0.6),
            "tournament": "Tri-Nations Cup", "neutral": True}
    save_to_db([pred], FILLER, db=db)
    (row,) = db.query(NP).all()
    assert (row.tournament, row.neutral) == ("Tri-Nations Cup", True)
