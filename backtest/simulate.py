"""Fill and exit rules for one Right Time to Buy signal.

The entry is the next bar's open. When a bar trades through both the stop and
the target, the stop is filled and the target is ignored. Positions are flat
on the close of the 15:50 ET bar (15:55). Nothing here sends an order.
"""

from __future__ import annotations

from typing import Any

from backtest.costs import PRIMARY_SCHEDULE, apply_slip, commission, share_count
from backtest.periods import FLAT_MINUTE


def _stop_fill(bar: dict[str, Any], stop: float, slip_bps: float) -> float:
    raw = bar["open"] if bar["open"] < stop else stop
    return apply_slip(raw, "sell", slip_bps)


def _target_fill(bar: dict[str, Any], target: float, slip_bps: float) -> float:
    raw = bar["open"] if bar["open"] > target else target
    return apply_slip(raw, "sell", slip_bps)


def _close_fill(bar: dict[str, Any], slip_bps: float) -> float:
    return apply_slip(bar["close"], "sell", slip_bps)


def simulate_long(
    future: list[dict[str, Any]],
    stop: float,
    target: float,
    *,
    mode: str = "bracket",
    max_bars: int = 12,
    r_multiple: float = 1.0,
    atr: float | None = None,
    atr_mult: float = 1.0,
    slip_bps: float = 2.0,
    schedule: str = PRIMARY_SCHEDULE,
    equity: float = 2160.0,
    flat_minute: int = FLAT_MINUTE,
) -> dict[str, Any] | None:
    """Simulate one long. ``future`` starts at the entry bar (the bar after the signal)."""
    if not future or stop <= 0 or target <= 0:
        return None
    entry_bar = future[0]
    entry = apply_slip(float(entry_bar["open"]), "buy", slip_bps)
    shares = share_count(equity, entry)
    if shares < 1:
        return None

    if mode == "r_multiple":
        risk = entry - stop
        if risk <= 0:
            target = entry
        else:
            target = entry + r_multiple * risk
    elif mode == "time":
        target = entry * 10.0  # unreachable; time or stop ends the trade
    elif mode == "trail":
        target = entry * 10.0
    elif mode != "bracket":
        raise ValueError(mode)

    trail = stop
    exit_px = None
    reason = None
    held = 0
    limit = max(1, int(max_bars))
    for index, bar in enumerate(future[:limit]):
        held = index + 1
        stop_level = trail if mode == "trail" else stop
        hit_stop = bar["low"] <= stop_level
        hit_target = mode == "bracket" or mode == "r_multiple"
        hit_target = hit_target and bar["high"] >= target
        if hit_stop:
            exit_px = _stop_fill(bar, stop_level, slip_bps)
            reason = "stop"
            break
        if hit_target:
            exit_px = _target_fill(bar, target, slip_bps)
            reason = "target"
            break
        flat = int(bar.get("minute") or 0) >= flat_minute
        last_bar = index == limit - 1 or index == len(future) - 1
        if flat or last_bar:
            exit_px = _close_fill(bar, slip_bps)
            reason = "eod" if flat else "time"
            break
        if mode == "trail" and atr:
            trail = max(trail, float(bar["close"]) - atr_mult * float(atr))

    if exit_px is None or reason is None:
        return None
    gross = (exit_px - entry) * shares
    fees = commission(shares, entry, "buy", schedule) + commission(shares, exit_px, "sell", schedule)
    net = gross - fees
    planned_risk = (entry - stop) * shares
    return {
        "entry": entry,
        "exit": exit_px,
        "shares": shares,
        "reason": reason,
        "bars": held,
        "gross": gross,
        "fees": fees,
        "net": net,
        "ret": net / (entry * shares) if entry else 0.0,
        "r_multiple": (net / planned_risk) if planned_risk > 1e-9 else 0.0,
        "notional": entry * shares,
    }
