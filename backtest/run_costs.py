"""Re-score frozen rules on the owner's execution cost.

IBKR is the data source only. The default model in ``app/cost_model.json``
charges no commission and no regulatory fee. Slippage is 2 bp per side on the
next bar's open. There is no IBKR commission column.

The daily-frequency ranking uses the validation window only. This command
does not append ``research/holdout_looks.csv``. Numbers for looks 2 and 3 are
the same already-opened trades, restated under slippage only, and are not used
to pick a winner. No threshold is moved. No order is placed.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from backtest.costs import (
    COSTS_BEGIN,
    COSTS_CHANGELOG_BEGIN,
    COSTS_CHANGELOG_END,
    COSTS_END,
    PRIMARY_SCHEDULE,
    SLIP_BPS_MIN,
)
from backtest.daily import DAILY_REGISTRY, build_sessions, choose_finalist
from backtest.gate import (
    POOLED_END,
    POOLED_START,
    GateVerdict,
    ideas_tried,
    judge,
    label_regimes,
)
from backtest.hypotheses import REGISTRY
from backtest.periods import HOLDOUT_END, HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.run_daily import (
    LOOKS_PATH,
    pack,
    refuse_holdout,
    run_book,
    spy_days,
)
from backtest.run_gate import _calendar, _spy_closes, champion_record
from backtest.run_hypotheses import load_book
from backtest.scan import load_membership
from backtest.spells import build_spells, selection_hits

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
RULE_PATH = ROOT / "app" / "signal_rule.json"
ACTIVE_PATH = ROOT / "models" / "ACTIVE"
CHANGELOG_PATH = ROOT / "models" / "CHANGELOG.md"
LOG_PATH = RESEARCH / "RESEARCH_LOG.md"
SUMMARY_PATH = RESEARCH / "cost_summary.json"
SELECTION_PATH = RESEARCH / "cost_selection.json"
TABLE_PATH = RESEARCH / "cost_rerank.csv"

# Published tiered loss per trade was smaller than a US$1 round trip. The
# runner still scores every frozen hypothesis and the live book. This set is
# a label, not a filter.
MARGINAL_IDS = frozenset({"h4_opening_range", "h5_gap_down", "d_rs_leader"})


def _window(spells: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [spell for spell in spells if start <= spell["day"] <= end]


def _score(spells: list[dict[str, Any]], sessions: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result = run_book(spells, schedule=PRIMARY_SCHEDULE)
    packed = pack(result["trades"], spells, sessions, result["maxDrawdown"])
    return packed, list(result["trades"])


def _champion_spells(
    book: dict[tuple[str, date], list[dict[str, Any]]],
    start: date,
    end: date,
    *,
    holdout: bool,
) -> list[dict[str, Any]]:
    spec = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    hits = [
        hit
        for hit in load_membership()
        if hit["day"] is not None and start <= hit["day"] <= end
    ]
    if holdout:
        early = [hit["day"] for hit in hits if hit["day"] < HOLDOUT_START]
        if early:
            raise RuntimeError(f"champion holdout restatement includes {min(early)}")
    else:
        hits = [hit for hit in selection_hits(hits) if hit["day"] <= POOLED_END]
        refuse_holdout(hits, "champion")
    return build_spells(hits, book, spec)


def _evaluate(
    rule_id: str,
    family: str,
    spells: list[dict[str, Any]],
    days: list[date],
) -> dict[str, Any]:
    refuse_holdout(spells, rule_id)
    pooled_days = [day for day in days if POOLED_START <= day <= POOLED_END]
    validation_days = [day for day in days if VALIDATE_START <= day <= VALIDATE_END]
    primary, trades = _score(_window(spells, POOLED_START, POOLED_END), len(pooled_days))
    validation, _validation_trades = _score(
        _window(spells, VALIDATE_START, VALIDATE_END), len(validation_days)
    )
    print(f"{rule_id} {_money0(primary['net'])} trades {primary['trades']}", flush=True)
    return {
        "id": rule_id,
        "family": family,
        "marginal": rule_id in MARGINAL_IDS,
        "primary": primary,
        "validation": validation,
        "trades": trades,
    }


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


def _bps(value: float | None) -> str:
    if value is None:
        return "n/a"
    digits = 2 if abs(value) < 0.05 else 1
    sign = "−" if value < 0 else ""
    return f"{sign}{abs(value):.{digits}f} bp"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _positive(rows: list[dict[str, Any]], field: str) -> list[str]:
    return [row["id"] for row in rows if float(row[field]["net"]) > 0]


def _write_marked(path: Path, section: str, begin: str, end: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    start = existing.find(begin)
    stop = existing.find(end)
    if start >= 0 and stop >= start:
        updated = existing[:start] + section + existing[stop + len(end) :]
    else:
        updated = existing.rstrip() + "\n\n" + section + "\n"
    path.write_text(updated, encoding="utf-8")


def _selection_payload(rows: list[dict[str, Any]], finalist: str | None) -> dict[str, Any]:
    daily = [row for row in rows if row["family"] == "daily"]
    return {
        "cost_model": PRIMARY_SCHEDULE,
        "slip_bps_per_side": SLIP_BPS_MIN,
        "commission_usd": 0,
        "chosen_on": "validation signal coverage >= 95%, then validation net",
        "holdout_used": False,
        "finalist": finalist,
        "rows": [
            {
                "id": row["id"],
                "signal_day_frac": row["validation"]["signal_day_frac"],
                "net": row["validation"]["net"],
                "bps": row["validation"]["bps"] or 0.0,
            }
            for row in daily
        ],
    }


def _restatement(rule_id: str, packed: dict[str, Any], look: int) -> dict[str, Any]:
    return {
        "look": look,
        "id": rule_id,
        "used_to_rank": False,
        "net": packed["net"],
        "bps": packed["bps"],
        "per_trade": packed["per_trade"],
        "trades": packed["trades"],
        "win_rate": packed["win_rate"],
        "max_drawdown": packed["max_drawdown"],
        "signal_day_frac": packed["signal_day_frac"],
    }


def _holdout_champion() -> dict[str, Any]:
    book = load_book(include_holdout=True)
    days = spy_days(book, HOLDOUT_START, HOLDOUT_END)
    spells = _champion_spells(book, HOLDOUT_START, HOLDOUT_END, holdout=True)
    early = [spell["day"] for spell in spells if spell["day"] < HOLDOUT_START]
    if early:
        raise RuntimeError(f"champion holdout spell on {min(early)}")
    packed, _trades = _score(spells, len(days))
    return _restatement("appear_disappear_midmorning", packed, 2)


def _holdout_daily(rule_id: str) -> dict[str, Any]:
    rule = next(item for item in DAILY_REGISTRY if item.id == rule_id)
    book = load_book(include_holdout=True)
    sessions = build_sessions(book)
    days = spy_days(book, HOLDOUT_START, HOLDOUT_END)
    spells = rule.spells(sessions, days)
    early = [spell["day"] for spell in spells if spell["day"] < HOLDOUT_START]
    if early:
        raise RuntimeError(f"{rule_id} holdout spell on {min(early)}")
    packed, _trades = _score(spells, len(days))
    return _restatement(rule_id, packed, 3)


def _look_count() -> int:
    return sum(1 for _row in csv.DictReader(LOOKS_PATH.open(encoding="utf-8")))


def _ranking_note(rows: list[dict[str, Any]]) -> str:
    daily = sorted(
        (row for row in rows if row["family"] == "daily"),
        key=lambda row: -float(row["validation"]["net"]),
    )
    order = ", ".join(f"`{row['id']}` {_money0(row['validation']['net'])}" for row in daily)
    above = [row["id"] for row in daily if float(row["validation"]["net"]) > 0]
    if above:
        tail = "Validation nets above zero: " + ", ".join(f"`{item}`" for item in above) + ". "
    else:
        tail = (
            "Every validation net in that list is below zero, so the finalist is the smallest loss "
            "among rules that signaled on at least 95% of sessions. "
        )
    return (
        "Daily-frequency rank on the validation window, highest net first: "
        f"{order}. {tail}"
        "A pooled gain that the validation window does not confirm was not treated as a pass. "
        "The fresh slice stayed shut."
    )


def markdown(
    rows: list[dict[str, Any]],
    verdicts: dict[str, GateVerdict],
    finalist: str | None,
    tried: int,
    restatements: list[dict[str, Any]],
) -> str:
    primary_positive = _positive(rows, "primary")
    validation_positive = _positive(rows, "validation")
    lines = [
        COSTS_BEGIN,
        "## Slippage-only cost",
        "",
        "IBKR supplies the 5-minute bars and is not the broker. Execution is assumed "
        "on a zero-commission platform. The book is US$2,120, whole shares, no broker "
        f"commission, no regulatory fee, and {SLIP_BPS_MIN:.0f} bp slippage on the next bar's open. "
        "There is no IBKR commission column. Thresholds were not moved. The Bonferroni "
        f"denominator stays {tried}, because these are the same ideas under the corrected "
        "cost, not a new search. The daily finalist below was chosen on validation coverage "
        "and validation net, before either holdout restatement was loaded. "
        f"That finalist is `{finalist}`. "
        "Looks 2 and 3 were already on file. Their dollar results are restated under "
        "slippage only and were not used to rank. No new look was appended. "
        "`models/ACTIVE` stays `v0.1`. No order was placed.",
        "",
        "Pooled window 2023-01-01 through 2026-03-31. Positive means the portfolio net is above zero.",
        "",
        (
            "Positive after slippage: "
            + (", ".join(f"`{item}`" for item in primary_positive) if primary_positive else "none")
            + ". Positive on the validation window: "
            + (", ".join(f"`{item}`" for item in validation_positive) if validation_positive else "none")
            + "."
        ),
        "",
        _ranking_note(rows),
        "",
        "| Rule | Family | Trades | Win | Net | $/trade | bp | Windows | Decision |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        stats = row["primary"]
        verdict = verdicts.get(row["id"])
        if verdict is None:
            windows = "champion"
            decision = "reference"
        else:
            wins = sum(1 for window in verdict.windows if window.win)
            windows = f"{wins}/{len(verdict.windows)}"
            decision = verdict.decision.upper()
        lines.append(
            f"| {row['id']} | {row['family']} | {stats['trades']} | {_pct(stats['win_rate'])} | "
            f"{_money0(stats['net'])} | {_money(stats['per_trade'])} | {_bps(stats['bps'])} | "
            f"{windows} | {decision} |"
        )
    lines.append("")
    lines.append(
        "Validation window 2024-07-01 to 2026-03-31, daily rules only, the selection sample. "
        f"Finalist: `{finalist}`."
    )
    lines.append("")
    lines.append("| Rule | Signal days | Net | bp |")
    lines.append("| --- | ---: | ---: | ---: |")
    for row in rows:
        if row["family"] != "daily":
            continue
        validation = row["validation"]
        lines.append(
            f"| {row['id']} | {validation['signal_day_frac'] * 100:.1f}% | "
            f"{_money0(validation['net'])} | {_bps(validation['bps'])} |"
        )
    lines.append("")
    lines.append(
        "Re-ranked with the daily rules: the six frozen hypotheses and the live midmorning book. "
        "The three that were inside a dollar per trade under the old tiered commissions are "
        "`h4_opening_range`, `h5_gap_down`, and `d_rs_leader`. The others were scored on the "
        "same run so a near-miss was not dropped after the cost change."
    )
    if restatements:
        lines.append("")
        lines.append("Holdout restatements of looks already recorded. Not used to choose the finalist.")
        lines.append("")
        lines.append("| Look | Rule | Trades | Net | bp |")
        lines.append("| ---: | --- | ---: | ---: | ---: |")
        for item in restatements:
            lines.append(
                f"| {item['look']} | {item['id']} | {item['trades']} | "
                f"{_money0(item['net'])} | {_bps(item['bps'])} |"
            )
    lines.append(COSTS_END)
    return "\n".join(lines) + "\n"


def changelog_note(rows: list[dict[str, Any]], finalist: str | None) -> str:
    lines = [
        COSTS_CHANGELOG_BEGIN,
        "## Slippage-only cost — 2026-09-28 — no checkpoint",
        "",
        "IBKR is data only. The same frozen rules were re-scored with no commission "
        f"and {SLIP_BPS_MIN:.0f} bp slippage per side. No IBKR commission column. "
        f"The daily finalist on validation was `{finalist}`. None replaced v0.1. "
        "The live list was not edited and no order was placed.",
        "",
        "| Id | Net |",
        "| --- | ---: |",
    ]
    for row in rows:
        lines.append(f"| {row['id']} | {_money0(row['primary']['net'])} |")
    lines.append(COSTS_CHANGELOG_END)
    return "\n".join(lines) + "\n"


def _public_row(row: dict[str, Any], verdict: GateVerdict | None) -> dict[str, Any]:
    out = {
        "id": row["id"],
        "family": row["family"],
        "marginal": row["marginal"],
        "primary": row["primary"],
        "validation": row["validation"],
        "positive": row["primary"]["net"] > 0,
        "positive_validation": row["validation"]["net"] > 0,
    }
    if verdict is not None:
        out["decision"] = verdict.decision
        out["windows_won"] = sum(1 for window in verdict.windows if window.win)
        out["windows"] = len(verdict.windows)
        out["bars"] = verdict.bars
        out["reasons"] = verdict.reasons
        out["bootstrap_p"] = verdict.bootstrap_p
        out["permutation_p"] = verdict.permutation_p
    return out


def _write_table(rows: list[dict[str, Any]], verdicts: dict[str, GateVerdict]) -> None:
    RESEARCH.mkdir(parents=True, exist_ok=True)
    with TABLE_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "family",
                "marginal",
                "trades",
                "win_rate",
                "signal_day_frac",
                "net",
                "per_trade",
                "bps",
                "per_day",
                "max_dd",
                "validation_net",
                "validation_bps",
                "positive",
                "positive_validation",
                "windows_won",
                "decision",
            ],
        )
        writer.writeheader()
        for row in rows:
            stats = row["primary"]
            verdict = verdicts.get(row["id"])
            writer.writerow(
                {
                    "id": row["id"],
                    "family": row["family"],
                    "marginal": row["marginal"],
                    "trades": stats["trades"],
                    "win_rate": stats["win_rate"],
                    "signal_day_frac": stats["signal_day_frac"],
                    "net": stats["net"],
                    "per_trade": stats["per_trade"],
                    "bps": stats["bps"],
                    "per_day": stats["per_day"],
                    "max_dd": stats["max_drawdown"],
                    "validation_net": row["validation"]["net"],
                    "validation_bps": row["validation"]["bps"],
                    "positive": stats["net"] > 0,
                    "positive_validation": row["validation"]["net"] > 0,
                    "windows_won": "" if verdict is None else sum(1 for window in verdict.windows if window.win),
                    "decision": "reference" if verdict is None else verdict.decision,
                }
            )


def main() -> None:
    looks_before = _look_count()
    rule_before = RULE_PATH.read_bytes()
    if ACTIVE_PATH.read_text(encoding="utf-8").strip() != "v0.1":
        raise SystemExit("refusing to score costs while ACTIVE is not v0.1")
    if PRIMARY_SCHEDULE != "zero":
        raise SystemExit("refusing to score while the cost config is not the zero schedule")
    book = load_book()
    days = spy_days(book, date(2023, 1, 1), POOLED_END)
    print("building champion spells", flush=True)
    champion_spells = _champion_spells(book, POOLED_START, POOLED_END, holdout=False)
    rows = [_evaluate("appear_disappear_midmorning", "champion", champion_spells, days)]
    for item in REGISTRY:
        print(f"building {item.id}", flush=True)
        rows.append(_evaluate(item.id, "hypothesis", item.spells(book), days))
    print("building daily sessions", flush=True)
    sessions = build_sessions(book)
    for rule in DAILY_REGISTRY:
        rows.append(_evaluate(rule.id, "daily", rule.spells(sessions, days), days))

    finalist = choose_finalist(
        [
            {
                "id": row["id"],
                "signal_day_frac": row["validation"]["signal_day_frac"],
                "net": row["validation"]["net"],
                "bps": row["validation"]["bps"] or 0.0,
            }
            for row in rows
            if row["family"] == "daily"
        ]
    )
    SELECTION_PATH.write_text(
        json.dumps(_selection_payload(rows, finalist), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"finalist {finalist} written before any holdout restatement", flush=True)

    calendar = _calendar(book)
    regimes = label_regimes(_spy_closes(book), POOLED_START, POOLED_END)
    tried = ideas_tried()
    champion_trades = rows[0]["trades"]
    verdicts: dict[str, GateVerdict] = {}
    for row in rows:
        if row["family"] == "champion":
            continue
        verdict = judge(
            row["id"],
            champion_trades,
            row["trades"],
            calendar=calendar,
            regimes=regimes,
            ideas_tried=tried,
        )
        verdicts[row["id"]] = verdict
        wins = sum(1 for window in verdict.windows if window.win)
        print(f"  gate {row['id']} {verdict.decision} {wins}/{len(verdict.windows)}", flush=True)
        if verdict.passed:
            raise SystemExit("a rule passed with the fresh slice still closed; refusing to promote")

    restatements = [_holdout_champion(), _holdout_daily("d_rs_leader")]
    if _look_count() != looks_before:
        raise SystemExit("holdout look count changed during a cost restatement")
    if ACTIVE_PATH.read_text(encoding="utf-8").strip() != "v0.1":
        raise SystemExit("ACTIVE changed during the run")
    if RULE_PATH.read_bytes() != rule_before:
        raise SystemExit("live signal rule was modified")
    if champion_record().get("replaced"):
        raise SystemExit("champion record was replaced")

    summary = {
        "primary": PRIMARY_SCHEDULE,
        "commission_usd": 0,
        "regulatory_fees": False,
        "slip_bps_per_side": SLIP_BPS_MIN,
        "ideas_tried": tried,
        "finalist": finalist,
        "holdout_used_to_rank": False,
        "positive": _positive(rows, "primary"),
        "positive_validation": _positive(rows, "validation"),
        "rows": [_public_row(row, verdicts.get(row["id"])) for row in rows],
        "holdout_restatements": restatements,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    _write_table(rows, verdicts)
    _write_marked(LOG_PATH, markdown(rows, verdicts, finalist, tried, restatements), COSTS_BEGIN, COSTS_END)
    _write_marked(
        CHANGELOG_PATH,
        changelog_note(rows, finalist),
        COSTS_CHANGELOG_BEGIN,
        COSTS_CHANGELOG_END,
    )
    print("cost rerank written; champion untouched; no new holdout look", flush=True)


if __name__ == "__main__":
    main()
