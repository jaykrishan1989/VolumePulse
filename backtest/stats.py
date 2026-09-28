"""Summaries for a set of simulated trades. Selection never sees the holdout."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from backtest.costs import PRIMARY_SCHEDULE
from backtest.periods import HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.simulate import simulate_long


def passes(signal: dict[str, Any], spec: dict[str, Any]) -> bool:
    rvol = signal.get("rvol")
    if spec.get("min_rvol") is not None:
        if rvol is None or rvol < float(spec["min_rvol"]):
            return False
    if spec.get("require_vwap_reclaim") and not signal.get("reclaimed_vwap"):
        return False
    if spec.get("require_above_vwap") and not signal.get("above_vwap"):
        return False
    if spec.get("min_rr") is not None and float(signal["rr"]) + 1e-9 < float(spec["min_rr"]):
        return False
    if spec.get("require_spy_qqq_vwap") and not (signal.get("spy_above") and signal.get("qqq_above")):
        return False
    minute = int(signal["minute"])
    if spec.get("minute_from") is not None and minute < int(spec["minute_from"]):
        return False
    if spec.get("minute_to") is not None and minute >= int(spec["minute_to"]):
        return False
    if spec.get("min_prior5") is not None:
        prior = signal.get("prior5")
        if prior is None or float(prior) <= float(spec["min_prior5"]):
            return False
    if spec.get("min_score") is not None and float(signal["score"]) + 1e-9 < float(spec["min_score"]):
        return False
    return True


def future_bars(signal: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"open": item[0], "high": item[1], "low": item[2], "close": item[3], "minute": item[4]}
        for item in signal["future"]
    ]


def simulate_signal(
    signal: dict[str, Any],
    spec: dict[str, Any],
    *,
    slip_bps: float = 2.0,
    schedule: str = PRIMARY_SCHEDULE,
    equity: float = 2160.0,
) -> dict[str, Any] | None:
    """Fill one stored signal. Stop and target may be rescaled for a random entry."""
    stop = float(signal["stop"])
    target = float(signal["target"])
    trade = simulate_long(
        future_bars(signal),
        stop,
        target,
        mode=str(spec.get("exit") or "bracket"),
        max_bars=int(spec.get("max_bars") or 12),
        r_multiple=float(spec.get("r_multiple") or 1.0),
        atr=signal.get("atr"),
        atr_mult=float(spec.get("atr_mult") or 1.0),
        slip_bps=slip_bps,
        schedule=schedule,
        equity=equity,
    )
    if trade is None:
        return None
    entry_t = int(signal["t"]) + 300
    trade["symbol"] = signal["symbol"]
    trade["day"] = signal["day"]
    trade["entry_t"] = entry_t
    trade["exit_t"] = entry_t + int(trade["bars"]) * 300
    trade["score"] = signal.get("score")
    return trade


def apply_spec(
    signals: list[dict[str, Any]],
    spec: dict[str, Any],
    *,
    slip_bps: float = 2.0,
    schedule: str = PRIMARY_SCHEDULE,
    equity: float = 2160.0,
) -> list[dict[str, Any]]:
    trades = []
    for signal in signals:
        if not passes(signal, spec):
            continue
        trade = simulate_signal(signal, spec, slip_bps=slip_bps, schedule=schedule, equity=equity)
        if trade is not None:
            trades.append(trade)
    return trades


def _profit_factor(trades: list[dict[str, Any]]) -> float | None:
    wins = sum(trade["net"] for trade in trades if trade["net"] > 0)
    losses = sum(-trade["net"] for trade in trades if trade["net"] < 0)
    if losses <= 1e-9:
        return None if wins <= 0 else float("inf")
    return wins / losses


def _max_drawdown(trades: list[dict[str, Any]]) -> float:
    ordered = sorted(trades, key=lambda trade: (trade["entry_t"], trade["symbol"]))
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for trade in ordered:
        equity += trade["net"]
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def sequential_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One position at a time. Same-time signals keep the higher score."""
    ordered = sorted(trades, key=lambda trade: (trade["entry_t"], -(trade.get("score") or 0), trade["symbol"]))
    taken: list[dict[str, Any]] = []
    free_at = None
    for trade in ordered:
        if free_at is not None and trade["entry_t"] < free_at:
            continue
        taken.append(trade)
        free_at = trade["exit_t"]
    return taken


