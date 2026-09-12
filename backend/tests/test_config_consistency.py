"""Cross-file invariants that no single module can enforce on its own.

Every assertion here corresponds to a bug that actually shipped, was found by a
human looking at the site, and cost a debugging session. The common shape is a
fact duplicated in two places that quietly drifted apart — nothing raised, the
feature just stopped doing anything.

Deliberately offline: no DB, no network, no API keys, so CI runs it on every
push. That is the whole point — these are exactly the failures that survive to
production because nothing fails loudly enough to notice.
"""
from __future__ import annotations

import glob
import os
import re

import pytest

from backend.app.ml.club_props import NAME_OVERRIDES as READ_OVERRIDES
from backend.app.ml.draw_classifier import DRAW_FEATURE_COLS
from backend.app.ml.features import (
    FEATURE_COLS,
    HISTORY_ONLY_LEAGUES,
    LEAGUE_DUMMY_COLS,
    ONE_HOT_LEAGUES,
)
from backend.app.ml.odds_analysis_service import (
    LEAGUE_SPORT_KEY,
    LEAGUE_SPORT_KEY_ALTS,
    _LEAGUE_API_SPORTS_ID,
)


# ── League wiring ─────────────────────────────────────────────────────────────

def test_every_predicted_league_has_an_api_football_id():
    """A league we price must be resolvable for stats ingestion.

    2026-07-31: `fetch_club_team_stats` kept its own hand-copied LEAGUE_IDS that
    was missing the twelve leagues added the day before. Every one of their
    clubs fell through to the per-team /teams?search fallback — 177 search calls
    in a run that normally makes 54 — and 50 clubs still ended up with no id at
    all, so their cards showed "—" for cards and corners.
    """
    missing = [lg for lg in ONE_HOT_LEAGUES if lg not in _LEAGUE_API_SPORTS_ID]
    assert not missing, f"leagues with no API-Football id: {missing}"


def test_every_fitted_league_is_one_hot_encoded():
    """The reverse direction — the one that was actually broken.

    Every other guard here reads ONE_HOT_LEAGUES and checks it against some
    other table: has an API id, has a country, has training rows. All of them
    pass while a league is missing from ONE_HOT_LEAGUES entirely, because a
    league that is not in the list is not iterated.

    2026-09-03: Championship, LeagueOne, Eredivisie and PrimeiraLiga were fitted
    on from the first commit and never encoded — 24,955 rows, 25.2% of the
    training set, reaching the model with every dummy zero, i.e. as the same
    "unnamed league" a Champions League tie gets. Nothing failed; the model just
    could not tell a 27.0%-draw division from a 23.6% one.

    Reads the CSV filenames rather than the parsed frame: cheap enough for the
    offline suite, and a league whose files exist is a league that will be
    fitted on the next retrain — which is exactly when this must fail.
    """
    raw_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    on_disk = {os.path.basename(p).split("_")[0]
               for p in glob.glob(os.path.join(raw_dir, "*.csv"))}
    fitted = on_disk - set(HISTORY_ONLY_LEAGUES) - {"international"}
    if not fitted:
        pytest.skip("no training CSVs on disk")

    missing = sorted(fitted - set(ONE_HOT_LEAGUES))
    assert not missing, (
        f"{len(missing)} league(s) are trained on but have no one-hot column, so "
        f"the model cannot tell them apart: {missing}. Add them to "
        f"ONE_HOT_LEAGUES (and retrain), or to HISTORY_ONLY_LEAGUES if they are "
        f"context only."
    )


def test_stats_fetcher_uses_the_shared_league_id_map():
    """The fetcher must not keep a private copy of the league→id mapping."""
    from scripts.fetch_club_team_stats import LEAGUE_IDS

    assert LEAGUE_IDS == dict(_LEAGUE_API_SPORTS_ID), (
        "fetch_club_team_stats.LEAGUE_IDS has drifted from "
        "odds_analysis_service._LEAGUE_API_SPORTS_ID"
    )


def test_the_training_split_cannot_go_stale():
    """The trees must not be fitted on a window that stopped moving.

    2026-09-03: the boundaries had been literals since the first commit. Twelve
    consecutive weekly retrains added 54 training rows between them
    (training_runs id 35→46: n_train 84,411 → 84,465) while the test set grew by
    246 — two full seasons invisible to the trees, and a 10-minute Monday job
    refitting the same data and reporting seed noise as a change in accuracy.

    Nothing could have failed here: a stale date is valid code. So this asserts
    against the clock instead, and against the documented window ORDER — trees,
    then calibration, then TEST, so the printed metric stays a forward estimate.
    """
    import pandas as pd

    from backend.app.ml.train import CAL_CUTOFF, TEST_CUTOFF, TRAIN_CUTOFF

    # Trees, then calibration, then test. The test window must come LAST or the
    # number a run prints is not a forward estimate — a calibrator fitted on
    # seasons after the test season inflates it.
    assert CAL_CUTOFF < TRAIN_CUTOFF < TEST_CUTOFF, (
        f"split boundaries out of order: trees<{CAL_CUTOFF} cal<{TRAIN_CUTOFF} "
        f"test<{TEST_CUTOFF} — the test window has to be the last one")

    if any(os.getenv(v) for v in ("ML_CAL_CUTOFF", "ML_TRAIN_CUTOFF", "ML_TEST_CUTOFF")):
        pytest.skip("split pinned by ML_*_CUTOFF for a backtest")

    from backend.app.ml.train import (
        CAL_SEASONS, TEST_SEASON_MATURITY_MONTHS, _season_start,
    )

    # Re-derive the rule from today's date. An age-only assertion is not enough:
    # on the day this bug was found the frozen 2024-07-01 was 26 months old and
    # would have passed any reasonable age bound. What gives it away is that it
    # is not the value the rule produces.
    today    = pd.Timestamp.today().normalize()
    current  = _season_start(today)
    mature   = today >= current + pd.DateOffset(months=TEST_SEASON_MATURITY_MONTHS)
    latest   = current if mature else current - pd.DateOffset(years=1)

    assert TRAIN_CUTOFF == latest, (
        f"the test season starts at {TRAIN_CUTOFF.date()}, but the season rule "
        f"says {latest.date()} for today ({today.date()}). A hard-coded split "
        f"stops moving while the calendar does not — that is how two whole "
        f"seasons became invisible to the model."
    )
    assert TEST_CUTOFF == TRAIN_CUTOFF + pd.DateOffset(years=1)
    assert CAL_CUTOFF == TRAIN_CUTOFF - pd.DateOffset(years=CAL_SEASONS)
    assert TEST_CUTOFF > today - pd.DateOffset(months=18), (
        f"TEST_CUTOFF {TEST_CUTOFF.date()} is too far in the past — the "
        f"calibration window has stopped following the calendar."
    )


def test_the_season_rule_actually_advances():
    """The rule itself, at fixed dates — the part `today` cannot exercise.

    `today` cannot exercise the rollover, so the rule is checked at fixed dates:
    what separates a rolling rule from a frozen literal is that one moves next
    December and the other does not.
    """
    import pandas as pd

    from backend.app.ml.train import (
        CAL_SEASONS, TEST_SEASON_MATURITY_MONTHS, _season_start,
    )

    def latest_complete_on(day: str) -> pd.Timestamp:
        ts = pd.Timestamp(day)
        cur = _season_start(ts)
        return cur if ts >= cur + pd.DateOffset(months=TEST_SEASON_MATURITY_MONTHS) \
            else cur - pd.DateOffset(years=1)

    assert _season_start(pd.Timestamp("2026-06-30")) == pd.Timestamp("2025-07-01")
    assert _season_start(pd.Timestamp("2026-07-01")) == pd.Timestamp("2026-07-01")

    # Immature season → the latest COMPLETE one is still the previous.
    assert latest_complete_on("2026-09-04") == pd.Timestamp("2025-07-01")
    assert latest_complete_on("2026-11-30") == pd.Timestamp("2025-07-01")
    # …and it steps forward on its own, without anyone editing train.py.
    assert latest_complete_on("2026-12-01") == pd.Timestamp("2026-07-01")
    assert latest_complete_on("2027-06-30") == pd.Timestamp("2026-07-01")
    assert latest_complete_on("2027-12-01") == pd.Timestamp("2027-07-01")
    # A year of literals would have frozen here; the rule has moved twice.
    assert latest_complete_on("2028-12-01") == pd.Timestamp("2028-07-01")

    # And the windows derived from it stay in the documented order — trees,
    # calibration, test — with the TEST window last so it stays a forward
    # estimate however CAL_SEASONS is set.
    for seasons in (1, 2, 3):
        latest    = latest_complete_on("2026-09-04")
        test_end  = latest + pd.DateOffset(years=1)
        cal_start = latest - pd.DateOffset(years=seasons)
        assert cal_start < latest < test_end, seasons


