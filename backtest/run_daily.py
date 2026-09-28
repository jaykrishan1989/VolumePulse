"""Score the daily-frequency rules. The holdout is read once, and only for the validation finalist.

``python -m backtest.run_daily`` uses the stored 5-minute bars. It does not
open a Gateway socket and it does not change the live rule.

The finalist is the validation rule whose signals cover at least 95 percent
of SPY sessions and whose tiered net is the highest. If none clears 95 percent,
the holdout stays shut. A gate pass does not deploy a live model.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from backtest.daily import (
    CHANGELOG_BEGIN,
    CHANGELOG_END,
    DAILY_BEGIN,
    DAILY_END,
    DAILY_REGISTRY,
    DailyRule,
    build_sessions,
    choose_finalist,
)
from backtest.gate import (
    HALF_YEARS,
    POOLED_END,
    POOLED_START,
    GateVerdict,
    ideas_tried,
    judge,
    label_regimes,
    slice_stats,
)
from backtest.periods import HOLDOUT_END, HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.run_gate import _calendar, _spy_closes, champion_trades
from backtest.run_hypotheses import load_book
from backtest.spells import ACCOUNT_USD, SLIP_BPS, portfolio

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
RULE_PATH = ROOT / "app" / "signal_rule.json"
ACTIVE_PATH = ROOT / "models" / "ACTIVE"
CHANGELOG_PATH = ROOT / "models" / "CHANGELOG.md"
LOG_PATH = RESEARCH / "RESEARCH_LOG.md"
LOOKS_PATH = RESEARCH / "holdout_looks.csv"
SELECTION_PATH = RESEARCH / "daily_selection.json"

REPORT_FOLDS: list[tuple[str, date, date]] = list(HALF_YEARS) + [
    ("2026Q1", date(2026, 1, 1), date(2026, 3, 31)),
]


def spy_days(book: dict[tuple[str, date], list[dict[str, Any]]], start: date, end: date) -> list[date]:
    return sorted(day for (symbol, day) in book if symbol == "SPY" and start <= day <= end)


def refuse_holdout(rows: list[dict[str, Any]], label: str) -> None:
    leaked = [row["day"] for row in rows if row["day"] >= HOLDOUT_START]
    if leaked:
        raise RuntimeError(f"{label} includes holdout day {min(leaked)}")


def run_book(spells: list[dict[str, Any]], *, schedule: str = "tiered") -> dict[str, Any]:
    return portfolio(spells, use_stop=True, schedule=schedule, equity=ACCOUNT_USD, slip_bps=SLIP_BPS)


def pack(trades: list[dict[str, Any]], spells: list[dict[str, Any]], sessions: int, drawdown: float) -> dict[str, Any]:
    stats = slice_stats(trades)
    wins = sum(1 for trade in trades if float(trade["net"]) > 0)
    fill_days = len({trade["day"] for trade in trades})
    signal_days = len({spell["day"] for spell in spells})
    return {
        "trades": stats.trades,
        "win_rate": None if stats.trades == 0 else wins / stats.trades,
        "net": stats.net,
        "per_trade": stats.expectancy,
        "bps": stats.avg_bps,
        "per_day": stats.net / sessions if sessions else None,
        "trades_per_day": stats.trades / sessions if sessions else None,
        "signal_days": signal_days,
        "fill_days": fill_days,
        "sessions": sessions,
        "signal_day_frac": signal_days / sessions if sessions else 0.0,
        "fill_day_frac": fill_days / sessions if sessions else 0.0,
        "max_drawdown": drawdown,
    }


def _window_spells(spells: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [spell for spell in spells if start <= spell["day"] <= end]


def evaluate_rule(
    rule: DailyRule,
    sessions: dict[tuple[str, date], Any],
    book: dict[tuple[str, date], list[dict[str, Any]]],
    days: list[date],
) -> dict[str, Any]:
    spells = rule.spells(sessions, days)
    refuse_holdout(spells, rule.id)
    pooled_days = [day for day in days if POOLED_START <= day <= POOLED_END]
    pooled_spells = _window_spells(spells, POOLED_START, POOLED_END)
    result = run_book(pooled_spells)
    fixed = run_book(pooled_spells, schedule="fixed")
    validation_days = [day for day in days if VALIDATE_START <= day <= VALIDATE_END]
    validation_spells = _window_spells(spells, VALIDATE_START, VALIDATE_END)
    validation = run_book(validation_spells)
    folds = []
    for name, start, end in REPORT_FOLDS:
        fold_spells = _window_spells(spells, start, end)
        fold_result = run_book(fold_spells)
        folds.append(
            {
                "fold": name,
                "vote": name != "2026Q1",
                **pack(fold_result["trades"], fold_spells, len([day for day in days if start <= day <= end]), fold_result["maxDrawdown"]),
            }
        )
    return {
        "rule": rule,
        "spells": pooled_spells,
        "trades": list(result["trades"]),
        "pooled": pack(result["trades"], pooled_spells, len(pooled_days), result["maxDrawdown"]),
        "fixed_net": fixed["net"],
        "validation": pack(
            validation["trades"],
            validation_spells,
            len(validation_days),
            validation["maxDrawdown"],
        ),
        "folds": folds,
    }


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _bps(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} bp"


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "−" if value < 0 else ""
    return f"{sign}${abs(value):.2f}"


def _money0(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "−" if value < 0 else ""
    return f"{sign}${abs(value):.0f}"


def selection_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validation numbers only. This is the object choose_finalist sees."""
    out = []
    for row in rows:
        validation = row["validation"]
        out.append(
            {
                "id": row["rule"].id,
                "signal_day_frac": validation["signal_day_frac"],
                "net": validation["net"],
                "bps": validation["bps"] if validation["bps"] is not None else 0.0,
            }
        )
    return out


