"""Walk-forward test of the pre-registered hypotheses.

``python -m backtest.run_hypotheses`` never reads a holdout date. A milestone
holdout is a separate command and is refused unless that one id already passed
the walk-forward gate. Looks are appended to ``research/holdout_looks.csv``.

Adopt only when all of these are true on the live cost model (no commission, 2 bp slippage),
the hard stop, and a US$2,120 account:

- pooled net from 2023-01-01 through 2026-03-31 is positive
- net on 2024-07-01 through 2026-03-31 is positive
- net on 2025-07-01 through 2026-03-31 is positive
- pooled trades are at least 80
- at least 4 of the 6 semi-annual folds have a positive net

Nothing here places an order.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from backtest.costs import PRIMARY_SCHEDULE
from backtest.data import CANDIDATES, bars_from_frame, load_symbol, sessions
from backtest.hypotheses import REGISTRY, Hypothesis
from backtest.gate import preserve_gate_section
from backtest.periods import HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.spells import ACCOUNT_USD, SLIP_BPS, portfolio, summarize_portfolio

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
LOOKS_PATH = RESEARCH / "holdout_looks.csv"
POOLED_START = date(2023, 1, 1)
POOLED_END = date(2026, 3, 31)
RECENT_START = date(2025, 7, 1)
MIN_TRADES = 80

# Six semi-annual folds, plus a partial first quarter that stays inside the
# pre-holdout sample. The partial quarter is reported and is part of the
# recent slice. It is not one of the six folds in the "4 of 6" gate.
FOLDS: list[tuple[str, date, date]] = [
    ("2023H1", date(2023, 1, 1), date(2023, 6, 30)),
    ("2023H2", date(2023, 7, 1), date(2023, 12, 31)),
    ("2024H1", date(2024, 1, 1), date(2024, 6, 30)),
    ("2024H2", date(2024, 7, 1), date(2024, 12, 31)),
    ("2025H1", date(2025, 1, 1), date(2025, 6, 30)),
    ("2025H2", date(2025, 7, 1), date(2025, 12, 31)),
    ("2026Q1", date(2026, 1, 1), date(2026, 3, 31)),
]

PRIOR_ROWS: list[dict[str, str]] = [
    {
        "id": "bracket_baseline",
        "source": "Prior study in RESULTS.md. Exit was a 60-minute stop/target bracket, not a new theory.",
        "hypothesis": "The live Right Time to Buy score, held to its stop, target, or 60 minutes.",
        "economic_rationale": "A fresh pullback should pay if the rebound is informed. It did not, after costs.",
        "test_setup": "US$2,160 ticket, tiered commissions, 2 bp, holdout read as look 1 together with the morning filter.",
        "pooled_start": "2022-01-01",
        "pooled_end": "2026-03-31",
        "trades": "7388",
        "trades_per_day": "16.8",
        "win_rate": "0.350",
        "net_dollars": "",
        "return_pct": "",
        "avg_net_bps": "-9.43",
        "max_drawdown": "",
        "profit_factor": "0.57",
        "positive_folds": "",
        "folds": "",
        "recent_net": "",
        "validate_net": "",
        "without_stop_net": "",
        "fixed_net": "",
        "holdout_checked": "yes",
        "holdout_look": "1",
        "holdout_net": "",
        "holdout_avg_bps": "-5.89",
        "decision": "rejected",
        "reason": "Validation and the one holdout read both lost after costs. Look 1.",
    },
    {
        "id": "appear_disappear_midmorning",
        "source": "Owner rule: buy when a name appears on the list and sell when it leaves. See RESULTS.md.",
        "hypothesis": "List membership from 10:00 to 11:00 ET is a profitable round trip after costs.",
        "economic_rationale": "Appearance is the moment the pullback confirms. Disappearance is the moment that confirmation fails.",
        "test_setup": "US$2,120, tiered, 2 bp, hard stop, 12 validation trials, then one holdout read (look 2).",
        "pooled_start": "2024-07-01",
        "pooled_end": "2026-03-31",
        "trades": "628",
        "trades_per_day": "1.43",
        "win_rate": "0.309",
        "net_dollars": "-863.99",
        "return_pct": "-40.75",
        "avg_net_bps": "-10.76",
        "max_drawdown": "882.09",
        "profit_factor": "0.43",
        "positive_folds": "",
        "folds": "",
        "recent_net": "",
        "validate_net": "-863.99",
        "without_stop_net": "-862.33",
        "fixed_net": "-1555.26",
        "holdout_checked": "yes",
        "holdout_look": "2",
        "holdout_net": "-268.37",
        "holdout_avg_bps": "-8.43",
        "decision": "rejected",
        "reason": "Least-bad of 12 validation trials, still a loss. Holdout look 2 confirmed the loss. Not traded.",
    },
]


def _profit_factor(trades: list[dict[str, Any]]) -> float | None:
    wins = sum(trade["net"] for trade in trades if trade["net"] > 0)
    losses = sum(-trade["net"] for trade in trades if trade["net"] < 0)
    if losses <= 1e-9:
        return None
    return wins / losses


def _window(spells: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [spell for spell in spells if start <= spell["day"] <= end]


def _days(book: dict[tuple[str, date], list[dict[str, Any]]], symbols: list[str], start: date, end: date) -> int:
    return len({day for (symbol, day) in book if symbol in symbols and start <= day <= end})


def _run(
    spells: list[dict[str, Any]],
    days: int,
    *,
    use_stop: bool = True,
    schedule: str = PRIMARY_SCHEDULE,
) -> dict[str, Any]:
    if any(spell["day"] >= HOLDOUT_START for spell in spells):
        raise RuntimeError("walk-forward run received a holdout spell")
    result = portfolio(spells, use_stop=use_stop, schedule=schedule, equity=ACCOUNT_USD, slip_bps=SLIP_BPS)
    stats = summarize_portfolio(result, days)
    stats["profitFactor"] = _profit_factor(result["trades"])
    return stats


def decide(pooled: dict[str, Any], recent: dict[str, Any], validate: dict[str, Any], folds: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (decision, reason). Thresholds are the ones in the module docstring."""
    semi = [row for row in folds if row["fold"] != "2026Q1"]
    positive = sum(1 for row in semi if (row["net"] or 0) > 0 and (row["trades"] or 0) > 0)
    failed: list[str] = []
    if (pooled["trades"] or 0) < MIN_TRADES:
        failed.append(f"fewer than {MIN_TRADES} pooled trades")
    if (pooled["net"] or 0) <= 0:
        failed.append("pooled net is not positive after costs")
    if (validate["net"] or 0) <= 0:
        failed.append("2024-07 through 2026-03 net is not positive")
    if (recent["net"] or 0) <= 0:
        failed.append("2025-07 through 2026-03 net is not positive")
    if positive < 4:
        failed.append(f"only {positive} of 6 semi-annual folds made money")
    if failed:
        return "rejected", "; ".join(failed)
    return (
        "adopt_pending_holdout",
        f"{positive} of 6 semi-annual folds were positive and the pooled, validation, and recent nets were positive. Holdout not read.",
    )


