"""Appear-to-disappear round trips.

A buy is the bar a name joins the Right Time to Buy list. The fill is the
next bar's open. A sell is the bar it leaves the list. The fill is the next
bar's open. Positions are flat on the close of the 15:50 ET bar. An optional
hard stop is the stop printed at the buy bar. Nothing here places an order.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from backtest.costs import apply_slip, commission
from backtest.periods import FLAT_MINUTE, HOLDOUT_START

ACCOUNT_USD = 2120.0
SLIP_BPS = 2.0


def _passes(hit: dict[str, Any], spec: dict[str, Any]) -> bool:
    if spec.get("min_score") is not None and float(hit["score"]) + 1e-9 < float(spec["min_score"]):
        return False
    if spec.get("min_rr") is not None and float(hit["rr"]) + 1e-9 < float(spec["min_rr"]):
        return False
    rvol = hit.get("rvol")
    if spec.get("min_rvol") is not None and (rvol is None or float(rvol) < float(spec["min_rvol"])):
        return False
    if spec.get("require_vwap_reclaim") and not hit.get("reclaimed_vwap"):
        return False
    if spec.get("require_above_vwap") and not hit.get("above_vwap"):
        return False
    minute = int(hit["minute"])
    if spec.get("minute_from") is not None and minute < int(spec["minute_from"]):
        return False
    if spec.get("minute_to") is not None and minute >= int(spec["minute_to"]):
        return False
    return True


def build_spells(
    hits: list[dict[str, Any]],
    sessions: dict[tuple[str, date], list[dict[str, Any]]],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    """Turn on-list bars into confirmed spells.

    ``sessions`` values are that symbol-day's bars, oldest first, each with
    minute, open, high, low, close.
    """
    confirm = max(1, int(spec.get("confirm") or 1))
    exit_lag = max(1, int(spec.get("exit_lag") or 1))
    grouped: dict[tuple[str, date], dict[int, dict[str, Any]]] = {}
    for hit in hits:
        if hit["day"] is None or not _passes(hit, spec):
            continue
        key = (hit["symbol"], hit["day"])
        grouped.setdefault(key, {})[int(hit["minute"])] = hit

    spells: list[dict[str, Any]] = []
    for key, by_minute in grouped.items():
        bars = sessions.get(key) or []
        if not bars:
            continue
        spells.extend(_spells_for_day(key[0], key[1], bars, by_minute, confirm, exit_lag))
    scale = float(spec.get("stop_scale") or 1.0)
    if scale != 1.0:
        for spell in spells:
            entry = float(spell["entry_bar"]["open"])
            stop = float(spell["stop"])
            if entry > stop:
                spell["stop"] = entry - scale * (entry - stop)
    spells.sort(key=lambda spell: (spell["entry_t"], spell["symbol"]))
    return spells


def _spells_for_day(
    symbol: str,
    day: date,
    bars: list[dict[str, Any]],
    on_at: dict[int, dict[str, Any]],
    confirm: int,
    exit_lag: int,
) -> list[dict[str, Any]]:
    active = False
    pending = 0
    misses = 0
    buy_at: int | None = None
    stop = 0.0
    score = 0.0
    out: list[dict[str, Any]] = []
    ordered = [bar for bar in bars if int(bar["minute"]) <= FLAT_MINUTE + 5]

    def emit(sell_index: int) -> None:
        nonlocal active, pending, misses, buy_at
        if buy_at is None:
            active = False
            pending = 0
            misses = 0
            return
        buy_index = next(i for i, bar in enumerate(ordered) if int(bar["minute"]) == buy_at)
        entry_index = buy_index + 1
        if entry_index >= len(ordered) or int(ordered[entry_index]["minute"]) >= FLAT_MINUTE:
            active = False
            pending = 0
            misses = 0
            buy_at = None
            return
        # Last bar that is still the 15:50 bar (or earlier if that print is missing).
        flat_index = None
        for i, bar in enumerate(ordered):
            if int(bar["minute"]) <= FLAT_MINUTE:
                flat_index = i
            else:
                break
        exit_index = sell_index + 1
        use_flat = exit_index >= len(ordered) or (
            flat_index is not None and int(ordered[exit_index]["minute"]) > FLAT_MINUTE
        )
        if use_flat:
            if flat_index is None or flat_index < entry_index:
                active = False
                pending = 0
                misses = 0
                buy_at = None
                return
            exit_index = flat_index
            reason_exit = "flat"
        else:
            reason_exit = "sell"
        exit_t = int(ordered[exit_index].get("t") or 0)
        if reason_exit == "flat" and exit_t:
            exit_t += 300  # close of the 15:50 bar is 15:55
        out.append(
            {
                "symbol": symbol,
                "day": day,
                "buy_minute": buy_at,
                "entry_t": int(ordered[entry_index].get("t") or 0),
                "exit_t": exit_t,
                "stop": stop,
                "score": score,
                "entry_bar": ordered[entry_index],
                "exit_bar": ordered[exit_index],
                "path": ordered[entry_index:exit_index],
                "exit_kind": reason_exit,
            }
        )
        active = False
        pending = 0
        misses = 0
        buy_at = None

    for index, bar in enumerate(ordered):
        minute = int(bar["minute"])
        if minute > FLAT_MINUTE:
            break
        is_on = minute in on_at
        if not active:
            if is_on and minute < FLAT_MINUTE:
                pending += 1
                if pending >= confirm:
                    active = True
                    buy_at = minute
                    stop = float(on_at[minute]["stop"])
                    score = float(on_at[minute]["score"])
                    misses = 0
            else:
                pending = 0
            continue
        if is_on:
            misses = 0
            continue
        misses += 1
        if misses >= exit_lag or minute >= FLAT_MINUTE:
            emit(index)
    if active:
        # Still on the list into the close. Always flat by 15:55.
        last = None
        for index, bar in enumerate(ordered):
            if int(bar["minute"]) <= FLAT_MINUTE:
                last = index
        if last is not None:
            emit(last)
    return out


def _stop_fill(bar: dict[str, Any], stop: float, slip_bps: float) -> float:
    raw = bar["open"] if bar["open"] < stop else stop
    return apply_slip(raw, "sell", slip_bps)


def resolve_exit(
    spell: dict[str, Any], *, use_stop: bool = True, slip_bps: float = SLIP_BPS
) -> tuple[float, str, int] | None:
    """Exit price, reason, and the timestamp cash is free.

    A disappearance fill is the exit bar's open, so that bar's low is not a
    stop. A 15:55 flatten holds the 15:50 bar through its close, so the low
    can stop the position before the close. A gap through the stop fills at
    the open and frees cash then; an intrabar stop frees cash at the bar close.
    """
    stop = float(spell["stop"])
    held_bars = list(spell["path"]) + [spell["exit_bar"]]
    for index, bar in enumerate(held_bars):
        is_exit_bar = index == len(held_bars) - 1
        sell_at_open = is_exit_bar and spell["exit_kind"] == "sell"
        stamp = int(bar.get("t") or 0)
        if use_stop and stop > 0 and float(bar["low"]) <= stop and not sell_at_open:
            free = stamp if float(bar["open"]) < stop else (stamp + 300 if stamp else stamp)
            return _stop_fill(bar, stop, slip_bps), "stop", free
        if is_exit_bar:
            if spell["exit_kind"] == "flat" or int(bar["minute"]) >= FLAT_MINUTE:
                free = stamp + 300 if stamp else stamp
                return apply_slip(float(bar["close"]), "sell", slip_bps), "flat", free
            return apply_slip(float(bar["open"]), "sell", slip_bps), "sell", stamp
    return None


def simulate_spell(
    spell: dict[str, Any],
    *,
    use_stop: bool = True,
    slip_bps: float = SLIP_BPS,
    schedule: str = "tiered",
    equity: float = ACCOUNT_USD,
    shares: int | None = None,
) -> dict[str, Any] | None:
    """Fill one spell. ``shares`` overrides the full-ticket size."""
    entry_bar = spell["entry_bar"]
    entry = apply_slip(float(entry_bar["open"]), "buy", slip_bps)
    if entry <= 0:
        return None
    if shares is None:
        budget = equity
        count = int(budget // entry)
    else:
        count = int(shares)
    if count < 1:
        return None
    resolved = resolve_exit(spell, use_stop=use_stop, slip_bps=slip_bps)
    if resolved is None:
        return None
    exit_px, reason, free_t = resolved
    stop = float(spell["stop"])
    buy_fee = commission(count, entry, "buy", schedule)
    sell_fee = commission(count, exit_px, "sell", schedule)
    gross = (exit_px - entry) * count
    net = gross - buy_fee - sell_fee
    notional = entry * count
    return {
        "symbol": spell["symbol"],
        "day": spell["day"],
        "entry_t": spell["entry_t"],
        "exit_t": free_t or spell["exit_t"],
        "entry": entry,
        "exit": exit_px,
        "shares": count,
        "stop": stop,
        "score": spell.get("score") or 0,
        "reason": reason,
        "gross": gross,
        "fees": buy_fee + sell_fee,
        "net": net,
        "ret": net / notional if notional else 0.0,
        "notional": notional,
    }


def portfolio(
    spells: list[dict[str, Any]],
    *,
    use_stop: bool = True,
    slip_bps: float = SLIP_BPS,
    schedule: str = "tiered",
    equity: float = ACCOUNT_USD,
) -> dict[str, Any]:
    """Spend remaining cash on each new spell. Concurrent when a share still fits."""
    # Higher priority spends scarce cash first. Equal priority keeps symbol order.
    ordered = sorted(
        spells,
        key=lambda spell: (spell["entry_t"], -(float(spell.get("priority") or 0.0)), spell["symbol"]),
    )
    planned: list[tuple[dict[str, Any], int]] = []
    for spell in ordered:
        resolved = resolve_exit(spell, use_stop=use_stop, slip_bps=slip_bps)
        if resolved is None:
            continue
        _px, _reason, free_t = resolved
        planned.append((spell, free_t or int(spell["exit_t"])))
    events: list[tuple[int, int, int]] = []
    for index, (spell, free_t) in enumerate(planned):
        events.append((int(spell["entry_t"]), 1, index))
        events.append((int(free_t), 0, index))
    events.sort()
    cash = float(equity)
    open_cost = 0.0
    peak = float(equity)
    max_dd = 0.0
    taken: list[dict[str, Any]] = []
    pending: dict[int, dict[str, Any]] = {}
    for _when, kind, index in events:
        if kind == 0:
            trade = pending.pop(index, None)
            if trade is None:
                continue
            cash += trade["exit"] * trade["shares"] - commission(trade["shares"], trade["exit"], "sell", schedule)
            open_cost -= trade["notional"]
            mark = cash + open_cost
            peak = max(peak, mark)
            max_dd = max(max_dd, peak - mark)
            continue
        spell = planned[index][0]
        entry = apply_slip(float(spell["entry_bar"]["open"]), "buy", slip_bps)
        if entry <= 0:
            continue
        shares = int(cash // entry)
        while shares >= 1 and (shares * entry + commission(shares, entry, "buy", schedule)) > cash + 1e-9:
            shares -= 1
        if shares < 1:
            continue
        trade = simulate_spell(
            spell, use_stop=use_stop, slip_bps=slip_bps, schedule=schedule, equity=equity, shares=shares
        )
        if trade is None:
            continue
        cash -= trade["notional"] + commission(trade["shares"], trade["entry"], "buy", schedule)
        open_cost += trade["notional"]
        pending[index] = trade
        taken.append(trade)
        mark = cash + open_cost
        peak = max(peak, mark)
        max_dd = max(max_dd, peak - mark)
    # Force any still-open residual into cash at its simulated exit.
    for trade in pending.values():
        cash += trade["exit"] * trade["shares"] - commission(trade["shares"], trade["exit"], "sell", schedule)
    final = cash
    return {
        "trades": taken,
        "final": final,
        "net": final - equity,
        "returnPct": (final - equity) / equity * 100.0 if equity else 0.0,
        "maxDrawdown": max_dd,
    }


def summarize_portfolio(result: dict[str, Any], session_days: int) -> dict[str, Any]:
    trades = result["trades"]
    n = len(trades)
    if n == 0:
        return {
            "trades": 0,
            "winRate": None,
            "net": 0.0,
            "returnPct": 0.0,
            "avgNetDollars": None,
            "avgNetBps": None,
            "maxDrawdown": result.get("maxDrawdown"),
            "tradesPerDay": 0.0,
            "reasons": {},
        }
    wins = sum(1 for trade in trades if trade["net"] > 0)
    reasons: dict[str, int] = {}
    for trade in trades:
        reasons[trade["reason"]] = reasons.get(trade["reason"], 0) + 1
    days = session_days or len({trade["day"] for trade in trades})
    return {
        "trades": n,
        "winRate": wins / n,
        "net": result["net"],
        "returnPct": result["returnPct"],
        "avgNetDollars": result["net"] / n,
        "avgNetBps": sum(trade["ret"] * 10_000.0 for trade in trades) / n,
        "maxDrawdown": result["maxDrawdown"],
        "tradesPerDay": n / days if days else None,
        "reasons": reasons,
        "sessionDays": days,
    }


def selection_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [hit for hit in hits if hit["day"] < HOLDOUT_START]
    if any(hit["day"] >= HOLDOUT_START for hit in kept):
        raise RuntimeError("holdout row leaked into the selection set")
    return kept
