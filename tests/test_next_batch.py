"""The next batch is causal, and it does not invent a result when the bars are missing."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from backtest.gate import ideas_tried
from backtest.hypotheses import REGISTRY
from backtest.next_batch import (
    NEXT_REGISTRY,
    clock_continuation,
    is_milestone,
    opening_range_failure,
    prior_day_reversal,
    wap_pressure,
)
from backtest.periods import HOLDOUT_START
from backtest.run_next_batch import choose, data_ready, main


def _weekdays(start: date, count: int) -> list[date]:
    days = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _bars(day: date, price: float = 100.0) -> list[dict]:
    bars = []
    minute = 9 * 60 + 30
    while minute <= 15 * 60 + 50:
        bars.append(
            {
                "minute": minute,
                "open": price,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price,
                "volume": 1_000.0,
                "average": price,
                "t": day.toordinal() * 100_000 + minute,
            }
        )
        minute += 5
    return bars


def _at(bars: list[dict], minute: int) -> dict:
    return next(bar for bar in bars if bar["minute"] == minute)


class NextBatchTests(unittest.TestCase):
    def test_registry_is_not_a_new_gate_idea(self) -> None:
        self.assertEqual([idea.id for idea in NEXT_REGISTRY], ["n_clock", "n_orb_fail", "n_prior_reversal", "n_flow"])
        self.assertTrue(all(idea.id not in {item.id for item in REGISTRY} for idea in NEXT_REGISTRY))
        self.assertEqual(ideas_tried(), 54)

    def test_clock_uses_yesterday_not_today(self) -> None:
        days = _weekdays(date(2024, 1, 2), 2)
        book = {("AAPL", day): _bars(day) for day in days}
        _at(book[("AAPL", days[0])], 9 * 60 + 30)["open"] = 100.0
        _at(book[("AAPL", days[0])], 9 * 60 + 55)["close"] = 102.0
        spells = clock_continuation(book)
        self.assertEqual([spell["day"] for spell in spells], [days[1]])
        self.assertEqual(spells[0]["buy_minute"], 9 * 60 + 30)

        leaked = {key: [dict(bar) for bar in bars] for key, bars in book.items()}
        _at(leaked[("AAPL", days[1])], 15 * 60 + 30)["close"] = 50.0
        again = clock_continuation(leaked)
        self.assertEqual(again[0]["priority"], spells[0]["priority"])

        faded = {key: [dict(bar) for bar in bars] for key, bars in book.items()}
        _at(faded[("AAPL", days[0])], 9 * 60 + 55)["close"] = 99.0
        self.assertEqual(clock_continuation(faded), [])

    def test_orb_failure_buys_the_reclaim_not_a_later_break(self) -> None:
        day = _weekdays(date(2024, 1, 2), 1)[0]
        early = _bars(day)
        for minute in (9 * 60 + 30, 9 * 60 + 35, 9 * 60 + 40):
            bar = _at(early, minute)
            bar["low"] = 100.0
            bar["high"] = 101.0
            bar["close"] = 100.5
        _at(early, 9 * 60 + 45)["close"] = 99.0
        _at(early, 9 * 60 + 45)["low"] = 98.0
        _at(early, 9 * 60 + 50)["close"] = 100.4
        _at(early, 9 * 60 + 50)["low"] = 99.5
        _at(early, 9 * 60 + 50)["high"] = 100.6
        late = _bars(day, price=100.0)
        for minute in (9 * 60 + 30, 9 * 60 + 35, 9 * 60 + 40):
            bar = _at(late, minute)
            bar["low"] = 100.0
            bar["high"] = 101.0
            bar["close"] = 100.5
        _at(late, 11 * 60)["close"] = 90.0
        _at(late, 11 * 60)["low"] = 90.0
        _at(late, 11 * 60 + 5)["close"] = 100.4
        _at(late, 11 * 60 + 5)["low"] = 99.0
        _at(late, 11 * 60 + 5)["high"] = 100.6
        spells = opening_range_failure({("AAPL", day): early, ("MSFT", day): late})
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["symbol"], "AAPL")
        self.assertEqual(spells[0]["buy_minute"], 9 * 60 + 55)

        stuck = _bars(day)
        for minute in (9 * 60 + 30, 9 * 60 + 35, 9 * 60 + 40):
            _at(stuck, minute)["low"] = 100.0
            _at(stuck, minute)["high"] = 101.0
        for bar in stuck:
            if bar["minute"] >= 9 * 60 + 45:
                bar["close"] = 99.0
                bar["low"] = 98.5
        self.assertEqual(opening_range_failure({("AAPL", day): stuck}), [])

    def test_prior_reversal_uses_yesterday_close_to_close(self) -> None:
        days = _weekdays(date(2024, 1, 2), 3)
        book = {}
        for symbol in ("AAPL", "MSFT"):
            for day in days:
                book[(symbol, day)] = _bars(day, price=100.0)
        _at(book[("AAPL", days[1])], 15 * 60 + 50)["close"] = 95.0
        _at(book[("MSFT", days[1])], 15 * 60 + 50)["close"] = 80.0
        for bar in book[("MSFT", days[2])]:
            bar["open"] = 80.0
            bar["close"] = 80.0
        spells = prior_day_reversal(book)
        self.assertEqual([spell["day"] for spell in spells], [days[2]])
        self.assertEqual(spells[0]["symbol"], "MSFT")
        self.assertEqual(spells[0]["buy_minute"], 9 * 60 + 30)

    def test_flow_ignores_a_later_bar_and_a_missing_average(self) -> None:
        days = _weekdays(date(2024, 1, 2), 2)
        book = {}
        for day in days:
            book[("AAPL", day)] = _bars(day)
            book[("MSFT", day)] = _bars(day)
        for bar in book[("AAPL", days[1])]:
            if bar["minute"] <= 9 * 60 + 55:
                bar["average"] = bar["close"] - 1.0
        for bar in book[("MSFT", days[1])]:
            if bar["minute"] <= 9 * 60 + 55:
                bar["average"] = bar["close"] - 0.1
        spells = wap_pressure(book)
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["symbol"], "AAPL")
        self.assertEqual(spells[0]["buy_minute"], 10 * 60)
        priority = spells[0]["priority"]

        leaked = {key: [dict(bar) for bar in bars] for key, bars in book.items()}
        _at(leaked[("AAPL", days[1])], 11 * 60)["average"] = 0.0
        again = wap_pressure(leaked)
        self.assertEqual(again[0]["priority"], priority)

        missing = {key: [dict(bar) for bar in bars] for key, bars in book.items()}
        _at(missing[("AAPL", days[1])], 9 * 60 + 35)["average"] = None
        _at(missing[("MSFT", days[1])], 9 * 60 + 35)["average"] = None
        self.assertEqual(wap_pressure(missing), [])

    def test_holdout_day_is_refused(self) -> None:
        day = HOLDOUT_START
        while day.weekday() >= 5:
            day += timedelta(days=1)
        book = {("AAPL", day): _bars(day)}
        with self.assertRaises(RuntimeError):
            clock_continuation(book)

    def test_milestone_is_above_the_published_validation_net(self) -> None:
        self.assertFalse(is_milestone(500.0, 80))
        self.assertFalse(is_milestone(1260.736236000008, 85))
        self.assertTrue(is_milestone(1260.736236000008 + 1.0, 85))
        self.assertFalse(is_milestone(2000.0, 49))

    def test_choose_refuses_a_holdout_window(self) -> None:
        row = {
            "id": "n_clock",
            "validate_trades": 80,
            "validate_net": 10.0,
            "window_end": "2026-03-31",
        }
        self.assertEqual(choose([row])["id"], "n_clock")
        row["window_end"] = "2026-04-01"
        with self.assertRaises(RuntimeError):
            choose([row])

    def test_missing_bars_do_not_write_a_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(data_ready(root))
            code = main(["--root", str(root)])
        self.assertEqual(code, 2)
        self.assertFalse(Path("research/next_batch_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
