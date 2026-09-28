"""IBKR-style commissions and slippage for a small US stock ticket.

Assumptions, stated so the backtest can be audited:

- Tiered: max(US$0.35, US$0.0035 per share), capped at 1% of notional.
- Fixed: max(US$1.00, US$0.005 per share), capped at 1% of notional.
- Sells add an SEC fee of US$27.80 per US$1M and FINRA TAF of US$0.000166
  per share (capped at US$8.30). These rates move; they are the schedule used
  in the 2026 research notes.
- Slippage is charged by worsening the fill price, not as a second fee.
"""

from __future__ import annotations


def commission(shares: float, price: float, side: str, schedule: str = "tiered") -> float:
    shares = float(shares)
    price = float(price)
    if shares <= 0 or price <= 0:
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


def round_trip_commission(shares: float, entry: float, exit_px: float, schedule: str = "tiered") -> float:
    return commission(shares, entry, "buy", schedule) + commission(shares, exit_px, "sell", schedule)


def apply_slip(price: float, side: str, slip_bps: float) -> float:
    """Buy fills higher. Sell fills lower."""
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
