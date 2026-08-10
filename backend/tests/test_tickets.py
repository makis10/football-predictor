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


def test_double_chance_falls_back_to_our_price_and_says_so():
    """Half a market price is not a market price.

    With the draw quote missing, 1X can still be offered — but only at OUR fair
    odds, flagged. Quoting a derived-looking number as if a book stood behind it
    is the failure this guards. 12 keeps its real price: both its components
    are quoted.
    """
    legs = _legs(bm_home=2.00, bm_draw=None, bm_away=4.00)
    dc = next(l for l in legs if l.market == "1X")
    assert dc.estimated is True
    assert dc.odds == pytest.approx(1 / (0.55 + 0.25), abs=0.01)
    assert next(l for l in legs if l.market == "12").estimated is False


def test_markets_without_a_bookmaker_price_are_flagged_estimated():
    poisson = {"over_1_5": 0.80, "under_1_5": 0.20,
               "over_3_5": 0.40, "under_3_5": 0.60}
    legs = _legs(poisson=poisson)
    o15 = next(l for l in legs if l.market == "O1.5")
    assert o15.estimated is True
    assert o15.odds == pytest.approx(1 / 0.80, abs=0.01)


def test_real_bookmaker_prices_are_not_flagged_estimated():
    legs = _legs(bm_home=1.90, bm_over=1.75, bm_btts_yes=1.80)
    for market in ("1", "O2.5", "GG"):
        assert next(l for l in legs if l.market == market).estimated is False


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
