"""Causal features for the one pre-registered intraday model.

A row is a completed 5-minute bar. The label starts at the next bar's open.
Nothing in the feature vector uses a later bar, a later day, or the label.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from backtest.data import CANDIDATES, CONTEXT
from backtest.ml_registry import FEATURE_COLUMNS, HORIZON_BARS
from backtest.periods import FLAT_MINUTE

SIGNAL_FROM = 9 * 60 + 45
SIGNAL_TO = 14 * 60 + 50
OPEN_MINUTE = 9 * 60 + 30


def _ret(closes: list[float], opens: list[float], index: int, lookback: int) -> float:
    if index >= lookback:
        base = closes[index - lookback]
    else:
        base = opens[0]
    if base <= 0:
        return np.nan
    return closes[index] / base - 1.0


def _std(values: list[float], end: int, window: int) -> float:
    start = max(1, end - window + 1)
    sample = values[start : end + 1]
    if len(sample) < 6:
        return np.nan
    return float(np.std(sample, ddof=0))


def build_frame(book: dict[tuple[str, date], list[dict[str, Any]]]) -> pd.DataFrame:
    """One row per signal bar. ``book`` values are that session's bars, oldest first."""
    symbols = [symbol for symbol in CANDIDATES + CONTEXT if any(key[0] == symbol for key in book)]
    days = sorted({day for (_symbol, day) in book})
    prior_close: dict[str, float] = {}
    prior_ret: dict[str, float] = {}
    prior_range_atr: dict[str, float] = {}
    atr: dict[str, float] = {}
    tr_history: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    close_history: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    volume_history: dict[str, dict[int, list[float]]] = {symbol: {} for symbol in symbols}
    market: dict[tuple[date, int], dict[str, float]] = {}
    base_rows: list[dict[str, Any]] = []

    for day in days:
        # Context symbols first so the same minute's SPY and QQQ state is known.
        for symbol in [item for item in CONTEXT if item in symbols] + [item for item in CANDIDATES if item in symbols]:
            bars = book.get((symbol, day))
            if not bars:
                continue
            minutes = [int(bar["minute"]) for bar in bars]
            if OPEN_MINUTE not in minutes or FLAT_MINUTE not in minutes:
                continue
            closes = [float(bar["close"]) for bar in bars]
            opens = [float(bar["open"]) for bar in bars]
            highs = [float(bar["high"]) for bar in bars]
            lows = [float(bar["low"]) for bar in bars]
            volumes = [float(bar["volume"]) for bar in bars]
            bar_rets = [np.nan]
            for index in range(1, len(bars)):
                prev = closes[index - 1]
                bar_rets.append(closes[index] / prev - 1.0 if prev > 0 else np.nan)
            this_atr = atr.get(symbol)
            this_close = prior_close.get(symbol)
            if symbol in CONTEXT and this_atr and this_close and this_atr > 0:
                _store_market(market, day, symbol, bars, closes, opens, volumes, this_atr, prior_ret.get(symbol))
            if symbol in CANDIDATES and this_atr and this_close and this_atr > 0:
                base_rows.extend(
                    _signal_rows(
                        symbol,
                        day,
                        bars,
                        closes,
                        opens,
                        highs,
                        lows,
                        volumes,
                        bar_rets,
                        this_atr,
                        this_close,
                        prior_ret.get(symbol),
                        prior_range_atr.get(symbol),
                        close_history[symbol],
                        volume_history[symbol],
                    )
                )
            _roll_prior(
                symbol,
                bars,
                highs,
                lows,
                volumes,
                prior_close,
                prior_ret,
                prior_range_atr,
                atr,
                tr_history,
                close_history,
                volume_history,
            )

    if not base_rows:
        return pd.DataFrame(columns=list(FEATURE_COLUMNS))
    frame = pd.DataFrame(base_rows)
    frame = _attach_market(frame, market)
    frame = _attach_ranks(frame)
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=list(FEATURE_COLUMNS) + ["y_scaled"])
    return frame.reset_index(drop=True)


