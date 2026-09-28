"""Pre-registered overlays on the appear-to-disappear book.

Thresholds are frozen. Do not retune them after a run. Sizing, liquidity, and
regime rules keep the live 10:00–11:00 signals and change only size, slippage,
or whether the signal is taken. Time-of-day rules keep the same confirm, exit
lag, and stop, and keep a spell only when the on-list bar falls in that clock.
The 10:00–11:00 clock is the champion and is not retested here.

Nothing here places an order.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from backtest.periods import HOLDOUT_START
from backtest.spells import ACCOUNT_USD

AREAS_BEGIN = "<!-- AREAS_BEGIN -->"
AREAS_END = "<!-- AREAS_END -->"
CHANGELOG_BEGIN = "<!-- AREAS_CHANGELOG_BEGIN -->"
CHANGELOG_END = "<!-- AREAS_CHANGELOG_END -->"

# Frozen before the first run. Not a search grid.
RISK_1PCT = 0.01
RISK_HALF_PCT = 0.005
MAX_CONCURRENT = 1
DAILY_LOSS_FRACTION = 0.01
MAX_CONSECUTIVE_LOSSES = 2
KELLY_MIN_OBS = 80
KELLY_CAP = 0.25
DOLLAR_VOLUME_FLOOR = 5_000_000.0
FALLING_TAPE = -0.003
RANGE_LOOKBACK = 60
RANGE_PERCENTILE = 0.75
OPEN_MINUTE = 9 * 60 + 30
# Scorer already skips the first 15 minutes, so 9:30–9:45 has no membership bars.
TOD_OPEN = (9 * 60 + 45, 10 * 60 + 30)
TOD_MIDDAY = (11 * 60, 13 * 60)
TOD_AFTERNOON = (13 * 60, 14 * 60 + 30)
TOD_LAST_HOUR = (14 * 60 + 30, 15 * 60 + 30)


def assert_preholdout(day: date) -> None:
    if day >= HOLDOUT_START:
        raise RuntimeError(f"holdout day {day} leaked into a research area")


def kelly_fraction(returns: list[float], *, min_obs: int = KELLY_MIN_OBS, cap: float = KELLY_CAP) -> float:
    """Continuous Kelly f* = mean / variance, capped. Too few observations, or f* <= 0, bets nothing.

    The returns have to be full-ticket champion returns. A one-share return would
    be dominated by the US$0.35 minimum and is not the estimator.
    """
    if len(returns) < min_obs:
        return 0.0
    mu = statistics.fmean(returns)
    var = statistics.variance(returns)
    if var <= 0 or mu <= 0:
        return 0.0
    return min(cap, mu / var)


def corwin_schultz_spread(high1: float, low1: float, high2: float, low2: float) -> float:
    """Two-bar Corwin-Schultz spread as a fraction of price. Non-positive alpha is a zero spread.

    The estimator was published for daily highs and lows. These files have no
    quotes, so the same algebra is applied to the entry bar and the bar before
    it. That is an approximation, not a quote.
    """
    if min(high1, low1, high2, low2) <= 0 or high1 < low1 or high2 < low2:
        return 0.0
    if high1 == low1 or high2 == low2:
        return 0.0
    beta = math.log(high1 / low1) ** 2 + math.log(high2 / low2) ** 2
    gamma = math.log(max(high1, high2) / min(low1, low2)) ** 2
    den = 3.0 - 2.0 * math.sqrt(2.0)
    alpha = (math.sqrt(2.0 * beta) - math.sqrt(beta)) / den - math.sqrt(gamma / den)
    if alpha <= 0:
        return 0.0
    exp_alpha = math.exp(alpha)
    return 2.0 * (exp_alpha - 1.0) / (exp_alpha + 1.0)


def percentile_at(values: list[float], fraction: float) -> float:
    """Inclusive rank percentile. For 60 values, 0.75 is the 45th smallest."""
    if not values:
        raise ValueError("percentile of an empty sample")
    ordered = sorted(values)
    index = math.ceil(fraction * len(ordered)) - 1
    index = min(max(index, 0), len(ordered) - 1)
    return ordered[index]


def _copy(spell: dict[str, Any], **extra: Any) -> dict[str, Any]:
    out = dict(spell)
    out.update(extra)
    return out


def _spy_bars(book: dict[tuple[str, date], list[dict[str, Any]]], day: date) -> list[dict[str, Any]]:
    return list(book.get(("SPY", day)) or [])


def _previous_bar(
    book: dict[tuple[str, date], list[dict[str, Any]]], spell: dict[str, Any]
) -> dict[str, Any] | None:
    bars = book.get((spell["symbol"], spell["day"])) or []
    minute = int(spell["entry_bar"]["minute"])
    previous = None
    for bar in bars:
        if int(bar["minute"]) < minute:
            previous = bar
        else:
            break
    return previous


def annotate_kelly(
    spells: list[dict[str, Any]], champion_trades: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str]:
    """Size from champion returns whose exit day is strictly before the new entry day."""
    by_day: dict[date, list[float]] = {}
    for trade in champion_trades:
        by_day.setdefault(trade["day"], []).append(float(trade["ret"]))
    running: list[float] = []
    fraction_on: dict[date, float] = {}
    days = sorted(set(by_day) | {spell["day"] for spell in spells})
    for day in days:
        fraction_on[day] = kelly_fraction(running)
        running.extend(by_day.get(day, []))
    out = [_copy(spell, invest_fraction=fraction_on.get(spell["day"], 0.0)) for spell in spells]
    positive = sum(1 for spell in out if float(spell["invest_fraction"]) > 0)
    return out, (
        f"Kelly uses full-ticket champion returns from earlier sessions only, "
        f"needs {KELLY_MIN_OBS} of them, and caps f* at {KELLY_CAP:.0%}. "
        f"{positive} of {len(out)} spells had f* > 0."
    )


def half_spread_slip(
    book: dict[tuple[str, date], list[dict[str, Any]]], spell: dict[str, Any]
) -> float:
    """2 bp plus half the Corwin-Schultz spread, in basis points. No previous bar leaves the spread at 0."""
    previous = _previous_bar(book, spell)
    entry = spell["entry_bar"]
    if previous is None:
        return 2.0
    spread = corwin_schultz_spread(
        float(previous["high"]),
        float(previous["low"]),
        float(entry["high"]),
        float(entry["low"]),
    )
    return 2.0 + spread * 5_000.0


def participation_slip(spell: dict[str, Any]) -> float | None:
    """2 bp plus square-root impact at a full US$2,120 ticket. Missing volume skips the spell.

    Impact is charged at floor(2120 / price) shares even when the fill is smaller.
    That is the conservative, pre-registered size. Sigma is the stop distance over price.
    """
    bar = spell["entry_bar"]
    price = float(bar["open"])
    volume = bar.get("volume")
    if volume is None or price <= 0:
        return None
    dollar = float(volume) * float(bar["close"])
    if dollar <= 0:
        return None
    sigma = max(0.0, (price - float(spell["stop"])) / price)
    shares = int(ACCOUNT_USD // price)
    notional = shares * price
    if notional <= 0:
        return None
    impact = 10_000.0 * sigma * math.sqrt(notional / dollar)
    return 2.0 + impact


def passes_dollar_volume(spell: dict[str, Any], floor: float = DOLLAR_VOLUME_FLOOR) -> bool:
    bar = spell["entry_bar"]
    volume = bar.get("volume")
    if volume is None:
        return False
    return float(volume) * float(bar["close"]) >= floor


def spy_above_vwap(
    book: dict[tuple[str, date], list[dict[str, Any]]], spell: dict[str, Any]
) -> bool | None:
    """True when the SPY close at or before the on-list bar is at or above that bar's session VWAP.

    None means the SPY session is missing, which skips the spell.
    """
    target = int(spell["buy_minute"])
    pv = 0.0
    vol = 0.0
    chosen: dict[str, Any] | None = None
    vwap: float | None = None
    for bar in _spy_bars(book, spell["day"]):
        minute = int(bar["minute"])
        if minute < OPEN_MINUTE:
            continue
        if minute > target:
            break
        typical = (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3.0
        volume = float(bar.get("volume") or 0.0)
        vol += volume
        pv += typical * volume
        chosen = bar
        vwap = pv / vol if vol > 0 else None
    if chosen is None or vwap is None:
        return None
    return float(chosen["close"]) + 1e-12 >= vwap


def spy_session_ranges(book: dict[tuple[str, date], list[dict[str, Any]]]) -> dict[date, float]:
    ranges: dict[date, float] = {}
    days = sorted(day for (symbol, day) in book if symbol == "SPY")
    for day in days:
        assert_preholdout(day)
        bars = [bar for bar in _spy_bars(book, day) if int(bar["minute"]) >= OPEN_MINUTE]
        if not bars:
            continue
        high = max(float(bar["high"]) for bar in bars)
        low = min(float(bar["low"]) for bar in bars)
        close = float(bars[-1]["close"])
        if close <= 0:
            continue
        ranges[day] = (high - low) / close
    return ranges


def high_range_days(ranges: dict[date, float]) -> set[date]:
    """Sessions to stand aside: fewer than 60 prior days, or yesterday's range at or above their 75th percentile."""
    ordered = sorted(ranges)
    stand: set[date] = set()
    for index, day in enumerate(ordered):
        if index < RANGE_LOOKBACK:
            stand.add(day)
            continue
        window = [ranges[ordered[cursor]] for cursor in range(index - RANGE_LOOKBACK, index)]
        prior = ranges[ordered[index - 1]]
        if prior + 1e-15 >= percentile_at(window, RANGE_PERCENTILE):
            stand.add(day)
    return stand


