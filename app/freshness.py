"""Hide Right Time to Buy rows that are not a live, in-range price.

IBKR market data type 3 or 4 is the delayed tape (about 15 minutes behind).
A 5-minute bar is stale once its close is more than a minute behind the
clock. A last price already through the stop or the target is not an entry.
This module never places orders.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

FRESH_SECONDS = 60
DELAYED_TYPES = frozenset({3, 4})


def bar_close_lag(bar_epoch: float, now: datetime, bar_minutes: int = 5) -> float:
    """Seconds since the bar's close. A bar that is still forming has lag 0.

    IB stamps intraday bars at the open of the bar, so the close is one bar
    later. Comparing the raw open to the clock would mark every live bar
    stale for four minutes out of five.
    """
    close_at = float(bar_epoch) + int(bar_minutes) * 60
    return max(0.0, now.timestamp() - close_at)


def quote_lag(quote_epoch: float | None, now: datetime) -> float | None:
    if quote_epoch is None:
        return None
    return max(0.0, now.timestamp() - float(quote_epoch))


def _through(last: float | None, stop: float | None, target: float | None) -> str | None:
    if last is None or stop is None or target is None:
        return "no_price"
    if last <= stop:
        return "through_stop"
    if last >= target:
        return "through_target"
    return None


def classify_setup(
    *,
    data_type: int | None,
    bar_epoch: float | None,
    quote_epoch: float | None,
    last: float | None,
    stop: float | None,
    target: float | None,
    now: datetime,
    bar_minutes: int = 5,
) -> dict[str, Any]:
    """Return whether the row may be listed, and why it was withheld."""
    reasons: list[str] = []
    delayed_type = data_type in DELAYED_TYPES
    if delayed_type:
        reasons.append("delayed")
    bar_age = bar_close_lag(bar_epoch, now, bar_minutes) if bar_epoch else None
    if bar_age is not None and bar_age > FRESH_SECONDS:
        reasons.append("stale")
    q_lag = quote_lag(quote_epoch, now)
    if q_lag is not None and q_lag > FRESH_SECONDS:
        if "stale" not in reasons and "delayed" not in reasons:
            reasons.append("stale")
    breach = _through(last, stop, target)
    if breach:
        reasons.append(breach)
    lags = [value for value in (bar_age, q_lag) if value is not None]
    return {
        "list": not reasons,
        "withhold": "+".join(reasons) if reasons else None,
        "delayed": bool(delayed_type or (bar_age is not None and bar_age > FRESH_SECONDS) or (q_lag is not None and q_lag > FRESH_SECONDS)),
        "dataType": data_type,
        "lagSec": max(lags) if lags else None,
    }


def delay_banner(data_type: int | None, withheld: list[dict[str, Any]]) -> dict[str, Any]:
    """Payload for the prominent banner. Inactive when nothing is delayed or stale."""
    delayed_feed = data_type in DELAYED_TYPES or any(
        "delayed" in str(row.get("entryWithhold") or "") for row in withheld
    )
    stale_names = [
        str(row.get("symbol"))
        for row in withheld
        if row.get("symbol") and "stale" in str(row.get("entryWithhold") or "")
    ]
    if delayed_feed:
        return {
            "active": True,
            "kind": "delayed",
            "message": (
                "DELAYED DATA. IBKR is sending delayed quotes (market data type 3 or 4, "
                "about 15 minutes behind the market). Right Time to Buy will not list a "
                "setup on that tape. The real price can already be through the stop."
            ),
        }
    if stale_names:
        shown = ", ".join(stale_names[:6])
        return {
            "active": True,
            "kind": "stale",
            "message": (
                f"STALE TAPE. {shown} last bar is more than a minute behind the clock. "
                "Those Right Time to Buy setups are hidden."
            ),
        }
    return {"active": False, "kind": None, "message": ""}


def annotate_setup(
    row: dict[str, Any],
    *,
    data_type: int | None,
    bar_epoch: float | None,
    quote_epoch: float | None,
    now: datetime,
    bar_minutes: int = 5,
) -> dict[str, Any]:
    """Copy a scored row and attach the delay fields the paper log stores."""
    last = _float(row.get("last"))
    found = classify_setup(
        data_type=data_type,
        bar_epoch=bar_epoch,
        quote_epoch=quote_epoch,
        last=last,
        stop=_float(row.get("entryStop")),
        target=_float(row.get("entryTarget")),
        now=now,
        bar_minutes=bar_minutes,
    )
    annotated = dict(row)
    annotated["entryDelayed"] = 1 if found["delayed"] else 0
    annotated["entryDataType"] = found["dataType"]
    annotated["entryLagSec"] = found["lagSec"]
    annotated["entryWithhold"] = found["withhold"]
    return annotated


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number
