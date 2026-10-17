"""Multi-timeframe trough book. Frozen before the fit. Not a gate idea.

A row exists only when the completed bar is a new 30-minute low, under VWAP,
and in the bottom 40% of the session range. The label is whether a long at
the next open hits plus one ATR before minus one ATR or the 15:55 flat.
LightGBM learns which of those troughs have bounced before. A sequence model
is not in this spec.

Up to four names can be open, each a quarter of the US$2,120 ticket, and a
symbol is not entered twice while that position is open. Nothing here places
an order. The locked holdout is not a training day.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from backtest.data import CANDIDATES, CONTEXT
from backtest.periods import FLAT_MINUTE, HOLDOUT_START
from backtest.spells import resolve_exit

TRADE_SYMBOLS = list(CANDIDATES) + list(CONTEXT)
OPEN_MINUTE = 9 * 60 + 30
# 14 bars of 5 minutes: the first legal signal is 10:40. RSI and a 12-bar z-score exist.
MIN_INDEX = 14
# 15:10 bar. The fill is the 15:15 open, and the flat is still 15:50.
SIGNAL_TO = 15 * 60 + 10
TROUGH_BARS = 6
SESSION_POS_MAX = 0.40
# One ATR up, one ATR down. Same-bar ties go to the stop.
TARGET_ATR = 1.0
STOP_ATR = 1.0
# Four slots. A fifth name waits for cash. Not a grid.
SLOT_FRACTION = 0.25
WARMUP_DAYS = 20
PUBLISHED_MODEL_VALIDATION_NET = 1260.736236000008
MIN_TRADES = 50
# Around the owner's 2–6 fills a day. Outside this band the book is the wrong shape.
MIN_FILLS_PER_DAY = 1.5
MAX_FILLS_PER_DAY = 8.0
THRESHOLDS = (0.55, 0.60, 0.65, 0.70)

FEATURE_COLUMNS = (
    "ret_3",
    "ret_6",
    "ret_12",
    "rsi_14",
    "z_12",
    "vwap_dist",
    "session_pos",
    "range_atr",
    "swing_12",
    "vol_surge",
    "low_dist",
    "trough_depth",
    "tod",
    "dow",
    "gap_atr",
    "prior_ret",
    "dist_ma5",
    "dist_range_20",
    "rv_20",
    "osc_rate",
    "ac1",
    "spy_from_open",
    "spy_vwap_dist",
    "spy_prior_ret",
    "spy_rv_20",
    "qqq_from_open",
    "qqq_vwap_dist",
    "qqq_prior_ret",
    "qqq_rv_20",
)


def is_milestone(net: float, net_ex_top5: float, trades: int) -> bool:
    """Holdout stays closed unless the full window beats the published model and survives its best days."""
    return trades >= MIN_TRADES and net > PUBLISHED_MODEL_VALIDATION_NET and net_ex_top5 > 0.0


def trough_indices(
    lows: np.ndarray,
    closes: np.ndarray,
    vwaps: np.ndarray,
    session_pos: np.ndarray,
    minutes: np.ndarray,
) -> list[int]:
    """New 30-minute low, under VWAP, in the lower part of today's range."""
    found = []
    for index in range(MIN_INDEX, len(closes)):
        minute = int(minutes[index])
        if minute > SIGNAL_TO or minute >= FLAT_MINUTE:
            continue
        window = lows[index - TROUGH_BARS : index]
        if not np.all(np.isfinite(window)) or not np.isfinite(lows[index]):
            continue
        if lows[index] >= np.min(window):
            continue
        vwap = vwaps[index]
        pos = session_pos[index]
        if not np.isfinite(vwap) or not np.isfinite(pos) or not np.isfinite(closes[index]):
            continue
        if closes[index] >= vwap or pos > SESSION_POS_MAX:
            continue
        found.append(index)
    return found


