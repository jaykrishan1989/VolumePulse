"""Calendar mechanisms the bars can score. Rules are frozen. Do not add a clock after the fill.

The write-up is ``research/ECONOMIC_HYPOTHESES.md``. Most of the mechanisms
in that note are already scored or have no identifying data. Two books are
registered here.

``e_fomc``. Lucca and Moench (Journal of Finance, 2015). On a scheduled FOMC
statement day, buy SPY at the 9:30 open and sell the 13:55 open, before a
14:00 statement. The 49 bp in the paper is the 24 hours ending at the
release. This account cannot hold the overnight half. The 100 bp stop is
the account cap. No magnitude filter. The date set is the one already
frozen in ``backtest.grid15``. This book cannot reach 80 trades. It is a
report.

``e_morning``. The same clock on every other session. Lucca and Moench
compare the announcement window with all other days. The control is not a
strategy. A profitable ordinary morning does not become a book.

Nothing in ``ADOPTABLE`` may open the holdout. CPI days and payroll days
stay in the control. Month-end labels are not generated: the published
window is a T+3 settlement window, and this validation sample is T+1.
No coefficient is estimated from returns. Nothing here places an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backtest.grid15 import FOMC_STATEMENT_DAYS
from backtest.hypotheses import make_spell
from backtest.periods import FLAT_MINUTE, HOLDOUT_START

OPEN_MINUTE = 9 * 60 + 30
# The 13:55 bar opens before a 14:00 statement. Its close is the statement minute.
FOMC_EXIT_MINUTE = 13 * 60 + 55
DISASTER_STOP = 0.0100

ADOPTABLE = frozenset()
BOOK_NAMES = ("e_fomc", "e_morning")


def assert_no_holdout(day: date) -> None:
    if day >= HOLDOUT_START:
        raise RuntimeError(f"holdout day {day} leaked into an economic hypothesis")


def may_open_holdout(rows: list[dict[str, Any]]) -> bool:
    """The promotion path. Empty by construction until a book is named in ``ADOPTABLE``."""
    adoptable = [row for row in rows if row.get("screenPass") and row.get("adoptable")]
    passes = [row for row in rows if row.get("screenPass")]
    return len(passes) == 1 and len(adoptable) == 1 and bool(adoptable[0].get("milestone"))


@dataclass
class EconomicResult:
    spells: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _rth(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [bar for bar in bars if OPEN_MINUTE <= int(bar["minute"]) <= FLAT_MINUTE + 5]


def _emit(bars: list[dict[str, Any]], day: date) -> dict[str, Any] | None:
    """Buy the 9:30 open and sell the 13:55 open. A missing 13:55 bar is a skip, not a later fill."""
    at = {int(bar["minute"]): index for index, bar in enumerate(bars)}
    entry_i = at.get(OPEN_MINUTE)
    exit_i = at.get(FOMC_EXIT_MINUTE)
    if entry_i is None or exit_i is None or exit_i <= entry_i:
        return None
    entry_open = float(bars[entry_i]["open"])
    if entry_open <= 0:
        return None
    spell = make_spell(
        symbol="SPY",
        day=day,
        bars=bars,
        entry_i=entry_i,
        exit_i=exit_i,
        stop=entry_open * (1.0 - DISASTER_STOP),
        priority=1.0,
        exit_kind="sell",
    )
    if spell is None:
        return None
    spell["invest_fraction"] = 1.0
    return spell


def generate(book: dict[tuple[str, date], list[dict[str, Any]]]) -> EconomicResult:
    spells: dict[str, list[dict[str, Any]]] = {name: [] for name in BOOK_NAMES}
    for day in sorted(day for symbol, day in book if symbol == "SPY"):
        assert_no_holdout(day)
        bars = _rth(book[("SPY", day)])
        if not bars:
            continue
        spell = _emit(bars, day)
        if spell is None:
            continue
        spells["e_fomc" if day in FOMC_STATEMENT_DAYS else "e_morning"].append(spell)
    return EconomicResult(spells=spells)
