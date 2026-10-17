"""Fifteen-minute decision grid. Tiers follow research/RESEARCH_PRO_TRADERS.md.

Rules in this file were frozen before the validation fill. Leave-one-out
books are a report. Only ``pro_aplus`` can clear the milestone, and only on
validation dollars after costs. Nothing here places an order.

The grid is 26 buckets from 9:30 through 15:45 ET. A decision at the end of a
bucket uses bars inside that bucket. A fill is the next 5-minute open.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from backtest.costs import apply_slip
from backtest.data import CANDIDATES, CONTEXT
from backtest.periods import FLAT_MINUTE, HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.spells import ACCOUNT_USD, SLIP_BPS

PUBLISHED_MODEL_VALIDATION_NET = 1260.736236000008
MIN_TRADES = 80
PRIMARY = "pro_aplus"

OPEN_MINUTE = 9 * 60 + 30
OR_START = OPEN_MINUTE
SLOT_STARTS = tuple(OPEN_MINUTE + 15 * i for i in range(26))
MORNING_STARTS = (OPEN_MINUTE + 15, OPEN_MINUTE + 30, OPEN_MINUTE + 45, OPEN_MINUTE + 60, OPEN_MINUTE + 75)
AFTERNOON_STARTS = (14 * 60, 14 * 60 + 15, 14 * 60 + 30, 14 * 60 + 45)
LUNCH_EXIT_MINUTE = 12 * 60

# Frozen. Not a grid.
RVOL_IN_PLAY = 1.2
RVOL_SLOT = 1.0
HISTORY_DAYS = 20
GAP_VETO = -0.01
GAP_FLAG_MULTIPLE = 2.0
GAP_HISTORY = 60
MIN_STOP = 0.0012
MAX_STOP = 0.025
MAX_EXTENSION = 1.0
INDEX_SMASH = -0.005
BREADTH_MIN = 5
RISK_FRACTION = 0.005
MAX_NOTIONAL = 0.25
DAILY_LOSS = 0.015
SHOCK_SCALE = 0.5
OPEX_SCALE = 0.75
EVENT_SCALE = 0.5
SMA_DAYS = 20

OPTIONAL_TIERS = (
    "vwap",
    "volume_rate",
    "relative_strength",
    "internals",
    "gap",
    "prior_levels",
    "events",
    "trend",
)

# FOMC statement day is the second day, 14:00 ET.
# https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# 2022-01-26 and 2023-02-01 are the first meeting of those years on that
# calendar. Validation starts 2024-07, so those two cannot change the book.
FOMC_STATEMENT_DAYS = frozenset(
    {
        date(2022, 1, 26),
        date(2022, 3, 16),
        date(2022, 5, 4),
        date(2022, 6, 15),
        date(2022, 7, 27),
        date(2022, 9, 21),
        date(2022, 11, 2),
        date(2022, 12, 14),
        date(2023, 2, 1),
        date(2023, 3, 22),
        date(2023, 5, 3),
        date(2023, 6, 14),
        date(2023, 7, 26),
        date(2023, 9, 20),
        date(2023, 11, 1),
        date(2023, 12, 13),
        date(2024, 1, 31),
        date(2024, 3, 20),
        date(2024, 5, 1),
        date(2024, 6, 12),
        date(2024, 7, 31),
        date(2024, 9, 18),
        date(2024, 11, 7),
        date(2024, 12, 18),
        date(2025, 1, 29),
        date(2025, 3, 19),
        date(2025, 5, 7),
        date(2025, 6, 18),
        date(2025, 7, 30),
        date(2025, 9, 17),
        date(2025, 10, 29),
        date(2025, 12, 10),
        date(2026, 1, 28),
        date(2026, 3, 18),
        date(2026, 4, 29),
        date(2026, 6, 17),
        date(2026, 7, 29),
        date(2026, 9, 16),
        date(2026, 10, 28),
        date(2026, 12, 9),
    }
)

# BLS 8:30 ET CPI releases. July 2024 through 2026 are the dates the validation
# window and a later holdout can touch. Earlier dates are omitted, not guessed.
# October 2025 was not published. November 2025 was released 2025-12-18.
# https://www.bls.gov/schedule/news_release/cpi.htm
CPI_DAYS = frozenset(
    {
        date(2024, 7, 11),
        date(2024, 8, 14),
        date(2024, 9, 11),
        date(2024, 10, 10),
        date(2024, 11, 13),
        date(2024, 12, 11),
        date(2025, 1, 15),
        date(2025, 2, 12),
        date(2025, 3, 12),
        date(2025, 4, 10),
        date(2025, 5, 13),
        date(2025, 6, 11),
        date(2025, 7, 15),
        date(2025, 8, 12),
        date(2025, 9, 11),
        date(2025, 10, 24),
        date(2025, 12, 18),
        date(2026, 1, 13),
        date(2026, 2, 13),
        date(2026, 3, 11),
        date(2026, 4, 10),
        date(2026, 5, 12),
        date(2026, 6, 10),
        date(2026, 7, 14),
        date(2026, 8, 12),
        date(2026, 9, 11),
        date(2026, 10, 14),
        date(2026, 11, 10),
        date(2026, 12, 10),
    }
)

# First Friday is the BLS employment-situation convention. These three were
# moved: January 2025 (day of mourning), and the 2026 lapse revisions.
NFP_REPLACEMENTS = {
    date(2025, 1, 3): date(2025, 1, 10),
    date(2026, 1, 2): date(2026, 1, 9),
    date(2026, 2, 6): date(2026, 2, 11),
}


@dataclass(frozen=True)
class TierVote:
    """One specialist's answer. A new tier returns the same shape."""

    name: str
    score: float
    veto: bool
    size_scale: float
    reason: str


