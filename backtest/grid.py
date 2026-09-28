"""Pre-registered configs. Do not add cells after looking at validation or holdout.

Every config is a filter on the same baseline scan, plus an exit. The live
scorer is not re-fit. Selection uses validation mean net bps only.
"""

from __future__ import annotations

# Minutes from midnight, America/New_York. 10:00 is 600, 12:00 is 720, 14:00 is 840.
SPECS: list[dict] = [
    {"id": "baseline", "exit": "bracket", "max_bars": 12},
    {"id": "rvol_1", "min_rvol": 1.0, "exit": "bracket", "max_bars": 12},
    {"id": "rvol_1_5", "min_rvol": 1.5, "exit": "bracket", "max_bars": 12},
    {"id": "vwap_reclaim", "require_vwap_reclaim": True, "exit": "bracket", "max_bars": 12},
    {"id": "above_vwap", "require_above_vwap": True, "exit": "bracket", "max_bars": 12},
    {"id": "rr_2", "min_rr": 2.0, "exit": "bracket", "max_bars": 12},
    {"id": "regime", "require_spy_qqq_vwap": True, "exit": "bracket", "max_bars": 12},
    {"id": "morning", "minute_from": 600, "minute_to": 720, "exit": "bracket", "max_bars": 12},
    {"id": "prior5_up", "min_prior5": 0.0, "exit": "bracket", "max_bars": 12},
    {"id": "score_80", "min_score": 80.0, "exit": "bracket", "max_bars": 12},
    {"id": "exit_1r", "exit": "r_multiple", "r_multiple": 1.0, "max_bars": 12},
    {"id": "exit_30m", "exit": "time", "max_bars": 6},
    {"id": "exit_trail", "exit": "trail", "atr_mult": 1.0, "max_bars": 12},
    {
        "id": "bundle",
        "min_rvol": 1.2,
        "require_vwap_reclaim": True,
        "require_spy_qqq_vwap": True,
        "min_rr": 1.5,
        "minute_from": 600,
        "minute_to": 840,
        "exit": "r_multiple",
        "r_multiple": 1.0,
        "max_bars": 12,
    },
    {
        "id": "strict_morning",
        "min_rvol": 1.5,
        "require_above_vwap": True,
        "require_spy_qqq_vwap": True,
        "min_rr": 2.0,
        "minute_from": 600,
        "minute_to": 720,
        "min_prior5": 0.0,
        "exit": "bracket",
        "max_bars": 12,
    },
]
