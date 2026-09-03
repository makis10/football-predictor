"""
Accumulator ("ticket") builder — pure functions, no DB, no I/O.

Turns a set of upcoming fixtures + their predictions into a small ladder of
multi-leg tickets, the way a punter would fill in a betting slip.

Design rules, and why they are what they are:

  • **Legs are ranked by our model's probability, never by the odds.**
    Ranking inside a *price* band (best model probability among legs paying
    ≥ 2.00) is the same thing as ranking by model-vs-market disagreement, and
    this project already measured where that leads: EV-selected picks hit 32.1%
    against 52.6% for plain argmax over the same 470 settled fixtures. So the
    risk ladder is cut by MODEL PROBABILITY bands instead. Higher odds then
    follow naturally, because model and market broadly agree about which games
    are coin-flips — we just never *select* on the gap.

  • **One leg per match — and per TIE, not per row.** Two legs off the same
    fixture are correlated (Over 2.5 and GG move together), so multiplying them
    overstates the ticket's chance. Different fixtures are close enough to
    independent for the product rule to hold.

    Keying that rule on `match_id` alone was not enough. A fixture can be stored
    twice — two feeds disagreeing about the date, or a postponement that landed
    outside the reschedule window — and then one real match arrives here as two
    match_ids with two predictions. On 2026-08-17 the 'safe' slip listed
    "PAOK v Levadiakos" twice, once per row, and multiplied a 78% by itself as
    if the two were independent events. The fixture layer has since been fixed
    (scripts/fixture_upsert.py), but the builder no longer relies on that being
    true: legs are deduplicated by the TIE — league plus the two club names —
    so a duplicate row costs a leg, never correctness.

  • **Leg count adapts to reach a target total odds.** A slip of five 1.10
    favourites pays 1.6× and nobody wants it. Each profile names the payout it
    is aiming for and takes as many legs as that needs, up to MAX_LEGS.

  • **No EV, anywhere.** Tickets show probability, odds and return. They never
    claim "value" or "edge" — we have not measured that and saying it would be
    inventing a reason. Enforced by test_tickets.py.

Odds provenance matters: 1×2, Over 2.5, GG and NG carry real bookmaker prices.
Double chance is derived from the real 1×2 prices the way a book derives it.
The remaining goal lines have no market at all, so their price is our own fair
odds (1/p) and every such leg is flagged `estimated=True` — a ticket may not be
built mostly out of them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

# ── Markets ───────────────────────────────────────────────────────────────────
# Codes are stable identifiers stored in the DB and graded by settle_market().
# Renaming one silently invalidates every stored ticket, so they never change.
MARKET_1     = "1"
MARKET_X     = "X"
MARKET_2     = "2"
MARKET_1X    = "1X"
MARKET_X2    = "X2"
MARKET_12    = "12"
MARKET_O15   = "O1.5"
MARKET_U15   = "U1.5"
MARKET_O25   = "O2.5"
MARKET_U25   = "U2.5"
MARKET_O35   = "O3.5"
MARKET_U35   = "U3.5"
MARKET_GG    = "GG"
MARKET_NG    = "NG"

ALL_MARKETS = (
    MARKET_1, MARKET_X, MARKET_2,
    MARKET_1X, MARKET_X2, MARKET_12,
    MARKET_O15, MARKET_U15, MARKET_O25, MARKET_U25, MARKET_O35, MARKET_U35,
    MARKET_GG, MARKET_NG,
)

# Markets derived from the 1x2 probabilities. These are the ones that go wrong
# when the fixture carried no bookmaker line — see candidate_legs.
RESULT_MARKETS = frozenset({
    MARKET_1, MARKET_X, MARKET_2, MARKET_1X, MARKET_X2, MARKET_12,
})


def settle_market(market: str, home_goals: int, away_goals: int) -> bool:
    """Did `market` win, given the final score?

    Pure and total over ALL_MARKETS — an unknown code raises rather than
    silently grading as a loss, because a typo that quietly settles every
    ticket as lost is far worse than a crash in the nightly job.
    """
    total = home_goals + away_goals
    if market == MARKET_1:   return home_goals > away_goals
    if market == MARKET_X:   return home_goals == away_goals
    if market == MARKET_2:   return away_goals > home_goals
    if market == MARKET_1X:  return home_goals >= away_goals
    if market == MARKET_X2:  return away_goals >= home_goals
    if market == MARKET_12:  return home_goals != away_goals
    if market == MARKET_O15: return total >= 2
    if market == MARKET_U15: return total <= 1
    if market == MARKET_O25: return total >= 3
    if market == MARKET_U25: return total <= 2
    if market == MARKET_O35: return total >= 4
    if market == MARKET_U35: return total <= 3
    if market == MARKET_GG:  return home_goals >= 1 and away_goals >= 1
    if market == MARKET_NG:  return home_goals == 0 or away_goals == 0
    raise ValueError(f"settle_market: unknown market {market!r}")


# ── Leg ───────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Leg:
    match_id:   int
    market:     str
    prob:       float          # our model's probability, 0–1
    odds:       float          # decimal odds actually offered to the punter
    estimated:  bool           # True → `odds` is our fair price, not a market one
    league:     str = ""
    home_team:  str = ""
    away_team:  str = ""
    kickoff:    Optional[str] = None   # ISO string, display only
    confidence: str = ""


def _dc_odds(o_a: Optional[float], o_b: Optional[float]) -> Optional[float]:
    """Double-chance price from the two real 1×2 prices it covers.

    1/(1/o_a + 1/o_b) is how a book builds it: add the implied probabilities,
    invert. The bookmaker's margin rides along in o_a and o_b, so the result is
    a genuine market price, not a fair one — hence these legs are not flagged
    estimated.
    """
    if not o_a or not o_b:
        return None
    return round(1.0 / (1.0 / o_a + 1.0 / o_b), 3)


# Below this, a "price" is not a price. A 0.97 leg quoted at 1.03 adds nothing
# to a ticket except a chance to lose it, and books rarely list them at all.
MIN_LEG_ODDS = 1.02
# Two teams that never trade below this cannot carry a slip either way.
MIN_LEG_PROB = 0.35


def candidate_legs(
    *,
    match_id: int,
    league: str,
    home_team: str,
    away_team: str,
    kickoff: Optional[str],
    confidence: str,
    home_win_prob: float,
    draw_prob: float,
    away_win_prob: float,
    over_2_5_prob: float,
    btts_prob: Optional[float],
    poisson: Optional[dict],
    bm_home: Optional[float] = None,
    bm_draw: Optional[float] = None,
    bm_away: Optional[float] = None,
    bm_over: Optional[float] = None,
    bm_under: Optional[float] = None,
    bm_btts_yes: Optional[float] = None,
    bm_btts_no: Optional[float] = None,
) -> list[Leg]:
    """Every market this fixture could contribute, as priced Legs.

    `poisson` is the dict from compute_extended_poisson_stats() with λ FITTED
    to the served probabilities (fit_lambdas_to_probs) — not the feature-state
    λ stored on the prediction row, which are a global constant for upcoming
    fixtures and would make every goal line identical across the card.
    Pass None when the fit failed; the goal-line legs are then simply absent.
    """
    # A fixture with no 1x2 line was never market-anchored, so its home/draw/away
    # probabilities are the model's alone (predict.anchor_to_market). That is
    # fine on the leagues the model was fitted on — measured over the 4,443 such
    # rows in the 2025/26 test window, the pre-anchor 1X and X2 probabilities are
    # calibrated to within 0.3pp.
    #
    # It is not fine for a TICKET, because the ladder ranks by probability and
    # the unpriced fixtures are systematically the exotic ones: European
    # qualifiers, cold-start clubs, friendlies. On 532 settled legs (2026-09-03):
    #
    #     draw-carrying legs WITH a line     n= 63  stated 0.756  real 0.730  ROI  -0.0%
    #     draw-carrying legs WITHOUT a line  n=286  stated 0.784  real 0.661  ROI -12.8%
    #     non-draw legs WITHOUT a line       n=135  stated 0.731  real 0.704  ROI  -1.6%
    #
    # A 12.3-point gap, specific to the markets containing the draw: the outcome
    # the model is weakest at, in the fixtures where no market exists to correct
    # it. So the 1x2-derived markets need a real line. Goals and BTTS do not —
    # they are calibrated with or without one, and cutting them would starve the
    # ladder for nothing.
    _has_1x2_line = bm_home is not None and bm_draw is not None and bm_away is not None

    raw: list[tuple[str, Optional[float], Optional[float]]] = [
        (MARKET_1,  home_win_prob, bm_home),
        (MARKET_X,  draw_prob,     bm_draw),
        (MARKET_2,  away_win_prob, bm_away),
        (MARKET_1X, home_win_prob + draw_prob,     _dc_odds(bm_home, bm_draw)),
        (MARKET_X2, draw_prob + away_win_prob,     _dc_odds(bm_draw, bm_away)),
        (MARKET_12, home_win_prob + away_win_prob, _dc_odds(bm_home, bm_away)),
        (MARKET_O25, over_2_5_prob,     bm_over),
        (MARKET_U25, 1.0 - over_2_5_prob, bm_under),
    ]
    if btts_prob is not None:
        raw.append((MARKET_GG, btts_prob,       bm_btts_yes))
        raw.append((MARKET_NG, 1.0 - btts_prob, bm_btts_no))
    if poisson:
        raw += [
            (MARKET_O15, poisson.get("over_1_5"),  None),
            (MARKET_U15, poisson.get("under_1_5"), None),
            (MARKET_O35, poisson.get("over_3_5"),  None),
            (MARKET_U35, poisson.get("under_3_5"), None),
        ]

    legs: list[Leg] = []
    for market, prob, odds in raw:
        if prob is None or prob < MIN_LEG_PROB:
            continue
        if market in RESULT_MARKETS and not _has_1x2_line:
            continue
        estimated = odds is None
        price = odds if odds is not None else round(1.0 / prob, 2)
        if price < MIN_LEG_ODDS:
            continue
        legs.append(Leg(
            match_id=match_id, market=market, prob=round(float(prob), 4),
            odds=round(float(price), 2), estimated=estimated,
            league=league, home_team=home_team, away_team=away_team,
            kickoff=kickoff, confidence=confidence,
        ))
    return legs


# ── Ticket profiles ───────────────────────────────────────────────────────────

# Markets whose stated probability survives contact with reality, measured on
# every settled leg we have cut (2026-09-01, 469 legs):
#
#     market   n     model    actual     gap
#     1X     238     80.1%     70.2%    -9.9      draw inside
#     X2      83     72.1%     57.8%   -14.2      draw inside
#     U2.5    12     55.9%      8.3%   -47.6
#     U3.5    16     72.1%     62.5%    -9.6
#     NG       8     45.4%     37.5%    -7.9
#     ---------------------------------------
#     12      31     80.4%     87.1%    +6.7      draw EXCLUDED
#     O1.5    41     83.8%     85.4%    +1.5
#     GG      11     62.3%     63.6%    +1.4
#     O2.5    39     66.4%     66.7%    +0.2
#
# The split is not about long prices — it is the DRAW. Every market containing
# a draw is overstated, "12" which excludes one is understated, and the goals
# markets are near-perfect. That matches everything else this project has
# measured about draws: the club Draw market runs -11.6% ROI and the national
# one went 0 for 16.
#
# It also explains how the slips filled with the worst of them. Legs are ranked
# by model probability, and a double chance is two outcomes added together —
# arithmetically the biggest number on the card, every time. The ranking was not
# choosing 1X because it was good, but because it was large.
CALIBRATED_MARKETS = frozenset({MARKET_12, MARKET_O15, MARKET_O25, MARKET_GG})


@dataclass(frozen=True)
class Profile:
    key:           str
    min_legs:      int
    max_legs:      int
    odds_min:      float   # a leg must be priced in this range to be eligible …
    odds_max:      float   # … which is a READER PREFERENCE, not a signal (see below)
    min_leg_prob:  float   # … and we still have to think it more likely than this
    # Restrict the slip to these markets. None means "any". Used by `longshot`,
    # whose legs sit where a miscalibration hurts most.
    markets:       Optional[frozenset] = None


# The ladder is cut by LEG PRICE, because that is what decides whether a slip
# is worth filling in: five 1.10 favourites pay 1.6× and nobody wants that, so
# short prices only earn a place on a long slip. Banding by our own probability
# instead was tried first and collapsed — our model sits well below the market
# on favourites (it says 77% where the book says 89%), so a "4-fold" came out
# as seven legs paying 4.2× at a 15% chance.
#
# The price range is a filter on what the reader wants to bet, fixed in advance
# and identical for every fixture. Selection INSIDE it is by model probability
# alone. That distinction is the whole ballgame: ranking by model-vs-market gap
# is what produced 32.1% hit rate against 52.6% for plain argmax on the same
# 470 fixtures, and nothing here ranks on that gap.
#
# odds_max keeps a "treble" from quietly becoming three 6.00 shots.
PROFILES: tuple[Profile, ...] = (
    Profile("safe",     min_legs=7, max_legs=10, odds_min=1.02, odds_max=1.45, min_leg_prob=0.62),
    Profile("treble",   min_legs=3, max_legs=3,  odds_min=1.60, odds_max=3.50, min_leg_prob=0.40),
    Profile("fourfold", min_legs=4, max_legs=4,  odds_min=1.45, odds_max=3.00, min_leg_prob=0.42),
    Profile("fivefold", min_legs=5, max_legs=5,  odds_min=1.35, odds_max=2.60, min_leg_prob=0.45),
    # Rebuilt 2026-09-01 after going 0 for 13.
    #
    # The old shape was four legs at 2.20-6.00 with a 0.28 probability floor,
    # which selects precisely the region where the model is least reliable: its
    # legs were priced at a stated 53.7% and landed 25.8%. A slip cannot recover
    # from that, and the page was advertising a 6% chance that was really 1%.
    #
    # Length now comes from the NUMBER of legs rather than the length of each,
    # and every leg must be a market whose stated probability has held up
    # (CALIBRATED_MARKETS above - no double chance carrying a draw). Five legs
    # at 1.70-3.00 still reach 15-60x, which is what the profile is for; the
    # difference is that the probability printed beside it is now the truth.
    Profile("longshot", min_legs=5, max_legs=5, odds_min=1.70, odds_max=3.00,
            min_leg_prob=0.45, markets=CALIBRATED_MARKETS),
)

# A fixture may carry at most this many of the five tickets. Reusing the single
# best leg across all of them would mean one bad result loses the whole page.
MAX_TICKETS_PER_MATCH = 2


def tie_key(leg: Leg) -> tuple[str, frozenset]:
    """What makes two legs the same real match.

    The league plus the unordered pair of clubs, lightly normalised. Unordered
    because a fixture written before the venue was settled and again afterwards
    differs only in which side is listed at home — the same reason
    scripts/dedupe_fixtures.py keys on a frozenset.

    Falls back to the match id when the leg carries no team names (the pure-unit
    tests construct Legs that way), so two anonymous legs are never merged.
    """
    def norm(s: str) -> str:
        return "".join(ch for ch in (s or "").lower() if ch.isalnum())

    home, away = norm(leg.home_team), norm(leg.away_team)
    if not home and not away:
        return (leg.league, frozenset((f"#{leg.match_id}",)))
    return (leg.league, frozenset((home, away)))
# Estimated-price legs are allowed but must stay a minority: a slip whose
# headline payout is mostly our own arithmetic is not a slip anyone can place.
#
# Not absolute, though. When The Odds API ran out of credits on 2026-08-13
# nothing carried a bookmaker price for eighteen days, every leg was estimated,
# and this cap turned a thin page into an empty one — the site showed slips cut
# two days earlier and never said why. So a profile that cannot be filled under
# the cap is retried with it lifted rather than dropped.
#
# What that costs, stated plainly: a slip priced entirely at 1/p has total odds
# equal to 1/(its own probability), which is a restatement of the model rather
# than an offer, and no bookmaker pays it. Those legs are already flagged
# `estimated` and the page marks them; a slip that is mostly estimated says so
# at slip level too. The alternative — showing nothing — is not more honest,
# it just hides the same uncertainty behind an empty page.
MAX_ESTIMATED_FRACTION = 0.4


@dataclass
class Ticket:
    profile:      str
    legs:         list[Leg] = field(default_factory=list)

    @property
    def total_odds(self) -> float:
        t = 1.0
        for l in self.legs:
            t *= l.odds
        return round(t, 2)

    @property
    def combined_prob(self) -> float:
        """Product of leg probabilities — valid because legs come from
        different fixtures (enforced in build_tickets)."""
        p = 1.0
        for l in self.legs:
            p *= l.prob
        return round(p, 6)

    @property
    def estimated_legs(self) -> int:
        return sum(1 for l in self.legs if l.estimated)


def _best_leg_in_band(
    legs: Sequence[Leg],
    p: Profile,
    committed: Optional[str] = None,
) -> Optional[Leg]:
    """The market this fixture contributes to a ticket of this shape.

    Eligibility is by price (the profile's band) and by a floor on our own
    probability. Among what survives, we take the outcome WE think most likely
    — the market has no say in the ranking.

    `committed` pins the fixture to the selection an earlier ticket already
    took. Without it the ladder happily put "Wolves or draw" on the banker and
    "Blackburn or draw" on the long shot — both defensible on their own (they
    share the draw), but side by side on one page it reads as tipping both
    teams, and a reader is right to stop trusting the page at that point. If
    the committed market falls outside this profile's band, the fixture simply
    sits this ticket out.

    Ties within 2pp prefer a real market price over our own fair one: same
    expected outcome for the reader, but a number they can actually find.
    """
    pool = [l for l in legs if committed is None or l.market == committed]
    if p.markets is not None:
        pool = [l for l in pool if l.market in p.markets]
    in_band = [
        l for l in pool
        if p.odds_min <= l.odds <= p.odds_max and l.prob >= p.min_leg_prob
    ]
    if not in_band:
        return None
    best = max(in_band, key=lambda l: l.prob)
    real_close = [l for l in in_band if not l.estimated and best.prob - l.prob <= 0.02]
    if real_close:
        return max(real_close, key=lambda l: l.prob)
    return best


def _fill(pool: Sequence[Leg], p: Profile, est_cap: float) -> list[Leg]:
    """Take legs off `pool` until the profile is full, or the pool runs out."""
    chosen: list[Leg] = []
    on_slip: set[tuple] = set()
    for leg in pool:
        if len(chosen) >= p.max_legs:
            break
        tie = tie_key(leg)
        if tie in on_slip:
            # Same real match reaching us as a second fixture row. Taking both
            # would multiply one probability by itself.
            continue
        if leg.estimated and est_cap < 1.0:
            # Checked against the ticket we would END UP with, not the one we
            # hold, so a 3-leg slip can never come out 2/3 estimated.
            would_be = sum(1 for l in chosen if l.estimated) + 1
            if would_be > est_cap * max(len(chosen) + 1, p.min_legs):
                continue
        chosen.append(leg)
        on_slip.add(tie)
    return chosen


def build_tickets(
    legs_by_match: dict[int, list[Leg]],
    profiles: Iterable[Profile] = PROFILES,
) -> list[Ticket]:
    """Build the ladder. Returns only the tickets that could be built honestly.

    A profile the card cannot fill is skipped rather than padded out with legs
    it did not ask for — the page then shows three tickets and says why, which
    is the truth. Thin midweek cards genuinely do this.
    """
    # Keyed by TIE, not match_id: a match stored under two rows must still count
    # as one fixture, both within a slip and across the page.
    card_has_real_prices = any(
        not leg.estimated for legs in legs_by_match.values() for leg in legs)
    used_count: dict[tuple, int] = {}
    # tie → the market that fixture is already tipped at, page-wide.
    committed: dict[tuple, str] = {}
    tickets: list[Ticket] = []

    for p in profiles:
        pool: list[Leg] = []
        for mid, legs in legs_by_match.items():
            if not legs:
                continue
            tie = tie_key(legs[0])
            if used_count.get(tie, 0) >= MAX_TICKETS_PER_MATCH:
                continue
            best = _best_leg_in_band(legs, p, committed.get(tie))
            if best:
                pool.append(best)
        # Highest model probability first — the only ranking signal we trust.
        # match_id breaks ties so the same card always yields the same ticket.
        pool.sort(key=lambda l: (-l.prob, l.match_id))

        chosen = _fill(pool, p, MAX_ESTIMATED_FRACTION)
        if len(chosen) < p.min_legs and not card_has_real_prices:
            # Second pass with the estimated-price cap lifted. See
            # MAX_ESTIMATED_FRACTION for what this costs and why it is a
            # fallback and not the rule.
            #
            # Only when the WHOLE CARD is unpriced. The fallback exists for the
            # days no bookmaker price reaches us at all; a profile that cannot
            # fill for its own reasons — `longshot` restricts itself to four
            # markets — must be skipped instead, because printing a payout we
            # invented while real prices sit on the same card is not the same
            # trade-off at all.
            chosen = _fill(pool, p, 1.0)

        if len(chosen) < p.min_legs:
            continue   # not enough eligible fixtures — no ticket

        tickets.append(Ticket(profile=p.key, legs=chosen))
        for leg in chosen:
            tie = tie_key(leg)
            used_count[tie] = used_count.get(tie, 0) + 1
            committed.setdefault(tie, leg.market)

    return tickets
