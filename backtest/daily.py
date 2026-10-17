"""Daily-frequency longs. Thresholds are frozen. Do not retune them after a run.

The live midmorning list does not fire every session. These five rules are
the pre-registered attempt to put at least one signal on a session. Two of
them always pick a name at a fixed clock. The other three wait for a setup
and will miss some days. The finalist, if any, is chosen on the validation
window only: signal coverage at least 95 percent of SPY sessions, then the
highest tiered net. The holdout is not an input to that choice.

Nothing here places an order. The tradable names are the eight stocks already
on disk. SPY is the benchmark, not a position.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from backtest.data import CANDIDATES
from backtest.hypotheses import ATR_BARS, make_spell
from backtest.periods import FLAT_MINUTE, HOLDOUT_START, VALIDATE_END, VALIDATE_START

DAILY_BEGIN = "<!-- DAILY_BEGIN -->"
DAILY_END = "<!-- DAILY_END -->"
CHANGELOG_BEGIN = "<!-- DAILY_CHANGELOG_BEGIN -->"
CHANGELOG_END = "<!-- DAILY_CHANGELOG_END -->"

OPEN_MINUTE = 9 * 60 + 30
RS_SIGNAL = 9 * 60 + 55
RS_ENTRY = 10 * 60
STRETCH_SIGNAL = 10 * 60 + 25
STRETCH_ENTRY = 10 * 60 + 30
ORB_MINUTES = (9 * 60 + 30, 9 * 60 + 35, 9 * 60 + 40)
ORB_LAST_SIGNAL = 11 * 60 + 55
PULL_START = 10 * 60
PULL_END = 11 * 60 + 30
RECLAIM_LAST = 14 * 60
DIP_ATR = 0.30
PULL_DEPTH = 0.40
IMPULSE_ATR = 0.30
# Written down before the run. A rule under this coverage is not the finalist.
FREQUENCY_MIN = 0.95

TRADABLE = list(CANDIDATES)


def assert_no_holdout(day: date) -> None:
    if day >= HOLDOUT_START:
        raise RuntimeError(f"holdout day {day} leaked into daily selection")


@dataclass
class Session:
    symbol: str
    day: date
    bars: list[dict[str, Any]]
    at: dict[int, int]
    atr: list[float | None]
    vwap: list[float | None]


def build_sessions(book: dict[tuple[str, date], list[dict[str, Any]]]) -> dict[tuple[str, date], Session]:
    """ATR carries across days. VWAP starts over each session."""
    sessions: dict[tuple[str, date], Session] = {}
    symbols = sorted({symbol for symbol, _day in book})
    for symbol in symbols:
        window: deque[float] = deque(maxlen=ATR_BARS)
        prev_close: float | None = None
        days = sorted(day for sym, day in book if sym == symbol)
        for day in days:
            raw = book[(symbol, day)]
            bars = [bar for bar in raw if OPEN_MINUTE <= int(bar["minute"]) <= FLAT_MINUTE + 5]
            if not bars:
                continue
            atrs: list[float | None] = []
            vwaps: list[float | None] = []
            at: dict[int, int] = {}
            pv = 0.0
            vol = 0.0
            for index, bar in enumerate(bars):
                at[int(bar["minute"])] = index
                if prev_close is None:
                    true_range = float(bar["high"]) - float(bar["low"])
                else:
                    true_range = max(
                        float(bar["high"]) - float(bar["low"]),
                        abs(float(bar["high"]) - prev_close),
                        abs(float(bar["low"]) - prev_close),
                    )
                window.append(true_range)
                prev_close = float(bar["close"])
                atrs.append(sum(window) / ATR_BARS if len(window) == ATR_BARS else None)
                typical = (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3.0
                volume = float(bar.get("volume") or 0.0)
                vol += volume
                pv += typical * volume
                vwaps.append(pv / vol if vol > 0 else None)
            sessions[(symbol, day)] = Session(symbol, day, bars, at, atrs, vwaps)
    return sessions


def _flat_index(bars: list[dict[str, Any]]) -> int | None:
    last = None
    for index, bar in enumerate(bars):
        if int(bar["minute"]) <= FLAT_MINUTE:
            last = index
        else:
            break
    return last


def _exit_after(bars: list[dict[str, Any]], condition_i: int) -> tuple[int, str] | None:
    """Sell the next bar's open, or flatten on the 15:50 bar if that is the condition."""
    flat_i = _flat_index(bars)
    if flat_i is None or condition_i > flat_i:
        return None
    nxt = condition_i + 1
    if nxt <= flat_i and int(bars[nxt]["minute"]) <= FLAT_MINUTE:
        return nxt, "sell"
    return flat_i, "flat"


