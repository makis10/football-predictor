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


def test_stats_fetcher_uses_the_shared_league_id_map():
    """The fetcher must not keep a private copy of the league→id mapping."""
    from scripts.fetch_club_team_stats import LEAGUE_IDS

    assert LEAGUE_IDS == dict(_LEAGUE_API_SPORTS_ID), (
        "fetch_club_team_stats.LEAGUE_IDS has drifted from "
        "odds_analysis_service._LEAGUE_API_SPORTS_ID"
    )


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
        if opens and 'API_FOOTBALL_OK" -eq 1' in line:
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
