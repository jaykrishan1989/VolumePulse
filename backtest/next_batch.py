"""Four pre-registered books. Thresholds are fixed. This is not a search.

The profit objective is validation net dollars after 2 bp of slippage.
Nothing here is added to the promotion-gate registries, so the Bonferroni
denominator stays 54 until one of these ids is submitted as a challenger.
Nothing here places an order. Generators use ``walk_symbol``, which refuses
a holdout day unless a caller has already opted in. This module does not.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any, Callable

from backtest.data import CANDIDATES
from backtest.hypotheses import (
    FLAT_MINUTE,
    OPEN_MINUTE,
    RANGE_END,
    make_spell,
    walk_symbol,
)

# 9:55 bar closes at 10:00. 10:00 is the next open after that print.
CLOCK_END = 9 * 60 + 55
ENTRY_1000 = 10 * 60
ENTRY_0930 = OPEN_MINUTE
# 14:55 bar closes at 15:00. The last-half-hour fill is that 15:00 open.
LATE_SIGNAL = 14 * 60 + 55
LATE_ENTRY = 15 * 60
VOL_LOOKBACK = 20

# Published validation net of ml:flat:flat:1atr:top1:1:20. A new holdout look
# is a milestone only when a frozen id beats this on validation dollars.
PUBLISHED_MODEL_VALIDATION_NET = 1260.736236000008
MIN_TRADES = 50


def _flat_close(bars: list[dict[str, Any]], minutes: dict[int, int]) -> float | None:
    index = minutes.get(FLAT_MINUTE)
    if index is None:
        return None
    close = float(bars[index]["close"])
    return close if close > 0 else None


def _first(spells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First entry time of the day, then the strongest name at that time.

    A later, larger signal is ignored. That later bar is not known at the fill.
    """
    ordered = sorted(
        spells,
        key=lambda spell: (spell["day"], int(spell["entry_t"]), -float(spell["priority"]), str(spell["symbol"])),
    )
    taken: list[dict[str, Any]] = []
    index = 0
    while index < len(ordered):
        day = ordered[index]["day"]
        when = int(ordered[index]["entry_t"])
        cohort: list[dict[str, Any]] = []
        while index < len(ordered) and ordered[index]["day"] == day and int(ordered[index]["entry_t"]) == when:
            cohort.append(ordered[index])
            index += 1
        taken.append(max(cohort, key=lambda spell: (float(spell["priority"]), str(spell["symbol"]))))
        while index < len(ordered) and ordered[index]["day"] == day:
            index += 1
    return taken


