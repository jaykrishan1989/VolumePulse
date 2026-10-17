"""Compare paper fills and a new backtest with the active checkpoint.

A rollback rewrites models/ACTIVE. It does not place an order. The threshold
is fixed in this file and in models/ROLLBACK.md. Do not loosen it after a bad
week.

Paper rule, all of it required:

- At least 30 closed round-trips in the outcome log (the most recent 30).
- Their mean net basis points are at least 10 bp worse than the checkpoint's
  expected holdout expectancy.
- A one-sided binomial test says that many of them landing below the
  checkpoint expectancy is unlikely if each trade were only a coin flip
  around that expectancy (p < 0.05).

Backtest rule, for a new summary of the same rule:

- At least 80 trades.
- Average net basis points at least 10 bp worse than the checkpoint expectancy.

If that trips and an older checkpoint has passed the costs-and-random bar,
ACTIVE switches to the latest such checkpoint. If none has passed, ACTIVE
stays put, the event is logged once, and the UI is told to show the flag.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from models.registry import MODELS, Store, default_store

WINDOW = 30
BPS_GAP = 10.0
ALPHA = 0.05
BACKTEST_MIN_TRADES = 80


def binomial_upper_p(successes: int, trials: int) -> float:
    """P(X >= successes) for X ~ Binomial(trials, 0.5)."""
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("binomial counts are out of range")
    if successes == 0:
        return 1.0
    total = 0
    for count in range(successes, trials + 1):
        total += math.comb(trials, count)
    return total / (2**trials)


@dataclass
class Assessment:
    tripped: bool
    kind: str
    n: int
    mean_bps: float | None
    expected_bps: float
    binomial_p: float | None
    reasons: list[str] = field(default_factory=list)


def assess_trades(bps: list[float], expected_bps: float) -> Assessment:
    sample = [float(value) for value in bps][-WINDOW:]
    if len(bps) < WINDOW:
        return Assessment(
            False,
            "paper",
            len(bps),
            statistics.fmean(sample) if sample else None,
            expected_bps,
            None,
            [f"{len(bps)} closed paper trades; the monitor waits for {WINDOW}"],
        )
    mean = statistics.fmean(sample)
    worse = sum(1 for value in sample if value < expected_bps - 1e-9)
    p_value = binomial_upper_p(worse, len(sample))
    reasons: list[str] = []
    if mean > expected_bps - BPS_GAP:
        reasons.append(
            f"mean {mean:.1f} bp is inside {BPS_GAP:.0f} bp of the checkpoint {expected_bps:.1f} bp"
        )
    if p_value >= ALPHA:
        reasons.append(
            f"{worse} of {len(sample)} trades fell below the checkpoint; binomial p={p_value:.3f}"
        )
    tripped = not reasons
    if tripped:
        reasons.append(
            f"last {len(sample)} trades averaged {mean:.1f} bp versus the checkpoint {expected_bps:.1f} bp "
            f"({worse} below it, binomial p={p_value:.4f})"
        )
    return Assessment(tripped, "paper", len(sample), mean, expected_bps, p_value, reasons)


def assess_backtest(avg_bps: float, trades: int, expected_bps: float) -> Assessment:
    if trades < BACKTEST_MIN_TRADES:
        return Assessment(
            False,
            "backtest",
            trades,
            avg_bps,
            expected_bps,
            None,
            [f"{trades} backtest trades; the monitor waits for {BACKTEST_MIN_TRADES}"],
        )
    gap = expected_bps - float(avg_bps)
    tripped = gap >= BPS_GAP
    reason = (
        f"backtest average {float(avg_bps):.1f} bp is {gap:.1f} bp worse than the checkpoint {expected_bps:.1f} bp"
        if tripped
        else f"backtest average {float(avg_bps):.1f} bp is inside {BPS_GAP:.0f} bp of the checkpoint"
    )
    return Assessment(tripped, "backtest", trades, float(avg_bps), expected_bps, None, [reason])


@dataclass
class Decision:
    action: str
    version: str
    target: str | None
    message: str
    assessment: Assessment


def decide(store: Store, assessment: Assessment) -> Decision:
    version = store.active_version()
    if not assessment.tripped:
        return Decision("none", version, None, " ".join(assessment.reasons), assessment)
    target = store.last_passing(exclude=version)
    detail = " ".join(assessment.reasons)
    if target is None:
        return Decision(
            "withheld",
            version,
            None,
            "ROLLBACK HELD. " + detail + " No passing checkpoint exists, so the active version was not changed. "
            "Volume Pulse does not place orders.",
            assessment,
        )
    return Decision(
        "rollback",
        version,
        target,
        f"ROLLBACK. {detail} ACTIVE moved from {version} to {target}. Volume Pulse does not place orders.",
        assessment,
    )


def _fingerprint(assessment: Assessment) -> str:
    mean = "na" if assessment.mean_bps is None else f"{assessment.mean_bps:.4f}"
    return f"{assessment.kind}:{assessment.n}:{mean}"


def apply_decision(
    store: Store,
    decision: Decision,
    *,
    changelog: Path,
    state_path: Path,
) -> dict[str, Any]:
    """Log a trip once. A rollback also moves ACTIVE. A repeat of the same sample does nothing."""
    if decision.action == "none":
        return {"action": "none", "version": decision.version, "logged": False}
    fingerprint = _fingerprint(decision.assessment)
    key = f"{decision.action}:{decision.version}:{decision.target or ''}:{fingerprint}"
    state: dict[str, Any] = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
    if state.get("lastKey") == key:
        return {
            "action": decision.action,
            "version": store.active_version(),
            "target": decision.target,
            "logged": False,
            "message": decision.message,
        }
    if decision.action == "rollback" and decision.target:
        store.restore(decision.target)
    text = changelog.read_text(encoding="utf-8") if changelog.is_file() else ""
    heading = "Rollback" if decision.action == "rollback" else "Rollback withheld"
    entry = (
        f"\n## {heading} — {date.today().isoformat()}\n\n"
        f"{decision.message}\n"
    )
    changelog.parent.mkdir(parents=True, exist_ok=True)
    changelog.write_text(text.rstrip() + "\n" + entry, encoding="utf-8")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"lastKey": key, "action": decision.action, "message": decision.message}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "action": decision.action,
        "version": store.active_version(),
        "target": decision.target,
        "logged": True,
        "message": decision.message,
    }


def status_payload(store: Store, bps: list[float], *, changelog: Path, state_path: Path) -> dict[str, Any]:
    config = store.load()
    expected = float((config.get("expected") or {}).get("avgNetBps"))
    assessment = assess_trades(bps, expected)
    decision = decide(store, assessment)
    applied = apply_decision(store, decision, changelog=changelog, state_path=state_path)
    if applied["action"] == "rollback":
        config = store.load()
    show = applied["action"] in {"withheld", "rollback"}
    return {
        "version": config["version"],
        "status": config.get("status") or ("passing" if config.get("passedGate") else "baseline"),
        "passedGate": bool(config.get("passedGate")),
        "label": _label(config),
        "rollback": {
            "active": show,
            "kind": applied["action"] if show else None,
            "message": decision.message if show else "",
        },
    }


def _label(config: dict[str, Any]) -> str:
    version = config["version"]
    if config.get("passedGate"):
        return f"{version} passing"
    return f"{version} baseline"


def live_status(bps: list[float]) -> dict[str, Any]:
    return status_payload(
        default_store(),
        bps,
        changelog=MODELS / "CHANGELOG.md",
        state_path=MODELS.parents[0] / "data" / "monitor_state.json",
    )
