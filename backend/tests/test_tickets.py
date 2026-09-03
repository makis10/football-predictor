"""
Guards for the accumulator builder.

Each test here exists because removing the thing it checks produces a specific,
plausible-looking bug that a reader would never spot from the page:

  • two legs off one match  → the slip's advertised probability is simply wrong
  • a market graded wrong   → the whole track record is wrong, silently
  • estimated legs unbounded→ the payout is our own arithmetic, presented as a price
  • EV language creeping in → the project measured EV selection at 32.1% vs 52.6%
                              for argmax, and decided not to sell it
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.app.ml.tickets import (
    RESULT_MARKETS,
    ALL_MARKETS,
    MAX_ESTIMATED_FRACTION,
    MAX_TICKETS_PER_MATCH,
    MIN_LEG_ODDS,
    PROFILES,
    Leg,
    Profile,
    build_tickets,
    candidate_legs,
    settle_market,
    tie_key,
)

REPO = Path(__file__).resolve().parents[2]


# ── settle_market ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("market,hg,ag,expected", [
    ("1", 2, 1, True),   ("1", 1, 1, False), ("1", 0, 1, False),
    ("X", 1, 1, True),   ("X", 2, 1, False),
    ("2", 0, 1, True),   ("2", 1, 1, False),
    ("1X", 2, 1, True),  ("1X", 1, 1, True),  ("1X", 0, 1, False),
    ("X2", 0, 1, True),  ("X2", 1, 1, True),  ("X2", 2, 1, False),
    ("12", 2, 1, True),  ("12", 0, 1, True),  ("12", 1, 1, False),
    ("O1.5", 1, 1, True),  ("O1.5", 1, 0, False), ("O1.5", 0, 0, False),
    ("U1.5", 1, 0, True),  ("U1.5", 1, 1, False),
    ("O2.5", 2, 1, True),  ("O2.5", 1, 1, False),
    ("U2.5", 1, 1, True),  ("U2.5", 2, 1, False),
    ("O3.5", 2, 2, True),  ("O3.5", 2, 1, False),
    ("U3.5", 2, 1, True),  ("U3.5", 2, 2, False),
    ("GG", 1, 1, True),    ("GG", 3, 0, False),   ("GG", 0, 0, False),
    ("NG", 3, 0, True),    ("NG", 0, 0, True),    ("NG", 1, 1, False),
])
def test_settle_market_grades_every_line(market, hg, ag, expected):
    assert settle_market(market, hg, ag) is expected


def test_settle_market_covers_every_market_we_can_store():
    """Every code the builder can emit must be gradeable.

    A market that builds but cannot settle would leave its tickets open for
    ever — invisible on the page, and silently missing from the record.
    """
    for market in ALL_MARKETS:
        settle_market(market, 1, 1)   # must not raise


def test_settle_market_rejects_unknown_code():
    """A typo must crash the nightly job, not grade every ticket as lost."""
    with pytest.raises(ValueError):
        settle_market("OVER_2_5", 3, 0)


# ── candidate_legs ────────────────────────────────────────────────────────────

def _legs(**over):
    kwargs = dict(
        match_id=1, league="EPL", home_team="A", away_team="B",
        kickoff="2026-08-10", confidence="medium",
        home_win_prob=0.55, draw_prob=0.25, away_win_prob=0.20,
        over_2_5_prob=0.60, btts_prob=0.55, poisson=None,
    )
    kwargs.update(over)
    return candidate_legs(**kwargs)


def test_double_chance_price_comes_from_the_real_1x2_prices():
    """1X must be priced 1/(1/o1 + 1/oX) — the way a book builds it — and must
    NOT be flagged estimated, because the bookmaker's margin rides along."""
    legs = _legs(bm_home=2.00, bm_draw=3.50, bm_away=4.00)
    dc = next(l for l in legs if l.market == "1X")
    assert dc.odds == pytest.approx(1 / (1 / 2.00 + 1 / 3.50), abs=0.005)
    assert dc.estimated is False


