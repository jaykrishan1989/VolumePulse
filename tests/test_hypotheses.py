"""Frozen hypothesis rules. These tests do not read the market file or the holdout."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from backtest.hypotheses import (
    REGISTRY,
    assert_preholdout,
    half_hour_momentum,
    opening_range_breakout,
    opening_reversal,
    overnight_gap_intraday,
)
from backtest.periods import HOLDOUT_START
from backtest.run_hypotheses import decide, milestone
from backtest.spells import ACCOUNT_USD, portfolio

NY = ZoneInfo("America/New_York")


def _bars(day: date, prices: dict[int, tuple[float, float, float, float]]) -> list[dict]:
    bars = []
    for minute in range(9 * 60 + 30, 15 * 60 + 55, 5):
        open_px, high, low, close = prices.get(minute, (100.0, 100.2, 99.8, 100.0))
        moment = datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=NY)
        bars.append(
            {
                "minute": minute,
                "open": open_px,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000.0,
                "t": int(moment.timestamp()),
            }
        )
    return bars


class HypothesisTests(unittest.TestCase):
    def test_registry_ids_are_unique_and_frozen(self) -> None:
        ids = [item.id for item in REGISTRY]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            ids,
            ["h1_spy", "h1_stocks", "h2_opening_reversal", "h3_vwap_shortfall", "h4_opening_range", "h5_gap_down"],
        )

    def test_holdout_day_is_refused(self) -> None:
        with self.assertRaises(RuntimeError):
            assert_preholdout(HOLDOUT_START)
        book = {("SPY", HOLDOUT_START): _bars(HOLDOUT_START, {})}
        with self.assertRaises(RuntimeError):
            half_hour_momentum(book, ["SPY"])

    def test_positive_first_half_hour_buys_the_last_half_hour(self) -> None:
        prior = date(2024, 8, 1)
        day = date(2024, 8, 2)
        book = {
            ("SPY", prior): _bars(prior, {}),
            ("SPY", day): _bars(day, {9 * 60 + 55: (101.0, 101.2, 100.8, 101.0)}),
        }
        spells = half_hour_momentum(book, ["SPY"])
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["entry_bar"]["minute"], 15 * 60 + 30)
        self.assertEqual(spells[0]["exit_kind"], "flat")
        self.assertEqual(spells[0]["exit_bar"]["minute"], 15 * 60 + 50)

    def test_down_morning_does_not_buy_the_close(self) -> None:
        prior = date(2024, 8, 1)
        day = date(2024, 8, 2)
        book = {
            ("SPY", prior): _bars(prior, {}),
            ("SPY", day): _bars(day, {9 * 60 + 55: (99.0, 99.2, 98.8, 99.0)}),
        }
        self.assertEqual(half_hour_momentum(book, ["SPY"]), [])

    def test_opening_drop_exits_an_hour_later(self) -> None:
        prior = date(2024, 8, 1)
        day = date(2024, 8, 2)
        prices = {
            9 * 60 + 30: (100.0, 100.2, 99.0, 99.4),
            9 * 60 + 55: (99.2, 99.3, 99.0, 99.2),
        }
        book = {
            ("AAPL", prior): _bars(prior, {}),
            ("AAPL", day): _bars(day, prices),
        }
        spells = opening_reversal(book)
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["entry_bar"]["minute"], 10 * 60)
        self.assertEqual(spells[0]["exit_bar"]["minute"], 11 * 60)
        self.assertEqual(spells[0]["exit_kind"], "sell")

    def test_gap_down_waits_until_0945_and_an_up_gap_is_skipped(self) -> None:
        prior = date(2024, 8, 1)
        down = date(2024, 8, 2)
        up = date(2024, 8, 5)
        book = {
            ("AAPL", prior): _bars(prior, {}),
            ("AAPL", down): _bars(down, {9 * 60 + 30: (99.0, 99.4, 98.8, 99.2)}),
            ("AAPL", up): _bars(up, {9 * 60 + 30: (101.0, 101.4, 100.6, 101.2)}),
        }
        spells = overnight_gap_intraday(book)
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["day"], down)
        self.assertEqual(spells[0]["entry_bar"]["minute"], 9 * 60 + 45)
        self.assertEqual(spells[0]["exit_kind"], "flat")

    def test_opening_range_buys_the_bar_after_the_break(self) -> None:
        day = date(2024, 8, 2)
        prices = {}
        for minute in (9 * 60 + 30, 9 * 60 + 35, 9 * 60 + 40):
            prices[minute] = (100.0, 100.5, 99.5, 100.2)
        prices[10 * 60] = (101.0, 102.0, 100.8, 101.6)
        book = {("AAPL", day): _bars(day, prices)}
        spells = opening_range_breakout(book)
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["entry_bar"]["minute"], 10 * 60 + 5)
        self.assertAlmostEqual(spells[0]["stop"], 99.5)
        self.assertEqual(spells[0]["exit_kind"], "flat")

    def test_walk_forward_gate_rejects_a_loss(self) -> None:
        pooled = {"trades": 100, "net": -10}
        recent = {"trades": 20, "net": -2}
        validate = {"trades": 40, "net": -5}
        folds = [{"fold": name, "trades": 10, "net": -1} for name in ("2023H1", "2023H2", "2024H1", "2024H2", "2025H1", "2025H2")]
        decision, reason = decide(pooled, recent, validate, folds)
        self.assertEqual(decision, "rejected")
        self.assertIn("pooled net", reason)

    def test_milestone_command_does_not_open_the_holdout(self) -> None:
        with self.assertRaises(RuntimeError):
            milestone("h1_spy")

    def test_higher_priority_is_funded_first(self) -> None:
        day = date(2024, 8, 1)
        entry_t = 1_700_000_000

        def spell(symbol: str, priority: float) -> dict:
            entry = {"minute": 600, "open": 2000.0, "high": 2001.0, "low": 1990.0, "close": 2000.0, "t": entry_t}
            exit_bar = {"minute": 610, "open": 2000.0, "high": 2001.0, "low": 1990.0, "close": 2000.0, "t": entry_t + 600}
            return {
                "symbol": symbol,
                "day": day,
                "entry_t": entry_t,
                "exit_t": entry_t + 600,
                "stop": 1900.0,
                "score": priority,
                "priority": priority,
                "entry_bar": entry,
                "exit_bar": exit_bar,
                "path": [entry],
                "exit_kind": "sell",
            }

        result = portfolio([spell("ZZZ", 5.0), spell("AAA", 1.0)], equity=ACCOUNT_USD, use_stop=False)
        self.assertEqual([trade["symbol"] for trade in result["trades"]], ["ZZZ"])


if __name__ == "__main__":
    unittest.main()
