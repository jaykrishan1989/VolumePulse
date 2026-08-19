"""IBKR Gateway feed: scanner + streaming market data."""

from __future__ import annotations

import asyncio
import math
import os
import random
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

try:
    from ib_insync import IB, ScannerSubscription, Stock
except ImportError:  # maintained fork
    from ib_async import IB, ScannerSubscription, Stock  # type: ignore

try:
    NY = ZoneInfo("America/New_York")
except Exception:
    from datetime import timezone, timedelta

    NY = timezone(timedelta(hours=-4), "EDT")

from app.sp500 import LIQUID_SP500, ib_symbol, is_sp500

SCAN_CODES = {
    "sp500": "HOT_BY_VOLUME",
    "hot_volume": "HOT_BY_VOLUME",
    "most_active": "MOST_ACTIVE",
    "top_percent_gain": "TOP_PERC_GAIN",
    "top_percent_lose": "TOP_PERC_LOSE",
}

# Liquid fallback if the scanner is unavailable (no market-data entitlement).
FALLBACK_SYMBOLS = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO",
    "AMD", "NFLX", "ORCL", "PLTR", "INTC", "MU", "SMCI", "ARM",
    "JPM", "BAC", "GS", "V", "MA",
    "XOM", "CVX", "UNH", "LLY", "COST", "WMT",
    "COIN", "MSTR", "UBER", "ABNB", "SHOP", "SQ", "SOFI", "NKE",
]

GENERIC_TICKS = "165,233,293,294,295"
INFORMATIONAL_ERRORS = {
    162, 2103, 2104, 2105, 2106, 2107, 2108, 2119, 2158,
    2100, 2110, 354, 365, 366, 10089, 10091, 10167, 10197,
}


def _is_informational_error(text: str | None) -> bool:
    if not text:
        return True
    code = text.split(":", 1)[0].strip()
    return code.isdigit() and int(code) in INFORMATIONAL_ERRORS


def finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def clean_price(value: Any) -> float | None:
    number = finite(value)
    if number is None or number <= 0:
        return None
    return number


def clean_size(value: Any) -> float | None:
    number = finite(value)
    if number is None or number < 0:
        return None
    return number


def pick_share_volume(quote: float | None, bar: float | None, avg: float | None) -> float | None:
    """Delayed IBKR quote volume is sometimes inflated by ~1e6; prefer bar volume then."""
    max_shares = 2_500_000_000.0

    def ok(value: float | None) -> bool:
        if value is None or value <= 0 or value > max_shares:
            return False
        if avg and avg > 0 and value / avg > 50:
            return False
        return True

    if ok(quote):
        return quote
    if ok(bar):
        return bar
    if quote and quote > max_shares:
        scaled = quote / 1_000_000.0
        if ok(scaled):
            return scaled
    return bar or quote


def to_et(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=NY)
        return value.astimezone(NY)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), NY)
    return None


def bar_session(moment: datetime) -> str:
    minutes = moment.hour * 60 + moment.minute
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "regular"
    if 16 * 60 <= minutes < 20 * 60:
        return "afterhours"
    if minutes < 4 * 60 or minutes >= 20 * 60:
        return "overnight"
    return "premarket"


def summarize_bars(bars: Any) -> dict[str, Any]:
    parsed: list[tuple[datetime, float, float | None]] = []
    for bar in bars or []:
        moment = to_et(getattr(bar, "date", None))
        if moment is None:
            continue
        price = clean_price(getattr(bar, "close", None))
        volume = clean_size(getattr(bar, "volume", None)) or 0.0
        parsed.append((moment, volume, price))
    if not parsed:
        return {}

    last_rth_i = None
    for i, (moment, _volume, price) in enumerate(parsed):
        if bar_session(moment) == "regular" and price is not None:
            last_rth_i = i
    rth_close = parsed[last_rth_i][2] if last_rth_i is not None else None
    start = 0 if last_rth_i is None else last_rth_i + 1
    ext_volume = sum(item[1] for item in parsed[start:])
    rth_volume = 0.0
    if last_rth_i is not None:
        rth_date = parsed[last_rth_i][0].date()
        rth_volume = sum(
            volume
            for moment, volume, _price in parsed
            if bar_session(moment) == "regular" and moment.date() == rth_date
        )
    last = parsed[-1][2]
    last_minutes = 1.0
    if len(parsed) >= 2:
        last_minutes = max(1.0, (parsed[-1][0] - parsed[-2][0]).total_seconds() / 60)
    recent_volume = parsed[-1][1]
    return {
        "last": last,
        "rthClose": rth_close,
        "rthVolume": rth_volume or None,
        "extVolume": ext_volume or None,
        "volumeRate": recent_volume / last_minutes if recent_volume else None,
        "barTime": parsed[-1][0].isoformat(),
    }


