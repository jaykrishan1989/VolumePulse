"""IBKR Gateway feed: scanner + streaming market data."""

from __future__ import annotations

import asyncio
import ipaddress
import math
import os
import random
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
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

from app.alerts import notify_signals
from app.entry import DISCLAIMER, ENTRY, build_demo_board, screen_entries, watch_symbols
from app.freshness import annotate_setup, delay_banner
from app.outcomes import OutcomeLog
from app.research import load_research
from app.signals import SignalBook, describe_rule, load_rule, row_passes
from app.etfs import (
    ETF_DEMO,
    ETF_SYMBOLS,
    INDUSTRY_ORDER,
    etf_meta,
    industry_stocks,
    is_etf,
)
from app.midprice import PRICE_MAX, PRICE_MIN, in_price_band, quality_mid_symbols
from app.sectors import (
    all_overview_demo_symbols,
    overview_symbols,
    sector_by_id,
    sector_catalog,
    sector_stock_symbols,
)
from app.sp500 import LIQUID_SP500, ib_symbol, is_sp500

SCAN_CODES = {
    "sp500": "HOT_BY_VOLUME",
    "etfs": "HOT_BY_VOLUME",
    "overview": "HOT_BY_VOLUME",
    "mid_price": "HOT_BY_VOLUME",
    "right_time": "HOT_BY_VOLUME",
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
    162, 200, 2103, 2104, 2105, 2106, 2107, 2108, 2119, 2158,
    2100, 2110, 300, 354, 365, 366, 10089, 10091, 10167, 10197,
}


def stock_contract(symbol: str) -> Stock:
    key = ib_symbol(symbol)
    # One-letter names (K, F, T, …) are ambiguous on SMART and return error 200.
    if len(key.replace(" ", "")) == 1:
        return Stock(key, "SMART", "USD", primaryExchange="NYSE")
    return Stock(key, "SMART", "USD")


def classify_print_side(price: float | None, bid: float | None, ask: float | None) -> str:
    if price is None:
        return "unknown"
    if ask is not None and price >= ask - 1e-9:
        return "buy"
    if bid is not None and price <= bid + 1e-9:
        return "sell"
    if bid is not None and ask is not None and ask >= bid:
        mid = (bid + ask) / 2.0
        if price > mid:
            return "buy"
        if price < mid:
            return "sell"
    return "unknown"


def normalize_watch_symbol(raw: str) -> str:
    text = " ".join((raw or "").strip().upper().replace(".", " ").split())
    if not text or len(text) > 10:
        raise ValueError("Enter a ticker like NVDA or BRK.B")
    if not all(ch.isalnum() or ch == " " for ch in text):
        raise ValueError("Enter a ticker like NVDA or BRK.B")
    return text


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


def _market_data_type(ticker: Any) -> int | None:
    raw = getattr(ticker, "marketDataType", None)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _quote_epoch(ticker: Any) -> int | None:
    moment = to_et(getattr(ticker, "time", None))
    if moment is None:
        return None
    return int(moment.timestamp())


def to_et(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=NY)
        return value.astimezone(NY)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 9, 30, tzinfo=NY)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), NY)
    return None


def previous_rth_open(bars: Any, today: date | None = None) -> float | None:
    today = today or datetime.now(NY).date()
    opens: dict[date, float] = {}
    for bar in bars or []:
        moment = to_et(getattr(bar, "date", None))
        if moment is None:
            continue
        session = bar_session(moment)
        daily = moment.hour == 0 and moment.minute == 0
        if session != "regular" and not daily:
            continue
        day = moment.date()
        if day in opens:
            continue
        price = clean_price(getattr(bar, "open", None)) or clean_price(getattr(bar, "close", None))
        if price is not None:
            opens[day] = price
    prior = [day for day in sorted(opens) if day < today]
    return opens[prior[-1]] if prior else None


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
    rth_open = None
    if last_rth_i is not None:
        rth_date = parsed[last_rth_i][0].date()
        for bar in bars or []:
            moment = to_et(getattr(bar, "date", None))
            if moment is None:
                continue
            if bar_session(moment) == "regular" and moment.date() == rth_date:
                rth_open = clean_price(getattr(bar, "open", None)) or clean_price(
                    getattr(bar, "close", None)
                )
                break
    last = parsed[-1][2]
    last_minutes = 1.0
    if len(parsed) >= 2:
        last_minutes = max(1.0, (parsed[-1][0] - parsed[-2][0]).total_seconds() / 60)
    recent_volume = parsed[-1][1]
    return {
        "last": last,
        "rthClose": rth_close,
        "rthOpen": rth_open,
        "prevRthOpen": previous_rth_open(bars),
        "rthVolume": rth_volume or None,
        "extVolume": ext_volume or None,
        "volumeRate": recent_volume / last_minutes if recent_volume else None,
        "barTime": parsed[-1][0].isoformat(),
    }


def allowed_gateway_host(host: str) -> bool:
    """Only loopback / private LAN — the API socket must not become an open proxy."""
    name = (host or "").strip().lower()
    if not name or len(name) > 64:
        return False
    if name in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def is_us_equity_holiday(day: date) -> bool:
    year = day.year
    closed = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
        date(2025, 4, 18),
        date(2026, 4, 3),
        date(2027, 3, 26),
    }
    return day in closed


def session_info() -> dict[str, Any]:
    now = datetime.now(NY)
    minutes = now.hour * 60 + now.minute
    weekday = now.weekday()
    open_m, close_m = 9 * 60 + 30, 16 * 60
    if weekday >= 5 or is_us_equity_holiday(now.date()):
        label = "weekend" if weekday >= 5 else "holiday"
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
        "extended": label in ("premarket", "afterhours", "overnight", "weekend", "holiday"),
    }