def test_half_a_market_price_produces_no_result_leg_at_all():
    """Superseded 2026-09-03, and deliberately stricter than what it replaced.

    This used to assert that a 1X with the draw quote missing could still be
    offered at OUR fair price, flagged estimated. The settled record says that
    is not good enough: a fixture without a complete 1x2 line is never
    market-anchored (anchor_to_market requires all three), and across 286
    settled draw-carrying legs on unanchored fixtures the stated probability was
    0.784 against a realised 0.661 — a 12.3-point gap, ROI -12.8%, while the
    same legs on priced fixtures sat at zero.

    So a partial line now yields no 1x2-derived leg at all. Goals and BTTS are
    unaffected; they are calibrated with or without a market.
    """
    legs = _legs(bm_home=2.00, bm_draw=None, bm_away=4.00)
    result_legs = [l.market for l in legs if l.market in RESULT_MARKETS]
    assert not result_legs, (
        f"a fixture with no draw quote still offered {result_legs}")
    # …and the rest of the card is untouched.
    assert {l.market for l in legs} >= {"O2.5", "U2.5", "GG", "NG"}


def test_markets_without_a_bookmaker_price_are_flagged_estimated():
    poisson = {"over_1_5": 0.80, "under_1_5": 0.20,
               "over_3_5": 0.40, "under_3_5": 0.60}
    legs = _legs(poisson=poisson)
    o15 = next(l for l in legs if l.market == "O1.5")
    assert o15.estimated is True
    assert o15.odds == pytest.approx(1 / 0.80, abs=0.01)


def test_real_bookmaker_prices_are_not_flagged_estimated():
    # A complete 1x2 line, because the result markets now require one.
    legs = _legs(bm_home=1.90, bm_draw=3.50, bm_away=4.20,
                 bm_over=1.75, bm_btts_yes=1.80)
    for market in ("1", "O2.5", "GG"):
        assert next(l for l in legs if l.market == market).estimated is False


def test_a_complete_line_restores_every_result_market():
    """The gate must be about the line, not about the markets themselves."""
    legs = {l.market for l in _legs(bm_home=1.90, bm_draw=3.50, bm_away=4.20)}
    assert {"1", "1X", "12", "X2"} <= legs


def test_under_2_5_uses_the_stored_price_when_present():
    """bm_under_odds exists precisely so Under 2.5 stops being estimated —
    migration 0032. Without it the mid bands are almost all our own prices."""
    legs = _legs(bm_under=2.05)
    u = next(l for l in legs if l.market == "U2.5")
    assert u.odds == 2.05 and u.estimated is False


def test_unpriceable_short_legs_are_dropped():
    """A 1.01 leg adds no payout and one more way to lose."""
    legs = _legs(home_win_prob=0.995, draw_prob=0.003, away_win_prob=0.002)
    assert all(l.odds >= MIN_LEG_ODDS for l in legs)


# ── build_tickets ─────────────────────────────────────────────────────────────

def _leg(match_id, market="1", prob=0.60, odds=1.70, estimated=False):
    return Leg(match_id=match_id, market=market, prob=prob, odds=odds,
               estimated=estimated)


def _card(n, **kw):
    """n fixtures, each offering one leg."""
    return {i: [_leg(i, **kw)] for i in range(1, n + 1)}


def test_never_two_legs_from_the_same_match():
    """Correlated legs multiplied as if independent overstate the slip's chance.
    Over 2.5 and GG move together; a slip carrying both is lying about itself."""
    card = {
        1: [_leg(1, "O2.5", 0.62, 1.70), _leg(1, "GG", 0.60, 1.75),
            _leg(1, "1", 0.58, 1.80)],
        2: [_leg(2, "1", 0.61, 1.72)],
        3: [_leg(3, "X2", 0.59, 1.78)],
        4: [_leg(4, "1X", 0.57, 1.82)],
        5: [_leg(5, "GG", 0.56, 1.85)],
    }
    for ticket in build_tickets(card):
        ids = [l.match_id for l in ticket.legs]
        assert len(ids) == len(set(ids)), f"{ticket.profile} reuses a fixture"


