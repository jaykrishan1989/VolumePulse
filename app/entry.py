"""Right Time to Buy — selective intraday long setups.

Every threshold lives on ``ENTRY``. The scorer is pure: bars in, signal or
nothing. A name appears only while a pullback has just turned up; it drops
off once the trigger is stale, the rebound low breaks, or price has run too
far. This module never places orders.

Bars are dicts with ``t`` (epoch seconds), ``open``, ``high``, ``low``,
``close``, and ``volume``. Times are interpreted in America/New_York.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.sectors import sector_by_id

try:
    NY = ZoneInfo("America/New_York")
except Exception:
    NY = timezone(timedelta(hours=-4), "EDT")

DISCLAIMER = (
    "Not financial advice. Volume Pulse never places orders. A row is a short-term "
    "long setup on this tape, not a recommendation, and it drops off when that setup "
    "is no longer valid."
)

# Specific groups win over broad ones so NVDA maps to SMH, not XLK.
_SECTOR_PREFERENCE = (
    "semi",
    "biotech",
    "banks",
    "tech",
    "comm",
    "health",
    "financials",
    "energy",
    "industrials",
    "discretionary",
    "staples",
    "realty",
    "materials",
    "utilities",
)

# Liquid names only. Kept short so streaming quotes plus sector ETFs stay
# inside a typical IBKR market-data line budget.
ENTRY_STOCKS = [
    "AAPL", "MSFT", "NVDA", "AMD", "AVGO", "MU", "INTC", "QCOM", "AMAT",
    "META", "GOOGL", "NFLX",
    "AMZN", "TSLA", "HD",
    "JPM", "BAC", "GS",
    "XOM", "CVX",
    "UNH", "LLY",
    "COST", "WMT",
    "CAT",
]

_CONTEXT_ALWAYS = ("SPY", "QQQ")


@dataclass(frozen=True)
class EntryConfig:
    """All Right Time to Buy gates. Edit this object to retune the filter."""

    bar_minutes: int = 5
    min_price: float = 8.0
    # Full-session dollar volume. Early bars are scaled by session fraction.
    min_dollar_volume: float = 8_000_000.0
    min_session_fraction: float = 0.15
    max_spread_pct: float = 0.0018
    skip_open_minutes: int = 15
    skip_close_minutes: int = 15
    # Allows a delayed tape (~15 min) plus the rotating historical refresh.
    max_data_lag_sec: int = 35 * 60
    atr_period: int = 14
    ema_period: int = 9
    rsi_period: int = 14
    rsi_oversold: float = 45.0
    stoch_period: int = 8
    stoch_smooth: int = 3
    stoch_oversold: float = 30.0
    # Pullback depth is (session high − rebound trough) / 5-min ATR.
    min_pullback_atr: float = 3.2
    max_pullback_atr: float = 11.0
    sweet_pullback_atr: float = 6.0
    min_pullback_pct: float = 0.7
    min_bounce_atr: float = 0.55
    max_extension_atr: float = 1.6
    min_confirms: int = 2
    max_trigger_age_bars: int = 3
    up_volume_ratio: float = 1.15
    min_rvol_gate: float = 1.45
    min_rr: float = 1.3
    stop_atr_buffer: float = 0.28
    context_lookback_bars: int = 6
    context_max_drop: float = -0.0022
    context_day_drop: float = -0.0075
    min_score: float = 70.0
    top_n: int = 8
    min_today_bars: int = 8
    max_subscriptions: int = 40

    # Score weights. They sum above 100 and are capped.
    w_pullback: float = 24.0
    w_higher_low: float = 12.0
    w_vwap: float = 12.0
    w_ema: float = 6.0
    w_rsi: float = 8.0
    w_stoch: float = 6.0
    w_confirm_cap: float = 32.0
    w_volume: float = 16.0
    w_context: float = 12.0
    w_fresh: float = 12.0
    w_quality: float = 8.0
    w_rr: float = 8.0


ENTRY = EntryConfig()


def _norm(symbol: str) -> str:
    return " ".join((symbol or "").upper().replace(".", " ").split())


def sector_etf_for(symbol: str) -> str | None:
    key = _norm(symbol)
    if not key:
        return None
    for sector_id in _SECTOR_PREFERENCE:
        item = sector_by_id(sector_id)
        if not item:
            continue
        for raw in item["stocks"]:
            if _norm(str(raw)) == key:
                return str(item["etf"])
    return None


def context_symbols(stocks: list[str] | None = None) -> list[str]:
    symbols = list(_CONTEXT_ALWAYS)
    for symbol in stocks if stocks is not None else ENTRY_STOCKS:
        etf = sector_etf_for(symbol)
        if etf and etf not in symbols:
            symbols.append(etf)
    return symbols


def watch_symbols(cfg: EntryConfig = ENTRY) -> list[str]:
    """Stocks to score, then SPY/QQQ and the sector ETFs those stocks need."""
    context = context_symbols(ENTRY_STOCKS)
    room = max(0, cfg.max_subscriptions - len(context))
    return list(ENTRY_STOCKS[:room]) + context


def _px(value: float) -> float:
    if abs(value) >= 1:
        return round(float(value), 2)
    return round(float(value), 4)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _as_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=NY)
        return value.astimezone(NY)
    number = _finite(value)
    if number is None:
        return None
    return datetime.fromtimestamp(number, NY)


def _clean_bars(bars: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for bar in bars or []:
        moment = _as_dt(bar.get("t"))
        close = _finite(bar.get("close"))
        if moment is None or close is None or close <= 0:
            continue
        open_px = _finite(bar.get("open")) or close
        high = _finite(bar.get("high")) or max(open_px, close)
        low = _finite(bar.get("low")) or min(open_px, close)
        volume = _finite(bar.get("volume")) or 0.0
        if volume < 0:
            volume = 0.0
        cleaned.append(
            {
                "t": int(moment.timestamp()),
                "dt": moment,
                "open": open_px,
                "high": max(high, open_px, close),
                "low": min(low, open_px, close),
                "close": close,
                "volume": volume,
            }
        )
    cleaned.sort(key=lambda item: item["t"])
    return cleaned


def _rth(moment: datetime) -> bool:
    minutes = moment.hour * 60 + moment.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


def _ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    weight = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for index in range(period, len(values)):
        prev = values[index] * weight + prev * (1 - weight)
        out[index] = prev
    return out


def _rsi(closes: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if period <= 0 or len(closes) <= period:
        return out
    gain = 0.0
    loss = 0.0
    for index in range(1, period + 1):
        change = closes[index] - closes[index - 1]
        gain += max(change, 0.0)
        loss += max(-change, 0.0)
    avg_gain = gain / period
    avg_loss = loss / period

    def reading(avg_g: float, avg_l: float) -> float:
        if avg_l <= 1e-12:
            return 100.0
        rs = avg_g / avg_l
        return 100.0 - (100.0 / (1.0 + rs))

    out[period] = reading(avg_gain, avg_loss)
    for index in range(period + 1, len(closes)):
        change = closes[index] - closes[index - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[index] = reading(avg_gain, avg_loss)
    return out


def _atr(bars: list[dict[str, Any]], period: int) -> list[float | None]:
    trs: list[float] = []
    prev_close = None
    for bar in bars:
        if prev_close is None:
            tr = bar["high"] - bar["low"]
        else:
            tr = max(
                bar["high"] - bar["low"],
                abs(bar["high"] - prev_close),
                abs(bar["low"] - prev_close),
            )
        trs.append(tr)
        prev_close = bar["close"]
    out: list[float | None] = [None] * len(bars)
    if not trs:
        return out
    if len(trs) < period or period <= 0:
        avg = sum(trs) / len(trs)
        return [avg] * len(bars)
    avg = sum(trs[:period]) / period
    out[period - 1] = avg
    for index in range(period, len(trs)):
        avg = (avg * (period - 1) + trs[index]) / period
        out[index] = avg
    # Warm the bars before the first full window so early today can still score.
    for index in range(period - 1):
        out[index] = out[period - 1]
    return out


def _stoch(
    bars: list[dict[str, Any]], period: int, smooth: int
) -> tuple[list[float | None], list[float | None]]:
    k: list[float | None] = [None] * len(bars)
    if period > 0:
        for index in range(period - 1, len(bars)):
            window = bars[index - period + 1 : index + 1]
            lo = min(item["low"] for item in window)
            hi = max(item["high"] for item in window)
            if hi <= lo:
                k[index] = 50.0
            else:
                k[index] = (bars[index]["close"] - lo) / (hi - lo) * 100.0
    d: list[float | None] = [None] * len(bars)
    if smooth > 0:
        for index in range(len(bars)):
            chunk = [
                k[pos]
                for pos in range(index - smooth + 1, index + 1)
                if pos >= 0 and k[pos] is not None
            ]
            if len(chunk) == smooth:
                d[index] = sum(chunk) / smooth
    return k, d


def _clock_minutes(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def market_state(bars: list[dict[str, Any]] | None, cfg: EntryConfig = ENTRY) -> str:
    """``firm``, ``falling``, or ``unknown`` from the latest regular-session bars."""
    cleaned = [bar for bar in _clean_bars(bars) if _rth(bar["dt"])]
    if len(cleaned) < cfg.context_lookback_bars + 1:
        return "unknown"
    last = cleaned[-1]
    today = [bar for bar in cleaned if bar["dt"].date() == last["dt"].date()]
    if len(today) < cfg.context_lookback_bars + 1:
        return "unknown"
    earlier = today[-(cfg.context_lookback_bars + 1)]
    if earlier["close"] <= 0:
        return "unknown"
    recent = (today[-1]["close"] - earlier["close"]) / earlier["close"]
    if recent <= cfg.context_max_drop:
        return "falling"
    opened = today[0]["open"] or today[0]["close"]
    if opened:
        day_return = (today[-1]["close"] - opened) / opened
        if day_return <= cfg.context_day_drop and recent < 0:
            return "falling"
    return "firm"


def _fail(reason: str, **detail: Any) -> dict[str, Any]:
    return {"ok": False, "fail": reason, "signal": None, **detail}


@dataclass
class EntrySignal:
    symbol: str
    score: float
    reasons: list[str]
    entry_low: float
    entry_high: float
    stop: float
    target: float
    reward_risk: float
    triggered_bars: int
    triggered_ago_sec: int
    last: float
    pullback_atr: float
    vwap: float | None = None
    atr: float | None = None

    def as_row(self) -> dict[str, Any]:
        row = {
            "entryScore": int(round(self.score)),
            "entryReasons": list(self.reasons),
            "entryLow": self.entry_low,
            "entryHigh": self.entry_high,
            "entryStop": self.stop,
            "entryTarget": self.target,
            "entryRR": self.reward_risk,
            "entryBars": self.triggered_bars,
            "entryAgoSec": self.triggered_ago_sec,
            "entryPullbackAtr": round(self.pullback_atr, 2),
        }
        if self.vwap is not None:
            row["vwap"] = self.vwap
        if self.atr is not None:
            row["entryAtr"] = self.atr
        return row


def diagnose_entry(
    bars: list[dict[str, Any]] | None,
    quote: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    session_fraction: float = 0.5,
    enforce_clock: bool = True,
    spy_state: str = "unknown",
    qqq_state: str = "unknown",
    sector_state: str = "unknown",
    sector_etf: str | None = None,
    cfg: EntryConfig = ENTRY,
) -> dict[str, Any]:
    """Score one name. ``fail`` explains the first gate that rejected it."""
    quote = quote or {}
    symbol = str(quote.get("symbol") or "")
    cleaned = _clean_bars(bars)
    rth = [bar for bar in cleaned if _rth(bar["dt"])]
    if len(rth) < cfg.atr_period:
        return _fail("not enough bars")

    last_bar = rth[-1]
    today = [bar for bar in rth if bar["dt"].date() == last_bar["dt"].date()]
    if len(today) < cfg.min_today_bars:
        return _fail("session too young")
    today_start = len(rth) - len(today)

    if enforce_clock:
        moment_now = now.astimezone(NY) if now is not None else datetime.now(NY)
        if last_bar["dt"].date() != moment_now.date():
            return _fail("bars are not from today's session")
        lag = (moment_now - last_bar["dt"]).total_seconds()
        if lag > cfg.max_data_lag_sec:
            return _fail("tape is stale")
        if lag < -120:
            return _fail("bar clock is ahead of now")
        open_m = 9 * 60 + 30
        close_m = 16 * 60
        minutes = _clock_minutes(last_bar["dt"])
        if minutes < open_m + cfg.skip_open_minutes:
            return _fail("too soon after the open")
        if minutes >= close_m - cfg.skip_close_minutes:
            return _fail("too close to the close")

    halted = quote.get("halted")
    try:
        halted_flag = int(halted) if halted is not None else 0
    except (TypeError, ValueError):
        halted_flag = 0
    if halted_flag in (1, 2):
        return _fail("halted")
    if today[-1]["volume"] <= 0 and today[-2]["volume"] <= 0:
        return _fail("halted")

    price = _finite(quote.get("last")) or last_bar["close"]
    if abs(price - last_bar["close"]) / last_bar["close"] > 0.03:
        price = last_bar["close"]
    if price < cfg.min_price:
        return _fail("price below minimum")

    fraction = max(cfg.min_session_fraction, min(1.0, float(session_fraction or 0)))
    bar_dollars = sum(bar["close"] * bar["volume"] for bar in today)
    quoted_dollars = _finite(quote.get("dollarVolume"))
    liquidity = quoted_dollars if quoted_dollars is not None else bar_dollars
    if liquidity < cfg.min_dollar_volume * fraction:
        return _fail("illiquid")

    bid = _finite(quote.get("bid"))
    ask = _finite(quote.get("ask"))
    spread_pct = None
    if bid is not None and ask is not None and ask >= bid and price > 0:
        spread_pct = (ask - bid) / price
        if spread_pct > cfg.max_spread_pct:
            return _fail("wide spread")

    if spy_state == "falling" or qqq_state == "falling":
        return _fail("market falling")
    if sector_state == "falling":
        return _fail("sector falling")

    closes = [bar["close"] for bar in rth]
    ema = _ema(closes, cfg.ema_period)
    rsi = _rsi(closes, cfg.rsi_period)
    atr = _atr(rth, cfg.atr_period)
    k_line, d_line = _stoch(rth, cfg.stoch_period, cfg.stoch_smooth)
    atr_now = atr[-1]
    if atr_now is None or atr_now <= price * 0.00005:
        return _fail("atr unavailable")

    # Session high must print before the trough, so this is a dip and not a breakout.
    trough_offset = min(range(len(today) - 2), key=lambda index: today[index]["low"])
    if trough_offset < 2:
        return _fail("no established selloff")
    trough_index = today_start + trough_offset
    pre_highs = today[:trough_offset]
    session_high = max(bar["high"] for bar in pre_highs)
    trough_low = today[trough_offset]["low"]
    pullback = session_high - trough_low
    # ATR at the trough, so a later quiet drift does not inflate the dip.
    atr_dip = atr[trough_index] or atr_now
    pullback_atr = pullback / atr_dip
    pullback_pct = pullback / session_high * 100.0 if session_high else 0.0
    if pullback_atr < cfg.min_pullback_atr or pullback_pct < cfg.min_pullback_pct:
        return _fail("pullback too shallow", pullback_atr=round(pullback_atr, 2))
    if pullback_atr > cfg.max_pullback_atr:
        return _fail("pullback too deep", pullback_atr=round(pullback_atr, 2))

    bounce_atr = (price - trough_low) / atr_now
    if bounce_atr < cfg.min_bounce_atr or price <= trough_low:
        return _fail("no bounce yet")
    if price >= session_high - atr_now * 0.15:
        return _fail("back at the high")

    vwap: list[float | None] = [None] * len(rth)
    pv = 0.0
    vol = 0.0
    for index in range(today_start, len(rth)):
        bar = rth[index]
        typical = (bar["high"] + bar["low"] + bar["close"]) / 3.0
        vol += bar["volume"]
        pv += typical * bar["volume"]
        if vol > 0:
            vwap[index] = pv / vol

    vwap_now = vwap[-1]
    if vwap_now is not None and (price - vwap_now) / atr_now > cfg.max_extension_atr:
        return _fail("extended above VWAP")

    def last_cross(predicate) -> int | None:
        found = None
        for index in range(max(today_start + 1, trough_index + 1), len(rth)):
            if predicate(index):
                found = index
        return found

    vwap_index = last_cross(
        lambda index: vwap[index] is not None
        and vwap[index - 1] is not None
        and rth[index - 1]["close"] < vwap[index - 1]
        and rth[index]["close"] >= vwap[index]
    )
    ema_index = last_cross(
        lambda index: ema[index] is not None
        and ema[index - 1] is not None
        and rth[index - 1]["close"] < ema[index - 1]
        and rth[index]["close"] >= ema[index]
    )
    rsi_index = last_cross(
        lambda index: rsi[index] is not None
        and rsi[index - 1] is not None
        and rsi[index - 1] <= cfg.rsi_oversold
        and rsi[index] > cfg.rsi_oversold
    )
    stoch_index = last_cross(
        lambda index: k_line[index] is not None
        and k_line[index - 1] is not None
        and d_line[index] is not None
        and k_line[index - 1] <= cfg.stoch_oversold
        and k_line[index] > k_line[index - 1]
        and k_line[index] > d_line[index]
    )

    hl_index = None
    hl_price = None
    for index in range(trough_index + 2, len(rth) - 1):
        if rth[index]["low"] <= rth[index - 1]["low"] and rth[index]["low"] <= rth[index + 1]["low"]:
            if rth[index]["low"] > trough_low:
                hl_index = index
                hl_price = rth[index]["low"]
    if hl_index is None:
        for index in range(trough_index + 3, len(rth)):
            if (
                rth[index]["low"] >= rth[index - 1]["low"] >= rth[index - 2]["low"]
                and rth[index - 2]["low"] > trough_low
            ):
                hl_index = index
                hl_price = rth[index - 2]["low"]
                break

    # A reclaim that has already failed is not a confirm anymore.
    if vwap_index is not None and vwap_now is not None and price < vwap_now - 0.1 * atr_now:
        vwap_index = None
    if ema_index is not None and ema[-1] is not None and price < ema[-1] - 0.1 * atr_now:
        ema_index = None

    confirms: list[tuple[int, str, float]] = []
    if hl_index is not None:
        confirms.append((hl_index, "Higher low", cfg.w_higher_low))
    if vwap_index is not None:
        confirms.append((vwap_index, "Reclaimed VWAP", cfg.w_vwap))
    if ema_index is not None:
        confirms.append((ema_index, "Reclaimed 9 EMA", cfg.w_ema))
    if rsi_index is not None:
        confirms.append((rsi_index, "RSI turned up", cfg.w_rsi))
    if stoch_index is not None:
        confirms.append((stoch_index, "Stoch turned up", cfg.w_stoch))
    if len(confirms) < cfg.min_confirms:
        return _fail("reversal not confirmed", confirms=len(confirms))

    ordered = sorted(confirms, key=lambda item: item[0])
    completion = ordered[1][0]
    age = len(rth) - 1 - completion
    if age > cfg.max_trigger_age_bars:
        return _fail("stale trigger", age=age)
    if price < (hl_price if hl_price is not None else trough_low):
        return _fail("rebound low broken")

    bounce_bars = rth[trough_index:]
    up_vol = sum(bar["volume"] for bar in bounce_bars if bar["close"] >= bar["open"])
    down_vol = sum(bar["volume"] for bar in bounce_bars if bar["close"] < bar["open"])
    if down_vol <= 0:
        vol_ratio = 3.0 if up_vol > 0 else 0.0
    else:
        vol_ratio = up_vol / down_vol
    rvol = _finite(quote.get("rvol"))
    volume_ok = vol_ratio >= cfg.up_volume_ratio or (rvol is not None and rvol >= cfg.min_rvol_gate)
    if not volume_ok:
        return _fail("volume not confirming", vol_ratio=round(vol_ratio, 2))

    rebound_low = hl_price if hl_price is not None else min(bar["low"] for bar in rth[trough_index : trough_index + 2])
    stop = rebound_low - max(0.01, cfg.stop_atr_buffer * atr_now)
    entry_high = price
    anchors = [price]
    if vwap_now is not None and stop < vwap_now <= price:
        anchors.append(vwap_now)
    if ema[-1] is not None and stop < ema[-1] <= price:
        anchors.append(ema[-1])
    entry_low = min(anchors)
    if entry_high - entry_low < price * 0.0008:
        entry_low = max(stop, price - 0.18 * atr_now)
    entry_low = min(entry_high, max(stop, entry_low))
    if stop >= entry_low:
        stop = entry_low - max(0.01, 0.2 * atr_now)
    risk = entry_high - stop
    if risk <= price * 0.0004:
        return _fail("risk too tight")

    room = session_high - entry_high
    measured = 0.55 * (session_high - trough_low)
    target = entry_high + max(cfg.min_rr * risk, min(room, measured))
    target = min(session_high, target)
    reward = target - entry_high
    reward_risk = reward / risk if risk else 0.0
    if reward_risk < cfg.min_rr - 1e-9:
        return _fail("reward to risk too low", rr=round(reward_risk, 2))

    # Sweet spot near ~6 ATR; shallow and exhausted dips score less.
    if pullback_atr <= cfg.sweet_pullback_atr:
        span = max(0.01, cfg.sweet_pullback_atr - cfg.min_pullback_atr)
        pull_t = (pullback_atr - cfg.min_pullback_atr) / span
    else:
        span = max(0.01, cfg.max_pullback_atr - cfg.sweet_pullback_atr)
        pull_t = (cfg.max_pullback_atr - pullback_atr) / span
    pull_pts = cfg.w_pullback * max(0.0, min(1.0, pull_t))
    confirm_pts = min(cfg.w_confirm_cap, sum(item[2] for item in confirms))
    vol_pts = min(10.0, max(0.0, vol_ratio - 1.0) * 8.0)
    if rvol is not None and rvol >= 1.2:
        vol_pts += min(6.0, (rvol - 1.0) * 3.5)
    vol_pts = min(cfg.w_volume, vol_pts)
    context_pts = 0.0
    context_bits = []
    if spy_state == "firm":
        context_pts += 4.0
        context_bits.append("SPY")
    if qqq_state == "firm":
        context_pts += 4.0
        context_bits.append("QQQ")
    if sector_state == "firm":
        context_pts += 4.0
    context_pts = min(cfg.w_context, context_pts)
    fresh_pts = {0: cfg.w_fresh, 1: 9.0, 2: 5.0, 3: 2.0}.get(age, 0.0)
    quality_pts = 2.0
    if spread_pct is not None and spread_pct <= cfg.max_spread_pct * 0.45:
        quality_pts += 3.0
    elif spread_pct is not None:
        quality_pts += 1.0
    if liquidity >= cfg.min_dollar_volume * fraction * 2:
        quality_pts += 3.0
    quality_pts = min(cfg.w_quality, quality_pts)
    rr_pts = min(cfg.w_rr, max(0.0, reward_risk - 1.1) * 5.0)
    score = min(100.0, pull_pts + confirm_pts + vol_pts + context_pts + fresh_pts + quality_pts + rr_pts)

    reasons = [f"Pulled back {pullback_atr:.1f} ATR"]
    have = {label for _index, label, _weight in confirms}
    if "Reclaimed VWAP" in have:
        reasons.append("Reclaimed VWAP")
    elif "Reclaimed 9 EMA" in have:
        reasons.append("Reclaimed 9 EMA")
    if rvol is not None and rvol >= 1.2:
        reasons.append(f"RVOL {rvol:.1f}×")
    for label in ("Higher low", "RSI turned up", "Stoch turned up"):
        if label in have:
            reasons.append(label)
    reasons.append(f"Up-volume {vol_ratio:.1f}×")
    if len(context_bits) == 2:
        reasons.append("SPY & QQQ holding")
    elif context_bits:
        reasons.append(f"{context_bits[0]} holding")
    if sector_state == "firm" and sector_etf:
        reasons.append(f"{sector_etf} holding")

    trigger_bar = rth[completion]
    ago = max(0, int(last_bar["t"] - trigger_bar["t"]))
    signal = EntrySignal(
        symbol=symbol,
        score=score,
        reasons=reasons[:7],
        entry_low=_px(entry_low),
        entry_high=_px(entry_high),
        stop=_px(stop),
        target=_px(target),
        reward_risk=round(reward_risk, 2),
        triggered_bars=age,
        triggered_ago_sec=ago,
        last=_px(price),
        pullback_atr=pullback_atr,
        vwap=_px(vwap_now) if vwap_now else None,
        atr=_px(atr_now),
    )
    return {
        "ok": score + 1e-9 >= cfg.min_score,
        "fail": None if score >= cfg.min_score else "below threshold",
        "signal": signal if score >= cfg.min_score else None,
        "score": round(score, 2),
        "age": age,
        "pullback_atr": round(pullback_atr, 2),
        "reasons": reasons,
    }


def evaluate_entry(
    bars: list[dict[str, Any]] | None,
    quote: dict[str, Any] | None = None,
    **kwargs: Any,
) -> EntrySignal | None:
    found = diagnose_entry(bars, quote, **kwargs)
    signal = found.get("signal")
    return signal if found.get("ok") and isinstance(signal, EntrySignal) else None


def screen_entries(
    books: dict[str, list[dict[str, Any]]],
    quotes: dict[str, dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
    session_fraction: float = 0.5,
    enforce_clock: bool = True,
    cfg: EntryConfig = ENTRY,
    score_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Rank the universe. Context ETFs are never themselves buy candidates."""
    quotes = quotes or {}
    spy_state = market_state(books.get("SPY"), cfg)
    qqq_state = market_state(books.get("QQQ"), cfg)
    blocked = spy_state == "falling" or qqq_state == "falling"
    context = set(context_symbols())
    wanted = score_symbols
    signals: list[EntrySignal] = []
    if not blocked:
        symbols = wanted if wanted is not None else list(books)
        for symbol in symbols:
            if symbol in context or symbol in _CONTEXT_ALWAYS:
                continue
            bars = books.get(symbol)
            if not bars:
                continue
            sector = sector_etf_for(symbol)
            sector_bars = books.get(sector) if sector else None
            quote = dict(quotes.get(symbol) or {})
            quote.setdefault("symbol", symbol)
            signal = evaluate_entry(
                bars,
                quote,
                now=now,
                session_fraction=session_fraction,
                enforce_clock=enforce_clock,
                spy_state=spy_state,
                qqq_state=qqq_state,
                sector_state=market_state(sector_bars, cfg) if sector else "unknown",
                sector_etf=sector,
                cfg=cfg,
            )
            if signal is not None:
                if not signal.symbol:
                    signal.symbol = symbol
                signals.append(signal)
    signals.sort(key=lambda item: (-item.score, item.symbol))
    selected = signals[: cfg.top_n]
    if blocked:
        note = "No fresh long entries — SPY or QQQ is falling, so dips are not buyable yet."
    elif not selected:
        note = "No name is at a fresh long entry on this tape. A setup leaves the list as soon as it goes stale or breaks."
    else:
        note = f"{len(selected)} setup{'s' if len(selected) != 1 else ''} above {int(cfg.min_score)}."
    return {
        "signals": selected,
        "note": note,
        "blocked": blocked,
        "spy": spy_state,
        "qqq": qqq_state,
        "threshold": cfg.min_score,
        "topN": cfg.top_n,
    }


