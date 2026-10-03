"""Score the four pre-registered books on validation dollars.

``python -m backtest.run_next_batch`` does not open the locked holdout.
A milestone would be a validation net above the published hold-to-close
model. That read is not part of this command. Nothing here places an order.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from backtest.data import CANDIDATES, bars_from_frame, load_symbol, raw_root, sessions
from backtest.next_batch import MIN_TRADES, NEXT_REGISTRY, is_milestone
from backtest.periods import HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.spells import ACCOUNT_USD, SLIP_BPS, portfolio, summarize_portfolio

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
SUMMARY_PATH = RESEARCH / "next_batch_summary.json"
CSV_PATH = RESEARCH / "next_batch.csv"
LOG_PATH = RESEARCH / "RESEARCH_LOG.md"
BEGIN = "<!-- NEXT_BEGIN -->"
END = "<!-- NEXT_END -->"
POOLED_START = date(2023, 1, 1)
POOLED_END = date(2026, 3, 31)


def data_ready(root: Path | None = None) -> bool:
    folder = root or raw_root()
    needed = list(CANDIDATES) + ["SPY"]
    return all((folder / symbol).is_dir() and any((folder / symbol).glob("*.parquet")) for symbol in needed)


def load_preholdout(root: Path | None = None) -> dict[tuple[str, date], list[dict[str, Any]]]:
    book: dict[tuple[str, date], list[dict[str, Any]]] = {}
    for symbol in list(CANDIDATES) + ["SPY"]:
        for day, frame in sessions(load_symbol(symbol, root)):
            if day >= HOLDOUT_START:
                continue
            book[(symbol, day)] = bars_from_frame(frame)
    if any(day >= HOLDOUT_START for (_symbol, day) in book):
        raise RuntimeError("holdout day remained after the load filter")
    return book


def _days(book: dict[tuple[str, date], list[dict[str, Any]]], start: date, end: date) -> list[date]:
    found = {day for (symbol, day) in book if symbol == "SPY" and start <= day <= end}
    if not found:
        found = {day for (_symbol, day) in book if start <= day <= end}
    return sorted(found)


def _window(spells: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [spell for spell in spells if start <= spell["day"] <= end]


def _score(spells: list[dict[str, Any]], sessions: int) -> dict[str, Any]:
    if any(spell["day"] >= HOLDOUT_START for spell in spells):
        raise RuntimeError("a next-batch spell reached the holdout")
    result = portfolio(spells, use_stop=True, slip_bps=SLIP_BPS, schedule="zero", equity=ACCOUNT_USD)
    stats = summarize_portfolio(result, sessions or 1)
    return {
        "trades": int(stats["trades"]),
        "net": float(stats["net"]),
        "per_trade": stats["avgNetDollars"],
        "bps": stats["avgNetBps"],
        "win_rate": stats["winRate"],
        "max_drawdown": stats["maxDrawdown"],
        "trades_per_day": stats["tradesPerDay"],
    }


def score_ideas(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    validate_days = _days(book, VALIDATE_START, VALIDATE_END)
    pooled_days = _days(book, POOLED_START, POOLED_END)
    rows = []
    for idea in NEXT_REGISTRY:
        spells = idea.spells(book)
        if any(spell["day"] >= HOLDOUT_START for spell in spells):
            raise RuntimeError(f"{idea.id} produced a holdout spell")
        validate = _score(_window(spells, VALIDATE_START, VALIDATE_END), len(validate_days))
        pooled = _score(_window(spells, POOLED_START, POOLED_END), len(pooled_days))
        rows.append(
            {
                "id": idea.id,
                "source": idea.source,
                "hypothesis": idea.hypothesis,
                "rationale": idea.rationale,
                "setup": idea.setup,
                "validate_trades": validate["trades"],
                "validate_net": validate["net"],
                "validate_per_trade": validate["per_trade"],
                "validate_bps": validate["bps"],
                "validate_win_rate": validate["win_rate"],
                "validate_max_drawdown": validate["max_drawdown"],
                "validate_trades_per_day": validate["trades_per_day"],
                "pooled_trades": pooled["trades"],
                "pooled_net": pooled["net"],
                "pooled_bps": pooled["bps"],
                "window_start": VALIDATE_START.isoformat(),
                "window_end": VALIDATE_END.isoformat(),
            }
        )
    return rows


def choose(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Highest validation net among books with enough trades. Holdout dates are refused."""
    eligible = []
    for row in rows:
        if date.fromisoformat(row["window_end"]) >= HOLDOUT_START:
            raise RuntimeError(f"{row['id']} selection window reaches the holdout")
        if int(row["validate_trades"]) >= MIN_TRADES:
            eligible.append(row)
    if not eligible:
        return None
    return max(eligible, key=lambda row: (float(row["validate_net"]), int(row["validate_trades"]), row["id"]))