def _num(stats: dict[str, Any], key: str, digits: int = 2) -> str:
    value = stats.get(key)
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


def _row(item: Hypothesis, pooled: dict[str, Any], recent: dict[str, Any], validate: dict[str, Any], bare: dict[str, Any], fixed: dict[str, Any], folds: list[dict[str, Any]], decision: str, reason: str) -> dict[str, str]:
    semi = [fold for fold in folds if fold["fold"] != "2026Q1"]
    positive = sum(1 for fold in semi if (fold["net"] or 0) > 0 and (fold["trades"] or 0) > 0)
    return {
        "id": item.id,
        "source": item.source,
        "hypothesis": item.hypothesis,
        "economic_rationale": item.rationale,
        "test_setup": item.setup,
        "pooled_start": POOLED_START.isoformat(),
        "pooled_end": POOLED_END.isoformat(),
        "trades": str(pooled["trades"]),
        "trades_per_day": _num(pooled, "tradesPerDay"),
        "win_rate": _num(pooled, "winRate", 4),
        "net_dollars": _num(pooled, "net"),
        "return_pct": _num(pooled, "returnPct"),
        "avg_net_bps": _num(pooled, "avgNetBps"),
        "max_drawdown": _num(pooled, "maxDrawdown"),
        "profit_factor": _num(pooled, "profitFactor"),
        "positive_folds": str(positive),
        "folds": str(len(semi)),
        "recent_net": _num(recent, "net"),
        "validate_net": _num(validate, "net"),
        "without_stop_net": _num(bare, "net"),
        "fixed_net": _num(fixed, "net"),
        "holdout_checked": "no",
        "holdout_look": "",
        "holdout_net": "",
        "holdout_avg_bps": "",
        "decision": decision,
        "reason": reason,
    }