def test_history_only_leagues_are_never_one_hot_encoded():
    """History-only leagues are context for Elo/form, never a fixture we price.

    A dummy column for a league that never appears at prediction time is dead
    weight that reads as a real feature.
    """
    overlap = set(ONE_HOT_LEAGUES) & set(HISTORY_ONLY_LEAGUES)
    assert not overlap, f"league is both predicted and history-only: {sorted(overlap)}"


# ── Feature vector ────────────────────────────────────────────────────────────

def test_league_dummies_are_generated_not_hand_written():
    """FEATURE_COLS and DRAW_FEATURE_COLS must carry every league dummy.

    These three lists were maintained by hand and adding a league to some but
    not others produced a column that is always zero — no error, just a feature
    that silently does nothing.
    """
    for name, cols in (("FEATURE_COLS", FEATURE_COLS),
                       ("DRAW_FEATURE_COLS", DRAW_FEATURE_COLS)):
        present = {c for c in cols if c.startswith("league_")}
        missing = set(LEAGUE_DUMMY_COLS) - present
        assert not missing, f"{name} is missing league dummies: {sorted(missing)}"


def test_feature_columns_have_no_duplicates():
    """A repeated column silently doubles that feature's weight in the matrix."""
    for name, cols in (("FEATURE_COLS", FEATURE_COLS),
                       ("DRAW_FEATURE_COLS", DRAW_FEATURE_COLS)):
        dupes = {c for c in cols if cols.count(c) > 1}
        assert not dupes, f"{name} has duplicate columns: {sorted(dupes)}"


# ── Team-name tables ──────────────────────────────────────────────────────────

def test_name_overrides_is_one_shared_table():
    """The read and write sides must be the SAME object, not two copies.

    2026-07-31: club_props held 45 entries and fetch_club_team_stats 60. The
    read side was a strict subset, so stats were ingested for Sion, Thun, LASK,
    Rakow, Univ. Craiova and CFR Cluj and the match page could not find them —
    the rows were in the database the whole time, displayed as "—".
    """
    from scripts.fetch_club_team_stats import NAME_OVERRIDES as WRITE_OVERRIDES

    assert WRITE_OVERRIDES is READ_OVERRIDES, (
        "fetch_club_team_stats defines its own NAME_OVERRIDES again — import "
        "club_props.NAME_OVERRIDES instead, or the two will drift"
    )


def test_no_alias_points_at_a_youth_reserve_or_womens_side():
    """Aliases must resolve to the senior men's team.

    2026-07-31: the /teams?search fallback accepted "SK Rapid W" (women's),
    "CFR Cluj II" (reserves) and "Flamengo RJ U17" because each search returned
    exactly one hit and that was taken as unambiguous. Their match stats would
    have been charged to the first team's cards and corners.
    """
    from scripts.team_resolver import COMMON_ALIASES, is_youth_side

    bad = {src: dst for src, dst in
           {**COMMON_ALIASES, **READ_OVERRIDES}.items()
           if is_youth_side(dst) and not is_youth_side(src)}
    assert not bad, f"alias resolves a senior club onto another side: {bad}"


def test_alias_tables_have_no_self_referential_loops():
    """A → B where B → C means the first hop is dead. Catches half-renames."""
    from scripts.team_resolver import COMMON_ALIASES

    chained = {src: dst for src, dst in COMMON_ALIASES.items()
               if dst in COMMON_ALIASES and COMMON_ALIASES[dst] != dst}
    assert not chained, f"alias target is itself aliased: {chained}"


# ── Bookmaker sport keys ──────────────────────────────────────────────────────

def test_every_sport_key_looks_like_a_real_odds_api_key():
    """Guards the shape, since the value itself needs the network.

    2026-07-30: `Championship` was mapped to "soccer_england_championship",
    which The Odds API answers with {"message": "Unknown sport"} — so that
    league silently carried NO odds at all, for as long as anyone can tell.
    The real key is "soccer_efl_champ". A live check lives in
    test_live_data.py; this one just stops obvious typos.
    """
    for league, key in LEAGUE_SPORT_KEY.items():
        assert key.startswith("soccer_"), f"{league}: {key!r} is not a soccer key"
        assert key == key.lower().strip(), f"{league}: {key!r} has case/space noise"
    for league, alts in LEAGUE_SPORT_KEY_ALTS.items():
        assert league in LEAGUE_SPORT_KEY, f"{league} has alts but no primary key"
        key_set = set(alts)
        assert key_set, f"{league}: empty alternate list"
        assert LEAGUE_SPORT_KEY[league] not in key_set, (
            f"{league}: primary key repeated in its own alternates")


@pytest.mark.parametrize("league", sorted(LEAGUE_SPORT_KEY))
def test_sport_keys_are_unique_per_league(league):
    """Two leagues sharing a key means one of them is silently served the
    other's fixtures — the bug that once wiped out EL and ECL league-phase odds."""
    owners = [lg for lg, k in LEAGUE_SPORT_KEY.items() if k == LEAGUE_SPORT_KEY[league]]
    assert owners == [league], f"sport key shared by {owners}"


# ── The reader-facing claim policy ────────────────────────────────────────────
# EV was retired as a *claim* to the reader: selecting on model-minus-market
# disagreement selects the model's own largest errors (EV-picked 32.1% vs plain
# argmax 52.6% over 470 settled fixtures — scripts/eval_gate_power.py §2b).
# compute_predictions.py stopped writing ev_score and MatchCard dropped its
# "⚡ EV +x%" badge. The LLM narrative prompt was the one surface the decision
# never reached, so match pages kept opening with "EV +24.2%" — on fixtures the
# gate had already declined to suggest. These pin the policy in the two places
# it can regress: the prompt we send, and the sentence we ship.

def test_the_shipped_narrative_regression_is_still_detected():
    """The exact paragraph served for match 18037 (Groningen–Utrecht, 2026-08-09).

    It quoted "EV +24.2 %" and, one clause later, said the odds offered no
    positive value — both because the prompt asked for both. If this stops
    tripping the detector, the guard has been weakened.
    """
    from backend.app.ml.odds_analysis_service import _warn_if_narrative_breaks_policy

    shipped = (
        "Η μεγαλύτερη απόκλιση μεταξύ μοντέλου και bookmakers είναι η νίκη του "
        "φιλοξενούμενου (Utrecht): το μοντέλο δίνει 42 % ενώ οι bookmakers το "
        "εκτιμούν μόνο στο 32 % (EV +24.2 %). Παρόλο που το Utrecht φαίνεται "
        "προτιμώμενο από το μοντέλο, οι τρέχουσες αποδόσεις δεν προσφέρουν "
        "θετική αξία, οπότε δεν υπάρχει προτεινόμενη αγορά."
    )
    hits = _warn_if_narrative_breaks_policy(shipped, "Groningen", "Utrecht")
    assert "ev +" in hits, "EV framing no longer detected"
    assert "δεν προσφέρουν θετική αξία" in hits, "false no-value claim no longer detected"