def _time_exit(bars: list[dict[str, Any]], entry_i: int) -> tuple[int, str] | None:
    flat_i = _flat_index(bars)
    if flat_i is None or flat_i <= entry_i:
        return None
    return flat_i, "flat"


def _names_on(sessions: dict[tuple[str, date], Session], day: date) -> list[Session]:
    found = []
    for symbol in TRADABLE:
        session = sessions.get((symbol, day))
        if session is not None:
            found.append(session)
    return found


def _emit(
    session: Session,
    entry_i: int,
    exit_i: int,
    stop: float,
    priority: float,
    exit_kind: str,
) -> dict[str, Any] | None:
    return make_spell(
        symbol=session.symbol,
        day=session.day,
        bars=session.bars,
        entry_i=entry_i,
        exit_i=exit_i,
        stop=stop,
        priority=priority,
        exit_kind=exit_kind,
    )


def relative_strength(sessions: dict[tuple[str, date], Session], days: list[date]) -> list[dict[str, Any]]:
    """At 10:00, buy the stock that beat SPY by the most from the 9:30 open to the 9:55 close.

    One name. Exit is the 15:55 flat. Stop is one ATR under the entry open.
    A missing SPY bar or a missing 9:55 print skips that session.
    """
    spells: list[dict[str, Any]] = []
    for day in days:
        spy = sessions.get(("SPY", day))
        if spy is None:
            continue
        spy_open = spy.at.get(OPEN_MINUTE)
        spy_sig = spy.at.get(RS_SIGNAL)
        if spy_open is None or spy_sig is None or float(spy.bars[spy_open]["open"]) <= 0:
            continue
        spy_ret = float(spy.bars[spy_sig]["close"]) / float(spy.bars[spy_open]["open"]) - 1.0
        scored: list[tuple[float, str, Session, int, int]] = []
        for session in _names_on(sessions, day):
            open_i = session.at.get(OPEN_MINUTE)
            sig_i = session.at.get(RS_SIGNAL)
            entry_i = session.at.get(RS_ENTRY)
            if None in (open_i, sig_i, entry_i):
                continue
            assert open_i is not None and sig_i is not None and entry_i is not None
            base = float(session.bars[open_i]["open"])
            atr = session.atr[sig_i]
            if base <= 0 or atr is None or atr <= 0 or not (open_i < sig_i < entry_i):
                continue
            excess = float(session.bars[sig_i]["close"]) / base - 1.0 - spy_ret
            scored.append((excess, session.symbol, session, entry_i, sig_i))
        if not scored:
            continue
        excess, _symbol, session, entry_i, sig_i = min(scored, key=lambda item: (-item[0], item[1]))
        scheduled = _time_exit(session.bars, entry_i)
        if scheduled is None:
            continue
        exit_i, kind = scheduled
        atr = session.atr[sig_i]
        assert atr is not None
        spell = _emit(session, entry_i, exit_i, float(session.bars[entry_i]["open"]) - atr, excess, kind)
        if spell is not None:
            spells.append(spell)
    return spells