def _store_market(
    market: dict[tuple[date, int], dict[str, float]],
    day: date,
    symbol: str,
    bars: list[dict[str, Any]],
    closes: list[float],
    opens: list[float],
    volumes: list[float],
    this_atr: float,
    yesterday_ret: float | None,
) -> None:
    prefix = symbol.lower()
    cum_pv = 0.0
    cum_v = 0.0
    for index, bar in enumerate(bars):
        typical = (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3.0
        volume = volumes[index]
        cum_pv += typical * volume
        cum_v += volume
        if cum_v <= 0 or this_atr <= 0:
            continue
        vwap = cum_pv / cum_v
        slot = market.setdefault((day, int(bar["minute"])), {})
        slot[f"{prefix}_from_open"] = closes[index] / opens[0] - 1.0 if opens[0] > 0 else np.nan
        slot[f"{prefix}_vwap_dist"] = (closes[index] - vwap) / this_atr
        slot[f"{prefix}_prior_ret"] = yesterday_ret if yesterday_ret is not None else np.nan
        slot[f"{prefix}_ret_12"] = _ret(closes, opens, index, 12)


def _signal_rows(
    symbol: str,
    day: date,
    bars: list[dict[str, Any]],
    closes: list[float],
    opens: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    bar_rets: list[float],
    this_atr: float,
    prior_session_close: float,
    yesterday_ret: float | None,
    yesterday_range: float | None,
    close_history: list[float],
    volume_history: dict[int, list[float]],
) -> list[dict[str, Any]]:
    by_minute = {int(bar["minute"]): index for index, bar in enumerate(bars)}
    flat_index = by_minute.get(FLAT_MINUTE)
    if flat_index is None:
        return []
    vol = this_atr / prior_session_close if prior_session_close > 0 else np.nan
    if not np.isfinite(vol) or vol <= 0:
        return []
    ma_base = close_history[-5:]
    dist_ma5 = np.nan
    if len(ma_base) >= 5 and np.mean(ma_base) > 0:
        dist_ma5 = closes[0] / float(np.mean(ma_base)) - 1.0
    gap = (opens[0] - prior_session_close) / this_atr
    cum_pv = 0.0
    cum_v = 0.0
    session_high = -1e18
    session_low = 1e18
    out = []
    for index, bar in enumerate(bars):
        typical = (highs[index] + lows[index] + closes[index]) / 3.0
        cum_pv += typical * max(volumes[index], 0.0)
        cum_v += max(volumes[index], 0.0)
        session_high = max(session_high, highs[index])
        session_low = min(session_low, lows[index])
        minute = int(bar["minute"])
        if minute < SIGNAL_FROM or minute > SIGNAL_TO:
            continue
        entry_index = index + 1
        if entry_index >= len(bars):
            continue
        exit_index = entry_index + HORIZON_BARS
        if exit_index >= len(bars) or int(bars[exit_index]["minute"]) >= FLAT_MINUTE:
            exit_index = flat_index
            exit_kind = "flat"
            exit_px = float(bars[exit_index]["close"])
        else:
            exit_kind = "sell"
            exit_px = float(bars[exit_index]["open"])
        entry_open = float(bars[entry_index]["open"])
        if entry_open <= 0 or exit_px <= 0 or exit_index <= entry_index:
            continue
        fwd = exit_px / entry_open - 1.0
        fwd_flat = float(bars[flat_index]["close"]) / entry_open - 1.0
        fwd_by_h = {}
        for horizon in (3, 6, 12):
            horizon_i = entry_index + horizon
            if horizon_i >= len(bars) or int(bars[horizon_i]["minute"]) >= FLAT_MINUTE:
                horizon_px = float(bars[flat_index]["close"])
            else:
                horizon_px = float(bars[horizon_i]["open"])
            fwd_by_h[horizon] = horizon_px / entry_open - 1.0 if horizon_px > 0 else np.nan
        vwap = cum_pv / cum_v if cum_v > 0 else np.nan
        span = session_high - session_low
        history = volume_history.get(minute) or []
        rvol = volumes[index] / float(np.mean(history[-20:])) if len(history) >= 5 and np.mean(history[-20:]) > 0 else np.nan
        ret_12 = _ret(closes, opens, index, 12)
        out.append(
            {
                "symbol": symbol,
                "day": day,
                "minute": minute,
                "entry_t": int(bars[entry_index]["t"]),
                "exit_t": int(bars[exit_index]["t"]),
                "exit_kind": exit_kind,
                "fwd_ret": fwd,
                "fwd_3": fwd_by_h[3],
                "fwd_6": fwd_by_h[6],
                "fwd_12": fwd_by_h[12],
                "fwd_flat": fwd_flat,
                "vol": vol,
                "y_scaled": fwd / vol,
                "atr": this_atr,
                "ret_1": _ret(closes, opens, index, 1),
                "ret_3": _ret(closes, opens, index, 3),
                "ret_6": _ret(closes, opens, index, 6),
                "ret_12": ret_12,
                "rv_12": _std(bar_rets, index, 12),
                "rv_36": _std(bar_rets, index, 36),
                "rvol": rvol,
                "vwap_dist": (closes[index] - vwap) / this_atr if np.isfinite(vwap) else np.nan,
                "session_pos": (closes[index] - session_low) / span if span > 0 else 0.5,
                "tod": (minute - OPEN_MINUTE) / 390.0,
                "dow": float(day.weekday()),
                "gap": gap,
                "prior_ret": yesterday_ret if yesterday_ret is not None else np.nan,
                "prior_range_atr": yesterday_range if yesterday_range is not None else np.nan,
                "dist_ma5": dist_ma5,
            }
        )
    return out


def _roll_prior(
    symbol: str,
    bars: list[dict[str, Any]],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    prior_close: dict[str, float],
    prior_ret: dict[str, float],
    prior_range_atr: dict[str, float],
    atr: dict[str, float],
    tr_history: dict[str, list[float]],
    close_history: dict[str, list[float]],
    volume_history: dict[str, dict[int, list[float]]],
) -> None:
    close = float(bars[-1]["close"])
    previous = prior_close.get(symbol)
    true_range = max(highs) - min(lows)
    if previous is not None:
        true_range = max(true_range, abs(max(highs) - previous), abs(min(lows) - previous))
        if previous > 0:
            prior_ret[symbol] = close / previous - 1.0
    tr_history[symbol].append(true_range)
    window = tr_history[symbol][-14:]
    if len(window) >= 5:
        atr[symbol] = float(np.mean(window))
        if atr[symbol] > 0:
            prior_range_atr[symbol] = (max(highs) - min(lows)) / atr[symbol]
    prior_close[symbol] = close
    close_history[symbol].append(close)
    for bar, volume in zip(bars, volumes):
        volume_history[symbol].setdefault(int(bar["minute"]), []).append(volume)


def _attach_market(frame: pd.DataFrame, market: dict[tuple[date, int], dict[str, float]]) -> pd.DataFrame:
    spy_from_open = []
    spy_vwap = []
    spy_prior = []
    qqq_from_open = []
    qqq_vwap = []
    qqq_prior = []
    resid = []
    for row in frame.itertuples(index=False):
        slot = market.get((row.day, int(row.minute))) or {}
        spy_from_open.append(slot.get("spy_from_open", np.nan))
        spy_vwap.append(slot.get("spy_vwap_dist", np.nan))
        spy_prior.append(slot.get("spy_prior_ret", np.nan))
        qqq_from_open.append(slot.get("qqq_from_open", np.nan))
        qqq_vwap.append(slot.get("qqq_vwap_dist", np.nan))
        qqq_prior.append(slot.get("qqq_prior_ret", np.nan))
        spy_ret = slot.get("spy_ret_12", np.nan)
        resid.append(row.ret_12 - spy_ret if np.isfinite(spy_ret) else np.nan)
    frame = frame.copy()
    frame["spy_from_open"] = spy_from_open
    frame["spy_vwap_dist"] = spy_vwap
    frame["spy_prior_ret"] = spy_prior
    frame["qqq_from_open"] = qqq_from_open
    frame["qqq_vwap_dist"] = qqq_vwap
    frame["qqq_prior_ret"] = qqq_prior
    frame["resid_12"] = resid
    return frame


def _attach_ranks(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    group = frame.groupby(["day", "minute"], sort=False)
    frame["xs_rank_ret12"] = group["ret_12"].rank(method="average", pct=True)
    frame["xs_rank_vwap"] = group["vwap_dist"].rank(method="average", pct=True)
    return frame