# --- Synthetic books (tests + demo). Deterministic, no broker. ---

_DEMO_DAY = date(2026, 9, 28)
_PRIOR_DAY = date(2026, 9, 25)


def _path_rows(start: float, closes: list[float], volume_for) -> list[tuple[float, float, float, float, float]]:
    rows = []
    prev = start
    for index, close in enumerate(closes):
        open_px = prev
        wick = max(0.035, abs(close - open_px) * 0.22)
        high = max(open_px, close) + wick
        low = min(open_px, close) - wick * 0.85
        rows.append((open_px, high, low, close, float(volume_for(index, open_px, close))))
        prev = close
    return rows


def _stamp(day: date, rows: list[tuple[float, float, float, float, float]]) -> list[dict[str, Any]]:
    start = datetime(day.year, day.month, day.day, 9, 30, tzinfo=NY)
    out = []
    for index, (open_px, high, low, close, volume) in enumerate(rows):
        moment = start + timedelta(minutes=5 * index)
        out.append(
            {
                "t": int(moment.timestamp()),
                "open": round(open_px, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close, 4),
                "volume": volume,
            }
        )
    return out


def _prior_chop(day: date = _PRIOR_DAY, seed: int = 7) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    price = 100.0
    closes = []
    for _ in range(54):
        price = min(100.7, max(99.25, price + rng.uniform(-0.2, 0.2)))
        closes.append(round(price, 4))
    return _stamp(day, _path_rows(100.0, closes, lambda *_args: 42000))


