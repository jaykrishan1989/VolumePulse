"""Three more books, frozen before any fill. This is not a search.

The previous seven books were one-name hold-to-close trades, and the dollars
sat in a few crash-rebound sessions. These three ask a different question:
can a book trade on ordinary sessions, more often than the 85-trade
hold-to-close model, without buying yesterday's loser and holding the rally.

Nothing here is added to the promotion-gate registries. The Bonferroni
denominator stays 54. Nothing here places an order. Generators use
``walk_symbol``, which refuses a holdout day.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from backtest.data import CANDIDATES
from backtest.hypotheses import FLAT_MINUTE, OPEN_MINUTE, make_spell, walk_symbol
from backtest.next_batch import ENTRY_0930, ENTRY_1000, Idea

# Noon hour, known at 13:00. The exit is the 14:00 open, a one-hour hold.
MID_OPEN = 12 * 60
MID_END = 12 * 60 + 55
MID_ENTRY = 13 * 60
MID_EXIT = 14 * 60
# Last 25 minutes that these files actually contain. The cash close is 15:55.
CLOSE_START = 15 * 60 + 30
# Two names is the long portfolio. One name was the previous lottery. Three
# mega-caps rarely fit in US$2,120. This count is not a grid.
SLOTS = 2


def _top(spells: list[dict[str, Any]], slots: int) -> list[dict[str, Any]]:
    """First entry time of the day, then the strongest ``slots`` names then.

    A later signal is ignored. Equal weight is applied to the names that qualify.
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
        cohort.sort(key=lambda spell: (-float(spell["priority"]), str(spell["symbol"])))
        chosen = cohort[:slots]
        if chosen:
            fraction = 1.0 / len(chosen)
            for spell in chosen:
                spell["invest_fraction"] = fraction
            taken.extend(chosen)
        while index < len(ordered) and ordered[index]["day"] == day:
            index += 1
    return taken


def _session_return(
    bars: list[dict[str, Any]],
    minutes: dict[int, int],
    start_minute: int,
    end_minute: int,
) -> float | None:
    """Open of the start bar to close of the end bar. Both prints are in that window."""
    start = minutes.get(start_minute)
    end = minutes.get(end_minute)
    if start is None or end is None or start > end:
        return None
    base = float(bars[start]["open"])
    if base <= 0:
        return None
    return float(bars[end]["close"]) / base - 1.0