def falling_tape(
    book: dict[tuple[str, date], list[dict[str, Any]]], spell: dict[str, Any]
) -> bool | None:
    """True when SPY is down at least 0.30% from the 9:30 open to the on-list bar. None skips."""
    bars = [bar for bar in _spy_bars(book, spell["day"]) if int(bar["minute"]) >= OPEN_MINUTE]
    if not bars:
        return None
    open_px = float(bars[0]["open"])
    if open_px <= 0:
        return None
    chosen = None
    for bar in bars:
        if int(bar["minute"]) <= int(spell["buy_minute"]):
            chosen = bar
        else:
            break
    if chosen is None:
        return None
    return float(chosen["close"]) / open_px - 1.0 <= FALLING_TAPE


@dataclass(frozen=True)
class Prepared:
    spells: list[dict[str, Any]]
    kwargs: dict[str, Any]
    note: str


Prepare = Callable[
    [list[dict[str, Any]], dict[tuple[str, date], list[dict[str, Any]]], list[dict[str, Any]]],
    Prepared,
]


def _sizing(risk: float | None = None, **kwargs: Any) -> Prepare:
    portfolio_kwargs = dict(kwargs)
    if risk is not None:
        portfolio_kwargs["risk_fraction"] = risk

    def prepare(
        spells: list[dict[str, Any]],
        _book: dict[tuple[str, date], list[dict[str, Any]]],
        _trades: list[dict[str, Any]],
    ) -> Prepared:
        return Prepared([dict(spell) for spell in spells], portfolio_kwargs, "Same midmorning signals. Only the size or the daily stop changes.")

    return prepare