def vwap_stretch(sessions: dict[tuple[str, date], Session], days: list[date]) -> list[dict[str, Any]]:
    """At 10:30, buy the name furthest below its session VWAP, in ATRs.

    The pick is forced, so a day where every name is above VWAP still buys the
    least extended one. Exit is the next open after a close back through VWAP,
    or the 15:55 flat. Stop is one ATR under the entry.
    """
    spells: list[dict[str, Any]] = []
    for day in days:
        scored: list[tuple[float, str, Session, int, int]] = []
        for session in _names_on(sessions, day):
            sig_i = session.at.get(STRETCH_SIGNAL)
            entry_i = session.at.get(STRETCH_ENTRY)
            if sig_i is None or entry_i is None or sig_i >= entry_i:
                continue
            atr = session.atr[sig_i]
            vwap = session.vwap[sig_i]
            if atr is None or atr <= 0 or vwap is None:
                continue
            stretch = (vwap - float(session.bars[sig_i]["close"])) / atr
            scored.append((stretch, session.symbol, session, entry_i, sig_i))
        if not scored:
            continue
        stretch, _symbol, session, entry_i, sig_i = min(scored, key=lambda item: (-item[0], item[1]))
        exit_i = None
        kind = "flat"
        flat_i = _flat_index(session.bars)
        if flat_i is None:
            continue
        for index in range(entry_i + 1, flat_i + 1):
            vwap = session.vwap[index]
            if vwap is not None and float(session.bars[index]["close"]) >= vwap:
                scheduled = _exit_after(session.bars, index)
                if scheduled is None:
                    break
                exit_i, kind = scheduled
                break
        if exit_i is None:
            scheduled = _time_exit(session.bars, entry_i)
            if scheduled is None:
                continue
            exit_i, kind = scheduled
        atr = session.atr[sig_i]
        assert atr is not None
        spell = _emit(session, entry_i, exit_i, float(session.bars[entry_i]["open"]) - atr, stretch, kind)
        if spell is not None:
            spells.append(spell)
    return spells


def _range(session: Session) -> tuple[float, float] | None:
    highs = []
    lows = []
    for minute in ORB_MINUTES:
        index = session.at.get(minute)
        if index is None:
            return None
        highs.append(float(session.bars[index]["high"]))
        lows.append(float(session.bars[index]["low"]))
    return max(highs), min(lows)


def opening_range(sessions: dict[tuple[str, date], Session], days: list[date]) -> list[dict[str, Any]]:
    """First stock that closes above its first-15-minute high. One name. No break by 11:55 means no trade.

    Stop is the opening-range low. Exit is the 15:55 flat.
    """
    spells: list[dict[str, Any]] = []
    for day in days:
        names = _names_on(sessions, day)
        minutes = sorted(
            {
                minute
                for session in names
                for minute in session.at
                if ORB_MINUTES[-1] < minute <= ORB_LAST_SIGNAL
            }
        )
        for minute in minutes:
            found: list[tuple[float, str, Session, int, float]] = []
            for session in names:
                index = session.at.get(minute)
                bounds = _range(session)
                if index is None or bounds is None:
                    continue
                high, low = bounds
                close = float(session.bars[index]["close"])
                if high <= 0 or close <= high:
                    continue
                extension = (close - high) / high
                found.append((extension, session.symbol, session, index, low))
            if not found:
                continue
            extension, _symbol, session, sig_i, range_low = min(found, key=lambda item: (-item[0], item[1]))
            scheduled = _exit_after(session.bars, sig_i)
            if scheduled is None:
                break
            entry_i, _entry_kind = scheduled
            # The break is the signal. The position is still held to the flat, not sold on the next bar.
            held = _time_exit(session.bars, entry_i)
            if held is None:
                break
            exit_i, kind = held
            spell = _emit(session, entry_i, exit_i, range_low, extension, kind)
            if spell is not None:
                spells.append(spell)
            break
    return spells


def first_pullback(sessions: dict[tuple[str, date], Session], days: list[date]) -> list[dict[str, Any]]:
    """First bounce after an open drive. The session has to be at least 0.3 ATR above the open, then a bar must dip 0.4 ATR off that high and close up.

    Earliest signal wins. Stop is the pullback low. Exit is the 15:55 flat.
    No setup by 11:30 means no trade.
    """
    spells: list[dict[str, Any]] = []
    for day in days:
        names = _names_on(sessions, day)
        minutes = sorted({minute for session in names for minute in session.at if PULL_START <= minute <= PULL_END})
        chosen = None
        for minute in minutes:
            found: list[tuple[float, str, Session, int, float]] = []
            for session in names:
                index = session.at.get(minute)
                open_i = session.at.get(OPEN_MINUTE)
                if index is None or open_i is None or index <= open_i:
                    continue
                atr = session.atr[index]
                if atr is None or atr <= 0:
                    continue
                prior = session.bars[:index]
                if not prior:
                    continue
                session_high = max(float(bar["high"]) for bar in prior)
                day_open = float(session.bars[open_i]["open"])
                bar = session.bars[index]
                prev = session.bars[index - 1]
                if session_high - day_open < IMPULSE_ATR * atr:
                    continue
                if session_high - float(bar["low"]) < PULL_DEPTH * atr:
                    continue
                if float(bar["close"]) <= float(bar["open"]) or float(bar["close"]) <= float(prev["close"]):
                    continue
                depth = (session_high - float(bar["low"])) / atr
                found.append((depth, session.symbol, session, index, float(bar["low"])))
            if not found:
                continue
            chosen = min(found, key=lambda item: (-item[0], item[1]))
            break
        if chosen is None:
            continue
        _depth, _symbol, session, sig_i, pull_low = chosen
        scheduled = _exit_after(session.bars, sig_i)
        if scheduled is None:
            continue
        entry_i, _kind = scheduled
        held = _time_exit(session.bars, entry_i)
        if held is None:
            continue
        exit_i, kind = held
        spell = _emit(session, entry_i, exit_i, pull_low, _depth, kind)
        if spell is not None:
            spells.append(spell)
    return spells