def _decision_line(decision: str, reason: str) -> str:
    label = "Rejected" if decision == "rejected" else "Pending a holdout milestone"
    text = reason[:1].upper() + reason[1:] if reason else ""
    return f"{label}. {text}"


def _ensure_looks() -> None:
    """Record the two reads that already happened. A normal run does not add one."""
    if LOOKS_PATH.exists():
        return
    with LOOKS_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["look", "date", "rules", "note"])
        writer.writeheader()
        writer.writerows(
            [
                {
                    "look": "1",
                    "date": "2026-09-28",
                    "rules": "bracket baseline and morning filter",
                    "note": "Read together after the bracket validation pick. Baseline holdout -5.9 bp. Morning holdout -1.7 bp.",
                },
                {
                    "look": "2",
                    "date": "2026-09-28",
                    "rules": "appear-disappear midmorning",
                    "note": "One frozen spec after 12 validation trials. Holdout portfolio -$268 (-12.7%).",
                },
            ]
        )


def _money(stats: dict[str, Any]) -> str:
    net = stats.get("net")
    ret = stats.get("returnPct")
    trades = stats.get("trades")
    win = stats.get("winRate")
    bps = stats.get("avgNetBps")
    dd = stats.get("maxDrawdown")
    per_day = stats.get("tradesPerDay")
    if not trades:
        return "no trades"
    win_txt = "n/a" if win is None else f"{win * 100:.1f}%"
    bps_txt = "n/a" if bps is None else f"{bps:.1f} bp"
    return (
        f"{trades} trades, {per_day:.2f}/session, win {win_txt}, "
        f"net ${net:.0f} ({ret:.1f}%), avg {bps_txt}, max drawdown ${dd:.0f}"
    )


