"""Research-area overlays. These tests do not read the market file or the holdout."""

from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path

from backtest.areas import (
    AREA_REGISTRY,
    FALLING_TAPE,
    KELLY_CAP,
    KELLY_MIN_OBS,
    corwin_schultz_spread,
    falling_tape,
    half_spread_slip,
    high_range_days,
    kelly_fraction,
    participation_slip,
    percentile_at,
    spy_above_vwap,
    spy_session_ranges,
)
from backtest.run_areas import refuse_holdout
from backtest.spells import portfolio
from models.registry import Store, create_passing_checkpoint


ROOT = Path(__file__).resolve().parents[1]
DAY = date(2024, 8, 1)


def _bar(minute: int, open_px: float, high: float, low: float, close: float, t: int, volume: float = 1_000_000.0) -> dict:
    return {
        "minute": minute,
        "open": open_px,
        "high": high,
        "low": low,
        "close": close,
        "t": t,
        "volume": volume,
    }


def _spell(
    symbol: str,
    entry_t: int,
    exit_t: int,
    open_px: float,
    exit_px: float,
    stop: float,
    *,
    day: date = DAY,
    minute: int = 600,
) -> dict:
    return {
        "symbol": symbol,
        "day": day,
        "buy_minute": minute,
        "entry_t": entry_t,
        "exit_t": exit_t,
        "stop": stop,
        "score": 80.0,
        "entry_bar": _bar(minute + 5, open_px, open_px + 1.0, open_px - 0.5, open_px, entry_t),
        "exit_bar": _bar(minute + 10, exit_px, exit_px + 1.0, stop + 0.5, exit_px, exit_t),
        "path": [],
        "exit_kind": "sell",
    }


class SizingTests(unittest.TestCase):
    def test_one_percent_risk_is_two_shares_not_a_full_ticket(self) -> None:
        spell = _spell("AAPL", 1_000, 2_000, 100.0, 101.0, 90.0)
        sized = portfolio([spell], risk_fraction=0.01, equity=2120.0, slip_bps=2.0)
        full = portfolio([spell], equity=2120.0, slip_bps=2.0)
        self.assertEqual(len(sized["trades"]), 1)
        self.assertEqual(sized["trades"][0]["shares"], 2)
        self.assertEqual(full["trades"][0]["shares"], 21)

    def test_invest_fraction_zero_skips(self) -> None:
        spell = _spell("AAPL", 1_000, 2_000, 100.0, 101.0, 90.0)
        spell["invest_fraction"] = 0
        result = portfolio([spell], equity=2120.0)
        self.assertEqual(result["trades"], [])

    def test_one_position_skips_the_overlapping_name(self) -> None:
        first = _spell("AAPL", 1_000, 5_000, 100.0, 101.0, 50.0)
        second = _spell("MSFT", 1_001, 5_000, 10.0, 10.1, 1.0)
        limited = portfolio([first, second], max_concurrent=1, equity=2120.0, slip_bps=0.0)
        both = portfolio([first, second], equity=2120.0, slip_bps=0.0)
        self.assertEqual(len(both["trades"]), 2)
        self.assertEqual(len(limited["trades"]), 1)
        self.assertEqual(limited["trades"][0]["symbol"], "AAPL")

    def test_daily_loss_skips_the_later_trade(self) -> None:
        loser = _spell("AAPL", 1_000, 1_500, 100.0, 90.0, 1.0)
        later = _spell("MSFT", 1_600, 2_000, 100.0, 101.0, 1.0)
        stopped = portfolio([loser, later], daily_loss_fraction=0.01, equity=2120.0, slip_bps=0.0)
        both = portfolio([loser, later], equity=2120.0, slip_bps=0.0)
        self.assertEqual(len(both["trades"]), 2)
        self.assertEqual([trade["symbol"] for trade in stopped["trades"]], ["AAPL"])

    def test_two_consecutive_losses_skip_the_third(self) -> None:
        spells = [
            _spell("AAPL", 1_000, 1_100, 50.0, 49.0, 1.0),
            _spell("MSFT", 1_200, 1_300, 50.0, 49.0, 1.0),
            _spell("NVDA", 1_400, 1_500, 50.0, 49.0, 1.0),
        ]
        stopped = portfolio(spells, max_consecutive_losses=2, equity=2120.0, slip_bps=0.0)
        all_three = portfolio(spells, equity=2120.0, slip_bps=0.0)
        self.assertEqual(len(all_three["trades"]), 3)
        self.assertEqual([trade["symbol"] for trade in stopped["trades"]], ["AAPL", "MSFT"])

    def test_default_portfolio_still_buys_a_full_ticket(self) -> None:
        spell = _spell("AAPL", 1_000, 2_000, 100.0, 101.0, 90.0)
        result = portfolio([spell], equity=2120.0, slip_bps=2.0)
        self.assertEqual(result["trades"][0]["shares"], 21)
        self.assertAlmostEqual(result["net"], result["final"] - 2120.0)


