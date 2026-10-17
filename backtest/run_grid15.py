"""Score the frozen 15-minute books on validation only.

``python -m backtest.run_grid15`` does not open the locked holdout. Only
``pro_aplus`` is allowed to clear the milestone, and this command still does
not load the holdout when it does. Nothing here places an order.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from backtest.data import CANDIDATES, bars_from_frame, load_symbol, raw_root, sessions
from backtest.grid15 import (
    BOOKS,
    DAILY_LOSS,
    PRIMARY,
    PUBLISHED_MODEL_VALIDATION_NET,
    drop_top_days,
    is_milestone,
    run_grid,
    simulate_shorts,
)
from backtest.periods import HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.spells import ACCOUNT_USD, SLIP_BPS, portfolio

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
SUMMARY_PATH = RESEARCH / "grid15_summary.json"
MONTHS_PATH = RESEARCH / "grid15_months.csv"
LOG_PATH = RESEARCH / "RESEARCH_LOG.md"
BEGIN = "<!-- GRID15_BEGIN -->"
END = "<!-- GRID15_END -->"


def data_ready(root: Path | None = None) -> bool:
    folder = root or raw_root()
    needed = list(CANDIDATES) + ["SPY", "QQQ"]
    return all((folder / symbol).is_dir() and any((folder / symbol).glob("*.parquet")) for symbol in needed)


def missing_message(root: Path) -> str:
    return f"15-minute grid not scored. No parquet bars under {root}."


def load_preholdout(root: Path | None = None) -> dict[tuple[str, date], list[dict[str, Any]]]:
    book: dict[tuple[str, date], list[dict[str, Any]]] = {}
    for symbol in list(CANDIDATES) + ["SPY", "QQQ"]:
        print(f"loading {symbol}", flush=True)
        for day, frame in sessions(load_symbol(symbol, root)):
            if day >= HOLDOUT_START:
                continue
            book[(symbol, day)] = bars_from_frame(frame)
    if any(day >= HOLDOUT_START for (_symbol, day) in book):
        raise RuntimeError("holdout day remained after the load filter")
    return book


def _stats(trades: list[dict[str, Any]], sessions: list[date], drawdown: float) -> dict[str, Any]:
    n = len(trades)
    wins = [trade for trade in trades if float(trade["net"]) > 0]
    losses = [trade for trade in trades if float(trade["net"]) < 0]
    net = sum(float(trade["net"]) for trade in trades)
    ex_top, dropped = drop_top_days(trades)
    by_day: Counter[date] = Counter()
    for trade in trades:
        by_day[trade["day"]] += 1
    histogram: Counter[int] = Counter()
    for day in sessions:
        histogram[by_day[day]] += 1
    entries = {(trade["symbol"], trade["day"], trade["entry_t"]) for trade in trades}
    by_entry: Counter[date] = Counter()
    for _symbol, day, _stamp in entries:
        by_entry[day] += 1
    entry_hist: Counter[int] = Counter()
    for day in sessions:
        entry_hist[by_entry[day]] += 1
    months: dict[str, float] = defaultdict(float)
    month_fills: Counter[str] = Counter()
    month_wins: Counter[str] = Counter()
    for trade in trades:
        key = trade["day"].strftime("%Y-%m")
        months[key] += float(trade["net"])
        month_fills[key] += 1
        if float(trade["net"]) > 0:
            month_wins[key] += 1
    return {
        "trades": n,
        "entries": len(entries),
        "winRate": (len(wins) / n) if n else None,
        "net": net,
        "avgWin": (sum(float(trade["net"]) for trade in wins) / len(wins)) if wins else None,
        "avgLoss": (sum(float(trade["net"]) for trade in losses) / len(losses)) if losses else None,
        "maxDrawdown": drawdown,
        "exTop5": ex_top,
        "topDays": dropped,
        "fillsPerDay": (n / len(sessions)) if sessions else None,
        "entriesPerDay": (len(entries) / len(sessions)) if sessions else None,
        "fillHistogram": {str(count): histogram[count] for count in sorted(histogram)},
        "entryHistogram": {str(count): entry_hist[count] for count in sorted(entry_hist)},
        "months": [
            {
                "month": key,
                "fills": month_fills[key],
                "winRate": (month_wins[key] / month_fills[key]) if month_fills[key] else None,
                "net": months[key],
            }
            for key in sorted(months)
        ],
    }


def score(book: dict[tuple[str, date], list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grid = run_grid(book)
    rows = []
    for spec in BOOKS:
        spells = grid.spells[spec.name]
        if spec.kind == "short":
            sim = simulate_shorts(spells, equity=ACCOUNT_USD, slip_bps=SLIP_BPS)
        else:
            sim = portfolio(
                spells,
                equity=ACCOUNT_USD,
                slip_bps=SLIP_BPS,
                schedule="zero",
                daily_loss_fraction=DAILY_LOSS,
                max_concurrent=8,
            )
        stats = _stats(sim["trades"], grid.sessions, float(sim["maxDrawdown"]))
        stats.update(
            {
                "id": spec.name,
                "kind": spec.kind,
                "adoptable": spec.adoptable,
                "candidates": grid.candidates[spec.name],
                "vetoes": dict(grid.vetoes[spec.name]),
                "milestone": bool(
                    spec.adoptable and is_milestone(float(stats["net"]), float(stats["exTop5"]), int(stats["trades"]))
                ),
            }
        )
        rows.append(stats)
    meta = {
        "evaluations": grid.evaluations,
        "sessions": len(grid.sessions),
        "slots": 26,
        "publishedNet": PUBLISHED_MODEL_VALIDATION_NET,
        "accountUsd": ACCOUNT_USD,
        "slipBps": SLIP_BPS,
        "window": [VALIDATE_START.isoformat(), VALIDATE_END.isoformat()],
    }
    return rows, meta


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.0f}" if abs(value) >= 10 else f"${value:,.2f}"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{100.0 * value:.1f}%"


def write_outputs(rows: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    SUMMARY_PATH.write_text(json.dumps({"meta": meta, "rows": rows}, indent=2, default=str) + "\n", encoding="utf-8")
    with MONTHS_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "month", "fills", "winRate", "net"])
        writer.writeheader()
        for row in rows:
            for month in row["months"]:
                writer.writerow({"id": row["id"], **month})


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Score the 15-minute grid on validation only. Does not trade.")
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
            f"{row['id']}: fills {row['trades']} entries {row['entries']} "
            f"win {_pct(row['winRate'])} net {_money(row['net'])} exTop5 {_money(row['exTop5'])} "
            f"dd {_money(row['maxDrawdown'])}",
            flush=True,
        )
    primary = next(row for row in rows if row["id"] == PRIMARY)
    if primary["milestone"]:
        print(f"{PRIMARY} cleared the validation bar. This command did not load the holdout.", flush=True)
    else:
        print(f"{PRIMARY} did not clear the validation bar. Holdout stays closed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