def _markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Research log",
        "",
        "One entry per theory. The walk-forward window ends on 2026-03-31. "
        "The holdout from 2026-04-01 is not used to choose among these ideas.",
        "",
        "Holdout looks so far: **2**. Look 1 was the 60-minute bracket (baseline and the morning filter). "
        "Look 2 was the appear-to-disappear rule frozen at 10:00–11:00 ET. "
        "This batch did not open the holdout. The next look is allowed only as a milestone for a single "
        "rule that has already passed the walk-forward gate, and it has to be recorded in `holdout_looks.csv`.",
        "",
        "Costs on every new row: US$2,120, whole shares, concurrent while cash remains, tiered IBKR commissions "
        "(US$0.35 minimum per side) unless a row says fixed, 2 bp slippage each side, flat by 15:55 ET. "
        "The decision column uses the hard stop. The no-stop and fixed-commission nets are reported beside it "
        "and are not a second search.",
        "",
        "How to add a hypothesis: write a generator in `backtest/hypotheses.py`, append a `Hypothesis` to "
        "`REGISTRY` with the source, the economic rationale, and the frozen setup, then run "
        "`python -m backtest.run_hypotheses`. Do not change a threshold after reading the result. "
        "Do not pass `--milestone` unless that one id has decision `adopt_pending_holdout`.",
        "",
        "## Already tested",
        "",
        "### bracket_baseline",
        "",
        "The 60-minute stop/target bracket on the live score. Validation average was −9.4 bp. "
        "Holdout look 1 was −5.9 bp per trade. Rejected. Full table in `RESULTS.md`.",
        "",
        "### appear_disappear_midmorning",
        "",
        "Buy the next open after a name appears, sell the next open after it leaves, 10:00–11:00 ET. "
        "Validation portfolio −$864 (−40.8%). Holdout look 2 was −$268 (−12.7%, −8.4 bp) on 191 trades. "
        "Rejected as a trade. The tab still emits the signal so it can be confirmed by hand, with that loss on the card.",
        "",
    ]
    for row in rows:
        item: Hypothesis = row["item"]
        lines.extend(
            [
                f"## {item.id}",
                "",
                f"**Source.** {item.source}",
                "",
                f"**Hypothesis.** {item.hypothesis}",
                "",
                f"**Economic rationale.** {item.rationale}",
                "",
                f"**Test setup.** {item.setup}",
                "",
                f"**Walk-forward, with stop.** Pooled 2023-01-01 to 2026-03-31: {_money(row['pooled'])}. "
                f"Validation window 2024-07-01 to 2026-03-31: {_money(row['validate'])}. "
                f"Most recent slice 2025-07-01 to 2026-03-31: {_money(row['recent'])}.",
                "",
                "Semi-annual folds, same costs:",
                "",
                "| Fold | Trades | Win | Net | Return | Avg | Max DD |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for fold in row["folds"]:
            if not fold["trades"]:
                lines.append(f"| {fold['fold']} | 0 |  | $0 |  |  |  |")
                continue
            win = fold["winRate"]
            win_txt = "n/a" if win is None else f"{win * 100:.1f}%"
            bps = fold["avgNetBps"]
            bps_txt = "n/a" if bps is None else f"{bps:.1f} bp"
            lines.append(
                f"| {fold['fold']} | {fold['trades']} | {win_txt} | ${fold['net']:.0f} | "
                f"{fold['returnPct']:.1f}% | {bps_txt} | ${fold['maxDrawdown']:.0f} |"
            )
        lines.extend(
            [
                "",
                f"**Without the stop.** {_money(row['bare'])}.",
                "",
                f"**Fixed US$1 minimum, with stop.** {_money(row['fixed'])}.",
                "",
                "**Holdout.** Not checked in this batch.",
                "",
                f"**Decision.** {_decision_line(row['decision'], row['reason'])}",
                "",
            ]
        )
    lines.extend(
        [
            "## Not tested yet",
            "",
            "These stay queued because the bars on hand cannot support them, or because this batch already had six frozen tests.",
            "",
            "- Same clock-time continuation from Heston, Korajczyk, and Sadka: yesterday's return at a given half hour predicts today's return at that half hour. Needs a wider cross-section than eight names to match their sort.",
            "- Order-flow imbalance and signed volume. These files are five-minute OHLC, not aggressor prints, so a flow hypothesis would be invented rather than measured.",
            "- A short book. The account is a small Canadian cash account and the prior brief kept it long-only.",
            "",
        ]
    )
    return "\n".join(lines)


def load_book(include_holdout: bool = False) -> dict[tuple[str, date], list[dict[str, Any]]]:
    """Load stored 5-minute bars. The holdout stays out unless a caller opts in.

    The default is the pre-holdout book. ``include_holdout=True`` is only for
    the one daily-frequency finalist read. It does not connect to IBKR.
    """
    book: dict[tuple[str, date], list[dict[str, Any]]] = {}
    for symbol in list(CANDIDATES) + ["SPY"]:
        print(f"loading {symbol}", flush=True)
        for day, frame in sessions(load_symbol(symbol)):
            if day >= HOLDOUT_START and not include_holdout:
                continue
            book[(symbol, day)] = bars_from_frame(frame)
    if not include_holdout and any(day >= HOLDOUT_START for (_symbol, day) in book):
        raise RuntimeError("holdout day remained after the load filter")
    return book


def run_registry(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for item in REGISTRY:
        print(f"hypothesis {item.id}", flush=True)
        spells = [spell for spell in item.spells(book) if spell["day"] >= POOLED_START]
        if any(spell["day"] >= HOLDOUT_START for spell in spells):
            raise RuntimeError(f"{item.id} produced a holdout spell")
        fold_stats = []
        for name, start, end in FOLDS:
            stats = _run(spells and _window(spells, start, end), _days(book, item.symbols, start, end))
            fold_stats.append({"fold": name, **stats})
        pooled = _run(_window(spells, POOLED_START, POOLED_END), _days(book, item.symbols, POOLED_START, POOLED_END))
        recent = _run(_window(spells, RECENT_START, POOLED_END), _days(book, item.symbols, RECENT_START, POOLED_END))
        validate = _run(
            _window(spells, VALIDATE_START, VALIDATE_END),
            _days(book, item.symbols, VALIDATE_START, VALIDATE_END),
        )
        bare = _run(
            _window(spells, POOLED_START, POOLED_END),
            _days(book, item.symbols, POOLED_START, POOLED_END),
            use_stop=False,
        )
        fixed = _run(
            _window(spells, POOLED_START, POOLED_END),
            _days(book, item.symbols, POOLED_START, POOLED_END),
            schedule="fixed",
        )
        decision, reason = decide(pooled, recent, validate, fold_stats)
        print(f"  {decision}: pooled net {pooled['net']:.0f} trades {pooled['trades']}", flush=True)
        rows.append(
            {
                "item": item,
                "pooled": pooled,
                "recent": recent,
                "validate": validate,
                "bare": bare,
                "fixed": fixed,
                "folds": fold_stats,
                "decision": decision,
                "reason": reason,
                "csv": _row(item, pooled, recent, validate, bare, fixed, fold_stats, decision, reason),
            }
        )
    return rows


def _write_outputs(rows: list[dict[str, Any]]) -> None:
    RESEARCH.mkdir(parents=True, exist_ok=True)
    fieldnames = list(PRIOR_ROWS[0].keys())
    csv_rows = list(PRIOR_ROWS) + [row["csv"] for row in rows]
    with (RESEARCH / "hypotheses.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)
    with (RESEARCH / "fold_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "fold", "trades", "win_rate", "net_dollars", "return_pct", "avg_net_bps", "max_drawdown", "trades_per_day"],
        )
        writer.writeheader()
        for row in rows:
            for fold in row["folds"]:
                writer.writerow(
                    {
                        "id": row["item"].id,
                        "fold": fold["fold"],
                        "trades": fold["trades"],
                        "win_rate": "" if fold["winRate"] is None else f"{fold['winRate']:.4f}",
                        "net_dollars": f"{fold['net']:.2f}",
                        "return_pct": "" if not fold["trades"] else f"{fold['returnPct']:.2f}",
                        "avg_net_bps": "" if fold["avgNetBps"] is None else f"{fold['avgNetBps']:.2f}",
                        "max_drawdown": f"{fold['maxDrawdown']:.2f}",
                        "trades_per_day": "" if fold["tradesPerDay"] is None else f"{fold['tradesPerDay']:.2f}",
                    }
                )
    log_path = RESEARCH / "RESEARCH_LOG.md"
    previous = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    log_path.write_text(preserve_gate_section(_markdown(rows), previous), encoding="utf-8")
    summary = {
        "holdoutLooksBeforeThisBatch": 2,
        "holdoutReadThisBatch": False,
        "accountUsd": ACCOUNT_USD,
        "slipBps": SLIP_BPS,
        "hypotheses": [
            {"id": row["item"].id, "decision": row["decision"], "pooledNet": row["pooled"]["net"], "trades": row["pooled"]["trades"]}
            for row in rows
        ],
    }
    (RESEARCH / "hypothesis_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def milestone(hypothesis_id: str) -> None:
    """One holdout read for a rule that already passed the walk-forward gate.

    Not called by the default command. Each call appends a look.
    """
    raise RuntimeError(
        f"Holdout milestone for {hypothesis_id} is a separate step. "
        "This batch has no adopted rule, so the command refuses to open the holdout."
    )


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--milestone":
        milestone(sys.argv[2] if len(sys.argv) > 2 else "")
        return
    if any(arg.startswith("--milestone") for arg in sys.argv):
        raise SystemExit("refusing a holdout read from an unknown flag")
    book = load_book()
    rows = run_registry(book)
    _ensure_looks()
    _write_outputs(rows)
    adopted = [row["item"].id for row in rows if row["decision"] == "adopt_pending_holdout"]
    print(f"wrote {RESEARCH / 'RESEARCH_LOG.md'}", flush=True)
    print(f"adopted pending holdout: {adopted or 'none'}", flush=True)


if __name__ == "__main__":
    main()