def _named(match_id, home, away, league="GreekSL", market="1", prob=0.60, odds=1.70):
    return Leg(match_id=match_id, market=market, prob=prob, odds=odds,
               estimated=False, league=league, home_team=home, away_team=away)


def test_one_match_stored_under_two_rows_still_yields_one_leg():
    """2026-08-17: PAOK–Levadiakos was in the DB twice — The Odds API had it on
    the 22nd, API-Football on the 23rd — so the 'safe' slip listed it as two
    legs and multiplied 0.78 by itself. The fixture layer has been fixed, but a
    duplicate row must cost a leg, never correctness."""
    card = {
        1: [_named(1, "PAOK", "Levadeiakos", prob=0.78, odds=1.10)],
        2: [_named(2, "PAOK", "Levadeiakos", prob=0.78, odds=1.10)],   # same tie
        3: [_named(3, "Club Brugge", "Cercle Brugge", "Belgium", prob=0.77, odds=1.09)],
        4: [_named(4, "PSV Eindhoven", "Groningen", "Eredivisie", prob=0.76, odds=1.10)],
        5: [_named(5, "Hull", "Man United", "EPL", prob=0.75, odds=1.12)],
        6: [_named(6, "Lens", "Auxerre", "Ligue1", prob=0.74, odds=1.22)],
        7: [_named(7, "Atalanta", "Sassuolo", "SerieA", prob=0.73, odds=1.12)],
        8: [_named(8, "Man City", "Bournemouth", "EPL", prob=0.72, odds=1.17)],
        9: [_named(9, "Fenerbahce", "Lyon", "EL", prob=0.71, odds=1.28)],
        10: [_named(10, "Cambuur", "Feyenoord", "Eredivisie", prob=0.70, odds=1.28)],
        11: [_named(11, "Tirol", "Salzburg", "Austria", prob=0.69, odds=1.30)],
    }
    for ticket in build_tickets(card):
        ties = [tie_key(l) for l in ticket.legs]
        assert len(ties) == len(set(ties)), (
            f"{ticket.profile} carries the same match twice: "
            f"{[(l.home_team, l.away_team) for l in ticket.legs]}"
        )


def test_the_same_tie_is_one_fixture_however_it_is_written():
    """Venue undecided when the row was first written, settled afterwards — the
    same reason dedupe_fixtures.py keys on an unordered pair."""
    assert tie_key(_named(1, "PAOK", "Levadeiakos")) == \
           tie_key(_named(2, "Levadeiakos", "PAOK"))
    assert tie_key(_named(1, "PAOK", "Levadeiakos")) != \
           tie_key(_named(2, "PAOK", "Panathinaikos"))
    # Same clubs, different competition, is a different match.
    assert tie_key(_named(1, "PAOK", "Levadeiakos")) != \
           tie_key(_named(2, "PAOK", "Levadeiakos", league="GreekCup"))


def test_legs_without_team_names_are_never_merged():
    """The unit tests above build Legs with no clubs on them; falling back to
    the match id keeps them distinct instead of collapsing the whole card."""
    assert tie_key(_leg(1)) != tie_key(_leg(2))


def test_a_match_is_capped_across_tickets():
    """One result must not be able to kill every slip on the page.

    The card is deliberately SHORT (8 fixtures for ~12 leg slots) so the profiles
    genuinely compete for the same games — on a wide card they never overlap and
    the cap is never exercised. The bound is written out rather than read from
    MAX_TICKETS_PER_MATCH: a test that imports the number it is checking passes
    no matter what that number becomes.
    """
    tickets = build_tickets(_card(8))
    seen: dict[int, int] = {}
    for t in tickets:
        for l in t.legs:
            seen[l.match_id] = seen.get(l.match_id, 0) + 1
    assert len(tickets) >= 2, "need competing tickets for the cap to mean anything"
    assert max(seen.values()) <= 2, f"a fixture carries {max(seen.values())} slips"
    assert MAX_TICKETS_PER_MATCH <= 2   # the constant must not drift past the policy


