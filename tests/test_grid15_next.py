"""Exit books and the daily top-k rank are causal, and the screen was frozen first."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta

from backtest.gate import ideas_tried
from backtest.grid15_next import (
    BOOKS,
    MIN_HISTORY,
    TOP_K,
    Running,
    SymbolMemory,
    rank_candidates,
    run_next,
    screen_failures,
    trail_spell,
    vote_impulse,
    vote_regime,
    vote_slot_scale,
)
from backtest.grid15 import prepare_day
from backtest.periods import HOLDOUT_START
from backtest.run_grid15_next import main
from backtest.spells import resolve_exit


def _weekdays(start: date, count: int) -> list[date]:
    days = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _bar(day: date, minute: int, open_: float, high: float, low: float, close: float) -> dict:
    return {
        "t": day.toordinal() * 1000 + minute,
        "minute": minute,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000.0,
    }


def _flat(day: date, price: float) -> list[dict]:
    bars = []
    minute = 9 * 60 + 30
    while minute <= 15 * 60 + 50:
        bars.append(_bar(day, minute, price, price, price, price))
        minute += 5
    return bars


def _break_day(day: date, price: float) -> list[dict]:
    bars = []
    minute = 9 * 60 + 30
    while minute <= 15 * 60 + 50:
        if minute <= 9 * 60 + 40:
            bars.append(_bar(day, minute, price, price + 0.30, price, price + 0.10))
        elif minute <= 9 * 60 + 55:
            bars.append(_bar(day, minute, price + 0.20, price + 0.50, price + 0.15, price + 0.40))
        else:
            bars.append(_bar(day, minute, price + 0.40, price + 0.45, price + 0.20, price + 0.40))
        minute += 5
    return bars


class NextGridTests(unittest.TestCase):
    def test_screen_and_registry_were_frozen(self) -> None:
        self.assertEqual(ideas_tried(), 54)
        self.assertEqual(TOP_K, 4)
        self.assertEqual(len(BOOKS), 9)
        self.assertEqual(screen_failures(
            validate_net=1, pooled_net=1, recent_net=1, validate_trades=80,
            positive_halves=4, ex_top5=1, days_with_fill=80, sessions=100,
        ), [])
        self.assertTrue(screen_failures(
            validate_net=-1, pooled_net=1, recent_net=1, validate_trades=80,
            positive_halves=4, ex_top5=1, days_with_fill=90, sessions=100,
        ))

    def test_tiers_vote_without_looking_ahead(self) -> None:
        self.assertTrue(vote_impulse(None, "mom").veto)
        self.assertTrue(vote_impulse(-0.2, "mom").veto)
        self.assertFalse(vote_impulse(0.4, "mom").veto)
        self.assertTrue(vote_impulse(0.2, "rev").veto)
        self.assertFalse(vote_impulse(-1.0, "rev").veto)
        self.assertTrue(vote_slot_scale(0.001).veto)
        self.assertFalse(vote_slot_scale(0.003).veto)
        blocked = vote_regime(True, True, enabled=True)
        self.assertTrue(blocked.veto)
        self.assertFalse(vote_regime(True, False, enabled=True).veto)
        self.assertFalse(vote_regime(True, True, enabled=False).veto)

    def test_slot_memory_does_not_include_the_observation_just_scored(self) -> None:
        memory = SymbolMemory()
        for index in range(MIN_HISTORY):
            memory.bucket(585).add(0.01 if index % 2 == 0 else -0.01)
            memory.forward(585).add(0.03 if index % 2 == 0 else -0.03)
        before = memory.z(585, -0.05)
        scale = memory.forward_std(585)
        self.assertIsNotNone(before)
        self.assertIsNotNone(scale)
        assert before is not None and scale is not None
        self.assertLess(before, 0)
        self.assertGreater(scale, 0.02)
        memory.bucket(585).add(-0.05)
        memory.forward(585).add(0.0)
        self.assertNotEqual(memory.z(585, -0.05), before)

    def test_rank_keeps_four_names_and_one_slot_each(self) -> None:
        rows = []
        for symbol, score in (("AAPL", 2.0), ("AMD", 1.5), ("NVDA", 1.2), ("TSLA", 0.4), ("MSFT", 0.2), ("SPY", 3.0)):
            rows.append({"symbol": symbol, "start": 585, "score": score, "veto": False})
            rows.append({"symbol": symbol, "start": 600, "score": score - 0.1, "veto": False})
        picked = rank_candidates(rows, TOP_K, False)
        self.assertEqual([row["symbol"] for row in picked], ["SPY", "AAPL", "AMD", "NVDA"])
        self.assertTrue(all(row["start"] == 585 for row in picked))
        self.assertEqual(rank_candidates(rows, TOP_K, True), [])

    def test_trail_uses_the_raised_stop_on_the_next_bar(self) -> None:
        day = date(2024, 7, 12)
        bars = [
            _bar(day, 600, 100.0, 102.0, 99.5, 101.5),
            _bar(day, 605, 101.4, 101.6, 100.9, 101.0),
            _bar(day, 15 * 60 + 50, 101.0, 101.2, 100.8, 101.0),
        ]
        # Pad so prepare_day sees a full session is not required; trail_spell takes a view.
        view = prepare_day(_flat(day, 100.0))
        assert view is not None
        view.ordered = bars
        view.by_minute = {int(bar["minute"]): bar for bar in bars}
        # Flat minute must exist for the walker. The third bar is the flat bar.
        planned = trail_spell(view, 0, 99.0, 1.0)
        self.assertIsNotNone(planned)
        assert planned is not None
        self.assertEqual(planned["planned_reason"], "stop")
        self.assertAlmostEqual(planned["stop"], 101.0)
        resolved = resolve_exit(planned, slip_bps=0.0)
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved[1], "stop")
        self.assertAlmostEqual(resolved[0], 101.0)

    def test_exit_clocks_differ_and_a_later_day_does_not_change_the_count(self) -> None:
        day = date(2024, 7, 12)
        book = {}
        for symbol in ("AAPL", "AMD", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "SPY", "QQQ"):
            book[(symbol, day)] = _break_day(day, 100.0)
        result = run_next(book)
        flat = result.spells["x_flat"]
        half = result.spells["x_30"]
        noon = result.spells["x_noon"]
        self.assertTrue(flat and half and noon)
        self.assertTrue(all(int(spell["exit_bar"]["minute"]) == 15 * 60 + 50 for spell in flat))
        self.assertTrue(all(int(spell["exit_bar"]["minute"]) == 10 * 60 + 30 for spell in half))
        self.assertTrue(all(int(spell["exit_bar"]["minute"]) == 12 * 60 for spell in noon))
        self.assertTrue(all(int(spell["entry_bar"]["minute"]) == 10 * 60 for spell in flat))
        first_day = {spell["entry_t"] for spell in flat}
        later = dict(book)
        later[("AAPL", date(2024, 7, 15))] = _break_day(date(2024, 7, 15), 50.0)
        again = run_next(later)
        again_first = {spell["entry_t"] for spell in again.spells["x_flat"] if spell["day"] == day}
        self.assertEqual(first_day, again_first)

    def test_holdout_is_refused(self) -> None:
        book = {("AAPL", HOLDOUT_START): _flat(HOLDOUT_START, 100.0)}
        with self.assertRaises(RuntimeError):
            run_next(book)

    def test_missing_bars_do_not_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["--root", tmp]), 2)

    def test_running_std_waits_for_history(self) -> None:
        stats = Running()
        for _ in range(MIN_HISTORY - 1):
            stats.add(0.01)
        self.assertIsNone(stats.std())
        stats.add(0.01)
        self.assertIsNotNone(stats.std())


if __name__ == "__main__":
    unittest.main()