def _scale(bars: list[dict[str, Any]], last_price: float) -> list[dict[str, Any]]:
    anchor = bars[-1]["close"] or 1.0
    factor = last_price / anchor
    scaled = []
    for bar in bars:
        item = {
            "t": bar["t"],
            "volume": bar["volume"],
        }
        for key in ("open", "high", "low", "close"):
            item[key] = round(float(bar[key]) * factor, 4)
        scaled.append(item)
    return scaled


def bars_clear_rebound(last_price: float = 100.0) -> list[dict[str, Any]]:
    """Selloff of several ATR, then a higher low and a fresh turn back up."""
    closes = [
        100.15, 100.55, 101.05, 101.55, 102.05, 102.45, 102.7,
        102.25, 101.45, 100.65, 99.95, 99.4, 99.05, 98.85,
        99.05, 98.98, 99.35, 99.85, 100.4,
    ]

    def volume(_index: int, open_px: float, close: float) -> float:
        if _index <= 6:
            return 9000
        if close < open_px:
            return 78000
        return 110000

    today = _stamp(_DEMO_DAY, _path_rows(100.0, closes, volume))
    book = _prior_chop() + today
    return book if abs(last_price - book[-1]["close"]) < 1e-6 else _scale(book, last_price)


def bars_downtrend(last_price: float = 100.0) -> list[dict[str, Any]]:
    closes = [100.0 - i * 0.28 for i in range(1, 22)]
    today = _stamp(_DEMO_DAY, _path_rows(100.0, closes, lambda *_args: 60000))
    book = _prior_chop(seed=3) + today
    return book if abs(last_price - 100) < 1e-9 else _scale(book, last_price)


