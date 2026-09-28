"""Paper log of Right Time to Buy setups. No orders are sent.

A row is written when a setup first appears. Later marks use the last traded
price already on the tape: stop if last is at or through the stop, otherwise
target, otherwise a time exit at 15:55 ET. Dollars use the same US$2,160
tiered cost model as the backtest.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from backtest.costs import apply_slip, commission, share_count
from backtest.periods import ACCOUNT_USD, FLAT_MINUTE, SLIP_BPS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "outcomes.sqlite"


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


class OutcomeLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS setups (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                day TEXT NOT NULL,
                stop REAL NOT NULL,
                target REAL NOT NULL,
                entry_low REAL,
                entry_high REAL,
                score INTEGER,
                rr REAL,
                reasons TEXT,
                appeared_at TEXT NOT NULL,
                status TEXT NOT NULL,
                exit_price REAL,
                exit_at TEXT,
                net_dollars REAL,
                net_bps REAL,
                UNIQUE(symbol, day, stop, target)
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def observe(self, setups: list[dict[str, Any]], marks: dict[str, float], now: datetime) -> None:
        day = now.date().isoformat()
        for row in setups:
            symbol = str(row.get("symbol") or "")
            stop = _num(row.get("entryStop"))
            target = _num(row.get("entryTarget"))
            if not symbol or stop is None or target is None:
                continue
            self._conn.execute(
                """
                INSERT OR IGNORE INTO setups (
                    symbol, day, stop, target, entry_low, entry_high, score, rr,
                    reasons, appeared_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """,
                (
                    symbol,
                    day,
                    stop,
                    target,
                    _num(row.get("entryLow")),
                    _num(row.get("entryHigh")),
                    int(row["entryScore"]) if row.get("entryScore") is not None else None,
                    _num(row.get("entryRR")),
                    ", ".join(row.get("entryReasons") or []),
                    now.isoformat(timespec="seconds"),
                ),
            )
        self._mark_open(marks, now)
        self._conn.commit()

    def _mark_open(self, marks: dict[str, float], now: datetime) -> None:
        minute = now.hour * 60 + now.minute
        rows = self._conn.execute(
            "SELECT id, symbol, day, stop, target, entry_high FROM setups WHERE status = 'open'"
        ).fetchall()
        for setup_id, symbol, day, stop, target, entry_high in rows:
            last = marks.get(symbol)
            if last is None:
                continue
            status = None
            exit_px = None
            if last <= stop:
                status = "stop"
                exit_px = apply_slip(min(last, stop), "sell", SLIP_BPS)
            elif last >= target:
                status = "target"
                exit_px = apply_slip(target, "sell", SLIP_BPS)
            elif day == now.date().isoformat() and minute >= FLAT_MINUTE + 5:
                status = "time"
                exit_px = apply_slip(last, "sell", SLIP_BPS)
            if status is None or exit_px is None or not entry_high:
                continue
            entry = apply_slip(float(entry_high), "buy", SLIP_BPS)
            shares = share_count(ACCOUNT_USD, entry)
            if shares < 1:
                net = 0.0
                bps = 0.0
            else:
                gross = (exit_px - entry) * shares
                fees = commission(shares, entry, "buy", "tiered") + commission(shares, exit_px, "sell", "tiered")
                net = gross - fees
                bps = net / (entry * shares) * 10_000.0
            self._conn.execute(
                """
                UPDATE setups
                SET status = ?, exit_price = ?, exit_at = ?, net_dollars = ?, net_bps = ?
                WHERE id = ?
                """,
                (status, exit_px, now.isoformat(timespec="seconds"), net, bps, setup_id),
            )

    def summary(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT status, net_dollars, net_bps FROM setups"
        ).fetchall()
        closed = [row for row in rows if row[0] != "open"]
        wins = [row for row in closed if (row[1] or 0) > 0]
        by_status: dict[str, int] = {}
        for status, _net, _bps in rows:
            by_status[status] = by_status.get(status, 0) + 1
        return {
            "open": by_status.get("open", 0),
            "closed": len(closed),
            "winRate": (len(wins) / len(closed)) if closed else None,
            "avgNetDollars": (sum(row[1] or 0 for row in closed) / len(closed)) if closed else None,
            "avgNetBps": (sum(row[2] or 0 for row in closed) / len(closed)) if closed else None,
            "byStatus": by_status,
            "note": "Paper log only. Volume Pulse never places orders.",
        }
