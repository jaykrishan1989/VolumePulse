"""Pre-registered hypotheses. Thresholds are fixed; do not retune them after a run.

Each generator sees only days before the locked holdout. A new idea is a
function that returns spells for ``portfolio`` in ``backtest.spells``, plus a
``Hypothesis`` row in ``REGISTRY``. The runner refuses holdout dates.

Nothing here places an order.
"""

from __future__ import annotations

from collections import deque
from datetime import date
from typing import Any, Callable

from backtest.data import CANDIDATES
from backtest.periods import FLAT_MINUTE, HOLDOUT_START

OPEN_MINUTE = 9 * 60 + 30
# 9:55 bar closes at 10:00. 15:30 is the start of the last half hour.
SIGNAL_1000 = 9 * 60 + 55
ENTRY_1530 = 15 * 60 + 30
ENTRY_1000 = 10 * 60
EXIT_1100 = 11 * 60
ENTRY_0945 = 9 * 60 + 45
VWAP_FROM = 10 * 60 + 30
# First 15 minutes: 9:30, 9:35, 9:40. The range is complete at 9:45.
RANGE_END = 9 * 60 + 45

# Frozen before the first run. Not a search grid.
OPENING_DROP = -0.005
VWAP_ATR = 0.6
GAP_DOWN = -0.004
ATR_BARS = 14


def assert_preholdout(day: date) -> None:
    if day >= HOLDOUT_START:
        raise RuntimeError(f"holdout day {day} leaked into a hypothesis")


