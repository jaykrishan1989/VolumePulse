"""Walk-forward search. Validation picks one config. Holdout runs once.

Decision rule, fixed before any result is read:

- Rank the pre-registered grid by validation mean net bps (tiered, 2 bp
  slippage, US$2,160, independent trades).
- A config is eligible only with at least 80 validation trades.
- The published config is the best eligible config, or the best ineligible
  one when none reach 80 trades.
- Holdout (from 2026-04-01) is then evaluated for that config and for the
  unmodified baseline. Those two reads are the only holdout reads. They do
  not change the pick.
- Worth paper-trading as a positive-expectancy alert only if the chosen
  holdout mean net bps is above zero, the day-bootstrap p-value is below
  0.05, and the same holdout beats a random-entry baseline at p < 0.05.
  Otherwise the verdict is do not trade.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from backtest.data import CANDIDATES, load_symbol, raw_root, sessions
from backtest.grid import SPECS
from backtest.periods import (
    ACCOUNT_USD,
    HOLDOUT_END,
    HOLDOUT_START,
    SLIP_BPS,
    TRAIN_END,
    TRAIN_START,
    VALIDATE_END,
    VALIDATE_START,
)
from backtest.scan import cache_path, load_cached_signals, scan_all
from backtest.data import bars_from_frame
from backtest.stats import (
    CompactPaths,
    apply_spec,
    day_bootstrap,
    holdout_signals,
    random_baseline,
    rank_configs,
    selection_signals,
    summarize,
)

REPORT_PATH = Path(__file__).resolve().parents[1] / "backtest_cache" / "report.json"
PUBLIC_STATS = Path(__file__).resolve().parents[1] / "app" / "research_stats.json"


def _window(signals: list[dict], start: date, end: date) -> list[dict]:
    return [row for row in signals if start <= row["day"] <= end]


def _session_days(start: date, end: date, root: Path | None = None) -> int:
    count = 0
    for day, _frame in sessions(load_symbol("SPY", root or raw_root())):
        if start <= day <= end:
            count += 1
    return count


def _paths_for(
    signals: list[dict],
    start: date,
    end: date,
    root: Path | None = None,
) -> CompactPaths:
    """Sessions in the window, for symbols that actually fired."""
    needed = {row["symbol"] for row in signals}
    paths = CompactPaths()
    root = root or raw_root()
    for symbol in sorted(needed):
        sessions_bars = []
        for day, frame in sessions(load_symbol(symbol, root)):
            if start <= day <= end:
                sessions_bars.append((day, bars_from_frame(frame)))
        paths.add(symbol, sessions_bars)
        print(f"paths {symbol} sessions {len(sessions_bars)}", flush=True)
    return paths


def _pack(stats: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    packed = dict(stats)
    if extra:
        packed.update(extra)
    pf = packed.get("profitFactor")
    if pf == float("inf"):
        packed["profitFactor"] = None
        packed["profitFactorInfinite"] = True
    return packed


def run() -> dict[str, Any]:
    if not cache_path().exists():
        scan_all(CANDIDATES)
    signals = load_cached_signals()
    pre = selection_signals(signals)
    print(f"signals total={len(signals)} pre_holdout={len(pre)}", flush=True)
    ranked = rank_configs(pre, SPECS, min_trades=80)
    chosen = ranked[0]
    spec = chosen["spec"]
    print(
        f"chosen {chosen['id']} validation n={chosen['validation']['trades']} "
        f"bps={chosen['validation']['avgNetBps']}",
        flush=True,
    )

    train_days = _session_days(TRAIN_START, TRAIN_END)
    val_days = _session_days(VALIDATE_START, VALIDATE_END)
    hold_days = _session_days(HOLDOUT_START, HOLDOUT_END)
    baseline = next(item for item in SPECS if item["id"] == "baseline")

    def evaluate(window: list[dict], item: dict, days: int, slip: float = SLIP_BPS, schedule: str = "tiered") -> dict:
        trades = apply_spec(window, item, slip_bps=slip, schedule=schedule, equity=ACCOUNT_USD)
        return summarize(trades, days), trades

    train_stats, _train_trades = evaluate(_window(pre, TRAIN_START, TRAIN_END), baseline, train_days)
    val_base_stats, val_base_trades = evaluate(_window(pre, VALIDATE_START, VALIDATE_END), baseline, val_days)
    val_chosen_stats, val_chosen_trades = evaluate(_window(pre, VALIDATE_START, VALIDATE_END), spec, val_days)

    print("validation bootstrap / random baseline", flush=True)
    val_universe = _window(pre, VALIDATE_START, VALIDATE_END)
    val_paths = _paths_for(val_universe, VALIDATE_START, VALIDATE_END)
    chosen_val_signals = [row for row in val_universe if _kept(row, spec)]
    base_val_signals = [row for row in val_universe if _kept(row, baseline)]
    val_boot = day_bootstrap(val_chosen_trades)
    val_random = random_baseline(
        chosen_val_signals,
        spec,
        val_paths,
        actual_mean_bps=val_chosen_stats.get("avgNetBps"),
    )
    base_boot = day_bootstrap(val_base_trades)
    base_random = random_baseline(
        base_val_signals,
        baseline,
        val_paths,
        actual_mean_bps=val_base_stats.get("avgNetBps"),
    )

    # Locked reads. Do not add another holdout config after this.
    print("holdout once", flush=True)
    hold = holdout_signals(signals)
    hold_base_stats, hold_base_trades = evaluate(hold, baseline, hold_days)
    hold_chosen_stats, hold_chosen_trades = evaluate(hold, spec, hold_days)
    hold_paths = _paths_for(hold, HOLDOUT_START, HOLDOUT_END)
    hold_boot = day_bootstrap(hold_chosen_trades, seed=19)
    hold_random = random_baseline(
        [row for row in hold if _kept(row, spec)],
        spec,
        hold_paths,
        seed=23,
        actual_mean_bps=hold_chosen_stats.get("avgNetBps"),
    )
    stress_fixed, _ = evaluate(hold, spec, hold_days, slip=SLIP_BPS, schedule="fixed")
    stress_slip, _ = evaluate(hold, spec, hold_days, slip=5.0, schedule="tiered")

    worth = _worth(hold_chosen_stats, hold_boot, hold_random)
    report = {
        "protocol": {
            "train": [TRAIN_START.isoformat(), TRAIN_END.isoformat()],
            "validate": [VALIDATE_START.isoformat(), VALIDATE_END.isoformat()],
            "holdout": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
            "accountUsd": ACCOUNT_USD,
            "slipBps": SLIP_BPS,
            "schedule": "tiered",
            "minTrades": 80,
            "grid": [item["id"] for item in SPECS],
            "sectorProxy": "QQQ",
            "shorts": "not tested; not shipped",
        },
        "chosenId": chosen["id"],
        "worthTrading": worth,
        "trainBaseline": _pack(train_stats),
        "validationBaseline": _pack(val_base_stats, {"bootstrap": base_boot, "random": base_random}),
        "validationChosen": _pack(val_chosen_stats, {"bootstrap": val_boot, "random": val_random}),
        "holdoutBaseline": _pack(hold_base_stats),
        "holdoutChosen": _pack(
            hold_chosen_stats,
            {"bootstrap": hold_boot, "random": hold_random, "stressFixed": _pack(stress_fixed), "stress5bp": _pack(stress_slip)},
        ),
        "ranking": [
            {
                "id": row["id"],
                "eligible": row["eligible"],
                "trades": row["validation"]["trades"],
                "avgNetBps": row["validation"]["avgNetBps"],
                "winRate": row["validation"]["winRate"],
                "profitFactor": None
                if row["validation"]["profitFactor"] in (None, float("inf"))
                else row["validation"]["profitFactor"],
                "avgNetDollars": row["validation"]["avgNetDollars"],
            }
            for row in ranked
        ],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=_json_default), encoding="utf-8")
    PUBLIC_STATS.write_text(json.dumps(_public(report), indent=2), encoding="utf-8")
    print(json.dumps({"chosen": chosen["id"], "worthTrading": worth, "holdoutBps": hold_chosen_stats.get("avgNetBps")}, indent=2))
    return report


def _kept(signal: dict, spec: dict) -> bool:
    from backtest.stats import passes

    return passes(signal, spec)


def _worth(stats: dict, boot: dict, random_stats: dict) -> bool:
    mean = stats.get("avgNetBps")
    if mean is None or mean <= 0:
        return False
    if not boot or boot.get("pValue") is None or boot["pValue"] >= 0.05:
        return False
    if not random_stats or random_stats.get("pValue") is None or random_stats["pValue"] >= 0.05:
        return False
    return True


def _json_default(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if value == float("inf"):
        return None
    raise TypeError(type(value))


def _public(report: dict) -> dict:
    """Numbers the live tab is allowed to show. No trade list."""
    base_hold = report["holdoutBaseline"]
    chosen_hold = report["holdoutChosen"]
    # The tab shows the rule it is actually running. A losing pick is not wired in,
    # so the card stats stay on the unmodified baseline.
    shipped = report["worthTrading"]
    hold = chosen_hold if shipped else base_hold
    val = report["validationChosen"] if shipped else report["validationBaseline"]
    verdict = (
        "Holdout mean is positive after costs and beats a random entry. Paper trade only; this is not a promise of profit."
        if shipped
        else "No configuration kept a cost-inclusive edge on the locked holdout. Do not trade it."
    )
    return {
        "chosenId": report["chosenId"],
        "shippedRule": report["chosenId"] if shipped else "baseline",
        "worthTrading": report["worthTrading"],
        "verdict": verdict,
        "accountUsd": ACCOUNT_USD,
        "slipBps": SLIP_BPS,
        "schedule": "tiered",
        "holdout": {
            "trades": hold.get("trades"),
            "winRate": hold.get("winRate"),
            "avgNetBps": hold.get("avgNetBps"),
            "avgNetDollars": hold.get("avgNetDollars"),
            "avgNetR": hold.get("avgNetR"),
            "profitFactor": hold.get("profitFactor"),
            "tradesPerDay": hold.get("tradesPerDay"),
        },
        "validation": {
            "trades": val.get("trades"),
            "winRate": val.get("winRate"),
            "avgNetBps": val.get("avgNetBps"),
            "avgNetDollars": val.get("avgNetDollars"),
        },
        "baselineHoldout": {
            "trades": base_hold.get("trades"),
            "winRate": base_hold.get("winRate"),
            "avgNetBps": base_hold.get("avgNetBps"),
            "avgNetDollars": base_hold.get("avgNetDollars"),
        },
        "chosenHoldout": {
            "trades": chosen_hold.get("trades"),
            "winRate": chosen_hold.get("winRate"),
            "avgNetBps": chosen_hold.get("avgNetBps"),
            "avgNetDollars": chosen_hold.get("avgNetDollars"),
        },
    }


if __name__ == "__main__":
    run()
