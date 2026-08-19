"""The second odds source: API-Football's /odds.

The Odds API plan runs out mid-month. When it did on 2026-08-13 every upcoming
fixture lost its bookmaker price, so every accumulator leg fell back to our own
fair odds, so the estimated-price cap could not be met and the ladder cut zero
tickets. API-Football is already paid for and carries the same three markets, so
it fills the gap — but only if it is parsed correctly, and the ways it can be
parsed wrongly are quiet ones.
"""
from __future__ import annotations

from scripts.fetch_odds_apifootball import BOOKMAKER_PREFERENCE, parse_fixture_odds


def _entry(bookmakers):
    return {"fixture": {"id": 1}, "bookmakers": bookmakers}


def _book(name, bets):
    return {"name": name, "bets": bets}


def _bet(bid, name, values):
    return {"id": bid, "name": name,
            "values": [{"value": v, "odd": str(o)} for v, o in values]}


MATCH_WINNER = _bet(1, "Match Winner",
                    [("Home", 1.35), ("Draw", 5.28), ("Away", 9.75)])
BTTS = _bet(8, "Both Teams Score", [("Yes", 1.71), ("No", 2.02)])
OVER_UNDER = _bet(5, "Goals Over/Under", [
    ("Over 1.5", 1.29), ("Under 1.5", 3.76),
    ("Over 2.5", 1.53), ("Under 2.5", 2.53),
    ("Over 3.5", 2.40), ("Under 3.5", 1.55),
])


def test_the_three_markets_we_price_are_read():
    odds = parse_fixture_odds(_entry([_book("Pinnacle", [MATCH_WINNER, OVER_UNDER, BTTS])]))

    assert odds == {
        "bm_home_odds": 1.35, "bm_draw_odds": 5.28, "bm_away_odds": 9.75,
        "bm_over_odds": 1.53, "bm_under_odds": 2.53,
        "bm_btts_yes_odds": 1.71, "bm_btts_no_odds": 2.02,
    }


def test_only_the_2_5_goal_line_is_taken():
    """The endpoint returns every line from 0.5 upward in one list. Taking the
    first Over/Under would store the 1.5 price against a card that displays
    Over 2.5 — the same bet name against a different bet."""
    odds = parse_fixture_odds(_entry([_book("Pinnacle", [OVER_UNDER])]))

    assert odds["bm_over_odds"] == 1.53
    assert odds["bm_under_odds"] == 2.53


def test_the_sharpest_book_wins_not_the_longest_price():
    """Taking the maximum across books would overstate every payout the site
    quotes, against a price no single book offers on the whole slip. Preference
    order is by margin, and Pinnacle is first."""
    generous = _bet(1, "Match Winner", [("Home", 1.60), ("Draw", 6.00), ("Away", 12.0)])
    odds = parse_fixture_odds(_entry([
        _book("Bet365", [generous]),
        _book("Pinnacle", [MATCH_WINNER]),
    ]))

    assert odds["bm_home_odds"] == 1.35, "took the longest price instead of the sharpest"
    assert BOOKMAKER_PREFERENCE[0] == "Pinnacle"


def test_markets_are_filled_from_whichever_book_posts_them():
    """A fixture Pinnacle prices 1x2 for but not BTTS must still get both."""
    odds = parse_fixture_odds(_entry([
        _book("Pinnacle", [MATCH_WINNER]),
        _book("Bet365", [BTTS]),
    ]))

    assert odds["bm_home_odds"] == 1.35
    assert odds["bm_btts_yes_odds"] == 1.71


def test_a_half_priced_market_is_dropped_rather_than_stored():
    """Storing home and away without the draw would leave the card showing a
    1x2 with a hole in it, and any de-vig computed from it would be wrong."""
    partial = _bet(1, "Match Winner", [("Home", 1.35), ("Away", 9.75)])

    assert parse_fixture_odds(_entry([_book("Pinnacle", [partial])])) == {}


def test_an_unknown_bookmaker_is_ignored_not_guessed_at():
    odds = parse_fixture_odds(_entry([_book("SomeLocalBook", [MATCH_WINNER])]))

    assert odds == {}


def test_a_fixture_with_no_bookmakers_returns_nothing():
    assert parse_fixture_odds(_entry([])) == {}
    assert parse_fixture_odds({"fixture": {"id": 1}}) == {}
