"""Score the frozen session-edge books.

``python -m backtest.run_session_edge`` uses tiered IBKR commission and 2 bp
of slippage. It does not open the locked holdout unless ``m_primary`` is the
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
from backtest.session_edge import (
    ADOPTABLE,
    BOOK_NAMES,
    clears_published_milestone,
    generate,
    screen_failures,
)
from backtest.spells import ACCOUNT_USD, SLIP_BPS, portfolio

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = ROOT / "research" / "session_edge_summary.json"
SCHEDULE = "tiered"


def _simulate(spells: list[dict[str, Any]]) -> dict[str, Any]:
    return portfolio(
        spells,
        equity=ACCOUNT_USD,
        slip_bps=SLIP_BPS,
        schedule=SCHEDULE,
        max_concurrent=1,
    )


def _positive_halves(trades: list[dict[str, Any]]) -> int:
    count = 0
    for start, end in HALVES:
        net = sum(float(trade["net"]) for trade in trades if start <= trade["day"] <= end)
        if net > 0:
            count += 1
    return count


def _describe(
    name: str,
    spells: list[dict[str, Any]],
    sessions: list[date],
) -> dict[str, Any]:
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
    clocks: Counter[int] = Counter(int(spell["buy_minute"]) for spell in validation)
    months: dict[str, float] = defaultdict(float)
    month_fills: Counter[str] = Counter()
    for trade in trades:
        key = trade["day"].strftime("%Y-%m")
        months[key] += float(trade["net"])
        month_fills[key] += 1
    wins = [trade for trade in trades if float(trade["net"]) > 0]
    losses = [trade for trade in trades if float(trade["net"]) < 0]
    avg_bps = (sum(float(trade["ret"]) * 10_000.0 for trade in trades) / len(trades)) if trades else 0.0
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
    return {
        "id": name,
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
        "dayShare": day_share,
        "reasons": dict(reasons),
        "symbols": dict(symbols),
        "entryMinutes": {str(minute): clocks[minute] for minute in sorted(clocks)},
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


def _residual_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    kept = [row for row in rows if in_validation(row["day"])]
    if not kept:
        return {"days": 0}
    values = sorted(float(row["worstResidual"]) for row in kept)
    mid = values[len(values) // 2]

    def share(level: float) -> float:
        return sum(1 for value in values if value <= level + 1e-12) / len(values)

    return {
        "days": len(kept),
        "medianWorstResidualBp": mid * 10_000.0,
        "shareAtOrBelow20bp": share(-0.0020),
        "shareAtOrBelow30bp": share(-0.0030),
        "shareAtOrBelow40bp": share(-0.0040),
        "shareImpulseAndReady": sum(1 for row in kept if row["spyImpulse"] and row["betaReady"]) / len(kept),
    }


def score(book: dict[tuple[str, date], list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if any(day >= HOLDOUT_START for (_symbol, day) in book):
        raise RuntimeError("session-edge scorer received a holdout day")
    result = generate(book)
    sessions = sorted(day for (symbol, day) in book if symbol == "SPY" and VALIDATE_START <= day <= VALIDATE_END)
    rows = [_describe(name, result.spells[name], sessions) for name in BOOK_NAMES]
    passes = [row["id"] for row in rows if row["screenPass"]]
    meta = {
        "schedule": SCHEDULE,
        "slipBps": SLIP_BPS,
        "accountUsd": ACCOUNT_USD,
        "sessions": len(sessions),
        "screenPasses": passes,
        "holdoutOpened": False,
        "residual": _residual_report(result.residual_days),
    }
    return rows, meta


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Score the session-edge books. Does not trade.")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root or raw_root()
    if not data_ready(root):
        print(f"Session-edge books not scored. No parquet bars under {root}.", flush=True)
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
    print(f"residual diagnostic: {meta['residual']}", flush=True)
    adoptable = [row for row in rows if row["screenPass"] and row["adoptable"]]
    if len(meta["screenPasses"]) == 1 and len(adoptable) == 1 and adoptable[0]["milestone"]:
        result = generate(book)
        spells = [spell for spell in result.spells[adoptable[0]["id"]] if in_pooled(spell["day"])]
        verdict = _preholdout_gate(book, _simulate(spells)["trades"], adoptable[0]["id"])
        meta["gate"] = {
            "candidate": adoptable[0]["id"],
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
                f"{adoptable[0]['id']} passed the pre-holdout gate. Holdout was not loaded by this path.",
                flush=True,
            )
        else:
            print("Pre-holdout gate failed. Holdout stays closed.", flush=True)
    else:
        print("No single adoptable book cleared the frozen screen and the published-net lock. Holdout stays closed.", flush=True)
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
        ideas_tried=ideas_tried(extra=len(BOOK_NAMES)),
    )


if __name__ == "__main__":
    raise SystemExit(main())
