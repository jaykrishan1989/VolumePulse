"""Daily-frequency rules. These tests do not read the market file."""

from __future__ import annotations

import unittest
from datetime import date

from backtest.daily import (
    DAILY_REGISTRY,
    FREQUENCY_MIN,
    Session,
    choose_finalist,
    first_pullback,
    opening_range,
    relative_strength,
    vwap_reclaim,
    vwap_stretch,
)
from backtest.periods import HOLDOUT_START
from backtest.run_daily import refuse_holdout


DAY = date(2024, 8, 1)


def _session(symbol: str, patches: dict[int, tuple[float, float, float, float]], vwap: float = 100.0) -> Session:
    bars = []
    for index, minute in enumerate(range(9 * 60 + 30, 15 * 60 + 55, 5)):
        open_px, high, low, close = patches.get(minute, (100.0, 100.5, 99.5, 100.0))
        bars.append(
            {
                "minute": minute,
                "open": open_px,
                "high": high,
                "low": low,
                "close": close,
                "t": 1_700_000_000 + index * 300,
                "volume": 1_000.0,
            }
        )
    return Session(
        symbol,
        DAY,
        bars,
        {int(bar["minute"]): index for index, bar in enumerate(bars)},
        [1.0] * len(bars),
        [vwap] * len(bars),
    )


class DailyRuleTests(unittest.TestCase):
    def test_relative_strength_buys_the_leader_not_spy(self) -> None:
        sessions = {
            ("SPY", DAY): _session("SPY", {}),
            ("AAPL", DAY): _session("AAPL", {595: (100.0, 102.5, 99.5, 102.0)}),
            ("MSFT", DAY): _session("MSFT", {595: (100.0, 100.5, 99.5, 100.0)}),
        }
        spells = relative_strength(sessions, [DAY])
        self.assertEqual([spell["symbol"] for spell in spells], ["AAPL"])
        self.assertEqual(spells[0]["exit_kind"], "flat")
        self.assertLess(spells[0]["stop"], spells[0]["entry_bar"]["open"])

    def test_vwap_stretch_buys_the_name_furthest_under_vwap(self) -> None:
        sessions = {
            ("AAPL", DAY): _session("AAPL", {625: (98.0, 98.5, 97.5, 98.0)}),
            ("MSFT", DAY): _session("MSFT", {625: (99.0, 99.5, 98.5, 99.0)}),
        }
        spells = vwap_stretch(sessions, [DAY])
        self.assertEqual(spells[0]["symbol"], "AAPL")
        self.assertEqual(len(spells), 1)

    def test_opening_range_skips_a_day_with_no_break_and_takes_the_first_break(self) -> None:
        quiet = {
            ("AAPL", DAY): _session("AAPL", {570: (100, 101, 99, 100), 575: (100, 101, 99, 100), 580: (100, 101, 99, 100)}),
        }
        self.assertEqual(opening_range(quiet, [DAY]), [])
        breaking = {
            ("AAPL", DAY): _session(
                "AAPL",
                {
                    570: (100, 101, 99, 100),
                    575: (100, 101, 99, 100),
                    580: (100, 101, 99, 100),
                    590: (101, 102.5, 100.5, 102),
                },
            ),
            ("MSFT", DAY): _session(
                "MSFT",
                {570: (100, 101, 99, 100), 575: (100, 101, 99, 100), 580: (100, 101, 99, 100)},
            ),
        }
        spells = opening_range(breaking, [DAY])
        self.assertEqual([spell["symbol"] for spell in spells], ["AAPL"])
        self.assertEqual(spells[0]["entry_bar"]["minute"], 595)
        self.assertEqual(spells[0]["stop"], 99)

    def test_pullback_requires_a_drive_and_a_bounce(self) -> None:
        flat = {("AAPL", DAY): _session("AAPL", {})}
        self.assertEqual(first_pullback(flat, [DAY]), [])
        bounce = {
            ("AAPL", DAY): _session(
                "AAPL",
                {
                    575: (100, 105, 99.5, 104),
                    605: (104, 104.5, 103.5, 104),
                    610: (100, 105, 104.5, 105),
                    615: (105, 105.5, 104.6, 105.2),
                },
            )
        }
        spells = first_pullback(bounce, [DAY])
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["entry_bar"]["minute"], 615)
        self.assertAlmostEqual(spells[0]["stop"], 104.5)

    def test_reclaim_needs_a_dip_before_the_cross(self) -> None:
        self.assertEqual(vwap_reclaim({("AAPL", DAY): _session("AAPL", {})}, [DAY]), [])
        sessions = {
            ("AAPL", DAY): _session(
                "AAPL",
                {
                    600: (99, 99.5, 98.5, 99),
                    605: (99.2, 99.5, 98.8, 99.2),
                    610: (100, 101, 99.5, 100.5),
                },
            ),
        }
        spells = vwap_reclaim(sessions, [DAY])
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["entry_bar"]["minute"], 615)

    def test_finalist_is_the_covered_rule_with_the_best_validation_net(self) -> None:
        rows = [
            {"id": "rare_winner", "signal_day_frac": 0.40, "net": 500.0, "bps": 20.0},
            {"id": "daily_worse", "signal_day_frac": 0.99, "net": -20.0, "bps": -5.0},
            {"id": "daily_better", "signal_day_frac": FREQUENCY_MIN, "net": -10.0, "bps": -4.0},
        ]
        self.assertEqual(choose_finalist(rows), "daily_better")
        self.assertIsNone(choose_finalist([rows[0]]))

    def test_registry_is_five_frozen_ids(self) -> None:
        ids = [rule.id for rule in DAILY_REGISTRY]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            ids,
            ["d_rs_leader", "d_vwap_stretch", "d_orb", "d_pullback", "d_vwap_reclaim"],
        )

    def test_holdout_day_is_refused_before_selection(self) -> None:
        self.assertGreaterEqual(HOLDOUT_START, date(2026, 4, 1))
        with self.assertRaises(RuntimeError):
            refuse_holdout([{"day": HOLDOUT_START}], "spell")


if __name__ == "__main__":
    unittest.main()
