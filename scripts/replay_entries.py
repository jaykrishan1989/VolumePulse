#!/usr/bin/env python3
"""Replay Right Time to Buy on IBKR historical 5-minute bars.

Read-only. This script never places or previews orders. Run it on a machine
that can see IB Gateway (default 127.0.0.1:4001) and use the printout to
retune thresholds in ``app/entry.py``.

Examples:

    python scripts/replay_entries.py --days 5
    python scripts/replay_entries.py --symbols NVDA,AMD,JPM --days 3
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.entry import (  # noqa: E402
    ENTRY,
    context_symbols,
    evaluate_entry,
    market_state,
    sector_etf_for,
)
from app.ibkr import NY, clean_price, clean_size, stock_contract, to_et  # noqa: E402

HORIZONS = (3, 6, 12)  # 5-minute bars: 15, 30, and 60 minutes


def _bar_time(value):
    moment = to_et(value)
    if moment is not None:
        return moment
    if isinstance(value, str) and value.strip():
        text = value.strip()
        for fmt in ("%Y%m%d  %H:%M:%S", "%Y%m%d %H:%M:%S", "%Y%m%d"):
            try:
                parsed = datetime.strptime(text, fmt)
            except ValueError:
                continue
            return parsed.replace(tzinfo=NY)
    return None


def bars_from_ib(raw) -> list[dict]:
    out = []
    for bar in raw or []:
        moment = _bar_time(getattr(bar, "date", None))
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
    out.sort(key=lambda item: item["t"])
    return out


def session_fraction(moment: datetime) -> float:
    minutes = moment.hour * 60 + moment.minute
    elapsed = minutes - (9 * 60 + 30)
    return max(0.02, min(1.0, elapsed / 390))


def fetch_bars(ib, symbol: str, days: int) -> list[dict]:
    contract = stock_contract(symbol)
    raw = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=f"{max(1, days)} D",
        barSizeSetting="5 mins",
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
        keepUpToDate=False,
    )
    return bars_from_ib(raw)


def _prefix(bars: list[dict], moment_ts: int) -> list[dict]:
    return [bar for bar in bars if bar["t"] <= moment_ts]


def _outcome(future: list[dict], entry: float, stop: float, target: float, horizon: int) -> dict | None:
    window = future[:horizon]
    if len(window) < horizon or entry <= 0:
        return None
    stopped = False
    hit_target = False
    for bar in window:
        if bar["low"] <= stop:
            stopped = True
            break
        if bar["high"] >= target:
            hit_target = True
            break
    if stopped:
        ret = (stop - entry) / entry
    else:
        ret = (window[-1]["close"] - entry) / entry
    return {"return": ret, "stopped": stopped, "target": hit_target and not stopped}


def replay_symbol(
    symbol: str,
    bars: list[dict],
    books: dict[str, list[dict]],
) -> list[dict]:
    sector = sector_etf_for(symbol)
    seen: set[int] = set()
    trades = []
    start = max(ENTRY.atr_period + ENTRY.min_today_bars, 20)
    for index in range(start, len(bars) - max(HORIZONS)):
        moment = datetime.fromtimestamp(bars[index]["t"], NY)
        if moment.weekday() >= 5:
            continue
        prefix = bars[: index + 1]
        spy = _prefix(books.get("SPY") or [], bars[index]["t"])
        qqq = _prefix(books.get("QQQ") or [], bars[index]["t"])
        sector_bars = _prefix(books.get(sector) or [], bars[index]["t"]) if sector else None
        last = prefix[-1]["close"]
        # No bid/ask on historical bars, so the spread gate stays open.
        # Dollar volume is taken from the session bars inside the scorer.
        signal = evaluate_entry(
            prefix,
            {
                "symbol": symbol,
                "last": last,
                "halted": 0,
            },
            now=moment + timedelta(minutes=ENTRY.bar_minutes),
            session_fraction=session_fraction(moment),
            enforce_clock=True,
            spy_state=market_state(spy),
            qqq_state=market_state(qqq),
            sector_state=market_state(sector_bars) if sector_bars else "unknown",
            sector_etf=sector,
        )
        if signal is None:
            continue
        trigger_t = bars[index]["t"] - signal.triggered_ago_sec
        if trigger_t in seen:
            continue
        seen.add(trigger_t)
        future = bars[index + 1 :]
        row = {
            "symbol": symbol,
            "when": moment.strftime("%Y-%m-%d %H:%M"),
            "score": round(signal.score, 1),
            "entry": signal.entry_high,
            "stop": signal.stop,
            "target": signal.target,
        }
        keep = False
        for horizon in HORIZONS:
            outcome = _outcome(future, signal.entry_high, signal.stop, signal.target, horizon)
            label = horizon * ENTRY.bar_minutes
            if outcome is None:
                row[f"ret{label}"] = None
                continue
            keep = True
            row[f"ret{label}"] = outcome["return"]
            row[f"stop{label}"] = outcome["stopped"]
            row[f"target{label}"] = outcome["target"]
        if keep:
            trades.append(row)
    return trades


def _summarize(trades: list[dict]) -> None:
    if not trades:
        print("No fresh long setups fired on this sample.")
        return
    print(f"\n{len(trades)} unique triggers (fill assumed at the top of the entry zone)\n")
    print(f"{'When':<18}{'Symbol':<8}{'Score':>7}{'15m':>9}{'30m':>9}{'60m':>9}")
    for trade in trades:
        cells = []
        for minutes in (15, 30, 60):
            value = trade.get(f"ret{minutes}")
            cells.append("—" if value is None else f"{value * 100:+.2f}%")
        print(
            f"{trade['when']:<18}{trade['symbol']:<8}{trade['score']:>7.0f}"
            f"{cells[0]:>9}{cells[1]:>9}{cells[2]:>9}"
        )
    print("\nAverages (stopped trades stay at the stop):")
    for minutes in (15, 30, 60):
        sample = [trade[f"ret{minutes}"] for trade in trades if trade.get(f"ret{minutes}") is not None]
        if not sample:
            continue
        wins = sum(1 for value in sample if value > 0)
        stopped = sum(1 for trade in trades if trade.get(f"stop{minutes}"))
        targeted = sum(1 for trade in trades if trade.get(f"target{minutes}"))
        avg = sum(sample) / len(sample)
        print(
            f"  {minutes:>2} min  n={len(sample):<3}  avg {avg * 100:+.2f}%"
            f"  positive {wins}/{len(sample)}  target-first {targeted}  stop-first {stopped}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay Right Time to Buy signals. Does not trade.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4001)
    parser.add_argument("--client-id", type=int, default=17)
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--symbols", default="", help="Comma-separated tickers. Default: a short liquid sample.")
    parser.add_argument("--market-data-type", type=int, default=3, choices=(1, 3, 4))
    parser.add_argument("--pause", type=float, default=2.0, help="Seconds between historical requests.")
    args = parser.parse_args()

    if args.symbols.strip():
        symbols = [item.strip().upper().replace(".", " ") for item in args.symbols.split(",") if item.strip()]
    else:
        symbols = ["NVDA", "AMD", "AAPL", "MSFT", "META", "AMZN", "JPM", "XOM", "LLY", "CAT"]

    try:
        from ib_insync import IB
    except ImportError:
        from ib_async import IB  # type: ignore

    ib = IB()
    print(f"Connecting read-only to {args.host}:{args.port} (clientId {args.client_id})…")
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, readonly=True, timeout=8)
    except Exception as exc:
        print(f"Could not reach IB Gateway: {exc}")
        print("Start Gateway with the socket API on port 4001, then run this again.")
        return 1
    try:
        ib.reqMarketDataType(args.market_data_type)
        needed = list(dict.fromkeys([*context_symbols(symbols), *symbols]))
        books: dict[str, list[dict]] = {}
        for index, symbol in enumerate(needed):
            if index:
                time.sleep(max(0.5, args.pause))
            try:
                books[symbol] = fetch_bars(ib, symbol, args.days)
                print(f"  {symbol:<6} {len(books[symbol])} bars")
            except Exception as exc:
                print(f"  {symbol:<6} history failed ({exc})")
                books[symbol] = []
        trades = []
        for symbol in symbols:
            if len(books.get(symbol) or []) < 40:
                print(f"Skipping {symbol}: not enough bars.")
                continue
            trades.extend(replay_symbol(symbol, books[symbol], books))
        trades.sort(key=lambda item: item["when"])
        _summarize(trades)
    finally:
        ib.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
