"""Score the four research areas. Does not read the holdout and does not replace the champion.

``python -m backtest.run_areas`` runs every id in ``backtest.areas`` through the
promotion gate on 2023-01-01 through 2026-03-31. The fresh slice stays closed.
A rejection leaves ``models/ACTIVE`` at v0.1 and does not mint a checkpoint.

Nothing here places an order.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from backtest.areas import (
    AREAS_BEGIN,
    AREAS_END,
    AREA_REGISTRY,
    CHANGELOG_BEGIN,
    CHANGELOG_END,
    Area,
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
from backtest.periods import HOLDOUT_START
from backtest.run_gate import _calendar, _spy_closes
from backtest.run_hypotheses import load_book
from backtest.scan import load_membership
from backtest.spells import ACCOUNT_USD, SLIP_BPS, build_spells, portfolio, selection_hits

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
RULE_PATH = ROOT / "app" / "signal_rule.json"
ACTIVE_PATH = ROOT / "models" / "ACTIVE"
CHANGELOG_PATH = ROOT / "models" / "CHANGELOG.md"
LOG_PATH = RESEARCH / "RESEARCH_LOG.md"

# Same confirm and exit as the live rule, wide enough for every clock under test.
# 9:45 is the first minute the scorer can list. 15:30 is the end of the last-hour window.
CLOCK_FROM = 9 * 60 + 45
CLOCK_TO = 15 * 60 + 30
REPORT_FOLDS: list[tuple[str, date, date]] = list(HALF_YEARS) + [
    ("2026Q1", date(2026, 1, 1), date(2026, 3, 31)),
]


def refuse_holdout(rows: list[dict[str, Any]], label: str) -> None:
    leaked = [row["day"] for row in rows if row["day"] >= HOLDOUT_START]
    if leaked:
        raise RuntimeError(f"{label} includes holdout day {min(leaked)}")


def _hits() -> list[dict[str, Any]]:
    hits = [
        hit
        for hit in selection_hits(load_membership())
        if POOLED_START <= hit["day"] <= POOLED_END
    ]
    refuse_holdout(hits, "membership")
    return hits


def _rule() -> dict[str, Any]:
    return json.loads(RULE_PATH.read_text(encoding="utf-8"))


def champion_spells(
    book: dict[tuple[str, date], list[dict[str, Any]]], hits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    spells = build_spells(hits, book, _rule())
    refuse_holdout(spells, "champion spells")
    return spells


def clock_spells(
    book: dict[tuple[str, date], list[dict[str, Any]]], hits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    spec = dict(_rule())
    spec["minute_from"] = CLOCK_FROM
    spec["minute_to"] = CLOCK_TO
    spells = build_spells(hits, book, spec)
    refuse_holdout(spells, "clock spells")
    return spells


def _run_portfolio(spells: list[dict[str, Any]], kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    refuse_holdout(spells, "portfolio")
    result = portfolio(
        spells,
        use_stop=True,
        schedule="tiered",
        equity=ACCOUNT_USD,
        slip_bps=SLIP_BPS,
        **kwargs,
    )
    trades = list(result["trades"])
    refuse_holdout(trades, "trades")
    return trades


def _fold_rows(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for name, start, end in REPORT_FOLDS:
        kept = [trade for trade in trades if start <= trade["day"] <= end]
        stats = slice_stats(kept)
        rows.append(
            {
                "fold": name,
                "vote": name != "2026Q1",
                "trades": stats.trades,
                "net": stats.net,
                "expectancy": stats.expectancy,
                "avg_bps": stats.avg_bps,
            }
        )
    return rows


def evaluate(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Pre-holdout bars only. Does not load a day on or after the holdout."""
    if any(day >= HOLDOUT_START for (_symbol, day) in book):
        raise RuntimeError("book contains a holdout day")
    hits = _hits()
    champion_rows = champion_spells(book, hits)
    clock_rows = clock_spells(book, hits)
    champion = _run_portfolio(champion_rows, {})
    print(f"champion trades {len(champion)} net {sum(trade['net'] for trade in champion):.0f}", flush=True)
    tried = ideas_tried()
    calendar = _calendar(book)
    regimes = label_regimes(_spy_closes(book), POOLED_START, POOLED_END)
    rows = []
    for area in AREA_REGISTRY:
        source = clock_rows if area.uses_clock else champion_rows
        prepared = area.prepare(source, book, champion)
        print(f"{area.id} spells {len(prepared.spells)}", flush=True)
        trades = _run_portfolio(prepared.spells, prepared.kwargs)
        verdict = judge(
            area.id,
            champion,
            trades,
            calendar=calendar,
            regimes=regimes,
            ideas_tried=tried,
        )
        wins = sum(1 for window in verdict.windows if window.win)
        print(
            f"  {verdict.decision}: windows {wins}/{len(verdict.windows)} "
            f"net {verdict.challenger_pooled.net:.0f} vs {verdict.champion_pooled.net:.0f}",
            flush=True,
        )
        rows.append(
            {
                "area": area,
                "verdict": verdict,
                "note": prepared.note,
                "folds": _fold_rows(trades),
                "trades": trades,
            }
        )
    ready = [
        row["verdict"].candidate_id
        for row in rows
        if row["verdict"].bars["walk_forward"] and row["verdict"].bars["consistency"]
    ]
    if ready:
        print(f"pre-holdout bars passed for {ready}; holdout left shut", flush=True)
    return rows


