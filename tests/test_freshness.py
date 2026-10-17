"""Delayed quotes and prices already through the stop stay off the buy list."""

from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.freshness import annotate_setup, bar_close_lag, classify_setup, delay_banner

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 28, 13, 16, tzinfo=NY)


def _row(**overrides):
    row = {
        "symbol": "AAPL",
        "last": 340.5,
        "entryStop": 340.21,
        "entryTarget": 342.90,
        "entryScore": 79,
    }
    row.update(overrides)
    return row


class FreshnessTests(unittest.TestCase):
    def test_forming_bar_is_fresh_and_a_closed_bar_is_not(self) -> None:
        # Bar opened at 13:10, so it closes at 13:15. At 13:16 the close is 60s behind.
        opened = datetime(2026, 9, 28, 13, 10, tzinfo=NY).timestamp()
        self.assertEqual(bar_close_lag(opened, datetime(2026, 9, 28, 13, 12, tzinfo=NY)), 0)
        self.assertGreater(bar_close_lag(opened, datetime(2026, 9, 28, 13, 16, 30, tzinfo=NY)), 60)

    def test_delayed_type_hides_a_setup_even_when_the_bar_just_opened(self) -> None:
        fresh_bar = datetime(2026, 9, 28, 13, 15, tzinfo=NY).timestamp()
        found = classify_setup(
            data_type=3,
            bar_epoch=fresh_bar,
            quote_epoch=fresh_bar,
            last=340.5,
            stop=340.21,
            target=342.90,
            now=NOW,
        )
        self.assertFalse(found["list"])
        self.assertIn("delayed", found["withhold"])
        self.assertTrue(found["delayed"])
        self.assertEqual(found["dataType"], 3)

    def test_stale_bar_and_stale_quote_are_hidden(self) -> None:
        old = datetime(2026, 9, 28, 13, 5, tzinfo=NY).timestamp()
        found = classify_setup(
            data_type=1,
            bar_epoch=old,
            quote_epoch=None,
            last=340.5,
            stop=340.21,
            target=342.90,
            now=NOW,
        )
        self.assertEqual(found["withhold"], "stale")
        quote = classify_setup(
            data_type=1,
            bar_epoch=None,
            quote_epoch=datetime(2026, 9, 28, 13, 0, tzinfo=NY).timestamp(),
            last=340.5,
            stop=340.21,
            target=342.90,
            now=NOW,
        )
        self.assertIn("stale", quote["withhold"])

    def test_price_through_stop_or_target_is_dropped(self) -> None:
        live_bar = datetime(2026, 9, 28, 13, 15, tzinfo=NY).timestamp()
        stopped = classify_setup(
            data_type=1,
            bar_epoch=live_bar,
            quote_epoch=NOW.timestamp(),
            last=340.00,
            stop=340.21,
            target=342.90,
            now=NOW,
        )
        self.assertEqual(stopped["withhold"], "through_stop")
        self.assertFalse(stopped["delayed"])
        targeted = classify_setup(
            data_type=1,
            bar_epoch=live_bar,
            quote_epoch=NOW.timestamp(),
            last=343.00,
            stop=340.21,
            target=342.90,
            now=NOW,
        )
        self.assertEqual(targeted["withhold"], "through_target")

    def test_live_in_range_setup_is_listed(self) -> None:
        live_bar = datetime(2026, 9, 28, 13, 15, tzinfo=NY).timestamp()
        found = classify_setup(
            data_type=1,
            bar_epoch=live_bar,
            quote_epoch=NOW.timestamp(),
            last=340.5,
            stop=340.21,
            target=342.90,
            now=NOW,
        )
        self.assertTrue(found["list"])
        self.assertIsNone(found["withhold"])

    def test_banner_names_delayed_data(self) -> None:
        row = annotate_setup(
            _row(),
            data_type=3,
            bar_epoch=datetime(2026, 9, 28, 13, 0, tzinfo=NY).timestamp(),
            quote_epoch=None,
            now=NOW,
        )
        self.assertEqual(row["entryDelayed"], 1)
        self.assertEqual(row["entryDataType"], 3)
        banner = delay_banner(3, [row])
        self.assertTrue(banner["active"])
        self.assertIn("DELAYED DATA", banner["message"])
        self.assertIn("will not list", banner["message"])
        self.assertFalse(delay_banner(1, [])["active"])


if __name__ == "__main__":
    unittest.main()
