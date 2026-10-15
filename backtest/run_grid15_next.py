"""Score the frozen exit books and the daily top-k books.

``python -m backtest.run_grid15_next`` does not open the locked holdout.
The screen in ``grid15_next.screen_failures`` was frozen before the fill.
Two books clearing it would still leave the holdout shut. Nothing here
places an order.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from backtest.data import bars_from_frame, load_symbol, raw_root, sessions
from backtest.grid15 import drop_top_days
from backtest.grid15_next import (
    BOOKS,
    RANK_SYMBOLS,
    BookSpec,
    in_pooled,
    in_recent,
    in_validation,
    run_next,
    screen_failures,
)
from backtest.periods import HOLDOUT_START
from backtest.spells import ACCOUNT_USD, SLIP_BPS, portfolio

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
SUMMARY_PATH = RESEARCH / "grid15_next_summary.json"
SCHEDULE = "tiered"


def data_ready(root: Path | None = None) -> bool:
    folder = root or raw_root()
    return all((folder / symbol).is_dir() and any((folder / symbol).glob("*.parquet")) for symbol in RANK_SYMBOLS)


def missing_message(root: Path) -> str:
    return f"Next 15-minute batch not scored. No parquet bars under {root}."


def load_preholdout(root: Path | None = None) -> dict[tuple[str, date], list[dict[str, Any]]]:
    book: dict[tuple[str, date], list[dict[str, Any]]] = {}
    for symbol in RANK_SYMBOLS:
        print(f"loading {symbol}", flush=True)
        for day, frame in sessions(load_symbol(symbol, root)):
            if day >= HOLDOUT_START:
                continue
            book[(symbol, day)] = bars_from_frame(frame)
    if any(day >= HOLDOUT_START for (_symbol, day) in book):
        raise RuntimeError("holdout day remained after the load filter")
    return book


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
    # Sessions with no fill are missing from by_day. Count them.
    histogram[0] = sum(1 for day in sessions if by_day[day] == 0)
    days_with = sum(1 for day in sessions if by_day[day] > 0)
    reasons: Counter[str] = Counter(trade["reason"] for trade in trades)
    months: dict[str, float] = defaultdict(float)
    month_fills: Counter[str] = Counter()
    for trade in trades:
        key = trade["day"].strftime("%Y-%m")
        months[key] += float(trade["net"])
        month_fills[key] += 1
    wins = [trade for trade in trades if float(trade["net"]) > 0]
    losses = [trade for trade in trades if float(trade["net"]) < 0]
    failures = screen_failures(
        validate_net=float(sim["net"]),
        pooled_net=float(pooled["net"]),
        recent_net=float(recent["net"]),
        validate_trades=len(trades),
        positive_halves=_positive_halves(pooled["trades"]),
        ex_top5=ex_top,
        days_with_fill=days_with,
        sessions=len(sessions),
    )
    return {
        "id": spec.name,
        "kind": spec.kind,
        "exit": spec.exit,
        "side": spec.side,
        "regime": spec.regime,
        "signals": len(validation),
        "trades": len(trades),
        "winRate": (len(wins) / len(trades)) if trades else None,
        "net": sim["net"],
        "fees": sum(float(trade["fees"]) for trade in trades),
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
        "pooledNet": pooled["net"],
        "pooledTrades": len(pooled["trades"]),
        "recentNet": recent["net"],
        "recentTrades": len(recent["trades"]),
        "positiveHalves": _positive_halves(pooled["trades"]),
        "screenFailures": failures,
        "screenPass": not failures,
        "months": [{"month": key, "fills": month_fills[key], "net": months[key]} for key in sorted(months)],
    }


def score(book: dict[tuple[str, date], list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result = run_next(book)
    rows = []
    for spec in BOOKS:
        rows.append(_describe(spec, result.spells[spec.name], result.sessions))
    passes = [row["id"] for row in rows if row["screenPass"]]
    meta = {
        "schedule": SCHEDULE,
        "slipBps": SLIP_BPS,
        "accountUsd": ACCOUNT_USD,
        "sessions": len(result.sessions),
        "screenPasses": passes,
        "holdoutOpened": False,
    }
    return rows, meta


def write_outputs(rows: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    SUMMARY_PATH.write_text(json.dumps({"meta": meta, "rows": rows}, indent=2, default=str) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Score the next 15-minute batch. Does not trade.")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root or raw_root()
    if not data_ready(root):
        print(missing_message(root), flush=True)
        return 2
    book = load_preholdout(root)
    rows, meta = score(book)
    write_outputs(rows, meta)
    for row in rows:
        print(
            f"{row['id']}: fills {row['trades']} /day {row['fillsPerDay']:.2f} "
            f"win {row['winRate']} net {row['net']:.0f} exTop5 {row['exTop5']:.0f} "
            f"pooled {row['pooledNet']:.0f} days {row['daysWithFill']}/{row['sessions']} "
            f"screen {'pass' if row['screenPass'] else 'fail'}",
            flush=True,
        )
    if len(meta["screenPasses"]) == 1:
        print(
            f"{meta['screenPasses'][0]} cleared the frozen screen. "
            "The promotion gate was not run in this command, and the holdout was not loaded.",
            flush=True,
        )
    else:
        print("No single book cleared the frozen screen. Holdout stays closed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
