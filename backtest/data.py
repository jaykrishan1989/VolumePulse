"""Load IBKR 5-minute RTH bars saved as one parquet chunk per symbol.

The parquet files live outside git (``data/raw5`` or ``RTTB_RAW``). Each file
is a few weeks of bars with columns date, open, high, low, close, volume.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from app.entry import NY

CANDIDATES = ["AAPL", "AMD", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA"]
CONTEXT = ["SPY", "QQQ"]


def raw_root() -> Path:
    env = os.environ.get("RTTB_RAW")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "data" / "raw5"


def load_symbol(symbol: str, root: Path | None = None) -> pd.DataFrame:
    folder = (root or raw_root()) / symbol
    files = sorted(folder.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquet bars for {symbol} under {folder}")
    frames = [pd.read_parquet(path) for path in files]
    frame = pd.concat(frames, ignore_index=True)
    frame["date"] = pd.to_datetime(frame["date"], utc=True).dt.tz_convert(NY)
    frame = frame.drop_duplicates(subset=["date"]).sort_values("date")
    frame = frame[frame["date"].dt.dayofweek < 5]
    return frame.reset_index(drop=True)


def sessions(frame: pd.DataFrame) -> list[tuple[date, pd.DataFrame]]:
    grouped = []
    for day, chunk in frame.groupby(frame["date"].dt.date, sort=True):
        grouped.append((day, chunk.reset_index(drop=True)))
    return grouped


def bars_from_frame(frame: pd.DataFrame) -> list[dict]:
    out = []
    for row in frame.itertuples(index=False):
        moment = row.date.to_pydatetime()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=NY)
        bar = {
            "t": int(moment.timestamp()),
            "dt": moment,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
            "minute": moment.hour * 60 + moment.minute,
        }
        average = getattr(row, "average", None)
        if average is not None:
            try:
                value = float(average)
            except (TypeError, ValueError):
                value = float("nan")
            if value == value:
                bar["average"] = value
        out.append(bar)
    return out


def as_of(moment: datetime) -> datetime:
    from datetime import timedelta

    return moment + timedelta(minutes=5)