def clock_continuation(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Heston, Korajczyk, and Sadka (2010): yesterday's same half-hour leads today.

    The signal is yesterday's 9:30 open to 9:55 close. Today's fill is the 9:30
    open. The exit is the 10:00 open, so the hold is that same half-hour.
    """
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        prior_clock: float | None = None
        prior_atr: float | None = None
        for day, bars, minutes, atrs, _vwaps, _prev in walk_symbol(book, symbol):
            open_i = minutes.get(ENTRY_0930)
            sig_i = minutes.get(CLOCK_END)
            exit_i = minutes.get(ENTRY_1000)
            if (
                prior_clock is not None
                and prior_clock > 0
                and prior_atr is not None
                and prior_atr > 0
                and open_i is not None
                and exit_i is not None
                and open_i < exit_i
            ):
                entry_open = float(bars[open_i]["open"])
                spell = make_spell(
                    symbol=symbol,
                    day=day,
                    bars=bars,
                    entry_i=open_i,
                    exit_i=exit_i,
                    stop=entry_open - prior_atr,
                    priority=prior_clock * 100.0,
                    exit_kind="sell",
                )
                if spell is not None:
                    spells.append(spell)
            if open_i is not None and sig_i is not None and float(bars[open_i]["open"]) > 0:
                prior_clock = float(bars[sig_i]["close"]) / float(bars[open_i]["open"]) - 1.0
            else:
                prior_clock = None
            flat_i = minutes.get(FLAT_MINUTE)
            prior_atr = atrs[flat_i] if flat_i is not None else None
    return _first(spells)


def opening_range_failure(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """A break under the first 15 minutes that trades back inside is the long.

    Crabel's opening-range breakout was already tested in the other direction.
    This is the failed breakdown: a seller who ran the range low and did not
    get followed. Entry is the next open after the reclaim close.
    """
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        for day, bars, minutes, atrs, _vwaps, _prev in walk_symbol(book, symbol):
            range_ix = [minutes.get(OPEN_MINUTE), minutes.get(OPEN_MINUTE + 5), minutes.get(OPEN_MINUTE + 10)]
            if any(index is None for index in range_ix):
                continue
            indexes = [int(index) for index in range_ix if index is not None]
            range_low = min(float(bars[index]["low"]) for index in indexes)
            range_high = max(float(bars[index]["high"]) for index in indexes)
            broke = False
            break_low: float | None = None
            signal_i: int | None = None
            for index, bar in enumerate(bars):
                if int(bar["minute"]) < RANGE_END:
                    continue
                close = float(bar["close"])
                low = float(bar["low"])
                if not broke:
                    if close < range_low:
                        broke = True
                        break_low = low
                    continue
                assert break_low is not None
                break_low = min(break_low, low)
                if range_low <= close <= range_high:
                    signal_i = index
                    break
            if signal_i is None or break_low is None or signal_i + 1 >= len(bars):
                continue
            entry_i = signal_i + 1
            flat_i = minutes.get(FLAT_MINUTE)
            if flat_i is None or entry_i > flat_i:
                continue
            atr = atrs[signal_i]
            entry_open = float(bars[entry_i]["open"])
            stop = break_low
            if atr is not None and entry_open - atr < stop:
                stop = entry_open - atr
            if stop >= entry_open:
                continue
            depth = range_low - break_low
            spell = make_spell(
                symbol=symbol,
                day=day,
                bars=bars,
                entry_i=entry_i,
                exit_i=flat_i,
                stop=stop,
                priority=depth,
                exit_kind="flat",
            )
            if spell is not None:
                spells.append(spell)
    return _first(spells)


def prior_day_reversal(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Jegadeesh (1990) and Lehmann (1990): buy yesterday's worst close-to-close loser.

    The signal is known at yesterday's 15:55 close, so the fill is today's 9:30
    open. A down open is a different number; the gap rule already trades that.
    """
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        yesterday_close: float | None = None
        older_close: float | None = None
        prior_atr: float | None = None
        for day, bars, minutes, atrs, _vwaps, _prev in walk_symbol(book, symbol):
            open_i = minutes.get(ENTRY_0930)
            flat_i = minutes.get(FLAT_MINUTE)
            if (
                yesterday_close is not None
                and older_close is not None
                and older_close > 0
                and prior_atr is not None
                and prior_atr > 0
                and open_i is not None
                and flat_i is not None
                and open_i < flat_i
            ):
                yret = yesterday_close / older_close - 1.0
                if yret < 0:
                    entry_open = float(bars[open_i]["open"])
                    spell = make_spell(
                        symbol=symbol,
                        day=day,
                        bars=bars,
                        entry_i=open_i,
                        exit_i=flat_i,
                        stop=entry_open - prior_atr,
                        priority=-yret * 100.0,
                        exit_kind="flat",
                    )
                    if spell is not None:
                        spells.append(spell)
            flat_close = _flat_close(bars, minutes)
            older_close = yesterday_close
            yesterday_close = flat_close
            if flat_i is not None:
                prior_atr = atrs[flat_i]
    return _first(spells)


def wap_pressure(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """First-half-hour buyer pressure, using the bar WAP already stored as ``average``.

    Chordia, Roll, and Subrahmanyam (2002) find order imbalance persists and
    moves price. A close above the bar WAP is the buyer-initiated proxy these
    files can support. There is no bid or ask. Days without ``average`` are skipped.
    """
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        for day, bars, minutes, atrs, _vwaps, _prev in walk_symbol(book, symbol):
            num = 0.0
            den = 0.0
            usable = True
            for bar in bars:
                if int(bar["minute"]) > CLOCK_END:
                    break
                average = bar.get("average")
                volume = float(bar.get("volume") or 0.0)
                if average is None or volume <= 0:
                    usable = False
                    break
                num += (float(bar["close"]) - float(average)) * volume
                den += volume
            if not usable or den <= 0:
                continue
            pressure = num / den
            if pressure <= 0:
                continue
            sig_i = minutes.get(CLOCK_END)
            entry_i = minutes.get(ENTRY_1000)
            flat_i = minutes.get(FLAT_MINUTE)
            if None in (sig_i, entry_i, flat_i):
                continue
            assert sig_i is not None and entry_i is not None and flat_i is not None
            if not (sig_i < entry_i < flat_i):
                continue
            atr = atrs[sig_i]
            if atr is None or atr <= 0:
                continue
            entry_open = float(bars[entry_i]["open"])
            spell = make_spell(
                symbol=symbol,
                day=day,
                bars=bars,
                entry_i=entry_i,
                exit_i=flat_i,
                stop=entry_open - atr,
                priority=pressure,
                exit_kind="flat",
            )
            if spell is not None:
                spells.append(spell)
    return _first(spells)


def _day_volume(bars: list[dict[str, Any]]) -> float:
    return sum(float(bar.get("volume") or 0.0) for bar in bars)


def volume_reversal(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Campbell, Grossman, and Wang (1993): a high-volume down day reverses next session.

    Yesterday's volume is compared with the median of the 20 sessions before it.
    The fill is today's 9:30 open. Today's volume is not in the signal.
    """
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        closes: list[float] = []
        volumes: list[float] = []
        prior_atr: float | None = None
        for day, bars, minutes, atrs, _vwaps, _prev in walk_symbol(book, symbol):
            open_i = minutes.get(ENTRY_0930)
            flat_i = minutes.get(FLAT_MINUTE)
            if (
                len(volumes) >= VOL_LOOKBACK + 1
                and len(closes) >= 2
                and closes[-2] > 0
                and prior_atr is not None
                and prior_atr > 0
                and open_i is not None
                and flat_i is not None
                and open_i < flat_i
            ):
                yret = closes[-1] / closes[-2] - 1.0
                baseline = volumes[-(VOL_LOOKBACK + 1) : -1]
                if yret < 0 and volumes[-1] > statistics.median(baseline):
                    entry_open = float(bars[open_i]["open"])
                    spell = make_spell(
                        symbol=symbol,
                        day=day,
                        bars=bars,
                        entry_i=open_i,
                        exit_i=flat_i,
                        stop=entry_open - prior_atr,
                        priority=-yret * 100.0,
                        exit_kind="flat",
                    )
                    if spell is not None:
                        spells.append(spell)
            close = _flat_close(bars, minutes)
            if close is not None:
                closes.append(close)
                volumes.append(_day_volume(bars))
            if flat_i is not None:
                prior_atr = atrs[flat_i]
    return _first(spells)


def _spy_session_return(book: dict[tuple[str, date], list[dict[str, Any]]]) -> dict[date, float]:
    """Close-to-close SPY return that finished on each session. Known after that close."""
    done: dict[date, float] = {}
    prev: float | None = None
    for day, bars, minutes, _atrs, _vwaps, _prev in walk_symbol(book, "SPY"):
        close = _flat_close(bars, minutes)
        if prev is not None and close is not None and prev > 0:
            done[day] = close / prev - 1.0
        if close is not None:
            prev = close
    return done


def residual_reversal(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Lo and MacKinlay (1990): fade the name that lagged SPY yesterday, not the market itself.

    A stock that fell only because SPY fell has a residual near zero and is not bought.
    """
    spy = _spy_session_return(book)
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        prev_close: float | None = None
        older_close: float | None = None
        prev_day: date | None = None
        prior_atr: float | None = None
        for day, bars, minutes, atrs, _vwaps, _prev in walk_symbol(book, symbol):
            open_i = minutes.get(ENTRY_0930)
            flat_i = minutes.get(FLAT_MINUTE)
            spy_ret = spy.get(prev_day) if prev_day is not None else None
            if (
                prev_close is not None
                and older_close is not None
                and older_close > 0
                and spy_ret is not None
                and prior_atr is not None
                and prior_atr > 0
                and open_i is not None
                and flat_i is not None
                and open_i < flat_i
            ):
                residual = prev_close / older_close - 1.0 - spy_ret
                if residual < 0:
                    entry_open = float(bars[open_i]["open"])
                    spell = make_spell(
                        symbol=symbol,
                        day=day,
                        bars=bars,
                        entry_i=open_i,
                        exit_i=flat_i,
                        stop=entry_open - prior_atr,
                        priority=-residual * 100.0,
                        exit_kind="flat",
                    )
                    if spell is not None:
                        spells.append(spell)
            flat_close = _flat_close(bars, minutes)
            older_close = prev_close
            prev_close = flat_close
            prev_day = day if flat_close is not None else None
            if flat_i is not None:
                prior_atr = atrs[flat_i]
    return _first(spells)


def late_reversal(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The other side of Gao, Han, Li, and Zhou (2018): fade the day's worst offer into the close.

    The signal is the 9:30 open to the 14:55 close. The fill is the 15:00 open.
    The last half hour is the hold. h1 buys continuation of a positive morning; this does not.
    """
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        for day, bars, minutes, atrs, _vwaps, _prev in walk_symbol(book, symbol):
            open_i = minutes.get(ENTRY_0930)
            sig_i = minutes.get(LATE_SIGNAL)
            entry_i = minutes.get(LATE_ENTRY)
            flat_i = minutes.get(FLAT_MINUTE)
            if None in (open_i, sig_i, entry_i, flat_i):
                continue
            assert open_i is not None and sig_i is not None and entry_i is not None and flat_i is not None
            if not (open_i < sig_i < entry_i <= flat_i):
                continue
            opened = float(bars[open_i]["open"])
            if opened <= 0:
                continue
            ret = float(bars[sig_i]["close"]) / opened - 1.0
            atr = atrs[sig_i]
            if ret >= 0 or atr is None or atr <= 0:
                continue
            entry_open = float(bars[entry_i]["open"])
            spell = make_spell(
                symbol=symbol,
                day=day,
                bars=bars,
                entry_i=entry_i,
                exit_i=flat_i,
                stop=entry_open - atr,
                priority=-ret * 100.0,
                exit_kind="flat",
            )
            if spell is not None:
                spells.append(spell)
    return _first(spells)


class Idea:
    def __init__(
        self,
        id: str,
        source: str,
        hypothesis: str,
        rationale: str,
        setup: str,
        generate: Callable[[dict[tuple[str, date], list[dict[str, Any]]]], list[dict[str, Any]]],
    ) -> None:
        self.id = id
        self.source = source
        self.hypothesis = hypothesis
        self.rationale = rationale
        self.setup = setup
        self.generate = generate

    def spells(self, book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
        return self.generate(book)


NEXT_REGISTRY: list[Idea] = [
    Idea(
        id="n_clock",
        source=(
            "Heston, S. L., Korajczyk, R. A., and Sadka, R. (2010). Intraday patterns in the "
            "cross-section of stock returns. Journal of Finance, 65(4), 1369–1407."
        ),
        hypothesis=(
            "The name with the strongest 9:30–10:00 return yesterday has a positive 9:30–10:00 "
            "return today, often enough to pay 2 bp of slippage on one US$2,120 ticket."
        ),
        rationale=(
            "The paper's continuation is a daily lag at the same clock, which they tie to "
            "institutions that trade the same part of the day. The other side is a liquidity "
            "provider who fades that habit. Eight names is a thin cross-section for their result. "
            "That limit is part of the test, not a reason to skip it."
        ),
        setup=(
            "Signal: yesterday's 9:55 close over yesterday's 9:30 open, strictly positive. "
            "One name, the largest of those returns. Entry: today's 9:30 open. Exit: today's 10:00 open. "
            "Stop: one prior-day ATR under the entry. No other threshold."
        ),
        generate=clock_continuation,
    ),
    Idea(
        id="n_orb_fail",
        source=(
            "Crabel, T. (1990). Day Trading With Short Term Price Patterns and Opening Range Breakout. "
            "The breakout direction was already rejected here as h4_opening_range and d_orb. "
            "This row is the failed-breakdown long."
        ),
        hypothesis=(
            "A close back inside the first-15-minute range, after a close below that range, "
            "rebounds to the 15:55 flat often enough to pay the ticket."
        ),
        rationale=(
            "A break under the opening range runs stops. If the print returns inside the range, "
            "that selling was not followed. The long provides liquidity to the stop run. "
            "The continuation breakout is a different trade and stays rejected."
        ),
        setup=(
            "Range: high and low of the 9:30, 9:35, and 9:40 bars. First later close below the low, "
            "then the first later close back inside the range. Entry is the next open. "
            "Stop is the lower of the breakdown low and one ATR under the entry. Exit is the 15:50 close. "
            "One name, the earliest signal, and the deeper break if two names reclaim together."
        ),
        generate=opening_range_failure,
    ),
    Idea(
        id="n_prior_reversal",
        source=(
            "Jegadeesh, N. (1990). Evidence of predictable behavior of security returns. "
            "Journal of Finance, 45(3), 881–898. Lehmann, B. N. (1990). Fads, martingales, and "
            "market efficiency. Quarterly Journal of Economics, 105(1), 1–28."
        ),
        hypothesis=(
            "Yesterday's worst close-to-close loser among the eight names bounces today "
            "from the open to the 15:55 flat, after 2 bp."
        ),
        rationale=(
            "One-day and one-week losers reverse because the seller demanded immediacy. "
            "The gap rule buys a down open, which mixes overnight news with that reversal. "
            "This signal is yesterday's full cash session and is known before today's open."
        ),
        setup=(
            "Return is yesterday's 15:50 close over the prior session's 15:50 close. "
            "Trade only if that return is negative. One name, the worst return. "
            "Entry 9:30 open, exit 15:50 close, stop one prior-day ATR."
        ),
        generate=prior_day_reversal,
    ),
    Idea(
        id="n_flow",
        source=(
            "Chordia, T., Roll, R., and Subrahmanyam, A. (2002). Order imbalance, liquidity, "
            "and market returns. Journal of Finance, 57(1), 111–137."
        ),
        hypothesis=(
            "The name whose 9:30–10:00 closes sit furthest above bar WAP keeps that bid "
            "into the 15:55 flat, after 2 bp."
        ),
        rationale=(
            "Signed imbalance persists for a short horizon. These files have no quotes. "
            "A close above the bar's average price is the buyer-initiated proxy. "
            "If the imbalance is informed, the rest of the day continues. If it was inventory, "
            "the stop is the loss."
        ),
        setup=(
            "From 9:30 through the 9:55 bar, pressure is the volume-weighted (close − average). "
            "Skip a name with any missing average. One name, and only if pressure is positive. "
            "Entry 10:00 open, exit 15:50 close, stop one ATR under the entry as of the 9:55 bar."
        ),
        generate=wap_pressure,
    ),
    Idea(
        id="n_volume_reversal",
        source=(
            "Campbell, J. Y., Grossman, S. J., and Wang, J. (1993). Trading volume and serial "
            "correlation in stock returns. Journal of Finance, 48(3), 905–939."
        ),
        hypothesis=(
            "Yesterday's loser reverses today only when yesterday's volume was above its own "
            "recent median. One US$2,120 ticket, after 2 bp."
        ),
        rationale=(
            "A high-volume down day is a non-informational seller demanding immediacy. "
            "The market maker who bought that flow expects the price to come back. "
            "A quiet down day is more likely news, so the rule stands aside. "
            "The plain prior-day loser, without the volume gate, is a separate row."
        ),
        setup=(
            "Yesterday's 15:50 close over the prior 15:50 close must be negative. "
            "Yesterday's regular-hours volume must exceed the median of the 20 sessions before yesterday. "
            "One name, the worst return among those that qualify. Entry 9:30 open, exit 15:50 close, "
            "stop one prior-day ATR. No other threshold."
        ),
        generate=volume_reversal,
    ),
    Idea(
        id="n_residual",
        source=(
            "Lo, A. W., and MacKinlay, A. C. (1990). When are contrarian profits due to stock "
            "market overreaction? Review of Financial Studies, 3(2), 175–205."
        ),
        hypothesis=(
            "The name that lagged SPY yesterday, not the name that merely fell with SPY, "
            "bounces from today's open to the 15:55 flat after 2 bp."
        ),
        rationale=(
            "A large part of one-day reversal is lead-lag with the market, not each name "
            "overreacting on its own. Subtracting SPY leaves the idiosyncratic seller. "
            "The raw loser is n_prior_reversal. This row asks whether the residual is the part that pays."
        ),
        setup=(
            "Residual is the stock's close-to-close return minus SPY's close-to-close return, both "
            "finished yesterday. Trade only if the residual is negative. One name, the most negative. "
            "Entry 9:30 open, exit 15:50 close, stop one prior-day ATR."
        ),
        generate=residual_reversal,
    ),
    Idea(
        id="n_late_reversal",
        source=(
            "Gao, L., Han, Y., Li, S. Z., and Zhou, G. (2018). Market intraday momentum. "
            "Journal of Financial Economics, 129(2), 394–414. This row is the reverse of their "
            "last-half-hour continuation, which was already rejected here as h1_stocks."
        ),
        hypothesis=(
            "The name that is down the most from the open by 15:00 bounces over the last half hour "
            "often enough to pay 2 bp."
        ),
        rationale=(
            "The last half hour is when passive flows hit the close. A name already offered all day "
            "is the inventory a liquidity provider is long. h1 buys a positive morning into that window. "
            "This buys the day's worst offer instead, and only for the last half hour."
        ),
        setup=(
            "Signal: 14:55 close over the 9:30 open, strictly negative. One name, the most negative. "
            "Entry 15:00 open, exit 15:50 close, stop one ATR under the entry as of the 14:55 bar. "
            "No other threshold."
        ),
        generate=late_reversal,
    ),
]


def is_milestone(net: float, trades: int) -> bool:
    """A new holdout read requires a validation net above the published model."""
    return trades >= MIN_TRADES and net > PUBLISHED_MODEL_VALIDATION_NET