def summarize(trades: list[dict[str, Any]], session_days: int | None = None) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {
            "trades": 0,
            "winRate": None,
            "avgNetR": None,
            "avgNetDollars": None,
            "avgNetBps": None,
            "avgGrossBps": None,
            "profitFactor": None,
            "maxDrawdown": None,
            "tradesPerDay": None,
            "sequentialTrades": 0,
            "sequentialNet": None,
            "reasons": {},
        }
    wins = sum(1 for trade in trades if trade["net"] > 0)
    gross_bps = [trade["gross"] / trade["notional"] * 10_000.0 for trade in trades if trade["notional"]]
    net_bps = [trade["ret"] * 10_000.0 for trade in trades]
    reasons: dict[str, int] = defaultdict(int)
    for trade in trades:
        reasons[trade["reason"]] += 1
    taken = sequential_trades(trades)
    days = session_days if session_days else len({trade["day"] for trade in trades})
    return {
        "trades": n,
        "winRate": wins / n,
        "avgNetR": sum(trade["r_multiple"] for trade in trades) / n,
        "avgNetDollars": sum(trade["net"] for trade in trades) / n,
        "avgNetBps": sum(net_bps) / n,
        "avgGrossBps": sum(gross_bps) / len(gross_bps) if gross_bps else None,
        "profitFactor": _profit_factor(trades),
        "maxDrawdown": _max_drawdown(trades),
        "tradesPerDay": n / days if days else None,
        "sequentialTrades": len(taken),
        "sequentialNet": sum(trade["net"] for trade in taken),
        "sequentialAvgNetBps": (
            sum(trade["ret"] * 10_000.0 for trade in taken) / len(taken) if taken else None
        ),
        "reasons": dict(reasons),
        "sessionDays": days,
    }


