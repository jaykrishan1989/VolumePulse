"""Major US-listed ETFs grouped by industry / asset class."""

from __future__ import annotations

from app.sectors import SECTORS

# Display order for the industry table.
INDUSTRY_ORDER = [
    "Broad market",
    "Technology",
    "Semiconductors",
    "Communication",
    "Health care",
    "Biotech",
    "Financials",
    "Energy",
    "Industrials",
    "Consumer",
    "Real estate",
    "Materials",
    "Utilities",
    "Treasuries & credit",
    "Commodities",
    "International",
]

# (symbol, name, typical last for demo, typical avg daily volume)
_ETF_ROWS: list[tuple[str, str, str, float, float]] = [
    ("Broad market", "SPY", "S&P 500", 562.0, 70e6),
    ("Broad market", "QQQ", "Nasdaq 100", 478.0, 45e6),
    ("Broad market", "DIA", "Dow Jones", 430.0, 4e6),
    ("Broad market", "IWM", "Russell 2000", 218.0, 32e6),
    ("Broad market", "VTI", "Total US market", 290.0, 4e6),
    ("Technology", "XLK", "Technology", 232.0, 8e6),
    ("Technology", "VGT", "Info technology", 620.0, 0.5e6),
    ("Semiconductors", "SMH", "Semiconductors", 268.0, 8e6),
    ("Semiconductors", "SOXX", "PHLX semiconductors", 245.0, 5e6),
    ("Communication", "XLC", "Communication services", 98.0, 5e6),
    ("Health care", "XLV", "Health care", 148.0, 8e6),
    ("Biotech", "XBI", "Biotech", 92.0, 10e6),
    ("Biotech", "IBB", "Nasdaq biotech", 140.0, 2e6),
    ("Financials", "XLF", "Financials", 48.0, 42e6),
    ("Financials", "KRE", "Regional banks", 58.0, 12e6),
    ("Financials", "KBE", "Banks", 54.0, 2e6),
    ("Energy", "XLE", "Energy", 92.0, 18e6),
    ("Energy", "XOP", "Oil & gas E&P", 140.0, 4e6),
    ("Energy", "OIH", "Oil services", 310.0, 0.4e6),
    ("Industrials", "XLI", "Industrials", 138.0, 10e6),
    ("Industrials", "ITA", "Aerospace & defense", 155.0, 0.5e6),
    ("Consumer", "XLY", "Consumer discretionary", 198.0, 5e6),
    ("Consumer", "XLP", "Consumer staples", 82.0, 12e6),
    ("Consumer", "XRT", "Retail", 78.0, 5e6),
    ("Consumer", "XHB", "Homebuilders", 110.0, 3e6),
    ("Real estate", "XLRE", "Real estate", 42.0, 6e6),
    ("Materials", "XLB", "Materials", 92.0, 6e6),
    ("Materials", "XME", "Metals & mining", 68.0, 3e6),
    ("Utilities", "XLU", "Utilities", 78.0, 14e6),
    ("Treasuries & credit", "TLT", "20+ year Treasury", 92.0, 35e6),
    ("Treasuries & credit", "IEF", "7–10 year Treasury", 96.0, 8e6),
    ("Treasuries & credit", "HYG", "High yield corporate", 78.0, 30e6),
    ("Treasuries & credit", "LQD", "Inv. grade corporate", 110.0, 25e6),
    ("Commodities", "GLD", "Gold", 248.0, 8e6),
    ("Commodities", "SLV", "Silver", 28.0, 18e6),
    ("Commodities", "USO", "Crude oil", 78.0, 4e6),
    ("Commodities", "UNG", "Natural gas", 14.0, 8e6),
    ("International", "EEM", "Emerging markets", 44.0, 28e6),
    ("International", "EFA", "Developed ex-US", 84.0, 14e6),
    ("International", "FXI", "China large-cap", 32.0, 22e6),
    ("International", "EWJ", "Japan", 72.0, 8e6),
    ("International", "VGK", "Europe", 70.0, 3e6),
]

ETF_META: dict[str, dict[str, str]] = {}
ETF_DEMO: dict[str, tuple[float, float]] = {}
ETF_SYMBOLS: list[str] = []
_seen: set[str] = set()
for industry, symbol, name, last, avg in _ETF_ROWS:
    if symbol in _seen:
        continue
    _seen.add(symbol)
    ETF_SYMBOLS.append(symbol)
    ETF_META[symbol] = {"industry": industry, "name": name}
    ETF_DEMO[symbol] = (last, avg)


def is_etf(symbol: str) -> bool:
    return (symbol or "").replace(" ", "").upper() in ETF_META


def etf_meta(symbol: str) -> dict[str, str]:
    return ETF_META.get((symbol or "").replace(" ", "").upper(), {})


_SECTOR_STOCKS = {str(item["name"]): [str(sym) for sym in item["stocks"]] for item in SECTORS}


def _uniq(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for symbol in symbols:
        key = symbol.replace(".", " ")
        if key in seen:
            continue
        seen.add(key)
        out.append(symbol)
    return out


INDUSTRY_STOCKS: dict[str, list[str]] = {
    "Broad market": _SECTOR_STOCKS["S&P 500"],
    "Technology": _SECTOR_STOCKS["Technology"],
    "Semiconductors": _SECTOR_STOCKS["Semiconductors"],
    "Communication": _SECTOR_STOCKS["Communication"],
    "Health care": _SECTOR_STOCKS["Health care"],
    "Biotech": _SECTOR_STOCKS["Biotech"],
    "Financials": _uniq(_SECTOR_STOCKS["Financials"] + _SECTOR_STOCKS["Regional banks"]),
    "Energy": _SECTOR_STOCKS["Energy"],
    "Industrials": _SECTOR_STOCKS["Industrials"],
    "Consumer": _uniq(_SECTOR_STOCKS["Consumer discretionary"] + _SECTOR_STOCKS["Consumer staples"]),
    "Real estate": _SECTOR_STOCKS["Real estate"],
    "Materials": _SECTOR_STOCKS["Materials"],
    "Utilities": _SECTOR_STOCKS["Utilities"],
    "Treasuries & credit": [],
    "Commodities": [],
    "International": ["TSM", "ASML", "NVO", "SAP", "SONY", "BABA", "TM", "SHOP"],
}


def industry_stocks(industry: str | None) -> list[str]:
    if not industry:
        return []
    return list(INDUSTRY_STOCKS.get(industry, []))


def all_industry_stock_symbols() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for names in INDUSTRY_STOCKS.values():
        for symbol in names:
            key = symbol.replace(".", " ")
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out