def _kelly_prepare(
    spells: list[dict[str, Any]],
    _book: dict[tuple[str, date], list[dict[str, Any]]],
    trades: list[dict[str, Any]],
) -> Prepared:
    sized, note = annotate_kelly(spells, trades)
    return Prepared(sized, {}, note)


def _clock(start: int, end: int) -> Prepare:
    def prepare(
        spells: list[dict[str, Any]],
        _book: dict[tuple[str, date], list[dict[str, Any]]],
        _trades: list[dict[str, Any]],
    ) -> Prepared:
        kept = [dict(spell) for spell in spells if start <= int(spell["buy_minute"]) < end]
        return Prepared(
            kept,
            {},
            f"On-list bar in [{start}, {end}) minutes from midnight. {len(kept)} of {len(spells)} appearances.",
        )

    return prepare


def _half_spread_prepare(
    spells: list[dict[str, Any]],
    book: dict[tuple[str, date], list[dict[str, Any]]],
    _trades: list[dict[str, Any]],
) -> Prepared:
    out = []
    extra = []
    missing = 0
    for spell in spells:
        slip = half_spread_slip(book, spell)
        if _previous_bar(book, spell) is None:
            missing += 1
        extra.append(slip - 2.0)
        out.append(_copy(spell, slip_bps=slip))
    mean_extra = statistics.fmean(extra) if extra else 0.0
    return Prepared(
        out,
        {},
        f"Mean extra slippage {mean_extra:.3f} bp. {missing} spells had no previous bar and kept a zero spread.",
    )


