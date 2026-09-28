#!/usr/bin/env python3
"""Fetch read-only IBKR 5-minute bars into ``data/raw5``.

Run this on the Windows PC where IB Gateway is already listening on
127.0.0.1:4001. This VM cannot see that socket. The script never places,
modifies, or previews orders. It opens a read-only client and sends
historical bar requests only.

Examples (from the repo root)::

    python scripts/fetch_history.py --dry-run
    python scripts/fetch_history.py --max-priority 3
    python scripts/fetch_history.py

``--dry-run`` prints the plan and does not connect. A fetch is resumable:
days already stored under ``data/raw5/<SYMBOL>/`` are not requested again.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Dashboard in app/main.py uses clientId 7. Replay uses 17.
DASHBOARD_CLIENT_ID = 7
DEFAULT_CLIENT_ID = 19

HISTORY_START = date(2018, 1, 2)
PANEL_START = date(2021, 12, 23)
HISTORY_END = date(2026, 9, 25)
# Day before the eight stocks currently on disk.
STOCK_BACKFILL_END = date(2021, 12, 22)
# Day before SPY, QQQ, and TSLA currently on disk.
LONG_BACKFILL_END = date(2020, 12, 23)

# Liquid names a US$2,120 account can buy several whole shares of.
# Prices were checked 2026-09-28; see DATA_REQUEST.md. Not the current book.
NEW_TRADEABLE = [
    "JPM",
    "BAC",
    "V",
    "XOM",
    "CVX",
    "JNJ",
    "UNH",
    "WMT",
    "PG",
    "HON",
    "NFLX",
    "ORCL",
]
EXISTING_STOCKS = ["AAPL", "AMD", "AMZN", "GOOGL", "META", "MSFT", "NVDA"]
LONG_HISTORY = ["SPY", "QQQ", "TSLA"]
# Context only. The account does not trade these.
SECTOR_CONTEXT = ["XLK", "XLF", "XLE", "XLV", "XLP", "XLI"]

# IB's 5-minute limit is one week. A 6-day step overlaps that week by a day.
BAR_SIZE = "5 mins"
DURATION = "1 W"
WHAT_TO_SHOW = "TRADES"
USE_RTH = True
KEEP_UP_TO_DATE = False
STEP_DAYS = 6
CHUNK_LOOKBACK_DAYS = 7

# IB paces historical requests at 60 per 10 minutes. Stay under that.
MIN_INTERVAL_SEC = 11.0
PACE_WINDOW_SEC = 600.0
MAX_REQUESTS_PER_WINDOW = 50
PACING_BACKOFF_SEC = 120.0
MAX_ATTEMPTS = 4
REQUEST_TIMEOUT_SEC = 90.0

OPEN_MINUTE = 9 * 60 + 30
CLOSE_MINUTE = 15 * 60 + 55
COLUMNS = ["date", "open", "high", "low", "close", "volume", "average", "barCount"]
LOG_NAME = "_fetch_log.csv"
MIN_DAYS_PRESENT = 4


def new_york() -> ZoneInfo:
    try:
        return ZoneInfo("America/New_York")
    except Exception as exc:  # Windows without tzdata
        raise SystemExit(
            "America/New_York is unavailable. Install it with: pip install tzdata"
        ) from exc


NY = None  # set in main / tests via require_tz


def require_tz() -> ZoneInfo:
    global NY
    if NY is None:
        NY = new_york()
    return NY


@dataclass(frozen=True)
class Job:
    priority: int
    symbol: str
    start: date
    end: date
    role: str


def default_jobs() -> list[Job]:
    """Priority order is the order to upload if the run is split.

    1. New tradeable names on the same dates the eight stocks already have.
    2. Those eight stocks, back to 2018, so training sees 2018Q4 and 2020.
    3. SPY, QQQ, and TSLA over the same gap (they already start in Dec 2020).
    4. Sector ETFs as context on the current sample. Not traded.
    5. The new names back to 2018, so the wider book has one start date.
    """

    jobs = [Job(1, symbol, PANEL_START, HISTORY_END, "tradeable") for symbol in NEW_TRADEABLE]
    jobs += [Job(2, symbol, HISTORY_START, STOCK_BACKFILL_END, "backfill") for symbol in EXISTING_STOCKS]
    jobs += [Job(3, symbol, HISTORY_START, LONG_BACKFILL_END, "backfill") for symbol in LONG_HISTORY]
    jobs += [Job(4, symbol, PANEL_START, HISTORY_END, "context") for symbol in SECTOR_CONTEXT]
    jobs += [Job(5, symbol, HISTORY_START, STOCK_BACKFILL_END, "backfill") for symbol in NEW_TRADEABLE]
    return jobs


def check_client_id(client_id: int) -> None:
    if client_id == DASHBOARD_CLIENT_ID:
        raise ValueError(
            f"clientId {DASHBOARD_CLIENT_ID} is the live dashboard. Use {DEFAULT_CLIENT_ID}."
        )
    if client_id <= 0:
        raise ValueError("clientId must be a positive integer other than 7.")


def chunk_ends(start: date, end: date, step_days: int = STEP_DAYS) -> list[date]:
    """Oldest first. Each end is the last calendar day of one 1-week request."""

    if end < start:
        return []
    ends: list[date] = []
    cursor = end
    while cursor >= start:
        ends.append(cursor)
        cursor -= timedelta(days=step_days)
    ends.reverse()
    return ends


def chunk_sessions(end: date) -> list[date]:
    """Weekdays inside the 1-week window that ends on ``end``."""

    return [
        end - timedelta(days=offset)
        for offset in range(CHUNK_LOOKBACK_DAYS)
        if (end - timedelta(days=offset)).weekday() < 5
    ]


def chunk_covered(present: set[date], end: date, min_days: int = MIN_DAYS_PRESENT) -> bool:
    sessions = chunk_sessions(end)
    if not sessions:
        return False
    have = sum(1 for day in sessions if day in present)
    return have >= min_days


class Pacer:
    """Space historical requests so a 10-minute window stays under the cap."""

    def __init__(
        self,
        min_interval: float = MIN_INTERVAL_SEC,
        window: float = PACE_WINDOW_SEC,
        max_calls: int = MAX_REQUESTS_PER_WINDOW,
        sleep=time.sleep,
        now=time.monotonic,
    ):
        self.min_interval = min_interval
        self.window = window
        self.max_calls = max_calls
        self.sleep = sleep
        self.now = now
        self.calls: deque[float] = deque()

    def wait(self) -> None:
        while True:
            moment = self.now()
            while self.calls and moment - self.calls[0] >= self.window:
                self.calls.popleft()
            delay = 0.0
            if self.calls:
                delay = max(delay, self.min_interval - (moment - self.calls[-1]))
            if len(self.calls) >= self.max_calls:
                delay = max(delay, self.window - (moment - self.calls[0]))
            if delay > 0:
                self.sleep(delay)
                continue
            self.calls.append(self.now())
            return

    def backoff(self, seconds: float = PACING_BACKOFF_SEC) -> None:
        self.sleep(seconds)
        self.calls.append(self.now())


def load_dates(root: Path, symbol: str) -> set[date]:
    folder = root / symbol
    if not folder.is_dir():
        return set()
    found: set[date] = set()
    for path in sorted(folder.glob("*.parquet")):
        frame = pd.read_parquet(path, columns=["date"])
        if frame.empty:
            continue
        stamps = pd.to_datetime(frame["date"], utc=True).dt.tz_convert(require_tz())
        found.update(stamps.dt.date.tolist())
    return found


def load_empty_chunks(root: Path) -> set[tuple[str, date]]:
    path = root / LOG_NAME
    if not path.exists():
        return set()
    found: set[tuple[str, date]] = set()
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") != "empty":
                continue
            found.add((row["symbol"], date.fromisoformat(row["chunk_end"])))
    return found


def append_log(root: Path, symbol: str, chunk_end: date, rows: int, status: str) -> None:
    path = root / LOG_NAME
    root.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["symbol", "chunk_end", "rows", "status"]
        )
        if new_file:
            writer.writeheader()
        writer.writerow(
            {
                "symbol": symbol,
                "chunk_end": chunk_end.isoformat(),
                "rows": rows,
                "status": status,
            }
        )


def missing_chunks(
    present: set[date],
    start: date,
    end: date,
    symbol: str,
    empties: set[tuple[str, date]],
) -> list[date]:
    out = []
    for chunk_end in chunk_ends(start, end):
        if chunk_covered(present, chunk_end):
            continue
        if (symbol, chunk_end) in empties:
            continue
        out.append(chunk_end)
    return out


def _stamp(value, assume_utc: bool) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(stamp):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC" if assume_utc else require_tz())
    return stamp.tz_convert(require_tz())


def bars_to_frame(bars, start: date, end: date, seen: set[str], assume_utc: bool = True) -> pd.DataFrame:
    """Keep RTH 5-minute bars inside the job, in the raw5 column layout."""

    rows = []
    for bar in bars or []:
        stamp = _stamp(getattr(bar, "date", None), assume_utc)
        if stamp is None:
            continue
        day = stamp.date()
        if day < start or day > end or day.weekday() >= 5:
            continue
        minute = stamp.hour * 60 + stamp.minute
        if minute < OPEN_MINUTE or minute > CLOSE_MINUTE or minute % 5 != 0:
            continue
        key = stamp.strftime("%Y-%m-%d %H:%M")
        if key in seen:
            continue
        close = _float(getattr(bar, "close", None))
        if close is None or close <= 0:
            continue
        open_px = _float(getattr(bar, "open", None)) or close
        high = _float(getattr(bar, "high", None)) or max(open_px, close)
        low = _float(getattr(bar, "low", None)) or min(open_px, close)
        volume = _float(getattr(bar, "volume", None))
        average = _float(getattr(bar, "average", None)) or close
        bar_count = getattr(bar, "barCount", 0)
        try:
            bar_count = int(bar_count or 0)
        except (TypeError, ValueError):
            bar_count = 0
        if volume is None or volume < 0:
            volume = 0.0
        rows.append(
            {
                "date": stamp,
                "open": open_px,
                "high": max(high, open_px, close),
                "low": min(low, open_px, close),
                "close": close,
                "volume": volume,
                "average": average,
                "barCount": bar_count,
            }
        )
        seen.add(key)
    frame = pd.DataFrame(rows, columns=COLUMNS)
    return _normalize(frame)


def _float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        frame = pd.DataFrame(columns=COLUMNS)
        frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(require_tz())
        frame["date"] = frame["date"].astype("datetime64[us, US/Eastern]")
        for column in ("open", "high", "low", "close", "volume", "average"):
            frame[column] = frame[column].astype("float64")
        frame["barCount"] = frame["barCount"].astype("int64")
        return frame
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], utc=True).dt.tz_convert(require_tz())
    out["date"] = out["date"].astype("datetime64[us, US/Eastern]")
    for column in ("open", "high", "low", "close", "volume", "average"):
        out[column] = out[column].astype("float64")
    out["barCount"] = out["barCount"].astype("int64")
    return out.sort_values("date").reset_index(drop=True)


def write_chunk(folder: Path, frame: pd.DataFrame) -> Path:
    """Write ``YYYYMMDD.parquet`` named by the last bar. Merge if it exists."""

    if frame.empty:
        raise ValueError("refusing to write an empty chunk")
    folder.mkdir(parents=True, exist_ok=True)
    last = pd.Timestamp(frame["date"].iloc[-1])
    path = folder / f"{last.strftime('%Y%m%d')}.parquet"
    if path.exists():
        old = pd.read_parquet(path)
        frame = pd.concat([old, frame], ignore_index=True)
        frame = frame.drop_duplicates(subset=["date"]).sort_values("date")
        frame = _normalize(frame)
    frame.to_parquet(path, index=False)
    return path


def classify_errors(errors: list[tuple[int, str]]) -> str:
    """Map Gateway error strings to pacing, empty, unknown, retry, or ok."""

    if not errors:
        return "ok"
    texts = " ".join(message.lower() for _, message in errors)
    codes = {code for code, _ in errors}
    if "pacing" in texts:
        return "pacing"
    if 200 in codes or "no security definition" in texts:
        return "unknown"
    if "no market data permissions" in texts:
        return "permissions"
    if "no data" in texts:
        return "empty"
    # Farm status lines are not failures.
    informational = {2103, 2104, 2105, 2106, 2107, 2108, 2119, 2158}
    if codes <= informational:
        return "ok"
    return "retry"


def _load_ib():
    try:
        from ib_insync import IB, Stock
    except ImportError:
        from ib_async import IB, Stock  # type: ignore
    return IB, Stock


def connect_history_only(host: str, port: int, client_id: int, timeout: float):
    """Open the socket without requesting orders, positions, or executions.

    ``IB.connect(readonly=True)`` still asks for positions, account updates,
    and executions. This path only completes the API handshake.
    """

    check_client_id(client_id)
    IB, _stock = _load_ib()
    ib = IB()
    ib._run(ib.client.connectAsync(host, port, client_id, timeout))
    if not ib.client.isReady():
        ib.disconnect()
        raise ConnectionError("Gateway socket did not become ready")
    return ib


def request_week(ib, contract, chunk_end: date, errors: list[tuple[int, str]]):
    errors.clear()
    if KEEP_UP_TO_DATE:
        raise RuntimeError("keepUpToDate would subscribe to live bars")
    return ib.reqHistoricalData(
        contract,
        endDateTime=f"{chunk_end:%Y%m%d} 20:00:00 US/Eastern",
        durationStr=DURATION,
        barSizeSetting=BAR_SIZE,
        whatToShow=WHAT_TO_SHOW,
        useRTH=USE_RTH,
        formatDate=2,
        keepUpToDate=False,
        timeout=REQUEST_TIMEOUT_SEC,
    )


def fetch_jobs(ib, jobs: list[Job], root: Path, pacer: Pacer) -> int:
    _, Stock = _load_ib()
    errors: list[tuple[int, str]] = []

    def on_error(req_id, code, message, contract=None):
        errors.append((int(code), str(message)))

    ib.errorEvent += on_error
    written = 0
    try:
        for job in jobs:
            present = load_dates(root, job.symbol)
            empties = load_empty_chunks(root)
            chunks = missing_chunks(present, job.start, job.end, job.symbol, empties)
            print(
                f"{job.symbol:<6} priority {job.priority}  {job.start} .. {job.end}"
                f"  {len(chunks)} requests",
                flush=True,
            )
            if not chunks:
                continue
            contract = Stock(job.symbol, "SMART", "USD")
            seen = _seen_keys(root, job.symbol)
            for chunk_end in chunks:
                status = _fetch_one(ib, contract, job, chunk_end, seen, root, pacer, errors)
                if status == "unknown" or status == "permissions":
                    print(
                        f"  stopping {job.symbol}: Gateway returned {status}.",
                        flush=True,
                    )
                    break
                if status == "ok":
                    written += 1
    finally:
        ib.errorEvent -= on_error
    return written


def _seen_keys(root: Path, symbol: str) -> set[str]:
    folder = root / symbol
    keys: set[str] = set()
    if not folder.is_dir():
        return keys
    for path in folder.glob("*.parquet"):
        frame = pd.read_parquet(path, columns=["date"])
        if frame.empty:
            continue
        stamps = pd.to_datetime(frame["date"], utc=True).dt.tz_convert(require_tz())
        keys.update(stamps.dt.strftime("%Y-%m-%d %H:%M").tolist())
    return keys


def _fetch_one(ib, contract, job: Job, chunk_end: date, seen: set[str], root: Path, pacer: Pacer, errors: list) -> str:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        pacer.wait()
        try:
            bars = request_week(ib, contract, chunk_end, errors)
        except Exception as exc:
            errors.append((0, str(exc)))
            bars = []
        kind = classify_errors(errors)
        if kind == "pacing" or kind == "retry":
            print(
                f"  {job.symbol} {chunk_end} {kind} (attempt {attempt}); sleeping",
                flush=True,
            )
            pacer.backoff()
            continue
        if kind in {"unknown", "permissions"}:
            append_log(root, job.symbol, chunk_end, 0, kind)
            return kind
        frame = bars_to_frame(bars, job.start, job.end, seen, assume_utc=True)
        if frame.empty:
            append_log(root, job.symbol, chunk_end, 0, "empty")
            print(f"  {job.symbol} {chunk_end} empty", flush=True)
            return "empty"
        path = write_chunk(root / job.symbol, frame)
        append_log(root, job.symbol, chunk_end, len(frame), "ok")
        print(f"  {path.name}  {len(frame)} bars", flush=True)
        return "ok"
    append_log(root, job.symbol, chunk_end, 0, "error")
    print(f"  {job.symbol} {chunk_end} failed after {MAX_ATTEMPTS} attempts", flush=True)
    return "error"


def plan_rows(root: Path, jobs: list[Job]) -> list[dict]:
    empties = load_empty_chunks(root) if root.exists() else set()
    cache: dict[str, set[date]] = {}
    rows = []
    for job in jobs:
        if job.symbol not in cache:
            cache[job.symbol] = load_dates(root, job.symbol) if root.exists() else set()
        chunks = missing_chunks(cache[job.symbol], job.start, job.end, job.symbol, empties)
        rows.append(
            {
                "priority": job.priority,
                "symbol": job.symbol,
                "start": job.start.isoformat(),
                "end": job.end.isoformat(),
                "role": job.role,
                "requests": len(chunks),
            }
        )
    return rows


def print_plan(rows: list[dict], interval: float) -> None:
    print(
        f"{'pri':>3}  {'symbol':<6}  {'start':<12}  {'end':<12}  {'requests':>8}  role",
        flush=True,
    )
    total = 0
    by_priority: dict[int, int] = {}
    for row in rows:
        total += row["requests"]
        by_priority[row["priority"]] = by_priority.get(row["priority"], 0) + row["requests"]
        print(
            f"{row['priority']:>3}  {row['symbol']:<6}  {row['start']:<12}  {row['end']:<12}"
            f"  {row['requests']:>8}  {row['role']}",
            flush=True,
        )
    hours = total * interval / 3600.0
    print(
        f"\n{total} historical requests, about {hours:.1f} hours at {interval:.0f}s spacing.",
        flush=True,
    )
    running = 0
    for priority in sorted(by_priority):
        running += by_priority[priority]
        print(
            f"  through priority {priority}: {running} requests,"
            f" about {running * interval / 3600.0:.1f} hours",
            flush=True,
        )
    print("No orders. Bar size 5 mins, TRADES, regular hours only.", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only IBKR 5-minute history into data/raw5. Does not trade."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4001)
    parser.add_argument("--client-id", type=int, default=DEFAULT_CLIENT_ID)
    parser.add_argument("--root", type=Path, default=ROOT / "data" / "raw5")
    parser.add_argument("--max-priority", type=int, default=5, choices=(1, 2, 3, 4, 5))
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and do not connect.")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    require_tz()
    try:
        check_client_id(args.client_id)
    except ValueError as exc:
        print(exc, flush=True)
        return 2

    jobs = [job for job in default_jobs() if job.priority <= args.max_priority]
    rows = plan_rows(args.root, jobs)
    print_plan(rows, MIN_INTERVAL_SEC)
    if args.dry_run:
        print("Dry run: Gateway was not contacted.", flush=True)
        return 0
    if sum(row["requests"] for row in rows) == 0:
        print("Nothing to fetch.", flush=True)
        return 0

    print(
        f"Connecting read-only to {args.host}:{args.port} (clientId {args.client_id}).",
        flush=True,
    )
    try:
        ib = connect_history_only(args.host, args.port, args.client_id, args.timeout)
    except Exception as exc:
        print(f"Could not reach IB Gateway: {exc}", flush=True)
        print("Start Gateway on this PC with the socket API on port 4001, then run this again.", flush=True)
        return 1
    try:
        fetch_jobs(ib, jobs, args.root, Pacer())
    finally:
        ib.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