def bars_stale_rebound(last_price: float = 100.0) -> list[dict[str, Any]]:
    """Same rebound, then a drift that leaves the trigger several bars behind."""
    base = bars_clear_rebound(100.0)
    last = base[-1]
    moment = datetime.fromtimestamp(last["t"], NY)
    price = last["close"]
    extra = []
    # Stay parked just after the trigger so the dip is still valid, but the
    # confirmation bar is no longer fresh and price does not re-cross VWAP.
    drifts = [0.02, -0.015, 0.01, -0.01, 0.015, -0.01, 0.01, -0.005]
    for offset, drift in enumerate(drifts, start=1):
        open_px = price
        price = price + drift
        stamp = moment + timedelta(minutes=5 * offset)
        extra.append(
            {
                "t": int(stamp.timestamp()),
                "open": round(open_px, 4),
                "high": round(max(open_px, price) + 0.04, 4),
                "low": round(min(open_px, price) - 0.03, 4),
                "close": round(price, 4),
                "volume": 22000,
            }
        )
    book = base + extra
    return book if abs(last_price - book[-1]["close"]) < 1e-6 else _scale(book, last_price)


def bars_firm(last_price: float = 500.0) -> list[dict[str, Any]]:
    closes = [100 + i * 0.04 for i in range(1, 23)]
    today = _stamp(_DEMO_DAY, _path_rows(100.0, closes, lambda *_args: 80000))
    book = _prior_chop(seed=11) + today
    return _scale(book, last_price)