def bounce_hit(bars: list[dict[str, Any]], entry_index: int, flat_index: int, atr: float) -> int:
    """1 when plus one ATR prints before minus one ATR. The stop wins a tie."""
    if atr <= 0 or entry_index > flat_index:
        return 0
    entry = float(bars[entry_index]["open"])
    if entry <= 0:
        return 0
    target = entry + TARGET_ATR * atr
    stop = entry - STOP_ATR * atr
    for index in range(entry_index, flat_index + 1):
        bar = bars[index]
        if float(bar["low"]) <= stop:
            return 0
        if float(bar["high"]) >= target:
            return 1
    return 0


def _rsi(closes: np.ndarray, index: int, length: int = 14) -> float:
    window = closes[index - length + 1 : index + 1]
    delta = np.diff(window)
    if len(delta) != length - 1:
        return np.nan
    gains = delta[delta > 0]
    losses = -delta[delta < 0]
    avg_gain = float(gains.mean()) if len(gains) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    if avg_loss == 0.0 and avg_gain == 0.0:
        return 0.5
    if avg_loss == 0.0:
        return 1.0
    rs = avg_gain / avg_loss
    return 1.0 - 1.0 / (1.0 + rs)


def _zscore(closes: np.ndarray, index: int, length: int) -> float:
    window = closes[index - length + 1 : index + 1]
    if len(window) < length or np.any(~np.isfinite(window)):
        return np.nan
    mean = float(window.mean())
    std = float(window.std())
    if std <= 0:
        return 0.0
    return (float(closes[index]) - mean) / std


def _ac1(closes: np.ndarray) -> float:
    if len(closes) < 21 or np.any(closes[:-1] <= 0):
        return np.nan
    rets = np.diff(closes) / closes[:-1]
    left = rets[:-1]
    right = rets[1:]
    if float(left.std()) == 0.0 or float(right.std()) == 0.0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def _day_features(history: dict[str, list[float]]) -> dict[str, float]:
    closes = history["closes"]
    highs = history["highs"]
    lows = history["lows"]
    rets = history["rets"]
    acs = history["ac1"]
    out = {
        "prior_close": np.nan,
        "prior_ret": np.nan,
        "dist_ma5": np.nan,
        "dist_range_20": np.nan,
        "rv_20": np.nan,
        "osc_rate": np.nan,
        "ac1": np.nan,
    }
    if len(closes) < WARMUP_DAYS or len(rets) < WARMUP_DAYS:
        return out
    prior = closes[-1]
    out["prior_close"] = prior
    ma5 = float(np.mean(closes[-5:]))
    hi = float(np.max(highs[-WARMUP_DAYS:]))
    lo = float(np.min(lows[-WARMUP_DAYS:]))
    out["prior_ret"] = rets[-1]
    out["dist_ma5"] = prior / ma5 - 1.0 if ma5 > 0 else np.nan
    out["dist_range_20"] = (prior - lo) / (hi - lo) if hi > lo else np.nan
    out["rv_20"] = float(np.std(rets[-WARMUP_DAYS:]))
    flags = history["recover"][-WARMUP_DAYS:]
    out["osc_rate"] = float(np.mean(flags)) if len(flags) >= WARMUP_DAYS else np.nan
    out["ac1"] = acs[-1] if acs else np.nan
    return out


def _empty_history() -> dict[str, list[float]]:
    return {"closes": [], "highs": [], "lows": [], "rets": [], "ac1": [], "recover": []}


def _append_day(history: dict[str, list[float]], high: float, low: float, close: float, ac: float) -> None:
    if history["closes"]:
        prev = history["closes"][-1]
        history["rets"].append(close / prev - 1.0 if prev > 0 else np.nan)
    history["closes"].append(close)
    history["highs"].append(high)
    history["lows"].append(low)
    history["ac1"].append(ac)
    span = high - low
    history["recover"].append(1.0 if span > 0 and (close - low) >= 0.5 * span else 0.0)