def vwap_reclaim(sessions: dict[tuple[str, date], Session], days: list[date]) -> list[dict[str, Any]]:
    """Buy the first name that was at least 0.3 ATR under VWAP and then closes back above it.

    Exit is the next open after a later close back under VWAP, or the 15:55 flat.
    No reclaim by 14:00 means no trade. Stop is one ATR under the entry.
    """
    spells: list[dict[str, Any]] = []
    for day in days:
        names = _names_on(sessions, day)
        armed: dict[str, int] = {}
        minutes = sorted({minute for session in names for minute in session.at if OPEN_MINUTE <= minute <= RECLAIM_LAST})
        chosen = None
        for minute in minutes:
            found: list[tuple[float, str, Session, int]] = []
            for session in names:
                index = session.at.get(minute)
                if index is None:
                    continue
                atr = session.atr[index]
                vwap = session.vwap[index]
                if atr is None or atr <= 0 or vwap is None:
                    continue
                close = float(session.bars[index]["close"])
                if session.symbol not in armed:
                    if vwap - close >= DIP_ATR * atr:
                        armed[session.symbol] = index
                    continue
                if index <= armed[session.symbol]:
                    continue
                if close >= vwap:
                    found.append((vwap - close, session.symbol, session, index))
            if not found:
                continue
            chosen = min(found, key=lambda item: (item[0], item[1]))
            break
        if chosen is None:
            continue
        _gap, _symbol, session, sig_i = chosen
        scheduled = _exit_after(session.bars, sig_i)
        if scheduled is None:
            continue
        entry_i, _kind = scheduled
        exit_i = None
        kind = "flat"
        flat_i = _flat_index(session.bars)
        if flat_i is None:
            continue
        for index in range(entry_i + 1, flat_i + 1):
            vwap = session.vwap[index]
            if vwap is not None and float(session.bars[index]["close"]) < vwap:
                later = _exit_after(session.bars, index)
                if later is None:
                    break
                exit_i, kind = later
                break
        if exit_i is None:
            held = _time_exit(session.bars, entry_i)
            if held is None:
                continue
            exit_i, kind = held
        atr = session.atr[sig_i]
        assert atr is not None
        spell = _emit(session, entry_i, exit_i, float(session.bars[entry_i]["open"]) - atr, 1.0, kind)
        if spell is not None:
            spells.append(spell)
    return spells


RuleFn = Callable[[dict[tuple[str, date], Session], list[date]], list[dict[str, Any]]]


@dataclass(frozen=True)
class DailyRule:
    id: str
    source: str
    hypothesis: str
    rationale: str
    setup: str
    spells: RuleFn