def test_an_honest_narrative_is_not_flagged():
    """The guard must not fire on the wording we actually want, or it gets muted."""
    from backend.app.ml.odds_analysis_service import _warn_if_narrative_breaks_policy

    good = (
        "Το μοντέλο θεωρεί πιθανότερη τη νίκη της Ουτρέχτης με 42%, με τη "
        "βαθμολογία και τη φόρμα να στηρίζουν τον φιλοξενούμενο. Η αγορά είναι "
        "πιο συντηρητική και τη δίνει στο 32%. Δεν υπάρχουν δεδομένα τραυματιών."
    )
    assert _warn_if_narrative_breaks_policy(good, "Groningen", "Utrecht") == []


def test_the_analysis_prompt_never_hands_the_model_an_ev_figure():
    """No EV number reaches the LLM, so it cannot quote one.

    Reads the built prompt rather than the source, so a reworded prompt that
    reintroduces EV still fails. Bookmaker probabilities and odds are expected —
    only the derived return-per-stake figure is banned.
    """
    import backend.app.ml.odds_analysis_service as svc

    captured = {}

    def _capture(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        raise RuntimeError("stop before the network call")

    class _FakeGroq:
        def __init__(self, *a, **k):
            self.chat = type("c", (), {"completions": type("x", (), {"create": staticmethod(_capture)})()})()

    import sys, types
    sys.modules["groq"] = types.SimpleNamespace(Groq=_FakeGroq)

    svc.GROQ_API_KEY = "test-key"
    svc.cache_get = lambda *_a, **_k: svc.CACHE_MISS
    svc.cache_set = lambda *_a, **_k: None

    svc._get_llm_analysis(
        "Groningen", "Utrecht", "Eredivisie",
        {"home_win": 0.3194, "draw": 0.2566, "away_win": 0.4240, "over_2_5": 0.57},
        {
            "num_bookmakers": 9,
            "bookmakers": ["bet365"],
            "fair_probs": {"home_win": 0.4025, "draw": 0.2789, "away_win": 0.3186,
                           "over_2_5": 0.58, "under_2_5": 0.42},
            "raw_odds": {"home_win": 2.30, "draw": 3.40, "away_win": 2.93,
                         "over_2_5": 1.70, "under_2_5": 2.15},
        },
    )

    prompt = captured["prompt"]
    low = prompt.lower()

    # A NUMBER, not the word: the prompt legitimately names EV in order to forbid
    # it. What must never appear is a figure the model can quote, e.g. "EV +24.2%".
    ev_figures = re.findall(r"ev[\s:]*[+\-−]?\s*\d", low)
    assert not ev_figures, f"an EV figure is back in the analysis prompt: {ev_figures}"
    assert "αναμενόμενη αξία =" not in low, "the EV formula is back in the analysis prompt"
    # The false premise that produced the contradiction. Check the IMPERATIVE,
    # not the phrase: the prompt now quotes "offer no value" in order to forbid
    # it, so presence of the words is fine — being told to write them is not.
    assert "say so explicitly" not in low, (
        "prompt again instructs the model to assert an unverified 'no value' reason")
    assert "do not claim the odds" in low, "the no-value prohibition was removed"
    # Odds/probabilities must survive — the fix is about the claim, not the data.
    assert "2.93" in prompt, "bookmaker odds were removed along with EV"


def test_the_suggested_line_is_only_demanded_when_a_market_qualifies():
    """The prompt used to order 'omit the SUGGESTED line' and 'write the SUGGESTED
    line' in the same breath. Whichever branch runs, it must say one thing."""
    import inspect
    from backend.app.ml.odds_analysis_service import _get_llm_analysis

    src = inspect.getsource(_get_llm_analysis)
    assert "suggested_line_rule" in src, "the SUGGESTED output rule is unconditional again"
    i = src.index("suggested_line_rule =")
    assert "if best_market else" in src[i:i + 400], (
        "suggested_line_rule is no longer branched on best_market")


# ── Fixture pruning ───────────────────────────────────────────────────────────
# 2026-08-09: football-data.org answered "0 fixtures" for PrimeiraLiga,
# Eredivisie and CL while serving the other seven leagues normally. The caller
# handed prune_vanished all ten league codes anyway, so every unplayed fixture
# of those three inside the 60-day window was deleted as "vanished" — 129 real
# matches, one of them kicking off three hours later. An empty feed response is
# never evidence of cancellation.

def test_pruning_is_skipped_when_a_run_matched_no_fixtures():
    """`notin_(empty)` is a no-op, so an empty touched_ids used to collapse the
    WHERE to `True` — i.e. delete every unplayed fixture of those leagues."""
    from scripts.fixture_upsert import prune_vanished

    class _ExplodingDB:
        def execute(self, *_a, **_k):
            raise AssertionError("prune ran with nothing matched — it must not")

        def commit(self):
            raise AssertionError("prune committed with nothing matched")

    assert prune_vanished(_ExplodingDB(), ["Eredivisie"], set()) == 0


def test_pruning_does_nothing_when_no_league_qualifies():
    from scripts.fixture_upsert import prune_vanished

    class _ExplodingDB:
        def execute(self, *_a, **_k):
            raise AssertionError("prune ran with an empty league list")

        def commit(self):
            raise AssertionError("prune committed with an empty league list")

    assert prune_vanished(_ExplodingDB(), [], {1, 2, 3}) == 0


def test_prune_scope_is_limited_to_leagues_the_feed_answered_for():
    """The caller must derive the league list from the fixtures it received,
    never from the static COMPETITIONS map."""
    import inspect

    import scripts.fetch_upcoming as fu

    src = inspect.getsource(fu.main) if hasattr(fu, "main") else inspect.getsource(fu)
    i = src.index("prune_vanished(db")
    call = src[i:i + 200]
    assert "COMPETITIONS.values()" not in call, (
        "prune scope is the full league map again — a league the feed did not "
        "answer for will have its fixtures deleted")
    assert "leagues_seen" in call, "prune scope is no longer derived from the fetched fixtures"


def test_alerts_are_never_sent_from_a_test_run():
    """A test must not page a human.

    2026-08-09: the no-EV regression test above feeds the guard the banned
    paragraph deliberately, and the guard pushes to GATE_ALERT_URL — so every
    pytest run sent a real "Match narrative broke the no-EV policy" alert to the
    owner's phone about a match that was fine.
    """
    import os

    from backend.app.alerting import post_alert

    os.environ["GATE_ALERT_URL"] = "https://ntfy.sh/should-never-be-hit"
    try:
        assert post_alert("this must not leave the test process") is False
    finally:
        os.environ.pop("GATE_ALERT_URL", None)


def test_every_api_football_step_in_run_daily_is_behind_the_preflight_guard():
    """A step that needs API-Football must not run when the pre-flight failed.

    2026-08-09: the pre-flight correctly detected the IP block and alerted, but
    only the first eight steps were wrapped in `if [ "$API_FOOTBALL_OK" -eq 1 ]`.
    Nine later ones ran anyway — fetch_squad_strength alone logged a warning per
    national team — and the derived "DATA GAPS: 11 alerts, 35 warnings" push
    buried the single alert that named the actual cause.

    Kept as a test because run_daily.sh keeps growing: a new API-Football step
    added without the guard is invisible until an outage, and by then it is a
    phone full of noise. Counts `fi` anywhere on the line — the guards close
    with `...; fi`, and a parser that only accepts a bare `fi` reports every
    later step as guarded (which is how this was missed the first time).
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    scripts_dir = root / "scripts"

    needs_api = set()
    for p in scripts_dir.glob("*.py"):
        src = p.read_text(encoding="utf-8", errors="ignore")
        if "API_SPORTS_KEY" in src or "from scripts.fetch_player_stats import" in src:
            needs_api.add(p.name)
    needs_api.discard("preflight_api_football.py")   # the guard's own source

    depth, guard_depths, unguarded = 0, [], []
    for lineno, raw in enumerate(
            (scripts_dir / "run_daily.sh").read_text().splitlines(), 1):
        line = raw.split("#")[0]
        opens = len(re.findall(r"(?:^|[\s;])if\s", line))
        closes = len(re.findall(r"(?:^|[\s;])fi(?:\s|;|$)", line))

        for _ in range(opens):
            depth += 1
        # Two guards satisfy this, and they are not interchangeable elsewhere:
        # API_FOOTBALL_OK is cleared by an IP block AND by the daily cap, while
        # AF_BLOCKED marks only the "API-Football is unusable" case. A step
        # whose output stays meaningful on a capped day (the completeness
        # report reads our own database) may sit behind the narrower one — what
        # this test enforces is that neither runs during an IP block.
        if opens and ('API_FOOTBALL_OK" -eq 1' in line
                      or 'AF_BLOCKED" -eq 0' in line):
            guard_depths.append(depth)

        hit = re.search(r"scripts/([a-z_0-9]+\.py)", line)
        if hit and hit.group(1) in needs_api and not guard_depths:
            unguarded.append(f"{hit.group(1)} (run_daily.sh:{lineno})")

        for _ in range(closes):
            if guard_depths and guard_depths[-1] == depth:
                guard_depths.pop()
            depth -= 1

    assert not unguarded, (
        "API-Football steps not behind the pre-flight guard — they will run and "
        "fail during an IP block:\n  " + "\n  ".join(unguarded))


def _api_football_scripts() -> set[str]:
    """Scripts that reach API-Football — the definition the test above uses."""
    import pathlib

    found = set()
    for p in (pathlib.Path(__file__).resolve().parents[2] / "scripts").glob("*.py"):
        src = p.read_text(encoding="utf-8", errors="ignore")
        if "API_SPORTS_KEY" in src or "from scripts.fetch_player_stats import" in src:
            found.add(p.name)
    found.discard("preflight_api_football.py")
    return found


def _shell_logical_lines(path) -> list[tuple[int, str]]:
    """(first line number, text): whole-line comments dropped, `\\` joined."""
    out, buf, start = [], "", 0
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = "" if raw.lstrip().startswith("#") else raw
        if not buf:
            start = lineno
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        out.append((start, buf + line))
        buf = ""
    return out


# `python scripts/x.py <args>` up to the first redirect, pipe or separator.
_PY_STEP = r"python\s+scripts/([a-z_0-9]+\.py)((?:\s+(?![0-9]?>|\||;|&)\S+)*)"


def _py_steps(line: str) -> list[tuple[str, tuple[str, ...]]]:
    import re

    return [(m.group(1), tuple(m.group(2).split())) for m in re.finditer(_PY_STEP, line)]


def test_af_recovery_replays_every_step_a_blocked_daily_run_skips():
    """run_af_recovery.sh must replay what the guard skips, with the same arguments.

    It exists because a blocked 06:00 run used to leave the data a day old even
    after the new address was whitelisted (2026-09-10: fixed around 10:00,
    nothing re-ran). It only helps while it mirrors run_daily.sh — a step added
    behind the guard there and not here is silently never recovered, and a
    changed argument (a wider --days-back, a bigger request budget) recovers
    something other than what the daily run would have fetched. The Monday-only
    block is excluded: a replay never retrains.
    """
    import pathlib
    import re

    scripts_dir = pathlib.Path(__file__).resolve().parents[2] / "scripts"

    depth, guards, weekly, guarded = 0, [], [], set()
    for _, line in _shell_logical_lines(scripts_dir / "run_daily.sh"):
        opens = len(re.findall(r"(?:^|[\s;])if\s", line))
        closes = len(re.findall(r"(?:^|[\s;])fi(?:\s|;|$)", line))
        depth += opens
        if opens and ('API_FOOTBALL_OK" -eq 1' in line or 'AF_BLOCKED" -eq 0' in line):
            guards.append(depth)
        if opens and 'DAY_OF_WEEK" -eq 1' in line:
            weekly.append(depth)
        if guards and not weekly:
            guarded.update(_py_steps(line))
        for _ in range(closes):
            if guards and guards[-1] == depth:
                guards.pop()
            if weekly and weekly[-1] == depth:
                weekly.pop()
            depth -= 1

    replayed = {step for _, line in _shell_logical_lines(scripts_dir / "run_af_recovery.sh")
                for step in _py_steps(line)}

    assert len(guarded) >= 15, (
        f"found only {len(guarded)} guarded steps in run_daily.sh — the parser "
        "is broken, and a broken parser passes this test vacuously")
    missing = sorted(f"{s} {' '.join(a)}".strip() for s, a in guarded - replayed)
    assert not missing, (
        "run_daily.sh skips these during an API-Football block but "
        "run_af_recovery.sh never replays them (or replays them with other "
        "arguments):\n  " + "\n  ".join(missing))


def test_blocked_and_quota_exit_codes_mean_the_same_thing_everywhere(monkeypatch):
    """Exit 2 = IP refused and 4 = daily cap, in the pre-flight, in every fetcher
    (scripts/_http_retry.py) and in both shell scripts that read them; the
    watchdog, the daily run and the recovery run share one marker file. Each
    pair is written in two languages in different files, which is how things
    drift."""
    import pathlib

    import scripts._http_retry as hr
    import scripts.preflight_api_football as pf

    class _Refused:
        def json(self):
            return {"errors": {"Ip": "This IP is not allowed to call the API"}}

    monkeypatch.setenv("API_SPORTS_KEY", "test-key")
    monkeypatch.setattr(pf.requests, "get", lambda *a, **k: _Refused())
    monkeypatch.setattr(pf, "current_public_ip", lambda: "203.0.113.7")
    monkeypatch.setattr(pf, "send_alert", lambda *a, **k: None)
    assert pf.main() == hr.API_FOOTBALL_BLOCKED_RC

    scripts_dir = pathlib.Path(__file__).resolve().parents[2] / "scripts"
    for name in ("run_daily.sh", "run_af_recovery.sh"):
        src = (scripts_dir / name).read_text()
        assert f"AF_BLOCKED_RC={hr.API_FOOTBALL_BLOCKED_RC}\n" in src, name
        assert f"AF_QUOTA_RC={hr.API_FOOTBALL_QUOTA_RC}\n" in src, name
    for name in ("run_daily.sh", "run_af_recovery.sh", "run_watchdog.sh"):
        assert ".af-recovery-pending" in (scripts_dir / name).read_text(), name


def test_every_scheduled_api_football_call_comes_after_a_preflight():
    """Outside run_daily.sh (guarded above), a scheduled job that reaches
    API-Football must ask /status first. The odds poll did not: from 2026-08-01
    to 2026-09-10 its UEFA refresh logged "This IP is not allowed" 167 times,
    exited 0 every time, and alerted nobody."""
    import pathlib

    needs = _api_football_scripts()
    scripts_dir = pathlib.Path(__file__).resolve().parents[2] / "scripts"
    blind = []
    for sh in sorted(scripts_dir.glob("*.sh")):
        if sh.name == "run_daily.sh":
            continue
        preflight_seen = False
        for lineno, line in _shell_logical_lines(sh):
            if "scripts/preflight_api_football.py" in line:
                preflight_seen = True
            for script, _ in _py_steps(line):
                if script in needs and not preflight_seen:
                    blind.append(f"{sh.name}:{lineno} {script}")
    assert not blind, (
        "scheduled API-Football calls with no pre-flight before them — an IP "
        "block makes them log and exit 0:\n  " + "\n  ".join(blind))


def test_importing_an_api_football_script_does_no_work():
    """Importing a fetcher must not fetch.

    download_xg_apifootball.py kept its whole body at module level, so
    `import scripts.download_xg_apifootball` — a harmless-looking import check
    on 2026-09-10 — parsed an empty argv and started the full 2021–2025 xG
    download: 751 API-Football requests before it was killed. A loop or an
    argv parse at module level is the signature of a script that runs on import.
    """
    import ast
    import pathlib

    scripts_dir = pathlib.Path(__file__).resolve().parents[2] / "scripts"
    offenders = []
    for name in sorted(_api_football_scripts()):
        tree = ast.parse((scripts_dir / name).read_text(encoding="utf-8", errors="ignore"))
        for node in tree.body:
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                offenders.append(f"{name}:{node.lineno} loop at module level")
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If)):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") == "parse_args":
                    offenders.append(f"{name}:{node.lineno} argv parsed at module level")
    assert not offenders, (
        "these scripts do work when imported — move it into main() behind "
        "`if __name__ == \"__main__\"`:\n  " + "\n  ".join(offenders))


def test_alert_helper_is_sourced_before_its_first_use():
    """A shell script that calls send_alert before sourcing _alert.sh gets
    "command not found" instead of a push. run_daily.sh did exactly that for
    the "backup NOT restorable" alert at step 0, ~700 lines before its only
    `source` — so the one alert saying the accounts and the bet ledger were
    unprotected could never have been delivered."""
    import pathlib
    import re

    scripts_dir = pathlib.Path(__file__).resolve().parents[2] / "scripts"
    early = []
    for sh in sorted(scripts_dir.glob("*.sh")):
        if sh.name == "_alert.sh":
            continue
        sourced_at = first_use = None
        for lineno, line in _shell_logical_lines(sh):
            if sourced_at is None and re.search(r"(?:source|\.)\s+\S*_alert\.sh", line):
                sourced_at = lineno
            if first_use is None and re.search(r"(?:^|[\s;|&(])send_alert\s", line):
                first_use = lineno
        if first_use is not None and (sourced_at is None or sourced_at > first_use):
            early.append(f"{sh.name}:{first_use} (sourced at {sourced_at})")
    assert not early, "send_alert called before _alert.sh is sourced:\n  " + "\n  ".join(early)


def test_a_day_is_only_marked_as_run_once_docker_is_ready():
    """The once-a-day stamps must be written after wait_for_docker succeeds.

    run_daily.sh wrote its stamp ~110 lines before waiting for Docker. A 06:00
    run that aborted on a daemon still starting marked the day as done, and the
    plist's KeepAlive retry then skipped itself — the day's pipeline lost to a
    slow Docker Desktop."""
    import pathlib

    scripts_dir = pathlib.Path(__file__).resolve().parents[2] / "scripts"
    for name, stamp in (("run_daily.sh", "DAILY_STAMP"),
                        ("run_prematch.sh", "PREMATCH_STAMP")):
        lines = _shell_logical_lines(scripts_dir / name)
        writes = [n for n, text in lines if f'> "${stamp}"' in text]
        ready = [n for n, text in lines if "wait_for_docker" in text and "||" in text]
        assert writes and ready, f"{name}: stamp write or Docker wait not found"
        assert min(writes) > min(ready), (
            f"{name}:{min(writes)} writes {stamp} before Docker is ready "
            f"(line {min(ready)})")


def test_launchd_restart_policies_are_the_intended_ones():
    """KeepAlive is not a harmless default. {SuccessfulExit: false} implies
    RunAtLoad (launchd.plist(5)), so the job also fires at every login, reboot
    and reinstall, and a failing run is restarted in a loop. The prematch job
    carried it and ran twice on 2026-08-31, 09-01 and 09-07. Two jobs keep it on
    purpose: the tunnel (always on) and the daily run, whose restart is its retry
    when Docker was not ready — safe only because its once-a-day stamp is
    written after Docker is (the test above)."""
    import pathlib
    import plistlib

    launchd_dir = pathlib.Path(__file__).resolve().parents[2] / "launchd"
    allowed = {"com.football-predictor.cloudflared": True,
               "com.football-predictor.daily": {"SuccessfulExit": False}}
    found = {}
    for p in sorted(launchd_dir.glob("*.plist")):
        with p.open("rb") as f:
            found[p.stem] = plistlib.load(f).get("KeepAlive")
    assert len(found) >= 5, f"only {len(found)} plists found — wrong directory?"
    wrong = {k: v for k, v in found.items() if v != allowed.get(k)}
    assert not wrong, f"unexpected KeepAlive policy: {wrong}"


def test_no_serving_path_fills_a_feature_training_leaves_missing():
    """Serving must not invent a value where training had none.

    train.py lists some features in `optional_feats` and never imputes them, so
    each model is fitted with them genuinely NaN and learns a branch for it. A
    serve-time constant means that branch is never taken — and the constant
    arrives beside still-NaN siblings, in combinations training never saw. The
    batch path stopped doing it on 2026-09-09; predict_match() — the API's
    cache-miss path — kept its own copy of the list and went on filling seven
    of them until 2026-09-10. Both copies are read from source here, so neither
    can drift back.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]

    def _dict_keys(path, target, inside=None):
        tree = ast.parse(path.read_text())
        scope = tree if inside is None else next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == inside)
        for node in ast.walk(scope):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                    and any(isinstance(t, ast.Name) and t.id == target
                            for t in node.targets)):
                return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
        raise AssertionError(f"no `{target} = {{...}}` in {path.name}")

    def _assigned(tree, name):
        return next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))

    # Read from source, not imported: train.py is the training entry point.
    train = ast.parse((root / "backend/app/ml/train.py").read_text())
    never_imputed = {c.value for s in ast.walk(_assigned(train, "optional_feats").value)
                     if isinstance(s, ast.Set)
                     for c in s.elts if isinstance(c, ast.Constant)}
    # Referee features are optional too, and _impute_optional deliberately
    # leaves them NaN ("a fake average referee hurts more than it helps").
    never_imputed |= {c.value for c in _assigned(train, "REF_COLS").value.elts
                      if isinstance(c, ast.Constant)}
    assert "h2h_draw_rate" in never_imputed and len(never_imputed) >= 20, (
        f"read only {len(never_imputed)} names from optional_feats — the parser "
        "is broken, and a broken parser passes this test vacuously")

    offenders = {}
    for label, path, target, inside in (
            ("predict.py predict_match()", root / "backend/app/ml/predict.py",
             "_fill", "predict_match"),
            ("compute_predictions.py DEFAULTS", root / "scripts/compute_predictions.py",
             "DEFAULTS", None)):
        bad = _dict_keys(path, target, inside) & never_imputed
        if bad:
            offenders[label] = sorted(bad)
    assert not offenders, (
        f"serve-time constants for features training leaves NaN: {offenders}")


