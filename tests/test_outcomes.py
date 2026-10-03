"""Paper-trade log and the alert stub. Neither path can place an order."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.alerts import notify_setups, reset_for_tests
from app.outcomes import OutcomeLog

NY = ZoneInfo("America/New_York")


def _setup(**overrides):
    row = {
        "symbol": "AAPL",
        "entryScore": 79,
        "entryReasons": ["Reclaimed VWAP"],
        "entryLow": 100.0,
        "entryHigh": 100.2,
        "entryStop": 99.0,
        "entryTarget": 102.0,
        "entryRR": 1.8,
    }
    row.update(overrides)
    return row


class OutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.log = OutcomeLog(Path(self._dir.name) / "outcomes.sqlite")
        self.now = datetime(2026, 9, 28, 11, 0, tzinfo=NY)

    def tearDown(self) -> None:
        self.log.close()
        self._dir.cleanup()

    def test_records_once_and_marks_stop_target_and_time(self) -> None:
        self.log.observe([_setup()], {"AAPL": 100.1}, self.now)
        self.log.observe([_setup()], {"AAPL": 100.1}, self.now)
        self.assertEqual(self.log.summary()["open"], 1)

        self.log.observe([], {"AAPL": 98.5}, self.now)
        stopped = self.log.summary()
        self.assertEqual(stopped["byStatus"].get("stop"), 1)
        self.assertLess(stopped["avgNetDollars"], 0)

        fresh = OutcomeLog(Path(self._dir.name) / "other.sqlite")
        try:
            fresh.observe([_setup(symbol="MSFT", entryStop=99.0, entryTarget=102.0)], {"MSFT": 103.0}, self.now)
            self.assertEqual(fresh.summary()["byStatus"].get("target"), 1)
            self.assertGreater(fresh.summary()["avgNetDollars"], 0)
            fresh.observe(
                [_setup(symbol="NVDA", entryStop=90.0, entryTarget=120.0, entryHigh=100.0)],
                {"NVDA": 101.0},
                datetime(2026, 9, 28, 15, 56, tzinfo=NY),
            )
            self.assertEqual(fresh.summary()["byStatus"].get("time"), 1)
        finally:
            fresh.close()

    def test_records_delay_and_does_not_treat_it_as_an_open_trade(self) -> None:
        self.log.observe(
            [
                _setup(
                    entryDelayed=1,
                    entryDataType=3,
                    entryLagSec=900,
                    entryWithhold="delayed+through_stop",
                )
            ],
            {"AAPL": 98.0},
            self.now,
        )
        row = self.log._conn.execute(
            "SELECT status, delayed, data_type, lag_sec, withhold FROM setups"
        ).fetchone()
        self.assertEqual(row[0], "withheld")
        self.assertEqual(row[1], 1)
        self.assertEqual(row[2], 3)
        self.assertEqual(row[3], 900)
        self.assertEqual(row[4], "delayed+through_stop")
        summary = self.log.summary()
        self.assertEqual(summary["open"], 0)
        self.assertEqual(summary["closed"], 0)
        self.assertEqual(summary["byStatus"].get("withheld"), 1)


class AlertTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_for_tests()
        os.environ.pop("ALERT_WEBHOOK_URL", None)
        os.environ.pop("ALERT_NTFY_TOPIC", None)

    def test_noop_without_config_and_posts_once(self) -> None:
        with patch("app.alerts._post") as post:
            notify_setups([_setup()])
            post.assert_not_called()
            os.environ["ALERT_WEBHOOK_URL"] = "http://127.0.0.1:9/hook"
            notify_setups([_setup(), _setup()])
            self.assertEqual(post.call_count, 1)
            body = post.call_args.args[1].decode("utf-8")
            self.assertIn("does not place orders", body)
            self.assertNotIn("place_order", body)


if __name__ == "__main__":
    unittest.main()