def session_info() -> dict[str, Any]:
    now = datetime.now(NY)
    minutes = now.hour * 60 + now.minute
    weekday = now.weekday()
    open_m, close_m = 9 * 60 + 30, 16 * 60
    if weekday == 5 or (weekday == 6 and minutes < 20 * 60):
        label = "weekend"
        fraction = 1.0
    elif minutes < 4 * 60 or minutes >= 20 * 60:
        label = "overnight"
        fraction = 1.0
    elif minutes < open_m:
        label = "premarket"
        fraction = 0.05
    elif minutes < close_m:
        label = "regular"
        elapsed = (minutes - open_m) + now.second / 60
        fraction = max(0.02, min(1.0, elapsed / 390))
    else:
        label = "afterhours"
        fraction = 1.0
    return {
        "label": label,
        "fraction": fraction,
        "nyTime": now.strftime("%H:%M:%S"),
        "nyDate": now.strftime("%Y-%m-%d"),
        "extended": label in ("premarket", "afterhours", "overnight"),
    }


class VolumeFeed:
    def __init__(self) -> None:
        self.host = os.environ.get("IBKR_HOST", "127.0.0.1")
        self.port = int(os.environ.get("IBKR_PORT", "4001"))
        self.client_id = int(os.environ.get("IBKR_CLIENT_ID", "7"))
        self.scan_key = os.environ.get("IBKR_SCAN", "sp500")
        self.row_count = int(os.environ.get("IBKR_ROWS", "30"))
        self.requested_data_type = int(os.environ.get("IBKR_MKT_DATA_TYPE", "3"))

        self.ib: IB | None = None

        self.connected = False
        self.mode = "connecting"
        self.last_error: str | None = None
        self.client_id_in_use: int | None = None
        self.market_data_type: int | None = None
        self.using_scanner = False
        self.last_scan_at: float | None = None
        self.farms: list[str] = []
        self._resubscribe = False

        self.tickers: dict[str, Any] = {}
        self.contracts: dict[str, Any] = {}
        self.ranks: dict[str, int] = {}
        self.bar_lists: dict[str, Any] = {}
        self.bar_stats: dict[str, dict[str, Any]] = {}
        self._hist_keep_up = True
        self._hist_cursor = 0
        self.history: dict[str, deque] = defaultdict(lambda: deque(maxlen=90))
        self.prev_print: dict[str, tuple] = {}
        self.prints: deque = deque(maxlen=40)
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()

        self._demo_state: dict[str, dict[str, float]] = {}

    def _on_error(self, req_id: int, code: int, message: str, contract: Any) -> None:
        text = f"{code}: {message}"
        symbol = getattr(contract, "symbol", None)
        if symbol:
            text += f" ({symbol})"
        if code in INFORMATIONAL_ERRORS:
            if code == 10167:
                self.market_data_type = 3
            if code in (10089, 354) and self.ib:
                self.market_data_type = 3
                try:
                    self.ib.reqMarketDataType(3)
                    self._resubscribe = True
                except Exception:
                    pass
            note = f"{code}: {message}"
            if note not in self.farms:
                self.farms.append(note)
                self.farms = self.farms[-8:]
            return
        if code in (1100, 2110, 504, 502, 326, 10182, 1300):
            self.last_error = text
            if code in (1100, 504, 502, 1300):
                self.connected = False
        elif code not in (2104, 2106, 2158):
            self.last_error = text

    def is_connected(self) -> bool:
        return bool(self.ib and self.ib.isConnected())

    def _bind_loop(self) -> None:
        asyncio.set_event_loop(asyncio.get_running_loop())

    def _new_client(self) -> None:
        self._disconnect()
        self._bind_loop()
        self.ib = IB()
        self.ib.errorEvent += self._on_error

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._ensure_connected()
                if not self.is_connected():
                    await asyncio.sleep(4)
                    continue
                await self._refresh_universe()
                if not self._hist_keep_up:
                    await self._poll_history()
                    await self._poll_history()
                for _ in range(20):
                    if self._stop.is_set() or not self.is_connected():
                        break
                    if self._resubscribe:
                        self._resubscribe = False
                        await self._refresh_universe(force=True)
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.last_error = str(exc)
                self.connected = False
                self.mode = "demo"
                await asyncio.sleep(4)
        self._disconnect()

    async def stop(self) -> None:
        self._stop.set()
        self._disconnect()

    def _disconnect(self) -> None:
        try:
            if self.ib and self.ib.isConnected():
                self.ib.disconnect()
        except Exception:
            pass
        self.connected = False

    async def _ensure_connected(self) -> None:
        self._bind_loop()
        if self.is_connected():
            self.connected = True
            self.mode = "live"
            return

        self.mode = "connecting"
        last_exc: Exception | None = None
        start_id = self.client_id
        for offset in range(8):
            client_id = start_id + offset
            self._new_client()
            try:
                await self.ib.connectAsync(
                    self.host,
                    self.port,
                    clientId=client_id,
                    readonly=True,
                    timeout=6,
                )
                self.ib.reqMarketDataType(self.requested_data_type)
                self.market_data_type = self.requested_data_type
                self.connected = True
                self.mode = "live"
                self.client_id_in_use = client_id
                self.last_error = None
                return
            except Exception as exc:
                last_exc = exc
                self._disconnect()
                await asyncio.sleep(0.3)

        self.connected = False
        self.mode = "demo"
        self.last_error = (
            f"Could not reach IBKR Gateway at {self.host}:{self.port}. "
            f"{last_exc or 'Is the Gateway running with API socket enabled?'}"
        )

    async def set_scan(self, scan_key: str) -> None:
        if scan_key not in SCAN_CODES:
            raise ValueError(f"Unknown scan '{scan_key}'")
        self.scan_key = scan_key
        if self.is_connected():
            await self._refresh_universe()

    async def _sp500_universe(self) -> tuple[list[str], dict[str, int], bool]:
        scanned: list[str] = []
        seen: set[str] = set()
        for scan_code in ("HOT_BY_VOLUME", "MOST_ACTIVE"):
            try:
                sub = ScannerSubscription(
                    instrument="STK",
                    locationCode="STK.US.MAJOR",
                    scanCode=scan_code,
                    numberOfRows=50,
                    abovePrice=15,
                    stockTypeFilter="CORP",
                )
                rows = await self.ib.reqScannerDataAsync(sub)
                for item in rows:
                    raw = item.contractDetails.contract.symbol
                    if not raw or not is_sp500(raw) or ib_symbol(raw) in seen:
                        continue
                    symbol = ib_symbol(raw)
                    seen.add(symbol)
                    scanned.append(symbol)
            except Exception:
                continue

        merged: list[str] = []
        used: set[str] = set()
        for symbol in scanned + [ib_symbol(item) for item in LIQUID_SP500]:
            if symbol in used:
                continue
            used.add(symbol)
            merged.append(symbol)
            if len(merged) >= self.row_count:
                break
        ranks = {symbol: index for index, symbol in enumerate(merged)}
        return merged, ranks, bool(scanned)

    async def _refresh_universe(self, force: bool = False) -> None:
        if not self.is_connected():
            return
        symbols: list[str] = []
        ranks: dict[str, int] = {}
        self.using_scanner = False
        try:
            if self.scan_key == "sp500":
                symbols, ranks, self.using_scanner = await self._sp500_universe()
            else:
                sub = ScannerSubscription(
                    instrument="STK",
                    locationCode="STK.US.MAJOR",
                    scanCode=SCAN_CODES.get(self.scan_key, "HOT_BY_VOLUME"),
                    numberOfRows=self.row_count,
                )
                if session_info()["label"] == "regular":
                    sub.abovePrice = 1
                rows = await self.ib.reqScannerDataAsync(sub)
                for item in rows:
                    contract = item.contractDetails.contract
                    symbol = contract.symbol
                    if not symbol or symbol in ranks:
                        continue
                    ranks[symbol] = int(item.rank)
                    symbols.append(symbol)
                if symbols:
                    self.using_scanner = True
        except Exception as exc:
            self.last_error = f"Scanner failed ({exc}). Ranking liquid names by live volume instead."

        if not symbols:
            if self.scan_key == "sp500":
                symbols = [ib_symbol(sym) for sym in LIQUID_SP500[: self.row_count]]
            else:
                symbols = FALLBACK_SYMBOLS[: self.row_count]
            ranks = {sym: i for i, sym in enumerate(symbols)}

        async with self._lock:
            await self._sync_subscriptions(symbols, ranks, force=force)
            self.last_scan_at = time.time()

    async def _sync_subscriptions(
        self, symbols: list[str], ranks: dict[str, int], force: bool = False
    ) -> None:
        wanted = set(symbols)
        for symbol in list(self.tickers):
            if force or symbol not in wanted:
                try:
                    self.ib.cancelMktData(self.contracts[symbol])
                except Exception:
                    pass
                self._drop_history(symbol)
                self.tickers.pop(symbol, None)
                self.contracts.pop(symbol, None)
                if symbol not in wanted:
                    self.ranks.pop(symbol, None)

        for symbol in symbols:
            self.ranks[symbol] = ranks.get(symbol, 99)
            if symbol not in self.tickers:
                contract = Stock(ib_symbol(symbol), "SMART", "USD")
                try:
                    ticker = self.ib.reqMktData(contract, GENERIC_TICKS, False, False)
                except Exception:
                    ticker = self.ib.reqMktData(contract, "", False, False)
                self.contracts[symbol] = contract
                self.tickers[symbol] = ticker
            if symbol not in self.bar_lists and len(self.bar_lists) < 20:
                await self._subscribe_history(symbol)
                await asyncio.sleep(0.15)

    def _drop_history(self, symbol: str) -> None:
        bars = self.bar_lists.pop(symbol, None)
        self.bar_stats.pop(symbol, None)
        if bars is None or not self.ib:
            return
        try:
            self.ib.cancelHistoricalData(bars)
        except Exception:
            pass

    async def _subscribe_history(self, symbol: str) -> None:
        contract = self.contracts.get(symbol)
        if not contract or not self.ib:
            return
        try:
            bars = await asyncio.wait_for(
                self.ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr="1 D",
                    barSizeSetting="1 min",
                    whatToShow="TRADES",
                    useRTH=False,
                    formatDate=1,
                    keepUpToDate=self._hist_keep_up,
                ),
                timeout=8,
            )
            self.bar_lists[symbol] = bars
            self.bar_stats[symbol] = summarize_bars(bars)
        except Exception:
            self._hist_keep_up = False
            try:
                bars = await asyncio.wait_for(
                    self.ib.reqHistoricalDataAsync(
                        contract,
                        endDateTime="",
                        durationStr="1 D",
                        barSizeSetting="5 mins",
                        whatToShow="TRADES",
                        useRTH=False,
                        formatDate=1,
                        keepUpToDate=False,
                    ),
                    timeout=8,
                )
                self.bar_lists[symbol] = bars
                self.bar_stats[symbol] = summarize_bars(bars)
            except Exception:
                return

    async def _poll_history(self) -> None:
        symbols = [symbol for symbol in self.tickers if symbol in self.contracts]
        if not symbols or not self.ib:
            return
        symbol = symbols[self._hist_cursor % len(symbols)]
        self._hist_cursor += 1
        contract = self.contracts[symbol]
        try:
            bars = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr="1 D",
                barSizeSetting="5 mins",
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
                keepUpToDate=False,
            )
            self.bar_lists[symbol] = bars
            self.bar_stats[symbol] = summarize_bars(bars)
        except Exception:
            return

    def snapshot(self) -> dict[str, Any]:
        session = session_info()
        if self.mode != "live" or not self.is_connected() or not self.tickers:
            return self._demo_snapshot(session)

        tickers: list[dict[str, Any]] = []
        now = time.time()
        for symbol, ticker in self.tickers.items():
            if symbol in self.bar_lists:
                self.bar_stats[symbol] = summarize_bars(self.bar_lists[symbol])
            row = self._row_from_ticker(symbol, ticker, session, now)
            tickers.append(row)
            self._capture_print(row)
            self.history[symbol].append(
                {
                    "t": now,
                    "last": row["last"],
                    "volume": row["volume"],
                    "volumeRate": row["volumeRate"],
                }
            )
            row["spark"] = [
                point["volumeRate"] if point["volumeRate"] is not None else 0
                for point in self.history[symbol]
            ]
            row["priceSpark"] = [
                point["last"] for point in self.history[symbol] if point["last"] is not None
            ]

            md_type = getattr(ticker, "marketDataType", None)
            if md_type:
                self.market_data_type = int(md_type)

        tickers.sort(key=lambda r: r.get("rank", 99))
        return {
            "mode": "live",
            "connected": True,
            "host": self.host,
            "port": self.port,
            "clientId": self.client_id_in_use,
            "scan": self.scan_key,
            "usingScanner": self.using_scanner,
            "marketDataType": self.market_data_type or 1,
            "lastError": None if _is_informational_error(self.last_error) else self.last_error,
            "farms": self.farms[-4:],
            "lastScanAt": self.last_scan_at,
            "serverTime": now,
            "session": session,
            "tickers": tickers,
            "prints": list(self.prints)[-18:],
        }

    def _row_from_ticker(self, symbol: str, ticker: Any, session: dict[str, Any], now: float) -> dict[str, Any]:
        last = clean_price(ticker.last) or clean_price(getattr(ticker, "delayedLast", None))
        prev_close = clean_price(ticker.close)
        if last is None:
            last = clean_price(ticker.marketPrice())
        bid = clean_price(ticker.bid)
        ask = clean_price(ticker.ask)
        volume = clean_size(ticker.volume)
        avg_volume = clean_size(getattr(ticker, "avVolume", None))
        volume_rate = clean_size(getattr(ticker, "volumeRate", None))
        trade_rate = clean_size(getattr(ticker, "tradeRate", None))
        last_size = clean_size(ticker.lastSize)
        high = clean_price(ticker.high)
        low = clean_price(ticker.low)
        vwap = clean_price(getattr(ticker, "vwap", None))
        high52 = clean_price(getattr(ticker, "high52week", None))
        low52 = clean_price(getattr(ticker, "low52week", None))

        ext = self.bar_stats.get(symbol) or {}
        rth_close = clean_price(ext.get("rthClose"))
        ext_volume = clean_size(ext.get("extVolume"))
        rth_volume = clean_size(ext.get("rthVolume"))
        if ext.get("last"):
            last = clean_price(ext["last"]) or last
        if ext.get("volumeRate") and not volume_rate:
            volume_rate = ext["volumeRate"]

        extended = bool(session.get("extended"))
        close = rth_close if extended and rth_close else prev_close
        if last is None:
            last = close
        if extended and ext_volume:
            volume = ext_volume
        else:
            volume = pick_share_volume(volume, rth_volume, avg_volume)

        change = None
        change_pct = None
        if last is not None and close not in (None, 0):
            change = last - close
            change_pct = (change / close) * 100

        rvol = None
        pace = None
        if volume not in (None, 0) and avg_volume not in (None, 0):
            rvol = volume / avg_volume
            if extended:
                pace = volume / (avg_volume * 0.08)
            else:
                pace = rvol / max(session.get("fraction") or 0.02, 0.02)
        elif ext_volume:
            pace = ext_volume

        dollar_volume = None
        if last is not None and volume is not None:
            dollar_volume = last * volume

        spread = None
        if bid is not None and ask is not None and ask >= bid:
            spread = ask - bid

        return {
            "symbol": symbol,
            "rank": self.ranks.get(symbol, 99),
            "last": last,
            "close": close,
            "prevClose": prev_close,
            "rthClose": rth_close,
            "change": change,
            "changePct": change_pct,
            "bid": bid,
            "ask": ask,
            "spread": spread,
            "volume": volume,
            "extVolume": ext_volume,
            "rthVolume": rth_volume,
            "avgVolume": avg_volume,
            "rvol": rvol,
            "pace": pace,
            "volumeRate": volume_rate,
            "tradeRate": trade_rate,
            "lastSize": last_size,
            "high": high,
            "low": low,
            "vwap": vwap,
            "high52": high52,
            "low52": low52,
            "dollarVolume": dollar_volume,
            "extended": extended,
            "updated": now,
        }

    def _capture_print(self, row: dict[str, Any]) -> None:
        symbol = row["symbol"]
        key = (row.get("last"), row.get("lastSize"), row.get("volume"))
        previous = self.prev_print.get(symbol)
        self.prev_print[symbol] = key
        if previous is None or key == previous:
            return
        if row.get("last") is None or row.get("lastSize") in (None, 0):
            return
        self.prints.appendleft(
            {
                "t": time.time(),
                "symbol": symbol,
                "price": row["last"],
                "size": row["lastSize"],
                "changePct": row.get("changePct"),
            }
        )

    def _demo_snapshot(self, session: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        if not self._demo_state:
            self._seed_demo()
        tickers = []
        for symbol, state in self._demo_state.items():
            if self.scan_key == "sp500" and not is_sp500(symbol):
                continue
            state["last"] += random.gauss(0, state["last"] * 0.0004)
            state["volume"] += abs(random.gauss(state["volumeRate"] / 60, state["volumeRate"] / 180))
            state["volumeRate"] = max(0, state["volumeRate"] + random.gauss(0, state["volumeRate"] * 0.05))
            if random.random() < 0.08:
                size = max(100, int(abs(random.gauss(1200, 800)) / 100) * 100)
                self.prints.appendleft(
                    {
                        "t": now,
                        "symbol": symbol,
                        "price": state["last"],
                        "size": size,
                        "changePct": (state["last"] - state["close"]) / state["close"] * 100,
                    }
                )
            change = state["last"] - state["close"]
            rvol = state["volume"] / state["avgVolume"]
            row = {
                "symbol": symbol,
                "rank": state["rank"],
                "last": state["last"],
                "close": state["close"],
                "change": change,
                "changePct": change / state["close"] * 100,
                "bid": state["last"] - 0.01,
                "ask": state["last"] + 0.01,
                "spread": 0.02,
                "volume": state["volume"],
                "avgVolume": state["avgVolume"],
                "rvol": rvol,
                "pace": rvol / max(session["fraction"], 0.02),
                "volumeRate": state["volumeRate"],
                "tradeRate": state["volumeRate"] / 400,
                "lastSize": 100,
                "high": max(state["last"], state["close"] * 1.01),
                "low": min(state["last"], state["close"] * 0.99),
                "vwap": (state["last"] + state["close"]) / 2,
                "high52": state["close"] * 1.4,
                "low52": state["close"] * 0.7,
                "dollarVolume": state["last"] * state["volume"],
                "simulated": True,
                "extended": bool(session.get("extended")),
                "updated": now,
            }
            self.history[symbol].append(
                {"t": now, "last": row["last"], "volume": row["volume"], "volumeRate": row["volumeRate"]}
            )
            row["spark"] = [p["volumeRate"] for p in self.history[symbol]]
            row["priceSpark"] = [p["last"] for p in self.history[symbol]]
            tickers.append(row)

        tickers.sort(key=lambda r: -(r["pace"] or 0))
        for i, row in enumerate(tickers):
            row["rank"] = i
        return {
            "mode": "demo",
            "connected": False,
            "host": self.host,
            "port": self.port,
            "clientId": None,
            "scan": self.scan_key,
            "usingScanner": False,
            "marketDataType": None,
            "lastError": self.last_error or "Waiting for IBKR Gateway… showing simulated tape so you can learn the layout.",
            "farms": [],
            "lastScanAt": now,
            "serverTime": now,
            "session": session,
            "tickers": tickers,
            "prints": list(self.prints)[-18:],
        }

    def _seed_demo(self) -> None:
        names = [
            ("NVDA", 118.4, 180e6),
            ("TSLA", 248.1, 95e6),
            ("AMD", 162.2, 55e6),
            ("AAPL", 227.6, 52e6),
            ("PLTR", 170.6, 70e6),
            ("COIN", 232.0, 12e6),
            ("MSTR", 148.5, 18e6),
            ("SMCI", 612.0, 8e6),
            ("SOFI", 13.4, 48e6),
            ("META", 512.3, 16e6),
            ("AMZN", 178.9, 40e6),
            ("QQQ", 478.2, 45e6),
            ("SPY", 562.1, 70e6),
            ("IWM", 218.4, 32e6),
            ("NFLX", 642.0, 4e6),
            ("INTC", 22.1, 80e6),
            ("BAC", 39.4, 42e6),
            ("UBER", 72.8, 20e6),
        ]
        session = session_info()
        for i, (symbol, price, avg) in enumerate(names):
            rvol_target = random.uniform(0.4, 3.8)
            volume = avg * rvol_target * session["fraction"]
            self._demo_state[symbol] = {
                "rank": i,
                "last": price * random.uniform(0.985, 1.02),
                "close": price,
                "avgVolume": avg,
                "volume": volume,
                "volumeRate": avg * rvol_target / 390,
            }
