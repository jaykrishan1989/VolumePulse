"""Promotion gate. These tests do not read the market file or the holdout."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from backtest.gate import (
    GATE_BEGIN,
    GATE_END,
    HALF_YEARS,
    TICKER_GROUPS,
    Regime,
    bonferroni_alpha,
    ideas_tried,
    judge,
    label_regimes,
    majority_needed,
    preserve_gate_section,
    promote,
)
from backtest.areas import AREA_REGISTRY, AREAS_BEGIN, AREAS_END
from backtest.daily import DAILY_BEGIN, DAILY_END, DAILY_REGISTRY
from backtest.grid import SPECS
from backtest.hypotheses import REGISTRY
from backtest.periods import HOLDOUT_START
from backtest.run_gate import fresh_slice
from backtest.run_roundtrip import PASS1


def _weekdays(start: date, end: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = start
    while cursor <= end and len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    if len(days) < count:
        raise RuntimeError(f"needed {count} sessions in {start}..{end}")
    return days


def _calendar(per_half: int = 24) -> list[date]:
    days: list[date] = []
    for _name, start, end in HALF_YEARS:
        days.extend(_weekdays(start, end, per_half))
    return days


def _regimes(days: list[date]) -> dict[date, Regime]:
    labels = {}
    for index, day in enumerate(days):
        direction = "up" if index % 2 == 0 else "down"
        vol = "high_vol" if (index // 2) % 2 == 0 else "low_vol"
        labels[day] = Regime(direction, vol)
    return labels


def _trade(day: date, symbol: str, net: float, ret: float) -> dict:
    return {"day": day, "symbol": symbol, "net": net, "ret": ret}


def _book(days: list[date], net: float, ret: float, jackpot: dict[date, tuple[float, float]] | None = None) -> list[dict]:
    jackpot = jackpot or {}
    rows = []
    for index, day in enumerate(days):
        symbol = "AAPL" if index % 2 == 0 else "NVDA"
        trade_net, trade_ret = jackpot.get(day, (net, ret))
        rows.append(_trade(day, symbol, trade_net, trade_ret))
    return rows


def _fresh(net: float, ret: float, count: int = 20) -> list[dict]:
    start = HOLDOUT_START + timedelta(days=1)
    days = _weekdays(start, date(2026, 6, 30), count)
    return [_trade(day, "AAPL" if index % 2 == 0 else "NVDA", net, ret) for index, day in enumerate(days)]


class GateRuleTests(unittest.TestCase):
    def test_majority_and_trial_count_match_the_written_gate(self) -> None:
        self.assertEqual(len(HALF_YEARS), 6)
        self.assertEqual(len(TICKER_GROUPS), 2)
        self.assertEqual(majority_needed(12), 9)
        self.assertEqual(len(SPECS), 15)
        self.assertEqual(len(PASS1), 8)
        self.assertEqual(len(REGISTRY), 6)
        self.assertEqual(len(AREA_REGISTRY), 15)
        self.assertEqual(len(DAILY_REGISTRY), 5)
        self.assertEqual(ideas_tried(), 15 + 12 + 6 + 15 + 5)
        self.assertAlmostEqual(bonferroni_alpha(ideas_tried()), 0.05 / 53)

    def test_regime_labels_use_the_prior_close_and_a_trailing_window(self) -> None:
        closes = []
        price = 100.0
        day = date(2023, 1, 3)
        for _ in range(30):
            while day.weekday() >= 5:
                day += timedelta(days=1)
            price *= 1.01
            closes.append((day, price))
            day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        closes.append((day, price * 0.99))
        labels = label_regimes(closes, closes[0][0], closes[-1][0])
        self.assertIsNone(labels[closes[1][0]].vol)
        self.assertEqual(labels[closes[25][0]].direction, "up")
        self.assertEqual(labels[closes[-1][0]].direction, "down")
        self.assertIn(labels[closes[25][0]].vol, {"high_vol", "low_vol"})

    def test_consistent_challenger_passes_only_with_a_fresh_slice(self) -> None:
        days = _calendar()
        regimes = _regimes(days)
        champion = _book(days, net=-2.0, ret=-0.002)
        challenger = _book(days, net=2.0, ret=0.002)
        closed = judge(
            "synthetic_winner",
            champion,
            challenger,
            calendar=days,
            regimes=regimes,
            ideas_tried=1,
            n_boot=400,
        )
        self.assertFalse(closed.passed)
        self.assertEqual(closed.decision, "rejected")
        self.assertTrue(closed.bars["walk_forward"])
        self.assertTrue(closed.bars["consistency"])
        self.assertFalse(closed.bars["fresh_slice"])
        self.assertFalse(closed.fresh_evaluated)
        opened = judge(
            "synthetic_winner",
            champion,
            challenger,
            calendar=days,
            regimes=regimes,
            ideas_tried=1,
            n_boot=400,
            fresh_champion=_fresh(-2.0, -0.002),
            fresh_challenger=_fresh(2.0, 0.002),
        )
        self.assertTrue(opened.bars["fresh_slice"])
        self.assertTrue(opened.passed)
        self.assertEqual(opened.decision, "promoted")
        self.assertGreaterEqual(sum(1 for window in opened.windows if window.win), 9)

    def test_a_severe_half_year_is_rejected(self) -> None:
        days = _calendar()
        bad = {day: (-40.0, -0.04) for day in days if date(2024, 7, 1) <= day <= date(2024, 12, 31)}
        verdict = judge(
            "severe",
            _book(days, net=-1.0, ret=-0.001),
            _book(days, net=1.0, ret=0.001, jackpot=bad),
            calendar=days,
            regimes=_regimes(days),
            ideas_tried=1,
            n_boot=50,
        )
        self.assertFalse(verdict.passed)
        self.assertTrue(any(window.name == "2024H2" and window.severe for window in verdict.windows))
        self.assertTrue(any("Severe regression in 2024H2" in reason for reason in verdict.reasons))

    def test_top_five_days_cannot_carry_the_edge(self) -> None:
        days = _calendar()
        jackpot = {day: (400.0, 0.40) for day in days[:5]}
        verdict = judge(
            "handful",
            _book(days, net=-1.0, ret=-0.001),
            _book(days, net=-2.0, ret=-0.002, jackpot=jackpot),
            calendar=days,
            regimes=_regimes(days),
            ideas_tried=1,
            n_boot=50,
        )
        self.assertFalse(verdict.passed)
        self.assertTrue(any(reason.startswith("After removing the top") for reason in verdict.reasons))
        self.assertLess(verdict.trimmed_challenger_net, verdict.trimmed_champion_net)

    def test_holdout_trade_is_refused_on_the_selection_sample(self) -> None:
        days = _calendar()
        leaked = _book(days, net=1.0, ret=0.001) + [_trade(HOLDOUT_START, "AAPL", 1.0, 0.001)]
        with self.assertRaises(RuntimeError):
            judge("leaked", _book(days, net=-1.0, ret=-0.001), leaked, calendar=days, regimes=_regimes(days), ideas_tried=1, n_boot=10)

    def test_promote_refuses_a_rejection_and_keeps_the_record(self) -> None:
        days = _calendar(per_half=4)
        verdict = judge(
            "nope",
            _book(days, net=-1.0, ret=-0.001),
            _book(days, net=-2.0, ret=-0.002),
            calendar=days,
            regimes=_regimes(days),
            ideas_tried=1,
            n_boot=20,
        )
        record = {"id": "appear_disappear_midmorning", "replaced": False}
        with self.assertRaises(RuntimeError):
            promote(verdict, record)
        self.assertEqual(record["id"], "appear_disappear_midmorning")
        self.assertFalse(record["replaced"])

    def test_promote_copies_a_passed_verdict_without_editing_the_input(self) -> None:
        days = _calendar()
        verdict = judge(
            "synthetic_winner",
            _book(days, net=-2.0, ret=-0.002),
            _book(days, net=2.0, ret=0.002),
            calendar=days,
            regimes=_regimes(days),
            ideas_tried=1,
            n_boot=400,
            fresh_champion=_fresh(-2.0, -0.002),
            fresh_challenger=_fresh(2.0, 0.002),
        )
        record = {"id": "appear_disappear_midmorning", "replaced": False}
        updated = promote(verdict, record)
        self.assertEqual(updated["id"], "synthetic_winner")
        self.assertTrue(updated["replaced"])
        self.assertEqual(updated["previousId"], "appear_disappear_midmorning")
        self.assertEqual(record["id"], "appear_disappear_midmorning")
        self.assertFalse(record["replaced"])

    def test_fresh_slice_command_does_not_load_the_holdout(self) -> None:
        with self.assertRaises(RuntimeError) as raised:
            fresh_slice("nobody", [])
        self.assertIn("refusing to open the holdout", str(raised.exception))

    def test_gate_section_survives_a_rewritten_log(self) -> None:
        old = "hypothesis log\n\n" + GATE_BEGIN + "\nkept\n" + GATE_END + "\n"
        new = preserve_gate_section("# Research log\n\nbody\n", old)
        self.assertIn("kept", new)
        self.assertIn("# Research log", new)
        self.assertLess(new.index("# Research log"), new.index("kept"))

    def test_areas_section_survives_a_rewritten_log(self) -> None:
        old = (
            "hypothesis log\n\n"
            + GATE_BEGIN
            + "\ngate\n"
            + GATE_END
            + "\n"
            + AREAS_BEGIN
            + "\nareas\n"
            + AREAS_END
            + "\n"
        )
        new = preserve_gate_section("# Research log\n\nbody\n", old)
        self.assertIn("gate", new)
        self.assertIn("areas", new)
        self.assertLess(new.index("gate"), new.index("areas"))

    def test_cost_section_survives_a_rewritten_log(self) -> None:
        from backtest.costs import COSTS_BEGIN, COSTS_END

        old = "hypothesis log\n\n" + COSTS_BEGIN + "\nzero commission\n" + COSTS_END + "\n"
        new = preserve_gate_section("# Research log\n\nbody\n", old)
        self.assertIn("zero commission", new)


if __name__ == "__main__":
    unittest.main()