def test_no_override_points_at_a_name_that_is_also_one_of_ours():
    """An override must translate OUR spelling into the FEED's, never the reverse.

    A mapping whose target is itself a key means the first hop is dead — the
    same half-rename this file already guards for the alias tables, but the
    override table was never checked.
    """
    chained = {src: dst for src, dst in READ_OVERRIDES.items()
               if dst in READ_OVERRIDES and READ_OVERRIDES[dst] != dst and dst != src}
    assert not chained, f"override target is itself overridden: {chained}"


def test_overrides_are_not_silently_identity_mapped_for_new_entries():
    """Identity entries ('Wolves' -> 'Wolves') are intentional pins, but a NEW
    league's club added as an identity map usually means someone guessed instead
    of reading the feed. Just assert the table stays free of empty targets."""
    blank = [k for k, v in READ_OVERRIDES.items() if not v or not v.strip()]
    assert not blank, f"overrides with an empty target: {blank}"


# ── Country equivalence in the club-stats id sweep ───────────────────────────

def test_country_guard_compares_nations_not_spellings():
    """The guard must not reject a club over a country's SPELLING.

    It compares what API-Football calls a country against what our training data
    calls it — two different vocabularies. A raw `!=` threw away ten correctly
    identified clubs on every run: Sparta Praha, Jablonec, Hradec Kralove
    ("Czech-Republic" vs our "Czechia"), Shkendija ("Macedonia"/"NMacedonia"),
    KI Klaksvik and NSI Runavik ("Faroe-Islands"/"FaroeIslands"), Larne
    ("Northern-Ireland"/"NorthernIreland"), plus Cardiff, Swansea and Vaduz,
    who simply play in a neighbour's league.
    """
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "_fcts", root / "scripts" / "fetch_club_team_stats.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    same = [
        ("Czech-Republic", "Czechia"),
        ("Macedonia", "NMacedonia"),
        ("Faroe-Islands", "FaroeIslands"),
        ("Northern-Ireland", "NorthernIreland"),
        ("Wales", "England"),            # Cardiff, Swansea, Wrexham
        ("Liechtenstein", "Switzerland"),  # Vaduz
    ]
    for api, ours in same:
        assert mod._same_country(api, ours), f"{api} should match {ours}"

    # …and it must STILL reject the collision it was written for: La Liga's
    # Athletic Club is not Brazil's Athletic Club of Serie B.
    assert not mod._same_country("Spain", "Brazil")
    assert not mod._same_country("Portugal", "Brazil")

    # Missing information is not a contradiction.
    assert mod._same_country("", "Spain")
    assert mod._same_country("Spain", "")

    # …and the sweep must actually USE it. Testing the helper alone passed
    # happily while the call site still compared the two strings directly,
    # which is the whole bug.
    src = (Path(__file__).resolve().parents[2]
           / "scripts" / "fetch_club_team_stats.py").read_text(encoding="utf-8")
    assert "if not _same_country(api_country, our_country):" in src
    assert "api_country != our_country" not in src