def _true_ranges(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    prev = np.empty_like(closes)
    prev[0] = closes[0]
    prev[1:] = closes[:-1]
    return np.maximum(highs - lows, np.maximum(np.abs(highs - prev), np.abs(lows - prev)))


def _market_path(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    opens: np.ndarray,
    volumes: np.ndarray,
    atr0: float,
    prior_ret: float,
    rv_20: float,
) -> dict[int, dict[str, float]]:
    cum_pv = 0.0
    cum_v = 0.0
    opened = float(opens[0])
    slots = {}
    for index in range(len(closes)):
        typical = (float(highs[index]) + float(lows[index]) + float(closes[index])) / 3.0
        volume = max(float(volumes[index]), 0.0)
        cum_pv += typical * volume
        cum_v += volume
        vwap_dist = np.nan
        if cum_v > 0 and atr0 > 0:
            vwap_dist = (float(closes[index]) - cum_pv / cum_v) / atr0
        from_open = float(closes[index]) / opened - 1.0 if opened > 0 else np.nan
        slots[index] = {"from_open": from_open, "vwap_dist": vwap_dist, "prior_ret": prior_ret, "rv_20": rv_20}
    return slots


def build_frame(
    book: dict[tuple[str, date], list[dict[str, Any]]],
    *,
    allow_holdout: bool = False,
) -> pd.DataFrame:
    """One row per trough. Features stop at that bar. The label starts at the next open."""
    if not allow_holdout:
        leaked = [day for (_symbol, day) in book if day >= HOLDOUT_START]
        if leaked:
            raise RuntimeError(f"holdout day {min(leaked)} leaked into the trough frame")
    symbols = [symbol for symbol in TRADE_SYMBOLS if any(key[0] == symbol for key in book)]
    days = sorted({day for (_symbol, day) in book})
    history = {symbol: _empty_history() for symbol in symbols}
    rows: list[dict[str, Any]] = []
    for day in days:
        paths: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            bars = book.get((symbol, day))
            if not bars:
                continue
            minutes = np.array([int(bar["minute"]) for bar in bars], dtype=np.int32)
            if OPEN_MINUTE not in set(minutes.tolist()) or FLAT_MINUTE not in set(minutes.tolist()):
                continue
            prepared = _prepare_day(bars, minutes)
            if prepared is None:
                continue
            paths[symbol] = prepared
        daily = {symbol: _day_features(history[symbol]) for symbol in symbols}
        market_by_minute: dict[int, dict[str, float]] = {}
        for symbol in CONTEXT:
            prepared = paths.get(symbol)
            if prepared is None:
                continue
            stats = daily[symbol]
            atr0 = float(prepared["atr"][MIN_INDEX]) if len(prepared["atr"]) > MIN_INDEX else np.nan
            slots = _market_path(
                prepared["highs"],
                prepared["lows"],
                prepared["closes"],
                prepared["opens"],
                prepared["volumes"],
                atr0 if np.isfinite(atr0) else 0.0,
                stats["prior_ret"],
                stats["rv_20"],
            )
            for index, slot in slots.items():
                minute = int(prepared["minutes"][index])
                bucket = market_by_minute.setdefault(minute, {})
                prefix = symbol.lower()
                bucket[f"{prefix}_from_open"] = slot["from_open"]
                bucket[f"{prefix}_vwap_dist"] = slot["vwap_dist"]
                bucket[f"{prefix}_prior_ret"] = slot["prior_ret"]
                bucket[f"{prefix}_rv_20"] = slot["rv_20"]
        for symbol in symbols:
            prepared = paths.get(symbol)
            if prepared is None:
                continue
            rows.extend(_trough_rows(symbol, day, prepared, daily[symbol], market_by_minute))
            _append_day(
                history[symbol],
                float(np.max(prepared["highs"])),
                float(np.min(prepared["lows"])),
                float(prepared["closes"][prepared["flat_index"]]),
                _ac1(prepared["closes"]),
            )
    if not rows:
        return pd.DataFrame(columns=list(FEATURE_COLUMNS))
    frame = pd.DataFrame(rows)
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=list(FEATURE_COLUMNS) + ["y_hit"])
    frame["day"] = pd.to_datetime(frame["day"]).dt.date
    return frame.reset_index(drop=True)


