"""The second batch is causal, trades winners or a short hold, and does not open the holdout."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from backtest.gate import ideas_tried
from backtest.hypotheses import REGISTRY
from backtest.next_batch import NEXT_REGISTRY
from backtest.next_batch2 import (
    NEXT2_REGISTRY,
    SLOTS,
    close_reversal,
    intraday_continuation,
    midday_reversal,
)
from backtest.periods import HOLDOUT_START
from backtest.run_next_batch2 import _reading, main


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


class NextBatch2Tests(unittest.TestCase):
    def test_registry_is_not_a_new_gate_idea(self) -> None:
        ids = [idea.id for idea in NEXT2_REGISTRY]
        self.assertEqual(ids, ["n_intraday_cont", "n_mid_reversal", "n_close_reversal"])
        taken = {item.id for item in REGISTRY} | {item.id for item in NEXT_REGISTRY}
        self.assertTrue(all(idea_id not in taken for idea_id in ids))
        self.assertEqual(ideas_tried(), 54)
        self.assertEqual(SLOTS, 2)

    def test_continuation_buys_yesterdays_winners_and_skips_a_loser(self) -> None:
        days = _weekdays(date(2024, 1, 2), 2)
        book = {}
        for symbol in ("AAPL", "AMD", "MSFT", "NVDA"):
            book[(symbol, days[0])] = _bars(days[0])
            book[(symbol, days[1])] = _bars(days[1])
        # Yesterday's open-to-close. NVDA fell and must not be bought today.
        _at(book[("AAPL", days[0])], 9 * 60 + 30)["open"] = 100.0
        _at(book[("AAPL", days[0])], 15 * 60 + 50)["close"] = 103.0
        _at(book[("AMD", days[0])], 9 * 60 + 30)["open"] = 100.0
        _at(book[("AMD", days[0])], 15 * 60 + 50)["close"] = 102.0
        _at(book[("MSFT", days[0])], 9 * 60 + 30)["open"] = 100.0
        _at(book[("MSFT", days[0])], 15 * 60 + 50)["close"] = 101.0
        _at(book[("NVDA", days[0])], 9 * 60 + 30)["open"] = 100.0
        _at(book[("NVDA", days[0])], 15 * 60 + 50)["close"] = 90.0

        spells = intraday_continuation(book)
        self.assertEqual([spell["day"] for spell in spells], [days[1], days[1]])
        self.assertEqual([spell["symbol"] for spell in spells], ["AAPL", "AMD"])
        self.assertTrue(all(spell["invest_fraction"] == 0.5 for spell in spells))
        self.assertTrue(all(spell["buy_minute"] == 9 * 60 + 30 for spell in spells))

        leaked = {key: [dict(bar) for bar in bars] for key, bars in book.items()}
        _at(leaked[("NVDA", days[1])], 15 * 60 + 50)["close"] = 200.0
        again = intraday_continuation(leaked)
        self.assertEqual([spell["symbol"] for spell in again], ["AAPL", "AMD"])
        self.assertEqual(again[0]["priority"], spells[0]["priority"])

    def test_one_winner_takes_the_whole_ticket(self) -> None:
        days = _weekdays(date(2024, 1, 2), 2)
        book = {("AAPL", day): _bars(day) for day in days}
        book[("MSFT", days[0])] = _bars(days[0])
        book[("MSFT", days[1])] = _bars(days[1])
        _at(book[("AAPL", days[0])], 9 * 60 + 30)["open"] = 100.0
        _at(book[("AAPL", days[0])], 15 * 60 + 50)["close"] = 101.0
        _at(book[("MSFT", days[0])], 9 * 60 + 30)["open"] = 100.0
        _at(book[("MSFT", days[0])], 15 * 60 + 50)["close"] = 99.0
        spells = intraday_continuation(book)
        self.assertEqual([spell["symbol"] for spell in spells], ["AAPL"])
        self.assertEqual(spells[0]["invest_fraction"], 1.0)

    def test_midday_reversal_uses_noon_and_exits_at_1400(self) -> None:
        day = _weekdays(date(2024, 1, 2), 1)[0]
        book = {("AAPL", day): _bars(day), ("MSFT", day): _bars(day)}
        _at(book[("AAPL", day)], 12 * 60)["open"] = 100.0
        _at(book[("AAPL", day)], 12 * 60 + 55)["close"] = 99.0
        _at(book[("MSFT", day)], 12 * 60)["open"] = 100.0
        _at(book[("MSFT", day)], 12 * 60 + 55)["close"] = 97.0
        spells = midday_reversal(book)
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["symbol"], "MSFT")
        self.assertEqual(spells[0]["buy_minute"], 13 * 60)
        self.assertEqual(spells[0]["exit_bar"]["minute"], 14 * 60)
        self.assertEqual(spells[0]["invest_fraction"], 1.0)

        leaked = {key: [dict(bar) for bar in bars] for key, bars in book.items()}
        _at(leaked[("MSFT", day)], 14 * 60 + 30)["close"] = 50.0
        again = midday_reversal(leaked)
        self.assertEqual(again[0]["priority"], spells[0]["priority"])

        quiet = {key: [dict(bar) for bar in bars] for key, bars in book.items()}
        _at(quiet[("AAPL", day)], 12 * 60 + 55)["close"] = 101.0
        _at(quiet[("MSFT", day)], 12 * 60 + 55)["close"] = 101.0
        self.assertEqual(midday_reversal(quiet), [])

    def test_close_reversal_uses_yesterdays_last_minutes(self) -> None:
        days = _weekdays(date(2024, 1, 2), 2)
        book = {}
        for symbol in ("AAPL", "MSFT"):
            book[(symbol, days[0])] = _bars(days[0])
            book[(symbol, days[1])] = _bars(days[1])
        _at(book[("AAPL", days[0])], 15 * 60 + 30)["open"] = 100.0
        _at(book[("AAPL", days[0])], 15 * 60 + 50)["close"] = 98.0
        _at(book[("MSFT", days[0])], 15 * 60 + 30)["open"] = 100.0
        _at(book[("MSFT", days[0])], 15 * 60 + 50)["close"] = 101.0
        spells = close_reversal(book)
        self.assertEqual([spell["symbol"] for spell in spells], ["AAPL"])
        self.assertEqual(spells[0]["day"], days[1])
        self.assertEqual(spells[0]["buy_minute"], 9 * 60 + 30)
        self.assertEqual(spells[0]["exit_bar"]["minute"], 10 * 60)

        leaked = {key: [dict(bar) for bar in bars] for key, bars in book.items()}
        _at(leaked[("AAPL", days[1])], 15 * 60 + 50)["close"] = 50.0
        again = close_reversal(leaked)
        self.assertEqual(again[0]["priority"], spells[0]["priority"])

    def test_a_loss_is_not_described_as_a_near_miss(self) -> None:
        row = {
            "id": "n_close_reversal",
            "validate_net": -154.0,
            "validate_trades": 386,
            "validate_signals": 386,
            "validate_rest_net": -400.0,
        }
        text = _reading([row])
        self.assertIn("The best net is a loss", text)
        self.assertIn("Look 8 stays closed", text)

    def test_holdout_day_is_refused(self) -> None:
        day = HOLDOUT_START
        while day.weekday() >= 5:
            day += timedelta(days=1)
        book = {("AAPL", day): _bars(day)}
        with self.assertRaises(RuntimeError):
            midday_reversal(book)

    def test_missing_bars_do_not_write_a_result(self) -> None:
        paths = (
            Path("research/next_batch_summary.json"),
            Path("research/next_batch2_summary.json"),
        )
        before = {path: path.read_bytes() if path.exists() else None for path in paths}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = main(["--root", str(root)])
        self.assertEqual(code, 2)
        after = {path: path.read_bytes() if path.exists() else None for path in paths}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