@dataclass(frozen=True)
class BookSpec:
    name: str
    kind: str
    disabled: frozenset[str]
    adoptable: bool


def _leave_one_out() -> tuple[BookSpec, ...]:
    books = [
        BookSpec(PRIMARY, "orb", frozenset(), True),
        BookSpec("bare_or", "orb", frozenset(OPTIONAL_TIERS), False),
    ]
    for name in OPTIONAL_TIERS:
        books.append(BookSpec(f"no_{name}", "orb", frozenset({name}), False))
    books.append(BookSpec("pro_vwap", "vwap", frozenset(), False))
    books.append(BookSpec("pro_short", "short", frozenset(), False))
    return tuple(books)


BOOKS = _leave_one_out()


@dataclass
class SymbolHist:
    closes: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    or_volumes: list[float] = field(default_factory=list)
    abs_gaps: list[float] = field(default_factory=list)
    daily_returns: list[float] = field(default_factory=list)
    slot_volumes: dict[int, list[float]] = field(default_factory=dict)

    def sma(self) -> float | None:
        if len(self.closes) < SMA_DAYS:
            return None
        window = self.closes[-SMA_DAYS:]
        return sum(window) / len(window)

    def median(self, values: list[float], n: int = HISTORY_DAYS) -> float | None:
        if len(values) < n:
            return None
        return float(statistics.median(values[-n:]))


@dataclass
class DayView:
    ordered: list[dict[str, Any]]
    by_minute: dict[int, dict[str, Any]]


def signal_minute(start: int) -> int:
    return min(start + 10, FLAT_MINUTE)


def nfp_day(year: int, month: int) -> date:
    cursor = date(year, month, 1)
    while cursor.weekday() != 4:
        cursor += timedelta(days=1)
    return NFP_REPLACEMENTS.get(cursor, cursor)


def is_nfp(day: date) -> bool:
    return day == nfp_day(day.year, day.month)


def third_friday(day: date) -> date:
    cursor = date(day.year, day.month, 1)
    while cursor.weekday() != 4:
        cursor += timedelta(days=1)
    return cursor + timedelta(days=14)


def is_month_end(day: date) -> bool:
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt.month != day.month


def is_milestone(net: float, net_ex_top5: float, trades: int) -> bool:
    return trades >= MIN_TRADES and net > PUBLISHED_MODEL_VALIDATION_NET and net_ex_top5 > 0.0


def assert_no_holdout(book: dict[tuple[str, date], list[dict[str, Any]]], *, allow_holdout: bool) -> None:
    if allow_holdout:
        return
    leaked = [day for (_symbol, day) in book if day >= HOLDOUT_START]
    if leaked:
        raise RuntimeError(f"holdout day {min(leaked)} leaked into the 15-minute grid")


def prepare_day(bars: list[dict[str, Any]]) -> DayView | None:
    ordered = [bar for bar in sorted(bars, key=lambda item: int(item["minute"])) if OPEN_MINUTE <= int(bar["minute"]) <= FLAT_MINUTE]
    by_minute = {int(bar["minute"]): bar for bar in ordered}
    if OPEN_MINUTE not in by_minute or FLAT_MINUTE not in by_minute:
        return None
    return DayView(ordered, by_minute)


def slot_bars(day: DayView, start: int) -> list[dict[str, Any]] | None:
    found = []
    for minute in (start, start + 5, start + 10):
        if minute > FLAT_MINUTE:
            continue
        bar = day.by_minute.get(minute)
        if bar is None:
            return None
        found.append(bar)
    return found or None


