"""Replay ``diagnose_entry`` on stored 5-minute bars.

One signal is kept per trigger (the first bar it qualifies). The entry bar is
not included; callers simulate from the following bar. This module never
places orders.
"""

from __future__ import annotations

import pickle
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.entry import ENTRY, diagnose_entry, market_state

from backtest.data import as_of, bars_from_frame, load_symbol, raw_root, sessions
from backtest.periods import FLAT_MINUTE

CACHE_DIR = Path(__file__).resolve().parents[1] / "backtest_cache"
OPEN_MINUTE = 9 * 60 + 30


def _session_vwap_flags(bars: list[dict[str, Any]]) -> dict[int, tuple[str, bool]]:
    """Map minute -> (market_state, close >= session VWAP) for one session."""
    flags: dict[int, tuple[str, bool]] = {}
    pv = 0.0
    vol = 0.0
    for index, bar in enumerate(bars):
        typical = (bar["high"] + bar["low"] + bar["close"]) / 3.0
        vol += bar["volume"]
        pv += typical * bar["volume"]
        if bar["minute"] < OPEN_MINUTE + ENTRY.skip_open_minutes:
            continue
        state = market_state(bars[: index + 1])
        vwap = pv / vol if vol > 0 else None
        above = bool(vwap is not None and bar["close"] >= vwap)
        flags[bar["minute"]] = (state, above)
    return flags


def build_context(root: Path | None = None) -> dict[str, dict[tuple[date, int], tuple[str, bool]]]:
    """SPY and QQQ state at each bar. QQQ stands in for the sector ETF."""
    root = root or raw_root()
    out: dict[str, dict[tuple[date, int], tuple[str, bool]]] = {}
    for symbol in ("SPY", "QQQ"):
        table: dict[tuple[date, int], tuple[str, bool]] = {}
        for day, frame in sessions(load_symbol(symbol, root)):
            flags = _session_vwap_flags(bars_from_frame(frame))
            for minute, payload in flags.items():
                table[(day, minute)] = payload
        out[symbol] = table
    return out


def _context_at(
    table: dict[tuple[date, int], tuple[str, bool]], day: date, minute: int
) -> tuple[str, bool]:
    found = table.get((day, minute))
    if found is not None:
        return found
    for back in (5, 10, 15):
        found = table.get((day, minute - back))
        if found is not None:
            return found
    return ("unknown", False)


def _future_bars(today: list[dict[str, Any]], index: int) -> list[tuple[float, float, float, float, int]]:
    future = []
    for bar in today[index + 1 :]:
        if bar["minute"] > FLAT_MINUTE:
            break
        future.append((bar["open"], bar["high"], bar["low"], bar["close"], bar["minute"]))
    return future


