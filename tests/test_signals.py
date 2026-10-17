"""List membership signals. Nothing here is allowed to place an order."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.alerts import notify_signals, reset_for_tests
from app.outcomes import OutcomeLog
from app.signals import SignalBook, row_passes

NY = ZoneInfo("America/New_York")


def _row() -> dict:
    return {
        "symbol": "AAPL",
        "entryScore": 80,
        "entryStop": 99.0,
        "entryTarget": 110.0,
        "entryReasons": ["Reclaimed VWAP"],
        "rvol": 1.2,
        "entryRR": 1.6,
    }


class BookTests(unittest.TestCase):
    def test_confirm_and_exit_lag(self) -> None:
        book = SignalBook({"confirm": 2, "exit_lag": 2, "use_stop": True})
        now = datetime(2026, 9, 28, 11, 0, tzinfo=NY)
        row = _row()
        self.assertEqual(book.update([row], {"AAPL": 100}, {"AAPL": 101}, now), [])
        self.assertEqual(book.update([row], {"AAPL": 100}, {"AAPL": 101}, now), [])
        bought = book.update([row], {"AAPL": 400}, {"AAPL": 102}, now)
        self.assertEqual(bought[0]["action"], "BUY")
        self.assertIn("Not an order", bought[0]["note"])
        self.assertIn("Confirm manually", bought[0]["note"])
        self.assertEqual(book.update([], {"AAPL": 700}, {"AAPL": 102}, now), [])
        self.assertIn("AAPL", book.active)
        sold = book.update([], {"AAPL": 1000}, {"AAPL": 103}, now)
        self.assertEqual(sold[0]["action"], "SELL")
        self.assertNotIn("AAPL", book.active)

    def test_stop_while_listed_and_flat_at_1555(self) -> None:
        book = SignalBook({"confirm": 1, "exit_lag": 1, "use_stop": True})
        now = datetime(2026, 9, 28, 11, 0, tzinfo=NY)
        row = _row()
        book.update([row], {"AAPL": 100}, {"AAPL": 101}, now)
        stopped = book.update([row], {"AAPL": 100}, {"AAPL": 98}, now)
        self.assertEqual(stopped[0]["action"], "STOP")
        self.assertNotIn("place_order", stopped[0]["note"])

        book.update([row], {"AAPL": 500}, {"AAPL": 101}, now)
        flat = book.update(
            [row],
            {"AAPL": 500},
            {"AAPL": 101},
            datetime(2026, 9, 28, 15, 55, tzinfo=NY),
        )
        self.assertEqual(flat[0]["action"], "FLAT")
        self.assertEqual(book.active, {})

    def test_minute_filter(self) -> None:
        rule = {"minute_from": 600, "minute_to": 720, "min_score": 80}
        self.assertTrue(row_passes(_row(), rule, 600))
        self.assertFalse(row_passes(_row(), rule, 720))
        self.assertFalse(row_passes(_row(), {**rule, "require_vwap_reclaim": True, "min_score": 90}, 630))


class SignalLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.log = OutcomeLog(Path(self._dir.name) / "outcomes.sqlite")
        self.now = datetime(2026, 9, 28, 11, 0, tzinfo=NY)

    def tearDown(self) -> None:
        self.log.close()
        self._dir.cleanup()

    def test_buy_then_sell_is_a_logged_round_trip(self) -> None:
        self.log.record_signals(
            [{"action": "BUY", "symbol": "AAPL", "price": 100.0, "stop": 99.0, "score": 80, "note": "Not an order."}],
            self.now,
        )
        self.assertEqual(self.log.signal_summary()["open"], 1)
        self.log.record_signals(
            [{"action": "SELL", "symbol": "AAPL", "price": 99.0, "stop": 99.0, "note": "Not an order."}],
            self.now,
        )
        summary = self.log.signal_summary()
        self.assertEqual(summary["closed"], 1)
        self.assertEqual(summary["open"], 0)
        self.assertLess(summary["avgNetDollars"], 0)
        self.assertIn("never places orders", summary["note"])
        recent = self.log.recent_signals(self.now.date().isoformat())
        self.assertEqual([row["action"] for row in recent], ["BUY", "SELL"])


class SignalAlertTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_for_tests()
        os.environ.pop("ALERT_WEBHOOK_URL", None)

    def test_signal_ping_says_it_is_not_an_order(self) -> None:
        with patch("app.alerts._post") as post:
            notify_signals([{"action": "BUY", "symbol": "NVDA", "price": 100, "stop": 90, "at": "t", "note": "Confirm manually. Not an order."}])
            post.assert_not_called()
            os.environ["ALERT_WEBHOOK_URL"] = "http://127.0.0.1:9/hook"
            notify_signals(
                [
                    {"action": "BUY", "symbol": "NVDA", "price": 100, "stop": 90, "at": "t", "note": "Confirm manually. Not an order."},
                    {"action": "SELL", "symbol": "NVDA", "price": 101, "stop": 90, "at": "t2", "note": "Confirm manually. Not an order."},
                ]
            )
            self.assertEqual(post.call_count, 2)
            body = post.call_args.args[1].decode("utf-8")
            self.assertIn("does not place orders", body)
            self.assertNotIn("place_order", body)


if __name__ == "__main__":
    unittest.main()