def test_one_fixture_is_tipped_one_way_across_the_whole_page():
    """A fixture must carry the SAME selection on every slip it appears on.

    Real output before this rule: "Wolves or draw" on the banker and
    "Blackburn or draw" on the long shot. Both are defensible alone — they
    share the draw — but printed side by side they read as tipping both teams,
    and that is where a reader stops believing the page.
    """
    # Each fixture offers a short 1X and a long X2. The bands are arranged so
    # the cheap slips want 1X and the long shot wants X2 — i.e. the card
    # actively pulls towards tipping both sides, which is what makes this a
    # test rather than a formality.
    card = {
        i: [
            _leg(i, "1X", prob=0.62, odds=1.50),
            _leg(i, "X2", prob=0.50, odds=2.40),
        ]
        for i in range(1, 13)
    }
    picks: dict[int, set[str]] = {}
    tickets = build_tickets(card)
    assert len(tickets) >= 2, "need at least two slips to observe a contradiction"
    shared = [
        mid for mid in card
        if sum(1 for t in tickets for l in t.legs if l.match_id == mid) > 1
    ]
    assert shared, "no fixture appears on two slips — nothing to contradict"
    for t in tickets:
        for l in t.legs:
            picks.setdefault(l.match_id, set()).add(l.market)
    clashes = {mid: mk for mid, mk in picks.items() if len(mk) > 1}
    assert not clashes, f"same fixture tipped two ways: {clashes}"


def test_estimated_legs_stay_a_minority_of_every_slip():
    """A payout that is mostly our own arithmetic is not a payout.

    The card puts the estimated legs FIRST in selection order (higher model
    probability) so the cap has to actively reject them; with the two kinds
    interleaved a broken cap still produces innocent-looking slips. Bound is a
    literal for the same reason as above.
    """
    card = {i: [_leg(i, "O1.5", 0.65, 1.70, estimated=True)] for i in range(1, 16)}
    card.update({i: [_leg(i, "1", 0.60, 1.70)] for i in range(16, 26)})
    tickets = build_tickets(card)
    assert tickets, "no tickets built — the cap cannot be observed"
    for t in tickets:
        assert t.estimated_legs <= 0.5 * len(t.legs), (
            f"{t.profile}: {t.estimated_legs}/{len(t.legs)} legs priced by us")
    assert MAX_ESTIMATED_FRACTION <= 0.5


def test_profile_is_skipped_rather_than_built_short():
    """A thin card must produce fewer slips, not undersized ones. Padding a
    4-fold out of three legs while calling it a 4-fold is the failure mode."""
    tickets = build_tickets(_card(2))   # two fixtures — nothing needs < 3 legs
    assert tickets == []


def test_leg_counts_match_the_profile_that_asked_for_them():
    tickets = build_tickets(_card(40))
    by_key = {p.key: p for p in PROFILES}
    assert tickets, "no tickets built"
    for t in tickets:
        p = by_key[t.profile]
        assert p.min_legs <= len(t.legs) <= p.max_legs


def test_combined_probability_is_the_product_of_the_legs():
    """The headline chance must be arithmetic on the legs shown, not a
    separately-computed number that could drift away from them."""
    for t in build_tickets(_card(40)):
        expected = 1.0
        for l in t.legs:
            expected *= l.prob
        assert t.combined_prob == pytest.approx(expected, abs=1e-6)
        odds = 1.0
        for l in t.legs:
            odds *= l.odds
        assert t.total_odds == pytest.approx(odds, abs=0.01)


def test_selection_ranks_by_model_probability_not_by_price():
    """The one rule that keeps this out of the EV trap.

    Two legs at the same price, different model probabilities: the slip must
    take the one WE think more likely. If ranking ever flips to "best price",
    this fails — and the project has the measurement to say why that matters
    (EV-selected 32.1% vs argmax 52.6% over the same 470 fixtures).
    """
    card = {
        1: [_leg(1, "1", prob=0.50, odds=1.80)],
        2: [_leg(2, "1", prob=0.58, odds=1.80)],
        3: [_leg(3, "1", prob=0.56, odds=1.80)],
        4: [_leg(4, "1", prob=0.52, odds=1.80)],
    }
    treble = next(t for t in build_tickets(card, [
        Profile("treble", min_legs=3, max_legs=3,
                odds_min=1.60, odds_max=3.50, min_leg_prob=0.40)]))
    probs = [l.prob for l in treble.legs]
    assert probs == sorted(probs, reverse=True)
    assert 0.50 not in probs, "took the weakest leg despite an identical price"