def record_look(rule_id: str, note: str) -> int:
    existing = list(csv.DictReader(LOOKS_PATH.open(encoding="utf-8")))
    for row in existing:
        if rule_id in row["rules"]:
            return int(row["look"])
    look = max(int(row["look"]) for row in existing) + 1
    if not LOOKS_PATH.read_text(encoding="utf-8").endswith("\n"):
        with LOOKS_PATH.open("a", encoding="utf-8") as handle:
            handle.write("\n")
    with LOOKS_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([look, date.today().isoformat(), rule_id, note])
    return look


def holdout_for(rule_id: str) -> dict[str, Any]:
    """One read. The book includes earlier days so ATR is warmed up. Only holdout spells are filled."""
    rule = next(item for item in DAILY_REGISTRY if item.id == rule_id)
    book = load_book(include_holdout=True)
    sessions = build_sessions(book)
    days = [day for day in spy_days(book, HOLDOUT_START, HOLDOUT_END)]
    spells = rule.spells(sessions, days)
    early = [spell["day"] for spell in spells if spell["day"] < HOLDOUT_START]
    if early:
        raise RuntimeError(f"holdout builder returned a pre-holdout day {min(early)}")
    result = run_book(spells)
    fixed = run_book(spells, schedule="fixed")
    packed = pack(result["trades"], spells, len(days), result["maxDrawdown"])
    packed["fixed_net"] = fixed["net"]
    packed["id"] = rule_id
    return packed


def _fmt_row(stats: dict[str, Any]) -> str:
    return (
        f"{stats['trades']} trades, {_pct(stats['win_rate'])} wins, "
        f"{_money0(stats['net'])} net, {_money(stats['per_trade'])}/trade, "
        f"{_money(stats['per_day'])}/session, {_bps(stats['bps'])}, "
        f"max DD {_money0(stats['max_drawdown'])}"
    )