def bars_falling(last_price: float = 500.0) -> list[dict[str, Any]]:
    closes = [100.0] * 12 + [100 - i * 0.18 for i in range(1, 11)]
    today = _stamp(_DEMO_DAY, _path_rows(100.2, closes, lambda *_args: 80000))
    book = _prior_chop(seed=13) + today
    return _scale(book, last_price)


def liquid_quote(
    symbol: str,
    bars: list[dict[str, Any]],
    *,
    spread_pct: float = 0.00015,
    dollar_volume: float | None = None,
    rvol: float = 2.2,
    halted: int = 0,
) -> dict[str, Any]:
    last = float(bars[-1]["close"])
    half = last * spread_pct / 2.0
    if dollar_volume is None:
        dollar_volume = max(last * 2_500_000, 25_000_000.0)
    return {
        "symbol": symbol,
        "last": last,
        "bid": round(last - half, 4),
        "ask": round(last + half, 4),
        "dollarVolume": dollar_volume,
        "rvol": rvol,
        "halted": halted,
        "volume": dollar_volume / last if last else 0,
        "avgVolume": (dollar_volume / last) / max(rvol, 0.1) if last else 0,
    }


def demo_as_of() -> datetime:
    """Clock matching the synthetic session, for tests that enforce the window."""
    probe = bars_clear_rebound()
    return datetime.fromtimestamp(probe[-1]["t"], NY) + timedelta(seconds=20)


