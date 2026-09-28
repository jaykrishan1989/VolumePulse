"""Appear-to-disappear fills. These tests do not read the market file."""

from __future__ import annotations

import unittest
from datetime import date

from backtest.costs import apply_slip, commission
from backtest.periods import HOLDOUT_START
from backtest.spells import (
    ACCOUNT_USD,
    build_spells,
    portfolio,
    selection_hits,
    simulate_spell,
)


DAY = date(2024, 8, 1)


def _bars(start: int, rows: list[tuple[float, float, float, float]], t0: int = 1_700_000_000) -> list[dict]:
    bars = []
    for index, (open_px, high, low, close) in enumerate(rows):
        bars.append(
            {
                "minute": start + index * 5,
                "open": open_px,
                "high": high,
                "low": low,
                "close": close,
                "t": t0 + index * 300,
            }
        )
    return bars


def _spells(on_minutes: list[int], bars: list[dict], spec: dict, stop: float = 98.0) -> list[dict]:
    hits = [
        {
            "symbol": "AAPL",
            "day": DAY,
            "minute": minute,
            "stop": stop,
            "score": 80,
            "rr": 1.5,
            "rvol": 1.2,
            "reclaimed_vwap": True,
            "above_vwap": True,
        }
        for minute in on_minutes
    ]
    return build_spells(hits, {("AAPL", DAY): bars}, spec)