def daily_markdown(
    rows: list[dict[str, Any]],
    verdicts: dict[str, GateVerdict],
    finalist: str | None,
    baseline_frac: float,
    tried: int,
    holdout: dict[str, Any] | None,
    look: int | None,
) -> str:
    lines = [
        DAILY_BEGIN,
        "## Daily frequency",
        "",
        "The owner asked for a buy and a sell on essentially every session. "
        f"The frozen midmorning list, measured on this file, has a fill on {baseline_frac * 100:.1f}% of "
        "SPY sessions from 2023-01-01 through 2026-03-31. That is the baseline these five rules are compared with. "
        "Two rules pick a name at a fixed clock, so a session with a 9:30 open gets a signal. "
        "Three rules wait for a setup and can miss a day. Thresholds were not moved after the run.",
        "",
        f"Costs: US$2,120, whole shares, tiered commissions, 2 bp slippage, hard stop, flat by 15:55. "
        f"Bonferroni denominator, including these five ids: {tried}. "
        "The finalist is chosen on the validation window only: at least 95% of SPY sessions have a signal, "
        "then the highest tiered net. "
        + (
            f"That finalist is `{finalist}`. The holdout was read once for it (look {look})."
            if finalist
            else "No rule cleared 95% coverage on the validation window, so the holdout was not opened."
        )
        + " The live rule was not changed. `models/ACTIVE` stays `v0.1`. No order was placed.",
        "",
        "| Rule | Signal days | Round trips/day | Win | Net | $/trade | $/day | Max DD | Windows | Decision |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        stats = row["pooled"]
        verdict = verdicts[row["rule"].id]
        wins = sum(1 for window in verdict.windows if window.win)
        lines.append(
            f"| {row['rule'].id} | {stats['signal_day_frac'] * 100:.1f}% | {stats['trades_per_day']:.2f} | "
            f"{_pct(stats['win_rate'])} | {_money0(stats['net'])} | {_money(stats['per_trade'])} | "
            f"{_money(stats['per_day'])} | {_money0(stats['max_drawdown'])} | {wins}/{len(verdict.windows)} | "
            f"{verdict.decision.upper()} |"
        )
    lines.append("")
    lines.append(
        f"Validation window 2024-07-01 to 2026-03-31, the selection sample. "
        f"Finalist: `{finalist or 'none'}`."
    )
    lines.append("")
    lines.append("| Rule | Validation signal days | Validation net | Eligible |")
    lines.append("| --- | ---: | ---: | --- |")
    for row in rows:
        validation = row["validation"]
        eligible = "yes" if validation["signal_day_frac"] + 1e-12 >= 0.95 else "no"
        lines.append(
            f"| {row['rule'].id} | {validation['signal_day_frac'] * 100:.1f}% | {_money0(validation['net'])} | {eligible} |"
        )
    lines.append("")
    for row in rows:
        rule: DailyRule = row["rule"]
        verdict = verdicts[rule.id]
        stats = row["pooled"]
        lines.extend(
            [
                f"### {rule.id}",
                "",
                f"**Source.** {rule.source}",
                "",
                f"**Hypothesis.** {rule.hypothesis}",
                "",
                f"**Economic rationale.** {rule.rationale}",
                "",
                f"**Test setup.** {rule.setup}",
                "",
                f"**Pooled, tiered.** {_fmt_row(stats)}. "
                f"Signal on {stats['signal_day_frac'] * 100:.1f}% of {stats['sessions']} sessions. "
                f"A fill on {stats['fill_day_frac'] * 100:.1f}%. "
                f"Fixed US$1 minimum: {_money0(row['fixed_net'])}.",
                "",
                f"**Validation.** {_fmt_row(row['validation'])}. "
                f"Signal days {row['validation']['signal_day_frac'] * 100:.1f}%.",
                "",
                "Half-years are votes. 2026Q1 is reported and is not a vote. Each fold is its own US$2,120 account.",
                "",
                "| Fold | Signal days | Trades | Win | Net | $/trade | $/day | Max DD | Vote |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for fold in row["folds"]:
            lines.append(
                f"| {fold['fold']} | {fold['signal_day_frac'] * 100:.1f}% | {fold['trades']} | {_pct(fold['win_rate'])} | "
                f"{_money0(fold['net'])} | {_money(fold['per_trade'])} | {_money(fold['per_day'])} | "
                f"{_money0(fold['max_drawdown'])} | {'yes' if fold['vote'] else 'no'} |"
            )
        lines.extend(
            [
                "",
                f"**Promotion gate.** {'Rejected' if verdict.decision == 'rejected' else 'Would pass, and was not deployed'}. "
                + " ".join(verdict.reasons),
                "",
            ]
        )
    if holdout is not None:
        lines.extend(
            [
                "### Holdout, one read",
                "",
                f"**Rule.** `{holdout['id']}`. Look {look}. Chosen on the validation window before this slice was loaded. "
                "The number below did not change the pick and did not change the live rule.",
                "",
                f"**Holdout, tiered.** {_fmt_row(holdout)}. "
                f"Signal on {holdout['signal_day_frac'] * 100:.1f}% of {holdout['sessions']} sessions. "
                f"Fixed US$1 minimum: {_money0(holdout['fixed_net'])}.",
                "",
                "The promotion-gate paragraph for this rule says the fresh slice was not read. "
                "That sentence means the gate was not given the slice, so it cannot promote. "
                "This paragraph is the one look. A profit here does not undo a loss on the validation window.",
                "",
            ]
        )
    else:
        lines.extend(["### Holdout", "", "Not read. No validation rule covered 95% of sessions.", ""])
    lines.append(DAILY_END)
    return "\n".join(lines)


def changelog_note(rows: list[dict[str, Any]], finalist: str | None, holdout: dict[str, Any] | None) -> str:
    lines = [
        CHANGELOG_BEGIN,
        "## Daily frequency — 2026-09-28 — no checkpoint",
        "",
        "Five pre-registered daily-frequency rules were scored. None replaced v0.1. "
        "The live list was not edited and no order was placed. "
        + (
            f"The validation finalist was `{finalist}`."
            if finalist
            else "No rule covered 95% of validation sessions."
        ),
        "",
        "| Id | Signal days | Trades | Net | $/trade | Decision |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        stats = row["pooled"]
        lines.append(
            f"| {row['rule'].id} | {stats['signal_day_frac'] * 100:.1f}% | {stats['trades']} | "
            f"{_money0(stats['net'])} | {_money(stats['per_trade'])} | {row['verdict'].decision} |"
        )
    if holdout is not None:
        lines.extend(
            [
                "",
                f"Holdout of `{holdout['id']}`, one read: {_fmt_row(holdout)}. "
                f"Signal days {holdout['signal_day_frac'] * 100:.1f}%. Not deployed.",
            ]
        )
    lines.append(CHANGELOG_END)
    return "\n".join(lines)


def _write_marked(path: Path, section: str, begin: str, end: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    start = existing.find(begin)
    stop = existing.find(end)
    if start >= 0 and stop >= start:
        updated = existing[:start] + section + existing[stop + len(end) :]
    else:
        updated = existing.rstrip() + "\n\n" + section + "\n"
    path.write_text(updated, encoding="utf-8")


def _write_tables(rows: list[dict[str, Any]], tried: int, finalist: str | None, holdout: dict[str, Any] | None) -> None:
    RESEARCH.mkdir(parents=True, exist_ok=True)
    with (RESEARCH / "daily.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "signal_day_frac",
                "fill_day_frac",
                "trades_per_day",
                "trades",
                "win_rate",
                "net",
                "per_trade",
                "per_day",
                "bps",
                "max_drawdown",
                "fixed_net",
                "validation_signal_day_frac",
                "validation_net",
                "windows_won",
                "windows",
                "bootstrap_p",
                "permutation_p",
                "alpha",
                "ideas_tried",
                "decision",
                "finalist",
                "reasons",
            ],
        )
        writer.writeheader()
        for row in rows:
            stats = row["pooled"]
            verdict: GateVerdict = row["verdict"]
            writer.writerow(
                {
                    "id": row["rule"].id,
                    "signal_day_frac": f"{stats['signal_day_frac']:.4f}",
                    "fill_day_frac": f"{stats['fill_day_frac']:.4f}",
                    "trades_per_day": f"{stats['trades_per_day']:.4f}",
                    "trades": stats["trades"],
                    "win_rate": "" if stats["win_rate"] is None else f"{stats['win_rate']:.4f}",
                    "net": f"{stats['net']:.2f}",
                    "per_trade": "" if stats["per_trade"] is None else f"{stats['per_trade']:.4f}",
                    "per_day": "" if stats["per_day"] is None else f"{stats['per_day']:.4f}",
                    "bps": "" if stats["bps"] is None else f"{stats['bps']:.2f}",
                    "max_drawdown": f"{stats['max_drawdown']:.2f}",
                    "fixed_net": f"{row['fixed_net']:.2f}",
                    "validation_signal_day_frac": f"{row['validation']['signal_day_frac']:.4f}",
                    "validation_net": f"{row['validation']['net']:.2f}",
                    "windows_won": sum(1 for window in verdict.windows if window.win),
                    "windows": len(verdict.windows),
                    "bootstrap_p": f"{verdict.bootstrap_p:.6f}",
                    "permutation_p": f"{verdict.permutation_p:.6f}",
                    "alpha": f"{verdict.alpha:.6f}",
                    "ideas_tried": tried,
                    "decision": verdict.decision,
                    "finalist": row["rule"].id == finalist,
                    "reasons": " ".join(verdict.reasons),
                }
            )
    with (RESEARCH / "daily_folds.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "fold", "vote", "signal_day_frac", "trades", "win_rate", "net", "per_trade", "per_day", "bps", "max_drawdown"],
        )
        writer.writeheader()
        for row in rows:
            for fold in row["folds"]:
                writer.writerow(
                    {
                        "id": row["rule"].id,
                        "fold": fold["fold"],
                        "vote": fold["vote"],
                        "signal_day_frac": f"{fold['signal_day_frac']:.4f}",
                        "trades": fold["trades"],
                        "win_rate": "" if fold["win_rate"] is None else f"{fold['win_rate']:.4f}",
                        "net": f"{fold['net']:.2f}",
                        "per_trade": "" if fold["per_trade"] is None else f"{fold['per_trade']:.4f}",
                        "per_day": "" if fold["per_day"] is None else f"{fold['per_day']:.4f}",
                        "bps": "" if fold["bps"] is None else f"{fold['bps']:.2f}",
                        "max_drawdown": f"{fold['max_drawdown']:.2f}",
                    }
                )
    summary = {
        "activeUnchanged": True,
        "checkpointIssued": False,
        "finalist": finalist,
        "holdoutRead": holdout is not None,
        "ideasTried": tried,
        "rules": [
            {
                "id": row["rule"].id,
                "decision": row["verdict"].decision,
                "signalDayFrac": row["pooled"]["signal_day_frac"],
                "trades": row["pooled"]["trades"],
                "net": row["pooled"]["net"],
                "perTrade": row["pooled"]["per_trade"],
                "perDay": row["pooled"]["per_day"],
                "bps": row["pooled"]["bps"],
                "maxDrawdown": row["pooled"]["max_drawdown"],
                "winRate": row["pooled"]["win_rate"],
            }
            for row in rows
        ],
        "holdout": holdout,
    }
    (RESEARCH / "daily_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    if any(arg.startswith("--milestone") for arg in sys.argv[1:]):
        raise SystemExit("refusing a second holdout path")
    active = ACTIVE_PATH.read_text(encoding="utf-8").strip()
    if active != "v0.1":
        raise SystemExit(f"ACTIVE is {active}, expected v0.1")
    rule_before = RULE_PATH.read_bytes()
    book = load_book()
    if any(day >= HOLDOUT_START for (_symbol, day) in book):
        raise SystemExit("pre-holdout book contains a holdout day")
    sessions = build_sessions(book)
    days = spy_days(book, date(2022, 1, 1), POOLED_END)
    print(f"sessions in book {len(days)}", flush=True)
    rows = []
    for rule in DAILY_REGISTRY:
        print(f"rule {rule.id}", flush=True)
        row = evaluate_rule(rule, sessions, book, days)
        print(
            f"  signals {row['pooled']['signal_day_frac'] * 100:.1f}% "
            f"net {row['pooled']['net']:.0f} validation {row['validation']['net']:.0f}",
            flush=True,
        )
        rows.append(row)
    finalist = choose_finalist(selection_rows(rows))
    SELECTION_PATH.write_text(
        json.dumps(
            {
                "finalist": finalist,
                "frequencyMin": 0.95,
                "window": [VALIDATE_START.isoformat(), VALIDATE_END.isoformat()],
                "chosenWithoutHoldout": True,
                "candidates": selection_rows(rows),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"finalist {finalist or 'none'} written before any holdout load", flush=True)
    champion = champion_trades(book)
    calendar = _calendar(book)
    baseline_days = len({trade["day"] for trade in champion if trade["day"] in set(calendar)})
    baseline_frac = baseline_days / len(calendar) if calendar else 0.0
    print(f"champion fill days {baseline_days}/{len(calendar)} ({baseline_frac * 100:.1f}%)", flush=True)
    tried = ideas_tried()
    regimes = label_regimes(_spy_closes(book), POOLED_START, POOLED_END)
    verdicts: dict[str, GateVerdict] = {}
    for row in rows:
        verdict = judge(
            row["rule"].id,
            champion,
            row["trades"],
            calendar=calendar,
            regimes=regimes,
            ideas_tried=tried,
        )
        row["verdict"] = verdict
        verdicts[row["rule"].id] = verdict
        wins = sum(1 for window in verdict.windows if window.win)
        print(f"  gate {row['rule'].id} {verdict.decision} {wins}/{len(verdict.windows)}", flush=True)
    holdout = None
    look = None
    if finalist is not None:
        look = record_look(
            finalist,
            "One read of the daily-frequency finalist. Chosen on validation coverage and validation net. Not used to pick.",
        )
        holdout = holdout_for(finalist)
        print(
            f"holdout look {look} {finalist} net {holdout['net']:.0f} "
            f"signals {holdout['signal_day_frac'] * 100:.1f}%",
            flush=True,
        )
    if any(row["verdict"].passed for row in rows):
        raise SystemExit("a daily rule passed with the gate's fresh slice still closed; refusing to promote")
    if ACTIVE_PATH.read_text(encoding="utf-8").strip() != "v0.1":
        raise SystemExit("ACTIVE changed during the run")
    if RULE_PATH.read_bytes() != rule_before:
        raise SystemExit("live signal rule was modified")
    _write_marked(LOG_PATH, daily_markdown(rows, verdicts, finalist, baseline_frac, tried, holdout, look), DAILY_BEGIN, DAILY_END)
    _write_marked(CHANGELOG_PATH, changelog_note(rows, finalist, holdout), CHANGELOG_BEGIN, CHANGELOG_END)
    _write_tables(rows, tried, finalist, holdout)
    print("champion untouched; no checkpoint; no orders", flush=True)


if __name__ == "__main__":
    main()
