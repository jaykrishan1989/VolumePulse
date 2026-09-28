"""Optional desktop/phone ping when a setup appears.

Set ``ALERT_WEBHOOK_URL`` and/or ``ALERT_NTFY_TOPIC``. With neither set, this
does nothing. The payload is a notice, never an order, and this module does
not connect to a broker.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

_seen: set[str] = set()


def _key(row: dict[str, Any]) -> str:
    return f"{row.get('symbol')}|{row.get('entryStop')}|{row.get('entryTarget')}"


def _post(url: str, body: bytes, headers: dict[str, str]) -> None:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=2.0) as response:
        response.read()


def notify_setups(rows: list[dict[str, Any]]) -> None:
    """Ping once per setup. Errors are swallowed so the feed keeps running."""
    url = (os.environ.get("ALERT_WEBHOOK_URL") or "").strip()
    topic = (os.environ.get("ALERT_NTFY_TOPIC") or "").strip()
    if not url and not topic:
        return
    for row in rows:
        if row.get("entryScore") is None:
            continue
        key = _key(row)
        if key in _seen:
            continue
        _seen.add(key)
        notice = {
            "text": (
                f"{row.get('symbol')} scored {row.get('entryScore')} "
                f"stop {row.get('entryStop')} target {row.get('entryTarget')}. "
                "Not an order. Volume Pulse does not place orders."
            ),
            "symbol": row.get("symbol"),
            "score": row.get("entryScore"),
        }
        raw = json.dumps(notice).encode("utf-8")
        try:
            if topic:
                _post(
                    f"https://ntfy.sh/{topic}",
                    notice["text"].encode("utf-8"),
                    {"Title": "Volume Pulse setup", "Content-Type": "text/plain"},
                )
            if url:
                _post(url, raw, {"Content-Type": "application/json"})
        except Exception:
            continue


def reset_for_tests() -> None:
    _seen.clear()