class EstimatorTests(unittest.TestCase):
    def test_corwin_schultz_is_positive_on_a_wide_pair_and_zero_when_alpha_is_not(self) -> None:
        wide = corwin_schultz_spread(50.0, 40.0, 55.0, 42.0)
        self.assertGreater(wide, 0.0)
        self.assertLess(wide, 1.0)
        self.assertEqual(corwin_schultz_spread(10.0, 10.0, 10.0, 10.0), 0.0)
        # A gap between two tight bars makes alpha non-positive, so the spread is zero.
        self.assertEqual(corwin_schultz_spread(10.0, 9.5, 20.0, 19.5), 0.0)

    def test_half_spread_without_a_previous_bar_stays_at_two_bp(self) -> None:
        spell = _spell("AAPL", 1_000, 2_000, 100.0, 101.0, 90.0)
        book = {("AAPL", DAY): [spell["entry_bar"]]}
        self.assertEqual(half_spread_slip(book, spell), 2.0)

    def test_participation_impact_is_well_under_a_commission_on_a_busy_bar(self) -> None:
        spell = _spell("AAPL", 1_000, 2_000, 100.0, 101.0, 99.0, minute=600)
        spell["entry_bar"]["volume"] = 1_000_000.0
        spell["entry_bar"]["close"] = 100.0
        slip = participation_slip(spell)
        assert slip is not None
        self.assertLess(slip - 2.0, 1.0)
        spell["entry_bar"]["volume"] = None
        self.assertIsNone(participation_slip(spell))

    def test_kelly_stands_aside_without_a_positive_sample(self) -> None:
        self.assertEqual(kelly_fraction([-0.01] * (KELLY_MIN_OBS - 1)), 0.0)
        self.assertEqual(kelly_fraction([-0.01] * KELLY_MIN_OBS), 0.0)
        fraction = kelly_fraction([0.02] * KELLY_MIN_OBS + [0.01])
        self.assertGreater(fraction, 0.0)
        self.assertLessEqual(fraction, KELLY_CAP)

    def test_high_range_needs_sixty_prior_sessions(self) -> None:
        start = date(2023, 1, 3)
        short = {start + timedelta(days=index): 0.01 for index in range(59)}
        self.assertEqual(high_range_days(short), set(short))
        ranges = {
            start + timedelta(days=index): 0.05 if index < 59 else 0.01 for index in range(61)
        }
        stand = high_range_days(ranges)
        self.assertIn(start + timedelta(days=59), stand)
        self.assertNotIn(start + timedelta(days=60), stand)
        self.assertEqual(percentile_at(list(range(1, 61)), 0.75), 45)

    def test_spy_vwap_and_falling_tape_use_the_on_list_bar(self) -> None:
        day = DAY
        bars = [
            _bar(570, 100.0, 101.0, 99.0, 100.0, 1, volume=100.0),
            _bar(600, 99.0, 99.2, 97.0, 97.5, 2, volume=100.0),
        ]
        book = {("SPY", day): bars}
        spell = _spell("AAPL", 1_000, 2_000, 50.0, 51.0, 40.0, minute=600)
        self.assertFalse(spy_above_vwap(book, spell))
        self.assertTrue(falling_tape(book, spell))
        self.assertLess(FALLING_TAPE, -0.002)
        bars[1]["close"] = 100.5
        bars[1]["high"] = 101.0
        bars[1]["low"] = 99.5
        self.assertTrue(spy_above_vwap(book, spell))
        self.assertFalse(falling_tape(book, spell))
        self.assertEqual(len(spy_session_ranges(book)), 1)

    def test_registry_covers_the_four_areas_once(self) -> None:
        ids = [area.id for area in AREA_REGISTRY]
        self.assertEqual(len(ids), len(set(ids)))
        counts: dict[str, int] = {}
        for area in AREA_REGISTRY:
            counts[area.area] = counts.get(area.area, 0) + 1
        self.assertEqual(
            counts,
            {"position_sizing": 5, "time_of_day": 4, "liquidity": 3, "market_regime": 3},
        )
        self.assertTrue(all(area.uses_clock for area in AREA_REGISTRY if area.area == "time_of_day"))
        self.assertFalse(any(area.uses_clock for area in AREA_REGISTRY if area.area != "time_of_day"))

    def test_holdout_day_is_refused(self) -> None:
        with self.assertRaises(RuntimeError):
            refuse_holdout([{"day": date(2026, 4, 1)}], "spell")

    def test_v01_results_cannot_mint_a_passing_checkpoint(self) -> None:
        results = json.loads((ROOT / "models" / "checkpoints" / "v0.1" / "results.json").read_text(encoding="utf-8"))
        store = Store(ROOT / "models")
        with self.assertRaises(RuntimeError) as raised:
            create_passing_checkpoint(
                store,
                results,
                {"passedGate": True, "liveCapable": True, "signalRule": {}, "expected": {}},
            )
        self.assertIn("refusing a passing checkpoint", str(raised.exception))
        self.assertFalse((ROOT / "models" / "checkpoints" / "v1.0").exists())


if __name__ == "__main__":
    unittest.main()