def test_club_stats_sweep_cannot_starve_a_club_forever():
    """Teams must not be walked in a fixed order against a request cap.

    `target` was `sorted(...)` and the cap lands around "M", so every club later
    in the alphabet was never processed on any run — Odense, Paide, SJK, Slovan
    Bratislava and Valur Reykjavik alerted "no stored stats" every morning and
    were right. Ordering by staleness alone is not enough either: ~150 clubs
    share an empty key, so a stable sort still walks them A→Z.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2]
           / "scripts" / "fetch_club_team_stats.py").read_text(encoding="utf-8")
    assert "MAX(match_date)" in src, "sweep no longer orders by staleness"
    assert "random.Random(date.today().toordinal())" in src, (
        "no per-day rotation — clubs sharing a staleness key will starve again")
    assert "target.sort(" in src and "target = sorted({r[0] for r in rows})" in src


def test_api_football_quota_exit_code_is_the_same_number_on_both_sides():
    """The daily cap's exit code is agreed between Python and bash.

    2026-08-25: API-Football hit its cap mid-run and three healthy steps —
    player match stats, team match stats, club form — were reported as failures.
    The run skipped its heartbeat and pushed an urgent alert about a condition
    that clears itself at the next reset, while each later step spent another
    request to be told the same thing.

    The fix is a dedicated exit code: `QuotaExhausted` carries it, and
    run_daily.sh's `_af_rc` reads it as "skip the rest of API-Football", not
    "this step is broken". The number lives in two files, which is exactly the
    drift this module exists to catch — a bash `AF_QUOTA_RC=5` against a Python
    4 would silently restore the old paging behaviour.
    """
    from pathlib import Path

    from scripts._http_retry import API_FOOTBALL_QUOTA_RC

    src = (Path(__file__).resolve().parents[2]
           / "scripts" / "run_daily.sh").read_text(encoding="utf-8")
    assert f"AF_QUOTA_RC={API_FOOTBALL_QUOTA_RC}" in src, (
        "run_daily.sh's AF_QUOTA_RC no longer matches "
        f"_http_retry.API_FOOTBALL_QUOTA_RC ({API_FOOTBALL_QUOTA_RC})")


def test_quota_exhaustion_never_exits_with_the_generic_failure_code():
    """A script that reports the daily cap must also carry the quota exit code.

    `raise SystemExit("...")` exits 1 — indistinguishable from a real crash, so
    run_daily.sh pages for it and keeps calling the remaining API-Football
    steps. A new fetch_* script copy-pasting the old line would reintroduce the
    2026-08-25 alert without touching anything this test's neighbours check.

    Either mechanism satisfies this: raise `QuotaExhausted`, or (when there is
    partial work worth writing first) finish the writes and `sys.exit` with
    `API_FOOTBALL_QUOTA_RC`. What must never happen is the message without one
    of them.
    """
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    offenders = []
    for p in sorted(scripts_dir.glob("*.py")):
        src = p.read_text(encoding="utf-8", errors="ignore")
        if "daily quota exhausted" not in src:
            continue
        if "QuotaExhausted" not in src and "API_FOOTBALL_QUOTA_RC" not in src:
            offenders.append(p.name)
    assert offenders == [], (
        "reports the daily cap but exits with the generic failure code, so the "
        "daily run pages instead of skipping: " + ", ".join(offenders))


# ── One daily run per day ─────────────────────────────────────────────────────
# The lock stops two runs OVERLAPPING; it says nothing about a second run hours
# after the first finished. On 2026-08-25 the pipeline ran at 06:00 and again at
# 10:16 (launchd coalesces missed calendar intervals after sleep), and that alone
# exhausted the account: one run costs 4,400–5,600 API-Football requests against
# a 7,500/day cap, so the second ran out partway and every remaining step
# reported a failure nothing could act on until the reset.

def _run_daily() -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[2] / "scripts" /
            "run_daily.sh").read_text(encoding="utf-8")


def test_the_daily_run_refuses_to_run_twice_in_one_day():
    body = _run_daily()

    assert "DAILY_STAMP" in body, "nothing stops a second full run on the same day"
    assert "already ran today" in body


def test_the_same_day_guard_can_be_overridden_deliberately():
    """A guard with no escape hatch gets deleted the first time someone needs a
    re-run, which is worse than not having it."""
    assert "FORCE_DAILY" in _run_daily()


def test_the_guard_sits_after_the_lock_not_instead_of_it():
    """They solve different problems: the lock is about concurrency, the stamp
    about repetition. Losing either brings back a different bug."""
    body = _run_daily()

    assert body.index('acquire_lock "run_daily"') < body.index("DAILY_STAMP")


# ── Market anchoring ─────────────────────────────────────────────────────────
# Restored at w=0.57 on 2026-09-01 after scripts/compare_anchoring.py replayed
# every settled match carrying both our raw probabilities and a de-vigged 1x2:
# accuracy climbed monotonically toward the market, 51.7% -> 54.6%, with no
# interior optimum. The site is a betting site, so the number beside a pick is
# the most accurate one we can produce.

def test_the_anchor_weight_is_the_measured_one():
    """0.85 since 2026-09-04, measured on 24,100 priced matches over four
    held-out seasons — 0.55 vs 0.85 is +0.21pp accuracy (P = 0.974) and
    -0.0036 log-loss (P = 1.000). The previous 0.57 came from 238 matches.

    Pinned because this weight decides most of every published probability, so
    it must not drift by accident. Changing it deliberately means changing this
    number and the table in predict.py together."""
    from backend.app.ml.predict import MARKET_ANCHOR_WEIGHT

    assert MARKET_ANCHOR_WEIGHT == 0.85


def test_anchoring_leaves_a_fixture_without_a_price_alone():
    """Most of a thin midweek card has no bookmaker line. Those keep the pure
    model rather than being dropped or defaulted."""
    from backend.app.ml.predict import anchor_to_market

    model = (0.50, 0.25, 0.25)
    assert anchor_to_market(model, None) == model
    assert anchor_to_market(model, (0.0, 0.0, 0.0)) == model
    assert anchor_to_market(model, (1.0, 3.0, 4.0)) == model   # 1.0 is not a price


def test_anchoring_de_vigs_before_blending():
    """We anchor to the bookmaker's OPINION, not their pricing. A 1x2 whose
    implied probabilities sum to 1.08 must contribute 1.00 of belief."""
    from backend.app.ml.predict import anchor_to_market

    out = anchor_to_market((0.34, 0.33, 0.33), (2.10, 3.40, 3.70))

    assert abs(sum(out) - 1.0) < 1e-9


def test_the_value_gate_reads_the_unblended_model():
    """The whole point of the gate is model-vs-market disagreement. Fed an
    anchored probability it compares the market with itself and finds an edge of
    roughly zero everywhere — silently, with no error to notice."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "backend" / "app" / "routers" /
           "predictions.py").read_text(encoding="utf-8")
    block = src[src.index("model_probs = {"):src.index("model_probs = {") + 500]

    assert "raw_home_prob" in block, "EV is being fed the anchored numbers"
    assert "raw_over_prob" in block
    # 2026-09-07: BTTS joined the anchoring, and it was the one market with no
    # unanchored column to protect it. Without raw_btts_prob every GG/NG edge
    # collapses to roughly minus the margin and the gate silently stops
    # surfacing goals bets — an accuracy fix that removes a feature.
    assert "raw_btts_prob" in block, (
        "BTTS is anchored but the EV gate still reads the served number")