class VolumeFeed:
    def __init__(self) -> None:
        self.host = os.environ.get("IBKR_HOST", "127.0.0.1")
        self.port = int(os.environ.get("IBKR_PORT", "4001"))
        self.client_id = int(os.environ.get("IBKR_CLIENT_ID", "7"))
        self.scan_key = os.environ.get("IBKR_SCAN", "sp500")
        self.sector_id: str | None = None
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
        self.bar_fetched: dict[str, float] = {}
        self.prev_opens: dict[str, float] = {}
        self.daily_marks: dict[str, dict[str, Any]] = {}
        self._hist_keep_up = True
        self._hist_cursor = 0
        self.history: dict[str, deque] = defaultdict(lambda: deque(maxlen=90))
        self.prev_print: dict[str, tuple] = {}
        self.prints: deque = deque(maxlen=80)
        self.prints_by_symbol: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.extra_watches: list[str] = []
        self.etf_industry: str | None = None
        self._unknown_contracts: set[str] = set()
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._signal_book = SignalBook(load_rule())

        self._demo_state: dict[str, dict[str, float]] = {}
        self._demo_entry_books: dict[str, list[dict[str, Any]]] = {}
        self._chart_bars: Any = None
        self._chart_key: tuple[str, int] | None = None
        self._chart_static: list[dict[str, Any]] | None = None
        self._chart_static_at = 0.0
        self._chart_lock = asyncio.Lock()

    def _on_error(self, req_id: int, code: int, message: str, contract: Any) -> None:
        text = f"{code}: {message}"
        symbol = getattr(contract, "symbol", None)
        if symbol:
            text += f" ({symbol})"
        if code in INFORMATIONAL_ERRORS:
            if code == 200 and symbol:
                self._unknown_contracts.add(ib_symbol(symbol))
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
                async with self._lock:
                    await self._ensure_connected()
                if not self.is_connected():
                    await asyncio.sleep(4)
                    continue
                await self._refresh_universe()
                await self._poll_daily_marks(8)
                missing_bars = any(symbol not in self.bar_stats for symbol in self.tickers)
                # Right Time to Buy keeps a slow rotation of 5-minute bars (two
                # requests per pass) so signals expire instead of freezing.
                if self.scan_key == "right_time" or not self._hist_keep_up or missing_bars:
                    await self._poll_history()
                    await self._poll_history()
                for i in range(20):
                    if self._stop.is_set() or not self.is_connected():
                        break
                    if self._resubscribe:
                        self._resubscribe = False
                        await self._refresh_universe(force=True)
                    if i % 5 == 4:
                        await self._poll_daily_marks(4)
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
        bars = self._chart_bars
        self._chart_bars = None
        self._chart_key = None
        self._chart_static = None
        try:
            if self.ib and bars is not None:
                self.ib.cancelHistoricalData(bars)
        except Exception:
            pass
        try:
            if self.ib and self.ib.isConnected():
                self.ib.disconnect()
        except Exception:
            pass
        self.connected = False

    async def reconnect(self, host: str, port: int, client_id: int, data_type: int) -> dict[str, Any]:
        if not allowed_gateway_host(host):
            raise ValueError("Gateway host must be localhost or a private LAN address.")
        if port < 1 or port > 65535:
            raise ValueError("Port must be between 1 and 65535.")
        if client_id < 0 or client_id > 32:
            raise ValueError("Client ID must be between 0 and 32.")
        if data_type not in (1, 3, 4):
            raise ValueError("Market data type must be 1 (live), 3 (delayed), or 4 (delayed-frozen).")
        self.host = host.strip()
        self.port = int(port)
        self.client_id = int(client_id)
        self.requested_data_type = int(data_type)
        self.last_error = None
        self.mode = "connecting"
        async with self._lock:
            self._disconnect()
            await self._ensure_connected()
        return {
            "ok": self.is_connected(),
            "mode": self.mode,
            "host": self.host,
            "port": self.port,
            "clientId": self.client_id_in_use,
            "error": None if self.is_connected() else self.last_error,
        }

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

    async def set_scan(self, scan_key: str, sector: str | None = None) -> None:
        if scan_key not in SCAN_CODES:
            raise ValueError(f"Unknown scan '{scan_key}'")
        if scan_key == "overview" and sector and not sector_by_id(sector):
            raise ValueError(f"Unknown sector '{sector}'")
        self.scan_key = scan_key
        self.sector_id = sector if scan_key == "overview" else None
        if scan_key != "etfs":
            self.etf_industry = None
        if self.is_connected():
            await self._refresh_universe()

    def _ensure_demo_symbol(self, raw: str) -> None:
        symbol = ib_symbol(raw)
        if not self._demo_state:
            self._seed_demo()
        if symbol in self._demo_state or raw in self._demo_state:
            return
        price = random.uniform(28, 420)
        avg = random.uniform(2e6, 18e6)
        session = session_info()
        rvol_target = random.uniform(0.5, 2.2)
        self._demo_state[symbol] = {
            "rank": 90,
            "last": price * random.uniform(0.988, 1.018),
            "close": price,
            "open": price * random.uniform(0.992, 1.008),
            "avgVolume": avg,
            "volume": avg * rvol_target * session["fraction"],
            "volumeRate": avg / 390,
        }

    async def set_etf_industry(self, industry: str | None) -> None:
        if industry:
            if industry not in INDUSTRY_ORDER:
                raise ValueError(f"Unknown industry '{industry}'")
            self.etf_industry = industry
            for symbol in industry_stocks(industry):
                self._ensure_demo_symbol(symbol)
        else:
            self.etf_industry = None
        if self.is_connected():
            await self._refresh_universe()

    async def watch_symbol(self, raw: str) -> str:
        symbol = normalize_watch_symbol(raw)
        if symbol in self.extra_watches:
            self.extra_watches.remove(symbol)
        self.extra_watches.append(symbol)
        self.extra_watches = self.extra_watches[-12:]
        if not self._demo_state:
            self._seed_demo()
        if symbol not in self._demo_state:
            price = 80.0
            avg = 8e6
            session = session_info()
            self._demo_state[symbol] = {
                "rank": 95,
                "last": price,
                "close": price,
                "open": price,
                "avgVolume": avg,
                "volume": avg * session["fraction"],
                "volumeRate": avg / 390,
            }
        if self.is_connected():
            async with self._lock:
                self.ranks.setdefault(symbol, 96)
                if symbol not in self.tickers:
                    contract = stock_contract(symbol)
                    try:
                        ticker = self.ib.reqMktData(contract, GENERIC_TICKS, False, False)
                    except Exception:
                        ticker = self.ib.reqMktData(contract, "", False, False)
                    self.contracts[symbol] = contract
                    self.tickers[symbol] = ticker
                    await self._subscribe_history(symbol)
            await self._fetch_daily_marks(symbol)
        return symbol

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

    async def _midprice_universe(self) -> tuple[list[str], dict[str, int], bool]:
        scanned: list[str] = []
        seen: set[str] = set()
        for scan_code in ("HOT_BY_VOLUME", "MOST_ACTIVE"):
            try:
                sub = ScannerSubscription(
                    instrument="STK",
                    locationCode="STK.US.MAJOR",
                    scanCode=scan_code,
                    numberOfRows=50,
                    abovePrice=PRICE_MIN,
                    belowPrice=PRICE_MAX,
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
        for symbol in scanned + quality_mid_symbols():
            if symbol in used:
                continue
            used.add(symbol)
            merged.append(symbol)
            if len(merged) >= 40:
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
            elif self.scan_key == "etfs":
                symbols = list(ETF_SYMBOLS)
                ranks = {sym: i for i, sym in enumerate(symbols)}
                for index, raw in enumerate(industry_stocks(self.etf_industry)):
                    key = ib_symbol(raw)
                    if key not in ranks:
                        ranks[key] = 200 + index
                        symbols.append(key)
                self.using_scanner = True
            elif self.scan_key == "overview":
                symbols = sector_stock_symbols(self.sector_id) if self.sector_id else overview_symbols()
                ranks = {sym: i for i, sym in enumerate(symbols)}
                self.using_scanner = True
            elif self.scan_key == "mid_price":
                symbols, ranks, self.using_scanner = await self._midprice_universe()
            elif self.scan_key == "right_time":
                symbols = watch_symbols()
                ranks = {sym: index for index, sym in enumerate(symbols)}
                self.using_scanner = True
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
            if self.scan_key == "etfs":
                symbols = list(ETF_SYMBOLS)
                for raw in industry_stocks(self.etf_industry):
                    key = ib_symbol(raw)
                    if key not in symbols:
                        symbols.append(key)
            elif self.scan_key == "overview":
                symbols = sector_stock_symbols(self.sector_id) if self.sector_id else overview_symbols()
            elif self.scan_key == "mid_price":
                symbols = quality_mid_symbols()
            elif self.scan_key == "right_time":
                symbols = watch_symbols()
            elif self.scan_key == "sp500":
                symbols = [ib_symbol(sym) for sym in LIQUID_SP500[: self.row_count]]
            else:
                symbols = FALLBACK_SYMBOLS[: self.row_count]
            ranks = {sym: i for i, sym in enumerate(symbols)}

        for symbol in self.extra_watches:
            if symbol not in ranks:
                ranks[symbol] = 96
                symbols.append(symbol)

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
                    self.prev_print.pop(symbol, None)
                    self.prints_by_symbol.pop(symbol, None)

        for symbol in symbols:
            self.ranks[symbol] = ranks.get(symbol, 99)
            if symbol not in self.tickers:
                if symbol in self._unknown_contracts:
                    continue
                contract = stock_contract(symbol)
                try:
                    ticker = self.ib.reqMktData(contract, GENERIC_TICKS, False, False)
                except Exception:
                    ticker = self.ib.reqMktData(contract, "", False, False)
                self.contracts[symbol] = contract
                self.tickers[symbol] = ticker

    def _drop_history(self, symbol: str) -> None:
        bars = self.bar_lists.pop(symbol, None)
        self.bar_stats.pop(symbol, None)
        self.bar_fetched.pop(symbol, None)
        self.prev_opens.pop(symbol, None)
        self.daily_marks.pop(symbol, None)
        if bars is None or not self.ib:
            return
        try:
            self.ib.cancelHistoricalData(bars)
        except Exception:
            pass

    def _store_bars(self, symbol: str, bars: Any) -> bool:
        stats = summarize_bars(bars)
        if not stats.get("last") and not stats.get("rthClose"):
            return False
        self.bar_lists[symbol] = bars
        self.bar_stats[symbol] = stats
        self.bar_fetched[symbol] = time.time()
        return True

    async def _request_trade_bars(
        self, contract: Any, duration: str, bar_size: str, keep_up: bool, timeout: float = 10
    ) -> Any:
        return await asyncio.wait_for(
            self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
                keepUpToDate=keep_up,
            ),
            timeout=timeout,
        )

    async def _subscribe_history(self, symbol: str) -> None:
        contract = self.contracts.get(symbol)
        if not contract or not self.ib:
            return
        attempts = []
        if self._hist_keep_up:
            attempts.append(("2 D", "1 min", True))
        # 2 calendar days is empty over a holiday weekend; walk back far enough
        # to include the last cash session (and its aftermarket).
        attempts.extend([("5 D", "5 mins", False), ("1 W", "15 mins", False)])
        for duration, size, keep in attempts:
            try:
                bars = await self._request_trade_bars(contract, duration, size, keep)
            except Exception:
                if keep:
                    self._hist_keep_up = False
                continue
            if self._store_bars(symbol, bars):
                return

    async def _poll_history(self) -> None:
        symbols = [symbol for symbol in self.tickers if symbol in self.contracts]
        if not symbols or not self.ib:
            return
        if self.scan_key == "right_time":
            symbol = min(symbols, key=lambda name: self.bar_fetched.get(name, 0.0))
        else:
            symbol = symbols[self._hist_cursor % len(symbols)]
            self._hist_cursor += 1
        if symbol in self._unknown_contracts:
            return
        contract = self.contracts[symbol]
        for duration, size in (("5 D", "5 mins"), ("1 W", "15 mins")):
            try:
                bars = await self._request_trade_bars(contract, duration, size, False, timeout=12)
            except Exception:
                continue
            if self._store_bars(symbol, bars):
                return

    async def _fetch_daily_marks(self, symbol: str) -> None:
        if symbol in self.daily_marks or symbol in self._unknown_contracts:
            return
        contract = self.contracts.get(symbol)
        if not contract or not self.ib:
            return
        try:
            bars = await asyncio.wait_for(
                self.ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr="5 D",
                    barSizeSetting="1 day",
                    whatToShow="TRADES",
                    useRTH=True,
                    formatDate=1,
                    keepUpToDate=False,
                ),
                timeout=6,
            )
        except Exception:
            return
        opens: dict[date, float] = {}
        closes: dict[date, float] = {}
        for bar in bars or []:
            moment = to_et(getattr(bar, "date", None))
            if moment is None:
                continue
            day = moment.date()
            open_px = clean_price(getattr(bar, "open", None))
            close_px = clean_price(getattr(bar, "close", None))
            if open_px is not None:
                opens[day] = open_px
            if close_px is not None:
                closes[day] = close_px
        today = datetime.now(NY).date()
        days = [day for day in sorted(closes) if day < today]
        if not days:
            return
        marks: dict[str, Any] = {"cashClose": closes[days[-1]], "cashDate": days[-1].isoformat()}
        if days[-1] in opens:
            marks["cashOpen"] = opens[days[-1]]
        if len(days) >= 2:
            marks["prevClose"] = closes[days[-2]]
            if days[-2] in opens:
                marks["prevOpen"] = opens[days[-2]]
        self.daily_marks[symbol] = marks
        if marks.get("prevOpen") is not None:
            self.prev_opens[symbol] = marks["prevOpen"]
        elif marks.get("cashOpen") is not None:
            self.prev_opens[symbol] = marks["cashOpen"]

    async def _poll_daily_marks(self, count: int = 4) -> None:
        missing = [
            symbol for symbol in self.tickers if symbol not in self.daily_marks and symbol in self.contracts
        ]
        if not missing:
            return
        await asyncio.gather(*(self._fetch_daily_marks(symbol) for symbol in missing[: max(1, count)]))

    def _ohlc_payload(self, bars: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for bar in bars or []:
            moment = to_et(getattr(bar, "date", None))
            close = clean_price(getattr(bar, "close", None))
            if moment is None or close is None:
                continue
            open_px = clean_price(getattr(bar, "open", None)) or close
            high = clean_price(getattr(bar, "high", None)) or max(open_px, close)
            low = clean_price(getattr(bar, "low", None)) or min(open_px, close)
            out.append(
                {
                    "t": int(moment.timestamp()),
                    "open": open_px,
                    "high": max(high, open_px, close),
                    "low": min(low, open_px, close),
                    "close": close,
                    "volume": clean_size(getattr(bar, "volume", None)) or 0,
                }
            )
        return out

    def _demo_entry_chart(self, symbol: str, minutes: int) -> list[dict[str, Any]] | None:
        if not self._demo_entry_books:
            self._demo_entry_books = build_demo_board()["books"]
        bars = self._demo_entry_books.get(symbol) or self._demo_entry_books.get(ib_symbol(symbol))
        if not bars:
            return None
        if minutes != 15:
            return [dict(bar) for bar in bars]
        folded = []
        chunk: list[dict[str, Any]] = []
        for bar in bars:
            chunk.append(bar)
            if len(chunk) < 3:
                continue
            folded.append(
                {
                    "t": chunk[-1]["t"],
                    "open": chunk[0]["open"],
                    "high": max(item["high"] for item in chunk),
                    "low": min(item["low"] for item in chunk),
                    "close": chunk[-1]["close"],
                    "volume": sum(item["volume"] for item in chunk),
                }
            )
            chunk = []
        return folded or [dict(bar) for bar in bars]

    def _demo_chart_bars(self, symbol: str, minutes: int = 5) -> list[dict[str, Any]]:
        if not self._demo_state:
            self._seed_demo()
        state = self._demo_state.get(symbol) or self._demo_state.get(ib_symbol(symbol)) or {}
        last = float(state.get("last") or state.get("close") or 80)
        rng = random.Random(symbol)
        step = 15 if minutes == 15 else 5
        bars_per_session = 26 if step == 15 else 78
        sessions: list[date] = []
        day = datetime.now(NY).date()
        while len(sessions) < 5:
            if day.weekday() < 5:
                sessions.append(day)
            day -= timedelta(days=1)
        sessions.reverse()
        price = last * rng.uniform(0.97, 1.01)
        out: list[dict[str, Any]] = []
        for session_day in sessions:
            start = datetime(session_day.year, session_day.month, session_day.day, 9, 30, tzinfo=NY)
            for index in range(bars_per_session):
                moment = start + timedelta(minutes=step * index)
                price = max(0.5, price + (last - price) * 0.003 + rng.gauss(0, last * 0.0015))
                open_px = price * rng.uniform(0.9985, 1.0015)
                close = price
                high = max(open_px, close) * (1 + abs(rng.gauss(0, 0.0012)))
                low = min(open_px, close) * (1 - abs(rng.gauss(0, 0.0012)))
                out.append(
                    {
                        "t": int(moment.timestamp()),
                        "open": round(open_px, 4),
                        "high": round(high, 4),
                        "low": round(low, 4),
                        "close": round(close, 4),
                        "volume": int(max(100, abs(rng.gauss(14000, 5000)))),
                    }
                )
        return out

    def _stamp_demo_last(self, symbol: str, bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
        state = self._demo_state.get(symbol) or self._demo_state.get(ib_symbol(symbol)) or {}
        last = float(state.get("last") or 0)
        if not bars or last <= 0:
            return bars
        bar = dict(bars[-1])
        bar["close"] = round(last, 4)
        bar["high"] = round(max(bar["high"], last), 4)
        bar["low"] = round(min(bar["low"], last), 4)
        return bars[:-1] + [bar]

    def _stamp_live_last(self, symbol: str, bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not bars:
            return bars
        last = None
        ticker = self.tickers.get(symbol)
        if ticker is not None:
            last = clean_price(getattr(ticker, "last", None)) or clean_price(getattr(ticker, "close", None))
            if last is None:
                try:
                    last = clean_price(ticker.marketPrice())
                except Exception:
                    last = None
        if last is None:
            state = self._demo_state.get(symbol) or self._demo_state.get(ib_symbol(symbol)) or {}
            last = float(state.get("last") or 0) or None
        if last is None:
            return bars
        bar = dict(bars[-1])
        px = float(last)
        bar["close"] = round(px, 4)
        bar["high"] = round(max(bar["high"], px), 4)
        bar["low"] = round(min(bar["low"], px), 4)
        return bars[:-1] + [bar]

    async def stop_chart_stream(self) -> None:
        async with self._chart_lock:
            bars = self._chart_bars
            self._chart_bars = None
            self._chart_key = None
            self._chart_static = None
            if bars is not None and self.ib:
                try:
                    self.ib.cancelHistoricalData(bars)
                except Exception:
                    pass

    async def chart_bars(self, raw: str, bar_minutes: int = 5) -> dict[str, Any]:
        symbol = normalize_watch_symbol(raw)
        minutes = 15 if int(bar_minutes or 5) == 15 else 5
        extra = {"barMinutes": minutes}
        async with self._chart_lock:
            return await self._chart_bars_locked(symbol, minutes, extra)

    async def _chart_bars_locked(self, symbol: str, minutes: int, extra: dict[str, Any]) -> dict[str, Any]:
        bar_size = "15 mins" if minutes == 15 else "5 mins"
        key = (symbol, minutes)
        min_bars = 20 if minutes == 15 else 40
        if not self.is_connected():
            if not self._demo_state:
                self._seed_demo()
            entry_bars = self._demo_entry_chart(symbol, minutes)
            bars = entry_bars if entry_bars else self._stamp_live_last(symbol, self._demo_chart_bars(symbol, minutes))
            return {
                "symbol": symbol,
                "bars": bars,
                "simulated": True,
                "live": True,
                **extra,
            }
        if self._chart_key == key and self._chart_bars is not None:
            payload = self._ohlc_payload(self._chart_bars)
            if len(payload) >= min_bars:
                return {"symbol": symbol, "bars": self._stamp_live_last(symbol, payload), "simulated": False, "live": True, **extra}
        if (
            self._chart_key == key
            and self._chart_static
            and time.time() - self._chart_static_at < 15
            and len(self._chart_static) >= min_bars
        ):
            return {"symbol": symbol, "bars": self._stamp_live_last(symbol, self._chart_static), "simulated": False, "live": True, **extra}

        if self._chart_key != key:
            bars = self._chart_bars
            self._chart_bars = None
            self._chart_key = None
            self._chart_static = None
            if bars is not None and self.ib:
                try:
                    self.ib.cancelHistoricalData(bars)
                except Exception:
                    pass

        contract = self.contracts.get(symbol) or stock_contract(symbol)
        try:
            bars = await asyncio.wait_for(
                self.ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr="5 D",
                    barSizeSetting=bar_size,
                    whatToShow="TRADES",
                    useRTH=True,
                    formatDate=1,
                    keepUpToDate=True,
                ),
                timeout=14,
            )
            self._chart_bars = bars
            self._chart_key = key
            payload = self._ohlc_payload(bars)
            if len(payload) >= min_bars:
                return {"symbol": symbol, "bars": self._stamp_live_last(symbol, payload), "simulated": False, "live": True, **extra}
        except Exception:
            pass
        try:
            bars = await asyncio.wait_for(
                self.ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr="5 D",
                    barSizeSetting=bar_size,
                    whatToShow="TRADES",
                    useRTH=True,
                    formatDate=1,
                    keepUpToDate=False,
                ),
                timeout=14,
            )
        except Exception as exc:
            return {
                "symbol": symbol,
                "bars": self._stamp_live_last(symbol, self._demo_chart_bars(symbol, minutes)),
                "simulated": True,
                "live": True,
                "note": f"IBKR history unavailable ({exc}). Showing a simulated path.",
                **extra,
            }
        payload = self._ohlc_payload(bars)
        if len(payload) < min_bars:
            return {
                "symbol": symbol,
                "bars": self._stamp_live_last(symbol, self._demo_chart_bars(symbol, minutes)),
                "simulated": True,
                "live": True,
                "note": "Not enough IBKR bars yet. Showing a simulated path.",
                **extra,
            }
        self._chart_key = key
        self._chart_static = payload
        self._chart_static_at = time.time()
        return {"symbol": symbol, "bars": self._stamp_live_last(symbol, payload), "simulated": False, "live": True, **extra}

    def snapshot(self) -> dict[str, Any]:
        session = session_info()
        if self.mode != "live" or not self.is_connected():
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
        entry_meta = self._empty_entry_meta()
        if self.scan_key == "right_time":
            tickers, entry_meta = self._live_entry(tickers, session)
        if self.scan_key == "mid_price":
            watched = set(self.extra_watches)
            tickers = [
                row
                for row in tickers
                if row["symbol"] in watched
                or in_price_band(row.get("last") if row.get("last") is not None else row.get("close"))
            ]
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
            "prints": list(self.prints)[:40],
            **self._print_payload(tickers),
            "industries": INDUSTRY_ORDER if self.scan_key == "etfs" else [],
            "etfIndustry": self.etf_industry if self.scan_key == "etfs" else None,
            "industryStocks": industry_stocks(self.etf_industry) if self.scan_key == "etfs" else [],
            "sectors": sector_catalog() if self.scan_key == "overview" else [],
            "sector": self.sector_id,
            "quoteDelay": entry_meta.get("quoteDelay") or self._quote_delay(tickers),
            **entry_meta,
            **self._model_fields(),
        }

    def _empty_entry_meta(self) -> dict[str, Any]:
        if self.scan_key != "right_time":
            return {
                "entryNote": None,
                "entryDisclaimer": None,
                "entryThreshold": None,
                "entryTopN": None,
            }
        return {
            "entryNote": None,
            "entryDisclaimer": DISCLAIMER,
            "entryThreshold": None,
            "entryTopN": None,
        }

    def _quote_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": row.get("symbol"),
            "last": row.get("last"),
            "bid": row.get("bid"),
            "ask": row.get("ask"),
            "dollarVolume": row.get("dollarVolume"),
            "rvol": row.get("rvol"),
            "halted": row.get("halted") or 0,
        }

    def _books(self) -> dict[str, list[dict[str, Any]]]:
        books: dict[str, list[dict[str, Any]]] = {}
        for symbol, bars in self.bar_lists.items():
            payload = self._ohlc_payload(bars)
            if payload:
                books[symbol] = payload
        return books

    def _outcome_log(self) -> OutcomeLog:
        log = getattr(self, "_outcomes", None)
        if log is None:
            log = OutcomeLog()
            self._outcomes = log
        return log

    def _research_fields(self) -> dict[str, Any]:
        try:
            paper = self._outcome_log().summary()
        except Exception:
            paper = {"open": 0, "closed": 0, "note": "Paper log only. Volume Pulse never places orders."}
        return {"entryResearch": load_research(), "entryPaper": paper}

    def _model_fields(self) -> dict[str, Any]:
        """Active checkpoint, plus a rollback flag when the paper log falls short."""
        try:
            from app.signals import SignalBook, load_rule
            from models.monitor import live_status

            payload = live_status(self._outcome_log().closed_signal_bps())
            if payload.get("rollback", {}).get("kind") == "rollback":
                load_rule.cache_clear()
                self._signal_book = SignalBook(load_rule())
        except Exception:
            payload = {
                "version": None,
                "status": "unknown",
                "passedGate": False,
                "label": "model unavailable",
                "rollback": {"active": False, "kind": None, "message": ""},
            }
        return {"model": payload}

    def _stamp_research(self, row: dict[str, Any]) -> dict[str, Any]:
        hold = (load_research().get("holdout") or {}) if load_research() else {}
        if hold:
            row["entryHistWin"] = hold.get("winRate")
            row["entryHistBps"] = hold.get("avgNetBps")
            row["entryHistDollars"] = hold.get("avgNetDollars")
            row["entryHistTrades"] = hold.get("trades")
        return row

    def _quote_delay(self, tickers: list[dict[str, Any]], withheld: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        types = []
        if self.market_data_type is not None:
            types.append(int(self.market_data_type))
        for row in tickers:
            if row.get("marketDataType") is not None:
                types.append(int(row["marketDataType"]))
        data_type = 3 if any(value in (3, 4) for value in types) else (types[0] if types else None)
        return delay_banner(data_type, withheld or [])

    def _apply_signals(self, tickers: list[dict[str, Any]], screened: dict[str, Any]) -> list[dict[str, Any]]:
        by_symbol = {row["symbol"]: row for row in tickers}
        rows = []
        for signal in screened["signals"]:
            base = dict(by_symbol.get(signal.symbol) or {"symbol": signal.symbol})
            base.update(signal.as_row())
            if base.get("last") is None:
                base["last"] = signal.last
            rows.append(self._stamp_research(base))
        return rows

    def _entry_meta(self, screened: dict[str, Any]) -> dict[str, Any]:
        meta = {
            "entryNote": screened["note"],
            "entryDisclaimer": DISCLAIMER,
            "entryThreshold": screened["threshold"],
            "entryTopN": screened["topN"],
        }
        meta.update(self._research_fields())
        return meta

    def _live_entry(
        self, tickers: list[dict[str, Any]], session: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if session.get("label") != "regular":
            return [], {
                "entryNote": "Setups only appear in the regular session, after the open and before the last 15 minutes.",
                "entryDisclaimer": DISCLAIMER,
                "entryThreshold": None,
                "entryTopN": None,
            }
        books = self._books()
        if not books:
            return [], {
                "entryNote": (
                    "Reading 5-minute bars from IBKR, two names at a time so the historical "
                    "feed stays inside pacing limits. A name shows up only after a fresh rebound scores."
                ),
                "entryDisclaimer": DISCLAIMER,
                "entryThreshold": None,
                "entryTopN": None,
            }
        quotes = {row["symbol"]: self._quote_from_row(row) for row in tickers}
        screened = screen_entries(
            books,
            quotes,
            now=datetime.now(NY),
            session_fraction=float(session.get("fraction") or 0.5),
            enforce_clock=True,
        )
        rows = self._apply_signals(tickers, screened)
        now = datetime.now(NY)
        books = self._books()
        annotated = []
        for row in rows:
            symbol = row.get("symbol")
            source = next((item for item in tickers if item.get("symbol") == symbol), {})
            series = books.get(symbol) or []
            bar_epoch = series[-1]["t"] if series else None
            data_type = source.get("marketDataType")
            if data_type is None:
                data_type = self.market_data_type
            annotated.append(
                annotate_setup(
                    row,
                    data_type=int(data_type) if data_type is not None else None,
                    bar_epoch=bar_epoch,
                    quote_epoch=source.get("quoteTime"),
                    now=now,
                    bar_minutes=ENTRY.bar_minutes,
                )
            )
        listed = [row for row in annotated if not row.get("entryWithhold")]
        withheld = [row for row in annotated if row.get("entryWithhold")]
        marks = {
            row["symbol"]: float(row["last"])
            for row in tickers
            if row.get("symbol") and row.get("last") is not None
        }
        rule = load_rule()
        minute = now.hour * 60 + now.minute
        qualifying = [row for row in listed if row_passes(row, rule, minute)]
        bar_epochs: dict[str, int | None] = {}
        for symbol, series in books.items():
            if series:
                bar_epochs[symbol] = series[-1]["t"]
        events = self._signal_book.update(qualifying, bar_epochs, marks, now)
        try:
            log = self._outcome_log()
            log.record_signals(events, now)
            notify_signals(events)
            logged = log.recent_signals(now.date().isoformat())
        except Exception:
            logged = events
        active_rows = []
        for symbol, saved in self._signal_book.active.items():
            fresh = next((row for row in listed if row.get("symbol") == symbol), None)
            active_rows.append(dict(fresh or saved))
        listed = active_rows
        meta = self._entry_meta(screened)
        meta["entryWithheld"] = withheld
        meta["quoteDelay"] = self._quote_delay(tickers, withheld)
        meta["entrySignals"] = logged
        meta["entryRule"] = describe_rule(rule)
        if qualifying and not listed:
            meta["entryNote"] = (
                "A name has to stay on the list for the confirm bars before it is a BUY. "
                "Nothing is confirmed yet. Confirm any signal yourself — this is not an order."
            )
        if not listed and withheld:
            meta["entryNote"] = (
                f"{len(withheld)} setup{'s' if len(withheld) != 1 else ''} hidden. "
                "Delayed quotes, a bar more than a minute behind the clock, or a price "
                "already through the stop or target is not a buy."
            )
        return listed, meta

    def _demo_entry_snapshot(self, session: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        board = build_demo_board()
        self._demo_entry_books = board["books"]
        tickers = []
        for row in board["rows"]:
            item = dict(row)
            item["simulated"] = True
            item["extended"] = bool(session.get("extended"))
            item["updated"] = now
            item.setdefault("spark", [])
            item.setdefault("priceSpark", [])
            tickers.append(self._stamp_research(item))
        withheld: list[dict[str, Any]] = []
        quote_delay = {"active": False, "kind": None, "message": ""}
        entry_note = board["note"]
        # Opt-in preview of the delayed-tape banner. Off unless RTTB_FORCE_DELAY=1.
        if os.environ.get("RTTB_FORCE_DELAY") == "1":
            for item in tickers:
                held = dict(item)
                held["entryWithhold"] = "delayed"
                held["entryDelayed"] = 1
                held["entryDataType"] = 3
                held["entryLagSec"] = 15 * 60
                withheld.append(held)
            tickers = []
            quote_delay = delay_banner(3, withheld)
            entry_note = (
                f"{len(withheld)} setups hidden. Delayed quotes are not a buy."
            )
        return {
            "mode": "demo",
            "connected": False,
            "host": self.host,
            "port": self.port,
            "clientId": None,
            "scan": self.scan_key,
            "usingScanner": False,
            "marketDataType": None,
            "lastError": self.last_error
            or "Waiting for IBKR Gateway… showing a simulated tape so you can learn the layout.",
            "farms": [],
            "lastScanAt": now,
            "serverTime": now,
            "session": session,
            "tickers": tickers,
            "prints": list(self.prints)[:40],
            **self._print_payload(tickers),
            "industries": [],
            "etfIndustry": None,
            "industryStocks": [],
            "sectors": [],
            "sector": None,
            "entryNote": entry_note,
            "entryDisclaimer": DISCLAIMER,
            "entryThreshold": board["threshold"],
            "entryTopN": board["topN"],
            "entryWithheld": withheld,
            "quoteDelay": quote_delay,
            "entryRule": describe_rule(),
            **self._model_fields(),
            "entrySignals": [
                {
                    "action": "BUY",
                    "symbol": item.get("symbol"),
                    "price": item.get("last"),
                    "stop": item.get("entryStop"),
                    "score": item.get("entryScore"),
                    "note": "Simulated. Enter at the next bar open. Confirm manually. Not an order.",
                    "simulated": True,
                }
                for item in tickers
            ],
            **self._research_fields(),
        }

    def _print_payload(self, tickers: list[dict[str, Any]]) -> dict[str, Any]:
        symbols = [row["symbol"] for row in tickers]
        for symbol in self.extra_watches:
            if symbol not in symbols:
                symbols.append(symbol)
        return {
            "extraWatches": list(self.extra_watches),
            "printsBySymbol": {
                symbol: list(self.prints_by_symbol.get(symbol, ())) for symbol in symbols
            },
            "printStats": {symbol: self._print_stats_for(symbol) for symbol in symbols},
        }

    def _row_from_ticker(self, symbol: str, ticker: Any, session: dict[str, Any], now: float) -> dict[str, Any]:
        last = clean_price(ticker.last) or clean_price(getattr(ticker, "delayedLast", None))
        prev_close = clean_price(ticker.close) or clean_price(getattr(ticker, "delayedClose", None))
        open_px = clean_price(getattr(ticker, "open", None)) or clean_price(
            getattr(ticker, "delayedOpen", None)
        )
        if last is None:
            last = clean_price(ticker.marketPrice())
        bid = clean_price(ticker.bid)
        ask = clean_price(ticker.ask)
        volume = clean_size(ticker.volume) or clean_size(getattr(ticker, "delayedVolume", None))
        avg_volume = clean_size(getattr(ticker, "avVolume", None))
        volume_rate = clean_size(getattr(ticker, "volumeRate", None))
        trade_rate = clean_size(getattr(ticker, "tradeRate", None))
        last_size = clean_size(ticker.lastSize)
        high = clean_price(ticker.high)
        low = clean_price(ticker.low)
        vwap = clean_price(getattr(ticker, "vwap", None))
        high52 = clean_price(getattr(ticker, "high52week", None))
        low52 = clean_price(getattr(ticker, "low52week", None))
        halted_raw = finite(getattr(ticker, "halted", None))
        halted = int(halted_raw) if halted_raw is not None and halted_raw > 0 else 0

        ext = self.bar_stats.get(symbol) or {}
        marks = self.daily_marks.get(symbol) or {}
        rth_close = clean_price(marks.get("cashClose")) or clean_price(ext.get("rthClose"))
        rth_open = clean_price(marks.get("cashOpen")) or clean_price(ext.get("rthOpen"))
        prior_close = clean_price(marks.get("prevClose"))
        prev_open = self.prev_opens.get(symbol)
        if prev_open is None:
            prev_open = clean_price(marks.get("prevOpen")) or clean_price(ext.get("prevRthOpen"))
        if prev_open is not None:
            self.prev_opens[symbol] = prev_open
        if open_px is None:
            open_px = rth_open
        ext_volume = clean_size(ext.get("extVolume"))
        rth_volume = clean_size(ext.get("rthVolume"))
        if last is None and ext.get("last"):
            last = clean_price(ext["last"])
        if ext.get("volumeRate") and not volume_rate:
            volume_rate = ext["volumeRate"]

        label = session.get("label") or ""
        extended = bool(session.get("extended"))
        session_over = label in ("overnight", "weekend", "holiday")
        if session_over and rth_close:
            last = rth_close
            close = prior_close if prior_close not in (None, rth_close) else None
        elif label == "afterhours" and rth_close:
            close = rth_close
        elif label == "premarket" and prior_close:
            close = prior_close
        else:
            close = prev_close if prev_close not in (None, 0) else prior_close or rth_close
        if last is None:
            last = close
        if session_over and rth_volume:
            volume = rth_volume
        elif extended and ext_volume:
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
            "open": open_px,
            "prevOpen": prev_open,
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
            "halted": halted,
            "dollarVolume": dollar_volume,
            "extended": extended,
            "updated": now,
            "marketDataType": _market_data_type(ticker),
            "quoteTime": _quote_epoch(ticker),
            **etf_meta(symbol),
        }

    def _capture_print(self, row: dict[str, Any]) -> None:
        symbol = row["symbol"]
        last = row.get("last")
        volume = row.get("volume")
        last_size = row.get("lastSize")
        key = (last, last_size, volume)
        previous = self.prev_print.get(symbol)
        self.prev_print[symbol] = key
        if previous is None or key == previous:
            return
        prev_last, _prev_size, prev_vol = previous
        size = None
        if volume is not None and prev_vol is not None and volume > prev_vol:
            delta = volume - prev_vol
            # Delayed volume often jumps in one snapshot; that is not a single order.
            if 0 < delta <= 400_000:
                size = delta
        if size is None:
            if last is None or last_size in (None, 0):
                return
            if last == prev_last and last_size == _prev_size:
                return
            size = last_size
        if last is None:
            return
        side = classify_print_side(last, row.get("bid"), row.get("ask"))
        item = {
            "t": time.time(),
            "symbol": symbol,
            "price": last,
            "size": size,
            "side": side,
            "changePct": row.get("changePct"),
        }
        self.prints.appendleft(item)
        self.prints_by_symbol[symbol].appendleft(item)

    def _print_stats_for(self, symbol: str) -> dict[str, float | int]:
        bought = sold = unknown = 0.0
        bought_d = sold_d = 0.0
        items = self.prints_by_symbol.get(symbol) or ()
        for print_ in items:
            size = print_.get("size") or 0
            price = print_.get("price") or 0
            notion = size * price
            side = print_.get("side")
            if side == "buy":
                bought += size
                bought_d += notion
            elif side == "sell":
                sold += size
                sold_d += notion
            else:
                unknown += size
        return {
            "bought": bought,
            "sold": sold,
            "unknown": unknown,
            "boughtDollars": bought_d,
            "soldDollars": sold_d,
            "count": len(items),
            "net": bought - sold,
        }

    def _demo_snapshot(self, session: dict[str, Any]) -> dict[str, Any]:
        if self.scan_key == "right_time":
            return self._demo_entry_snapshot(session)
        now = time.time()
        if not self._demo_state:
            self._seed_demo()
        tickers = []
        for symbol, state in self._demo_state.items():
            watched = ib_symbol(symbol) in self.extra_watches
            if watched:
                pass
            elif self.scan_key == "etfs":
                holdings = {ib_symbol(item) for item in industry_stocks(self.etf_industry)}
                if not is_etf(symbol) and ib_symbol(symbol) not in holdings:
                    continue
            elif self.scan_key == "overview":
                wanted = {
                    item.replace(".", " ")
                    for item in (
                        sector_stock_symbols(self.sector_id) if self.sector_id else overview_symbols()
                    )
                }
                if symbol.replace(".", " ") not in wanted:
                    continue
            elif self.scan_key == "mid_price":
                if not is_sp500(symbol) or not in_price_band(state["last"]):
                    continue
            elif is_etf(symbol) and symbol not in ("SPY", "QQQ", "IWM"):
                continue
            elif self.scan_key == "sp500" and not is_sp500(symbol):
                continue
            state["last"] += random.gauss(0, state["last"] * 0.0004)
            state["volume"] += abs(random.gauss(state["volumeRate"] / 60, state["volumeRate"] / 180))
            state["volumeRate"] = max(0, state["volumeRate"] + random.gauss(0, state["volumeRate"] * 0.05))
            if random.random() < 0.08:
                size = max(100, int(abs(random.gauss(1200, 800)) / 100) * 100)
                price = state["last"]
                side = "buy" if random.random() < 0.55 else "sell"
                if side == "buy":
                    price = state["last"] + 0.01
                else:
                    price = state["last"] - 0.01
                item = {
                    "t": now,
                    "symbol": symbol,
                    "price": price,
                    "size": size,
                    "side": side,
                    "changePct": (state["last"] - state["close"]) / state["close"] * 100,
                }
                self.prints.appendleft(item)
                self.prints_by_symbol[symbol].appendleft(item)
            change = state["last"] - state["close"]
            rvol = state["volume"] / state["avgVolume"]
            row = {
                "symbol": symbol,
                "rank": state["rank"],
                "last": state["last"],
                "open": state.get("open", state["close"]),
                "prevOpen": state.get("prevOpen")
                or (state.get("open") or state["close"]) * 0.992,
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
                "high": max(state["last"], state.get("open", state["close"]), state["close"] * 1.01),
                "low": min(state["last"], state.get("open", state["close"]), state["close"] * 0.99),
                "vwap": (state["last"] + state["close"]) / 2,
                "high52": state["close"] * 1.4,
                "low52": state["close"] * 0.7,
                "dollarVolume": state["last"] * state["volume"],
                "simulated": True,
                "extended": bool(session.get("extended")),
                "updated": now,
                **etf_meta(symbol),
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
            "prints": list(self.prints)[:40],
            **self._print_payload(tickers),
            "industries": INDUSTRY_ORDER if self.scan_key == "etfs" else [],
            "etfIndustry": self.etf_industry if self.scan_key == "etfs" else None,
            "industryStocks": industry_stocks(self.etf_industry) if self.scan_key == "etfs" else [],
            "sectors": sector_catalog() if self.scan_key == "overview" else [],
            "sector": self.sector_id,
            "entryNote": None,
            "entryDisclaimer": None,
            "entryThreshold": None,
            "entryTopN": None,
            **self._model_fields(),
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
                "open": price * random.uniform(0.992, 1.008),
                "avgVolume": avg,
                "volume": volume,
                "volumeRate": avg * rvol_target / 390,
            }
        for symbol, (price, avg) in ETF_DEMO.items():
            if symbol in self._demo_state:
                continue
            rvol_target = random.uniform(0.5, 2.4)
            volume = avg * rvol_target * session["fraction"]
            self._demo_state[symbol] = {
                "rank": 80,
                "last": price * random.uniform(0.988, 1.018),
                "close": price,
                "open": price * random.uniform(0.992, 1.008),
                "avgVolume": avg,
                "volume": volume,
                "volumeRate": avg * rvol_target / 390,
            }
        for symbol in all_overview_demo_symbols():
            key = symbol.replace(".", " ")
            if key in self._demo_state:
                continue
            price = random.uniform(28, 420)
            avg = random.uniform(2e6, 18e6)
            rvol_target = random.uniform(0.5, 2.2)
            volume = avg * rvol_target * session["fraction"]
            self._demo_state[key] = {
                "rank": 90,
                "last": price * random.uniform(0.988, 1.018),
                "close": price,
                "open": price * random.uniform(0.992, 1.008),
                "avgVolume": avg,
                "volume": volume,
                "volumeRate": avg * rvol_target / 390,
            }
        for symbol in quality_mid_symbols():
            if symbol in self._demo_state and in_price_band(self._demo_state[symbol]["last"]):
                continue
            price = random.uniform(12.5, 47.5)
            avg = random.uniform(4e6, 40e6)
            rvol_target = random.uniform(0.6, 2.8)
            volume = avg * rvol_target * session["fraction"]
            last = price * random.uniform(0.985, 1.02)
            open_px = price * random.uniform(0.99, 1.01)
            self._demo_state[symbol] = {
                "rank": 70,
                "last": last,
                "close": price,
                "open": open_px,
                "prevOpen": open_px * random.uniform(0.97, 1.03),
                "avgVolume": avg,
                "volume": volume,
                "volumeRate": avg * rvol_target / 390,
            }