DAILY_REGISTRY: list[DailyRule] = [
    DailyRule(
        id="d_rs_leader",
        source="Jegadeesh, Journal of Finance 1990, short-horizon reversal, is the risk on the other side. The rule still buys the morning leader. Gao, Han, Li and Zhou, Journal of Financial Economics 2018, is the index-clock cousin and was already rejected as its own trade.",
        hypothesis="The stock that beat SPY the most between 9:30 and 9:55 keeps leading into the close often enough to pay a US$2,120 ticket every session.",
        rationale="A book that waits for a rare dip is idle on quiet days. Ranking forces one long every session the open printed. The other side of a morning leader is either a momentum buyer who is late or a short-horizon reversal: Jegadeesh found the recent winner tends to give the gain back. This is that bet, taken in the continuation direction, once a day, with a hard stop and a 15:55 flat.",
        setup="Signal is the 9:55 close. Fill is the 10:00 open, 2 bp worse. Stop is one ATR under that open. Exit is the close of the 15:50 bar. One name. SPY is the benchmark and is not bought.",
        spells=relative_strength,
    ),
    DailyRule(
        id="d_vwap_stretch",
        source="Berkowitz, Logue and Noser, Journal of Finance 1988, VWAP as the benchmark. Kyle, Econometrica 1985, is why a name far under VWAP may be informed selling rather than a discount.",
        hypothesis="Buying the name furthest under its own VWAP at 10:30, every session, reverts enough after costs to beat doing nothing.",
        rationale="The stretch is the distance a seller has already pushed the print. A market maker who is long that inventory wants it back toward VWAP. If the seller is informed, the print keeps falling and the stop pays them. Forcing a trade when every name is above VWAP buys the least extended name, which is a weaker version of the same idea and is included so the book is not allowed to skip the day.",
        setup="Signal is the 10:25 close. Fill is the 10:30 open. Rank is (VWAP − close) / ATR. Exit is the next open after a later close at or above VWAP, or the 15:55 flat. Stop is one ATR.",
        spells=vwap_stretch,
    ),
    DailyRule(
        id="d_orb",
        source="Holmberg, Lönnbark and Lundström, Finance Research Letters 2013; Crabel, Day Trading with Short Term Price Patterns and Opening Range Breakout (1990). An earlier all-names opening-range rule on this same history was rejected.",
        hypothesis="Taking only the first stock that closes above its 9:30–9:40 range, instead of every break, is frequent enough and selective enough to pay the ticket.",
        rationale="The opening range is the price that absorbed the overnight inventory. A close above it is a bid that got through that inventory. The earlier test bought every such break and lost. This version buys one name, the first and the largest extension, and stands aside when nothing breaks by 11:55. Standing aside will miss days. That is reported, not patched.",
        setup="Range is the high and low of the 9:30, 9:35, and 9:40 bars. Signal is the first later close above that high, through the 11:55 bar. Fill is the next open. Stop is the range low. Exit is the 15:55 flat.",
        spells=opening_range,
    ),
    DailyRule(
        id="d_pullback",
        source="The live Right Time to Buy card is a pullback. This is the same shape with the score gate removed and a limit of one fill a day, so frequency is a property of the open rather than of a score threshold.",
        hypothesis="The first pullback after an opening drive, one name a day, pays after costs more often than waiting for the scored list.",
        rationale="The opening buyer who chased the first push is the inventory on the other side of the dip. A bounce is that inventory being taken back. If the drive was the informed order, the pullback does not bounce and the stop is the loss. The rule does not fire on a day with no drive and no dip.",
        setup="From 10:00 to 11:30, the session high before the bar has to be at least 0.3 ATR above the 9:30 open, and the bar's low at least 0.4 ATR under that high, with an up close. Fill is the next open. Stop is the pullback low. Exit is the 15:55 flat. Earliest signal wins.",
        spells=first_pullback,
    ),
    DailyRule(
        id="d_vwap_reclaim",
        source="Berkowitz, Logue and Noser (1988). A reclaim is a print that was offered under VWAP and then trades back through the benchmark.",
        hypothesis="The first VWAP reclaim of the day, after a dip of at least 0.3 ATR, is a daily long that pays the commission.",
        rationale="Under VWAP the seller has the benchmark against him. A close back through VWAP says that offer was absorbed. The failure mode is a second break, which is why the exit is the next open after a close back under VWAP. Days with no dip, or no reclaim by 14:00, produce no signal.",
        setup="Arm when a bar closes at least 0.3 ATR under session VWAP. Signal is a later close at or above VWAP, through 14:00. Fill is the next open. Stop is one ATR. Exit is the next open after a close back under VWAP, or the 15:55 flat.",
        spells=vwap_reclaim,
    ),
]


def choose_finalist(rows: list[dict[str, Any]]) -> str | None:
    """Validation coverage first, then validation net. No holdout field is read."""
    eligible = [row for row in rows if float(row["signal_day_frac"]) + 1e-12 >= FREQUENCY_MIN]
    if not eligible:
        return None
    eligible.sort(key=lambda row: (-float(row["net"]), -float(row["bps"] or 0.0), str(row["id"])))
    return str(eligible[0]["id"])


def validation_bounds() -> tuple[date, date]:
    return VALIDATE_START, VALIDATE_END