def _rth(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [bar for bar in bars if OPEN_MINUTE <= int(bar["minute"]) <= FLAT_MINUTE]


def _flat_index(bars: list[dict[str, Any]]) -> int | None:
    last = None
    for index, bar in enumerate(bars):
        if int(bar["minute"]) <= FLAT_MINUTE:
            last = index
    return last


def walk_symbol(
    book: dict[tuple[str, date], list[dict[str, Any]]], symbol: str
):
    """Yield one regular session at a time, with ATR carried across days."""
    window: deque[float] = deque(maxlen=ATR_BARS)
    prev_close: float | None = None
    days = sorted(day for (sym, day) in book if sym == symbol)
    for day in days:
        assert_preholdout(day)
        bars = _rth(book[(symbol, day)])
        if not bars:
            continue
        day_prev = prev_close
        minutes: dict[int, int] = {}
        atrs: list[float | None] = []
        vwaps: list[float | None] = []
        pv = 0.0
        vol = 0.0
        for index, bar in enumerate(bars):
            minutes[int(bar["minute"])] = index
            if prev_close is None:
                tr = float(bar["high"]) - float(bar["low"])
            else:
                tr = max(
                    float(bar["high"]) - float(bar["low"]),
                    abs(float(bar["high"]) - prev_close),
                    abs(float(bar["low"]) - prev_close),
                )
            window.append(tr)
            prev_close = float(bar["close"])
            atrs.append(sum(window) / ATR_BARS if len(window) == ATR_BARS else None)
            typical = (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3.0
            volume = float(bar.get("volume") or 0.0)
            vol += volume
            pv += typical * volume
            vwaps.append(pv / vol if vol > 0 else None)
        yield day, bars, minutes, atrs, vwaps, day_prev


def make_spell(
    *,
    symbol: str,
    day: date,
    bars: list[dict[str, Any]],
    entry_i: int,
    exit_i: int,
    stop: float,
    priority: float,
    exit_kind: str,
) -> dict[str, Any] | None:
    if exit_i <= entry_i or entry_i < 0 or exit_i >= len(bars):
        return None
    entry = bars[entry_i]
    exit_bar = bars[exit_i]
    if int(entry["minute"]) >= FLAT_MINUTE:
        return None
    if int(exit_bar["minute"]) > FLAT_MINUTE:
        return None
    if float(stop) >= float(entry["open"]):
        return None
    exit_t = int(exit_bar.get("t") or 0)
    if exit_kind == "flat" and exit_t:
        exit_t += 300
    return {
        "symbol": symbol,
        "day": day,
        "buy_minute": int(entry["minute"]),
        "entry_t": int(entry.get("t") or 0),
        "exit_t": exit_t,
        "stop": float(stop),
        "score": float(priority),
        "priority": float(priority),
        "entry_bar": entry,
        "exit_bar": exit_bar,
        "path": bars[entry_i:exit_i],
        "exit_kind": exit_kind,
    }


def _scheduled(bars: list[dict[str, Any]], exit_i: int) -> tuple[int, str] | None:
    """Use a flat exit when the scheduled bar would be after 15:50."""
    flat_i = _flat_index(bars)
    if flat_i is None:
        return None
    if exit_i >= len(bars) or int(bars[exit_i]["minute"]) > FLAT_MINUTE:
        return flat_i, "flat"
    return exit_i, "sell"


def half_hour_momentum(
    book: dict[tuple[str, date], list[dict[str, Any]]], symbols: list[str]
) -> list[dict[str, Any]]:
    """First half-hour return from the prior close predicts a long into the close."""
    spells: list[dict[str, Any]] = []
    for symbol in symbols:
        for day, bars, minutes, atrs, _vwaps, prev_close in walk_symbol(book, symbol):
            sig = minutes.get(SIGNAL_1000)
            entry_i = minutes.get(ENTRY_1530)
            exit_i = minutes.get(FLAT_MINUTE)
            if sig is None or entry_i is None or exit_i is None or prev_close is None or prev_close <= 0:
                continue
            if entry_i <= sig or exit_i <= entry_i:
                continue
            ret = float(bars[sig]["close"]) / prev_close - 1.0
            atr = atrs[sig]
            if ret <= 0 or atr is None or atr <= 0:
                continue
            stop = float(bars[entry_i]["open"]) - atr
            spell = make_spell(
                symbol=symbol,
                day=day,
                bars=bars,
                entry_i=entry_i,
                exit_i=exit_i,
                stop=stop,
                priority=ret * 100.0,
                exit_kind="flat",
            )
            if spell is not None:
                spells.append(spell)
    return spells


def opening_reversal(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """A down first half-hour is bought for the next hour."""
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        for day, bars, minutes, atrs, _vwaps, _prev in walk_symbol(book, symbol):
            sig = minutes.get(SIGNAL_1000)
            open_i = minutes.get(OPEN_MINUTE)
            entry_i = minutes.get(ENTRY_1000)
            exit_i = minutes.get(EXIT_1100)
            if None in (sig, open_i, entry_i, exit_i):
                continue
            assert sig is not None and open_i is not None and entry_i is not None and exit_i is not None
            if not (open_i < sig < entry_i < exit_i):
                continue
            base = float(bars[open_i]["open"])
            if base <= 0:
                continue
            ret = float(bars[sig]["close"]) / base - 1.0
            atr = atrs[sig]
            if ret > OPENING_DROP or atr is None or atr <= 0:
                continue
            stop = float(bars[entry_i]["open"]) - atr
            spell = make_spell(
                symbol=symbol,
                day=day,
                bars=bars,
                entry_i=entry_i,
                exit_i=exit_i,
                stop=stop,
                priority=-ret * 100.0,
                exit_kind="sell",
            )
            if spell is not None:
                spells.append(spell)
    return spells


def vwap_shortfall(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Buy the first bar that finishes at least 0.6 ATR below session VWAP."""
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        for day, bars, _minutes, atrs, vwaps, _prev in walk_symbol(book, symbol):
            signal_i = None
            for index, bar in enumerate(bars):
                minute = int(bar["minute"])
                if minute < VWAP_FROM or minute >= 15 * 60:
                    continue
                atr = atrs[index]
                vwap = vwaps[index]
                if atr is None or atr <= 0 or vwap is None:
                    continue
                if float(bar["close"]) <= vwap - VWAP_ATR * atr:
                    signal_i = index
                    break
            if signal_i is None:
                continue
            entry_i = signal_i + 1
            if entry_i >= len(bars) or int(bars[entry_i]["minute"]) >= FLAT_MINUTE:
                continue
            atr = atrs[signal_i]
            vwap = vwaps[signal_i]
            if atr is None or atr <= 0 or vwap is None:
                continue
            exit_i = None
            last_held = min(entry_i + 11, len(bars) - 1)
            for index in range(entry_i, last_held + 1):
                if int(bars[index]["minute"]) >= FLAT_MINUTE:
                    break
                level = vwaps[index]
                if level is not None and float(bars[index]["close"]) >= level:
                    exit_i = index + 1
                    break
            if exit_i is None:
                exit_i = entry_i + 12
            scheduled = _scheduled(bars, exit_i)
            if scheduled is None:
                continue
            exit_at, kind = scheduled
            if exit_at <= entry_i:
                continue
            stop = float(bars[entry_i]["open"]) - atr
            priority = (vwap - float(bars[signal_i]["close"])) / atr
            spell = make_spell(
                symbol=symbol,
                day=day,
                bars=bars,
                entry_i=entry_i,
                exit_i=exit_at,
                stop=stop,
                priority=priority,
                exit_kind=kind,
            )
            if spell is not None:
                spells.append(spell)
    return spells


def opening_range_breakout(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Buy the first close through the first 15-minute high. Stop is the range low."""
    spells: list[dict[str, Any]] = []
    needed = {OPEN_MINUTE, OPEN_MINUTE + 5, OPEN_MINUTE + 10}
    for symbol in CANDIDATES:
        for day, bars, minutes, atrs, _vwaps, _prev in walk_symbol(book, symbol):
            if not needed <= set(minutes):
                continue
            range_bars = [bars[minutes[minute]] for minute in sorted(needed)]
            or_high = max(float(bar["high"]) for bar in range_bars)
            or_low = min(float(bar["low"]) for bar in range_bars)
            signal_i = None
            for index, bar in enumerate(bars):
                if int(bar["minute"]) < RANGE_END or int(bar["minute"]) >= FLAT_MINUTE:
                    continue
                if float(bar["close"]) > or_high:
                    signal_i = index
                    break
            if signal_i is None or signal_i + 1 >= len(bars):
                continue
            entry_i = signal_i + 1
            flat_i = _flat_index(bars)
            if flat_i is None or flat_i <= entry_i:
                continue
            atr = atrs[signal_i]
            priority = 0.0 if atr is None or atr <= 0 else (float(bars[signal_i]["close"]) - or_high) / atr
            spell = make_spell(
                symbol=symbol,
                day=day,
                bars=bars,
                entry_i=entry_i,
                exit_i=flat_i,
                stop=or_low,
                priority=priority,
                exit_kind="flat",
            )
            if spell is not None:
                spells.append(spell)
    return spells


def overnight_gap_intraday(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Buy a down open and hold the cash session. The overnight winner is not bought."""
    spells: list[dict[str, Any]] = []
    for symbol in CANDIDATES:
        for day, bars, minutes, atrs, _vwaps, prev_close in walk_symbol(book, symbol):
            open_i = minutes.get(OPEN_MINUTE)
            entry_i = minutes.get(ENTRY_0945)
            exit_i = minutes.get(FLAT_MINUTE)
            if None in (open_i, entry_i, exit_i) or prev_close is None or prev_close <= 0:
                continue
            assert open_i is not None and entry_i is not None and exit_i is not None
            if not (open_i < entry_i < exit_i):
                continue
            gap = float(bars[open_i]["open"]) / prev_close - 1.0
            # ATR is known from the prior session once 14 bars have printed; use the entry bar's carried ATR.
            atr = atrs[entry_i]
            if gap > GAP_DOWN or atr is None or atr <= 0:
                continue
            stop = float(bars[entry_i]["open"]) - atr
            spell = make_spell(
                symbol=symbol,
                day=day,
                bars=bars,
                entry_i=entry_i,
                exit_i=exit_i,
                stop=stop,
                priority=-gap * 100.0,
                exit_kind="flat",
            )
            if spell is not None:
                spells.append(spell)
    return spells


class Hypothesis:
    def __init__(
        self,
        id: str,
        source: str,
        hypothesis: str,
        rationale: str,
        setup: str,
        generate: Callable[[dict[tuple[str, date], list[dict[str, Any]]]], list[dict[str, Any]]],
        symbols: list[str],
    ) -> None:
        self.id = id
        self.source = source
        self.hypothesis = hypothesis
        self.rationale = rationale
        self.setup = setup
        self.generate = generate
        self.symbols = symbols

    def spells(self, book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
        return self.generate(book)


REGISTRY: list[Hypothesis] = [
    Hypothesis(
        id="h1_spy",
        source=(
            "Gao, L., Han, Y., Li, S. Z., and Zhou, G. (2018). Market intraday momentum. "
            "Journal of Financial Economics, 129(2), 394–414. "
            "https://doi.org/10.1016/j.jfineco.2018.05.009"
        ),
        hypothesis=(
            "SPY's return from the prior cash close to 10:00 ET predicts a positive last-half-hour "
            "return. Buy SPY at the 15:30 open when that return is positive, and sell the close of the 15:50 bar."
        ),
        rationale=(
            "Gao, Han, Li, and Zhou find this on SPY itself and tie it to two paying counterparties: "
            "late-informed traders who wait for the open to confirm overnight news, and institutions that "
            "rebalance near the close (Bogousslavsky's infrequent-rebalancing channel, as they cite it). "
            "The other side of the 15:30 buy is a dealer selling into that demand and charging for inventory "
            "into the cash close. This account can hold that inventory only until 15:55, so the test keeps "
            "the paper's direction and gives up the last five minutes, including the closing auction."
        ),
        setup=(
            "Instrument: SPY only, the paper's market. Signal: 9:55-bar close divided by the prior regular-session "
            "close, minus one, must be strictly positive. Entry: 15:30 open. Exit: 15:50 close (15:55). "
            "Protective stop: one 14-bar ATR under the entry open, ATR carried from prior bars. "
            "No other threshold. With-stop tiered fills are the decision; no-stop and fixed commissions are reported."
        ),
        generate=lambda book: half_hour_momentum(book, ["SPY"]),
        symbols=["SPY"],
    ),
    Hypothesis(
        id="h1_stocks",
        source=(
            "Gao, L., Han, Y., Li, S. Z., and Zhou, G. (2018). Market intraday momentum. "
            "Journal of Financial Economics, 129(2), 394–414. The published evidence is ETFs; "
            "this row asks whether the same clock-time pattern appears in the eight-stock book."
        ),
        hypothesis=(
            "Each stock's own return from the prior close to 10:00 predicts its last half hour. "
            "Buy at 15:30 when that return is positive and sell the 15:50 close."
        ),
        rationale=(
            "If late-day demand is index rebalancing, the pattern should be strongest in the ETF and weaker, "
            "noisier, or absent in single names after a $0.35 commission. Testing the eight names separately "
            "from SPY keeps a failure on the stocks from being read as a failure of the paper's own asset."
        ),
        setup=(
            "Same clock and stop as h1_spy, applied independently to AAPL, AMD, AMZN, GOOGL, META, MSFT, NVDA, and TSLA. "
            "When several names trigger at 15:30, the larger morning return is funded first."
        ),
        generate=lambda book: half_hour_momentum(book, list(CANDIDATES)),
        symbols=list(CANDIDATES),
    ),
    Hypothesis(
        id="h2_opening_reversal",
        source=(
            "Heston, S. L., Korajczyk, R. A., and Sadka, R. (2010). Intraday patterns in the cross-section "
            "of stock returns. Journal of Finance, 65(4), 1369–1407. "
            "https://doi.org/10.1111/j.1540-6261.2010.01573.x"
        ),
        hypothesis=(
            "A stock that falls at least 0.50% from the 9:30 open to the 10:00 close bounces over the next hour. "
            "Buy the 10:00 open and sell the 11:00 open."
        ),
        rationale=(
            "Heston, Korajczyk, and Sadka show that short-horizon reversal is a liquidity imbalance that dies "
            "inside an hour, with part of the quote-level effect coming from bid-ask bounce. The paying side is "
            "the trader who sells into the open and demands immediacy; the bid that takes that flow should earn "
            "the imbalance back as the book refills. On five-minute bars the bounce is already averaged, so the "
            "remaining edge has to clear 2 bp of slippage and the $0.35 minimum. A loss after costs is the "
            "result the spread argument predicts, and it is still the right test of the direction."
        ),
        setup=(
            "Own-stock return from the 9:30 open to the 9:55 close, threshold −0.50% fixed in advance. "
            "Entry 10:00 open, exit 11:00 open, stop one ATR under the entry. One trade a day. "
            "The deeper drop is funded first."
        ),
        generate=opening_reversal,
        symbols=list(CANDIDATES),
    ),
    Hypothesis(
        id="h3_vwap_shortfall",
        source=(
            "Berkowitz, S. A., Logue, D. E., and Noser, E. A. (1988). The total cost of transactions on the NYSE. "
            "Journal of Finance, 43(1), 97–112. Almgren, R., and Chriss, N. (2001). Optimal execution of "
            "portfolio transactions. Journal of Risk, 3(2), 5–39."
        ),
        hypothesis=(
            "The first time after 10:30 that price closes at least 0.6 ATR below session VWAP, buy the next open "
            "and sell the next open after price closes back at VWAP, or after 60 minutes, whichever comes first."
        ),
        rationale=(
            "VWAP is the benchmark execution desks are measured against (Berkowitz, Logue, and Noser). "
            "A schedule that is behind a falling price can wait; a schedule that can buy below VWAP beats the "
            "benchmark by lifting the offer there, so latent buy interest sits under VWAP (the participation "
            "trade-off in Almgren and Chriss). The other side is a seller who needs immediacy and walks price "
            "through that bid. This long is on the side of the benchmarked buyer. The distance 0.6 ATR is a "
            "single pre-set gate so the test is not a search over how far is far enough."
        ),
        setup=(
            "Session VWAP from 9:30 using typical price times volume. First signal at or after 10:30 and before 15:00. "
            "Entry is the next bar's open. Exit is the open after the first later close back at or above VWAP, "
            "else 12 bars later, else the 15:50 close. Stop is one ATR under the entry, ATR as of the signal bar. "
            "One spell a day. Larger shortfall is funded first."
        ),
        generate=vwap_shortfall,
        symbols=list(CANDIDATES),
    ),
    Hypothesis(
        id="h4_opening_range",
        source=(
            "Holmberg, U., Lönnbark, C., and Lundström, C. (2013). Assessing the profitability of intraday "
            "opening range breakout strategies. Finance Research Letters, 10(1), 27–33. "
            "https://doi.org/10.1016/j.frl.2012.09.001. "
            "Practitioner source: Crabel, T. (1990). Day Trading With Short Term Price Patterns and Opening "
            "Range Breakout. Traders Press."
        ),
        hypothesis=(
            "A close above the high of the first 15 minutes continues to the cash close. "
            "Buy the next open and sell the 15:50 close. The protective stop is the opening-range low."
        ),
        rationale=(
            "The opening range is where overnight information meets the book. A break is the informed flow "
            "that could not finish inside that range; the other side is liquidity posted at the range high. "
            "Holmberg, Lönnbark, and Lundström found a positive ORB result on crude oil, and later work from "
            "the same line ties the profits to high-volatility stretches rather than a steady edge. "
            "On mega-cap stocks the range high is a crowded stop-in, so false breaks pay the breakout buyer. "
            "The test uses one range length, 15 minutes, and does not search it."
        ),
        setup=(
            "Range is the high and low of the 9:30, 9:35, and 9:40 bars, complete at 9:45. "
            "First later close above that high, entry on the next open, exit on the 15:50 close. "
            "Stop at the range low. One trade a day. A larger break, scaled by ATR, is funded first."
        ),
        generate=opening_range_breakout,
        symbols=list(CANDIDATES),
    ),
    Hypothesis(
        id="h5_gap_down",
        source=(
            "Lou, D., Polk, C., and Skouras, S. (2019). A tug of war: Overnight versus intraday expected returns. "
            "Journal of Financial Economics, 134(1), 192–213. https://doi.org/10.1016/j.jfineco.2019.03.011"
        ),
        hypothesis=(
            "A stock that opens at least 0.40% below the prior cash close has a positive intraday return. "
            "Buy the 9:45 open and sell the 15:50 close. An up gap is not bought."
        ),
        rationale=(
            "Lou, Polk, and Skouras decompose returns into an overnight clientele and an intraday clientele that "
            "pull in opposite directions: firm-level continuation inside each piece, and a cross-period reversal "
            "between them. Momentum profits in their sample accrue overnight, which this account cannot earn "
            "because it is flat by 15:55. The piece a day-trader can hold is the intraday reversal of the overnight "
            "move. The other side of a down-gap buy is the overnight seller whose flow is being offset by the "
            "intraday clientele. Buying up gaps would be the overnight-momentum trade held at the wrong time of day."
        ),
        setup=(
            "Gap is the 9:30 open over the prior regular-session close, threshold −0.40% fixed in advance. "
            "Entry waits until the 9:45 open so the first 15 minutes are not a fill. Exit is the 15:50 close. "
            "Stop is one ATR under that entry. The larger down gap is funded first."
        ),
        generate=overnight_gap_intraday,
        symbols=list(CANDIDATES),
    ),
]
