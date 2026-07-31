"""What the site is actually serving right now.

Everything else in this suite checks code and CSVs. These check the rows the
visitor sees, which is where the last few bugs were found — by a human scrolling
the page, because no test looked at the output.

Needs a database, so they SKIP on a fresh CI checkout and run locally with:

    docker compose exec -T backend python -m pytest backend/tests/test_live_data.py -q

Read-only. Nothing here writes.
"""
from __future__ import annotations

import datetime as dt
import re

import pytest


@pytest.fixture(scope="module")
def db():
    try:
        from sqlalchemy import text

        from backend.app.database import SessionLocal
        s = SessionLocal()
        s.execute(text("SELECT 1"))
    except Exception as e:                       # no DB in CI — that is fine
        pytest.skip(f"no database available: {type(e).__name__}")
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(scope="module")
def upcoming(db):
    from backend.app.models.match import Match
    from backend.app.models.prediction import Prediction

    rows = (db.query(Match, Prediction)
            .join(Prediction, Prediction.match_id == Match.id)
            .filter(Match.result.is_(None),
                    Match.match_date >= dt.date.today())
            .all())
    if not rows:
        pytest.skip("no upcoming fixtures with predictions")
    return rows


# ── The suggestion the visitor reads ──────────────────────────────────────────

def test_the_suggested_market_matches_the_probability_bars(upcoming):
    """The pick must be the outcome the card shows as most likely.

    The suggestion used to be the highest-EV market, which is a different thing
    entirely: over 470 settled fixtures those picks landed 32% of the time
    against 53% for simply taking the model's favourite. A card that says
    "Away 41%" while the bars show Home ahead is incoherent to a reader.
    """
    bad = []
    for m, p in upcoming:
        if p.insufficient_data or not p.suggested_market:
            continue
        market = p.suggested_market.split(" @ ")[0]
        probs = {"Home Win": p.home_win_prob, "Draw": p.draw_prob,
                 "Away Win": p.away_win_prob}
        if market not in probs:
            continue
        if probs[market] < max(probs.values()) - 1e-9:
            bad.append(f"{m.home_team} v {m.away_team}: says {market} "
                       f"but {max(probs, key=probs.get)} is higher")
    assert not bad, "suggestion contradicts the probabilities:\n" + "\n".join(bad[:10])


def test_the_model_gives_each_fixture_its_own_numbers(upcoming):
    """Distinct fixtures must produce distinct RAW model output.

    Default-feature fixtures collapse onto one probability triple — 14 of 24
    UEFA qualifiers once shared just four, and Fenerbahçe v Górnik came out
    identical to Kauno Žalgiris v KI Klaksvík.

    Asserted on the RAW columns on purpose. The SERVED probabilities legitimately
    cluster: isotonic calibration is a step function, so 2,123 distinct raw
    triples map to a few hundred calibrated ones. Testing the served numbers
    would fail permanently on correct behaviour — checked before writing this,
    raw was 2123/2123 distinct while served was 425.
    """
    raw = [(p.raw_home_prob, p.raw_draw_prob, p.raw_away_prob)
           for _, p in upcoming
           if not p.insufficient_data and p.raw_home_prob is not None]
    if len(raw) < 20:
        pytest.skip("too few served predictions with raw columns to judge")
    distinct = {tuple(round(v, 4) for v in t) for t in raw}
    assert len(distinct) > len(raw) * 0.8, (
        f"{len(raw)} predictions share only {len(distinct)} distinct RAW "
        "probability triples — features are collapsing to defaults")


def test_insufficient_data_is_only_set_when_history_is_really_missing(upcoming, db):
    """The flag must reflect the data, not a stale prediction.

    Four fixtures were still flagged after the history import purely because
    their rows predated it — the model knew both clubs by then.
    """
    from backend.app.routers.matches import _unknown_sides

    wrong = [f"{m.home_team} v {m.away_team}"
             for m, p in upcoming
             if p.insufficient_data and not _unknown_sides(m.home_team, m.away_team)]
    assert not wrong, (
        "flagged 'insufficient data' although both clubs are known "
        f"(stale predictions — recompute): {wrong[:10]}")


# ── Fixture hygiene ───────────────────────────────────────────────────────────

def test_no_fixture_is_stored_twice(db):
    """One match, one row.

    Two feeds spelling a club differently wrote "SC Braga" and "Sp Braga"
    against the same opponent and date — two predictions, two cards, and the
    club's Elo split across both.
    """
    from backend.app.models.match import Match
    from scripts.team_resolver import COMMON_ALIASES

    def canon(t: str) -> str:
        return re.sub(r"[^a-z0-9]", "", COMMON_ALIASES.get(t, t).lower())

    rows = db.query(Match).filter(
        Match.match_date >= dt.date.today() - dt.timedelta(days=30)).all()
    seen: dict[tuple, str] = {}
    dupes = []
    for m in rows:
        key = (m.league, m.match_date, canon(m.home_team), canon(m.away_team))
        if key in seen:
            dupes.append(f"{m.league} {m.match_date} {seen[key]} / "
                         f"{m.home_team} v {m.away_team}")
        seen[key] = f"{m.home_team} v {m.away_team}"
    assert not dupes, "duplicate fixtures (run dedupe_fixtures.py):\n" + "\n".join(dupes[:10])


def test_upcoming_fixtures_mostly_carry_a_usable_prediction(upcoming):
    """Coverage guard.

    Blank cards are the most visible failure this project has — a whole
    competition night reading "no prediction". Deliberately loose: European
    qualifying rounds draw on leagues nobody publishes history for, so some
    blanks are honest. This fires when the share collapses.
    """
    served = sum(1 for _, p in upcoming if not p.insufficient_data)
    share = served / len(upcoming)
    assert share > 0.60, (
        f"only {share:.0%} of {len(upcoming)} upcoming fixtures have a usable "
        "prediction — ingestion or name resolution has regressed")


# ── Stats the pages read ──────────────────────────────────────────────────────

def test_team_stats_are_reachable_under_the_names_we_store(db):
    """Ingested cards/corners must be findable by the read side.

    They were not: stats sat in team_match_stats under the API spelling while
    club_props looked for the CSV one, so match pages showed "—" for clubs whose
    data was already in the database.
    """
    from sqlalchemy import text

    from backend.app.ml.club_props import NAME_OVERRIDES, _api_name

    stored = {s for (s,) in db.execute(
        text("SELECT DISTINCT team FROM team_match_stats")).fetchall()}
    if not stored:
        pytest.skip("team_match_stats is empty")

    unreachable = [our for our, api in NAME_OVERRIDES.items()
                   if api in stored and _api_name(db, our) is None]
    assert not unreachable, (
        "stats exist but the read side cannot find them for: "
        f"{unreachable[:10]}")