def test_the_methodology_says_the_numbers_are_partly_the_market():
    """Publishing 54% without saying most of it is the bookmaker's own line
    would be the misleading version of this change.

    2026-09-07: this test pinned the literal string "57%", which is precisely
    what let the copy go stale. Commit 212738e raised MARKET_ANCHOR_WEIGHT from
    0.57 to 0.85 and the test kept passing, so the first paragraph of /stats told
    every visitor "43% our model, 57% the bookmakers' line" for three days while
    the real split was 15/85 — wrong by 28 percentage points.

    It now derives both percentages from the constant, in both languages, so the
    copy cannot survive a weight change. The failure message names the numbers to
    write.
    """
    from pathlib import Path

    from backend.app.ml.predict import MARKET_ANCHOR_WEIGHT

    i18n = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" /
            "i18n.ts").read_text(encoding="utf-8")

    assert i18n.count('"stats.anchor.body"') == 2, "missing in one language"

    market = round(MARKET_ANCHOR_WEIGHT * 100)
    model  = 100 - market
    bodies = [ln for ln in i18n.splitlines() if '"stats.anchor.body"' in ln]
    for body in bodies:
        assert f"{model}%" in body and f"{market}%" in body, (
            f"the anchoring copy does not state the weight actually served. "
            f"MARKET_ANCHOR_WEIGHT is {MARKET_ANCHOR_WEIGHT}, so it must say "
            f"{model}% our model and {market}% the market. Offending line:\n{body[:160]}")

    # …and no stale split may survive anywhere else in the file.
    for stale in ("43%", "57%", "30%", "70%"):
        if stale in (f"{model}%", f"{market}%"):
            continue
        assert stale not in i18n, (
            f"{stale} still appears in the copy; it is a retired anchor weight")