def _prepare_day(bars: list[dict[str, Any]], minutes: np.ndarray) -> dict[str, Any] | None:
    flat_hits = np.flatnonzero(minutes == FLAT_MINUTE)
    if len(flat_hits) == 0:
        return None
    closes = np.array([float(bar["close"]) for bar in bars], dtype=np.float64)
    opens = np.array([float(bar["open"]) for bar in bars], dtype=np.float64)
    highs = np.array([float(bar["high"]) for bar in bars], dtype=np.float64)
    lows = np.array([float(bar["low"]) for bar in bars], dtype=np.float64)
    volumes = np.array([float(bar["volume"]) for bar in bars], dtype=np.float64)
    ranges = _true_ranges(highs, lows, closes)
    atr = np.full(len(closes), np.nan)
    if len(closes) > MIN_INDEX:
        window = np.cumsum(ranges)
        for index in range(MIN_INDEX - 1, len(closes)):
            start = index - 13
            atr[index] = (window[index] - (window[start - 1] if start else 0.0)) / 14.0
    cum_pv = np.cumsum(((highs + lows + closes) / 3.0) * np.maximum(volumes, 0.0))
    cum_v = np.cumsum(np.maximum(volumes, 0.0))
    vwaps = np.divide(cum_pv, cum_v, out=np.full(len(closes), np.nan), where=cum_v > 0)
    session_high = np.maximum.accumulate(highs)
    session_low = np.minimum.accumulate(lows)
    span = session_high - session_low
    session_pos = np.divide(closes - session_low, span, out=np.full(len(closes), np.nan), where=span > 0)
    return {
        "bars": bars,
        "minutes": minutes,
        "closes": closes,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
        "atr": atr,
        "vwaps": vwaps,
        "session_pos": session_pos,
        "session_high": session_high,
        "session_low": session_low,
        "flat_index": int(flat_hits[0]),
    }


def _trough_rows(
    symbol: str,
    day: date,
    prepared: dict[str, Any],
    daily: dict[str, float],
    market_by_minute: dict[int, dict[str, float]],
) -> list[dict[str, Any]]:
    hits = trough_indices(
        prepared["lows"],
        prepared["closes"],
        prepared["vwaps"],
        prepared["session_pos"],
        prepared["minutes"],
    )
    closes = prepared["closes"]
    highs = prepared["highs"]
    lows = prepared["lows"]
    volumes = prepared["volumes"]
    atrs = prepared["atr"]
    flat_index = prepared["flat_index"]
    opened = float(prepared["opens"][0])
    out = []
    for index in hits:
        entry_index = index + 1
        if entry_index > flat_index:
            continue
        if int(prepared["minutes"][entry_index]) >= FLAT_MINUTE:
            continue
        atr = float(atrs[index])
        if not np.isfinite(atr) or atr <= 0 or opened <= 0:
            continue
        minute = int(prepared["minutes"][index])
        market = market_by_minute.get(minute)
        if market is None:
            continue
        vol_window = volumes[index - 11 : index + 1]
        median = float(np.median(vol_window))
        swing_high = float(np.max(highs[index - 11 : index + 1]))
        row = {
            "symbol": symbol,
            "day": day,
            "minute": minute,
            "atr": atr,
            "y_hit": bounce_hit(prepared["bars"], entry_index, flat_index, atr),
            "ret_3": closes[index] / closes[index - 3] - 1.0,
            "ret_6": closes[index] / closes[index - 6] - 1.0,
            "ret_12": closes[index] / closes[index - 12] - 1.0,
            "rsi_14": _rsi(closes, index),
            "z_12": _zscore(closes, index, 12),
            "vwap_dist": (closes[index] - prepared["vwaps"][index]) / atr,
            "session_pos": prepared["session_pos"][index],
            "range_atr": (prepared["session_high"][index] - prepared["session_low"][index]) / atr,
            "swing_12": (swing_high - float(np.min(lows[index - 11 : index + 1]))) / atr,
            "vol_surge": volumes[index] / median if median > 0 else np.nan,
            "low_dist": (closes[index] - prepared["session_low"][index]) / atr,
            "trough_depth": (float(np.max(highs[index - TROUGH_BARS : index + 1])) - closes[index]) / atr,
            "tod": minute / (15 * 60 + 50),
            "dow": float(day.weekday()),
            "gap_atr": (opened - float(daily["prior_close"])) / atr if daily["prior_close"] and daily["prior_close"] > 0 else np.nan,
            "prior_ret": daily["prior_ret"],
            "dist_ma5": daily["dist_ma5"],
            "dist_range_20": daily["dist_range_20"],
            "rv_20": daily["rv_20"],
            "osc_rate": daily["osc_rate"],
            "ac1": daily["ac1"],
        }
        for key in (
            "spy_from_open",
            "spy_vwap_dist",
            "spy_prior_ret",
            "spy_rv_20",
            "qqq_from_open",
            "qqq_vwap_dist",
            "qqq_prior_ret",
            "qqq_rv_20",
        ):
            row[key] = market.get(key, np.nan)
        out.append(row)
    return out


