"""Validation-only choices for the profit study.

The grid below is the whole search. Nothing here reads a day on or after the
locked holdout. The runner writes the winner to disk before any holdout fill.
Net dollars after 2 bp slippage are the only score. A candidate with fewer
than ``MIN_TRADES`` validation fills cannot win.
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from backtest.data import CANDIDATES
from backtest.hypotheses import (
    ENTRY_0945,
    FLAT_MINUTE,
    OPEN_MINUTE,
    allow_holdout_days,
    make_spell,
    walk_symbol,
)
from backtest.ml_registry import FEATURE_COLUMNS
from backtest.periods import HOLDOUT_START

PROFIT_BEGIN = "<!-- PROFIT_BEGIN -->"
PROFIT_END = "<!-- PROFIT_END -->"

MIN_TRADES = 50
THRESHOLDS_BPS = (0.0, 10.0, 20.0, 40.0)
STOPS = ("1atr", "none")
BOOKS = ("concurrent", "top1")
SIZES = (1.0, 0.5)
GAPS = (-0.002, -0.004, -0.008, -0.015)
GAP_EXITS = ("flat", "60min")
SEQ_COLUMNS = ("ret_1_l1", "ret_1_l2", "ret_1_l3")
LABEL_CLIP = 0.05

SMALL_PARAMS = {
    "objective": "regression",
    "metric": "l2",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_data_in_leaf": 500,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "num_threads": 4,
    "force_col_wise": True,
}
WIDE_PARAMS = {
    **SMALL_PARAMS,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 200,
}
ROUNDS = {"small": 80, "wide": 120}


def model_specs() -> list[dict[str, Any]]:
    """One row per fitted model. Exits are the trades that model is allowed to run."""
    base = list(FEATURE_COLUMNS)
    seq = base + list(SEQ_COLUMNS)
    return [
        {"name": "h3", "label": "fwd_3", "features": base, "params": "small", "horizon": 3, "exits": ("horizon", "signal_off")},
        {"name": "h6", "label": "fwd_6", "features": base, "params": "small", "horizon": 6, "exits": ("horizon", "signal_off")},
        {"name": "h12", "label": "fwd_12", "features": base, "params": "small", "horizon": 12, "exits": ("horizon", "signal_off")},
        {"name": "h12_wide", "label": "fwd_12", "features": base, "params": "wide", "horizon": 12, "exits": ("horizon", "signal_off")},
        {"name": "h12_seq", "label": "fwd_12", "features": seq, "params": "small", "horizon": 12, "exits": ("horizon", "signal_off")},
        {"name": "flat", "label": "fwd_flat", "features": base, "params": "small", "horizon": 12, "exits": ("flat",)},
    ]


def assert_preholdout_days(days: list[date] | pd.Series, where: str) -> None:
    if len(days) == 0:
        return
    latest = max(days)
    if latest >= HOLDOUT_START:
        raise RuntimeError(f"{where} saw holdout day {latest}")


def add_return_lags(frame: pd.DataFrame) -> pd.DataFrame:
    """Prior completed bars' one-bar returns. The current bar is not lagged into itself."""
    out = frame.sort_values(["symbol", "day", "minute"]).copy()
    grouped = out.groupby(["symbol", "day"], sort=False)["ret_1"]
    out["ret_1_l1"] = grouped.shift(1)
    out["ret_1_l2"] = grouped.shift(2)
    out["ret_1_l3"] = grouped.shift(3)
    return out


def stack_oos(
    frame: pd.DataFrame,
    predictors: list[str],
    label: str,
    test_days: list[date],
    min_rows: int = 500,
) -> pd.Series:
    """OLS of ``label`` on earlier days only. The test day's own label is not in the fit."""
    assert_preholdout_days(list(frame["day"].unique()), "stack")
    assert_preholdout_days(test_days, "stack test")
    work = frame.dropna(subset=predictors + [label]).sort_values(["day", "symbol", "minute"]).reset_index()
    pred = pd.Series(np.nan, index=frame.index, dtype=float)
    if work.empty:
        return pred
    days = list(work["day"])
    matrix = np.column_stack([np.ones(len(work)), work[predictors].to_numpy(dtype=np.float64)])
    target = work[label].to_numpy(dtype=np.float64)
    day_start: dict[date, int] = {}
    for index, day in enumerate(days):
        day_start.setdefault(day, index)
    ordered = list(day_start.items())
    wanted = set(test_days)
    for position, (day, start) in enumerate(ordered):
        if day not in wanted:
            continue
        embargo = day - timedelta(days=1)
        cut = 0
        for prior, prior_start in ordered:
            if prior >= embargo:
                cut = prior_start
                break
        else:
            cut = len(work)
        if cut < min_rows:
            continue
        coef, *_rest = np.linalg.lstsq(matrix[:cut], target[:cut], rcond=None)
        end = ordered[position + 1][1] if position + 1 < len(ordered) else len(work)
        fitted = np.clip(matrix[start:end] @ coef, -LABEL_CLIP, LABEL_CLIP)
        original = work.loc[start : end - 1, "index"].to_numpy()
        pred.loc[original] = fitted
    return pred


