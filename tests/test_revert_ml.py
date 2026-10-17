"""The trough model is causal, and a stop beats a target on the same bar."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

from backtest.gate import ideas_tried
from backtest.periods import HOLDOUT_START
from backtest.revert_ml import (
    FEATURE_COLUMNS,
    bounce_hit,
    build_frame,
    drop_top_days,
    is_milestone,
    make_spell,
    spells_for,
    trough_indices,
)
from backtest.spells import resolve_exit


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
                "high": price + 0.4,
                "low": price - 0.4,
                "close": price,
                "volume": 1_000.0,
                "t": day.toordinal() * 100_000 + minute,
            }
        )
        minute += 5
    return bars


def _at(bars: list[dict], minute: int) -> dict:
    return next(bar for bar in bars if bar["minute"] == minute)


def _book(days: list[date]) -> dict:
    book = {}
    for day in days:
        for symbol in ("AAPL", "SPY", "QQQ"):
            book[(symbol, day)] = _bars(day, 100.0 if symbol == "AAPL" else 400.0)
    return book


class RevertTests(unittest.TestCase):
    def test_registry_is_not_a_gate_idea(self) -> None:
        self.assertEqual(ideas_tried(), 54)
        self.assertIn("osc_rate", FEATURE_COLUMNS)
        self.assertNotIn("y_hit", FEATURE_COLUMNS)

    def test_trough_is_a_new_low_under_vwap(self) -> None:
        lows = np.full(20, 100.0)
        closes = np.full(20, 100.0)
        vwaps = np.full(20, 100.0)
        pos = np.full(20, 0.2)
        minutes = np.array([9 * 60 + 30 + 5 * i for i in range(20)])
        lows[14] = 99.0
        closes[14] = 99.2
        self.assertEqual(trough_indices(lows, closes, vwaps, pos, minutes), [14])
        lows[18] = 90.0
        closes[18] = 90.5
        self.assertEqual(trough_indices(lows, closes, vwaps, pos, minutes), [14, 18])

    def test_stop_wins_a_tie_and_a_later_bar_is_not_the_signal(self) -> None:
        bars = _bars(date(2024, 1, 2))
        flat = len(bars) - 1
        self.assertEqual(bounce_hit(bars, 15, flat, 0.5), 0)
        for bar in bars[15:]:
            bar["high"] = bar["open"] + 2.0
            bar["low"] = bar["open"]
        self.assertEqual(bounce_hit(bars, 15, flat, 0.5), 1)
        bars[15]["low"] = bars[15]["open"] - 1.0
        bars[15]["high"] = bars[15]["open"] + 2.0
        self.assertEqual(bounce_hit(bars, 15, flat, 0.5), 0)

    def test_features_ignore_a_later_bar(self) -> None:
        days = _weekdays(date(2024, 1, 2), 25)
        book = _book(days)
        signal = days[-1]
        trough = _at(book[("AAPL", signal)], 10 * 60 + 40)
        trough["low"] = 97.0
        trough["close"] = 97.5
        trough["open"] = 98.0
        frame = build_frame(book)
        row = frame[(frame["symbol"] == "AAPL") & (frame["day"] == signal) & (frame["minute"] == 10 * 60 + 40)]
        self.assertEqual(len(row), 1)
        leaked = {key: [dict(bar) for bar in bars] for key, bars in book.items()}
        later = _at(leaked[("AAPL", signal)], 14 * 60)
        later["close"] = 50.0
        later["low"] = 49.0
        again = build_frame(leaked)
        again_row = again[(again["symbol"] == "AAPL") & (again["day"] == signal) & (again["minute"] == 10 * 60 + 40)]
        for column in FEATURE_COLUMNS:
            self.assertAlmostEqual(float(row.iloc[0][column]), float(again_row.iloc[0][column]), places=8)

    def test_holdout_day_is_refused(self) -> None:
        day = HOLDOUT_START
        while day.weekday() >= 5:
            day += timedelta(days=1)
        with self.assertRaises(RuntimeError):
            build_frame(_book([day]))

    def test_one_position_per_symbol_until_the_exit(self) -> None:
        day = _weekdays(date(2024, 7, 1), 1)[0]
        bars = _bars(day)
        book = {("AAPL", day): bars}
        first = {
            "symbol": "AAPL",
            "day": day,
            "minute": 10 * 60 + 40,
            "atr": 0.5,
            "prob": 0.9,
        }
        second = dict(first)
        second["minute"] = 11 * 60
        second["prob"] = 0.95
        import pandas as pd

        spells = spells_for(pd.DataFrame([first, second]), book, 0.55)
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["invest_fraction"], 0.25)
        self.assertAlmostEqual(spells[0]["target"] - spells[0]["entry_bar"]["open"], 0.5)

    def test_target_fill_and_stop_priority(self) -> None:
        bar = {"minute": 600, "open": 100.0, "high": 102.0, "low": 99.5, "close": 101.0, "t": 1000}
        spell = {
            "stop": 99.0,
            "target": 101.5,
            "path": [],
            "exit_bar": bar,
            "exit_kind": "flat",
        }
        price, reason, _free = resolve_exit(spell, use_stop=True, slip_bps=0.0)
        self.assertEqual(reason, "target")
        self.assertAlmostEqual(price, 101.5)
        spell["stop"] = 99.6
        price, reason, _free = resolve_exit(spell, use_stop=True, slip_bps=0.0)
        self.assertEqual(reason, "stop")
        self.assertAlmostEqual(price, 99.6)

    def test_drop_top_days_and_the_milestone(self) -> None:
        trades = [{"day": date(2024, 7, index), "net": float(index)} for index in range(1, 8)]
        net, kept, dropped = drop_top_days(trades)
        self.assertEqual(len(dropped), 5)
        self.assertEqual(len(kept), 2)
        self.assertAlmostEqual(net, 1.0 + 2.0)
        self.assertFalse(is_milestone(1260.0, 10.0, 80))
        self.assertFalse(is_milestone(2000.0, -1.0, 80))
        self.assertTrue(is_milestone(1260.736236000008 + 1.0, 1.0, 80))
        self.assertFalse(is_milestone(2000.0, 1.0, 49))

    def test_make_spell_uses_the_next_open(self) -> None:
        day = date(2024, 7, 1)
        bars = _bars(day)
        spell = make_spell({("AAPL", day): bars}, type("Row", (), {"symbol": "AAPL", "day": day, "minute": 10 * 60 + 40, "atr": 1.0})(), 0.7)
        self.assertIsNotNone(spell)
        assert spell is not None
        self.assertEqual(spell["entry_bar"]["minute"], 10 * 60 + 45)
        self.assertEqual(spell["exit_bar"]["minute"], 15 * 60 + 50)


if __name__ == "__main__":
    unittest.main()
