"""Re-score frozen rules on the owner's commission-free account.

Primary schedule is ``regulatory``: US$0 broker commission, 2 bp slippage on
the next bar's open, and the SEC and FINRA fees on sells. Secondary schedule
is ``fixed``: IBKR Pro at US$0.005 per share with a US$1 minimum, plus the
same slippage and regulatory fees.

The daily-frequency ranking uses the validation window only. This command
does not append ``research/holdout_looks.csv``. Numbers for looks 2 and 3 are
the same already-opened trades, restated under the new fees, and are not used
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
    SENSITIVITY_SCHEDULE,
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

# Published tiered loss per trade was smaller than a US$1 round trip, so the
# broker minimum could have been the whole result. The runner still scores
# every frozen hypothesis and the live book. This set is a label, not a filter.
MARGINAL_IDS = frozenset({"h4_opening_range", "h5_gap_down", "d_rs_leader"})


def _window(spells: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [spell for spell in spells if start <= spell["day"] <= end]


def _score(spells: list[dict[str, Any]], sessions: int, schedule: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result = run_book(spells, schedule=schedule)
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
    pooled_spells = _window(spells, POOLED_START, POOLED_END)
    validation_spells = _window(spells, VALIDATE_START, VALIDATE_END)
    regulatory, trades = _score(pooled_spells, len(pooled_days), PRIMARY_SCHEDULE)
    fixed, _fixed_trades = _score(pooled_spells, len(pooled_days), SENSITIVITY_SCHEDULE)
    validation_regulatory, _validation_trades = _score(
        validation_spells, len(validation_days), PRIMARY_SCHEDULE
    )
    validation_fixed, _ = _score(validation_spells, len(validation_days), SENSITIVITY_SCHEDULE)
    print(
        f"{rule_id} regulatory {_money0(regulatory['net'])} "
        f"fixed {_money0(fixed['net'])} trades {regulatory['trades']}",
        flush=True,
    )
    return {
        "id": rule_id,
        "family": family,
        "marginal": rule_id in MARGINAL_IDS,
        "regulatory": regulatory,
        "fixed": fixed,
        "validation_regulatory": validation_regulatory,
        "validation_fixed": validation_fixed,
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
        "sensitivity": SENSITIVITY_SCHEDULE,
        "chosen_on": "validation signal coverage >= 95%, then validation regulatory net",
        "holdout_used": False,
        "finalist": finalist,
        "rows": [
            {
                "id": row["id"],
                "signal_day_frac": row["validation_regulatory"]["signal_day_frac"],
                "net": row["validation_regulatory"]["net"],
                "bps": row["validation_regulatory"]["bps"] or 0.0,
                "fixed_net": row["validation_fixed"]["net"],
            }
            for row in daily
        ],
    }


def _restatement(rule_id: str, packed: dict[str, Any], fixed_net: float, look: int) -> dict[str, Any]:
    return {
        "look": look,
        "id": rule_id,
        "used_to_rank": False,
        "regulatory_net": packed["net"],
        "regulatory_bps": packed["bps"],
        "regulatory_per_trade": packed["per_trade"],
        "trades": packed["trades"],
        "win_rate": packed["win_rate"],
        "max_drawdown": packed["max_drawdown"],
        "signal_day_frac": packed["signal_day_frac"],
        "fixed_net": fixed_net,
    }


def _holdout_champion() -> dict[str, Any]:
    book = load_book(include_holdout=True)
    days = spy_days(book, HOLDOUT_START, HOLDOUT_END)
    spells = _champion_spells(book, HOLDOUT_START, HOLDOUT_END, holdout=True)
    early = [spell["day"] for spell in spells if spell["day"] < HOLDOUT_START]
    if early:
        raise RuntimeError(f"champion holdout spell on {min(early)}")
    packed, _trades = _score(spells, len(days), PRIMARY_SCHEDULE)
    fixed, _ = _score(spells, len(days), SENSITIVITY_SCHEDULE)
    return _restatement("appear_disappear_midmorning", packed, fixed["net"], 2)


def _holdout_daily(rule_id: str) -> dict[str, Any]:
    rule = next(item for item in DAILY_REGISTRY if item.id == rule_id)
    book = load_book(include_holdout=True)
    sessions = build_sessions(book)
    days = spy_days(book, HOLDOUT_START, HOLDOUT_END)
    spells = rule.spells(sessions, days)
    early = [spell["day"] for spell in spells if spell["day"] < HOLDOUT_START]
    if early:
        raise RuntimeError(f"{rule_id} holdout spell on {min(early)}")
    packed, _trades = _score(spells, len(days), PRIMARY_SCHEDULE)
    fixed, _ = _score(spells, len(days), SENSITIVITY_SCHEDULE)
    return _restatement(rule_id, packed, fixed["net"], 3)


def _look_count() -> int:
    return sum(1 for _row in csv.DictReader(LOOKS_PATH.open(encoding="utf-8")))


def _ranking_note(rows: list[dict[str, Any]]) -> str:
    daily = sorted(
        (row for row in rows if row["family"] == "daily"),
        key=lambda row: -float(row["validation_regulatory"]["net"]),
    )
    order = ", ".join(
        f"`{row['id']}` {_money0(row['validation_regulatory']['net'])}" for row in daily
    )
    return (
        "Daily-frequency rank on the validation window under commission-free costs, "
        f"highest net first: {order}. "
        "Every validation net in that list is below zero, so the finalist is the smallest loss "
        "among rules that signaled on at least 95% of sessions. "
        "A pooled gain that the validation window does not confirm was not treated as a pass. "
        "The two pooled gains still failed the promotion gate, and the fresh slice stayed shut."
    )


def markdown(
    rows: list[dict[str, Any]],
    verdicts: dict[str, GateVerdict],
    finalist: str | None,
    tried: int,
    restatements: list[dict[str, Any]],
) -> str:
    primary_positive = _positive(rows, "regulatory")
    fixed_positive = _positive(rows, "fixed")
    validation_positive = _positive(rows, "validation_regulatory")
    lines = [
        COSTS_BEGIN,
        "## Commission-free primary",
        "",
        "The owner reports zero broker commissions. The primary book is "
        "US$2,120, whole shares, US$0 broker commission, 2 bp slippage on the "
        "next bar's open, and the SEC fee plus FINRA TAF on sells. "
        "The secondary column is IBKR Pro fixed: US$0.005 per share with a "
        "US$1 minimum, plus the same slippage and regulatory fees. "
        "Thresholds were not moved. The Bonferroni denominator stays "
        f"{tried}, because these are the same ideas under a corrected fee, not a new search. "
        "The daily finalist below was chosen on validation coverage and validation "
        "regulatory net, before either holdout restatement was loaded. "
        f"That finalist is `{finalist}`. "
        "Looks 2 and 3 were already on file. Their dollar results are restated "
        "under the new fees and were not used to rank. No new look was appended. "
        "`models/ACTIVE` stays `v0.1`. No order was placed.",
        "",
        "Pooled window 2023-01-01 through 2026-03-31. "
        "Positive means the portfolio net is above zero.",
        "",
        (
            "Positive under commission-free costs: "
            + (", ".join(f"`{item}`" for item in primary_positive) if primary_positive else "none")
            + ". Positive under IBKR Pro fixed commissions: "
            + (", ".join(f"`{item}`" for item in fixed_positive) if fixed_positive else "none")
            + ". Positive on the validation window under commission-free costs: "
            + (", ".join(f"`{item}`" for item in validation_positive) if validation_positive else "none")
            + "."
        ),
        "",
        _ranking_note(rows),
        "",
        "| Rule | Family | Trades | Win | Commission-free net | $/trade | bp | Fixed net | Windows | Decision |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        stats = row["regulatory"]
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
            f"{_money0(row['fixed']['net'])} | {windows} | {decision} |"
        )
    lines.append("")
    lines.append(
        "Validation window 2024-07-01 to 2026-03-31, daily rules only, the selection sample. "
        f"Finalist under commission-free costs: `{finalist}`."
    )
    lines.append("")
    lines.append("| Rule | Signal days | Commission-free net | Fixed net |")
    lines.append("| --- | ---: | ---: | ---: |")
    for row in rows:
        if row["family"] != "daily":
            continue
        validation = row["validation_regulatory"]
        lines.append(
            f"| {row['id']} | {validation['signal_day_frac'] * 100:.1f}% | "
            f"{_money0(validation['net'])} | {_money0(row['validation_fixed']['net'])} |"
        )
    lines.append("")
    lines.append(
        "Marginal after the old tiered commissions, from the already published "
        "loss per trade being smaller than US$1: `h4_opening_range`, `h5_gap_down`, "
        "and `d_rs_leader`. The other hypotheses and the live book were re-scored "
        "on the same run so a near-miss was not dropped after seeing the new fees."
    )
    if restatements:
        lines.append("")
        lines.append(
            "Holdout restatements of looks already recorded. Not used to choose the finalist."
        )
        lines.append("")
        lines.append("| Look | Rule | Trades | Commission-free net | bp | Fixed net |")
        lines.append("| ---: | --- | ---: | ---: | ---: | ---: |")
        for item in restatements:
            lines.append(
                f"| {item['look']} | {item['id']} | {item['trades']} | "
                f"{_money0(item['regulatory_net'])} | {_bps(item['regulatory_bps'])} | "
                f"{_money0(item['fixed_net'])} |"
            )
    lines.append(COSTS_END)
    return "\n".join(lines) + "\n"


def changelog_note(rows: list[dict[str, Any]], finalist: str | None) -> str:
    lines = [
        COSTS_CHANGELOG_BEGIN,
        "## Commission-free costs — 2026-09-28 — no checkpoint",
        "",
        "The same frozen rules were re-scored with US$0 broker commission as the "
        "primary cost and IBKR Pro fixed commissions as a sensitivity column. "
        f"The daily finalist on validation was `{finalist}`. None replaced v0.1. "
        "The live list was not edited and no order was placed.",
        "",
        "| Id | Commission-free net | Fixed net |",
        "| --- | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['id']} | {_money0(row['regulatory']['net'])} | {_money0(row['fixed']['net'])} |"
        )
    lines.append(COSTS_CHANGELOG_END)
    return "\n".join(lines) + "\n"


def _public_row(row: dict[str, Any], verdict: GateVerdict | None) -> dict[str, Any]:
    out = {
        "id": row["id"],
        "family": row["family"],
        "marginal": row["marginal"],
        "regulatory": row["regulatory"],
        "fixed": row["fixed"],
        "validation_regulatory": row["validation_regulatory"],
        "validation_fixed": row["validation_fixed"],
        "positive_regulatory": row["regulatory"]["net"] > 0,
        "positive_fixed": row["fixed"]["net"] > 0,
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
                "regulatory_net",
                "regulatory_per_trade",
                "regulatory_bps",
                "regulatory_per_day",
                "regulatory_max_dd",
                "fixed_net",
                "fixed_per_trade",
                "fixed_bps",
                "validation_regulatory_net",
                "validation_fixed_net",
                "positive_regulatory",
                "positive_fixed",
                "windows_won",
                "decision",
            ],
        )
        writer.writeheader()
        for row in rows:
            stats = row["regulatory"]
            verdict = verdicts.get(row["id"])
            writer.writerow(
                {
                    "id": row["id"],
                    "family": row["family"],
                    "marginal": row["marginal"],
                    "trades": stats["trades"],
                    "win_rate": stats["win_rate"],
                    "signal_day_frac": stats["signal_day_frac"],
                    "regulatory_net": stats["net"],
                    "regulatory_per_trade": stats["per_trade"],
                    "regulatory_bps": stats["bps"],
                    "regulatory_per_day": stats["per_day"],
                    "regulatory_max_dd": stats["max_drawdown"],
                    "fixed_net": row["fixed"]["net"],
                    "fixed_per_trade": row["fixed"]["per_trade"],
                    "fixed_bps": row["fixed"]["bps"],
                    "validation_regulatory_net": row["validation_regulatory"]["net"],
                    "validation_fixed_net": row["validation_fixed"]["net"],
                    "positive_regulatory": stats["net"] > 0,
                    "positive_fixed": row["fixed"]["net"] > 0,
                    "windows_won": "" if verdict is None else sum(1 for window in verdict.windows if window.win),
                    "decision": "reference" if verdict is None else verdict.decision,
                }
            )


def main() -> None:
    looks_before = _look_count()
    rule_before = RULE_PATH.read_bytes()
    if ACTIVE_PATH.read_text(encoding="utf-8").strip() != "v0.1":
        raise SystemExit("refusing to score costs while ACTIVE is not v0.1")
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
                "signal_day_frac": row["validation_regulatory"]["signal_day_frac"],
                "net": row["validation_regulatory"]["net"],
                "bps": row["validation_regulatory"]["bps"] or 0.0,
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
        "sensitivity": SENSITIVITY_SCHEDULE,
        "slip_bps": 2,
        "ideas_tried": tried,
        "finalist": finalist,
        "holdout_used_to_rank": False,
        "positive_regulatory": _positive(rows, "regulatory"),
        "positive_fixed": _positive(rows, "fixed"),
        "positive_validation_regulatory": _positive(rows, "validation_regulatory"),
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