def intraday_continuation(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Lou, Polk, and Skouras (2019): the intraday clientele continues the next session.

    h5 already bought the overnight loser and held the day. This row is the other
    leg. Yesterday's open-to-close must be positive. A down day is not bought.
    """
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        prior: float | None = None
        prior_atr: float | None = None
        for day, bars, minutes, atrs, _vwaps, _prev in walk_symbol(book, symbol):
            open_i = minutes.get(ENTRY_0930)
            flat_i = minutes.get(FLAT_MINUTE)
            if (
                prior is not None
                and prior > 0
                and prior_atr is not None
                and prior_atr > 0
                and open_i is not None
                and flat_i is not None
                and open_i < flat_i
            ):
                entry_open = float(bars[open_i]["open"])
                spell = make_spell(
                    symbol=symbol,
                    day=day,
                    bars=bars,
                    entry_i=open_i,
                    exit_i=flat_i,
                    stop=entry_open - prior_atr,
                    priority=prior * 100.0,
                    exit_kind="flat",
                )
                if spell is not None:
                    spells.append(spell)
            prior = _session_return(bars, minutes, OPEN_MINUTE, FLAT_MINUTE)
            prior_atr = atrs[flat_i] if flat_i is not None else None
    return _top(spells, SLOTS)


def midday_reversal(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Heston, Korajczyk, and Sadka (2010): the noon hour reverses over the next hour.

    h2 already faded a −0.50% open and was rejected. This row does not move that
    gate. The signal is today's 12:00 open to the 12:55 close, and the hold ends
    at 14:00, before the close.
    """
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        for day, bars, minutes, atrs, _vwaps, _prev in walk_symbol(book, symbol):
            ret = _session_return(bars, minutes, MID_OPEN, MID_END)
            entry_i = minutes.get(MID_ENTRY)
            exit_i = minutes.get(MID_EXIT)
            sig_i = minutes.get(MID_END)
            if ret is None or entry_i is None or exit_i is None or sig_i is None:
                continue
            if not (sig_i < entry_i < exit_i):
                continue
            atr = atrs[sig_i]
            if ret >= 0 or atr is None or atr <= 0:
                continue
            entry_open = float(bars[entry_i]["open"])
            spell = make_spell(
                symbol=symbol,
                day=day,
                bars=bars,
                entry_i=entry_i,
                exit_i=exit_i,
                stop=entry_open - atr,
                priority=-ret * 100.0,
                exit_kind="sell",
            )
            if spell is not None:
                spells.append(spell)
    return _top(spells, 1)


def close_reversal(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Cushing and Madhavan (2000): selling into the close comes back the next morning.

    The signal is yesterday's 15:30 open to the 15:50 close. The fill is today's
    9:30 open and the exit is the 10:00 open. The rest of the day is not the trade.
    """
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        prior: float | None = None
        prior_atr: float | None = None
        for day, bars, minutes, atrs, _vwaps, _prev in walk_symbol(book, symbol):
            open_i = minutes.get(ENTRY_0930)
            exit_i = minutes.get(ENTRY_1000)
            if (
                prior is not None
                and prior < 0
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
                    priority=-prior * 100.0,
                    exit_kind="sell",
                )
                if spell is not None:
                    spells.append(spell)
            prior = _session_return(bars, minutes, CLOSE_START, FLAT_MINUTE)
            flat_i = minutes.get(FLAT_MINUTE)
            prior_atr = atrs[flat_i] if flat_i is not None else None
    return _top(spells, 1)


NEXT2_REGISTRY: list[Idea] = [
    Idea(
        id="n_intraday_cont",
        source=(
            "Lou, D., Polk, C., and Skouras, S. (2019). A tug of war: Overnight versus "
            "intraday expected returns. Journal of Financial Economics, 134(1), 192–213. "
            "The overnight-reversal leg was already tested as h5_gap_down."
        ),
        hypothesis=(
            "Yesterday's cash-session winner has a positive open-to-close return today, "
            "often enough to pay 2 bp on up to two equal-weight US$2,120 slots."
        ),
        rationale=(
            "The paper finds continuation inside the intraday clientele, and a reversal "
            "only when the overnight piece is the signal. h5 bought the overnight loser. "
            "The loser books in the previous batch bought yesterday's crash and held the "
            "rebound. This book buys yesterday's open-to-close winner, so a name that "
            "only fell is not eligible. Two equal-weight slots are the long portfolio. "
            "A third name does not fit the account, and one name was the crash lottery."
        ),
        setup=(
            "Signal: yesterday's 15:50 close over yesterday's 9:30 open, strictly positive. "
            "Up to two names, the largest of those returns, equal weight. A single qualifier "
            "takes the whole ticket. Entry 9:30 open, exit 15:50 close, stop one prior-day ATR. "
            "No other threshold."
        ),
        generate=intraday_continuation,
    ),
    Idea(
        id="n_mid_reversal",
        source=(
            "Heston, S. L., Korajczyk, R. A., and Sadka, R. (2010). Intraday patterns in the "
            "cross-section of stock returns. Journal of Finance, 65(4), 1369–1407. "
            "The open, with a −0.50% gate, was already rejected as h2_opening_reversal."
        ),
        hypothesis=(
            "The name that fell over the noon hour bounces over the following hour, "
            "after 2 bp, without holding the position into the close."
        ),
        rationale=(
            "The same paper finds a liquidity reversal between adjacent half-hours, not "
            "only at the open. The open mixes overnight news with that reversal, and h2 "
            "already lost with a −0.50% gate. Noon is after that news has printed. "
            "The one-hour hold ends at 14:00, so a crash day's rally to the close is not "
            "this trade. There is no magnitude gate: adding one would be a search over h2."
        ),
        setup=(
            "Signal: 12:55 close over the 12:00 open, strictly negative. One name, the most "
            "negative. Entry 13:00 open, exit 14:00 open, stop one ATR under the entry as of "
            "the 12:55 bar. No other threshold."
        ),
        generate=midday_reversal,
    ),
    Idea(
        id="n_close_reversal",
        source=(
            "Cushing, D., and Madhavan, A. (2000). Stock returns and trading at the close. "
            "Journal of Financial Markets, 3(1), 45–67. The files have no closing auction, "
            "so the last 25 regular-hours minutes stand in for the close."
        ),
        hypothesis=(
            "The name that was offered from 15:30 to 15:55 yesterday bounces from today's "
            "open to 10:00, after 2 bp."
        ),
        rationale=(
            "Imbalance at the close pushes the print away from value, and that pressure "
            "comes back the next morning. n_prior_reversal used the whole prior day and "
            "held to the close, which is how a handful of rebound sessions produced the "
            "dollar total. This signal is only the last 25 minutes, and the hold is half "
            "an hour, so the rest of a rally is not collected."
        ),
        setup=(
            "Signal: yesterday's 15:50 close over yesterday's 15:30 open, strictly negative. "
            "One name, the most negative. Entry 9:30 open, exit 10:00 open, stop one prior-day ATR. "
            "No other threshold."
        ),
        generate=close_reversal,
    ),
]
