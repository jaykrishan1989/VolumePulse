"""Leakage checks for the pre-registered intraday model.

These tests build a few synthetic sessions. They do not read the market file
and they do not score the holdout.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

import pandas as pd

from backtest.ml_panel import build_frame
from backtest.ml_registry import FEATURE_COLUMNS
from backtest.periods import HOLDOUT_START
from backtest.run_ml import _day_bootstrap, choose_threshold, train_cut, walk_forward


def _weekdays(start: date, count: int) -> list[date]:
    days = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _session(day: date, seed: float, volume_base: float) -> list[dict]:
    bars = []
    minute = 9 * 60 + 30
    while minute <= 15 * 60 + 50:
        px = seed + ((minute // 5) % 7) * 0.02
        bars.append(
            {
                "minute": minute,
                "open": px,
                "high": px + 0.25,
                "low": px - 0.25,
                "close": px + 0.04,
                "volume": volume_base + minute,
                "t": day.toordinal() * 10_000 + minute,
            }
        )
        minute += 5
    return bars


def _book(days: list[date]) -> dict:
    seeds = {"AAPL": 180.0, "MSFT": 370.0, "SPY": 470.0, "QQQ": 400.0}
    book = {}
    for day in days:
        for symbol, seed in seeds.items():
            book[(symbol, day)] = _session(day, seed, 1_000_000.0 if symbol != "AAPL" else 2_000_000.0)
    return book


def _row(frame: pd.DataFrame, day: date, symbol: str, minute: int) -> pd.Series:
    match = frame.loc[(frame["day"] == day) & (frame["symbol"] == symbol) & (frame["minute"] == minute)]
    if len(match) != 1:
        raise AssertionError(f"{symbol} {day} minute {minute} has {len(match)} rows")
    return match.iloc[0]


class LeakageTests(unittest.TestCase):
    def test_future_bar_does_not_change_earlier_features(self) -> None:
        days = _weekdays(date(2024, 1, 2), 8)
        signal_day = days[5]
        book = _book(days)
        before = build_frame(book)
        earlier = _row(before, signal_day, "AAPL", 14 * 60)
        features = earlier[list(FEATURE_COLUMNS)].to_dict()

        leaked = _book(days)
        future = next(bar for bar in leaked[("AAPL", signal_day)] if bar["minute"] == 15 * 60 + 5)
        future["open"] = 999.0
        future["close"] = 1000.0
        after = build_frame(leaked)
        same = _row(after, signal_day, "AAPL", 14 * 60)
        for name, value in features.items():
            self.assertAlmostEqual(float(same[name]), float(value), places=10, msg=name)
        self.assertNotAlmostEqual(float(same["fwd_ret"]), float(earlier["fwd_ret"]), places=6)

        shifted = _book(days)
        for bar in shifted[("AAPL", days[6])]:
            bar["close"] = 50.0
            bar["open"] = 50.0
        untouched = build_frame(shifted)
        later_day = _row(untouched, signal_day, "AAPL", 14 * 60)
        for name, value in features.items():
            self.assertAlmostEqual(float(later_day[name]), float(value), places=10, msg=name)
        self.assertAlmostEqual(float(later_day["fwd_ret"]), float(earlier["fwd_ret"]), places=10)

    def test_signal_close_changes_features_not_the_forward_label(self) -> None:
        days = _weekdays(date(2024, 1, 2), 8)
        signal_day = days[5]
        book = _book(days)
        before = _row(build_frame(book), signal_day, "AAPL", 14 * 60)
        bumped = _book(days)
        bar = next(item for item in bumped[("AAPL", signal_day)] if item["minute"] == 14 * 60)
        bar["close"] = bar["close"] + 5.0
        after = _row(build_frame(bumped), signal_day, "AAPL", 14 * 60)
        self.assertNotAlmostEqual(float(after["ret_1"]), float(before["ret_1"]), places=6)
        self.assertAlmostEqual(float(after["fwd_ret"]), float(before["fwd_ret"]), places=10)

    def test_missing_market_context_drops_the_frame(self) -> None:
        days = _weekdays(date(2024, 1, 2), 8)
        book = _book(days)
        for key in [key for key in book if key[0] == "QQQ"]:
            del book[key]
        self.assertTrue(build_frame(book).empty)

    def test_train_cut_drops_embargo_day_and_holdout(self) -> None:
        self.assertEqual(train_cut(date(2024, 7, 1)), date(2024, 6, 30))
        self.assertEqual(train_cut(HOLDOUT_START), date(2026, 3, 31))
        self.assertEqual(train_cut(date(2026, 7, 1)), date(2026, 3, 31))
        cut = train_cut(HOLDOUT_START)
        days = [date(2026, 3, 30), date(2026, 3, 31), HOLDOUT_START]
        trainable = [day for day in days if day < cut]
        self.assertEqual(trainable, [date(2026, 3, 30)])

    def test_day_bootstrap_resamples_whole_days(self) -> None:
        trades = [
            {"day": date(2026, 4, 1), "net": 10.0},
            {"day": date(2026, 4, 1), "net": -4.0},
            {"day": date(2026, 4, 2), "net": -3.0},
        ]
        out = _day_bootstrap(trades, draws=40, seed=1)
        self.assertEqual(out["days"], 2)
        self.assertEqual(out["draws"], 40)
        self.assertGreaterEqual(out["pValue"], 0.0)
        self.assertLessEqual(out["pValue"], 1.0)
        self.assertEqual(_day_bootstrap([], draws=10)["pValue"], None)

    def test_threshold_and_walk_forward_reject_holdout(self) -> None:
        frame = pd.DataFrame({"day": [HOLDOUT_START], "pred_ret": [0.01]})
        with self.assertRaises(RuntimeError):
            choose_threshold(frame, {})
        with self.assertRaises(RuntimeError):
            walk_forward(frame)
