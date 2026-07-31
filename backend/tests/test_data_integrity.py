"""Does the training data actually say anything?

The failure mode these guard is not a crash — it is a lookup quietly returning
its default. Every team ends up rated 1500, every fixture gets the same
probabilities, and the site keeps serving confident-looking numbers that carry
no information. That shipped twice in July 2026 and both times a human spotted
it on the page, not a test.

Runs off the CSVs in the repo: no DB, no network. The snapshot build is a few
seconds, so it is module-scoped and shared.
"""
from __future__ import annotations

import os
import statistics

import pytest

from backend.app.ml.features import (
    HISTORY_ONLY_LEAGUES,
    ONE_HOT_LEAGUES,
    build_team_snapshot,
    load_raw_csvs,
    snapshot_name,
)

_RAW = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "backend", "data", "raw")

ELO_START = 1500.0


@pytest.fixture(scope="module")
def history():
    if not os.path.isdir(_RAW):
        pytest.skip("no raw CSV directory in this checkout")
    df = load_raw_csvs(_RAW)
    if df.empty:
        pytest.skip("raw CSV directory is empty")
    return df


@pytest.fixture(scope="module")
def snapshot(history):
    return build_team_snapshot(history)


# ── The default-value trap ────────────────────────────────────────────────────

def test_elo_ratings_are_not_all_the_default(snapshot):
    """Elo must have real spread.

    2026-07-30: `club_elo` built ratings from the `matches` table alone, which
    holds only the fixtures we ingest — for the twelve leagues added that week
    it held nothing at all. Every club fell back to 1500, so the season
    projection gave all eighteen Süper Lig teams the same 47 expected points and
    a 6% title chance, while the CSVs on disk rated Galatasaray 1850.
    """
    elo = dict(snapshot.get("elo", {}))
    assert len(elo) > 100, f"only {len(elo)} rated clubs — snapshot looks empty"

    at_default = sum(1 for v in elo.values() if abs(v - ELO_START) < 1e-6)
    assert at_default / len(elo) < 0.10, (
        f"{at_default}/{len(elo)} clubs sit exactly at the {ELO_START} default — "
        "a lookup is silently missing, not a modelling result")

    spread = statistics.pstdev(elo.values())
    assert spread > 50, (
        f"Elo standard deviation is only {spread:.1f}; ratings are effectively "
        "uniform, which makes every fixture look identical")


def test_club_elo_seeds_from_the_csv_history_not_just_the_database():
    """The projections' Elo source must include the CSVs.

    This is the actual bug, not the snapshot above: `club_elo._build()` walked
    the `matches` table alone, which holds only fixtures we ingest. For the
    twelve leagues added in July 2026 it held zero completed matches, so every
    club there was rated 1500 and the season projection came out uniform.

    Asserted on `_csv_elo()` because it needs no database — which is also why
    the regression could never have been caught by the DB-gated tests.
    """
    from backend.app.ml.club_elo import _csv_elo

    elo, seen = _csv_elo()
    assert len(elo) > 100, f"CSV-derived Elo has only {len(elo)} clubs"
    assert seen, "no (date, home, away) keys recorded — DB results would double-count"

    spread = statistics.pstdev(elo.values())
    assert spread > 50, f"CSV-derived Elo is flat (sd={spread:.1f})"

    # Clubs from leagues we hold no FIXTURES for must still be rated, since
    # that is exactly the gap the CSV base exists to fill.
    from_expansion = [t for t in ("Galatasaray", "Fenerbahce", "Midtjylland",
                                  "Legia", "Rakow") if t in elo]
    if from_expansion:
        assert all(abs(elo[t] - ELO_START) > 1e-6 for t in from_expansion), (
            f"expansion clubs still at the default: "
            f"{ {t: round(elo[t]) for t in from_expansion} }")


def test_the_strongest_clubs_outrank_the_weakest(snapshot):
    """A sanity anchor that survives retraining and re-scaling.

    Not a claim about exact numbers — just that the ordering is football-shaped.
    If this fails, the snapshot is keyed on the wrong names.
    """
    elo = snapshot.get("elo", {})
    known = {n: elo[n] for n in ("Man City", "Bayern Munich", "Real Madrid", "Barcelona")
             if n in elo}
    if len(known) < 2:
        pytest.skip("elite clubs not present under these names")
    assert min(known.values()) > ELO_START, (
        f"elite clubs rated at or below the default: {known}")


# ── League coverage ───────────────────────────────────────────────────────────

def test_every_predicted_league_has_training_rows(history):
    """A league we one-hot encode but never trained on contributes nothing."""
    counts = history.groupby("League").size().to_dict()
    missing = [lg for lg in ONE_HOT_LEAGUES if counts.get(lg, 0) < 100]
    assert not missing, f"leagues with almost no training rows: {missing}"


def test_history_only_leagues_actually_loaded(history):
    """A history-only league with no CSVs on disk is a silent no-op.

    They exist to give promoted clubs and European qualifiers a record; if the
    import stopped writing files, the fixtures would go back to reading
    "no history — no prediction" and nothing would say why.
    """
    counts = history.groupby("League").size().to_dict()
    present = [lg for lg in HISTORY_ONLY_LEAGUES if counts.get(lg, 0) > 0]
    if not present:
        pytest.skip("history-only leagues not imported in this checkout")
    empty = [lg for lg in HISTORY_ONLY_LEAGUES
             if 0 < counts.get(lg, 0) < 100]
    assert not empty, f"history-only leagues with suspiciously few rows: {empty}"


# ── Name resolution ───────────────────────────────────────────────────────────

def test_accented_fixture_names_resolve_to_the_csv_spelling(snapshot):
    """The fixture feeds carry diacritics the CSV history does not.

    Thirteen clubs were invisible to the model after the July 2026 import for
    exactly this reason — the data was on disk, the name just never matched.
    `snapshot_name` resolves it with an accent-insensitive slug so the alias
    table does not have to grow one entry per diacritic in Europe.
    """
    known = frozenset(snapshot.get("elo", {}))
    cases = ["Žilina", "Hradec Králové", "Çorum FK", "Velež",
             "Kauno Žalgiris", "Železničar Pančevo"]
    present = [c for c in cases if snapshot_name(c, known) in known]
    if not present:
        pytest.skip("expansion history not imported in this checkout")
    unresolved = [c for c in cases if snapshot_name(c, known) not in known]
    assert not unresolved, (
        f"accented names still unresolved: {unresolved} — the slug fallback in "
        "features.snapshot_name has regressed")


def test_snapshot_name_never_guesses_between_two_clubs(snapshot):
    """Ambiguity must return the input unchanged, never a coin flip.

    A similarity matcher proposed Velež (Bosnia) → Vejle (Denmark) at 0.80.
    Wrong-but-confident is worse than unresolved: the fixture inherits another
    club's Elo and form.
    """
    known = frozenset(snapshot.get("elo", {}))
    for invented in ("Totally Fake FC", "Zzz United", "Nonexistent Rovers"):
        assert snapshot_name(invented, known) == invented, (
            f"{invented!r} was mapped onto a real club")


def test_no_club_in_the_snapshot_is_a_youth_or_womens_side(snapshot):
    """Reserve and women's sides must not carry a senior club's record."""
    from scripts.team_resolver import is_youth_side

    offenders = [t for t in snapshot.get("elo", {}) if is_youth_side(t)]
    # A handful legitimately appear as friendly opponents under their own name.
    assert len(offenders) < 25, (
        f"{len(offenders)} youth/reserve/women's sides in the Elo snapshot — "
        f"sample: {sorted(offenders)[:10]}")
