"""Scoring tests for Right Time to Buy. Synthetic bars only — no broker."""

from __future__ import annotations

import unittest
from datetime import timedelta

from app.entry import (
    ENTRY,
    bars_clear_rebound,
    bars_downtrend,
    bars_falling,
    bars_firm,
    bars_stale_rebound,
    build_demo_board,
    demo_as_of,
    diagnose_entry,
    evaluate_entry,
    liquid_quote,
    screen_entries,
    sector_etf_for,
    watch_symbols,
)


def _now(bars):
    from datetime import datetime

    from app.entry import NY

    return datetime.fromtimestamp(bars[-1]["t"], NY) + timedelta(seconds=25)


def _firm(**extra):
    params = dict(
        spy_state="firm",
        qqq_state="firm",
        sector_state="firm",
        sector_etf="SMH",
        session_fraction=0.42,
        enforce_clock=True,
    )
    params.update(extra)
    return params


class EntryScoringTest(unittest.TestCase):
    def test_clear_rebound_qualifies(self):
        bars = bars_clear_rebound(118.4)
        quote = liquid_quote("NVDA", bars, rvol=3.4)
        found = diagnose_entry(bars, quote, now=_now(bars), **_firm())
        self.assertTrue(found["ok"], found["fail"])
        signal = found["signal"]
        self.assertIsNotNone(signal)
        self.assertGreaterEqual(signal.score, ENTRY.min_score)
        self.assertTrue(any(reason.startswith("Pulled back") for reason in signal.reasons))
        self.assertIn("Reclaimed VWAP", signal.reasons)
        self.assertTrue(any(reason.startswith("RVOL") for reason in signal.reasons))
        self.assertLessEqual(signal.triggered_bars, ENTRY.max_trigger_age_bars)
        self.assertLess(signal.stop, signal.entry_high)
        self.assertLessEqual(signal.entry_low, signal.entry_high)
        self.assertGreater(signal.target, signal.entry_high)
        self.assertGreaterEqual(signal.reward_risk, ENTRY.min_rr)
        self.assertEqual(signal.symbol, "NVDA")

    def test_steady_downtrend_does_not_qualify(self):
        bars = bars_downtrend(248.0)
        quote = liquid_quote("TSLA", bars, rvol=1.7)
        signal = evaluate_entry(bars, quote, now=_now(bars), **_firm())
        self.assertIsNone(signal)

    def test_illiquid_does_not_qualify(self):
        bars = bars_clear_rebound(14.2)
        quote = liquid_quote("SOFI", bars, dollar_volume=80_000, rvol=0.4)
        found = diagnose_entry(bars, quote, now=demo_as_of(), **_firm())
        self.assertFalse(found["ok"])
        self.assertEqual(found["fail"], "illiquid")
        self.assertIsNone(found["signal"])

    def test_wide_spread_does_not_qualify(self):
        bars = bars_clear_rebound(22.4)
        quote = liquid_quote("INTC", bars, spread_pct=0.012, rvol=1.5)
        found = diagnose_entry(bars, quote, now=demo_as_of(), **_firm())
        self.assertEqual(found["fail"], "wide spread")
        self.assertIsNone(evaluate_entry(bars, quote, now=demo_as_of(), **_firm()))

    def test_stale_trigger_does_not_qualify(self):
        bars = bars_stale_rebound(28.4)
        quote = liquid_quote("PLTR", bars, rvol=2.4)
        found = diagnose_entry(bars, quote, now=_now(bars), **_firm(sector_etf="XLK"))
        self.assertEqual(found["fail"], "stale trigger")
        self.assertIsNone(found["signal"])
        self.assertGreater(found.get("age", 0), ENTRY.max_trigger_age_bars)

    def test_falling_market_blocks_a_valid_dip(self):
        bars = bars_clear_rebound()
        quote = liquid_quote("NVDA", bars, rvol=3.4)
        found = diagnose_entry(
            bars,
            quote,
            now=demo_as_of(),
            **_firm(spy_state="falling"),
        )
        self.assertEqual(found["fail"], "market falling")

    def test_rank_keeps_top_n_above_threshold(self):
        from app.entry import retune

        rebound = bars_clear_rebound(100.0)
        books = {
            "NVDA": rebound,
            "AMD": bars_clear_rebound(100.0),
            "TSLA": bars_downtrend(100.0),
            "SPY": bars_firm(),
            "QQQ": bars_firm(),
            "SMH": bars_firm(),
        }
        quotes = {
            "NVDA": liquid_quote("NVDA", books["NVDA"], rvol=3.0),
            "AMD": liquid_quote("AMD", books["AMD"], rvol=2.0),
            "TSLA": liquid_quote("TSLA", books["TSLA"], rvol=2.0),
        }
        cfg = retune(top_n=1)
        screened = screen_entries(
            books,
            quotes,
            now=demo_as_of(),
            session_fraction=0.42,
            enforce_clock=False,
            cfg=cfg,
            score_symbols=["NVDA", "AMD", "TSLA"],
        )
        self.assertEqual(len(screened["signals"]), 1)
        self.assertGreaterEqual(screened["signals"][0].score, cfg.min_score)
        self.assertNotEqual(screened["signals"][0].symbol, "TSLA")

    def test_demo_board_is_selective(self):
        board = build_demo_board()
        symbols = [row["symbol"] for row in board["rows"]]
        self.assertIn("NVDA", symbols)
        self.assertNotIn("TSLA", symbols)
        self.assertNotIn("INTC", symbols)
        self.assertNotIn("SOFI", symbols)
        self.assertNotIn("PLTR", symbols)
        self.assertLessEqual(len(symbols), ENTRY.top_n)
        for row in board["rows"]:
            self.assertGreaterEqual(row["entryScore"], ENTRY.min_score)
            self.assertTrue(row["entryReasons"])
            self.assertLess(row["entryStop"], row["entryTarget"])

    def test_watch_list_stays_inside_line_cap(self):
        symbols = watch_symbols()
        self.assertLessEqual(len(symbols), ENTRY.max_subscriptions)
        self.assertIn("SPY", symbols)
        self.assertIn("QQQ", symbols)
        self.assertIn("NVDA", symbols)
        self.assertEqual(sector_etf_for("NVDA"), "SMH")
        self.assertEqual(sector_etf_for("JPM"), "XLF")

    def test_falling_context_detector(self):
        from app.entry import market_state

        self.assertEqual(market_state(bars_firm()), "firm")
        self.assertEqual(market_state(bars_falling()), "falling")


if __name__ == "__main__":
    unittest.main()