class SpellTests(unittest.TestCase):
    def test_buy_on_appear_and_sell_on_disappear(self) -> None:
        bars = _bars(600, [(100, 101, 99, 100.4)] * 4)
        spells = _spells([600], bars, {"confirm": 1, "exit_lag": 1})
        self.assertEqual(len(spells), 1)
        spell = spells[0]
        self.assertEqual(spell["entry_bar"]["minute"], 605)
        self.assertEqual(spell["exit_bar"]["minute"], 610)
        self.assertEqual(spell["exit_kind"], "sell")
        trade = simulate_spell(spell, equity=ACCOUNT_USD)
        assert trade is not None
        self.assertEqual(trade["reason"], "sell")
        self.assertAlmostEqual(trade["entry"], apply_slip(100, "buy", 2))
        self.assertAlmostEqual(trade["exit"], apply_slip(100, "sell", 2))
        self.assertGreater(trade["fees"], 0.7)

    def test_exit_lag_ignores_one_off_bar(self) -> None:
        bars = _bars(600, [(100, 101, 99.5, 100.2)] * 6)
        spells = _spells([600, 610], bars, {"confirm": 1, "exit_lag": 2})
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["entry_bar"]["minute"], 605)
        self.assertEqual(spells[0]["exit_bar"]["minute"], 625)

    def test_confirm_waits_for_a_second_on_bar(self) -> None:
        bars = _bars(600, [(100, 101, 99.5, 100.2)] * 4)
        spells = _spells([600, 605], bars, {"confirm": 2, "exit_lag": 1})
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["buy_minute"], 605)
        self.assertEqual(spells[0]["entry_bar"]["minute"], 610)
        self.assertEqual(spells[0]["exit_bar"]["minute"], 615)

    def test_stop_fires_before_disappear_and_can_be_turned_off(self) -> None:
        bars = _bars(
            600,
            [
                (100, 101, 99, 100),
                (100, 101, 97, 99),
                (99, 100, 98, 99.5),
            ],
        )
        spells = _spells([600], bars, {"confirm": 1, "exit_lag": 1}, stop=98)
        stopped = simulate_spell(spells[0], use_stop=True)
        held = simulate_spell(spells[0], use_stop=False)
        assert stopped is not None and held is not None
        self.assertEqual(stopped["reason"], "stop")
        self.assertAlmostEqual(stopped["exit"], apply_slip(98, "sell", 2))
        self.assertEqual(held["reason"], "sell")
        self.assertAlmostEqual(held["exit"], apply_slip(99, "sell", 2))

    def test_sell_at_the_open_does_not_use_the_exit_bar_low(self) -> None:
        bars = _bars(
            600,
            [
                (100, 101, 99, 100),
                (100, 101, 99, 100),
                (100, 101, 90, 95),
            ],
        )
        spells = _spells([600], bars, {"confirm": 1, "exit_lag": 1}, stop=98)
        trade = simulate_spell(spells[0], use_stop=True)
        assert trade is not None
        self.assertEqual(trade["reason"], "sell")
        self.assertAlmostEqual(trade["exit"], apply_slip(100, "sell", 2))

    def test_still_on_at_the_close_flattens_at_1555(self) -> None:
        start = 15 * 60 + 40
        bars = _bars(start, [(100, 101, 99, 100.5)] * 4)
        spells = _spells([start, start + 5, start + 10], bars, {"confirm": 1, "exit_lag": 1})
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0]["exit_kind"], "flat")
        self.assertEqual(spells[0]["exit_bar"]["minute"], 15 * 60 + 50)
        trade = simulate_spell(spells[0])
        assert trade is not None
        self.assertEqual(trade["reason"], "flat")
        self.assertAlmostEqual(trade["exit"], apply_slip(100.5, "sell", 2))

    def test_no_entry_on_the_1550_bar(self) -> None:
        start = 15 * 60 + 45
        bars = _bars(start, [(100, 101, 99, 100)] * 3)
        spells = _spells([start], bars, {"confirm": 1, "exit_lag": 1})
        self.assertEqual(spells, [])

    def test_portfolio_cash_matches_trade_net_and_skips_a_second_share(self) -> None:
        cheap = _spells([600], _bars(600, [(100, 101, 99, 100)] * 4), {"confirm": 1, "exit_lag": 1})
        result = portfolio(cheap, equity=ACCOUNT_USD)
        self.assertEqual(len(result["trades"]), 1)
        self.assertAlmostEqual(result["net"], result["trades"][0]["net"])
        trade = result["trades"][0]
        self.assertGreater(trade["shares"], 1)
        round_trip = commission(trade["shares"], trade["entry"], "buy", "tiered") + commission(
            trade["shares"], trade["exit"], "sell", "tiered"
        )
        self.assertAlmostEqual(trade["fees"], round_trip)

        first = _manual("AAA", 1_000, 2_000, 2000.0, 2010.0, low=1990.0)
        second = _manual("BBB", 1_000, 2_000, 2000.0, 2010.0, low=1990.0)
        crowded = portfolio([first, second], equity=ACCOUNT_USD, use_stop=False)
        self.assertEqual(len(crowded["trades"]), 1)

    def test_stop_frees_cash_for_a_later_entry(self) -> None:
        stopped = _manual("AAA", 1_000, 9_000, 100.0, 100.0, low=90.0, stop=98.0)
        later = _manual("BBB", 2_000, 3_000, 2000.0, 2010.0, low=1990.0, stop=1900.0)
        result = portfolio([stopped, later], equity=ACCOUNT_USD, use_stop=True)
        self.assertEqual({trade["symbol"] for trade in result["trades"]}, {"AAA", "BBB"})
        held = portfolio([stopped, later], equity=ACCOUNT_USD, use_stop=False)
        self.assertEqual([trade["symbol"] for trade in held["trades"]], ["AAA"])

    def test_selection_drops_the_holdout(self) -> None:
        hits = [
            {"day": date(2024, 8, 1), "symbol": "AAPL"},
            {"day": HOLDOUT_START, "symbol": "AAPL"},
        ]
        kept = selection_hits(hits)
        self.assertEqual(len(kept), 1)
        self.assertLess(kept[0]["day"], HOLDOUT_START)


def _manual(
    symbol: str,
    entry_t: int,
    exit_t: int,
    entry_open: float,
    exit_open: float,
    *,
    low: float,
    stop: float = 1.0,
) -> dict:
    entry = {
        "minute": 600,
        "open": entry_open,
        "high": entry_open + 1,
        "low": low,
        "close": entry_open,
        "t": entry_t,
    }
    exit_bar = {
        "minute": 610,
        "open": exit_open,
        "high": exit_open + 1,
        "low": exit_open - 1,
        "close": exit_open,
        "t": exit_t,
    }
    return {
        "symbol": symbol,
        "day": DAY,
        "buy_minute": 600,
        "entry_t": entry_t,
        "exit_t": exit_t,
        "stop": stop,
        "score": 80,
        "entry_bar": entry,
        "exit_bar": exit_bar,
        "path": [entry],
        "exit_kind": "sell",
    }


if __name__ == "__main__":
    unittest.main()
