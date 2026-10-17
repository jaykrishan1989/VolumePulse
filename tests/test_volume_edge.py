"""Same-minute volume rules are frozen, causal, and do not read the holdout."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from backtest.gate import ideas_tried
from backtest.periods import HOLDOUT_START
from backtest.volume_edge import (
    ADOPTABLE,
    BOOK_NAMES,
    DAY_SHARE_MIN,
    DISASTER_STOP,
    PRICE_FLOOR,
    RVOL_MULT,
    RVOL_QUIET,
    RVOL_WINDOW,
    clears_published_milestone,
    generate,
    screen_failures,
)


def _weekdays(start: date, count: int) -> list[date]:
    days = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _session(day: date, price: float = 100.0, volume: float = 1000.0, overrides: dict | None = None) -> list[dict]:
    bars = []
    minute = 9 * 60 + 30
    while minute <= 15 * 60 + 50:
        opened, closed, vol = price, price, volume
        if overrides and minute in overrides:
            opened, closed, vol = overrides[minute]
        bars.append(
            {
                "t": day.toordinal() * 1000 + minute,
                "minute": minute,
                "open": opened,
                "high": max(opened, closed),
                "low": min(opened, closed),
                "close": closed,
                "volume": vol,
            }
        )
        minute += 5
    return bars


def _book(signal_day: date, **names: dict) -> dict:
    days = _weekdays(date(2023, 1, 3), RVOL_WINDOW + 1)
    assert days[-1] == signal_day or True
    days[-1] = signal_day if signal_day == days[-1] else days[-1]
    book: dict = {}
    for day in days[:-1]:
        for symbol in names:
            book[(symbol, day)] = _session(day)
    for symbol, overrides in names.items():
        book[(symbol, days[-1])] = _session(days[-1], overrides=overrides)
    return book, days[-1]


class VolumeEdgeRulesTest(unittest.TestCase):
    def test_hurdles_stay_frozen(self) -> None:
        self.assertEqual(ideas_tried(), 54)
        self.assertEqual(ADOPTABLE, frozenset({"u_primary"}))
        self.assertEqual(BOOK_NAMES, ("u_primary", "u_fade", "u_quiet"))
        self.assertEqual(RVOL_MULT, 2.0)
        self.assertEqual(RVOL_QUIET, 0.5)
        self.assertEqual(RVOL_WINDOW, 20)
        self.assertEqual(PRICE_FLOOR, 0.0010)
        self.assertEqual(DAY_SHARE_MIN, 0.50)
        self.assertNotEqual(RVOL_MULT, 1.2)
        self.assertNotEqual(PRICE_FLOOR, 0.0040)
        clean = dict(
            validate_net=1.0,
            pooled_net=1.0,
            recent_net=1.0,
            validate_trades=80,
            positive_halves=4,
            ex_top5=1.0,
            avg_bps=1.0,
            day_share=0.50,
        )
        self.assertEqual(screen_failures(**clean), [])
        self.assertFalse(clears_published_milestone(1260.736236000008, 1.0, 80))

    def test_twice_the_minute_with_ten_basis_points_is_the_line(self) -> None:
        signal = _weekdays(date(2023, 1, 3), RVOL_WINDOW + 1)[-1]
        book, day = _book(signal, AAPL={10 * 60: (100.0, 100.20, 2000.0)})
        spells = [spell for spell in generate(book).spells["u_primary"] if spell["day"] == day]
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["symbol"], "AAPL")
        self.assertEqual(spells[0]["buy_minute"], 10 * 60 + 5)
        self.assertEqual(spells[0]["invest_fraction"], 1.0)
        self.assertAlmostEqual(spells[0]["stop"], float(spells[0]["entry_bar"]["open"]) * (1.0 - DISASTER_STOP))
        self.assertAlmostEqual(spells[0]["signal_rvol"], 2.0)

        shy, shy_day = _book(signal, AAPL={10 * 60: (100.0, 100.20, 1500.0)})
        self.assertEqual([spell for spell in generate(shy).spells["u_primary"] if spell["day"] == shy_day], [])
        small, small_day = _book(signal, AAPL={10 * 60: (100.0, 100.05, 2500.0)})
        self.assertEqual([spell for spell in generate(small).spells["u_primary"] if spell["day"] == small_day], [])

    def test_the_heavier_name_wins_and_the_down_bar_is_the_other_book(self) -> None:
        signal = _weekdays(date(2023, 1, 3), RVOL_WINDOW + 1)[-1]
        book, day = _book(
            signal,
            AAPL={10 * 60: (100.0, 100.20, 3000.0)},
            NVDA={10 * 60: (100.0, 100.30, 2500.0)},
        )
        spells = [spell for spell in generate(book).spells["u_primary"] if spell["day"] == day]
        self.assertEqual(spells[0]["symbol"], "AAPL")

        faded, fade_day = _book(signal, NVDA={10 * 60 + 15: (100.0, 99.80, 2500.0)})
        result = generate(faded)
        self.assertEqual([spell for spell in result.spells["u_primary"] if spell["day"] == fade_day], [])
        fade_spells = [spell for spell in result.spells["u_fade"] if spell["day"] == fade_day]
        self.assertEqual(len(fade_spells), 1)
        self.assertEqual(fade_spells[0]["symbol"], "NVDA")
        self.assertEqual(fade_spells[0]["buy_minute"], 10 * 60 + 20)

    def test_quiet_control_does_not_count_as_the_primary(self) -> None:
        signal = _weekdays(date(2023, 1, 3), RVOL_WINDOW + 1)[-1]
        book, day = _book(signal, AAPL={11 * 60: (100.0, 100.20, 400.0)})
        result = generate(book)
        self.assertEqual([spell for spell in result.spells["u_primary"] if spell["day"] == day], [])
        quiet = [spell for spell in result.spells["u_quiet"] if spell["day"] == day]
        self.assertEqual(len(quiet), 1)
        self.assertAlmostEqual(quiet[0]["signal_rvol"], 0.4)

    def test_a_later_day_does_not_change_the_earlier_fill(self) -> None:
        signal = _weekdays(date(2023, 1, 3), RVOL_WINDOW + 1)[-1]
        book, day = _book(signal, AAPL={10 * 60: (100.0, 100.25, 4000.0)})
        before = [spell for spell in generate(book).spells["u_primary"] if spell["day"] == day]
        book[("AAPL", date(2023, 6, 1))] = _session(date(2023, 6, 1), volume=50_000.0)
        after = [spell for spell in generate(book).spells["u_primary"] if spell["day"] == day]
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]["symbol"], after[0]["symbol"])
        self.assertEqual(before[0]["buy_minute"], after[0]["buy_minute"])
        self.assertAlmostEqual(before[0]["signal_rvol"], after[0]["signal_rvol"])

    def test_holdout_day_is_refused(self) -> None:
        day = HOLDOUT_START
        book = {("AAPL", day): _session(day)}
        with self.assertRaises(RuntimeError):
            generate(book)


if __name__ == "__main__":
    unittest.main()
