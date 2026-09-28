"""BUY when a name appears on the list. SELL when it leaves.

Hysteresis is counted in new 5-minute bars, matching the backtest. This
module never places an order. The owner confirms every trade.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from backtest.periods import FLAT_MINUTE

_PATH = Path(__file__).resolve().parent / "signal_rule.json"


@lru_cache(maxsize=1)
def load_rule() -> dict[str, Any]:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"id": "confirm1_lag1", "confirm": 1, "exit_lag": 1, "use_stop": True}


def describe_rule(rule: dict[str, Any] | None = None) -> str:
    rule = rule or load_rule()
    confirm = int(rule.get("confirm") or 1)
    lag = int(rule.get("exit_lag") or 1)
    parts = [
        f"BUY when a name has been on the list for {confirm} bar{'s' if confirm != 1 else ''}.",
        f"SELL after {lag} bar{'s' if lag != 1 else ''} off the list.",
        "Enter and exit at the next bar open. Flat by 15:55 ET.",
    ]
    if rule.get("use_stop", True):
        parts.append("A hard stop is a safety net while the name is still listed.")
    if rule.get("min_score") is not None:
        parts.append(f"Score at least {rule['min_score']}.")
    if rule.get("minute_from") is not None and rule.get("minute_to") is not None:
        parts.append(f"Only {_hhmm(int(rule['minute_from']))}–{_hhmm(int(rule['minute_to']))} ET.")
    if rule.get("require_vwap_reclaim"):
        parts.append("VWAP reclaim required.")
    if rule.get("min_rr") is not None:
        parts.append(f"Reward/risk at least {rule['min_rr']}.")
    parts.append("Confirm each trade yourself. Volume Pulse does not place orders.")
    return " ".join(parts)


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def row_passes(row: dict[str, Any], rule: dict[str, Any], minute: int) -> bool:
    score = row.get("entryScore")
    if rule.get("min_score") is not None and (score is None or float(score) < float(rule["min_score"])):
        return False
    rr = row.get("entryRR")
    if rule.get("min_rr") is not None and (rr is None or float(rr) < float(rule["min_rr"])):
        return False
    rvol = row.get("rvol")
    if rule.get("min_rvol") is not None and (rvol is None or float(rvol) < float(rule["min_rvol"])):
        return False
    if rule.get("require_vwap_reclaim"):
        reasons = row.get("entryReasons") or []
        if "Reclaimed VWAP" not in reasons:
            return False
    if rule.get("minute_from") is not None and minute < int(rule["minute_from"]):
        return False
    if rule.get("minute_to") is not None and minute >= int(rule["minute_to"]):
        return False
    return True


class SignalBook:
    """Bar-by-bar membership. One BUY and one later SELL, STOP, or FLAT per spell."""

    def __init__(self, rule: dict[str, Any] | None = None) -> None:
        self.rule = dict(rule or load_rule())
        self.confirm = max(1, int(self.rule.get("confirm") or 1))
        self.exit_lag = max(1, int(self.rule.get("exit_lag") or 1))
        self.use_stop = bool(self.rule.get("use_stop", True))
        self.pending: dict[str, int] = {}
        self.misses: dict[str, int] = {}
        self.active: dict[str, dict[str, Any]] = {}
        self.last_bar: dict[str, int] = {}

    def update(
        self,
        qualifying: list[dict[str, Any]],
        bar_epochs: dict[str, int | None],
        lasts: dict[str, float],
        now: datetime,
    ) -> list[dict[str, Any]]:
        minute = now.hour * 60 + now.minute
        if minute >= FLAT_MINUTE + 5 and self.active:
            events = [
                self._event("FLAT", symbol, row, lasts.get(symbol), now)
                for symbol, row in list(self.active.items())
            ]
            self.active.clear()
            self.pending.clear()
            self.misses.clear()
            return events

        by_symbol = {str(row.get("symbol")): row for row in qualifying if row.get("symbol")}
        events: list[dict[str, Any]] = []
        symbols = set(by_symbol) | set(self.active) | set(self.pending)
        for symbol in symbols:
            epoch = bar_epochs.get(symbol)
            if epoch is None:
                continue
            epoch = int(epoch)
            if self.last_bar.get(symbol) == epoch:
                continue
            self.last_bar[symbol] = epoch
            row = by_symbol.get(symbol)
            if row is not None:
                self.misses[symbol] = 0
                if symbol in self.active:
                    self.active[symbol] = row
                    continue
                self.pending[symbol] = self.pending.get(symbol, 0) + 1
                if self.pending[symbol] >= self.confirm:
                    self.active[symbol] = row
                    self.pending[symbol] = 0
                    events.append(self._event("BUY", symbol, row, lasts.get(symbol), now))
                continue
            self.pending[symbol] = 0
            if symbol not in self.active:
                continue
            self.misses[symbol] = self.misses.get(symbol, 0) + 1
            if self.misses[symbol] >= self.exit_lag:
                events.append(self._event("SELL", symbol, self.active.pop(symbol), lasts.get(symbol), now))
                self.misses[symbol] = 0

        if self.use_stop:
            for symbol, row in list(self.active.items()):
                last = lasts.get(symbol)
                stop = row.get("entryStop")
                if last is None or stop is None:
                    continue
                if float(last) <= float(stop):
                    events.append(self._event("STOP", symbol, self.active.pop(symbol), float(last), now))
                    self.misses.pop(symbol, None)
        return events

    def _event(
        self, action: str, symbol: str, row: dict[str, Any], price: float | None, now: datetime
    ) -> dict[str, Any]:
        if action == "BUY":
            note = "Enter at the next bar open. Confirm manually. Not an order."
        elif action == "SELL":
            note = "Exit at the next bar open. Confirm manually. Not an order."
        elif action == "STOP":
            note = "Protective stop. Confirm the exit manually. Not an order."
        else:
            note = "Flat by 15:55 ET. Confirm the exit manually. Not an order."
        return {
            "action": action,
            "symbol": symbol,
            "price": price,
            "stop": row.get("entryStop"),
            "target": row.get("entryTarget"),
            "score": row.get("entryScore"),
            "delayed": 1 if row.get("entryDelayed") else 0,
            "lagSec": row.get("entryLagSec"),
            "at": now.isoformat(timespec="seconds"),
            "note": note,
            "simulated": False,
        }
