"""Published backtest stats for the Right Time to Buy tab.

The file is written by ``python -m backtest.run_search`` after the locked
holdout. The web app only reads it.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "research_stats.json"


@lru_cache(maxsize=1)
def load_research() -> dict:
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
