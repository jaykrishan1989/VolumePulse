"""The session-edge rules are frozen, causal, and do not read the holdout."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from backtest.gate import ideas_tried
from backtest.periods import HOLDOUT_START
from backtest.session_edge import (
    ADOPTABLE,
    BAR_SHOCK,
    BETA_MIN,
    BOOK_NAMES,
    DAY_SHARE_MIN,
    DISASTER_STOP,
    RESIDUAL_HURDLE,
    SPY_IMPULSE,
    VWAP_GAP,
    clears_published_milestone,
    generate,
    screen_failures,
)


def _weekdays(start: date, count: int) -> list[date]:
    days = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _session(day: date, price: float, overrides: dict[int, tuple[float, float]] | None = None) -> list[dict]:
    """Regular bars at one price. overrides map a minute to (open, close)."""
    bars = []
    minute = 9 * 60 + 30
    while minute <= 15 * 60 + 50:
        opened, closed = price, price
        if overrides and minute in overrides:
            opened, closed = overrides[minute]
        low = min(opened, closed)
        high = max(opened, closed)
        bars.append(
            {
                "t": day.toordinal() * 1000 + minute,
                "minute": minute,
                "open": opened,
                "high": high,
                "low": low,
                "close": closed,
                "volume": 1000.0,
            }
        )
        minute += 5
    return bars


def _warm_book(signal_overrides: dict[str, dict[int, tuple[float, float]]]) -> dict:
    """Forty prior SPY returns, then one signal day. Stock closes match SPY, so beta is 1."""
    days = _weekdays(date(2023, 1, 3), BETA_MIN + 2)
    book: dict = {}
    price = 100.0
    for index, day in enumerate(days[:-1]):
        book[("SPY", day)] = _session(day, price)
        book[("AAPL", day)] = _session(day, price)
        book[("NVDA", day)] = _session(day, price)
        price *= 1.01 if index % 2 == 0 else 0.99
    signal = days[-1]
    book[("SPY", signal)] = _session(signal, 100.0, signal_overrides.get("SPY"))
    book[("AAPL", signal)] = _session(signal, 100.0, signal_overrides.get("AAPL"))
    book[("NVDA", signal)] = _session(signal, 100.0, signal_overrides.get("NVDA"))
    return book, signal


class SessionEdgeRulesTest(unittest.TestCase):
    def test_registry_and_hurdles_stay_frozen(self) -> None:
        self.assertEqual(ideas_tried(), 54)
        self.assertEqual(ADOPTABLE, frozenset({"m_primary"}))
        self.assertEqual(BOOK_NAMES, ("m_primary", "m_lag", "m_impact", "m_thrust", "m_vwap", "m_lasthour"))
        self.assertEqual(RESIDUAL_HURDLE, -0.0030)
        self.assertEqual(BAR_SHOCK, 0.0040)
        self.assertEqual(VWAP_GAP, 0.0030)
        self.assertEqual(SPY_IMPULSE, 0.0015)
        self.assertEqual(DISASTER_STOP, 0.0100)
        self.assertEqual(DAY_SHARE_MIN, 0.50)

    def test_screen_rejects_a_sparse_or_negative_book(self) -> None:
        clean = dict(
            validate_net=1.0,
            pooled_net=1.0,
            recent_net=1.0,
            validate_trades=80,
            positive_halves=4,
            ex_top5=1.0,
            avg_bps=1.0,
            day_share=0.50,
        )
        self.assertEqual(screen_failures(**clean), [])
        sparse = dict(clean)
        sparse["day_share"] = 0.20
        self.assertTrue(any("most sessions" in reason for reason in screen_failures(**sparse)))
        losing = dict(clean)
        losing["avg_bps"] = -0.1
        self.assertTrue(screen_failures(**losing))
        self.assertFalse(clears_published_milestone(1260.736236000008, 1.0, 80))
        self.assertTrue(clears_published_milestone(1260.736236000008 + 1.0, 1.0, 80))

    def test_holdout_day_is_refused(self) -> None:
        day = HOLDOUT_START
        book = {("SPY", day): _session(day, 100.0), ("AAPL", day): _session(day, 100.0)}
        with self.assertRaises(RuntimeError):
            generate(book)

    def test_thirty_basis_points_buys_the_laggard_and_twenty_does_not(self) -> None:
        book, signal = _warm_book(
            {
                "SPY": {},
                "AAPL": {10 * 60 + 25: (99.70, 99.70)},
                "NVDA": {},
            }
        )
        result = generate(book)
        primary = [spell for spell in result.spells["m_primary"] if spell["day"] == signal]
        self.assertEqual(len(primary), 1)
        self.assertEqual(primary[0]["symbol"], "AAPL")
        self.assertEqual(primary[0]["buy_minute"], 10 * 60 + 30)
        self.assertAlmostEqual(primary[0]["stop"], float(primary[0]["entry_bar"]["open"]) * (1.0 - DISASTER_STOP))
        self.assertEqual(primary[0]["invest_fraction"], 1.0)
        self.assertEqual(primary[0]["entry_bar"]["minute"], 10 * 60 + 30)

        shy, shy_day = _warm_book({"AAPL": {10 * 60 + 25: (99.80, 99.80)}})
        shy_spells = [spell for spell in generate(shy).spells["m_primary"] if spell["day"] == shy_day]
        self.assertEqual(shy_spells, [])

    def test_later_clock_is_used_only_when_the_first_does_not_qualify(self) -> None:
        book, signal = _warm_book({"AAPL": {11 * 60 + 25: (99.50, 99.50)}})
        spells = [spell for spell in generate(book).spells["m_primary"] if spell["day"] == signal]
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["buy_minute"], 11 * 60 + 30)

    def test_lag_requires_the_spy_impulse(self) -> None:
        book, signal = _warm_book(
            {
                "SPY": {10 * 60 + 25: (100.20, 100.20)},
                "AAPL": {10 * 60 + 25: (99.50, 99.50)},
            }
        )
        result = generate(book)
        self.assertTrue(any(spell["day"] == signal for spell in result.spells["m_primary"]))
        self.assertTrue(any(spell["day"] == signal for spell in result.spells["m_lag"]))

        quiet, quiet_day = _warm_book(
            {
                "SPY": {10 * 60 + 25: (100.10, 100.10)},
                "AAPL": {10 * 60 + 25: (99.50, 99.50)},
            }
        )
        quiet_result = generate(quiet)
        self.assertTrue(any(spell["day"] == quiet_day for spell in quiet_result.spells["m_primary"]))
        self.assertFalse(any(spell["day"] == quiet_day for spell in quiet_result.spells["m_lag"]))

    def test_bar_shock_is_the_next_open_and_the_small_bar_is_not_a_trade(self) -> None:
        day = date(2024, 7, 1)
        book = {
            ("SPY", day): _session(day, 100.0),
            ("AAPL", day): _session(day, 100.0, {10 * 60: (100.0, 99.50)}),
            ("NVDA", day): _session(day, 100.0, {10 * 60 + 10: (100.0, 100.50)}),
        }
        result = generate(book)
        self.assertEqual(result.spells["m_impact"][0]["symbol"], "AAPL")
        self.assertEqual(result.spells["m_impact"][0]["buy_minute"], 10 * 60 + 5)
        self.assertEqual(result.spells["m_thrust"][0]["symbol"], "NVDA")
        self.assertEqual(result.spells["m_thrust"][0]["buy_minute"], 10 * 60 + 15)
        small = {
            ("SPY", day): _session(day, 100.0),
            ("AAPL", day): _session(day, 100.0, {10 * 60: (100.0, 99.70)}),
        }
        self.assertEqual(generate(small).spells["m_impact"], [])

    def test_vwap_sits_out_when_price_is_not_far_enough_below(self) -> None:
        day = date(2024, 7, 2)
        far = {minute: (100.0, 100.0) for minute in range(9 * 60 + 30, 10 * 60 + 25, 5)}
        far[10 * 60 + 25] = (99.60, 99.60)
        near = {10 * 60 + 25: (99.90, 99.90)}
        book = {
            ("AAPL", day): _session(day, 100.0, far),
            ("NVDA", day): _session(day, 100.0, near),
        }
        spells = generate(book).spells["m_vwap"]
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["symbol"], "AAPL")
        self.assertEqual(spells[0]["buy_minute"], 10 * 60 + 30)
        above = {("AAPL", day): _session(day, 100.0), ("NVDA", day): _session(day, 100.0)}
        self.assertEqual(generate(above).spells["m_vwap"], [])

    def test_last_hour_buys_the_strongest_up_morning_only(self) -> None:
        first, second = date(2024, 7, 1), date(2024, 7, 2)
        book = {
            ("AAPL", first): _session(first, 100.0),
            ("NVDA", first): _session(first, 100.0),
            ("AAPL", second): _session(second, 100.0, {9 * 60 + 55: (101.0, 101.0)}),
            ("NVDA", second): _session(second, 100.0, {9 * 60 + 55: (102.0, 102.0)}),
        }
        spells = [spell for spell in generate(book).spells["m_lasthour"] if spell["day"] == second]
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["symbol"], "NVDA")
        self.assertEqual(spells[0]["buy_minute"], 15 * 60 + 30)
        self.assertEqual(spells[0]["exit_kind"], "flat")
        down = {
            ("AAPL", first): _session(first, 100.0),
            ("AAPL", second): _session(second, 100.0, {9 * 60 + 55: (99.0, 99.0)}),
        }
        self.assertEqual(generate(down).spells["m_lasthour"], [])

    def test_a_later_day_does_not_change_the_earlier_fill(self) -> None:
        book, signal = _warm_book({"AAPL": {10 * 60 + 25: (99.40, 99.40)}})
        before = generate(book).spells["m_primary"]
        extra = date(2023, 6, 1)
        book[("SPY", extra)] = _session(extra, 50.0)
        book[("AAPL", extra)] = _session(extra, 50.0)
        after = generate(book).spells["m_primary"]
        before_signal = [spell for spell in before if spell["day"] == signal]
        after_signal = [spell for spell in after if spell["day"] == signal]
        self.assertEqual(len(before_signal), 1)
        self.assertEqual(before_signal[0]["symbol"], after_signal[0]["symbol"])
        self.assertEqual(before_signal[0]["buy_minute"], after_signal[0]["buy_minute"])
        self.assertAlmostEqual(before_signal[0]["stop"], after_signal[0]["stop"])
        self.assertAlmostEqual(before_signal[0]["priority"], after_signal[0]["priority"])


if __name__ == "__main__":
    unittest.main()