def _as_date(value: Any) -> date:
    if type(value) is date:
        return value
    return value.date()


def make_spell(book: dict[tuple[str, date], list[dict[str, Any]]], row: Any, probability: float) -> dict[str, Any] | None:
    """Next-bar open, one ATR target, one ATR stop, flat at 15:55 if neither prints."""
    bars = book.get((str(row.symbol), _as_date(row.day)))
    if not bars:
        return None
    by_minute = {int(bar["minute"]): index for index, bar in enumerate(bars)}
    signal = by_minute.get(int(row.minute))
    flat_index = by_minute.get(FLAT_MINUTE)
    if signal is None or flat_index is None:
        return None
    entry_index = signal + 1
    if entry_index > flat_index:
        return None
    entry = bars[entry_index]
    atr = float(row.atr)
    opened = float(entry["open"])
    if atr <= 0 or opened <= 0:
        return None
    return {
        "symbol": str(row.symbol),
        "day": _as_date(row.day),
        "entry_t": int(entry["t"]),
        "exit_t": int(bars[flat_index]["t"]),
        "stop": opened - STOP_ATR * atr,
        "target": opened + TARGET_ATR * atr,
        "priority": float(probability),
        "invest_fraction": SLOT_FRACTION,
        "entry_bar": entry,
        "exit_bar": bars[flat_index],
        "path": bars[entry_index:flat_index],
        "exit_kind": "flat",
    }


def spells_for(
    frame: pd.DataFrame,
    book: dict[tuple[str, date], list[dict[str, Any]]],
    threshold: float,
) -> list[dict[str, Any]]:
    """One open position per symbol. A higher probability spends cash first."""
    if frame.empty or "prob" not in frame.columns:
        return []
    ordered = frame.sort_values(["day", "minute", "prob"], ascending=[True, True, False])
    busy: dict[str, int] = {}
    spells = []
    for row in ordered.itertuples(index=False):
        if float(row.prob) < threshold:
            continue
        spell = make_spell(book, row, float(row.prob))
        if spell is None:
            continue
        if int(spell["entry_t"]) < busy.get(str(row.symbol), 0):
            continue
        resolved = resolve_exit(spell, use_stop=True)
        if resolved is None:
            continue
        _price, _reason, free_t = resolved
        spells.append(spell)
        busy[str(row.symbol)] = int(free_t or spell["exit_t"])
    return spells


def drop_top_days(trades: list[dict[str, Any]], count: int = 5) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove the sessions with the largest dollar sum. The remainder is the concentration check."""
    by_day: dict[date, float] = {}
    for trade in trades:
        by_day[trade["day"]] = by_day.get(trade["day"], 0.0) + float(trade["net"])
    ranked = sorted(by_day, key=lambda day: (by_day[day], str(day)), reverse=True)
    dropped = ranked[:count]
    dropped_rows = [{"day": day.isoformat(), "net": by_day[day]} for day in dropped]
    keep = {day for day in by_day if day not in set(dropped)}
    kept = [trade for trade in trades if trade["day"] in keep]
    return sum(float(trade["net"]) for trade in kept), kept, dropped_rows
