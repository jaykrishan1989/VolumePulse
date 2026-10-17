"""Locked sample splits. Holdout starts 2026-04-01 and is evaluated once."""

from __future__ import annotations

from datetime import date

# In-sample description only. Configs are not chosen on this window.
TRAIN_START = date(2022, 1, 1)
TRAIN_END = date(2024, 6, 30)
# Selection window. The single published config is chosen here.
VALIDATE_START = date(2024, 7, 1)
VALIDATE_END = date(2026, 3, 31)
# Locked. Do not use this to pick, retune, or discard a config.
HOLDOUT_START = date(2026, 4, 1)
HOLDOUT_END = date(2026, 12, 31)

ACCOUNT_USD = 2160.0
SLIP_BPS = 2.0
MAX_HOLD_BARS_60 = 12
FLAT_MINUTE = 15 * 60 + 50  # bar that opens at 15:50 closes at 15:55
