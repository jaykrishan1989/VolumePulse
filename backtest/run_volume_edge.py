"""Score the frozen same-minute volume books.

``python -m backtest.run_volume_edge`` uses tiered IBKR commission and 2 bp
of slippage. It does not open the locked holdout unless ``u_primary`` is the
only book that clears the screen, its validation net beats the published
model, and it then passes promotion-gate bars 1 and 3. Nothing here places
an order.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from backtest.data import raw_root
from backtest.grid15 import drop_top_days
from backtest.grid15_next import HALVES, in_pooled, in_recent, in_validation
from backtest.periods import HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.run_grid15_next import data_ready, load_preholdout
from backtest.spells import ACCOUNT_USD, SLIP_BPS, portfolio
from backtest.volume_edge import (
    ADOPTABLE,
    BOOK_NAMES,
    SHOCK_RETURN,
    clears_published_milestone,
    generate,
    screen_failures,
)

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = ROOT / "research" / "volume_edge_summary.json"
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
    symbols: Counter[str] = Counter(trade["symbol"] for trade in trades)
    wins = [trade for trade in trades if float(trade["net"]) > 0]
    losses = [trade for trade in trades if float(trade["net"]) < 0]
    avg_bps = (sum(float(trade["ret"]) * 10_000.0 for trade in trades) / len(trades)) if trades else 0.0
    notionals = [float(trade["notional"]) for trade in trades]
    shock_overlap = (
        sum(1 for spell in validation if float(spell.get("signal_return") or 0.0) >= SHOCK_RETURN - 1e-12) / len(validation)
        if validation
        else None
    )
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
        "fees": sum(float(trade["fees"]) for trade in trades),
        "avgBps": avg_bps,
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
        "symbols": dict(symbols),
        "medianSignalRvol": _median(float(spell["signal_rvol"]) for spell in validation),
        "shockOverlap": shock_overlap,
        "pooledNet": pooled["net"],
        "pooledTrades": len(pooled["trades"]),
        "recentNet": recent["net"],
        "recentTrades": len(recent["trades"]),
        "positiveHalves": _positive_halves(pooled["trades"]),
        "screenFailures": failures,
        "screenPass": not failures,
        "adoptable": name in ADOPTABLE,
        "milestone": clears_published_milestone(float(sim["net"]), ex_top, len(trades)),
        "months": [{"month": key, "fills": month_fills[key], "net": months[key]} for key in sorted(months)],
    }


def _median(values) -> float | None:
    rows = sorted(values)
    if not rows:
        return None
    return rows[len(rows) // 2]


def _coverage_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    kept = [row for row in rows if in_validation(row["day"])]
    if not kept:
        return {"days": 0}
    n = len(kept)
    return {
        "days": n,
        "shareLoudUp": sum(1 for row in kept if row["up"]) / n,
        "shareLoudDown": sum(1 for row in kept if row["down"]) / n,
        "shareQuietUp": sum(1 for row in kept if row["quiet"]) / n,
    }


def score(book: dict[tuple[str, date], list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if any(day >= HOLDOUT_START for (_symbol, day) in book):
        raise RuntimeError("volume-edge scorer received a holdout day")
    result = generate(book)
    sessions = sorted(day for (symbol, day) in book if symbol == "SPY" and VALIDATE_START <= day <= VALIDATE_END)
    rows = [_describe(name, result.spells[name], sessions) for name in BOOK_NAMES]
    meta = {
        "schedule": SCHEDULE,
        "slipBps": SLIP_BPS,
        "accountUsd": ACCOUNT_USD,
        "sessions": len(sessions),
        "screenPasses": [row["id"] for row in rows if row["screenPass"]],
        "holdoutOpened": False,
        "coverage": _coverage_report(result.days),
    }
    return rows, meta


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Score the same-minute volume books. Does not trade.")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root or raw_root()
    if not data_ready(root):
        print(f"Volume books not scored. No parquet bars under {root}.", flush=True)
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
    print(f"coverage: {meta['coverage']}", flush=True)
    adoptable = [row for row in rows if row["screenPass"] and row["adoptable"]]
    if len(meta["screenPasses"]) == 1 and len(adoptable) == 1 and adoptable[0]["milestone"]:
        from backtest.gate import POOLED_END, POOLED_START, ideas_tried, judge, label_regimes
        from backtest.run_gate import _calendar, _spy_closes, champion_trades
        from backtest.scan import membership_path, scan_membership

        if not membership_path().exists():
            scan_membership()
        spells = [spell for spell in generate(book).spells[adoptable[0]["id"]] if in_pooled(spell["day"])]
        verdict = judge(
            adoptable[0]["id"],
            champion_trades(book, schedule=SCHEDULE),
            _simulate(spells)["trades"],
            calendar=_calendar(book),
            regimes=label_regimes(_spy_closes(book), POOLED_START, POOLED_END),
            ideas_tried=ideas_tried(extra=len(BOOK_NAMES)),
        )
        meta["gate"] = {
            "candidate": adoptable[0]["id"],
            "walkForward": verdict.bars["walk_forward"],
            "consistency": verdict.bars["consistency"],
            "freshSlice": verdict.bars["fresh_slice"],
            "reasons": verdict.reasons,
        }
        meta["holdoutOpened"] = False
        SUMMARY_PATH.write_text(json.dumps({"meta": meta, "rows": rows}, indent=2, default=str) + "\n", encoding="utf-8")
        print(verdict.reason_text(), flush=True)
        print("Pre-holdout gate finished. Holdout was not loaded by this path.", flush=True)
    else:
        print("No single adoptable book cleared the frozen screen and the published-net lock. Holdout stays closed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
