"""US market categories: sector ETF for the headline move, liquid stocks for drill-in."""

from __future__ import annotations

SECTORS: list[dict[str, object]] = [
    {
        "id": "sp500",
        "name": "S&P 500",
        "etf": "SPY",
        "stocks": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "BRK.B", "AVGO", "JPM", "TSLA"],
    },
    {
        "id": "nasdaq",
        "name": "Nasdaq 100",
        "etf": "QQQ",
        "stocks": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "AVGO", "GOOGL", "TSLA", "NFLX", "AMD"],
    },
    {
        "id": "smallcap",
        "name": "Russell 2000",
        "etf": "IWM",
        "stocks": ["SMCI", "COIN", "PLTR", "SOFI", "MSTR", "RIVN", "HOOD", "AFRM"],
    },
    {
        "id": "dow",
        "name": "Dow Jones",
        "etf": "DIA",
        "stocks": ["GS", "MSFT", "CAT", "HD", "UNH", "V", "JPM", "AMGN", "MCD", "IBM"],
    },
    {
        "id": "tech",
        "name": "Technology",
        "etf": "XLK",
        "stocks": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD", "INTU", "QCOM"],
    },
    {
        "id": "semi",
        "name": "Semiconductors",
        "etf": "SMH",
        "stocks": ["NVDA", "AVGO", "AMD", "QCOM", "AMAT", "MU", "INTC", "LRCX", "KLAC", "TXN"],
    },
    {
        "id": "comm",
        "name": "Communication",
        "etf": "XLC",
        "stocks": ["META", "GOOGL", "NFLX", "DIS", "T", "VZ", "CMCSA", "CHTR"],
    },
    {
        "id": "health",
        "name": "Health care",
        "etf": "XLV",
        "stocks": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE", "AMGN", "ISRG", "TMO"],
    },
    {
        "id": "biotech",
        "name": "Biotech",
        "etf": "XBI",
        "stocks": ["VRTX", "REGN", "GILD", "AMGN", "MRNA", "BIIB", "ALNY"],
    },
    {
        "id": "financials",
        "name": "Financials",
        "etf": "XLF",
        "stocks": ["JPM", "BAC", "WFC", "GS", "MS", "C", "SCHW", "BLK", "AXP"],
    },
    {
        "id": "banks",
        "name": "Regional banks",
        "etf": "KRE",
        "stocks": ["USB", "PNC", "TFC", "CFG", "HBAN", "RF", "KEY"],
    },
    {
        "id": "energy",
        "name": "Energy",
        "etf": "XLE",
        "stocks": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "WMB"],
    },
    {
        "id": "industrials",
        "name": "Industrials",
        "etf": "XLI",
        "stocks": ["CAT", "GE", "HON", "UNP", "RTX", "DE", "BA", "ETN"],
    },
    {
        "id": "discretionary",
        "name": "Consumer discretionary",
        "etf": "XLY",
        "stocks": ["AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "BKNG"],
    },
    {
        "id": "staples",
        "name": "Consumer staples",
        "etf": "XLP",
        "stocks": ["WMT", "COST", "PG", "KO", "PEP", "PM", "MDLZ"],
    },
    {
        "id": "realty",
        "name": "Real estate",
        "etf": "XLRE",
        "stocks": ["AMT", "PLD", "EQIX", "WELL", "SPG", "O"],
    },
    {
        "id": "materials",
        "name": "Materials",
        "etf": "XLB",
        "stocks": ["LIN", "SHW", "APD", "FCX", "NEM", "ECL"],
    },
    {
        "id": "utilities",
        "name": "Utilities",
        "etf": "XLU",
        "stocks": ["NEE", "SO", "DUK", "CEG", "AEP", "SRE"],
    },
]


def sector_by_id(sector_id: str | None) -> dict[str, object] | None:
    if not sector_id:
        return None
    for item in SECTORS:
        if item["id"] == sector_id:
            return item
    return None


def overview_symbols() -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []
    for item in SECTORS:
        etf = str(item["etf"])
        if etf not in seen:
            seen.add(etf)
            symbols.append(etf)
    return symbols


def sector_stock_symbols(sector_id: str | None) -> list[str]:
    item = sector_by_id(sector_id)
    if not item:
        return overview_symbols()
    return [str(sym).replace(".", " ") for sym in item["stocks"]]


def sector_catalog() -> list[dict[str, object]]:
    return [
        {
            "id": str(s["id"]),
            "name": str(s["name"]),
            "etf": str(s["etf"]),
            "stocks": [str(sym) for sym in s["stocks"]],
        }
        for s in SECTORS
    ]


def all_overview_demo_symbols() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in SECTORS:
        for symbol in [str(item["etf"]), *item["stocks"]]:
            key = symbol.replace(".", " ")
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out