def test_price_band_is_respected():
    """A 'treble' of three 6.00 shots is not what the reader asked for."""
    card = {i: [_leg(i, "1", prob=0.45, odds=6.00)] for i in range(1, 20)}
    for t in build_tickets(card):
        p = next(pr for pr in PROFILES if pr.key == t.profile)
        for l in t.legs:
            assert p.odds_min <= l.odds <= p.odds_max


def test_build_is_deterministic():
    """Same card in, same slips out — otherwise a re-run of the daily job would
    hand the reader different tickets for the same day."""
    card = _card(40)
    a = build_tickets(card)
    b = build_tickets(card)
    assert [(t.profile, [(l.match_id, l.market) for l in t.legs]) for t in a] == \
           [(t.profile, [(l.match_id, l.market) for l in t.legs]) for t in b]


# ── policy ────────────────────────────────────────────────────────────────────

_EV_FIGURE = re.compile(r"ev[\s:]*[+\-−]?\s*\d", re.IGNORECASE)


def test_ticket_code_quotes_no_ev_figure():
    """Tickets must never advertise an expected value.

    The project removed EV from the match narrative for a measured reason; a new
    page reintroducing it through the side door would undo that silently.
    Prose may DISCUSS why EV is absent — an EV *number* is what is banned.
    """
    for rel in ("backend/app/ml/tickets.py",
                "backend/app/routers/tickets.py",
                "backend/app/schemas/ticket.py",
                "frontend/src/components/TicketCard.tsx",
                "frontend/src/app/tickets/page.tsx"):
        text = (REPO / rel).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in text.splitlines()
            if not line.lstrip().startswith(("#", "*", "//", "/*"))
        )
        assert not _EV_FIGURE.search(code), f"{rel} quotes an EV figure"


def test_page_shows_probability_beside_every_payout():
    """A payout with no probability next to it is the single most misleading
    thing this page could do."""
    card = (REPO / "frontend/src/components/TicketCard.tsx").read_text(encoding="utf-8")
    assert "ticket.totalOdds" in card
    assert "ticket.winProb" in card
    assert card.index("ticket.totalOdds") < card.index("ticket.returns"), (
        "returns must not be rendered before the odds/probability block")


def test_honesty_note_renders_above_the_slips():
    """Below the fold it is decoration; above them it is a warning."""
    page = (REPO / "frontend/src/app/tickets/page.tsx").read_text(encoding="utf-8")
    assert "tickets.honesty.body" in page
    assert page.index("tickets.honesty.body") < page.index("TicketCard key=")


def test_daily_job_cuts_tickets():
    """Without this step the page freezes on whatever day it last ran."""
    sh = (REPO / "scripts/run_daily.sh").read_text(encoding="utf-8")
    assert "generate_tickets.py" in sh


def test_every_profile_has_both_translations():
    """A missing key renders the raw key ("tickets.profile.longshot") to the
    reader, in both languages, and nothing else complains."""
    i18n = (REPO / "frontend/src/lib/i18n.ts").read_text(encoding="utf-8")
    for p in PROFILES:
        for suffix in ("", ".desc"):
            key = f'"tickets.profile.{p.key}{suffix}":'
            assert i18n.count(key) == 2, f"{key} needs an EN and an EL entry"


