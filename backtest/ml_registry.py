"""The one pre-registered intraday model. Counted by the promotion gate.

Written down before the fit. A threshold inside ``THRESHOLDS_BPS`` is chosen
on the validation window. It is not a second idea.
"""

from __future__ import annotations

ML_BEGIN = "<!-- ML_BEGIN -->"
ML_END = "<!-- ML_END -->"

MODEL_ID = "ml_lgb_60m"
HORIZON_BARS = 12
SEEDS = (7, 11, 21)
THRESHOLDS_BPS = (0.0, 10.0, 20.0, 30.0)
NUM_BOOST_ROUND = 80

FEATURE_COLUMNS = (
    "ret_1",
    "ret_3",
    "ret_6",
    "ret_12",
    "rv_12",
    "rv_36",
    "rvol",
    "vwap_dist",
    "session_pos",
    "tod",
    "dow",
    "gap",
    "prior_ret",
    "prior_range_atr",
    "dist_ma5",
    "xs_rank_ret12",
    "xs_rank_vwap",
    "spy_from_open",
    "spy_vwap_dist",
    "spy_prior_ret",
    "qqq_from_open",
    "qqq_vwap_dist",
    "qqq_prior_ret",
    "resid_12",
)

ML_REGISTRY = (
    {
        "id": MODEL_ID,
        "label": "60-minute forward return from the next open, scaled by prior-day ATR",
        "model": "LightGBM regression, three frozen seeds averaged",
        "thresholds_bps": THRESHOLDS_BPS,
    },
)
