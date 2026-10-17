"""The profit search must not see the holdout while it is choosing."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

import pandas as pd

from backtest.hypotheses import walk_symbol
from backtest.ml_panel import build_frame
from backtest.periods import HOLDOUT_START, VALIDATE_END
from backtest.profit_grid import (
    add_return_lags,
    choose_winner,
    gap_spells,
    ml_spells,
    stack_oos,
    take_spells,
)
from tests.test_ml import _book, _row, _weekdays


def _session_pair() -> dict:
    days = _weekdays(date(2024, 1, 2), 3)
    book = _book(days)
    # Day 2 opens 1.5% under day 1's last close.
    symbol = "AAPL"
    day1 = days[1]
    day2 = days[2]
    previous = book[(symbol, day1)][-1]["close"]
    opened = previous * 0.985
    for bar in book[(symbol, day2)]:
        bar["open"] = opened
        bar["high"] = opened + 0.2
        bar["low"] = opened - 0.2
        bar["close"] = opened + 0.05
        opened = bar["close"]
    return book


class ProfitSelectionTests(unittest.TestCase):
    def test_winner_is_validation_dollars_and_refuses_the_holdout(self) -> None:
        rows = [
            {"id": "small", "family": "ml", "trades": 80, "net": 10.0, "window_end": VALIDATE_END},
            {"id": "lucky", "family": "ml", "trades": 4, "net": 500.0, "window_end": VALIDATE_END},
            {"id": "rule", "family": "rule", "trades": 100, "net": 40.0, "window_end": VALIDATE_END},
        ]
        self.assertEqual(choose_winner(rows)["id"], "rule")
        rows[0]["window_end"] = HOLDOUT_START
        with self.assertRaises(RuntimeError):
            choose_winner(rows)

    def test_walk_symbol_rejects_holdout_unless_asked(self) -> None:
        book = {("AAPL", HOLDOUT_START): [{"minute": 600, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]}
        with self.assertRaises(RuntimeError):
            list(walk_symbol(book, "AAPL"))

    def test_gap_uses_the_open_and_not_the_close(self) -> None:
        book = _session_pair()
        day = max(day for _symbol, day in book if True)
        spells = [spell for spell in gap_spells(book, gap_max=-0.004, stop_mode="1atr", exit_mode="flat") if spell["symbol"] == "AAPL"]
        self.assertTrue(any(spell["day"] == day for spell in spells))
        quiet = gap_spells(book, gap_max=-0.02, stop_mode="1atr", exit_mode="flat")
        self.assertFalse(any(spell["symbol"] == "AAPL" and spell["day"] == day for spell in quiet))
        changed = _session_pair()
        for bar in changed[("AAPL", day)]:
            if bar["minute"] == 15 * 60 + 50:
                bar["close"] = 50.0
        again = [spell for spell in gap_spells(changed, gap_max=-0.004, stop_mode="1atr", exit_mode="flat") if spell["symbol"] == "AAPL" and spell["day"] == day]
        self.assertEqual(len(again), 1)

    def test_lags_ignore_the_next_bar(self) -> None:
        days = _weekdays(date(2024, 1, 2), 8)
        frame = add_return_lags(build_frame(_book(days)))
        day = days[5]
        before = _row(frame, day, "AAPL", 14 * 60)
        book = _book(days)
        nxt = next(bar for bar in book[("AAPL", day)] if bar["minute"] == 14 * 60 + 5)
        nxt["close"] = nxt["close"] + 5
        after = _row(add_return_lags(build_frame(book)), day, "AAPL", 14 * 60)
        for name in ("ret_1_l1", "ret_1_l2", "ret_1_l3"):
            self.assertAlmostEqual(float(before[name]), float(after[name]), places=10)

    def test_stack_fit_ignores_the_test_day_label(self) -> None:
        rows = []
        start = date(2024, 1, 2)
        for offset in range(8):
            day = start + timedelta(days=offset)
            for index in range(6):
                rows.append(
                    {
                        "symbol": "AAPL",
                        "day": day,
                        "minute": 600 + index,
                        "pred_h3": 0.001 * (offset + 1),
                        "pred_h6": -0.001,
                        "pred_h12": 0.002,
                        "fwd_flat": 0.01 if offset < 7 else 0.2,
                    }
                )
        frame = pd.DataFrame(rows)
        test_day = start + timedelta(days=7)
        first = stack_oos(frame, ["pred_h3", "pred_h6", "pred_h12"], "fwd_flat", [test_day], min_rows=5)
        frame.loc[frame["day"] == test_day, "fwd_flat"] = -0.3
        second = stack_oos(frame, ["pred_h3", "pred_h6", "pred_h12"], "fwd_flat", [test_day], min_rows=5)
        self.assertTrue(first.dropna().equals(second.dropna()))

    def test_top1_acts_on_the_first_bar_not_a_later_peak(self) -> None:
        day = date(2024, 1, 2)
        early = {"day": day, "entry_t": 100, "exit_t": 200, "priority": 0.01, "symbol": "AAPL"}
        later = {"day": day, "entry_t": 300, "exit_t": 400, "priority": 0.09, "symbol": "NVDA"}
        taken = take_spells([later, early], "top1")
        self.assertEqual([spell["symbol"] for spell in taken], ["AAPL"])
        same_time = [
            {"day": day, "entry_t": 100, "exit_t": 200, "priority": 0.01, "symbol": "AAPL"},
            {"day": day, "entry_t": 100, "exit_t": 200, "priority": 0.02, "symbol": "MSFT"},
        ]
        self.assertEqual(take_spells(same_time, "top1")[0]["symbol"], "MSFT")

    def test_ml_spells_reject_holdout_rows(self) -> None:
        frame = pd.DataFrame(
            [{"symbol": "AAPL", "day": HOLDOUT_START, "minute": 600, "atr": 1.0, "pred": 0.01}]
        )
        with self.assertRaises(RuntimeError):
            ml_spells(frame, {}, horizon=12, exit_mode="horizon", stop_mode="1atr", min_pred=0.0)
