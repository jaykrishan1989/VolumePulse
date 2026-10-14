"""Score the second pre-registered batch on validation dollars.

``python -m backtest.run_next_batch2`` does not open the locked holdout and
does not rewrite the first next-batch files. A milestone would be a validation
net above the published hold-to-close model. That read is not part of this
command. Nothing here places an order.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from backtest.next_batch import is_milestone
from backtest.next_batch2 import NEXT2_REGISTRY
from backtest.periods import HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.run_next_batch import (
    POOLED_END,
    POOLED_START,
    _concentration,
    _days,
    _money,
    _score,
    _window,
    choose,
    data_ready,
    decision_for,
    load_preholdout,
    reason_for,
)
from backtest.spells import ACCOUNT_USD

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
SUMMARY_PATH = RESEARCH / "next_batch2_summary.json"
CSV_PATH = RESEARCH / "next_batch2.csv"
LOG_PATH = RESEARCH / "RESEARCH_LOG.md"
BEGIN = "<!-- NEXT2_BEGIN -->"
END = "<!-- NEXT2_END -->"
# Published validation trade count of ml:flat:flat:1atr:top1:1:20. Frequency
# is compared with this count. It is not a new holdout look.
PUBLISHED_MODEL_TRADES = 85


def score_ideas(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    validate_days = _days(book, VALIDATE_START, VALIDATE_END)
    pooled_days = _days(book, POOLED_START, POOLED_END)
    rows = []
    for idea in NEXT2_REGISTRY:
        spells = idea.spells(book)
        if any(spell["day"] >= HOLDOUT_START for spell in spells):
            raise RuntimeError(f"{idea.id} produced a holdout spell")
        validate_spells = _window(spells, VALIDATE_START, VALIDATE_END)
        pooled_spells = _window(spells, POOLED_START, POOLED_END)
        validate = _score(validate_spells, len(validate_days))
        pooled = _score(pooled_spells, len(pooled_days))
        rows.append(
            {
                "id": idea.id,
                "source": idea.source,
                "hypothesis": idea.hypothesis,
                "rationale": idea.rationale,
                "setup": idea.setup,
                "validate_signals": len(validate_spells),
                "validate_trades": validate["trades"],
                "validate_net": validate["net"],
                "validate_per_trade": validate["per_trade"],
                "validate_bps": validate["bps"],
                "validate_win_rate": validate["win_rate"],
                "validate_max_drawdown": validate["max_drawdown"],
                "validate_trades_per_day": validate["trades_per_day"],
                "validate_stop_trades": validate["stop_trades"],
                "validate_top5_net": validate["top5_net"],
                "validate_rest_net": validate["rest_net"],
                "validate_largest": validate["largest"],
                "validate_top5_keys": validate["top5_keys"],
                "pooled_trades": pooled["trades"],
                "pooled_net": pooled["net"],
                "pooled_bps": pooled["bps"],
                "pooled_max_drawdown": pooled["max_drawdown"],
                "window_start": VALIDATE_START.isoformat(),
                "window_end": VALIDATE_END.isoformat(),
            }
        )
    return rows


def _reading(rows: list[dict[str, Any]]) -> str:
    best = max(rows, key=lambda row: float(row["validate_net"]))
    busiest = max(rows, key=lambda row: int(row["validate_trades"]))
    if rows and all(float(row["validate_rest_net"]) < 0 for row in rows):
        tail = "After those five trades are removed, every book on this page is negative. "
    else:
        tail = ""
    if is_milestone(float(best["validate_net"]), int(best["validate_trades"])):
        gate = "The best net clears the published model. This command did not open the holdout and did not run the promotion gate. "
    else:
        gate = "The best net is short of $1,261, so look 8 stays closed and the promotion gate was not run. "
    return (
        f"Reading. `{best['id']}` is the highest validation net at {_money(best['validate_net'])} "
        f"on {best['validate_trades']} fills ({best['validate_signals']} signals). "
        f"`{busiest['id']}` is the busiest, at {busiest['validate_trades']} fills against "
        f"{PUBLISHED_MODEL_TRADES} for the published hold-to-close model. "
        f"{gate}{tail}"
        "The five-day drop is the concentration bar in `research/GATE.md`, reported here as a description, "
        "not as a gate pass."
    )


def render_section(rows: list[dict[str, Any]], chosen: dict[str, Any] | None) -> str:
    lines = [
        BEGIN,
        "## Next batch, ordinary sessions",
        "",
        f"{len(rows)} books were written down before the run. They are built to trade ordinary sessions, "
        "not yesterday's loser held to the close. Costs are no commission and 2 bp per side "
        f"on a US${ACCOUNT_USD:.0f} ticket, flat by 15:55. "
        "Selection is validation net dollars from 2024-07-01 through 2026-03-31. "
        "The locked holdout was not loaded. `models/ACTIVE` stays `v0.1`.",
        "",
        "| Id | Signals | Fills | Win | Validation net | bp | Fills/day | Pooled net | Decision |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    chosen_id = None if chosen is None else chosen["id"]
    for row in rows:
        decision = decision_for(row, chosen_id)
        win = row["validate_win_rate"]
        win_text = "n/a" if win is None else f"{100 * float(win):.1f}%"
        bps = row["validate_bps"]
        bps_text = "n/a" if bps is None else f"{float(bps):.1f}"
        per_day = row["validate_trades_per_day"]
        per_day_text = "n/a" if per_day is None else f"{float(per_day):.2f}"
        lines.append(
            f"| `{row['id']}` | {row['validate_signals']} | {row['validate_trades']} | {win_text} | "
            f"{_money(row['validate_net'])} | {bps_text} | {per_day_text} | {_money(row['pooled_net'])} | {decision} |"
        )
    lines.append("")
    for row in rows:
        lines.append(f"`{row['id']}` — {reason_for(row, chosen)} {_concentration(row)}")
    lines.append("")
    lines.append(_reading(rows))
    lines.append("")
    lines.append("Sources, frozen before the fill:")
    for row in rows:
        lines.append(f"- `{row['id']}`: {row['source']}")
    lines.append("")
    lines.append(
        "The twelve extra names and XLK, XLF, XLE, XLV, XLP, and XLI are still absent, so a sector residual "
        "was not scored. The published holdout is unchanged: look 7 is +$297 on 19 trades, and the 1.5% gap "
        "rule on look 6 is +$210 on 52 trades. No order was placed."
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
                "validate_signals": row["validate_signals"],
                "validate_trades": row["validate_trades"],
                "validate_net": row["validate_net"],
                "validate_bps": row["validate_bps"],
                "validate_win_rate": row["validate_win_rate"],
                "validate_max_drawdown": row["validate_max_drawdown"],
                "validate_trades_per_day": row["validate_trades_per_day"],
                "validate_stop_trades": row["validate_stop_trades"],
                "validate_top5_net": row["validate_top5_net"],
                "validate_rest_net": row["validate_rest_net"],
                "validate_largest": row["validate_largest"],
                "pooled_trades": row["pooled_trades"],
                "pooled_net": row["pooled_net"],
            }
            for row in rows
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "decision",
                "validate_signals",
                "validate_trades",
                "validate_net",
                "validate_bps",
                "validate_win_rate",
                "validate_max_drawdown",
                "validate_trades_per_day",
                "validate_stop_trades",
                "validate_top5_net",
                "validate_rest_net",
                "pooled_trades",
                "pooled_net",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row[name] if name != "decision" else decision_for(row, chosen_id) for name in writer.fieldnames})
    write_log(render_section(rows, chosen))


def missing_message(root: Path) -> str:
    return (
        f"No 5-minute bars under {root}. This batch was not scored and the holdout was not opened. "
        "Restore data/raw5 and run python -m backtest.run_next_batch2."
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Score the second next batch on validation only. Does not trade.")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    from backtest.data import raw_root

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