def selection_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the locked holdout. Raises if a holdout row would be kept."""
    kept = [row for row in signals if row["day"] < HOLDOUT_START]
    if any(row["day"] >= HOLDOUT_START for row in kept):
        raise RuntimeError("holdout row leaked into the selection set")
    return kept


def validation_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pre = selection_signals(signals)
    return [row for row in pre if VALIDATE_START <= row["day"] <= VALIDATE_END]


def holdout_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in signals if row["day"] >= HOLDOUT_START]


def rank_configs(
    signals: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    *,
    min_trades: int = 80,
) -> list[dict[str, Any]]:
    """Rank by validation mean net bps. Holdout dates must already be removed."""
    if any(row["day"] >= HOLDOUT_START for row in signals):
        raise RuntimeError("rank_configs refuses holdout dates")
    window = [row for row in signals if VALIDATE_START <= row["day"] <= VALIDATE_END]
    ranked = []
    for spec in specs:
        trades = apply_spec(window, spec)
        stats = summarize(trades)
        ranked.append({"id": spec["id"], "spec": spec, "validation": stats, "eligible": (stats["trades"] or 0) >= min_trades})
    def sort_key(row: dict[str, Any]) -> tuple:
        stats = row["validation"]
        mean = stats["avgNetBps"]
        # Eligible configs sort first, then by mean net bps.
        return (0 if row["eligible"] else 1, 0.0 if mean is None else -mean)

    ranked.sort(key=sort_key)
    return ranked


def day_bootstrap(trades: list[dict[str, Any]], draws: int = 2000, seed: int = 7) -> dict[str, Any]:
    """Resample session-days. ``pValue`` is the share of draws with mean net bps <= 0."""
    import random

    by_day: dict[date, list[float]] = defaultdict(list)
    for trade in trades:
        by_day[trade["day"]].append(trade["ret"] * 10_000.0)
    days = list(by_day.values())
    if not days:
        return {"draws": 0, "pValue": None, "mean": None}
    rng = random.Random(seed)
    means = []
    n_days = len(days)
    for _ in range(draws):
        sample = [days[rng.randrange(n_days)] for _ in range(n_days)]
        flat = [value for chunk in sample for value in chunk]
        means.append(sum(flat) / len(flat))
    at_or_below = sum(1 for value in means if value <= 0)
    return {
        "draws": draws,
        "pValue": at_or_below / draws,
        "mean": sum(trade["ret"] * 10_000.0 for trade in trades) / len(trades),
        "days": n_days,
    }


class CompactPaths:
    """One symbol's sessions in typed arrays, indexed by clock minute.

    Random entries need another session at the same minute. Storing every
    future bar as a Python tuple blows memory, so this keeps parallel arrays
    and builds a future only for the sampled bar.
    """

    def __init__(self) -> None:
        self._minutes: dict[str, dict[int, list[tuple[int, int]]]] = {}
        self._days: dict[str, list[date]] = {}
        self._ohlc: dict[str, list[tuple[Any, Any, Any, Any, Any]]] = {}

    def add(self, symbol: str, sessions_bars: list[tuple[date, list[dict[str, Any]]]]) -> None:
        import array

        from backtest.periods import FLAT_MINUTE

        index: dict[int, list[tuple[int, int]]] = defaultdict(list)
        days: list[date] = []
        ohlc: list[tuple[Any, Any, Any, Any, Any]] = []
        for day_index, (day, bars) in enumerate(sessions_bars):
            minutes = array.array("i")
            opens = array.array("d")
            highs = array.array("d")
            lows = array.array("d")
            closes = array.array("d")
            for bar in bars:
                minute = int(bar["minute"])
                if minute > FLAT_MINUTE:
                    break
                minutes.append(minute)
                opens.append(float(bar["open"]))
                highs.append(float(bar["high"]))
                lows.append(float(bar["low"]))
                closes.append(float(bar["close"]))
            last_future = len(minutes) - 1
            for bar_index in range(len(minutes)):
                if bar_index >= last_future:
                    continue
                index[minutes[bar_index]].append((day_index, bar_index))
            days.append(day)
            ohlc.append((minutes, opens, highs, lows, closes))
        self._minutes[symbol] = index
        self._days[symbol] = days
        self._ohlc[symbol] = ohlc

    def sample(
        self, rng: Any, symbol: str, minute: int, not_day: date
    ) -> tuple[date, float, list[tuple]] | None:
        choices = self._minutes.get(symbol, {}).get(int(minute)) or []
        if not choices:
            return None
        days = self._days[symbol]
        # A few tries avoids building a list of every other session.
        for _ in range(8):
            day_index, bar_index = choices[rng.randrange(len(choices))]
            if days[day_index] != not_day or len(choices) == 1:
                if days[day_index] == not_day:
                    return None
                return self._materialize(symbol, day_index, bar_index)
        for day_index, bar_index in choices:
            if days[day_index] != not_day:
                return self._materialize(symbol, day_index, bar_index)
        return None

    def _materialize(self, symbol: str, day_index: int, bar_index: int) -> tuple[date, float, list[tuple]]:
        minutes, opens, highs, lows, closes = self._ohlc[symbol][day_index]
        future = [
            (opens[index], highs[index], lows[index], closes[index], minutes[index])
            for index in range(bar_index + 1, len(minutes))
        ]
        return self._days[symbol][day_index], closes[bar_index], future


def rescale_signal(signal: dict[str, Any], close: float, future: list[tuple]) -> dict[str, Any]:
    """Same stop/target/ATR percent distances, on another session's path."""
    base = float(signal["close"])
    if base <= 0 or close <= 0:
        return signal
    scale = close / base
    cloned = dict(signal)
    cloned["close"] = close
    cloned["stop"] = float(signal["stop"]) * scale
    cloned["target"] = float(signal["target"]) * scale
    if signal.get("atr"):
        cloned["atr"] = float(signal["atr"]) * scale
    cloned["future"] = future
    return cloned


def random_baseline(
    trades_signals: list[dict[str, Any]],
    spec: dict[str, Any],
    paths: CompactPaths,
    *,
    draws: int = 200,
    seed: int = 11,
    actual_mean_bps: float | None = None,
) -> dict[str, Any]:
    """Same symbol and minute, random other session, same percent stop and target.

    ``pValue`` is the share of random means at least as high as the strategy.
    """
    import random

    rng = random.Random(seed)
    if actual_mean_bps is None or not trades_signals:
        return {"draws": 0, "pValue": None, "randomMeanBps": None}
    means = []
    usable = 0
    for _ in range(draws):
        rets = []
        for signal in trades_signals:
            sampled = paths.sample(rng, signal["symbol"], int(signal["minute"]), signal["day"])
            if sampled is None:
                continue
            day, close, future = sampled
            cloned = rescale_signal(signal, close, future)
            cloned["day"] = day
            trade = simulate_signal(cloned, spec)
            if trade is not None:
                rets.append(trade["ret"] * 10_000.0)
        if not rets:
            continue
        usable += 1
        means.append(sum(rets) / len(rets))
    if not means:
        return {"draws": 0, "pValue": None, "randomMeanBps": None}
    beaten = sum(1 for value in means if value + 1e-9 >= actual_mean_bps)
    return {
        "draws": usable,
        "pValue": beaten / usable,
        "randomMeanBps": sum(means) / len(means),
        "strategyMeanBps": actual_mean_bps,
    }
