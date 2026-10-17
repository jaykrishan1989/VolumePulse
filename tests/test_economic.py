"""The FOMC-morning report is frozen, causal, and cannot open the holdout."""

from __future__ import annotations

import unittest
from datetime import date

from backtest.economic import (
    ADOPTABLE,
    BOOK_NAMES,
    DISASTER_STOP,
    FOMC_EXIT_MINUTE,
    OPEN_MINUTE,
    generate,
    may_open_holdout,
)
from backtest.gate import ideas_tried
from backtest.grid15 import CPI_DAYS, FOMC_STATEMENT_DAYS
from backtest.periods import HOLDOUT_START


def _session(day: date, *, drop: set[int] | None = None) -> list[dict]:
    bars = []
    minute = 9 * 60 + 30
    while minute <= 15 * 60 + 50:
        if drop and minute in drop:
            minute += 5
            continue
        bars.append(
            {
                "t": day.toordinal() * 1000 + minute,
                "minute": minute,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1000.0,
            }
        )
        minute += 5
    return bars


class EconomicRulesTest(unittest.TestCase):
    def test_nothing_is_adoptable(self) -> None:
        self.assertEqual(ideas_tried(), 54)
        self.assertEqual(ADOPTABLE, frozenset())
        self.assertEqual(BOOK_NAMES, ("e_fomc", "e_morning"))
        self.assertEqual(OPEN_MINUTE, 9 * 60 + 30)
        self.assertEqual(FOMC_EXIT_MINUTE, 13 * 60 + 55)
        self.assertEqual(DISASTER_STOP, 0.0100)
        self.assertIn(date(2024, 7, 31), FOMC_STATEMENT_DAYS)
        self.assertNotIn(date(2025, 8, 22), FOMC_STATEMENT_DAYS)
        self.assertIn(date(2024, 7, 11), CPI_DAYS)
        self.assertNotIn(date(2024, 7, 11), FOMC_STATEMENT_DAYS)

    def test_statement_day_is_the_report_and_the_other_morning_is_the_control(self) -> None:
        statement = date(2024, 7, 31)
        ordinary = date(2024, 7, 30)
        cpi = date(2024, 7, 11)
        book = {
            ("SPY", statement): _session(statement),
            ("SPY", ordinary): _session(ordinary),
            ("SPY", cpi): _session(cpi),
            ("AAPL", statement): _session(statement),
        }
        result = generate(book)
        fomc = result.spells["e_fomc"]
        morning = result.spells["e_morning"]
        self.assertEqual([spell["day"] for spell in fomc], [statement])
        self.assertEqual(sorted(spell["day"] for spell in morning), [cpi, ordinary])
        spell = fomc[0]
        self.assertEqual(spell["symbol"], "SPY")
        self.assertEqual(spell["buy_minute"], OPEN_MINUTE)
        self.assertEqual(spell["exit_bar"]["minute"], FOMC_EXIT_MINUTE)
        self.assertEqual(spell["exit_kind"], "sell")
        self.assertEqual(spell["invest_fraction"], 1.0)
        self.assertAlmostEqual(spell["stop"], 100.0 * (1.0 - DISASTER_STOP))
        self.assertLess(spell["exit_bar"]["minute"], 14 * 60)

    def test_a_missing_statement_bar_is_a_skip(self) -> None:
        day = date(2024, 12, 18)
        book = {("SPY", day): _session(day, drop={FOMC_EXIT_MINUTE})}
        self.assertEqual(generate(book).spells["e_fomc"], [])
        self.assertEqual(generate(book).spells["e_morning"], [])

    def test_a_later_price_does_not_change_the_earlier_fill(self) -> None:
        first = date(2024, 9, 18)
        later = date(2024, 11, 7)
        book = {("SPY", first): _session(first), ("SPY", later): _session(later)}
        before = generate(book).spells["e_fomc"][0]
        book[("SPY", later)][0]["open"] = 50.0
        book[("SPY", later)][0]["close"] = 80.0
        after = generate(book).spells["e_fomc"][0]
        self.assertEqual(before["day"], first)
        self.assertEqual(before["buy_minute"], after["buy_minute"])
        self.assertEqual(before["exit_bar"]["minute"], after["exit_bar"]["minute"])
        self.assertAlmostEqual(before["entry_bar"]["open"], after["entry_bar"]["open"])

    def test_holdout_day_is_refused(self) -> None:
        book = {("SPY", HOLDOUT_START): _session(HOLDOUT_START)}
        with self.assertRaises(RuntimeError):
            generate(book)

    def test_a_passing_control_still_cannot_open_the_holdout(self) -> None:
        self.assertFalse(
            may_open_holdout(
                [
                    {"id": "e_morning", "screenPass": True, "adoptable": False, "milestone": True},
                    {"id": "e_fomc", "screenPass": False, "adoptable": False, "milestone": False},
                ]
            )
        )
        self.assertFalse(
            may_open_holdout(
                [
                    {"id": "e_fomc", "screenPass": True, "adoptable": False, "milestone": True},
                ]
            )
        )


if __name__ == "__main__":
    unittest.main()
