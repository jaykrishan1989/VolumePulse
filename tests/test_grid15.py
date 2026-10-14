"""The 15-minute grid is causal, and the checklist is frozen before any fill."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta

from backtest.gate import ideas_tried
from backtest.grid15 import (
    BOOKS,
    CPI_DAYS,
    FOMC_STATEMENT_DAYS,
    MORNING_STARTS,
    PRIMARY,
    SLOT_STARTS,
    is_milestone,
    is_nfp,
    nfp_day,
    plan_exit,
    run_grid,
    third_friday,
    vote_premarket,
    vote_tape,
)
from backtest.periods import HOLDOUT_START
from backtest.run_grid15 import main
from backtest.spells import resolve_exit


def _weekdays(start: date, count: int) -> list[date]:
    days = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _bar(day: date, minute: int, open_: float, high: float, low: float, close: float, volume: float) -> dict:
    return {
        "t": day.toordinal() * 1000 + minute,
        "minute": minute,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _session(day: date, price: float, *, breakout: bool = False, late_break: bool = False) -> list[dict]:
    """Flat session, or a 9:55 break, or a break that waits until 11:10."""
    bars = []
    minute = 9 * 60 + 30
    while minute <= 15 * 60 + 50:
        if breakout and not late_break and minute <= 9 * 60 + 40:
            bars.append(_bar(day, minute, price, price + 0.20, price, price + 0.10, 4000.0))
        elif breakout and not late_break and minute == 9 * 60 + 45:
            bars.append(_bar(day, minute, price + 0.22, price + 0.30, price + 0.15, price + 0.28, 2000.0))
        elif breakout and not late_break and minute == 9 * 60 + 50:
            bars.append(_bar(day, minute, price + 0.28, price + 0.36, price + 0.20, price + 0.32, 2000.0))
        elif breakout and not late_break and minute == 9 * 60 + 55:
            bars.append(_bar(day, minute, price + 0.32, price + 0.40, price + 0.22, price + 0.35, 2000.0))
        elif breakout and not late_break:
            bars.append(_bar(day, minute, price + 0.35, price + 0.40, price + 0.20, price + 0.35, 1000.0))
        elif late_break and minute <= 9 * 60 + 40:
            bars.append(_bar(day, minute, price, price + 0.20, price, price + 0.10, 4000.0))
        elif late_break and minute < 11 * 60:
            bars.append(_bar(day, minute, price + 0.10, price + 0.20, price + 0.05, price + 0.10, 1000.0))
        elif late_break and minute <= 11 * 60 + 10:
            bars.append(_bar(day, minute, price + 0.22, price + 0.40, price + 0.15, price + 0.35, 2000.0))
        elif late_break:
            bars.append(_bar(day, minute, price + 0.35, price + 0.40, price + 0.20, price + 0.35, 1000.0))
        else:
            bars.append(_bar(day, minute, price, price, price, price, 1000.0))
        minute += 5
    return bars


def _book(break_day: date, *, late: bool = False) -> dict:
    history = _weekdays(date(2024, 6, 3), 21)
    history = [day for day in history if day < break_day]
    book = {}
    names = ["AAPL", "AMD", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA"]
    for index, day in enumerate(history):
        for symbol in names:
            book[(symbol, day)] = _session(day, 100.0 + index * 0.5)
        book[("SPY", day)] = _session(day, 100.0)
    price = 100.0 + (len(history) - 1) * 0.5
    for symbol in names:
        book[(symbol, break_day)] = _session(day=break_day, price=price, breakout=True, late_break=late)
    book[("SPY", break_day)] = _session(break_day, 100.0)
    return book


class GridTests(unittest.TestCase):
    def test_calendar_and_slot_count(self) -> None:
        self.assertEqual(len(SLOT_STARTS), 26)
        self.assertEqual(len(MORNING_STARTS), 5)
        self.assertIn(date(2024, 9, 18), FOMC_STATEMENT_DAYS)
        self.assertIn(date(2024, 7, 11), CPI_DAYS)
        self.assertNotIn(date(2025, 10, 1), CPI_DAYS)
        self.assertEqual(nfp_day(2025, 1), date(2025, 1, 10))
        self.assertTrue(is_nfp(date(2025, 1, 10)))
        self.assertEqual(third_friday(date(2024, 7, 1)), date(2024, 7, 19))
        self.assertEqual(sum(1 for spec in BOOKS if spec.adoptable), 1)
        self.assertEqual(PRIMARY, "pro_aplus")
        self.assertFalse(is_milestone(1260.736236000008, 1.0, 80))
        self.assertTrue(is_milestone(1260.736236000008 + 1.0, 1.0, 80))
        self.assertFalse(is_milestone(2000.0, -1.0, 80))

    def test_specialists_that_have_no_data_abstain(self) -> None:
        self.assertFalse(vote_premarket().veto)
        self.assertIn("premarket", vote_premarket().reason)
        self.assertFalse(vote_tape().veto)
        self.assertIn("abstain", vote_tape().reason)

    def test_registry_is_unchanged(self) -> None:
        self.assertEqual(ideas_tried(), 54)

    def test_break_fills_the_next_open_and_a_cpi_morning_sits_out(self) -> None:
        book = _book(date(2024, 7, 12))
        result = run_grid(book)
        spells = result.spells["pro_aplus"]
        self.assertTrue(spells)
        self.assertTrue(all(spell["buy_minute"] == 10 * 60 for spell in spells))
        self.assertTrue(all(int(spell["entry_bar"]["minute"]) == 10 * 60 for spell in spells))
        roles = {spell["role"] for spell in spells}
        self.assertEqual(roles, {"scale", "runner"})
        cpi = _book(date(2024, 7, 11))
        blocked = run_grid(cpi)
        self.assertEqual(blocked.spells["pro_aplus"], [])
        self.assertGreater(blocked.vetoes["pro_aplus"]["events"], 0)
        self.assertTrue(blocked.spells["bare_or"])

    def test_a_later_day_does_not_change_the_fill(self) -> None:
        book = _book(date(2024, 7, 12))
        before = len(run_grid(book).spells["pro_aplus"])
        book[("AAPL", date(2024, 7, 15))] = _session(date(2024, 7, 15), price=1.0)
        after = len(run_grid(book).spells["pro_aplus"])
        self.assertEqual(before, after)

    def test_lunch_break_is_a_sit_out(self) -> None:
        book = _book(date(2024, 7, 12), late=True)
        result = run_grid(book)
        self.assertEqual(result.spells["pro_aplus"], [])
        self.assertGreater(result.vetoes["pro_aplus"]["time_of_day"], 0)

    def test_holdout_day_is_refused(self) -> None:
        book = _book(date(2024, 7, 12))
        book[("AAPL", HOLDOUT_START)] = _session(HOLDOUT_START, 100.0)
        with self.assertRaises(RuntimeError):
            run_grid(book)

    def test_runner_stop_moves_to_the_entry_only_after_one_r(self) -> None:
        bars = [
            {"t": 1, "minute": 600, "open": 100.0, "high": 101.2, "low": 99.5, "close": 101.0, "volume": 1},
            {"t": 2, "minute": 605, "open": 100.4, "high": 100.5, "low": 100.0, "close": 100.2, "volume": 1},
            {"t": 3, "minute": 720, "open": 100.3, "high": 100.4, "low": 100.2, "close": 100.3, "volume": 1},
        ]
        planned = plan_exit(bars, 0, 2, 99.0, 102.0, "sell", breakeven_after=101.0)
        self.assertIsNotNone(planned)
        assert planned is not None
        self.assertEqual(planned["planned_reason"], "stop")
        self.assertAlmostEqual(planned["stop"], 100.0)
        resolved = resolve_exit(planned, slip_bps=0.0)
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved[1], "stop")
        self.assertAlmostEqual(resolved[0], 100.0)

    def test_same_bar_stop_beats_the_target(self) -> None:
        bars = [
            {"t": 1, "minute": 600, "open": 100.0, "high": 101.5, "low": 98.0, "close": 99.0, "volume": 1},
            {"t": 2, "minute": 720, "open": 99.0, "high": 99.2, "low": 98.5, "close": 99.0, "volume": 1},
        ]
        planned = plan_exit(bars, 0, 1, 99.0, 101.0, "sell", breakeven_after=None)
        self.assertIsNotNone(planned)
        assert planned is not None
        self.assertEqual(planned["planned_reason"], "stop")

    def test_missing_bars_do_not_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["--root", tmp]), 2)


if __name__ == "__main__":
    unittest.main()