def _bps(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} bp"


def _money(stats: Any) -> str:
    return f"${stats.net:.0f} on {stats.trades} trades, {_bps(stats.avg_bps)}"


def areas_markdown(rows: list[dict[str, Any]], tried: int) -> str:
    lines = [
        AREAS_BEGIN,
        "## Research areas",
        "",
        "Four areas, fifteen pre-registered overlays. Sizing, liquidity, and regime keep the live "
        "10:00–11:00 signals. Time-of-day keeps the same confirm, exit lag, and stop, and keeps a spell "
        "only when the on-list bar is inside that clock. The 10:00–11:00 clock is the champion and is not "
        "retested. Costs: US$2,120, tiered commissions, hard stop, flat by 15:55. Slippage is 2 bp except "
        "where a liquidity rule adds a spread or an impact. "
        f"Bonferroni denominator, including these fifteen ids: {tried}. "
        "The holdout from 2026-04-01 was not opened. Look count remains 2. "
        "`models/ACTIVE` stays `v0.1`. No checkpoint was issued.",
        "",
        "Rules are in `research/GATE.md`. A window win needs at least 20 challenger trades and a better "
        "net, a better dollar expectancy, and a better per-trade basis-point expectancy than the champion. "
        "2026Q1 is inside the pooled sample and is not its own vote. An empty book does not beat a loss, "
        "so a Kelly fraction of zero is a rejection, not a live rule that trades nothing.",
        "",
        "| Candidate | Area | Pooled challenger | Windows | Bootstrap p | Permutation p | Decision |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        verdict: GateVerdict = row["verdict"]
        wins = sum(1 for window in verdict.windows if window.win)
        lines.append(
            f"| {verdict.candidate_id} | {row['area'].area} | {_money(verdict.challenger_pooled)} | "
            f"{wins}/{len(verdict.windows)} | {verdict.bootstrap_p:.4f} | {verdict.permutation_p:.4f} | "
            f"{verdict.decision.upper()} |"
        )
    lines.append("")
    for row in rows:
        area: Area = row["area"]
        verdict = row["verdict"]
        lines.extend(
            [
                f"### {area.id}",
                "",
                f"**Area.** {area.area}.",
                "",
                f"**Source.** {area.source}",
                "",
                f"**Hypothesis.** {area.hypothesis}",
                "",
                f"**Economic rationale.** {area.rationale}",
                "",
                f"**Test setup.** {area.setup}",
                "",
                f"**Sample note.** {row['note']}",
                "",
                f"**Walk-forward.** Challenger {_money(verdict.challenger_pooled)}. "
                f"Champion {_money(verdict.champion_pooled)} "
                f"(${verdict.champion_pooled.expectancy if verdict.champion_pooled.expectancy is not None else float('nan'):.2f}/trade).",
                "",
                "Half-years are votes. 2026Q1 is reported and is not a vote.",
                "",
                "| Fold | Trades | Net | Avg | Vote |",
                "| --- | ---: | ---: | ---: | --- |",
            ]
        )
        for fold in row["folds"]:
            lines.append(
                f"| {fold['fold']} | {fold['trades']} | ${fold['net']:.0f} | {_bps(fold['avg_bps'])} | "
                f"{'yes' if fold['vote'] else 'no'} |"
            )
        lines.extend(
            [
                "",
                f"**Decision.** {'Rejected' if verdict.decision == 'rejected' else 'Promoted'}. "
                + " ".join(verdict.reasons),
                "",
                "**Holdout.** Not checked in this batch.",
                "",
            ]
        )
    lines.append(AREAS_END)
    return "\n".join(lines)


def changelog_note(rows: list[dict[str, Any]]) -> str:
    adopted = [row["verdict"].candidate_id for row in rows if row["verdict"].decision == "promoted"]
    lines = [
        CHANGELOG_BEGIN,
        "## Research areas — 2026-09-28 — no checkpoint",
        "",
        "Fifteen pre-registered overlays were scored on the promotion gate: position size and risk, "
        "time of day, liquidity, and market regime. "
        + (
            "Every one was rejected. "
            if not adopted
            else f"Pre-holdout bars passed for {', '.join(adopted)}, and the holdout was still not opened. "
        )
        + "`models/ACTIVE` stays `v0.1`. No v1 checkpoint was written and the `v0.1` tag was not moved. "
        "The write-up is the research-areas section of `research/RESEARCH_LOG.md`.",
        "",
        "| Id | Trades | Net | Windows | Decision |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        verdict: GateVerdict = row["verdict"]
        wins = sum(1 for window in verdict.windows if window.win)
        lines.append(
            f"| {verdict.candidate_id} | {verdict.challenger_pooled.trades} | "
            f"${verdict.challenger_pooled.net:.0f} | {wins}/{len(verdict.windows)} | {verdict.decision} |"
        )
    lines.append(CHANGELOG_END)
    return "\n".join(lines)


def _write_log(section: str) -> None:
    existing = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
    begin = existing.find(AREAS_BEGIN)
    end = existing.find(AREAS_END)
    if begin >= 0 and end >= begin:
        updated = existing[:begin] + section + existing[end + len(AREAS_END) :]
    else:
        updated = existing.rstrip() + "\n\n" + section + "\n"
    LOG_PATH.write_text(updated, encoding="utf-8")


def _write_changelog(section: str) -> None:
    existing = CHANGELOG_PATH.read_text(encoding="utf-8") if CHANGELOG_PATH.exists() else ""
    begin = existing.find(CHANGELOG_BEGIN)
    end = existing.find(CHANGELOG_END)
    if begin >= 0 and end >= begin:
        updated = existing[:begin] + section + existing[end + len(CHANGELOG_END) :]
    else:
        updated = existing.rstrip() + "\n\n" + section + "\n"
    CHANGELOG_PATH.write_text(updated, encoding="utf-8")


def _write_tables(rows: list[dict[str, Any]], tried: int) -> None:
    import csv

    RESEARCH.mkdir(parents=True, exist_ok=True)
    with (RESEARCH / "areas.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "area",
                "decision",
                "trades",
                "net",
                "expectancy",
                "bps",
                "champion_net",
                "champion_expectancy",
                "champion_bps",
                "windows_won",
                "windows",
                "bootstrap_p",
                "permutation_p",
                "alpha",
                "ideas_tried",
                "note",
                "reasons",
            ],
        )
        writer.writeheader()
        for row in rows:
            verdict: GateVerdict = row["verdict"]
            chall = verdict.challenger_pooled
            champ = verdict.champion_pooled
            writer.writerow(
                {
                    "id": verdict.candidate_id,
                    "area": row["area"].area,
                    "decision": verdict.decision,
                    "trades": chall.trades,
                    "net": f"{chall.net:.2f}",
                    "expectancy": "" if chall.expectancy is None else f"{chall.expectancy:.4f}",
                    "bps": "" if chall.avg_bps is None else f"{chall.avg_bps:.2f}",
                    "champion_net": f"{champ.net:.2f}",
                    "champion_expectancy": "" if champ.expectancy is None else f"{champ.expectancy:.4f}",
                    "champion_bps": "" if champ.avg_bps is None else f"{champ.avg_bps:.2f}",
                    "windows_won": sum(1 for window in verdict.windows if window.win),
                    "windows": len(verdict.windows),
                    "bootstrap_p": f"{verdict.bootstrap_p:.6f}",
                    "permutation_p": f"{verdict.permutation_p:.6f}",
                    "alpha": f"{verdict.alpha:.6f}",
                    "ideas_tried": tried,
                    "note": row["note"],
                    "reasons": " ".join(verdict.reasons),
                }
            )
    with (RESEARCH / "area_folds.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "fold", "vote", "trades", "net", "avg_bps"],
        )
        writer.writeheader()
        for row in rows:
            for fold in row["folds"]:
                writer.writerow(
                    {
                        "id": row["verdict"].candidate_id,
                        "fold": fold["fold"],
                        "vote": fold["vote"],
                        "trades": fold["trades"],
                        "net": f"{fold['net']:.2f}",
                        "avg_bps": "" if fold["avg_bps"] is None else f"{fold['avg_bps']:.2f}",
                    }
                )
    summary = {
        "champion": "appear_disappear_midmorning",
        "activeUnchanged": True,
        "checkpointIssued": False,
        "holdoutReadThisBatch": False,
        "ideasTried": tried,
        "areas": [
            {
                "id": row["verdict"].candidate_id,
                "area": row["area"].area,
                "decision": row["verdict"].decision,
                "trades": row["verdict"].challenger_pooled.trades,
                "net": row["verdict"].challenger_pooled.net,
                "bps": row["verdict"].challenger_pooled.avg_bps,
                "windowsWon": sum(1 for window in row["verdict"].windows if window.win),
            }
            for row in rows
        ],
    }
    (RESEARCH / "area_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    if any("holdout" in arg or "milestone" in arg for arg in __import__("sys").argv[1:]):
        raise SystemExit("refusing a holdout read")
    active = ACTIVE_PATH.read_text(encoding="utf-8").strip()
    if active != "v0.1":
        raise SystemExit(f"ACTIVE is {active}, expected v0.1")
    rule_before = RULE_PATH.read_bytes()
    book = load_book()
    rows = evaluate(book)
    if any(row["verdict"].passed for row in rows):
        raise SystemExit("a challenger passed with the fresh slice still closed; refusing to promote")
    if ACTIVE_PATH.read_text(encoding="utf-8").strip() != "v0.1":
        raise SystemExit("ACTIVE changed during the run")
    if RULE_PATH.read_bytes() != rule_before:
        raise SystemExit("live signal rule was modified")
    tried = ideas_tried()
    _write_log(areas_markdown(rows, tried))
    _write_tables(rows, tried)
    _write_changelog(changelog_note(rows))
    print(f"wrote {LOG_PATH}", flush=True)
    print("champion untouched; holdout not read; no checkpoint", flush=True)


if __name__ == "__main__":
    main()