def _participation_prepare(
    spells: list[dict[str, Any]],
    _book: dict[tuple[str, date], list[dict[str, Any]]],
    _trades: list[dict[str, Any]],
) -> Prepared:
    out = []
    extra = []
    skipped = 0
    for spell in spells:
        slip = participation_slip(spell)
        if slip is None:
            skipped += 1
            continue
        extra.append(slip - 2.0)
        out.append(_copy(spell, slip_bps=slip))
    mean_extra = statistics.fmean(extra) if extra else 0.0
    return Prepared(
        out,
        {},
        f"Skipped {skipped} of {len(spells)} spells with no dollar volume. Mean square-root impact {mean_extra:.3f} bp.",
    )


def _dollar_volume_prepare(
    spells: list[dict[str, Any]],
    _book: dict[tuple[str, date], list[dict[str, Any]]],
    _trades: list[dict[str, Any]],
) -> Prepared:
    kept = [dict(spell) for spell in spells if passes_dollar_volume(spell)]
    return Prepared(
        kept,
        {},
        f"Entry-bar dollar volume at least ${DOLLAR_VOLUME_FLOOR:,.0f}. Kept {len(kept)} of {len(spells)}.",
    )


def _vwap_prepare(
    spells: list[dict[str, Any]],
    book: dict[tuple[str, date], list[dict[str, Any]]],
    _trades: list[dict[str, Any]],
) -> Prepared:
    kept = []
    missing = 0
    aside = 0
    for spell in spells:
        flag = spy_above_vwap(book, spell)
        if flag is None:
            missing += 1
            continue
        if not flag:
            aside += 1
            continue
        kept.append(dict(spell))
    return Prepared(kept, {}, f"Took {len(kept)}. Stood aside {aside} under VWAP. Skipped {missing} with no SPY bar.")


def _range_prepare(
    spells: list[dict[str, Any]],
    book: dict[tuple[str, date], list[dict[str, Any]]],
    _trades: list[dict[str, Any]],
) -> Prepared:
    stand = high_range_days(spy_session_ranges(book))
    kept = []
    aside = 0
    for spell in spells:
        if spell["day"] in stand or ("SPY", spell["day"]) not in book:
            aside += 1
            continue
        kept.append(dict(spell))
    return Prepared(
        kept,
        {},
        f"Stood aside {aside} of {len(spells)} after a wide prior SPY day, or before 60 prior sessions existed.",
    )


def _falling_prepare(
    spells: list[dict[str, Any]],
    book: dict[tuple[str, date], list[dict[str, Any]]],
    _trades: list[dict[str, Any]],
) -> Prepared:
    kept = []
    aside = 0
    missing = 0
    for spell in spells:
        flag = falling_tape(book, spell)
        if flag is None:
            missing += 1
            continue
        if flag:
            aside += 1
            continue
        kept.append(dict(spell))
    return Prepared(
        kept,
        {},
        f"Took {len(kept)}. Stood aside {aside} when SPY was down {abs(FALLING_TAPE) * 100:.2f}% or more from the open. Skipped {missing} with no SPY bar.",
    )


@dataclass(frozen=True)
class Area:
    id: str
    area: str
    source: str
    hypothesis: str
    rationale: str
    setup: str
    uses_clock: bool
    prepare: Prepare


