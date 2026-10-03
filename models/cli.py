"""List, show, restore, and check model checkpoints.

    python -m models.cli list
    python -m models.cli show v0.1
    python -m models.cli restore v0.1
    python -m models.cli check
    python -m models.cli check --backtest results.json

Restore points models/ACTIVE at a live-capable checkpoint and mirrors its
signal rule. Check runs the rollback monitor. Neither command places an order.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from models.monitor import assess_backtest, assess_trades, decide
from models.registry import default_store


def _print_show(store, version: str) -> None:
    config = store.load(version)
    expected = config.get("expected") or {}
    print(f"{config['version']}  status={config.get('status')}  passedGate={bool(config.get('passedGate'))}  live={bool(config.get('liveCapable'))}")
    print(f"tag {config.get('tag') or '—'}")
    net = expected.get("net")
    bps = expected.get("avgNetBps")
    win = expected.get("winRate")
    print(
        "expected "
        f"net {net}  win {win}  {bps} bp  "
        f"maxDD {expected.get('maxDrawdown')}  trades/day {expected.get('tradesPerDay')}"
    )
    note = store.note(version).strip()
    if note:
        print()
        print(note)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m models.cli")
    parser.add_argument("command", choices=("list", "show", "restore", "check"))
    parser.add_argument("version", nargs="?")
    parser.add_argument("--backtest", type=Path, help="JSON with avgNetBps and trades")
    args = parser.parse_args(argv)
    store = default_store()
    if args.command == "list":
        active = store.active_version()
        for version in store.list_versions():
            config = store.load(version)
            mark = " active" if version == active else ""
            gate = "pass" if config.get("passedGate") else "baseline"
            print(f"{version}  {gate}{mark}")
        return 0
    if args.command == "show":
        if not args.version:
            parser.error("show needs a version")
        _print_show(store, args.version)
        return 0
    if args.command == "restore":
        if not args.version:
            parser.error("restore needs a version")
        store.restore(args.version)
        from app.signals import load_rule

        load_rule.cache_clear()
        print(f"ACTIVE -> {store.active_version()}")
        print("Restart the app so an already-open signal book picks up the rule.")
        print("Volume Pulse does not place orders.")
        return 0
    config = store.load()
    expected = float((config.get("expected") or {})["avgNetBps"])
    if args.backtest:
        payload = json.loads(args.backtest.read_text(encoding="utf-8"))
        avg = payload.get("avgNetBps", payload.get("avg_net_bps"))
        trades = payload.get("trades")
        if avg is None or trades is None:
            hold = payload.get("holdout") or {}
            avg = hold.get("avgNetBps")
            trades = hold.get("trades")
        assessment = assess_backtest(float(avg), int(trades), expected)
    else:
        from app.outcomes import OutcomeLog

        assessment = assess_trades(OutcomeLog().closed_signal_bps(), expected)
    decision = decide(store, assessment)
    print(decision.action)
    print(decision.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
