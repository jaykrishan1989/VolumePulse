"""Score the frozen FOMC-morning report.

``python -m backtest.run_economic`` uses tiered IBKR commission and 2 bp of
slippage. ``e_fomc`` and ``e_morning`` are a report. Neither is adoptable.
The locked holdout is not loaded. Nothing here places an order.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from backtest.data import raw_root
from backtest.economic import ADOPTABLE, BOOK_NAMES, generate, may_open_holdout
from backtest.grid15 import drop_top_days
from backtest.grid15_next import HALVES, in_pooled, in_recent, in_validation
from backtest.periods import HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.run_grid15_next import data_ready, load_preholdout
from backtest.session_edge import clears_published_milestone, screen_failures
from backtest.spells import ACCOUNT_USD, SLIP_BPS, portfolio

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = ROOT / "research" / "economic_summary.json"
SCHEDULE = "tiered"


def _simulate(spells: list[dict[str, Any]]) -> dict[str, Any]:
    return portfolio(spells, equity=ACCOUNT_USD, slip_bps=SLIP_BPS, schedule=SCHEDULE, max_concurrent=1)


def _positive_halves(trades: list[dict[str, Any]]) -> int:
    count = 0
    for start, end in HALVES:
        net = sum(float(trade["net"]) for trade in trades if start <= trade["day"] <= end)
        if net > 0:
            count += 1
    return count


def _describe(name: str, spells: list[dict[str, Any]], sessions: list[date]) -> dict[str, Any]:
    validation = [spell for spell in spells if in_validation(spell["day"])]
    sim = _simulate(validation)
    trades = sim["trades"]
    pooled = _simulate([spell for spell in spells if in_pooled(spell["day"])])
    recent = _simulate([spell for spell in spells if in_recent(spell["day"])])
    ex_top, dropped = drop_top_days(trades)
    by_day: Counter[date] = Counter(trade["day"] for trade in trades)
    days_with = sum(1 for day in sessions if by_day[day] > 0)
    day_share = (days_with / len(sessions)) if sessions else 0.0
    reasons: Counter[str] = Counter(trade["reason"] for trade in trades)
    wins = [trade for trade in trades if float(trade["net"]) > 0]
    losses = [trade for trade in trades if float(trade["net"]) < 0]
    avg_bps = (sum(float(trade["ret"]) * 10_000.0 for trade in trades) / len(trades)) if trades else 0.0
    gross_bps = (
        sum(float(trade["gross"]) / float(trade["notional"]) * 10_000.0 for trade in trades if trade["notional"]) / len(trades)
        if trades
        else 0.0
    )
    notionals = [float(trade["notional"]) for trade in trades]
    fees = sum(float(trade["fees"]) for trade in trades)
    failures = screen_failures(
        validate_net=float(sim["net"]),
        pooled_net=float(pooled["net"]),
        recent_net=float(recent["net"]),
        validate_trades=len(trades),
        positive_halves=_positive_halves(pooled["trades"]),
        ex_top5=ex_top,
        avg_bps=avg_bps,
        day_share=day_share,
    )
    months: dict[str, float] = defaultdict(float)
    month_fills: Counter[str] = Counter()
    for trade in trades:
        key = trade["day"].strftime("%Y-%m")
        months[key] += float(trade["net"])
        month_fills[key] += 1
    return {
        "id": name,
        "signals": len(validation),
        "trades": len(trades),
        "winRate": (len(wins) / len(trades)) if trades else None,
        "net": sim["net"],
        "fees": fees,
        "preCommission": float(sim["net"]) + fees,
        "avgBps": avg_bps,
        "avgGrossBps": gross_bps,
        "avgNotional": (sum(notionals) / len(notionals)) if notionals else None,
        "avgWin": (sum(float(trade["net"]) for trade in wins) / len(wins)) if wins else None,
        "avgLoss": (sum(float(trade["net"]) for trade in losses) / len(losses)) if losses else None,
        "maxDrawdown": sim["maxDrawdown"],
        "exTop5": ex_top,
        "topDays": dropped,
        "fillsPerDay": (len(trades) / len(sessions)) if sessions else None,
        "daysWithFill": days_with,
        "sessions": len(sessions),
        "dayShare": day_share,
        "reasons": dict(reasons),
        "pooledNet": pooled["net"],
        "pooledTrades": len(pooled["trades"]),
        "pooledBps": (
            sum(float(trade["ret"]) * 10_000.0 for trade in pooled["trades"]) / len(pooled["trades"])
            if pooled["trades"]
            else None
        ),
        "recentNet": recent["net"],
        "recentTrades": len(recent["trades"]),
        "positiveHalves": _positive_halves(pooled["trades"]),
        "independentMonths": len(months),
        "screenFailures": failures,
        "screenPass": not failures,
        "adoptable": name in ADOPTABLE,
        "milestone": clears_published_milestone(float(sim["net"]), ex_top, len(trades)),
        "days": [trade["day"].isoformat() for trade in trades],
        "months": [{"month": key, "fills": month_fills[key], "net": months[key]} for key in sorted(months)],
    }


def score(book: dict[tuple[str, date], list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if any(day >= HOLDOUT_START for (_symbol, day) in book):
        raise RuntimeError("economic scorer received a holdout day")
    result = generate(book)
    sessions = sorted(day for (symbol, day) in book if symbol == "SPY" and VALIDATE_START <= day <= VALIDATE_END)
    rows = [_describe(name, result.spells[name], sessions) for name in BOOK_NAMES]
    by_id = {row["id"]: row for row in rows}
    gap = None
    if by_id["e_fomc"]["trades"] and by_id["e_morning"]["trades"]:
        gap = float(by_id["e_fomc"]["avgBps"]) - float(by_id["e_morning"]["avgBps"])
    meta = {
        "schedule": SCHEDULE,
        "slipBps": SLIP_BPS,
        "accountUsd": ACCOUNT_USD,
        "sessions": len(sessions),
        "adoptable": sorted(ADOPTABLE),
        "fomcMinusMorningBps": gap,
        "screenPasses": [row["id"] for row in rows if row["screenPass"]],
        "holdoutOpened": False,
        "estimatedThreshold": False,
    }
    meta["mayOpenHoldout"] = may_open_holdout(rows)
    return rows, meta


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Score the frozen FOMC-morning report. Does not trade.")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root or raw_root()
    if not data_ready(root):
        print(f"Economic report not scored. No parquet bars under {root}.", flush=True)
        return 2
    book = load_preholdout(root)
    rows, meta = score(book)
    if meta["mayOpenHoldout"] or meta["holdoutOpened"]:
        raise RuntimeError("economic report tried to open the holdout")
    SUMMARY_PATH.write_text(json.dumps({"meta": meta, "rows": rows}, indent=2, default=str) + "\n", encoding="utf-8")
    for row in rows:
        print(
            f"{row['id']}: fills {row['trades']} /day {row['fillsPerDay']:.2f} "
            f"win {row['winRate']} bp {row['avgBps']:.1f} grossBp {row['avgGrossBps']:.1f} "
            f"net {row['net']:.0f} pre {row['preCommission']:.0f} "
            f"pooled {row['pooledNet']:.0f} screen {'pass' if row['screenPass'] else 'fail'} "
            f"adoptable {row['adoptable']}",
            flush=True,
        )
    print(f"fomc minus morning, net bp: {meta['fomcMinusMorningBps']}", flush=True)
    print("Report only. No adoptable book. Holdout stays closed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
