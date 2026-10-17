"""S&P 500 names in the $10–$50 pocket — established, generally profitable businesses."""

from __future__ import annotations

from app.sp500 import ib_symbol, is_sp500

PRICE_MIN = 10.0
PRICE_MAX = 50.0

# Liquid S&P 500 operators that often trade in this band (banks, telecom, energy,
# staples, airlines, hardware). Live last still has to print $10–$50 to appear.
QUALITY_MID = [
    "T", "VZ", "PFE", "BMY", "MO", "KMI", "WBD", "F", "GM", "BAC",
    "USB", "PNC", "TFC", "CFG", "HBAN", "RF", "KEY", "FITB", "WFC", "C",
    "SLB", "HAL", "BKR", "OXY", "DVN", "MRO", "APA", "CTRA", "EQT", "KHC",
    "K", "GIS", "CPB", "TAP", "HRL", "SJM", "IP", "IPG", "OMC", "HST",
    "DAL", "UAL", "AAL", "LUV", "CCL", "NCLH", "MGM", "AES", "CNP", "PPL",
    "FE", "EXC", "NI", "NRG", "HPE", "HPQ", "ON", "SWKS", "QRVO", "CSCO",
    "INTC", "PARA", "HAS", "KMX", "MOS", "FCX", "NEM", "WMB", "KDP", "KR",
]


def in_price_band(price: float | None) -> bool:
    return price is not None and PRICE_MIN <= price <= PRICE_MAX


def quality_mid_symbols() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for symbol in QUALITY_MID:
        if not is_sp500(symbol):
            continue
        key = ib_symbol(symbol)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out