def vwap_through(day: DayView, minute: int) -> float | None:
    price_volume = 0.0
    volume = 0.0
    for bar in day.ordered:
        if int(bar["minute"]) > minute:
            break
        typical = (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3.0
        bar_volume = float(bar["volume"])
        if bar_volume <= 0:
            continue
        price_volume += typical * bar_volume
        volume += bar_volume
    if volume <= 0:
        return None
    return price_volume / volume


def from_open(day: DayView, minute: int) -> float | None:
    opened = day.by_minute.get(OPEN_MINUTE)
    bar = day.by_minute.get(minute)
    if opened is None or bar is None or float(opened["open"]) <= 0:
        return None
    return float(bar["close"]) / float(opened["open"]) - 1.0


def _index_at(day: DayView, minute: int) -> int | None:
    for index, bar in enumerate(day.ordered):
        if int(bar["minute"]) == minute:
            return index
    return None


def _exit_index(day: DayView, entry_index: int, target_minute: int) -> tuple[int, str] | None:
    if target_minute >= FLAT_MINUTE:
        flat_index = _index_at(day, FLAT_MINUTE)
        if flat_index is None or flat_index <= entry_index:
            return None
        return flat_index, "flat"
    for index in range(entry_index + 1, len(day.ordered)):
        minute = int(day.ordered[index]["minute"])
        if minute >= target_minute:
            if minute >= FLAT_MINUTE:
                return index, "flat"
            return index, "sell"
    return None


def plan_exit(
    bars: list[dict[str, Any]],
    entry_index: int,
    exit_index: int,
    stop: float,
    target: float | None,
    exit_kind: str,
    *,
    breakeven_after: float | None,
) -> dict[str, Any] | None:
    """Path, stop, and target that ``resolve_exit`` will fill the same way.

    The breakeven stop, once 1R has printed, applies on later bars. The bar
    that prints 1R keeps the original stop, because that bar can also trade
    through the stop and the file does not say which happened first.
    """
    if exit_index <= entry_index:
        return None
    entry_open = float(bars[entry_index]["open"])
    if stop >= entry_open:
        return None
    active_stop = stop
    armed_after: int | None = None
    reason = "time"
    hit_index = exit_index
    for index in range(entry_index, exit_index + 1):
        bar = bars[index]
        is_exit = index == exit_index
        if is_exit and exit_kind == "sell":
            reason = "time"
            hit_index = index
            break
        if float(bar["low"]) <= active_stop:
            reason = "stop"
            hit_index = index
            break
        if target is not None and float(bar["high"]) >= target:
            reason = "target"
            hit_index = index
            break
        if breakeven_after is not None and armed_after is None and float(bar["high"]) >= breakeven_after:
            armed_after = index
            active_stop = entry_open
        if is_exit:
            reason = "flat" if exit_kind == "flat" or int(bar["minute"]) >= FLAT_MINUTE else "time"
            hit_index = index
            break
    if reason == "stop" and armed_after is not None and hit_index > armed_after:
        path_start = armed_after + 1
        used_stop = entry_open
        used_target = None
        kind = "flat"
    elif reason == "target":
        path_start = entry_index if armed_after is None or hit_index <= armed_after else armed_after + 1
        used_stop = stop if path_start == entry_index else entry_open
        used_target = target
        kind = "flat"
    elif reason == "stop":
        path_start = entry_index
        used_stop = stop
        used_target = None
        kind = "flat"
    else:
        path_start = entry_index if armed_after is None else armed_after + 1
        used_stop = stop if path_start == entry_index else entry_open
        used_target = None
        kind = exit_kind if hit_index == exit_index else "flat"
    if path_start > hit_index:
        return None
    exit_bar = bars[hit_index]
    exit_t = int(exit_bar.get("t") or 0)
    if kind == "flat" and exit_t:
        exit_t += 300
    planned: dict[str, Any] = {
        "stop": float(used_stop),
        "entry_bar": bars[entry_index],
        "exit_bar": exit_bar,
        "path": bars[path_start:hit_index],
        "exit_kind": kind,
        "exit_t": exit_t,
        "planned_reason": reason,
    }
    if used_target is not None:
        planned["target"] = float(used_target)
    return planned


def _vote(name: str, *, score: float = 0.0, veto: bool = False, size_scale: float = 1.0, reason: str) -> TierVote:
    return TierVote(name, score, veto, size_scale, reason)


def vote_premarket() -> TierVote:
    return _vote("premarket", reason="no premarket bars in the regular-hours files; abstain")


def vote_tape() -> TierVote:
    return _vote("tape", reason="no prints; volume_rate is the 5-minute proxy; abstain")


def vote_time(start: int, kind: str) -> TierVote:
    if kind == "orb":
        allowed = start in MORNING_STARTS
        return _vote("time_of_day", score=1.0 if allowed else 0.0, veto=not allowed, reason="morning opening-range window" if allowed else "outside the morning window")
    if kind == "vwap":
        allowed = start in AFTERNOON_STARTS
        return _vote("time_of_day", score=1.0 if allowed else 0.0, veto=not allowed, reason="afternoon pullback window" if allowed else "outside the afternoon window")
    allowed = start in MORNING_STARTS
    return _vote("time_of_day", score=1.0 if allowed else 0.0, veto=not allowed, reason="morning window" if allowed else "outside the morning window")


def vote_opening_range(close: float, or_high: float, or_low: float) -> TierVote:
    broke = close > or_high
    span = (or_high - or_low) / close if close else 0.0
    return _vote(
        "opening_range",
        score=1.0 if broke else 0.0,
        veto=not broke,
        reason=f"close {close:.4f} vs range high {or_high:.4f}; span {span:.4f}",
    )


def vote_vwap(close: float, vwap: float | None, *, reclaim: bool = False) -> TierVote:
    if vwap is None or vwap <= 0:
        return _vote("vwap", veto=True, reason="vwap unavailable")
    above = close > vwap
    if reclaim:
        return _vote("vwap", score=1.0 if above else 0.0, veto=not above, reason="reclaim" if above else "still under vwap")
    return _vote("vwap", score=1.0 if above else 0.0, veto=not above, reason="above session vwap" if above else "under session vwap")


def vote_volume(
    hist: SymbolHist,
    start: int,
    or_volume: float,
    slot_volume: float,
    previous_volume: float | None,
    bucket_up: bool,
) -> TierVote:
    or_median = hist.median(hist.or_volumes)
    slot_median = hist.median(hist.slot_volumes.get(start, []))
    if or_median is None or slot_median is None or or_median <= 0 or slot_median <= 0:
        return _vote("volume_rate", veto=True, reason="fewer than 20 prior sessions for this slot")
    or_rvol = or_volume / or_median
    slot_rvol = slot_volume / slot_median
    fading = previous_volume is not None and start != MORNING_STARTS[0] and slot_volume < previous_volume
    veto = or_rvol < RVOL_IN_PLAY or slot_rvol < RVOL_SLOT or fading or not bucket_up
    score = 1.0 if or_rvol >= 1.5 and not veto else 0.0
    return _vote(
        "volume_rate",
        score=score,
        veto=veto,
        reason=f"or rvol {or_rvol:.2f}; slot rvol {slot_rvol:.2f}; bucket up {bucket_up}; fading {fading}",
    )


def vote_relative_strength(symbol_return: float | None, spy_return: float | None) -> TierVote:
    if symbol_return is None or spy_return is None:
        return _vote("relative_strength", veto=True, reason="return from the open unavailable")
    stronger = symbol_return > spy_return
    return _vote("relative_strength", score=1.0 if stronger else 0.0, veto=not stronger, reason=f"name {symbol_return:.4f}; spy {spy_return:.4f}")


def vote_internals(spy_return: float | None, qqq_return: float | None, breadth: int) -> TierVote:
    if spy_return is None:
        return _vote("internals", veto=True, reason="spy session unavailable")
    smash = spy_return <= INDEX_SMASH or (qqq_return is not None and qqq_return <= INDEX_SMASH)
    thin = spy_return < 0 and breadth < BREADTH_MIN
    veto = smash or thin
    return _vote("internals", score=0.0 if veto else 1.0, veto=veto, reason=f"spy {spy_return:.4f}; qqq {qqq_return}; breadth {breadth}")


def vote_gap(gap: float | None, gap_median: float | None) -> TierVote:
    if gap is None:
        return _vote("gap", veto=True, reason="gap unavailable")
    flag = gap_median is not None and gap_median > 0 and abs(gap) > GAP_FLAG_MULTIPLE * gap_median
    veto = gap < GAP_VETO
    reason = f"gap {gap:.4f}"
    if flag:
        reason += "; possible catalyst, size unchanged"
    return _vote("gap", score=0.0, veto=veto, reason=reason)


def vote_prior(close: float, or_high: float, or_low: float, prior_high: float | None) -> TierVote:
    span = or_high - or_low
    extension = (close - or_high) / span if span > 0 else 0.0
    through_high = prior_high is not None and close > prior_high
    veto = extension > MAX_EXTENSION
    return _vote(
        "prior_levels",
        score=1.0 if through_high and not veto else 0.0,
        veto=veto,
        reason=f"extension {extension:.2f}; through prior high {through_high}",
    )


def vote_events(day: date, entry_minute: int, spy_hist: SymbolHist | None, *, kind: str) -> TierVote:
    scale = 1.0
    reasons = []
    veto = False
    if day in CPI_DAYS or is_nfp(day):
        reasons.append("cpi or employment-situation morning")
        if kind == "orb" or kind == "short":
            veto = True
        elif entry_minute < 10 * 60 + 30:
            veto = True
        else:
            scale = min(scale, EVENT_SCALE)
    if day in FOMC_STATEMENT_DAYS and entry_minute >= 13 * 60 + 30:
        reasons.append("fomc statement window")
        veto = True
    if day == third_friday(day):
        reasons.append("monthly opex")
        scale = min(scale, OPEX_SCALE)
    if is_month_end(day):
        reasons.append("month-end, size unchanged")
    if spy_hist is not None and len(spy_hist.daily_returns) >= HISTORY_DAYS:
        window = spy_hist.daily_returns[-HISTORY_DAYS:]
        mean = sum(window) / len(window)
        variance = sum((value - mean) ** 2 for value in window) / (len(window) - 1)
        std = variance**0.5
        if std > 0 and abs(window[-1]) > 2.0 * std:
            reasons.append("spy shock, half size")
            scale = min(scale, SHOCK_SCALE)
    if not reasons:
        reasons.append("ordinary session")
    return _vote("events", score=0.0 if veto else 1.0, veto=veto, size_scale=scale, reason="; ".join(reasons))


def vote_trend(hist: SymbolHist) -> TierVote:
    average = hist.sma()
    if average is None or not hist.closes:
        return _vote("trend", veto=True, reason="fewer than 20 prior closes")
    last = hist.closes[-1]
    above = last > average
    return _vote("trend", score=1.0 if above else 0.0, veto=not above, reason=f"prior close {last:.4f}; 20-day average {average:.4f}")


def vote_risk(close: float, or_high: float, or_low: float, entry_open: float | None) -> TierVote:
    if close <= 0 or or_high <= or_low:
        return _vote("risk", veto=True, reason="range empty")
    span = (or_high - or_low) / close
    if span < MIN_STOP or span > MAX_STOP:
        return _vote("risk", veto=True, reason=f"range {span:.4f} outside 12 bp to 2.5%")
    if entry_open is None or entry_open <= or_low:
        return _vote("risk", veto=True, reason="entry missing or through the range low")
    distance = (entry_open - or_low) / entry_open
    if distance < MIN_STOP or distance > MAX_STOP:
        return _vote("risk", veto=True, reason=f"stop distance {distance:.4f} outside 12 bp to 2.5%")
    return _vote("risk", score=1.0, reason=f"stop distance {distance:.4f}")


def _breadth(prepared: dict[str, DayView], minute: int) -> int:
    count = 0
    for symbol in CANDIDATES:
        view = prepared.get(symbol)
        if view is None:
            continue
        change = from_open(view, minute)
        if change is not None and change > 0:
            count += 1
    return count


def _gap(hist: SymbolHist, day: DayView) -> tuple[float | None, float | None]:
    opened = day.by_minute.get(OPEN_MINUTE)
    if opened is None or not hist.closes or hist.closes[-1] <= 0:
        return None, hist.median(hist.abs_gaps, GAP_HISTORY) if len(hist.abs_gaps) >= HISTORY_DAYS else None
    gap = float(opened["open"]) / hist.closes[-1] - 1.0
    median = hist.median(hist.abs_gaps, GAP_HISTORY) if len(hist.abs_gaps) >= HISTORY_DAYS else None
    return gap, median


def _priority(votes: dict[str, TierVote]) -> float:
    score = votes["prior_levels"].score + votes["volume_rate"].score
    return float(score)


def _fraction(entry_open: float, stop: float, scale: float) -> float:
    distance = entry_open - stop
    if distance <= 0 or entry_open <= 0:
        return 0.0
    raw = min(MAX_NOTIONAL, RISK_FRACTION * entry_open / distance)
    return raw * scale


def _long_spells(
    *,
    symbol: str,
    day: date,
    view: DayView,
    entry_index: int,
    exit_index: int,
    exit_kind: str,
    stop: float,
    fraction: float,
    priority: float,
) -> list[dict[str, Any]]:
    entry_open = float(view.ordered[entry_index]["open"])
    distance = entry_open - stop
    if distance <= 0 or fraction <= 0:
        return []
    one_r = entry_open + distance
    two_r = entry_open + 2.0 * distance
    half = fraction / 2.0
    specs = (
        ("scale", one_r, None, half),
        ("runner", two_r, one_r, half),
    )
    spells = []
    for role, target, breakeven, piece in specs:
        planned = plan_exit(
            view.ordered,
            entry_index,
            exit_index,
            stop,
            target,
            exit_kind,
            breakeven_after=breakeven,
        )
        if planned is None:
            continue
        planned.update(
            {
                "symbol": symbol,
                "day": day,
                "buy_minute": int(view.ordered[entry_index]["minute"]),
                "entry_t": int(view.ordered[entry_index].get("t") or 0),
                "score": priority,
                "priority": priority,
                "invest_fraction": piece,
                "role": role,
                "side": "long",
            }
        )
        spells.append(planned)
    return spells


def _emit_long(
    spec: BookSpec,
    symbol: str,
    day: date,
    view: DayView,
    start: int,
    stop: float,
    votes: dict[str, TierVote],
    disabled: frozenset[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    blockers = [name for name, vote in votes.items() if vote.veto and name not in disabled]
    if blockers:
        return [], blockers
    signal = signal_minute(start)
    entry_minute = signal + 5
    entry_index = _index_at(view, entry_minute)
    if entry_index is None:
        return [], ["risk"]
    if spec.kind == "vwap":
        target_minute = entry_minute + 60
    else:
        target_minute = LUNCH_EXIT_MINUTE
    located = _exit_index(view, entry_index, target_minute)
    if located is None:
        return [], ["risk"]
    exit_index, exit_kind = located
    scale = 1.0
    for name, vote in votes.items():
        if name in disabled:
            continue
        scale = min(scale, vote.size_scale)
    entry_open = float(view.ordered[entry_index]["open"])
    fraction = _fraction(entry_open, stop, scale)
    spells = _long_spells(
        symbol=symbol,
        day=day,
        view=view,
        entry_index=entry_index,
        exit_index=exit_index,
        exit_kind=exit_kind,
        stop=stop,
        fraction=fraction,
        priority=_priority(votes),
    )
    if not spells:
        return [], ["risk"]
    return spells, []


def _orb_candidate(
    spec: BookSpec,
    symbol: str,
    day: date,
    view: DayView,
    hist: SymbolHist,
    spy_view: DayView | None,
    qqq_view: DayView | None,
    spy_hist: SymbolHist | None,
    breadth_at: dict[int, int],
) -> tuple[list[dict[str, Any]], list[str], bool]:
    opening = slot_bars(view, OR_START)
    if opening is None:
        return [], [], False
    or_high = max(float(bar["high"]) for bar in opening)
    or_low = min(float(bar["low"]) for bar in opening)
    or_volume = sum(float(bar["volume"]) for bar in opening)
    previous: list[dict[str, Any]] | None = opening
    for start in SLOT_STARTS:
        if start <= OR_START:
            continue
        bars = slot_bars(view, start)
        if bars is None:
            previous = None
            continue
        close = float(bars[-1]["close"])
        if close <= or_high:
            previous = bars
            continue
        signal = signal_minute(start)
        entry_minute = signal + 5
        entry_bar = view.by_minute.get(entry_minute)
        entry_open = float(entry_bar["open"]) if entry_bar is not None else None
        gap, gap_median = _gap(hist, view)
        slot_volume = sum(float(bar["volume"]) for bar in bars)
        previous_volume = sum(float(bar["volume"]) for bar in previous) if previous is not None else None
        bucket_up = close > float(bars[0]["open"])
        spy_return = from_open(spy_view, signal) if spy_view is not None else None
        qqq_return = from_open(qqq_view, signal) if qqq_view is not None else None
        votes = {
            "opening_range": vote_opening_range(close, or_high, or_low),
            "time_of_day": vote_time(start, "orb"),
            "vwap": vote_vwap(close, vwap_through(view, signal)),
            "volume_rate": vote_volume(hist, start, or_volume, slot_volume, previous_volume, bucket_up),
            "relative_strength": vote_relative_strength(from_open(view, signal), spy_return),
            "internals": vote_internals(spy_return, qqq_return, breadth_at.get(signal, 0)),
            "gap": vote_gap(gap, gap_median),
            "prior_levels": vote_prior(close, or_high, or_low, hist.highs[-1] if hist.highs else None),
            "events": vote_events(day, entry_minute, spy_hist, kind="orb"),
            "trend": vote_trend(hist),
            "risk": vote_risk(close, or_high, or_low, entry_open),
            "premarket": vote_premarket(),
            "tape": vote_tape(),
        }
        spells, blockers = _emit_long(spec, symbol, day, view, start, or_low, votes, spec.disabled)
        return spells, blockers, True
    return [], [], False


def _vwap_candidate(
    spec: BookSpec,
    symbol: str,
    day: date,
    view: DayView,
    hist: SymbolHist,
    spy_view: DayView | None,
    qqq_view: DayView | None,
    spy_hist: SymbolHist | None,
    breadth_at: dict[int, int],
) -> tuple[list[dict[str, Any]], list[str], bool]:
    saw_dip = False
    previous_close_under = False
    for start in SLOT_STARTS:
        bars = slot_bars(view, start)
        if bars is None:
            continue
        signal = signal_minute(start)
        vwap = vwap_through(view, signal)
        close = float(bars[-1]["close"])
        if vwap is not None and close < vwap:
            saw_dip = True
        if start not in AFTERNOON_STARTS or not saw_dip or not previous_close_under:
            previous_close_under = vwap is not None and close <= vwap
            continue
        if vwap is None or close <= vwap:
            previous_close_under = True
            continue
        entry_minute = signal + 5
        entry_bar = view.by_minute.get(entry_minute)
        entry_open = float(entry_bar["open"]) if entry_bar is not None else None
        bucket_low = min(float(bar["low"]) for bar in bars)
        spy_return = from_open(spy_view, signal) if spy_view is not None else None
        qqq_return = from_open(qqq_view, signal) if qqq_view is not None else None
        votes = {
            "opening_range": _vote("opening_range", score=0.0, reason="not used on the vwap book"),
            "time_of_day": vote_time(start, "vwap"),
            "vwap": vote_vwap(close, vwap, reclaim=True),
            "volume_rate": _vote("volume_rate", score=0.0, reason="not required on the vwap reclaim"),
            "relative_strength": vote_relative_strength(from_open(view, signal), spy_return),
            "internals": vote_internals(spy_return, qqq_return, breadth_at.get(signal, 0)),
            "gap": _vote("gap", reason="not required on the vwap reclaim"),
            "prior_levels": _vote("prior_levels", reason="not required on the vwap reclaim"),
            "events": vote_events(day, entry_minute, spy_hist, kind="vwap"),
            "trend": vote_trend(hist),
            "risk": vote_risk(close, close, bucket_low, entry_open) if entry_open else _vote("risk", veto=True, reason="entry missing"),
            "premarket": vote_premarket(),
            "tape": vote_tape(),
        }
        # Risk for a reclaim uses the bucket low as the stop. vote_risk treats
        # or_high/or_low as the range. Pass the close and the bucket low.
        spells, blockers = _emit_long(spec, symbol, day, view, start, bucket_low, votes, spec.disabled)
        return spells, blockers, True
    return [], [], False


def _short_candidate(
    symbol: str,
    day: date,
    view: DayView,
    hist: SymbolHist,
    spy_hist: SymbolHist | None,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    opening = slot_bars(view, OR_START)
    if opening is None:
        return [], [], False
    or_high = max(float(bar["high"]) for bar in opening)
    or_volume = sum(float(bar["volume"]) for bar in opening)
    or_median = hist.median(hist.or_volumes)
    if or_median is None or or_volume < RVOL_IN_PLAY * or_median:
        return [], [], False
    broke = False
    break_high = or_high
    for start in MORNING_STARTS:
        bars = slot_bars(view, start)
        if bars is None:
            continue
        close = float(bars[-1]["close"])
        bucket_high = max(float(bar["high"]) for bar in bars)
        if not broke:
            if close > or_high:
                broke = True
                break_high = bucket_high
            continue
        if close >= or_high or close >= float(bars[0]["open"]):
            continue
        if day in CPI_DAYS or is_nfp(day):
            return [], ["events"], True
        signal = signal_minute(start)
        entry_minute = signal + 5
        entry_index = _index_at(view, entry_minute)
        if entry_index is None:
            return [], ["risk"], True
        located = _exit_index(view, entry_index, LUNCH_EXIT_MINUTE)
        if located is None:
            return [], ["risk"], True
        exit_index, exit_kind = located
        entry_open = float(view.ordered[entry_index]["open"])
        stop = max(break_high, entry_open)
        distance = stop - entry_open
        if distance <= 0 or distance / entry_open < MIN_STOP or distance / entry_open > MAX_STOP:
            return [], ["risk"], True
        target = entry_open - distance
        planned = _plan_short(view.ordered, entry_index, exit_index, stop, target, exit_kind)
        if planned is None:
            return [], ["risk"], True
        scale = vote_events(day, entry_minute, spy_hist, kind="short").size_scale
        fraction = min(MAX_NOTIONAL, RISK_FRACTION * entry_open / distance) * scale
        planned.update(
            {
                "symbol": symbol,
                "day": day,
                "buy_minute": entry_minute,
                "entry_t": int(view.ordered[entry_index].get("t") or 0),
                "score": 0.0,
                "priority": 0.0,
                "invest_fraction": fraction,
                "role": "short",
                "side": "short",
                "stop_price": stop,
                "target_price": target,
            }
        )
        return [planned], [], True
    return [], [], False


def _plan_short(
    bars: list[dict[str, Any]],
    entry_index: int,
    exit_index: int,
    stop: float,
    target: float,
    exit_kind: str,
) -> dict[str, Any] | None:
    """Short path. Stop is above the entry. Stop wins if the same bar hits both."""
    if exit_index <= entry_index:
        return None
    entry_open = float(bars[entry_index]["open"])
    if stop <= entry_open:
        return None
    reason = "time"
    hit_index = exit_index
    for index in range(entry_index, exit_index + 1):
        bar = bars[index]
        is_exit = index == exit_index
        if is_exit and exit_kind == "sell":
            reason = "time"
            hit_index = index
            break
        if float(bar["high"]) >= stop:
            reason = "stop"
            hit_index = index
            break
        if float(bar["low"]) <= target:
            reason = "target"
            hit_index = index
            break
        if is_exit:
            reason = "flat" if exit_kind == "flat" else "time"
            hit_index = index
            break
    kind = "sell" if reason == "time" and exit_kind == "sell" else "flat"
    exit_bar = bars[hit_index]
    exit_t = int(exit_bar.get("t") or 0)
    if kind == "flat" and exit_t:
        exit_t += 300
    return {
        "stop": stop,
        "target": target,
        "entry_bar": bars[entry_index],
        "exit_bar": exit_bar,
        "path": bars[entry_index:hit_index],
        "exit_kind": kind,
        "exit_t": exit_t,
        "planned_reason": reason,
    }


def resolve_short(spell: dict[str, Any], slip_bps: float = SLIP_BPS) -> tuple[float, float, str] | None:
    entry = apply_slip(float(spell["entry_bar"]["open"]), "sell", slip_bps)
    stop = float(spell["stop"])
    target = spell.get("target")
    held = list(spell["path"]) + [spell["exit_bar"]]
    for index, bar in enumerate(held):
        is_exit = index == len(held) - 1
        cover_at_open = is_exit and spell["exit_kind"] == "sell"
        if not cover_at_open and float(bar["high"]) >= stop:
            raw = float(bar["open"]) if float(bar["open"]) > stop else stop
            return entry, apply_slip(raw, "buy", slip_bps), "stop"
        if target is not None and not cover_at_open and float(bar["low"]) <= float(target):
            raw = float(bar["open"]) if float(bar["open"]) < float(target) else float(target)
            return entry, apply_slip(raw, "buy", slip_bps), "target"
        if is_exit:
            if spell["exit_kind"] == "flat" or int(bar["minute"]) >= FLAT_MINUTE:
                return entry, apply_slip(float(bar["close"]), "buy", slip_bps), "flat"
            return entry, apply_slip(float(bar["open"]), "buy", slip_bps), "sell"
    return None


def simulate_shorts(
    spells: list[dict[str, Any]],
    *,
    equity: float = ACCOUNT_USD,
    slip_bps: float = SLIP_BPS,
) -> dict[str, Any]:
    """Research column. The cash account cannot place these.

    Notional is locked at the entry and released at the cover, so overlapping
    names cannot spend the same dollars twice.
    """
    planned: list[tuple[dict[str, Any], float, float, str]] = []
    for spell in spells:
        resolved = resolve_short(spell, slip_bps)
        if resolved is None:
            continue
        entry, cover, reason = resolved
        planned.append((spell, entry, cover, reason))
    events: list[tuple[int, int, int]] = []
    for index, (spell, _entry, _cover, _reason) in enumerate(planned):
        events.append((int(spell["entry_t"]), 1, index))
        events.append((int(spell["exit_t"]), 0, index))
    events.sort()
    cash = float(equity)
    open_notional = 0.0
    peak = float(equity)
    max_dd = 0.0
    taken: list[dict[str, Any]] = []
    pending: dict[int, dict[str, Any]] = {}
    day_start: dict[date, float] = {}
    day_realized: dict[date, float] = {}
    for _when, kind, index in events:
        if kind == 0:
            trade = pending.pop(index, None)
            if trade is None:
                continue
            cash += trade["notional"] + float(trade["net"])
            open_notional -= trade["notional"]
            day_realized[trade["day"]] = day_realized.get(trade["day"], 0.0) + float(trade["net"])
            mark = cash + open_notional
            peak = max(peak, mark)
            max_dd = max(max_dd, peak - mark)
            continue
        spell, entry, cover, reason = planned[index]
        day = spell["day"]
        if day not in day_start:
            day_start[day] = cash + open_notional
        if day_realized.get(day, 0.0) <= -DAILY_LOSS * day_start[day] + 1e-9:
            continue
        fraction = float(spell.get("invest_fraction") or 0.0)
        equity_now = cash + open_notional
        if fraction <= 0 or entry <= 0 or equity_now <= 0:
            continue
        shares = int((equity_now * fraction) // entry)
        if shares < 1 or shares * entry > cash + 1e-9:
            continue
        notional = entry * shares
        gross = (entry - cover) * shares
        cash -= notional
        open_notional += notional
        trade = {
            "symbol": spell["symbol"],
            "day": day,
            "entry_t": spell["entry_t"],
            "entry": entry,
            "exit": cover,
            "shares": shares,
            "reason": reason,
            "net": gross,
            "ret": gross / notional if notional else 0.0,
            "notional": notional,
            "side": "short",
            "role": "short",
        }
        pending[index] = trade
        taken.append(trade)
        mark = cash + open_notional
        peak = max(peak, mark)
        max_dd = max(max_dd, peak - mark)
    for trade in pending.values():
        cash += trade["notional"] + float(trade["net"])
    return {"trades": taken, "final": cash, "net": cash - equity, "maxDrawdown": max_dd}


def _update_history(hist: SymbolHist, day: DayView) -> None:
    flat = day.by_minute.get(FLAT_MINUTE)
    opened = day.by_minute.get(OPEN_MINUTE)
    if flat is None or opened is None:
        return
    close = float(flat["close"])
    high = max(float(bar["high"]) for bar in day.ordered)
    if hist.closes:
        previous = hist.closes[-1]
        if previous > 0:
            hist.daily_returns.append(close / previous - 1.0)
        hist.abs_gaps.append(abs(float(opened["open"]) / previous - 1.0) if previous > 0 else 0.0)
    hist.closes.append(close)
    hist.highs.append(high)
    opening = slot_bars(day, OR_START)
    if opening is not None:
        hist.or_volumes.append(sum(float(bar["volume"]) for bar in opening))
    for start in SLOT_STARTS:
        bars = slot_bars(day, start)
        if bars is None:
            continue
        hist.slot_volumes.setdefault(start, []).append(sum(float(bar["volume"]) for bar in bars))


@dataclass
class GridResult:
    spells: dict[str, list[dict[str, Any]]]
    vetoes: dict[str, Counter[str]]
    candidates: dict[str, int]
    evaluations: int
    sessions: list[date]


def run_grid(
    book: dict[tuple[str, date], list[dict[str, Any]]],
    specs: tuple[BookSpec, ...] = BOOKS,
    *,
    allow_holdout: bool = False,
) -> GridResult:
    assert_no_holdout(book, allow_holdout=allow_holdout)
    names = list(dict.fromkeys([*CANDIDATES, *CONTEXT]))
    history = {symbol: SymbolHist() for symbol in names}
    spells: dict[str, list[dict[str, Any]]] = {spec.name: [] for spec in specs}
    vetoes: dict[str, Counter[str]] = {spec.name: Counter() for spec in specs}
    candidates = {spec.name: 0 for spec in specs}
    evaluations = 0
    sessions: list[date] = []
    days = sorted({day for (_symbol, day) in book})
    for day in days:
        prepared: dict[str, DayView] = {}
        for symbol in names:
            bars = book.get((symbol, day))
            if not bars:
                continue
            view = prepare_day(bars)
            if view is not None:
                prepared[symbol] = view
        in_window = VALIDATE_START <= day <= VALIDATE_END
        if in_window and "SPY" in prepared:
            sessions.append(day)
        breadth_at = {}
        if in_window:
            for start in SLOT_STARTS:
                breadth_at[signal_minute(start)] = _breadth(prepared, signal_minute(start))
            for symbol in CANDIDATES:
                if symbol in prepared:
                    evaluations += len(SLOT_STARTS)
        spy_view = prepared.get("SPY")
        qqq_view = prepared.get("QQQ")
        for spec in specs:
            if not in_window:
                continue
            for symbol in CANDIDATES:
                view = prepared.get(symbol)
                if view is None:
                    continue
                if spec.kind == "orb":
                    emitted, blockers, candidate = _orb_candidate(
                        spec, symbol, day, view, history[symbol], spy_view, qqq_view, history.get("SPY"), breadth_at
                    )
                elif spec.kind == "vwap":
                    emitted, blockers, candidate = _vwap_candidate(
                        spec, symbol, day, view, history[symbol], spy_view, qqq_view, history.get("SPY"), breadth_at
                    )
                else:
                    emitted, blockers, candidate = _short_candidate(symbol, day, view, history[symbol], history.get("SPY"))
                if candidate:
                    candidates[spec.name] += 1
                if blockers:
                    vetoes[spec.name].update(blockers)
                spells[spec.name].extend(emitted)
        for symbol, view in prepared.items():
            _update_history(history[symbol], view)
    return GridResult(spells, vetoes, candidates, evaluations, sessions)


def drop_top_days(trades: list[dict[str, Any]], count: int = 5) -> tuple[float, list[dict[str, Any]]]:
    by_day: dict[date, float] = {}
    for trade in trades:
        by_day[trade["day"]] = by_day.get(trade["day"], 0.0) + float(trade["net"])
    ranked = sorted(by_day, key=lambda item: (by_day[item], str(item)), reverse=True)
    dropped = ranked[:count]
    dropped_rows = [{"day": item.isoformat(), "net": by_day[item]} for item in dropped]
    keep = {item for item in by_day if item not in set(dropped)}
    kept = [trade for trade in trades if trade["day"] in keep]
    return sum(float(trade["net"]) for trade in kept), dropped_rows
