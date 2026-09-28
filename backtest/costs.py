"""Execution costs for the owner's account.

IBKR is the market-data source. It is not the broker. Fills are assumed on a
zero-commission platform. The only cost in the default model is slippage of at
least 2 bp per side, charged by worsening the next bar's open.

``app/cost_model.json`` is the config. ``schedule`` there is ``zero``, which
charges no broker commission and no regulatory fee. Slippage is applied by
``apply_slip``, not inside ``commission``.

``tiered`` and ``fixed`` remain as explicit historical schedules from the
earlier IBKR-assumption notes. They are not the default and they are not a
reported column.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "app" / "cost_model.json"

COSTS_BEGIN = "<!-- COSTS_BEGIN -->"
COSTS_END = "<!-- COSTS_END -->"
COSTS_CHANGELOG_BEGIN = "<!-- COSTS_CHANGELOG_BEGIN -->"
COSTS_CHANGELOG_END = "<!-- COSTS_CHANGELOG_END -->"


def load_cost_model() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


_MODEL = load_cost_model()
PRIMARY_SCHEDULE = str(_MODEL["schedule"])
SLIP_BPS_MIN = float(_MODEL["slipBpsPerSide"])


def commission(shares: float, price: float, side: str, schedule: str | None = None) -> float:
    shares = float(shares)
    price = float(price)
    if shares <= 0 or price <= 0:
        return 0.0
    if schedule is None:
        schedule = PRIMARY_SCHEDULE
    if schedule == "zero":
        return 0.0
    notional = shares * price
    if schedule == "tiered":
        fee = max(0.35, 0.0035 * shares)
    elif schedule == "fixed":
        fee = max(1.0, 0.005 * shares)
    else:
        raise ValueError(f"Unknown commission schedule '{schedule}'")
    fee = min(fee, 0.01 * notional)
    if side == "sell":
        fee += notional * 27.80 / 1_000_000.0
        fee += min(8.30, shares * 0.000166)
    return fee


def round_trip_commission(
    shares: float,
    entry: float,
    exit_px: float,
    schedule: str | None = None,
) -> float:
    return commission(shares, entry, "buy", schedule) + commission(shares, exit_px, "sell", schedule)


def apply_slip(price: float, side: str, slip_bps: float) -> float:
    """Buy fills higher. Sell fills lower.

    Evaluations use at least ``SLIP_BPS_MIN`` from the cost config. A caller
    can still pass a smaller number when a test is isolating something else.
    """
    slip = slip_bps / 10_000.0
    if side == "buy":
        return price * (1.0 + slip)
    if side == "sell":
        return price * (1.0 - slip)
    raise ValueError(side)


def share_count(equity: float, entry_price: float) -> int:
    if entry_price <= 0 or equity <= 0:
        return 0
    return int(equity // entry_price)