def collect_signals(
    symbol: str,
    day_bars: list[tuple[date, list[dict[str, Any]]]],
    spy: dict[tuple[date, int], tuple[str, bool]],
    qqq: dict[tuple[date, int], tuple[str, bool]],
) -> list[dict[str, Any]]:
    """Score one symbol. ``day_bars`` is chronological regular-session bars."""
    daily_volume: list[float] = []
    daily_close: list[float] = []
    signals: list[dict[str, Any]] = []
    seen: set[tuple[date, int]] = set()

    for day_index, (day, today) in enumerate(day_bars):
        if len(today) < ENTRY.min_today_bars:
            daily_volume.append(sum(bar["volume"] for bar in today))
            daily_close.append(today[-1]["close"] if today else 0.0)
            continue
        prior_vol = daily_volume[-20:]
        avg_vol = sum(prior_vol) / len(prior_vol) if prior_vol else 0.0
        prior5 = None
        if day_index >= 6 and daily_close[day_index - 6] > 0:
            prior5 = (daily_close[day_index - 1] - daily_close[day_index - 6]) / daily_close[day_index - 6]

        history: list[dict[str, Any]] = []
        for _past_day, past in day_bars[max(0, day_index - 4) : day_index]:
            history.extend(past)
        running_hi = 0.0
        running_lo = 0.0
        cum_vol = 0.0

        for index, bar in enumerate(today):
            cum_vol += bar["volume"]
            running_hi = bar["high"] if index == 0 else max(running_hi, bar["high"])
            running_lo = bar["low"] if index == 0 else min(running_lo, bar["low"])
            if index + 1 < ENTRY.min_today_bars:
                continue
            if bar["minute"] < OPEN_MINUTE + ENTRY.skip_open_minutes:
                continue
            if bar["minute"] >= 16 * 60 - ENTRY.skip_close_minutes:
                break
            if running_hi <= 0 or (running_hi - running_lo) / running_hi * 100.0 < ENTRY.min_pullback_pct:
                continue
            spy_state, spy_above = _context_at(spy, day, bar["minute"])
            qqq_state, qqq_above = _context_at(qqq, day, bar["minute"])
            if spy_state == "falling" or qqq_state == "falling":
                continue

            rvol = (cum_vol / avg_vol) if avg_vol > 0 else None
            last = bar["close"]
            quote = {
                "symbol": symbol,
                "last": last,
                "bid": last * 0.9999,
                "ask": last * 1.0001,
                "rvol": rvol,
                "halted": 0,
            }
            elapsed = max(0.0, (bar["minute"] - OPEN_MINUTE) / 390.0)
            found = diagnose_entry(
                history + today[: index + 1],
                quote,
                now=as_of(bar["dt"]),
                session_fraction=elapsed,
                enforce_clock=True,
                spy_state=spy_state,
                qqq_state=qqq_state,
                sector_state=qqq_state,
                sector_etf="QQQ",
            )
            if not found.get("ok"):
                continue
            signal = found["signal"]
            trigger_t = int(bar["t"]) - int(signal.triggered_ago_sec)
            if (day, trigger_t) in seen:
                continue
            seen.add((day, trigger_t))
            future = _future_bars(today, index)
            if not future:
                continue
            vwap = signal.vwap
            reasons = list(signal.reasons)
            signals.append(
                {
                    "symbol": symbol,
                    "day": day,
                    "t": int(bar["t"]),
                    "trigger_t": trigger_t,
                    "minute": int(bar["minute"]),
                    "score": float(signal.score),
                    "rr": float(signal.reward_risk),
                    "rvol": None if rvol is None else float(rvol),
                    "vwap": None if vwap is None else float(vwap),
                    "close": float(last),
                    "above_vwap": bool(vwap is not None and last + 1e-9 >= float(vwap)),
                    "reclaimed_vwap": any(reason == "Reclaimed VWAP" for reason in reasons),
                    "spy_above": bool(spy_above),
                    "qqq_above": bool(qqq_above),
                    "prior5": None if prior5 is None else float(prior5),
                    "stop": float(signal.stop),
                    "target": float(signal.target),
                    "atr": None if signal.atr is None else float(signal.atr),
                    "future": future,
                }
            )
        daily_volume.append(sum(bar["volume"] for bar in today))
        daily_close.append(today[-1]["close"])
    return signals


def scan_symbol(
    symbol: str,
    context: dict[str, dict[tuple[date, int], tuple[str, bool]]] | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    root = root or raw_root()
    if context is None:
        context = build_context(root)
    day_bars = [(day, bars_from_frame(frame)) for day, frame in sessions(load_symbol(symbol, root))]
    return collect_signals(symbol, day_bars, context["SPY"], context["QQQ"])


def cache_path() -> Path:
    return CACHE_DIR / "signals.pkl"


def context_path() -> Path:
    return CACHE_DIR / "context.pkl"


def load_cached_signals() -> list[dict[str, Any]]:
    path = cache_path()
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    return list(payload["signals"])


def scan_all(symbols: list[str] | None = None, root: Path | None = None, workers: int = 4) -> list[dict[str, Any]]:
    """Score every candidate and write ``backtest_cache/signals.pkl``."""
    from concurrent.futures import ProcessPoolExecutor, as_completed

    from backtest.data import CANDIDATES

    root = root or raw_root()
    symbols = list(symbols or CANDIDATES)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("building SPY/QQQ context", flush=True)
    context = build_context(root)
    with context_path().open("wb") as handle:
        pickle.dump(context, handle, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"context bars spy={len(context['SPY'])} qqq={len(context['QQQ'])}", flush=True)

    signals: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, workers), initializer=_init_worker, initargs=(str(root),)) as pool:
        futures = {pool.submit(_scan_job, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            rows = future.result()
            print(f"{symbol} signals {len(rows)}", flush=True)
            signals.extend(rows)
    signals.sort(key=lambda row: (row["day"], row["t"], row["symbol"]))
    payload = {
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "symbols": symbols,
        "signals": signals,
    }
    with cache_path().open("wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"wrote {len(signals)} signals to {cache_path()}", flush=True)
    return signals


_WORKER_ROOT: str | None = None
_WORKER_CONTEXT: dict | None = None


def _init_worker(root: str) -> None:
    global _WORKER_ROOT, _WORKER_CONTEXT
    _WORKER_ROOT = root
    with context_path().open("rb") as handle:
        _WORKER_CONTEXT = pickle.load(handle)


def _scan_job(symbol: str) -> list[dict[str, Any]]:
    assert _WORKER_CONTEXT is not None
    return scan_symbol(symbol, _WORKER_CONTEXT, Path(_WORKER_ROOT) if _WORKER_ROOT else None)


def main() -> None:
    scan_all()


if __name__ == "__main__":
    main()
