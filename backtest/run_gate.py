"""Run the promotion gate. Does not read the holdout and does not replace the champion.

``python -m backtest.run_gate`` scores every hypothesis in the registry against
the live champion on 2023-01-01 through 2026-03-31. Bar 2 stays closed: the
fresh slice is the locked holdout, and it is read only inside ``fresh_slice``
after exactly one challenger has passed the other bars alone.

Nothing here places an order.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from backtest.gate import (
    GATE_BEGIN,
    GATE_END,
    HALF_YEARS,
    POOLED_END,
    POOLED_START,
    TICKER_GROUPS,
    GateVerdict,
    ideas_tried,
    judge,
    label_regimes,
    promote,
)
from backtest.hypotheses import REGISTRY
from backtest.periods import HOLDOUT_START
from backtest.run_hypotheses import load_book
from backtest.scan import load_membership
from backtest.costs import PRIMARY_SCHEDULE
from backtest.spells import ACCOUNT_USD, SLIP_BPS, build_spells, portfolio, selection_hits

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
RULE_PATH = ROOT / "app" / "signal_rule.json"
CHAMPION_PATH = RESEARCH / "champion.json"
LOG_PATH = RESEARCH / "RESEARCH_LOG.md"

CHAMPION_ID = "appear_disappear_midmorning"


def champion_record() -> dict[str, Any]:
    if CHAMPION_PATH.exists():
        return json.loads(CHAMPION_PATH.read_text(encoding="utf-8"))
    return {
        "id": CHAMPION_ID,
        "signalRule": "app/signal_rule.json",
        "signalRuleId": "midmorning",
        "replaced": False,
        "note": "Live list. Replaced only when backtest.gate.promote accepts a verdict.",
    }


def _spy_closes(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[tuple[date, float]]:
    closes = []
    for (symbol, day), bars in book.items():
        if symbol != "SPY" or not bars:
            continue
        closes.append((day, float(bars[-1]["close"])))
    return closes


def _calendar(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[date]:
    days = [
        day
        for (symbol, day) in book
        if symbol == "SPY" and POOLED_START <= day <= POOLED_END and day < HOLDOUT_START
    ]
    return sorted(set(days))


def _trades(spells: list[dict[str, Any]], schedule: str = PRIMARY_SCHEDULE) -> list[dict[str, Any]]:
    kept = [spell for spell in spells if POOLED_START <= spell["day"] <= POOLED_END]
    if any(spell["day"] >= HOLDOUT_START for spell in kept):
        raise RuntimeError("gate received a holdout spell")
    result = portfolio(kept, use_stop=True, schedule=schedule, equity=ACCOUNT_USD, slip_bps=SLIP_BPS)
    return list(result["trades"])


def champion_trades(
    book: dict[tuple[str, date], list[dict[str, Any]]],
    schedule: str = PRIMARY_SCHEDULE,
) -> list[dict[str, Any]]:
    spec = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    hits = [
        hit
        for hit in selection_hits(load_membership())
        if POOLED_START <= hit["day"] <= POOLED_END
    ]
    if any(hit["day"] >= HOLDOUT_START for hit in hits):
        raise RuntimeError("membership leaked a holdout row into the gate")
    spells = build_spells(hits, book, spec)
    return _trades(spells, schedule)


def challenger_trades(
    book: dict[tuple[str, date], list[dict[str, Any]]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    rows = []
    for item in REGISTRY:
        spells = item.spells(book)
        print(f"challenger {item.id} spells {len(spells)}", flush=True)
        rows.append((item.id, _trades(spells)))
    return rows


def fresh_slice(candidate_id: str, pre_verdicts: list[GateVerdict]) -> None:
    """Holdout read for the one challenger that already cleared the other bars.

    This batch does not call it. Opening it would append a holdout look.
    """
    ready = [verdict.candidate_id for verdict in pre_verdicts if verdict.bars["walk_forward"] and verdict.bars["consistency"]]
    if ready != [candidate_id]:
        raise RuntimeError(
            "refusing to open the holdout. "
            f"Passed the pre-holdout bars: {ready or 'none'}. "
            "The fresh slice is read only when exactly one challenger has passed alone."
        )
    raise RuntimeError(
        f"Holdout milestone for {candidate_id} is not implemented in this batch. "
        "The command stops before loading any day from 2026-04-01."
    )


def _fmt_window(verdict: GateVerdict) -> list[str]:
    lines = [
        "| Window | Challenger | Champion | Win |",
        "| --- | --- | --- | --- |",
    ]
    for window in verdict.windows:
        chall = window.challenger
        champ = window.champion
        chall_bps = "n/a" if chall.avg_bps is None else f"{chall.avg_bps:.1f} bp"
        champ_bps = "n/a" if champ.avg_bps is None else f"{champ.avg_bps:.1f} bp"
        flag = "yes" if window.win else "no"
        if window.severe:
            flag = "severe"
        lines.append(
            f"| {window.name} | ${chall.net:.0f}, {chall.trades} trades, {chall_bps} | "
            f"${champ.net:.0f}, {champ.trades} trades, {champ_bps} | {flag} |"
        )
    return lines


def gate_markdown(verdicts: list[GateVerdict], tried: int) -> str:
    lines = [
        GATE_BEGIN,
        "## Promotion gate",
        "",
        f"Champion: `{CHAMPION_ID}` (live rule `midmorning` in `app/signal_rule.json`). "
        "Costs: US$2,120, tiered commissions, 2 bp slippage, hard stop, flat by 15:55. "
        f"Ideas already tried, and therefore the Bonferroni denominator: {tried}. "
        "The holdout from 2026-04-01 was not opened. Look count remains 2. "
        "The champion file was not changed.",
        "",
        "Rules are in `research/GATE.md`. A window win needs at least 20 challenger trades and a better "
        "net, a better dollar expectancy, and a better per-trade basis-point expectancy than the champion. "
        "Voting windows are six half-years, four SPY regimes (up, down, high vol, low vol), and two ticker "
        f"groups ({', '.join(TICKER_GROUPS)}). 2026Q1 is inside the pooled sample and is not its own vote.",
        "",
        "| Candidate | Pooled challenger | Pooled champion | Windows | Bootstrap p | Permutation p | Decision |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for verdict in verdicts:
        wins = sum(1 for window in verdict.windows if window.win)
        lines.append(
            f"| {verdict.candidate_id} | ${verdict.challenger_pooled.net:.0f} / "
            f"{verdict.challenger_pooled.avg_bps if verdict.challenger_pooled.avg_bps is not None else float('nan'):.1f} bp | "
            f"${verdict.champion_pooled.net:.0f} / "
            f"{verdict.champion_pooled.avg_bps if verdict.champion_pooled.avg_bps is not None else float('nan'):.1f} bp | "
            f"{wins}/{len(verdict.windows)} | {verdict.bootstrap_p:.4f} | {verdict.permutation_p:.4f} | "
            f"{verdict.decision.upper()} |"
        )
    lines.append("")
    for verdict in verdicts:
        lines.extend(
            [
                f"### {verdict.candidate_id}",
                "",
                f"**Decision.** {'Rejected' if verdict.decision == 'rejected' else 'Promoted'}. "
                + " ".join(verdict.reasons),
                "",
                *_fmt_window(verdict),
                "",
            ]
        )
    lines.append(GATE_END)
    return "\n".join(lines)


def _write_log(section: str) -> None:
    existing = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
    begin = existing.find(GATE_BEGIN)
    end = existing.find(GATE_END)
    if begin >= 0 and end >= begin:
        updated = existing[:begin] + section + existing[end + len(GATE_END) :]
    else:
        updated = existing.rstrip() + "\n\n" + section + "\n"
    LOG_PATH.write_text(updated, encoding="utf-8")


def _write_tables(verdicts: list[GateVerdict], tried: int) -> None:
    import csv

    RESEARCH.mkdir(parents=True, exist_ok=True)
    with (RESEARCH / "gate_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "decision",
                "walk_forward",
                "consistency",
                "fresh_slice",
                "challenger_net",
                "champion_net",
                "challenger_expectancy",
                "champion_expectancy",
                "challenger_bps",
                "champion_bps",
                "windows_won",
                "windows",
                "severe_windows",
                "trimmed_challenger_net",
                "trimmed_champion_net",
                "bootstrap_p",
                "permutation_p",
                "alpha",
                "ideas_tried",
                "fresh_evaluated",
                "reasons",
            ],
        )
        writer.writeheader()
        for verdict in verdicts:
            chall = verdict.challenger_pooled
            champ = verdict.champion_pooled
            writer.writerow(
                {
                    "id": verdict.candidate_id,
                    "decision": verdict.decision,
                    "walk_forward": verdict.bars["walk_forward"],
                    "consistency": verdict.bars["consistency"],
                    "fresh_slice": verdict.bars["fresh_slice"],
                    "challenger_net": f"{chall.net:.2f}",
                    "champion_net": f"{champ.net:.2f}",
                    "challenger_expectancy": "" if chall.expectancy is None else f"{chall.expectancy:.4f}",
                    "champion_expectancy": "" if champ.expectancy is None else f"{champ.expectancy:.4f}",
                    "challenger_bps": "" if chall.avg_bps is None else f"{chall.avg_bps:.2f}",
                    "champion_bps": "" if champ.avg_bps is None else f"{champ.avg_bps:.2f}",
                    "windows_won": sum(1 for window in verdict.windows if window.win),
                    "windows": len(verdict.windows),
                    "severe_windows": ",".join(window.name for window in verdict.windows if window.severe),
                    "trimmed_challenger_net": f"{verdict.trimmed_challenger_net:.2f}",
                    "trimmed_champion_net": f"{verdict.trimmed_champion_net:.2f}",
                    "bootstrap_p": f"{verdict.bootstrap_p:.6f}",
                    "permutation_p": f"{verdict.permutation_p:.6f}",
                    "alpha": f"{verdict.alpha:.6f}",
                    "ideas_tried": tried,
                    "fresh_evaluated": verdict.fresh_evaluated,
                    "reasons": " ".join(verdict.reasons),
                }
            )
    with (RESEARCH / "gate_windows.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "window", "family", "challenger_net", "champion_net", "challenger_bps", "champion_bps", "challenger_trades", "champion_trades", "win", "severe"],
        )
        writer.writeheader()
        for verdict in verdicts:
            for window in verdict.windows:
                writer.writerow(
                    {
                        "id": verdict.candidate_id,
                        "window": window.name,
                        "family": window.family,
                        "challenger_net": f"{window.challenger.net:.2f}",
                        "champion_net": f"{window.champion.net:.2f}",
                        "challenger_bps": "" if window.challenger.avg_bps is None else f"{window.challenger.avg_bps:.2f}",
                        "champion_bps": "" if window.champion.avg_bps is None else f"{window.champion.avg_bps:.2f}",
                        "challenger_trades": window.challenger.trades,
                        "champion_trades": window.champion.trades,
                        "win": window.win,
                        "severe": window.severe,
                    }
                )
    summary = {
        "champion": CHAMPION_ID,
        "championUntouched": True,
        "holdoutReadThisBatch": False,
        "ideasTried": tried,
        "alpha": verdicts[0].alpha if verdicts else None,
        "halfYears": [name for name, _start, _end in HALF_YEARS],
        "verdicts": [
            {
                "id": verdict.candidate_id,
                "decision": verdict.decision,
                "bars": verdict.bars,
                "challengerNet": verdict.challenger_pooled.net,
                "championNet": verdict.champion_pooled.net,
                "windowsWon": sum(1 for window in verdict.windows if window.win),
                "bootstrapP": verdict.bootstrap_p,
                "permutationP": verdict.permutation_p,
            }
            for verdict in verdicts
        ],
    }
    (RESEARCH / "gate_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def evaluate(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[GateVerdict]:
    """Pre-holdout bars only. Does not load a day on or after the holdout."""
    if any(day >= HOLDOUT_START for (_symbol, day) in book):
        raise RuntimeError("book contains a holdout day")
    tried = ideas_tried()
    calendar = _calendar(book)
    regimes = label_regimes(_spy_closes(book), POOLED_START, POOLED_END)
    champion = champion_trades(book)
    print(f"champion trades {len(champion)} net {sum(trade['net'] for trade in champion):.0f}", flush=True)
    verdicts = []
    for candidate_id, trades in challenger_trades(book):
        verdict = judge(
            candidate_id,
            champion,
            trades,
            calendar=calendar,
            regimes=regimes,
            ideas_tried=tried,
        )
        print(
            f"  {verdict.decision}: windows {sum(1 for window in verdict.windows if window.win)}/{len(verdict.windows)} "
            f"net {verdict.challenger_pooled.net:.0f} vs {verdict.champion_pooled.net:.0f}",
            flush=True,
        )
        verdicts.append(verdict)
    ready = [verdict.candidate_id for verdict in verdicts if verdict.bars["walk_forward"] and verdict.bars["consistency"]]
    if len(ready) > 1:
        raise RuntimeError(f"more than one challenger cleared the pre-holdout bars ({ready}); holdout stays shut")
    # A single pre-holdout pass still does not load the holdout in this command.
    # fresh_slice() is the only path that could, and it refuses until a later milestone.
    if len(ready) == 1:
        print(f"pre-holdout bars passed for {ready[0]} only; holdout left shut", flush=True)
    return verdicts


def main() -> None:
    record = champion_record()
    if record.get("id") != CHAMPION_ID or record.get("replaced"):
        raise SystemExit(f"champion record is {record.get('id')}, expected {CHAMPION_ID} untouched")
    rule_before = RULE_PATH.read_text(encoding="utf-8")
    book = load_book()
    verdicts = evaluate(book)
    if any(verdict.passed for verdict in verdicts):
        raise SystemExit("a challenger passed with the fresh slice still closed; refusing to promote")
    for verdict in verdicts:
        try:
            promote(verdict, record)
        except RuntimeError:
            continue
        raise SystemExit(f"promote accepted {verdict.candidate_id} without a fresh slice")
    if not CHAMPION_PATH.exists():
        CHAMPION_PATH.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    elif json.loads(CHAMPION_PATH.read_text(encoding="utf-8")).get("id") != record["id"]:
        raise SystemExit("champion record changed during the run")
    _write_log(gate_markdown(verdicts, ideas_tried()))
    _write_tables(verdicts, ideas_tried())
    if RULE_PATH.read_text(encoding="utf-8") != rule_before:
        raise SystemExit("live signal rule was modified")
    print(f"wrote {LOG_PATH}", flush=True)
    print("champion untouched; holdout not read", flush=True)


if __name__ == "__main__":
    main()