def test_the_gg_badge_is_derived_from_the_probability_it_sits_above():
    """A stored label and a served probability are not the same thing.

    `predictions.btts_prediction` is frozen at whatever threshold was in force
    the day the row was written — a record of what we published, and a useful
    one. Serving it beside a probability computed elsewhere put 613 of 3,797
    rows into open self-contradiction on 2026-09-08: match 14315 (Alverca v
    Estoril) rendered a red "NG" badge directly above a bar reading "GG 61%".
    557 rows carried an NG label at btts_prob >= 0.50 and 56 a GG label below it.

    routers/stats.py already refuses to trust that column for the same reason
    and says so. This pins the other half of the decision, so the two surfaces
    cannot drift apart again.
    """
    import ast
    from pathlib import Path

    router = Path(__file__).resolve().parents[1] / "app" / "routers" / "predictions.py"
    tree = ast.parse(router.read_text())

    # Find the keyword argument btts_prediction=... in the response construction.
    exprs = [kw.value for node in ast.walk(tree) if isinstance(node, ast.Call)
             for kw in node.keywords if kw.arg == "btts_prediction"]
    assert exprs, "the response no longer sets btts_prediction"

    # 2026-09-08: this loop was gated on `if "_get_btts_threshold" in src`, and
    # that string is present ONLY when the fix is. Revert the source to
    # `btts_prediction=pred.btts_prediction` and the body never runs, leaving
    # `assert exprs` as the only live assertion — which the reverted line
    # satisfies just as well. It verified "the fix is not half-applied" and said
    # nothing about whether the fix was applied at all. A guard written backwards
    # is the same defect as the "57%" literal that started this audit.
    dumped = [ast.dump(e) for e in exprs]
    derived = [d for d in dumped if "_get_btts_threshold" in d]
    assert derived, (
        "the served GG/NG call is no longer derived from the served probability "
        "at the current threshold — it is reading the stored, frozen-threshold "
        "column again, and will contradict the probability bar beneath it")
    for d in derived:
        assert "btts_prediction" not in d, (
            "the derived call still falls back to the stored column")


def test_both_surfaces_cut_gg_at_the_same_place():
    """The match card decided GG/NG twice: the badge at the swept threshold and
    the bar's bold weight at a hardcoded 0.5. Between the two, 56 upcoming
    fixtures sat in a band where the badge said GG and the bar bolded NG."""
    from pathlib import Path

    bar = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "components"
           / "PredictionBar.tsx").read_text(encoding="utf-8")
    btts_block = bar[bar.index("export function BttsProbabilityBar"):]
    # The old form of this assertion stripped the very literal it banned
    # (`.replace("bttsProb >= 0.5", "")`), so a revert to
    # `const ggCalled = bttsProb >= 0.5;` passed it. Assert the shape that must
    # be there instead: the call is taken from the prop, and 0.5 appears only as
    # the fallback for when there is none.
    body = btts_block[:btts_block.index("return")]
    assert "prediction ?" in body or "prediction ?" in btts_block, (
        "BttsProbabilityBar does not branch on the call the badge is making, so "
        "it is deciding GG/NG a second time")
    assert body.count("0.5") <= 1, (
        f"0.5 appears {body.count('0.5')} times before the render; it may only "
        f"remain as the fallback for a leg with no call")
    assert "prediction === \"GG\"" in body, (
        "the bar does not read the badge's own call")


def test_no_secret_is_compared_with_a_plain_equality():
    """`!=` on str short-circuits at the first differing byte, so the time a
    failure takes leaks how much of the secret the caller got right.

    internal_auth.py used hmac.compare_digest from the start; admin.py compared
    the retrain/cache-clear key with `!=` until 2026-09-09. Same codebase, same
    author, one place forgotten — which is exactly the kind of thing a test
    should hold rather than a habit.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    # Only bare IDENTIFIERS whose name says secret. A dict lookup like
    # `market["key"] == "h2h"` is a market key, not a credential, and matching on
    # the rendered text flagged six of those on the first attempt.
    secretish = ("KEY", "SECRET", "TOKEN", "PASSWORD")

    def is_secret_name(node) -> bool:
        """A module CONSTANT (_ADMIN_KEY) or a FastAPI header parameter
        (x_admin_key). `p.key` on a ticket profile is neither, and matching any
        attribute called "key" flagged it on the second attempt."""
        if isinstance(node, ast.Name):
            raw = node.id
        else:
            return False
        looks_constant = raw.lstrip("_").isupper()
        looks_header = raw.startswith("x_")
        if not (looks_constant or looks_header):
            return False
        return any(w in raw.upper() for w in secretish)

    offenders = []
    for py in sorted(root.rglob("*.py")):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if not any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
                continue
            if is_secret_name(node.left) or any(is_secret_name(c) for c in node.comparators):
                offenders.append(
                    f"{py.relative_to(root.parent)}:{node.lineno}  {ast.unparse(node)[:70]}")
    assert not offenders, (
        "a secret is compared with == or != instead of hmac.compare_digest:\n  "
        + "\n  ".join(offenders))


def test_the_rate_limiter_cannot_be_keyed_on_a_header_the_client_writes():
    """Cloudflare APPENDS to any X-Forwarded-For the caller sends, so its first
    entry is whatever the caller typed.

    Verified against the live site on 2026-09-09 with a single request carrying
    `X-Forwarded-For: 203.0.113.99`: the bucket landed in Redis as
    `rl:chat:203.0.113.99`. Every IP-keyed limit was bypassable by rotating that
    header — the public LLM endpoint, login, register, and the CSV export.

    CF-Connecting-IP is overwritten by Cloudflare and cannot be forged from
    outside. This asserts the limiter reads that and not the forwarded chain.
    """
    import inspect

    from backend.app.rate_limit import client_ip

    src = inspect.getsource(client_ip)
    assert "cf-connecting-ip" in src.lower(), (
        "client_ip no longer reads CF-Connecting-IP")

    code = src.split('"""')[-1]          # the body, past the docstring
    assert "x-forwarded-for" not in code.lower(), (
        "client_ip reads X-Forwarded-For again — its first entry is written by "
        "the caller, and counting hops from the right is a guess about topology")


