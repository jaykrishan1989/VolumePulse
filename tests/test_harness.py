"""Fills, costs, and the holdout lock. These tests do not read the market file."""

from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path

from backtest.costs import apply_slip, commission
from backtest.grid import SPECS
from backtest.periods import HOLDOUT_START
from backtest.simulate import simulate_long
from backtest.stats import apply_spec, rank_configs, selection_signals, summarize


def _bar(open_px: float, high: float, low: float, close: float, minute: int) -> dict:
    return {"open": open_px, "high": high, "low": low, "close": close, "minute": minute}


def _signal(day: date, *, score: float, up: bool, minute: int = 600) -> dict:
    if up:
        future = [(100.0, 110.0, 99.0, 108.0, minute + 5)]
    else:
        future = [(100.0, 101.0, 90.0, 96.0, minute + 5)]
    return {
        "symbol": "AAPL",
        "day": day,
        "t": 1_700_000_000 + minute,
        "minute": minute,
        "score": score,
        "rr": 2.0,
        "rvol": 1.2,
        "vwap": 100.0,
        "close": 100.0,
        "above_vwap": True,
        "reclaimed_vwap": True,
        "spy_above": True,
        "qqq_above": True,
        "prior5": 0.01,
        "stop": 98.0 if up else 98.0,
        "target": 105.0 if up else 110.0,
        "atr": 1.0,
        "future": future,
    }


class FillTests(unittest.TestCase):
    def test_stop_before_target_on_the_same_bar(self) -> None:
        trade = simulate_long([_bar(100, 110, 90, 100, 600)], stop=95, target=105)
        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertEqual(trade["reason"], "stop")
        self.assertAlmostEqual(trade["exit"], apply_slip(95, "sell", 2))

    def test_gap_through_stop_fills_at_the_open(self) -> None:
        trade = simulate_long([_bar(94, 96, 93, 95, 600)], stop=95, target=110)
        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertEqual(trade["reason"], "stop")
        self.assertAlmostEqual(trade["exit"], apply_slip(94, "sell", 2))

    def test_target_and_gap_through_target(self) -> None:
        trade = simulate_long([_bar(100, 106, 99, 105, 600)], stop=95, target=105)
        assert trade is not None
        self.assertEqual(trade["reason"], "target")
        self.assertAlmostEqual(trade["exit"], apply_slip(105, "sell", 2))
        gap = simulate_long([_bar(106, 108, 105, 107, 600)], stop=95, target=105)
        assert gap is not None
        self.assertAlmostEqual(gap["exit"], apply_slip(106, "sell", 2))

    def test_flat_by_1555_and_time_stop(self) -> None:
        flat = simulate_long([_bar(100, 101, 99, 100.5, 15 * 60 + 50)], stop=90, target=120)
        assert flat is not None
        self.assertEqual(flat["reason"], "eod")
        self.assertAlmostEqual(flat["exit"], apply_slip(100.5, "sell", 2))
        bars = [_bar(100, 101, 99, 100.2, 600 + i * 5) for i in range(6)]
        timed = simulate_long(bars, stop=90, target=120, mode="time", max_bars=6)
        assert timed is not None
        self.assertEqual(timed["reason"], "time")
        self.assertEqual(timed["bars"], 6)

    def test_trail_updates_after_the_bar(self) -> None:
        bars = [
            _bar(100, 102, 99, 101, 600),
            _bar(101, 102, 100, 101.5, 605),
        ]
        trade = simulate_long(bars, stop=95, target=200, mode="trail", atr=1.0, atr_mult=1.0, max_bars=4)
        assert trade is not None
        self.assertEqual(trade["reason"], "stop")
        self.assertAlmostEqual(trade["exit"], apply_slip(100, "sell", 2))
        self.assertGreater(trade["exit"], 95)

    def test_tiered_and_fixed_minimums(self) -> None:
        self.assertEqual(commission(1, 100, "buy", "tiered"), 0.35)
        self.assertEqual(commission(1, 100, "buy", "fixed"), 1.0)
        self.assertGreater(commission(1, 100, "sell", "tiered"), 0.35)
        self.assertGreater(apply_slip(100, "buy", 2), 100)
        self.assertLess(apply_slip(100, "sell", 2), 100)

    def test_regulatory_schedule_is_broker_commission_free(self) -> None:
        self.assertEqual(commission(10, 50, "buy", "regulatory"), 0.0)
        sell = commission(10, 50, "sell", "regulatory")
        sec = 500 * 27.80 / 1_000_000.0
        taf = min(8.30, 10 * 0.000166)
        self.assertAlmostEqual(sell, sec + taf)
        self.assertLess(sell, commission(10, 50, "sell", "tiered"))
        self.assertLess(commission(10, 50, "sell", "tiered"), commission(10, 50, "sell", "fixed"))

    def test_buy_slippage_is_in_the_entry(self) -> None:
        trade = simulate_long([_bar(100, 101, 99, 100.4, 15 * 60 + 50)], stop=90, target=120)
        assert trade is not None
        self.assertAlmostEqual(trade["entry"], apply_slip(100, "buy", 2))


class HoldoutTests(unittest.TestCase):
    def test_rank_refuses_holdout_dates(self) -> None:
        leaked = [_signal(HOLDOUT_START, score=90, up=True)]
        with self.assertRaises(RuntimeError):
            rank_configs(leaked, SPECS)

    def test_selection_ignores_a_holdout_that_would_flip_the_winner(self) -> None:
        val_day = date(2024, 8, 1)
        rows = []
        for offset in range(90):
            rows.append(_signal(val_day + timedelta(days=offset % 40), score=90, up=True, minute=600 + offset))
        for offset in range(80):
            rows.append(_signal(val_day + timedelta(days=offset % 40), score=70, up=False, minute=700 + offset))
        for offset in range(80):
            rows.append(_signal(HOLDOUT_START + timedelta(days=offset % 40), score=90, up=False, minute=600))
        for offset in range(80):
            rows.append(_signal(HOLDOUT_START + timedelta(days=offset % 40), score=70, up=True, minute=700))

        kept = selection_signals(rows)
        self.assertTrue(all(row["day"] < HOLDOUT_START for row in kept))
        ranked = rank_configs(kept, [item for item in SPECS if item["id"] in {"baseline", "score_80"}])
        self.assertEqual(ranked[0]["id"], "score_80")
        hold = [row for row in rows if row["day"] >= HOLDOUT_START]
        chosen = next(item for item in SPECS if item["id"] == "score_80")
        stats = summarize(apply_spec(hold, chosen))
        self.assertLess(stats["avgNetBps"], 0)
        self.assertGreaterEqual(ranked[0]["validation"]["trades"], 80)


class PublishedStatsTests(unittest.TestCase):
    def test_shipped_rule_is_a_loss(self) -> None:
        path = Path(__file__).resolve().parents[1] / "app" / "research_stats.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["rule"], "appear_disappear")
        self.assertEqual(payload["shippedRule"], "midmorning")
        self.assertFalse(payload["worthTrading"])
        self.assertLess(payload["holdout"]["net"], 0)
        self.assertLess(payload["holdout"]["avgNetBps"], 0)
        self.assertIn("Do not trade", payload["verdict"])
        self.assertGreaterEqual(payload["bootstrap"]["pValue"], 0.05)
        self.assertLess(payload["bracket"]["holdout"]["avgNetBps"], 0)


if __name__ == "__main__":
    unittest.main()
