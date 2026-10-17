"""Same-day residual and impact books. Thresholds are frozen. Do not lower them after a fill.

The last batches faded a 15-minute slot, or a slot z-score, or yesterday's
close-to-close residual. Those forwards were about 0 to 5 bp. A full
US$2,120 ticket pays about 8 bp round trip under tiered IBKR commission and
2 bp of slippage, and a quarter ticket pays about 20 bp. A book has to
select a larger dislocation than that, on a full ticket, or the commission
is the result.

Six books, one economic question each. Only ``m_primary`` may open the
holdout. The other five are a report, not a menu.

``m_primary``. Avellaneda and Lee (2010), statistical arbitrage on the
residual to a traded factor, and Gatev, Goetzmann, and Rouwenhorst (2006),
pairs trading only when the spread is wide enough to pay the round trip.
Beta is the prior 60 close-to-close sessions versus SPY, at least 40, and
it is known before the open. At 10:30, 11:30, and 13:00, buy the name whose
open-to-signal residual is the most negative, and only if that residual is
30 bp or worse. One name, the full ticket, held 60 minutes. A 100 bp stop
is the account disaster cap, not the exit. This is not ``n_residual``
(yesterday's residual, held to the flat) and it is not a slot z-score.

``m_lag``. Lo and MacKinlay (1990) and Chordia and Swaminathan (2000):
a market impulse leads the slower name. Same residual trade, and only when
SPY itself rose at least 15 bp over the prior 30 minutes. Buying the laggard
is the opposite of ``d_rs_leader``, which bought the leader. Long only, so
a down impulse is not a short of the name that has not fallen yet.

``m_impact``. Bouchaud, Gefen, Potters, and Wyart (2004) and Almgren, Thum,
Hauptmann, and Li (2005): temporary impact decays over minutes. Fade the
first 5-minute bar whose own return is −40 bp or worse. Hold 15 minutes.
That is a single-bar shock and a short decay window, not the 1.5-sigma
15-minute slot fade in ``c_move``.

``m_thrust``. The other sign of that same bar. A +40 bp bar, held 15
minutes. The pair is frozen so the sign is a result.

``m_vwap``. Hendershott and Menkveld (2014) price pressure, and Berkowitz,
Logue, and Noser (1988) on VWAP as the benchmark. Buy only when a close is
at least 30 bp under that session's VWAP. No trade when every name is above
VWAP. Sixty minutes, same disaster stop. ``h3`` used 0.6 ATR and a wider
1 ATR stop. ``d_vwap_stretch`` bought a name even when it was above VWAP.

``m_lasthour``. Gao, Han, Li, and Zhou (2018): a positive first half-hour,
from the prior close to 10:00, is bought at 15:30 and sold at the 15:55
flat. The strongest name, one full ticket. ``h1`` put a 1 ATR stop on this
clock and the stop became the exit. The 100 bp stop here is the disaster
cap. The book is not adoptable. It is off on down mornings, so it is not
the near-daily candidate.

The screen requires a positive validation, pooled, and recent net, four of
six half-years, a positive net without the five best days, at least 80
trades, a positive average basis-point result, and a fill on at least half
of validation sessions. Half of sessions is the frozen line for "most
sessions." A once-a-week book fails it. The line is not moved after the fill.

Nothing here places an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backtest.data import CANDIDATES
from backtest.grid15 import PUBLISHED_MODEL_VALIDATION_NET
from backtest.hypotheses import make_spell
from backtest.periods import FLAT_MINUTE, HOLDOUT_START, VALIDATE_END, VALIDATE_START

# Frozen before the fill. Not a search, and not the old 20 bp historical-edge hurdle.
RESIDUAL_HURDLE = -0.0030
BETA_DAYS = 60
BETA_MIN = 40
HOLD_BARS = 12
DISASTER_STOP = 0.0100
SIGNAL_MINUTES = (10 * 60 + 25, 11 * 60 + 25, 12 * 60 + 55)
SPY_IMPULSE = 0.0015
IMPULSE_LOOKBACK = 30
BAR_SHOCK = 0.0040
IMPACT_HOLD = 3
IMPACT_FROM = 10 * 60
IMPACT_TO = 14 * 60
VWAP_GAP = 0.0030
LAST_SIGNAL = 9 * 60 + 55
LAST_ENTRY = 15 * 60 + 30
OPEN_MINUTE = 9 * 60 + 30

SCREEN_MIN_TRADES = 80
SCREEN_MIN_HALVES = 4
DAY_SHARE_MIN = 0.50

ADOPTABLE = frozenset({"m_primary"})
BOOK_NAMES = ("m_primary", "m_lag", "m_impact", "m_thrust", "m_vwap", "m_lasthour")


def assert_no_holdout(day: date) -> None:
    if day >= HOLDOUT_START:
        raise RuntimeError(f"holdout day {day} leaked into session-edge selection")


def screen_failures(
    *,
    validate_net: float,
    pooled_net: float,
    recent_net: float,
    validate_trades: int,
    positive_halves: int,
    ex_top5: float,
    avg_bps: float,
    day_share: float,
) -> list[str]:
    """Frozen adoption screen. A failure list is a rejection."""
    reasons: list[str] = []
    if validate_net <= 0:
        reasons.append("validation net is not positive")
    if pooled_net <= 0:
        reasons.append("pooled net is not positive")
    if recent_net <= 0:
        reasons.append("recent net is not positive")
    if validate_trades < SCREEN_MIN_TRADES:
        reasons.append(f"fewer than {SCREEN_MIN_TRADES} validation trades")
    if positive_halves < SCREEN_MIN_HALVES:
        reasons.append(f"fewer than {SCREEN_MIN_HALVES} positive half-years")
    if ex_top5 <= 0:
        reasons.append("validation net without the five best days is not positive")
    if avg_bps <= 0:
        reasons.append("average net basis points are not positive")
    if day_share + 1e-12 < DAY_SHARE_MIN:
        reasons.append("fills are not on most sessions")
    return reasons


def clears_published_milestone(net: float, ex_top5: float, trades: int) -> bool:
    """Existing look-8 lock. Beating it is required before any holdout read."""
    return trades >= SCREEN_MIN_TRADES and net > PUBLISHED_MODEL_VALIDATION_NET and ex_top5 > 0.0


@dataclass
class DayTape:
    day: date
    bars: list[dict[str, Any]]
    at: dict[int, int]
    close: float
    prev_close: float | None


@dataclass
class EdgeResult:
    spells: dict[str, list[dict[str, Any]]]
    residual_days: list[dict[str, Any]] = field(default_factory=list)


def _rth(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [bar for bar in bars if OPEN_MINUTE <= int(bar["minute"]) <= FLAT_MINUTE + 5]


def _tapes(book: dict[tuple[str, date], list[dict[str, Any]]], symbol: str) -> list[DayTape]:
    tapes: list[DayTape] = []
    prev_close: float | None = None
    for day in sorted(day for sym, day in book if sym == symbol):
        assert_no_holdout(day)
        ordered = _rth(book[(symbol, day)])
        if not ordered:
            continue
        at = {int(bar["minute"]): index for index, bar in enumerate(ordered)}
        flat_i = None
        for index, bar in enumerate(ordered):
            if int(bar["minute"]) <= FLAT_MINUTE:
                flat_i = index
            else:
                break
        if flat_i is None:
            continue
        close = float(ordered[flat_i]["close"])
        tapes.append(DayTape(day, ordered, at, close, prev_close))
        prev_close = close
    return tapes


def _beta(pairs: list[tuple[float, float]]) -> float | None:
    window = pairs[-BETA_DAYS:]
    if len(window) < BETA_MIN:
        return None
    n = len(window)
    mean_s = sum(stock for stock, _spy in window) / n
    mean_m = sum(spy for _stock, spy in window) / n
    var_m = sum((spy - mean_m) ** 2 for _stock, spy in window)
    if var_m <= 1e-18:
        return None
    cov = sum((stock - mean_s) * (spy - mean_m) for stock, spy in window)
    return cov / var_m


def _open_to(tape: DayTape, minute: int) -> float | None:
    open_i = tape.at.get(OPEN_MINUTE)
    sig_i = tape.at.get(minute)
    if open_i is None or sig_i is None:
        return None
    base = float(tape.bars[open_i]["open"])
    if base <= 0:
        return None
    return float(tape.bars[sig_i]["close"]) / base - 1.0


def _window_return(tape: DayTape, end_minute: int, lookback: int) -> float | None:
    end_i = tape.at.get(end_minute)
    start_i = tape.at.get(end_minute - lookback)
    if end_i is None or start_i is None:
        return None
    base = float(tape.bars[start_i]["close"])
    if base <= 0:
        return None
    return float(tape.bars[end_i]["close"]) / base - 1.0


def _vwap_through(tape: DayTape, minute: int) -> float | None:
    sig_i = tape.at.get(minute)
    if sig_i is None:
        return None
    pv = 0.0
    vol = 0.0
    for bar in tape.bars[: sig_i + 1]:
        typical = (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3.0
        volume = float(bar.get("volume") or 0.0)
        vol += volume
        pv += typical * volume
    if vol <= 0:
        return None
    return pv / vol


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


def _emit(
    tape: DayTape,
    entry_i: int,
    hold_bars: int,
    priority: float,
) -> dict[str, Any] | None:
    if entry_i < 0 or entry_i >= len(tape.bars):
        return None
    if int(tape.bars[entry_i]["minute"]) >= FLAT_MINUTE:
        return None
    scheduled = _exit_at(tape.bars, entry_i, hold_bars)
    if scheduled is None:
        return None
    exit_i, kind = scheduled
    entry_open = float(tape.bars[entry_i]["open"])
    if entry_open <= 0:
        return None
    spell = make_spell(
        symbol="",
        day=tape.day,
        bars=tape.bars,
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


def _daily_returns(tapes: list[DayTape]) -> dict[date, float]:
    out: dict[date, float] = {}
    for tape in tapes:
        if tape.prev_close is None or tape.prev_close <= 0:
            continue
        out[tape.day] = tape.close / tape.prev_close - 1.0
    return out


def _first_shock(
    named: list[tuple[str, DayTape]], *, side: str
) -> dict[str, Any] | None:
    best: tuple[int, float, str, str, DayTape, int] | None = None
    for symbol, tape in named:
        for minute, index in sorted(tape.at.items()):
            if minute < IMPACT_FROM or minute > IMPACT_TO:
                continue
            bar = tape.bars[index]
            opened = float(bar["open"])
            if opened <= 0:
                continue
            ret = float(bar["close"]) / opened - 1.0
            if side == "down" and ret > -BAR_SHOCK + 1e-12:
                continue
            if side == "up" and ret + 1e-12 < BAR_SHOCK:
                continue
            rank = ret if side == "down" else -ret
            key = (minute, rank, symbol)
            if best is None or key < (best[0], best[1], best[2]):
                best = (minute, rank, symbol, symbol, tape, index)
            break
    if best is None:
        return None
    _minute, _rank, _symbol, symbol, tape, index = best
    spell = _emit(tape, index + 1, IMPACT_HOLD, priority=abs(_rank))
    if spell is None:
        return None
    spell["symbol"] = symbol
    return spell


def _residuals_at(
    named: list[tuple[str, DayTape]],
    spy: DayTape,
    betas: dict[str, float],
    minute: int,
) -> tuple[float | None, list[tuple[float, str, DayTape, int]]]:
    spy_ret = _open_to(spy, minute)
    if spy_ret is None:
        return None, []
    worst: float | None = None
    rows: list[tuple[float, str, DayTape, int]] = []
    for symbol, tape in named:
        beta = betas.get(symbol)
        if beta is None:
            continue
        stock_ret = _open_to(tape, minute)
        sig_i = tape.at.get(minute)
        if stock_ret is None or sig_i is None:
            continue
        residual = stock_ret - beta * spy_ret
        if worst is None or residual < worst:
            worst = residual
        rows.append((residual, symbol, tape, sig_i))
    return worst, rows


def _clock_choice(
    named: list[tuple[str, DayTape]],
    spy: DayTape | None,
    betas: dict[str, float],
    *,
    require_impulse: bool,
) -> tuple[dict[str, Any] | None, float | None, bool]:
    """First qualifying clock. The worst residual is scanned across every clock."""
    if spy is None:
        return None, None, False
    worst: float | None = None
    impulse_ok = False
    chosen: dict[str, Any] | None = None
    for minute in SIGNAL_MINUTES:
        impulse = _window_return(spy, minute, IMPULSE_LOOKBACK)
        if impulse is not None and impulse + 1e-12 >= SPY_IMPULSE:
            impulse_ok = True
        clock_worst, rows = _residuals_at(named, spy, betas, minute)
        if clock_worst is not None and (worst is None or clock_worst < worst):
            worst = clock_worst
        if chosen is not None:
            continue
        if require_impulse and (impulse is None or impulse + 1e-12 < SPY_IMPULSE):
            continue
        qualified = [row for row in rows if row[0] <= RESIDUAL_HURDLE + 1e-12]
        if not qualified:
            continue
        residual, symbol, tape, sig_i = min(qualified, key=lambda row: (row[0], row[1]))
        spell = _emit(tape, sig_i + 1, HOLD_BARS, priority=-residual)
        if spell is None:
            continue
        spell["symbol"] = symbol
        chosen = spell
    return chosen, worst, impulse_ok


def _vwap_choice(named: list[tuple[str, DayTape]]) -> dict[str, Any] | None:
    for minute in SIGNAL_MINUTES:
        rows: list[tuple[float, str, DayTape, int]] = []
        for symbol, tape in named:
            sig_i = tape.at.get(minute)
            if sig_i is None:
                continue
            close = float(tape.bars[sig_i]["close"])
            if close <= 0:
                continue
            vwap = _vwap_through(tape, minute)
            if vwap is None:
                continue
            gap = (vwap - close) / close
            if gap + 1e-12 < VWAP_GAP:
                continue
            rows.append((gap, symbol, tape, sig_i))
        if not rows:
            continue
        gap = max(row[0] for row in rows)
        tied = [row for row in rows if abs(row[0] - gap) <= 1e-12]
        gap, symbol, tape, sig_i = min(tied, key=lambda row: row[1])
        spell = _emit(tape, sig_i + 1, HOLD_BARS, priority=gap)
        if spell is None:
            continue
        spell["symbol"] = symbol
        return spell
    return None


def _last_hour(named: list[tuple[str, DayTape]]) -> dict[str, Any] | None:
    rows: list[tuple[float, str, DayTape]] = []
    for symbol, tape in named:
        sig_i = tape.at.get(LAST_SIGNAL)
        entry_i = tape.at.get(LAST_ENTRY)
        if sig_i is None or entry_i is None or tape.prev_close is None or tape.prev_close <= 0:
            continue
        if entry_i <= sig_i:
            continue
        ret = float(tape.bars[sig_i]["close"]) / tape.prev_close - 1.0
        if ret <= 0:
            continue
        rows.append((ret, symbol, tape))
    if not rows:
        return None
    _ret, symbol, tape = max(rows, key=lambda row: (row[0], ""))
    tied = [row for row in rows if abs(row[0] - _ret) <= 1e-12]
    ret, symbol, tape = min(tied, key=lambda row: row[1])
    entry_i = tape.at[LAST_ENTRY]
    flat_i = None
    for index, bar in enumerate(tape.bars):
        if int(bar["minute"]) <= FLAT_MINUTE:
            flat_i = index
    if flat_i is None or flat_i <= entry_i:
        return None
    entry_open = float(tape.bars[entry_i]["open"])
    spell = make_spell(
        symbol=symbol,
        day=tape.day,
        bars=tape.bars,
        entry_i=entry_i,
        exit_i=flat_i,
        stop=entry_open * (1.0 - DISASTER_STOP),
        priority=ret,
        exit_kind="flat",
    )
    if spell is None:
        return None
    spell["invest_fraction"] = 1.0
    return spell


def generate(book: dict[tuple[str, date], list[dict[str, Any]]]) -> EdgeResult:
    """Walk every pre-holdout session once. Later days do not change earlier spells."""
    for _symbol, day in book:
        assert_no_holdout(day)
    by_symbol = {symbol: _tapes(book, symbol) for symbol in CANDIDATES if any(sym == symbol for sym, _day in book)}
    spy_tapes = _tapes(book, "SPY") if any(sym == "SPY" for sym, _day in book) else []
    spy_by_day = {tape.day: tape for tape in spy_tapes}
    spy_returns = _daily_returns(spy_tapes)
    history: dict[str, list[tuple[float, float]]] = {symbol: [] for symbol in by_symbol}
    days = sorted({tape.day for tapes in by_symbol.values() for tape in tapes} | set(spy_by_day))
    tape_on = {symbol: {tape.day: tape for tape in tapes} for symbol, tapes in by_symbol.items()}
    spells: dict[str, list[dict[str, Any]]] = {name: [] for name in BOOK_NAMES}
    residual_days: list[dict[str, Any]] = []
    for day in days:
        betas: dict[str, float] = {}
        for symbol, pairs in history.items():
            beta = _beta(pairs)
            if beta is not None:
                betas[symbol] = beta
        named = [(symbol, tape_on[symbol][day]) for symbol in CANDIDATES if day in tape_on.get(symbol, {})]
        spy = spy_by_day.get(day)
        primary, worst, impulse = _clock_choice(named, spy, betas, require_impulse=False)
        lagged, _worst_lag, _impulse_lag = _clock_choice(named, spy, betas, require_impulse=True)
        if primary is not None:
            spells["m_primary"].append(primary)
        if lagged is not None:
            spells["m_lag"].append(lagged)
        impact = _first_shock(named, side="down")
        if impact is not None:
            spells["m_impact"].append(impact)
        thrust = _first_shock(named, side="up")
        if thrust is not None:
            spells["m_thrust"].append(thrust)
        vwap = _vwap_choice(named)
        if vwap is not None:
            spells["m_vwap"].append(vwap)
        last = _last_hour(named)
        if last is not None:
            spells["m_lasthour"].append(last)
        if worst is not None:
            residual_days.append(
                {"day": day, "worstResidual": worst, "spyImpulse": impulse, "betaReady": bool(betas)}
            )
        market_ret = spy_returns.get(day)
        if market_ret is not None:
            for _symbol, tape in named:
                if tape.prev_close is None or tape.prev_close <= 0 or tape.close <= 0:
                    continue
                history[_symbol].append((tape.close / tape.prev_close - 1.0, market_ret))
    for name in spells:
        spells[name].sort(key=lambda spell: (spell["day"], spell["entry_t"], spell["symbol"]))
    return EdgeResult(spells, residual_days)
