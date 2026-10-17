"""Score the frozen cost-clearing books.

``python -m backtest.run_grid15_cost`` uses tiered IBKR commission and 2 bp
of slippage. It does not open the locked holdout unless ``c_primary`` is the
only book that clears the screen and then passes promotion-gate bars 1 and 3.
Nothing here places an order.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from backtest.data import raw_root
from backtest.grid15 import drop_top_days
from backtest.grid15_next import (
    ADOPTABLE,
    COST_BOOKS,
    BookSpec,
    cost_screen_failures,
    in_pooled,
    in_recent,
    in_validation,
    run_next,
)
from backtest.periods import HOLDOUT_START
from backtest.run_grid15_next import data_ready, load_preholdout
from backtest.spells import ACCOUNT_USD, SLIP_BPS, portfolio

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = ROOT / "research" / "grid15_cost_summary.json"
SCHEDULE = "tiered"


def _simulate(spells: list[dict[str, Any]]) -> dict[str, Any]:
    return portfolio(
        spells,
        equity=ACCOUNT_USD,
        slip_bps=SLIP_BPS,
        schedule=SCHEDULE,
        max_concurrent=4,
    )


def _positive_halves(trades: list[dict[str, Any]]) -> int:
    from backtest.grid15_next import HALVES

    count = 0
    for start, end in HALVES:
        net = sum(float(trade["net"]) for trade in trades if start <= trade["day"] <= end)
        if net > 0:
            count += 1
    return count


def _describe(spec: BookSpec, spells: list[dict[str, Any]], sessions: list[date]) -> dict[str, Any]:
    validation = [spell for spell in spells if in_validation(spell["day"])]
    sim = _simulate(validation)
    trades = sim["trades"]
    pooled = _simulate([spell for spell in spells if in_pooled(spell["day"])])
    recent = _simulate([spell for spell in spells if in_recent(spell["day"])])
    ex_top, dropped = drop_top_days(trades)
    by_day: Counter[date] = Counter(trade["day"] for trade in trades)
    histogram: Counter[int] = Counter(by_day[day] for day in sessions)
    histogram[0] = sum(1 for day in sessions if by_day[day] == 0)
    days_with = sum(1 for day in sessions if by_day[day] > 0)
    reasons: Counter[str] = Counter(trade["reason"] for trade in trades)
    symbols: Counter[str] = Counter(trade["symbol"] for trade in trades)
    months: dict[str, float] = defaultdict(float)
    month_fills: Counter[str] = Counter()
    for trade in trades:
        key = trade["day"].strftime("%Y-%m")
        months[key] += float(trade["net"])
        month_fills[key] += 1
    wins = [trade for trade in trades if float(trade["net"]) > 0]
    losses = [trade for trade in trades if float(trade["net"]) < 0]
    avg_bps = (sum(float(trade["ret"]) * 10_000.0 for trade in trades) / len(trades)) if trades else 0.0
    failures = cost_screen_failures(
        validate_net=float(sim["net"]),
        pooled_net=float(pooled["net"]),
        recent_net=float(recent["net"]),
        validate_trades=len(trades),
        positive_halves=_positive_halves(pooled["trades"]),
        ex_top5=ex_top,
        avg_bps=avg_bps,
    )
    return {
        "id": spec.name,
        "kind": spec.kind,
        "side": spec.side,
        "topK": spec.top_k,
        "investFraction": spec.invest_fraction,
        "minZ": spec.min_z,
        "minStd": spec.min_std,
        "requireEdge": spec.require_edge,
        "signals": len(validation),
        "trades": len(trades),
        "winRate": (len(wins) / len(trades)) if trades else None,
        "net": sim["net"],
        "fees": sum(float(trade["fees"]) for trade in trades),
        "avgBps": avg_bps,
        "avgWin": (sum(float(trade["net"]) for trade in wins) / len(wins)) if wins else None,
        "avgLoss": (sum(float(trade["net"]) for trade in losses) / len(losses)) if losses else None,
        "maxDrawdown": sim["maxDrawdown"],
        "exTop5": ex_top,
        "topDays": dropped,
        "fillsPerDay": (len(trades) / len(sessions)) if sessions else None,
        "daysWithFill": days_with,
        "sessions": len(sessions),
        "fillHistogram": {str(count): histogram[count] for count in sorted(histogram)},
        "reasons": dict(reasons),
        "symbols": dict(symbols),
        "pooledNet": pooled["net"],
        "pooledTrades": len(pooled["trades"]),
        "recentNet": recent["net"],
        "recentTrades": len(recent["trades"]),
        "positiveHalves": _positive_halves(pooled["trades"]),
        "screenFailures": failures,
        "screenPass": not failures,
        "adoptable": spec.name in ADOPTABLE,
        "months": [{"month": key, "fills": month_fills[key], "net": months[key]} for key in sorted(months)],
    }


def score(book: dict[tuple[str, date], list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result = run_next(book, COST_BOOKS)
    rows = [_describe(spec, result.spells[spec.name], result.sessions) for spec in COST_BOOKS]
    passes = [row["id"] for row in rows if row["screenPass"]]
    meta = {
        "schedule": SCHEDULE,
        "slipBps": SLIP_BPS,
        "accountUsd": ACCOUNT_USD,
        "sessions": len(result.sessions),
        "screenPasses": passes,
        "holdoutOpened": False,
    }
    if any(day >= HOLDOUT_START for (_symbol, day) in book):
        raise RuntimeError("cost scorer received a holdout day")
    return rows, meta


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Score the cost-clearing books. Does not trade.")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root or raw_root()
    if not data_ready(root):
        print(f"Cost-clearing books not scored. No parquet bars under {root}.", flush=True)
        return 2
    book = load_preholdout(root)
    rows, meta = score(book)
    SUMMARY_PATH.write_text(json.dumps({"meta": meta, "rows": rows}, indent=2, default=str) + "\n", encoding="utf-8")
    for row in rows:
        print(
            f"{row['id']}: fills {row['trades']} /day {row['fillsPerDay']:.2f} "
            f"win {row['winRate']} bp {row['avgBps']:.1f} net {row['net']:.0f} "
            f"exTop5 {row['exTop5']:.0f} pooled {row['pooledNet']:.0f} "
            f"days {row['daysWithFill']}/{row['sessions']} "
            f"screen {'pass' if row['screenPass'] else 'fail'}",
            flush=True,
        )
    adoptable = [row["id"] for row in rows if row["screenPass"] and row["adoptable"]]
    if len(meta["screenPasses"]) == 1 and adoptable == meta["screenPasses"]:
        from backtest.grid15_next import in_pooled as _in_pooled

        result = run_next(book, COST_BOOKS)
        spells = [spell for spell in result.spells[adoptable[0]] if _in_pooled(spell["day"])]
        verdict = _preholdout_gate(book, _simulate(spells)["trades"], adoptable[0])
        meta["gate"] = {
            "candidate": adoptable[0],
            "walkForward": verdict.bars["walk_forward"],
            "consistency": verdict.bars["consistency"],
            "freshSlice": verdict.bars["fresh_slice"],
            "reasons": verdict.reasons,
            "bootstrapP": verdict.bootstrap_p,
            "permutationP": verdict.permutation_p,
            "alpha": verdict.alpha,
            "ideasTried": verdict.ideas_tried,
        }
        SUMMARY_PATH.write_text(json.dumps({"meta": meta, "rows": rows}, indent=2, default=str) + "\n", encoding="utf-8")
        print(verdict.reason_text(), flush=True)
        if verdict.bars["walk_forward"] and verdict.bars["consistency"]:
            print(
                f"{adoptable[0]} passed the pre-holdout gate. Holdout was not loaded by this path.",
                flush=True,
            )
        else:
            print("Pre-holdout gate failed. Holdout stays closed.", flush=True)
    else:
        print("No single adoptable book cleared the frozen screen. Holdout stays closed.", flush=True)
    return 0


def _preholdout_gate(book, trades, candidate_id):
    """Bars 1 and 3 only. Does not write gate_results.csv and does not load the holdout."""
    from backtest.gate import POOLED_END, POOLED_START, ideas_tried, judge, label_regimes
    from backtest.run_gate import _calendar, _spy_closes, champion_trades
    from backtest.scan import membership_path, scan_membership

    if not membership_path().exists():
        scan_membership()
    champion = champion_trades(book, schedule=SCHEDULE)
    calendar = _calendar(book)
    regimes = label_regimes(_spy_closes(book), POOLED_START, POOLED_END)
    return judge(
        candidate_id,
        champion,
        list(trades),
        calendar=calendar,
        regimes=regimes,
        ideas_tried=ideas_tried(extra=len(COST_BOOKS)),
    )


if __name__ == "__main__":
    raise SystemExit(main())
