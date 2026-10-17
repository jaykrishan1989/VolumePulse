"""Same-minute relative volume. Thresholds are frozen. Do not lower them after a fill.

Price-path rules on this mega-cap tape have no gross edge. Slot fades,
opening-range breaks, a 30 bp residual versus SPY, a 40 bp bar in either
direction, a 30 bp VWAP discount, and the last half-hour were all negative
after 2 bp of slippage and before commission. The clock and the hold were
not the missing piece: 15 minutes, 30 minutes, 60 minutes, and the flat all
failed, from 10:00 through 15:30. The eight names are one growth tape, and
a US$2,120 order is invisible in their volume.

These books use the one field the price tests ignored as a signal: how
unusual this 5-minute bucket's volume is for this name at this minute.
The median is the prior 20 sessions of that same minute, so the open's
ordinary volume is not a signal. Today's bar is not in the median.

``u_primary``. Blume, Easley, and O'Hara (1994) and the intraday reading of
Gervais, Kaniel, and Mingelgrin (2001): volume that is extreme for its own
clock carries information the price change does not. Buy the first bar from
10:00 through 14:00 whose volume is at least twice that median and whose own
return is at least +10 bp. The 10 bp is a direction, not the rejected 40 bp
price shock. The multiple is 2.0, not the rejected 1.2 opening-range filter.
One full ticket, 30 minutes, 100 bp disaster stop. Only this book may open
the holdout.

``u_fade``. Campbell, Grossman, and Wang (1993): unusually heavy volume on a
down move is non-informational selling and should reverse. Same multiple,
bar return at most −10 bp, buy it, same hold. This is not yesterday's daily
volume rule (``n_volume_reversal``) and not a −40 bp bar with no volume
gate (``m_impact``). It is not adoptable.

``u_quiet``. The negative control. A +10 bp bar whose volume is at most half
its own minute. If volume is the information, this book should not be the
edge. It is not adoptable, and a win here is not a promotion.

The adoption screen is the one already frozen for the session-edge batch:
positive validation, pooled, and recent nets, four of six half-years, a
positive net without the five best days, at least 80 trades, a positive
average basis-point result, and a fill on at least half of sessions.

Nothing here places an order. Earnings dates are not in these files and are
not invented.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backtest.data import CANDIDATES
from backtest.hypotheses import make_spell
from backtest.periods import FLAT_MINUTE, HOLDOUT_START
from backtest.session_edge import DAY_SHARE_MIN, clears_published_milestone, screen_failures

# Frozen before the fill. Not a search over the rejected 1.2 or the rejected 40 bp.
RVOL_MULT = 2.0
RVOL_QUIET = 0.5
RVOL_WINDOW = 20
PRICE_FLOOR = 0.0010
HOLD_BARS = 6
DISASTER_STOP = 0.0100
SIGNAL_FROM = 10 * 60
SIGNAL_TO = 14 * 60
OPEN_MINUTE = 9 * 60 + 30
SHOCK_RETURN = 0.0040

ADOPTABLE = frozenset({"u_primary"})
BOOK_NAMES = ("u_primary", "u_fade", "u_quiet")


def assert_no_holdout(day: date) -> None:
    if day >= HOLDOUT_START:
        raise RuntimeError(f"holdout day {day} leaked into volume-edge selection")


@dataclass
class VolumeResult:
    spells: dict[str, list[dict[str, Any]]]
    days: list[dict[str, Any]] = field(default_factory=list)


def _rth(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [bar for bar in bars if OPEN_MINUTE <= int(bar["minute"]) <= FLAT_MINUTE + 5]


def _median(history: list[float]) -> float | None:
    window = history[-RVOL_WINDOW:]
    if len(window) < RVOL_WINDOW:
        return None
    value = float(statistics.median(window))
    if value <= 0:
        return None
    return value


def _exit_at(bars: list[dict[str, Any]], entry_i: int, hold_bars: int) -> tuple[int, str] | None:
    flat_i = None
    for index, bar in enumerate(bars):
        if int(bar["minute"]) <= FLAT_MINUTE:
            flat_i = index
        else:
            break
    if flat_i is None or entry_i >= flat_i:
        return None
    exit_i = entry_i + hold_bars
    if exit_i >= len(bars) or int(bars[exit_i]["minute"]) > FLAT_MINUTE or exit_i > flat_i:
        return flat_i, "flat"
    return exit_i, "sell"


def _emit(bars: list[dict[str, Any]], day: date, entry_i: int, priority: float) -> dict[str, Any] | None:
    if entry_i < 0 or entry_i >= len(bars) or int(bars[entry_i]["minute"]) >= FLAT_MINUTE:
        return None
    scheduled = _exit_at(bars, entry_i, HOLD_BARS)
    if scheduled is None:
        return None
    exit_i, kind = scheduled
    entry_open = float(bars[entry_i]["open"])
    if entry_open <= 0:
        return None
    spell = make_spell(
        symbol="",
        day=day,
        bars=bars,
        entry_i=entry_i,
        exit_i=exit_i,
        stop=entry_open * (1.0 - DISASTER_STOP),
        priority=priority,
        exit_kind=kind,
    )
    if spell is None:
        return None
    spell["invest_fraction"] = 1.0
    return spell


def _qualify(
    kind: str,
    rvol: float,
    ret: float,
) -> bool:
    if kind == "up":
        return rvol + 1e-12 >= RVOL_MULT and ret + 1e-12 >= PRICE_FLOOR
    if kind == "down":
        return rvol + 1e-12 >= RVOL_MULT and ret <= -PRICE_FLOOR + 1e-12
    if kind == "quiet":
        return rvol <= RVOL_QUIET + 1e-12 and ret + 1e-12 >= PRICE_FLOOR
    raise ValueError(kind)


def _pick(
    named: list[tuple[str, list[dict[str, Any]], dict[int, int]]],
    history: dict[str, dict[int, list[float]]],
    day: date,
    kind: str,
) -> dict[str, Any] | None:
    for minute in range(SIGNAL_FROM, SIGNAL_TO + 1, 5):
        rows: list[tuple[float, str, list[dict[str, Any]], int, float]] = []
        for symbol, bars, at in named:
            index = at.get(minute)
            if index is None:
                continue
            baseline = _median(history[symbol][minute])
            if baseline is None:
                continue
            bar = bars[index]
            opened = float(bar["open"])
            if opened <= 0:
                continue
            rvol = float(bar.get("volume") or 0.0) / baseline
            ret = float(bar["close"]) / opened - 1.0
            if not _qualify(kind, rvol, ret):
                continue
            rows.append((rvol, symbol, bars, index, ret))
        if not rows:
            continue
        if kind == "quiet":
            rvol, symbol, bars, index, ret = min(rows, key=lambda row: (row[0], row[1]))
        else:
            rvol, symbol, bars, index, ret = min(rows, key=lambda row: (-row[0], row[1]))
        spell = _emit(bars, day, index + 1, priority=rvol)
        if spell is None:
            continue
        spell["symbol"] = symbol
        spell["signal_rvol"] = rvol
        spell["signal_return"] = ret
        return spell
    return None


def _coverage(
    named: list[tuple[str, list[dict[str, Any]], dict[int, int]]],
    history: dict[str, dict[int, list[float]]],
) -> dict[str, bool]:
    flags = {"up": False, "down": False, "quiet": False}
    for minute in range(SIGNAL_FROM, SIGNAL_TO + 1, 5):
        for symbol, bars, at in named:
            index = at.get(minute)
            if index is None:
                continue
            baseline = _median(history[symbol][minute])
            if baseline is None:
                continue
            bar = bars[index]
            opened = float(bar["open"])
            if opened <= 0:
                continue
            rvol = float(bar.get("volume") or 0.0) / baseline
            ret = float(bar["close"]) / opened - 1.0
            for kind in flags:
                if _qualify(kind, rvol, ret):
                    flags[kind] = True
    return flags


def generate(book: dict[tuple[str, date], list[dict[str, Any]]]) -> VolumeResult:
    """Walk every pre-holdout session once. Later days do not change earlier spells."""
    for _symbol, day in book:
        assert_no_holdout(day)
    tapes: dict[str, dict[date, tuple[list[dict[str, Any]], dict[int, int]]]] = {}
    for symbol in CANDIDATES:
        days = sorted(day for sym, day in book if sym == symbol)
        if not days:
            continue
        tapes[symbol] = {}
        for day in days:
            ordered = _rth(book[(symbol, day)])
            if not ordered:
                continue
            tapes[symbol][day] = (ordered, {int(bar["minute"]): index for index, bar in enumerate(ordered)})
    history: dict[str, dict[int, list[float]]] = {
        symbol: {minute: [] for minute in range(OPEN_MINUTE, FLAT_MINUTE + 5, 5)} for symbol in tapes
    }
    spells: dict[str, list[dict[str, Any]]] = {name: [] for name in BOOK_NAMES}
    covered: list[dict[str, Any]] = []
    all_days = sorted({day for by_day in tapes.values() for day in by_day})
    for day in all_days:
        named = [(symbol, tapes[symbol][day][0], tapes[symbol][day][1]) for symbol in CANDIDATES if day in tapes.get(symbol, {})]
        flags = _coverage(named, history)
        covered.append({"day": day, **flags})
        primary = _pick(named, history, day, "up")
        faded = _pick(named, history, day, "down")
        quiet = _pick(named, history, day, "quiet")
        if primary is not None:
            spells["u_primary"].append(primary)
        if faded is not None:
            spells["u_fade"].append(faded)
        if quiet is not None:
            spells["u_quiet"].append(quiet)
        for symbol, bars, _at in named:
            for bar in bars:
                minute = int(bar["minute"])
                bucket = history[symbol].get(minute)
                if bucket is None:
                    continue
                bucket.append(float(bar.get("volume") or 0.0))
    for name in spells:
        spells[name].sort(key=lambda spell: (spell["day"], spell["entry_t"], spell["symbol"]))
    return VolumeResult(spells, covered)


__all__ = [
    "ADOPTABLE",
    "BOOK_NAMES",
    "DAY_SHARE_MIN",
    "DISASTER_STOP",
    "PRICE_FLOOR",
    "RVOL_MULT",
    "RVOL_QUIET",
    "RVOL_WINDOW",
    "SHOCK_RETURN",
    "clears_published_milestone",
    "generate",
    "screen_failures",
]