def build_demo_board() -> dict[str, Any]:
    """A few live-looking rebounds plus names that must stay off the list."""
    specs: list[tuple[str, list[dict[str, Any]], dict[str, Any]]] = []

    def add(symbol: str, bars: list[dict[str, Any]], **quote_kw: Any) -> None:
        specs.append((symbol, bars, liquid_quote(symbol, bars, **quote_kw)))

    add("NVDA", bars_clear_rebound(118.4), rvol=3.4)
    add("AMD", bars_clear_rebound(162.2), rvol=2.6)
    add("JPM", bars_clear_rebound(214.5), rvol=1.8)
    add("TSLA", bars_downtrend(248.0), rvol=1.7)
    add("PLTR", bars_stale_rebound(28.4), rvol=2.4)
    add("INTC", bars_clear_rebound(22.4), spread_pct=0.012, rvol=1.5)
    add("SOFI", bars_clear_rebound(14.2), dollar_volume=80_000, rvol=0.4)

    books: dict[str, list[dict[str, Any]]] = {symbol: bars for symbol, bars, _quote in specs}
    quotes: dict[str, dict[str, Any]] = {symbol: quote for symbol, _bars, quote in specs}
    books["SPY"] = bars_firm(562.0)
    books["QQQ"] = bars_firm(478.0)
    for etf, price in (("SMH", 268.0), ("XLF", 48.0), ("XLK", 232.0)):
        books[etf] = bars_firm(price)
    screened = screen_entries(
        books,
        quotes,
        now=demo_as_of(),
        session_fraction=0.42,
        enforce_clock=False,
        score_symbols=[item[0] for item in specs],
    )
    rows = []
    by_quote = quotes
    for signal in screened["signals"]:
        quote = by_quote[signal.symbol]
        last = signal.last
        series = _clean_bars(books[signal.symbol])
        rth = [bar for bar in series if _rth(bar["dt"])]
        prior = [bar for bar in rth if bar["dt"].date() < rth[-1]["dt"].date()] if rth else []
        close = prior[-1]["close"] if prior else last
        opened = rth[0]["open"] if rth else last
        row = {
            "symbol": signal.symbol,
            "rank": 0,
            "last": last,
            "open": _px(opened),
            "close": _px(close),
            "change": round(last - close, 4),
            "changePct": ((last - close) / close * 100.0) if close else 0.0,
            "bid": quote["bid"],
            "ask": quote["ask"],
            "spread": round(quote["ask"] - quote["bid"], 4),
            "volume": quote["volume"],
            "avgVolume": quote["avgVolume"],
            "rvol": quote["rvol"],
            "pace": quote["rvol"] / 0.42,
            "volumeRate": quote["volume"] / 180,
            "tradeRate": 40,
            "lastSize": 200,
            "high": round(last * 1.025, 2),
            "low": round(signal.stop * 1.002, 2),
            "vwap": round((signal.entry_low + signal.entry_high) / 2, 2),
            "dollarVolume": quote["dollarVolume"],
            "simulated": True,
            "halted": 0,
        }
        row.update(signal.as_row())
        rows.append(row)
    for index, row in enumerate(rows):
        row["rank"] = index
    return {
        "rows": rows,
        "note": screened["note"],
        "spy": screened["spy"],
        "qqq": screened["qqq"],
        "threshold": screened["threshold"],
        "topN": screened["topN"],
        "books": books,
    }


def retune(**changes: Any) -> EntryConfig:
    return replace(ENTRY, **changes)