def test_the_proxy_forwards_the_unforgeable_client_ip():
    """The backend can only key on CF-Connecting-IP if the proxy passes it on.
    The proxy builds a fresh header object, so anything not explicitly forwarded
    is dropped."""
    from pathlib import Path

    route = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "app"
             / "api" / "proxy" / "[...path]" / "route.ts").read_text(encoding="utf-8")
    assert '"CF-Connecting-IP"' in route, (
        "the proxy does not forward CF-Connecting-IP, so every request reaches "
        "the backend with no usable client address and shares one bucket")


def test_serving_never_fills_a_feature_that_training_left_missing():
    """A feature that is NaN in training and a constant at serve time means the
    branch the model learned is never taken in production.

    Found 2026-09-09: sixteen of them. train.py lists them in `optional_feats`,
    so dropna keeps the rows and _impute_optional does not fill them — the model
    is fitted with those columns genuinely missing. compute_predictions then
    filled them from DEFAULTS.

    Worse than a mismatched value: the constants arrived beside their still-NaN
    siblings, producing combinations that occur exactly zero times in training. A
    first-ever meeting was served h2h_draw_rate = 0.26 with the other five h2h
    stats NaN, when features.py sets all six NaN together. A fixture in a league
    with no table was told both teams were exactly mid-table and equally ranked
    while the five motivation features guarded by the same condition stayed NaN.
    On the 216 fixtures of the following week, that trio was NaN on 133 of them.
    """
    import json
    import re
    from pathlib import Path

    import backend.app.ml.train as T
    from backend.app.ml.features import FEATURE_COLS

    root = Path(__file__).resolve().parents[2]
    tr = (root / "backend" / "app" / "ml" / "train.py").read_text()
    cp = (root / "scripts" / "compute_predictions.py").read_text()

    block = tr[tr.index("optional_feats = ("):tr.index("core_feats = [")]
    optional = set(re.findall(r'"([a-z0-9_]+)"', block))
    for name in ("SHOTS_COLS", "EUROPEAN_FEATURE_COLS", "MARKET_COLS",
                 "XG_COLS", "REF_COLS", "POISSON_COLS"):
        optional |= set(getattr(T, name, []))

    imp = tr[tr.index("def _impute_optional"):]
    imp = imp[:imp.index("\ndef ")]
    imputed = set(re.findall(r'"([a-z0-9_]+)"', imp))
    for name in ("SHOTS_COLS", "EUROPEAN_FEATURE_COLS", "MARKET_COLS",
                 "XG_COLS", "POISSON_COLS"):
        if name in imp:
            imputed |= set(getattr(T, name, []))

    defaults_block = re.search(r"^DEFAULTS\s*=\s*\{(.*?)^\}", cp, re.S | re.M)
    assert defaults_block, "compute_predictions no longer defines DEFAULTS"
    defaults = set(re.findall(r'"([a-z0-9_]+)"\s*:', defaults_block.group(1)))

    medians_path = root / "backend" / "data" / "models" / "impute_medians.json"
    medians = set(json.loads(medians_path.read_text())) if medians_path.exists() else set()

    skew = sorted((optional & defaults & set(FEATURE_COLS)) - imputed - medians)
    assert not skew, (
        "these features are NaN in training but filled with a constant at serve "
        "time, so the model's missing-value branch is never taken:\n  "
        + "\n  ".join(skew)
        + "\n\nEither drop them from DEFAULTS in compute_predictions.py, or add "
          "them to _impute_optional in train.py so both sides use one value.")


def test_every_model_accepts_a_missing_optional_feature():
    """The reason the fix above is safe, asserted rather than assumed. If a
    future ensemble member cannot take NaN — sklearn's MLPClassifier cannot —
    dropping the defaults would start raising on the live card instead."""
    import numpy as np
    import pandas as pd

    from backend.app.ml.features import FEATURE_COLS, RESULT_FEATURE_COLS
    from backend.app.ml.predict import _get_models

    result_model, goals_model = _get_models()
    row = {c: 0.5 for c in FEATURE_COLS}
    for c in ("h2h_draw_rate", "h_league_pos_norm", "a_league_pos_norm",
              "league_pos_diff", "h_ewma_form", "elo_closeness"):
        if c in row:
            row[c] = np.nan
    X = pd.DataFrame([row])

    probs = result_model.predict_proba(X[[c for c in RESULT_FEATURE_COLS if c in X]])[0]
    assert len(probs) == 3 and np.all(np.isfinite(probs))


def test_the_proxy_allowlist_is_exact_paths_not_prefixes():
    """A prefix allowlist was two separate holes.

    `{ method: "POST", prefix: "auth/" }` matched `auth/oauth`, which upserts a
    user BY EMAIL — so any browser could create accounts without a session or a
    rate limit and overwrite an existing account's name, image, provider and
    provider_id. Verified on 2026-09-10: one unauthenticated POST created user
    id 153. The router's require_internal_secret does not stop it, because the
    proxy attaches that secret to everything it forwards.

    The same prefix is what the path traversal rode in on: "auth/../admin/retrain"
    starts with "auth/", so the deny-by-default gate was skipped and the request
    reached the backend — POST /api/proxy/admin/retrain answered 401 while
    POST /api/proxy/auth/..%2fadmin%2fretrain answered 403, the backend's own
    admin-key check.

    Only `auth/register` is browser-facing; login and oauth are called
    server-side by NextAuth against INTERNAL_API.
    """
    from pathlib import Path

    route = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "app"
             / "api" / "proxy" / "[...path]" / "route.ts").read_text(encoding="utf-8")

    assert "PUBLIC_PATHS" in route and "PUBLIC_PREFIXES" not in route, (
        "the proxy allowlist is a prefix list again")
    assert "path === p.path" in route, (
        "isPublicPath no longer compares the whole path; a prefix match reopens "
        "both auth/oauth and the traversal")
    assert '"auth/oauth"' not in route, (
        "auth/oauth is on the browser-facing allowlist; it upserts by email and "
        "NextAuth calls it server-side, so it never needs to be")


def test_the_proxy_refuses_a_traversal_segment():
    """Next decodes %2f inside a catch-all segment, so `auth/..%2fadmin` arrives
    as ["auth", "../admin"] and joins back into a path that escapes. The check
    has to look at the SEGMENTS, which is the form the encoding hid in."""
    from pathlib import Path

    route = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "app"
             / "api" / "proxy" / "[...path]" / "route.ts").read_text(encoding="utf-8")
    guard = route[:route.index("const path      = params.path.join")]
    assert "for (const seg of params.path)" in guard, (
        "nothing validates the path segments before they are joined")
    assert '"' + ".." + '"' in guard, "the traversal guard no longer rejects '..'"


def test_oauth_upsert_is_rate_limited_like_its_siblings():
    """register and login both call _rate_limit; oauth never did, and it is the
    one that upserts by email."""
    import inspect

    from backend.app.routers import auth

    src = inspect.getsource(auth.oauth_upsert)
    assert "_rate_limit(" in src, "oauth_upsert is not rate limited"