def test_history_is_not_limited_to_settled_slips():
    """A slip runs for up to seven days, so a settled-only history is empty for
    most of a week — on 2026-08-12, with three days of slips on file, not one had
    finished. The page then reads "no history" when the truth is "still running",
    which is the opposite of the receipts it is meant to show."""
    src = (REPO / "backend/app/routers/tickets.py").read_text(encoding="utf-8")
    history = src[src.index("def settled_tickets("):]
    assert "Ticket.outcome.isnot(None)" not in history, (
        "history must include open slips, not just graded ones"
    )
    # Today's card is already the top of the page; history is what came before.
    # Asserted on BEHAVIOUR, not on the literal expression: the window gained an
    # offset for paging (`< until`, where until = today - offset_days), and a
    # string match on `< today` failed while the rule it protects was intact.
    assert "Ticket.generated_for <" in history, "history must exclude today's slips"
    assert "generated_for >=" in history, "history must be bounded at the far end too"

    # And the boundary itself, exercised rather than read: with no offset the
    # upper bound has to BE today.
    import re
    assert re.search(r"until\s*=\s*today\s*-\s*timedelta\(days=offset_days\)", history), (
        "the upper bound must collapse to today when offset_days is 0"
    )


def test_results_poll_grades_ticket_legs():
    """Settlement used to run only in the daily job, so a leg whose match had
    finished stayed ungraded for up to ~24h and the page showed stale progress
    (verified: seven such legs on 2026-08-12). The 2-hourly poll that writes the
    scores must grade them too."""
    sh = (REPO / "scripts/run_results_poll.sh").read_text(encoding="utf-8")
    assert "generate_tickets.py --settle-only" in sh
    # --settle-only must never cut a fresh card: the slips are frozen on purpose.
    assert "--replace" not in sh


def test_history_ui_has_both_translations():
    """A missing key renders the raw key to the reader in both languages."""
    i18n = (REPO / "frontend/src/lib/i18n.ts").read_text(encoding="utf-8")
    for key in ("title", "body", "count", "progress", "legend", "dead"):
        needle = f'"tickets.history.{key}":'
        assert i18n.count(needle) == 2, f"{needle} needs an EN and an EL entry"