def choose_winner(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Highest validation net among candidates with enough fills. Holdout rows are refused."""
    if not rows:
        raise RuntimeError("no candidates")
    for row in rows:
        window_end = row.get("window_end", HOLDOUT_START)
        if isinstance(window_end, str):
            window_end = date.fromisoformat(window_end)
        if window_end >= HOLDOUT_START:
            raise RuntimeError(f"{row.get('id')} selection window reaches the holdout")
    eligible = [row for row in rows if int(row["trades"]) >= MIN_TRADES]
    if not eligible:
        raise RuntimeError("no candidate had enough validation trades")
    return max(eligible, key=lambda row: (float(row["net"]), int(row["trades"]), str(row["id"])))


def best_of(rows: list[dict[str, Any]], family: str) -> dict[str, Any]:
    return choose_winner([row for row in rows if row["family"] == family])


def _scheduled(bars: list[dict[str, Any]], exit_i: int) -> tuple[int, str] | None:
    flat_i = next((index for index, bar in enumerate(bars) if int(bar["minute"]) == FLAT_MINUTE), None)
    if flat_i is None:
        return None
    if exit_i >= len(bars) or int(bars[exit_i]["minute"]) >= FLAT_MINUTE:
        return flat_i, "flat"
    return exit_i, "sell"


def gap_spells(
    book: dict[tuple[str, date], list[dict[str, Any]]],
    *,
    gap_max: float,
    stop_mode: str,
    exit_mode: str,
    allow_holdout: bool = False,
) -> list[dict[str, Any]]:
    """Down-gap longs. ``gap_max`` of -0.004 with a 1 ATR stop and a flat exit is the frozen rule."""
    context = allow_holdout_days() if allow_holdout else nullcontext()
    spells: list[dict[str, Any]] = []
    with context:
        for symbol in CANDIDATES:
            for day, bars, minutes, atrs, _vwaps, prev_close in walk_symbol(book, symbol):
                open_i = minutes.get(OPEN_MINUTE)
                entry_i = minutes.get(ENTRY_0945)
                if None in (open_i, entry_i) or prev_close is None or prev_close <= 0:
                    continue
                assert open_i is not None and entry_i is not None
                if not (open_i < entry_i):
                    continue
                gap = float(bars[open_i]["open"]) / prev_close - 1.0
                atr = atrs[entry_i]
                if gap > gap_max or atr is None or atr <= 0:
                    continue
                entry_open = float(bars[entry_i]["open"])
                if exit_mode == "flat":
                    scheduled = _scheduled(bars, len(bars))
                elif exit_mode == "60min":
                    scheduled = _scheduled(bars, entry_i + 12)
                else:
                    raise ValueError(exit_mode)
                if scheduled is None:
                    continue
                exit_i, kind = scheduled
                if stop_mode == "1atr":
                    stop = entry_open - float(atr)
                elif stop_mode == "none":
                    stop = entry_open * 0.5
                else:
                    raise ValueError(stop_mode)
                spell = make_spell(
                    symbol=symbol,
                    day=day,
                    bars=bars,
                    entry_i=entry_i,
                    exit_i=exit_i,
                    stop=stop,
                    priority=-gap * 100.0,
                    exit_kind=kind,
                )
                if spell is not None:
                    spells.append(spell)
    return spells


def with_size(spells: list[dict[str, Any]], size: float) -> list[dict[str, Any]]:
    if size == 1.0:
        return spells
    sized = []
    for spell in spells:
        copy = dict(spell)
        copy["invest_fraction"] = float(size)
        sized.append(copy)
    return sized


def take_spells(spells: list[dict[str, Any]], book_mode: str) -> list[dict[str, Any]]:
    """Drop same-name overlaps, or keep only the strongest signal of each day."""
    if book_mode == "top1":
        best: dict[date, dict[str, Any]] = {}
        for spell in spells:
            current = best.get(spell["day"])
            if current is None or float(spell["priority"]) > float(current["priority"]):
                best[spell["day"]] = spell
        return list(best.values())
    if book_mode != "concurrent":
        raise ValueError(book_mode)
    ordered = sorted(spells, key=lambda spell: (int(spell["entry_t"]), -float(spell["priority"]), spell["symbol"]))
    busy: dict[str, int] = {}
    taken = []
    for spell in ordered:
        if int(spell["entry_t"]) < busy.get(spell["symbol"], 0):
            continue
        taken.append(spell)
        busy[spell["symbol"]] = int(spell["exit_t"])
    return taken


def _signal_off_exit(
    bars: list[dict[str, Any]],
    signal_index: int,
    pred_by_minute: dict[int, float],
    horizon: int,
) -> tuple[int, str] | None:
    """Leave at the next open after a later bar predicts a negative return."""
    flat = _scheduled(bars, len(bars))
    if flat is None:
        return None
    for index in range(signal_index + 1, len(bars)):
        minute = int(bars[index]["minute"])
        if minute >= FLAT_MINUTE:
            break
        pred = pred_by_minute.get(minute)
        if pred is None or pred >= 0:
            continue
        return _scheduled(bars, index + 1)
    return _scheduled(bars, signal_index + 1 + horizon)


def ml_spells(
    frame: pd.DataFrame,
    book: dict[tuple[str, date], list[dict[str, Any]]],
    *,
    horizon: int,
    exit_mode: str,
    stop_mode: str,
    min_pred: float,
    allow_holdout: bool = False,
) -> list[dict[str, Any]]:
    """Turn predicted returns into next-bar spells. Holdout rows are refused unless the one evaluation asks."""
    if not allow_holdout:
        assert_preholdout_days(list(frame["day"].unique()) if len(frame) else [], "ml spells")
    if frame.empty:
        return []
    eligible = frame.loc[frame["pred"] >= min_pred]
    spells: list[dict[str, Any]] = []
    bars_cache: dict[tuple[str, date], list[dict[str, Any]] | None] = {}
    pred_cache: dict[tuple[str, date], dict[int, float]] = {}
    if exit_mode == "signal_off":
        for key, chunk in frame.groupby(["symbol", "day"], sort=False):
            pred_cache[key] = {int(minute): float(value) for minute, value in zip(chunk["minute"], chunk["pred"])}
    minute_cache: dict[tuple[str, date], dict[int, int]] = {}
    for row in eligible.itertuples(index=False):
        key = (row.symbol, row.day)
        if key not in bars_cache:
            bars_cache[key] = book.get(key)
            found = bars_cache[key]
            minute_cache[key] = {int(bar["minute"]): index for index, bar in enumerate(found)} if found else {}
        bars = bars_cache[key]
        if not bars:
            continue
        signal = minute_cache[key].get(int(row.minute))
        if signal is None or signal + 1 >= len(bars):
            continue
        entry_i = signal + 1
        if exit_mode == "horizon":
            scheduled = _scheduled(bars, entry_i + horizon)
        elif exit_mode == "flat":
            scheduled = _scheduled(bars, len(bars))
        elif exit_mode == "signal_off":
            scheduled = _signal_off_exit(bars, signal, pred_cache.get(key, {}), horizon)
        else:
            raise ValueError(exit_mode)
        if scheduled is None:
            continue
        exit_i, kind = scheduled
        entry_open = float(bars[entry_i]["open"])
        atr = float(row.atr)
        if not np.isfinite(atr) or atr <= 0 or entry_open <= 0:
            continue
        if stop_mode == "1atr":
            stop = entry_open - atr
        elif stop_mode == "none":
            stop = entry_open * 0.5
        else:
            raise ValueError(stop_mode)
        spell = make_spell(
            symbol=row.symbol,
            day=row.day,
            bars=bars,
            entry_i=entry_i,
            exit_i=exit_i,
            stop=stop,
            priority=float(row.pred),
            exit_kind=kind,
        )
        if spell is not None:
            spells.append(spell)
    return spells
