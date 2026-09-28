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
                delayed INTEGER,
                data_type INTEGER,
                lag_sec REAL,
                withhold TEXT,
                UNIQUE(symbol, day, stop, target)
            )
            """
        )
        self._ensure_columns()
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                day TEXT NOT NULL,
                action TEXT NOT NULL,
                price REAL,
                stop REAL,
                target REAL,
                score INTEGER,
                delayed INTEGER,
                lag_sec REAL,
                appeared_at TEXT NOT NULL,
                status TEXT NOT NULL,
                exit_price REAL,
                exit_at TEXT,
                net_dollars REAL,
                net_bps REAL
            )
            """
        )
        self._conn.commit()

    def _ensure_columns(self) -> None:
        present = {row[1] for row in self._conn.execute("PRAGMA table_info(setups)")}
        for name, decl in (
            ("delayed", "INTEGER"),
            ("data_type", "INTEGER"),
            ("lag_sec", "REAL"),
            ("withhold", "TEXT"),
        ):
            if name not in present:
                self._conn.execute(f"ALTER TABLE setups ADD COLUMN {name} {decl}")

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
            withhold = row.get("entryWithhold") or None
            delayed = 1 if row.get("entryDelayed") else 0
            if withhold and ("delayed" in str(withhold) or "stale" in str(withhold)):
                delayed = 1
            status = "withheld" if withhold else "open"
            self._conn.execute(
                """
                INSERT OR IGNORE INTO setups (
                    symbol, day, stop, target, entry_low, entry_high, score, rr,
                    reasons, appeared_at, status, delayed, data_type, lag_sec, withhold
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    status,
                    delayed,
                    _num(row.get("entryDataType")),
                    _num(row.get("entryLagSec")),
                    withhold,
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
        closed = [row for row in rows if row[0] in ("stop", "target", "time")]
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
            "signals": self.signal_summary(),
        }

    def record_signals(self, events: list[dict[str, Any]], now: datetime) -> None:
        """Log a BUY and its later SELL, STOP, or FLAT. This is not an order."""
        day = now.date().isoformat()
        for event in events:
            symbol = str(event.get("symbol") or "")
            action = str(event.get("action") or "")
            if not symbol or action not in {"BUY", "SELL", "STOP", "FLAT"}:
                continue
            price = _num(event.get("price"))
            self._conn.execute(
                """
                INSERT INTO signals (
                    symbol, day, action, price, stop, target, score, delayed, lag_sec,
                    appeared_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    day,
                    action,
                    price,
                    _num(event.get("stop")),
                    _num(event.get("target")),
                    int(event["score"]) if event.get("score") is not None else None,
                    1 if event.get("delayed") else 0,
                    _num(event.get("lagSec")),
                    event.get("at") or now.isoformat(timespec="seconds"),
                    "open" if action == "BUY" else action.lower(),
                ),
            )
            if action != "BUY":
                self._close_buy(symbol, day, action.lower(), price, now)
        self._conn.commit()

    def _close_buy(self, symbol: str, day: str, status: str, price: float | None, now: datetime) -> None:
        row = self._conn.execute(
            """
            SELECT id, price FROM signals
            WHERE symbol = ? AND day = ? AND action = 'BUY' AND status = 'open'
            ORDER BY id DESC LIMIT 1
            """,
            (symbol, day),
        ).fetchone()
        if row is None or price is None or not row[1]:
            return
        from backtest.spells import ACCOUNT_USD as SIGNAL_ACCOUNT

        entry = apply_slip(float(row[1]), "buy", SLIP_BPS)
        exit_px = apply_slip(float(price), "sell", SLIP_BPS)
        shares = share_count(SIGNAL_ACCOUNT, entry)
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
            UPDATE signals
            SET status = ?, exit_price = ?, exit_at = ?, net_dollars = ?, net_bps = ?
            WHERE id = ?
            """,
            (status, exit_px, now.isoformat(timespec="seconds"), net, bps, row[0]),
        )

    def recent_signals(self, day: str, limit: int = 12) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT action, symbol, price, stop, score, appeared_at, status
            FROM signals WHERE day = ? ORDER BY id DESC LIMIT ?
            """,
            (day, limit),
        ).fetchall()
        notes = {
            "BUY": "Enter at the next bar open. Confirm manually. Not an order.",
            "SELL": "Exit at the next bar open. Confirm manually. Not an order.",
            "STOP": "Protective stop. Confirm the exit manually. Not an order.",
            "FLAT": "Flat by 15:55 ET. Confirm the exit manually. Not an order.",
        }
        out = []
        for action, symbol, price, stop, score, appeared_at, _status in reversed(rows):
            out.append(
                {
                    "action": action,
                    "symbol": symbol,
                    "price": price,
                    "stop": stop,
                    "score": score,
                    "at": appeared_at,
                    "note": notes.get(action, "Confirm manually. Not an order."),
                    "simulated": False,
                }
            )
        return out

    def signal_summary(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT status, net_dollars, net_bps FROM signals WHERE action = 'BUY'"
        ).fetchall()
        closed = [row for row in rows if row[0] in ("sell", "stop", "flat")]
        wins = [row for row in closed if (row[1] or 0) > 0]
        return {
            "open": sum(1 for row in rows if row[0] == "open"),
            "closed": len(closed),
            "winRate": (len(wins) / len(closed)) if closed else None,
            "avgNetDollars": (sum(row[1] or 0 for row in closed) / len(closed)) if closed else None,
            "avgNetBps": (sum(row[2] or 0 for row in closed) / len(closed)) if closed else None,
            "note": "Signals only. Confirm every trade. Volume Pulse never places orders.",
        }

    def closed_signal_bps(self) -> list[float]:
        """Net basis points of closed BUY signals, oldest first. Paper only."""
        rows = self._conn.execute(
            """
            SELECT net_bps FROM signals
            WHERE action = 'BUY' AND status IN ('sell', 'stop', 'flat')
            ORDER BY id
            """
        ).fetchall()
        return [float(row[0] or 0.0) for row in rows]