AREA_REGISTRY: list[Area] = [
    Area(
        id="sz_risk_1pct",
        area="position_sizing",
        source="Kelly (1956), Bell System Technical Journal; Thorp, fractional Kelly. Fixed-fractional risk is the retail cap used here, not a fitted Kelly fraction. Vince optimal-f is the aggressive cousin and is not searched.",
        hypothesis="Risking 1% of current equity to the stop, in whole shares, loses less to a single gap than a full US$2,120 ticket and still clears the minimum commission.",
        rationale="On a US$2,120 account one full ticket is often the whole account. A stop a few dollars under a US$100 name can remove several percent of equity, and the US$0.35 minimum is already a few basis points on a two-share fill. Capping the loss at 1% of equity (cash plus open cost) keeps a gap from dominating the book. The other side of a too-small fill is the minimum commission, which the whole-share round-down does not waive.",
        setup="Same midmorning spells. risk_fraction=0.01. Shares = floor(equity × 0.01 / (slipped entry − stop)), then reduced until notional plus the buy commission fits cash. Skip when that is under one share.",
        uses_clock=False,
        prepare=_sizing(RISK_1PCT),
    ),
    Area(
        id="sz_risk_half_pct",
        area="position_sizing",
        source="Same as sz_risk_1pct. The live stop is already about one ATR, so 0.5% of equity per stop distance is the volatility-scaled cousin of the 1% rule. Both fractions were written down together. Neither is chosen because it lost less.",
        hypothesis="Risking 0.5% of equity to the same stop is small enough that one loss cannot move the account, and large enough that the US$0.35 minimum does not take the whole edge on a typical mega-cap print.",
        rationale="Half a percent is the pre-registered tighter cap. It is not a second look at the 1% result. If the champion's edge is negative, a smaller bet loses fewer dollars and can still lose on a per-trade basis once the minimum commission binds. The gate requires a better dollar total and a better per-trade expectancy, so shrinking a losing book is not by itself an improvement.",
        setup="Same midmorning spells. risk_fraction=0.005. Same whole-share and cash cap as the 1% rule.",
        uses_clock=False,
        prepare=_sizing(RISK_HALF_PCT),
    ),
    Area(
        id="sz_one_position",
        area="position_sizing",
        source="Concentration and gap risk on a cash account that cannot borrow. One open long is the tightest concurrent-position cap.",
        hypothesis="Allowing only one open position removes the case where several names gap through their stops together and the cash account cannot fund the later, better signal.",
        rationale="The champion spends remaining cash on every new name. Two or three mega-caps can each gap through a stop in the same bar. A one-position book gives up later signals in exchange for a smaller overnight-style intraday gap. Alphabetical order still breaks ties, matching the champion.",
        setup="Same midmorning spells and full-ticket size. max_concurrent=1. A name is skipped while another fill is still open.",
        uses_clock=False,
        prepare=_sizing(max_concurrent=MAX_CONCURRENT),
    ),
    Area(
        id="sz_daily_stop",
        area="position_sizing",
        source="A daily loss limit is a hard risk budget, not a signal. The consecutive-loss stop is the same idea in trade counts. Both reset the next session and were fixed before the run.",
        hypothesis="Stopping for the day after a 1% realized loss, or after two consecutive losing fills, avoids a session where the tape has already gone against every dip.",
        rationale="If the morning is a one-way offer, later dip buys are the same informed seller. A 1% equity stop and a two-loss stop are crude ways to stand aside without fitting a new indicator. Realized losses count; an open trade does not trip the stop until it closes. A winner resets the consecutive-loss count. Neither threshold is moved after the run.",
        setup="Same midmorning spells and full-ticket size. daily_loss_fraction=0.01 of that session's starting equity, or max_consecutive_losses=2. Both reset the next session.",
        uses_clock=False,
        prepare=_sizing(daily_loss_fraction=DAILY_LOSS_FRACTION, max_consecutive_losses=MAX_CONSECUTIVE_LOSSES),
    ),
    Area(
        id="sz_kelly_cap",
        area="position_sizing",
        source="Kelly (1956); Thorp on fractional Kelly. The cap at one quarter is the pre-registered fractional-Kelly limit. It is not estimated from the holdout.",
        hypothesis="A fractional Kelly fraction, estimated only from earlier full-ticket champion trades and capped at 25% of equity, bets more only when that past sample has a positive mean.",
        rationale="Kelly's fraction is mean over variance. A negative mean is a zero bet: the formula says the game is not worth playing. That is the economic content. An empty book does not beat a losing champion on the gate, because an empty book has no trades. Standing aside is reported as a rejection, not adopted as a live rule that trades nothing. The estimator uses full-ticket returns so the US$0.35 minimum is in the same units as the live book. Fewer than 80 prior trades also bets nothing.",
        setup="invest_fraction = min(0.25, mean/variance) from champion trades whose session is strictly before the new entry day. f* <= 0 or fewer than 80 prior trades sets invest_fraction to 0 and the spell is skipped. Whole shares, cash cap unchanged.",
        uses_clock=False,
        prepare=_kelly_prepare,
    ),
    Area(
        id="tod_open",
        area="time_of_day",
        source="Admati and Pfleiderer (1988), Review of Financial Studies, volume and informed flow at the open and the close; Gao, Han, Li and Zhou, Journal of Financial Economics 2018, DOI 10.1016/j.jfineco.2018.05.009; Heston, Korajczyk and Sadka, Journal of Finance 2010, DOI 10.1111/j.1540-6261.2010.01573.x.",
        hypothesis="Appearances from 9:45 to 10:30 have a different cost-inclusive edge from the rest of the day because the open concentrates volume.",
        rationale="The open is when overnight inventory is unwound. Gao's first-half-hour pattern was already tested as its own trade and rejected; this overlay only asks whether the existing list is less bad in that window. The scorer drops the first 15 minutes, so 9:30–9:45 is empty on purpose and is not a missing file. The live 10:00–11:00 window is the champion and is not a challenger.",
        setup="Same confirm, exit lag, and stop as the live rule. Keep a spell only when the on-list bar is in [9:45, 10:30). The fill is still the next bar's open, which can fall a bar outside the window. Exit is still disappearance or 15:55.",
        uses_clock=True,
        prepare=_clock(*TOD_OPEN),
    ),
    Area(
        id="tod_midday",
        area="time_of_day",
        source="Heston, Korajczyk and Sadka (2010), same-clock half-hour patterns; Admati and Pfleiderer (1988) on the midday lull in volume.",
        hypothesis="Appearances from 11:00 to 13:00 are the quiet-tape book, and either pay after costs or are no better than the champion.",
        rationale="Midday volume is thinner, so a listed dip is more likely a lack of bids than an informed buyer. If that is the case the window should not be adopted. The comparison is the champion's 10:00–11:00 book, not a search for the least-negative clock.",
        setup="On-list bar in [11:00, 13:00). Same confirm, exit lag, stop, and disappearance exit.",
        uses_clock=True,
        prepare=_clock(*TOD_MIDDAY),
    ),
    Area(
        id="tod_afternoon",
        area="time_of_day",
        source="Heston, Korajczyk and Sadka (2010). Afternoon half-hours are a different clock from the open and from the last hour.",
        hypothesis="Appearances from 13:00 to 14:30 carry the same list edge without the open's inventory shock or the close's hedging flow.",
        rationale="A window that is merely less negative than another losing window is not a promotion. It has to beat the champion on net and on expectancy in the gate's windows. This clock was written down with the others and is not a fallback if the open fails.",
        setup="On-list bar in [13:00, 14:30). Same confirm, exit lag, stop, and disappearance exit.",
        uses_clock=True,
        prepare=_clock(*TOD_AFTERNOON),
    ),
    Area(
        id="tod_last_hour",
        area="time_of_day",
        source="Gao, Han, Li and Zhou (2018), last-half-hour return; Admati and Pfleiderer (1988), volume at the close. The live book is flat by 15:55 and does not trade the closing auction.",
        hypothesis="Appearances from 14:30 to 15:30 still have time to exit on a disappearance or the 15:55 flat, and the close's volume is enough to pay the ticket.",
        rationale="The published last-half-hour effect is a long into the auction. This book is flat before the auction, so the economic claim is weaker: only that a late appearance of the same dip is a better or worse trade than a midmorning one. The scorer also drops the last 15 minutes, so the window stops at 15:30.",
        setup="On-list bar in [14:30, 15:30). Same confirm, exit lag, stop, and disappearance or 15:55 flat.",
        uses_clock=True,
        prepare=_clock(*TOD_LAST_HOUR),
    ),
    Area(
        id="liq_half_spread",
        area="liquidity",
        source="Corwin and Schultz, Journal of Finance 2012, DOI 10.1111/j.1540-6261.2011.01694.x. These files are OHLC, not quotes, so the two-bar high-low estimator stands in for the spread.",
        hypothesis="Adding half the estimated spread to the 2 bp slippage removes trades whose edge was only an ignored bid-ask bounce, or shows that the spread is too small to matter next to the commission.",
        rationale="A marketable buy pays the half-spread on top of any delay. If the expected rebound is a few basis points and the spread is wider than that, the fill erases it. The estimator returns zero when alpha is non-positive, and zero when the entry bar has no previous bar. It is not a quote, and a zero is not evidence that the spread was zero.",
        setup="slip_bps = 2 + half the Corwin-Schultz spread in basis points, from the entry bar and the previous bar. Same midmorning signals and full-ticket size.",
        uses_clock=False,
        prepare=_half_spread_prepare,
    ),
    Area(
        id="liq_participation",
        area="liquidity",
        source="Kyle, Econometrica 1985; Almgren, Thum, Hauptmann and Li, Risk 2005, square-root impact.",
        hypothesis="Impact of a US$2,120 ticket in a mega-cap 5-minute bar is a fraction of a basis point, so the US$0.35 minimum, not participation, is the binding friction.",
        rationale="Temporary impact in the square-root model scales with volatility times the square root of order size over volume. A two-thousand-dollar order against tens of millions of dollars in a 5-minute bar is invisible. Charging it anyway is the test. If the mean impact is far below the minimum commission, a participation filter will not create an edge.",
        setup="impact_bps = 10000 × ((open − stop) / open) × sqrt(notional / entry-bar dollar volume), notional = floor(2120 / price) × price. slip_bps = 2 + impact. Missing volume skips the spell.",
        uses_clock=False,
        prepare=_participation_prepare,
    ),
    Area(
        id="liq_dvol",
        area="liquidity",
        source="Kyle (1985). A dollar-volume floor is a crude participation limit when the spread itself is not observed.",
        hypothesis="Skipping an entry bar under US$5,000,000 of dollar volume drops names where a small ticket could still move the print, and does nothing on bars that already trade far more than that.",
        rationale="These eight names often print tens of millions of dollars in a 5-minute bar. A US$5,000,000 floor was frozen as a level that can bind on a quiet bar without being fit to the result. A filter that drops nothing matches the champion and is not an improvement. Missing volume skips the spell.",
        setup="Keep the spell only when entry-bar volume × close is at least US$5,000,000. Same size and 2 bp slippage otherwise.",
        uses_clock=False,
        prepare=_dollar_volume_prepare,
    ),
    Area(
        id="reg_spy_vwap",
        area="market_regime",
        source="Berkowitz, Logue and Noser, Journal of Finance 1988, VWAP as the execution benchmark. The list is a dip in a single name.",
        hypothesis="A long dip while SPY itself is offered under its session VWAP is a bid into a market that is already being sold, and should be skipped.",
        rationale="The other side of a name trading under VWAP, while the index is also under VWAP, is more likely an index seller than a buyer of that name. Taking the dip only when SPY has reclaimed VWAP asks for the index bid to be present. The comparison uses the SPY bar at or before the on-list minute, so the fill one bar later is not in the signal. A missing SPY day skips the spell.",
        setup="Take the long only when the SPY close at or before the on-list bar is at or above the session VWAP of typical price × volume from 9:30 through that bar.",
        uses_clock=False,
        prepare=_vwap_prepare,
    ),
    Area(
        id="reg_high_range",
        area="market_regime",
        source="Grossman and Miller, Journal of Finance 1988, inventory risk after a large move. Wilder (1978) ADX is the practitioner cousin and is not used: the smoothing length would be another search.",
        hypothesis="After a prior SPY day in the top quartile of recent ranges, the next open is a gap risk the US$2,120 account should not take.",
        rationale="A wide prior day leaves dealers with inventory and leaves stops closer to the open. Standing aside is the pre-registered response. The 75th percentile of the previous 60 sessions is one frozen split. It is not refit inside a half-year, and it is not flipped to 'only trade wide days' if this direction loses. Fewer than 60 prior sessions means do not trade.",
        setup="Stand aside when yesterday's SPY (high − low) / close is at or above the 75th percentile of the previous 60 sessions, or when those 60 sessions do not exist yet.",
        uses_clock=False,
        prepare=_range_prepare,
    ),
    Area(
        id="reg_falling_tape",
        area="market_regime",
        source="Kyle (1985): an informed seller makes the bid toxic. The −0.30% open-to-signal drop is frozen and is not the live scorer's −0.22% six-bar gate.",
        hypothesis="Skipping the list when SPY is already down 0.30% from the 9:30 open to the on-list bar avoids buying a dip while the index seller is still active.",
        rationale="A single-name pullback in a falling index is often the same trade as the index. The threshold is −0.30% from today's open, known at the on-list bar and before the next-bar fill. It was not chosen by looking at which side of zero lost less. The rule stands aside in that state and does not flip to short. A missing SPY day skips the spell.",
        setup="Stand aside when SPY close at the on-list bar / SPY 9:30 open − 1 is at or below −0.003. Otherwise the champion spell is unchanged.",
        uses_clock=False,
        prepare=_falling_prepare,
    ),
]