def decision_for(row: dict[str, Any], chosen_id: str | None) -> str:
    trades = int(row["validate_trades"])
    net = float(row["validate_net"])
    if trades < MIN_TRADES:
        return "rejected"
    if net <= 0:
        return "rejected"
    if chosen_id == row["id"] and is_milestone(net, trades):
        return "milestone_not_adopted"
    return "not_adopted"


def reason_for(row: dict[str, Any], chosen: dict[str, Any] | None) -> str:
    trades = int(row["validate_trades"])
    net = float(row["validate_net"])
    if trades < MIN_TRADES:
        return f"Validation had {trades} trades. The floor is {MIN_TRADES}. Holdout was not opened."
    if net <= 0:
        return f"Validation net was ${net:.0f} after 2 bp. A loss is not a candidate. Holdout was not opened."
    if chosen and chosen["id"] == row["id"] and is_milestone(net, trades):
        return (
            "Validation net beat the published hold-to-close model. "
            "The promotion gate was not run and the holdout was not opened by this command."
        )
    return (
        f"Validation net was ${net:.0f} on {trades} trades. "
        "That does not clear the published model validation net of "
        f"${PUBLISHED_TEXT}. Holdout was not opened."
    )


PUBLISHED_TEXT = "1,261"


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.0f}"


def render_section(rows: list[dict[str, Any]], chosen: dict[str, Any] | None) -> str:
    lines = [
        BEGIN,
        "## Next batch",
        "",
        "Four books were written down before the run. Costs are no commission and 2 bp per side "
        f"on a US${ACCOUNT_USD:.0f} ticket, one name a day, flat by 15:55. "
        "Selection is validation net dollars from 2024-07-01 through 2026-03-31. "
        "The locked holdout was not loaded. `models/ACTIVE` stays `v0.1`.",
        "",
        "| Id | Validation trades | Validation net | Pooled net | Decision |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    chosen_id = None if chosen is None else chosen["id"]
    for row in rows:
        decision = decision_for(row, chosen_id)
        lines.append(
            f"| `{row['id']}` | {row['validate_trades']} | {_money(row['validate_net'])} | "
            f"{_money(row['pooled_net'])} | {decision} |"
        )
    lines.append("")
    for row in rows:
        lines.append(f"`{row['id']}` — {reason_for(row, chosen)}")
    lines.append("")
    lines.append(
        "Sector-relative strength was not scored. XLK, XLF, XLE, XLV, XLP, and XLI are not in `data/raw5`. "
        "That request is priority 4 in `DATA_REQUEST.md`."
    )
    lines.append(END)
    return "\n".join(lines) + "\n"


def write_log(section: str) -> None:
    text = LOG_PATH.read_text(encoding="utf-8")
    if BEGIN in text and END in text:
        start = text.index(BEGIN)
        finish = text.index(END) + len(END)
        text = text[:start] + section.rstrip() + text[finish:]
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + section
    LOG_PATH.write_text(text, encoding="utf-8")


def write_outputs(rows: list[dict[str, Any]], chosen: dict[str, Any] | None) -> None:
    chosen_id = None if chosen is None else chosen["id"]
    payload = {
        "holdout_used": False,
        "active": "v0.1",
        "chosen_id": chosen_id,
        "milestone": bool(chosen) and is_milestone(float(chosen["validate_net"]), int(chosen["validate_trades"])),
        "rows": [
            {
                "id": row["id"],
                "decision": decision_for(row, chosen_id),
                "reason": reason_for(row, chosen),
                "validate_trades": row["validate_trades"],
                "validate_net": row["validate_net"],
                "pooled_net": row["pooled_net"],
            }
            for row in rows
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    import csv

    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "decision",
                "validate_trades",
                "validate_net",
                "validate_bps",
                "validate_win_rate",
                "pooled_trades",
                "pooled_net",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "id": row["id"],
                    "decision": decision_for(row, chosen_id),
                    "validate_trades": row["validate_trades"],
                    "validate_net": row["validate_net"],
                    "validate_bps": row["validate_bps"],
                    "validate_win_rate": row["validate_win_rate"],
                    "pooled_trades": row["pooled_trades"],
                    "pooled_net": row["pooled_net"],
                }
            )
    write_log(render_section(rows, chosen))


def missing_message(root: Path) -> str:
    return (
        f"No 5-minute bars under {root}. The ten existing symbols and the twelve names in "
        "DATA_REQUEST.md are both absent, so this batch was not scored and the holdout was not opened. "
        "Restore data/raw5 and run python -m backtest.run_next_batch."
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Score the next batch on validation only. Does not trade.")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root or raw_root()
    if not data_ready(root):
        print(missing_message(root), flush=True)
        return 2
    book = load_preholdout(root)
    rows = score_ideas(book)
    chosen = choose(rows)
    if chosen and is_milestone(float(chosen["validate_net"]), int(chosen["validate_trades"])):
        print(
            f"{chosen['id']} beat the published validation net. Look 8 was not opened by this command.",
            flush=True,
        )
    write_outputs(rows, chosen)
    for row in rows:
        print(
            f"{row['id']} validation {row['validate_trades']} trades {_money(row['validate_net'])}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