def test_outcome_type_admits_void():
    """generate_tickets.py writes outcome="void" when a fixture on the slip was
    deleted, and the backend types it as a bare Optional[str], so it reaches the
    browser. While the TS union omitted it, `outcome === "void"` was a tsc error
    and an exhaustive switch silently dropped the case."""
    api = (REPO / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
    assert '"won" | "lost" | "void" | null' in api


# ── Estimated-price fallback ──────────────────────────────────────────────────
# The Odds API plan ran out on 2026-08-13 and for eighteen days nothing carried
# a bookmaker price. Every leg was estimated, the minority rule could never be
# satisfied, and the ladder built nothing — the page kept showing slips cut two
# days earlier without saying why. Showing nothing is not more honest than
# showing a flagged estimate; it hides the same uncertainty behind a blank page.

def _est_card(n):
    """n fixtures, every one priced by us rather than by a bookmaker."""
    return {i: [Leg(match_id=i, market="1X", prob=0.62, odds=1.35, estimated=True,
                    league="L", home_team=f"H{i}", away_team=f"A{i}")]
            for i in range(1, n + 1)}


def test_a_card_with_no_bookmaker_prices_still_produces_slips():
    tickets = build_tickets(_est_card(12))

    assert tickets, "every leg estimated produced an empty ladder"
    assert all(len(t.legs) >= 3 for t in tickets)


def test_the_minority_rule_still_holds_when_real_prices_exist():
    """The lift is a fallback, not the new rule: a card that CAN fill a slip
    under the cap must still do so."""
    card = _card(12)                      # all real prices
    card[13] = [_leg(13, "O1.5", 0.70, 1.40, estimated=True)]
    card[14] = [_leg(14, "O1.5", 0.69, 1.42, estimated=True)]
    card[15] = [_leg(15, "O1.5", 0.68, 1.44, estimated=True)]

    for ticket in build_tickets(card):
        est = sum(1 for l in ticket.legs if l.estimated)
        assert est <= MAX_ESTIMATED_FRACTION * len(ticket.legs) + 1, (
            f"{ticket.profile} took {est}/{len(ticket.legs)} estimated legs "
            f"while real ones were available")


def test_a_fallback_slip_is_identifiable_as_mostly_estimated():
    """The page has to be able to say so, so the flag must survive onto the
    legs rather than being smoothed away."""
    tickets = build_tickets(_est_card(12))

    assert tickets
    for t in tickets:
        assert t.estimated_legs == len(t.legs)


# ── The longshot rebuild ──────────────────────────────────────────────────────
# It went 0 for 13. Not bad luck: its legs were priced at a stated 53.7% and
# landed 25.8%, because the old shape (four legs, 2.20–6.00, prob floor 0.28)
# selected precisely the region where the model is least reliable. Measured over
# every settled leg, the miscalibration is not about long prices at all — it is
# the DRAW:
#
#     1X   -9.9pp    X2  -14.2pp    U2.5 -47.6pp      (draw or under inside)
#     12   +6.7pp    O1.5 +1.5pp    O2.5  +0.2pp   GG +1.4pp

def test_the_longshot_only_uses_markets_that_have_held_up():
    from backend.app.ml.tickets import CALIBRATED_MARKETS

    longshot = next(p for p in PROFILES if p.key == "longshot")

    assert longshot.markets == CALIBRATED_MARKETS
    for bad in ("1X", "X2", "U2.5", "NG"):
        assert bad not in longshot.markets, f"{bad} is overstated by the model"


def test_no_double_chance_carrying_a_draw_reaches_a_longshot():
    card = {i: [_leg(i, "1X", 0.80, 2.00), _leg(i, "O2.5", 0.55, 2.10)]
            for i in range(1, 12)}

    for t in build_tickets(card):
        if t.profile == "longshot":
            assert all(l.market != "1X" for l in t.legs)


def test_the_longshot_gets_its_length_from_leg_count_not_leg_odds():
    """Five fairly-priced legs, not four improbable ones. Same target payout,
    honest probability beside it."""
    longshot = next(p for p in PROFILES if p.key == "longshot")

    assert longshot.min_legs >= 5
    assert longshot.odds_max <= 3.0, "back in the miscalibrated tail"
    assert longshot.min_leg_prob >= 0.42


def test_the_estimated_fallback_only_fires_on_a_wholly_unpriced_card():
    """It exists for the days no bookmaker price reaches us at all. A profile
    that cannot fill for its OWN reasons must be skipped instead — inventing a
    payout while real prices sit on the same card is a different trade."""
    card = {i: [_leg(i, "O1.5", 0.65, 1.70, estimated=True)] for i in range(1, 16)}
    card.update({i: [_leg(i, "1", 0.60, 1.70)] for i in range(16, 26)})

    for t in build_tickets(card):
        assert t.estimated_legs <= 0.5 * len(t.legs), (
            f"{t.profile}: {t.estimated_legs}/{len(t.legs)} invented while real "
            f"prices were available")


# ── A leg postponed out of the slip's window ─────────────────────────────────
# Jagiellonia–Pogoń moved from 16 Aug to 16 DECEMBER. Its two slips sat "still
# running" on the page while every other slip from those days had been graded —
# a 15 August accumulator advertised as live in September, and it would have
# stayed there until Christmas. The old row predated the feed-id column, so
# neither the 14-day reschedule window nor the id match could see the move.

def test_a_slip_is_voided_when_a_leg_is_postponed_out_of_its_window():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "scripts" /
           "generate_tickets.py").read_text(encoding="utf-8")

    assert "STALE_LEG_GRACE_DAYS" in src
    assert "was postponed" in src, "a postponed leg no longer voids the slip"
    # Void, not lost: nothing about the slip was wrong, it simply cannot be
    # settled as offered, and grading it as a loss would be inventing a result.
    block = src[src.index("stale_leg is not None"):][:400]
    assert '"void"' in block


def test_the_grace_period_allows_ordinary_rescheduling():
    """A day or two of TV movement is normal and must not void anything; a
    month is a different fixture in every way that matters to the reader."""
    import importlib

    gt = importlib.import_module("scripts.generate_tickets")

    assert 3 <= gt.STALE_LEG_GRACE_DAYS <= 14
