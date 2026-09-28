"""Champion / challenger promotion gate.

A live champion is replaced only when one challenger passes every bar below.
The comparison sample is 2023-01-01 through 2026-03-31. The locked holdout
from 2026-04-01 is bar 2, and only for a single challenger that has already
passed the other bars. Nothing here places an order.

The numbers in this module are the gate. ``research/GATE.md`` states the same
rules. Do not loosen a threshold after reading a result.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from backtest.grid import SPECS
from backtest.periods import HOLDOUT_START
from backtest.spells import ACCOUNT_USD

# Walk-forward votes. 2026Q1 is reported by the runner and is not a vote:
# it is a partial quarter, and a year is the sum of its halves, so counting
# both would score the same days twice.
HALF_YEARS: list[tuple[str, date, date]] = [
    ("2023H1", date(2023, 1, 1), date(2023, 6, 30)),
    ("2023H2", date(2023, 7, 1), date(2023, 12, 31)),
    ("2024H1", date(2024, 1, 1), date(2024, 6, 30)),
    ("2024H2", date(2024, 7, 1), date(2024, 12, 31)),
    ("2025H1", date(2025, 1, 1), date(2025, 6, 30)),
    ("2025H2", date(2025, 7, 1), date(2025, 12, 31)),
]

REGIMES = ("up", "down", "high_vol", "low_vol")

# Two groups the eight-name book actually splits into. SPY is in neither.
TICKER_GROUPS: dict[str, frozenset[str]] = {
    "megacap": frozenset({"AAPL", "MSFT", "GOOGL", "AMZN", "META"}),
    "high_beta": frozenset({"NVDA", "AMD", "TSLA"}),
}

POOLED_START = date(2023, 1, 1)
POOLED_END = date(2026, 3, 31)
MAJORITY = 0.75
MIN_WINDOW_TRADES = 20
MIN_HALF_YEAR_WINS = 2
TOP_DAYS = 5
VOL_LOOKBACK = 20
# 10% of the US$2,120 account. A window this far behind the champion is severe.
SEVERE_DOLLARS = round(ACCOUNT_USD * 0.10, 2)
SEVERE_BPS = 15.0
FAMILY_ALPHA = 0.05
BOOTSTRAP_DRAWS = 5000
# Historical searches that already spent a look at the data. The six
# hypotheses are counted via REGISTRY, not here.
BRACKET_TRIALS = len(SPECS)
ROUNDTRIP_TRIALS = 12
SEED = 20260928

GATE_BEGIN = "<!-- GATE_BEGIN -->"
GATE_END = "<!-- GATE_END -->"


def ideas_tried(extra: int = 0) -> int:
    """Bonferroni denominator: every idea already scored, plus any new ids."""
    from backtest.areas import AREA_REGISTRY
    from backtest.daily import DAILY_REGISTRY
    from backtest.hypotheses import REGISTRY

    return BRACKET_TRIALS + ROUNDTRIP_TRIALS + len(REGISTRY) + len(AREA_REGISTRY) + len(DAILY_REGISTRY) + extra


def bonferroni_alpha(tried: int) -> float:
    if tried < 1:
        raise ValueError("ideas_tried must be positive")
    return FAMILY_ALPHA / tried


def draws_for(tried: int) -> int:
    """Enough resamples that a perfect edge can still clear the corrected alpha.

    The smallest p-value we report is 1 / (draws + 1). That floor has to sit
    under alpha, or the statistical bar could never pass. The formula is
    fixed; it is not chosen after seeing a p-value.
    """
    need = int(math.ceil(tried / FAMILY_ALPHA)) + 2
    return max(BOOTSTRAP_DRAWS, need)


def majority_needed(windows: int) -> int:
    """Smallest integer count that is at least 75% of ``windows``."""
    if windows < 1:
        raise ValueError("window count must be positive")
    return (3 * windows + 3) // 4


@dataclass
class Regime:
    direction: str | None
    vol: str | None


@dataclass
class SliceStats:
    trades: int
    net: float
    expectancy: float | None
    avg_bps: float | None

    def better_than(self, other: "SliceStats") -> bool:
        """Strictly better net dollars and per-trade expectancy, in $ and bp."""
        if self.trades < 1:
            return False
        other_exp = 0.0 if other.expectancy is None else other.expectancy
        other_bps = 0.0 if other.avg_bps is None else other.avg_bps
        if self.expectancy is None or self.avg_bps is None:
            return False
        return (
            self.net > other.net + 1e-6
            and self.expectancy > other_exp + 1e-9
            and self.avg_bps > other_bps + 1e-9
        )


@dataclass
class WindowScore:
    name: str
    family: str
    champion: SliceStats
    challenger: SliceStats
    win: bool
    severe: bool
    severe_reason: str


@dataclass
class GateVerdict:
    candidate_id: str
    passed: bool
    decision: str
    reasons: list[str]
    bars: dict[str, bool]
    windows: list[WindowScore]
    champion_pooled: SliceStats
    challenger_pooled: SliceStats
    trimmed_challenger_net: float
    trimmed_champion_net: float
    trimmed_challenger_expectancy: float | None
    trimmed_champion_expectancy: float | None
    bootstrap_p: float
    permutation_p: float
    alpha: float
    ideas_tried: int
    fresh_evaluated: bool
    dropped_days: list[date] = field(default_factory=list)

    def reason_text(self) -> str:
        if not self.reasons:
            return "Every bar passed."
        return " ".join(self.reasons)


def slice_stats(trades: list[dict[str, Any]]) -> SliceStats:
    n = len(trades)
    if n == 0:
        return SliceStats(0, 0.0, None, None)
    net = float(sum(trade["net"] for trade in trades))
    bps = sum(float(trade["ret"]) * 10_000.0 for trade in trades) / n
    return SliceStats(n, net, net / n, bps)


def daily_pnl(trades: list[dict[str, Any]], calendar: list[date]) -> dict[date, float]:
    out = {day: 0.0 for day in calendar}
    for trade in trades:
        day = trade["day"]
        if day in out:
            out[day] += float(trade["net"])
    return out


def label_regimes(closes: list[tuple[date, float]], start: date, end: date) -> dict[date, Regime]:
    """Market regime of each session from SPY closes.

    Direction uses that session's close over the prior session's close.
    Volatility is the sample standard deviation of the prior 20 close-to-close
    returns, so the label is known before the session. High vol is a trailing
    vol at or above the median of those labels inside ``start``..``end``.
    The median is one split for the whole comparison, not a trading threshold
    and not refit inside each half-year.
    """
    ordered = sorted(closes, key=lambda item: item[0])
    returns: list[tuple[date, float]] = []
    prev: float | None = None
    for day, close in ordered:
        if prev is not None and prev > 0:
            returns.append((day, close / prev - 1.0))
        prev = close
    vol_at: dict[date, float] = {}
    history: list[float] = []
    for day, ret in returns:
        if len(history) >= VOL_LOOKBACK:
            vol_at[day] = statistics.stdev(history[-VOL_LOOKBACK:])
        history.append(ret)
    sample = [vol for day, vol in vol_at.items() if start <= day <= end]
    median = statistics.median(sample) if sample else None
    direction_at = {day: ("up" if ret > 0 else "down") for day, ret in returns}
    labels: dict[date, Regime] = {}
    for day, _close in ordered:
        if day < start or day > end:
            continue
        vol = vol_at.get(day)
        vol_label = None
        if vol is not None and median is not None:
            vol_label = "high_vol" if vol >= median else "low_vol"
        labels[day] = Regime(direction_at.get(day), vol_label)
    return labels


def _filter_trades(
    trades: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    return [trade for trade in trades if predicate(trade)]


def _window_predicates(
    regimes: dict[date, Regime],
) -> list[tuple[str, str, Callable[[dict[str, Any]], bool]]]:
    windows: list[tuple[str, str, Callable[[dict[str, Any]], bool]]] = []
    for name, start, end in HALF_YEARS:
        windows.append((name, "half_year", lambda trade, start=start, end=end: start <= trade["day"] <= end))
    windows.append(("up", "regime", lambda trade: (regimes.get(trade["day"]) or Regime(None, None)).direction == "up"))
    windows.append(("down", "regime", lambda trade: (regimes.get(trade["day"]) or Regime(None, None)).direction == "down"))
    windows.append(("high_vol", "regime", lambda trade: (regimes.get(trade["day"]) or Regime(None, None)).vol == "high_vol"))
    windows.append(("low_vol", "regime", lambda trade: (regimes.get(trade["day"]) or Regime(None, None)).vol == "low_vol"))
    for name, symbols in TICKER_GROUPS.items():
        windows.append((name, "ticker_group", lambda trade, symbols=symbols: trade["symbol"] in symbols))
    return windows


def _severe(champion: SliceStats, challenger: SliceStats) -> str:
    gap = champion.net - challenger.net
    if gap > SEVERE_DOLLARS:
        return f"net is ${gap:.0f} worse than the champion, past the ${SEVERE_DOLLARS:.0f} limit"
    if (
        champion.trades >= 1
        and challenger.trades >= 1
        and champion.avg_bps is not None
        and challenger.avg_bps is not None
        and champion.avg_bps - challenger.avg_bps > SEVERE_BPS
    ):
        worse = champion.avg_bps - challenger.avg_bps
        return f"expectancy is {worse:.1f} bp worse than the champion, past the {SEVERE_BPS:.0f} bp limit"
    return ""


def score_windows(
    champion: list[dict[str, Any]],
    challenger: list[dict[str, Any]],
    regimes: dict[date, Regime],
) -> list[WindowScore]:
    scored: list[WindowScore] = []
    for name, family, predicate in _window_predicates(regimes):
        champ = slice_stats(_filter_trades(champion, predicate))
        chall = slice_stats(_filter_trades(challenger, predicate))
        reason = _severe(champ, chall)
        win = chall.trades >= MIN_WINDOW_TRADES and chall.better_than(champ)
        scored.append(WindowScore(name, family, champ, chall, win, bool(reason), reason))
    return scored


def _one_sided_p(diffs: list[float], draws: int, rng: random.Random, permute: bool) -> float:
    """One-sided p that the mean daily gap is <= 0, with add-one smoothing.

    The bootstrap recenters nothing: a resample whose sum is <= 0 counts
    against the observed positive gap. The sign-flip test compares each
    flipped sum with the observed sum, which is the paired permutation test.
    Counting flipped sums that are merely negative would stay near one half
    even when every day favors the challenger.
    """
    if not diffs:
        return 1.0
    observed = sum(diffs)
    count = 0
    width = len(diffs)
    for _ in range(draws):
        if permute:
            total = 0.0
            for gap in diffs:
                total += gap if rng.random() < 0.5 else -gap
            if total >= observed - 1e-9:
                count += 1
        else:
            total = 0.0
            for _draw in range(width):
                total += diffs[rng.randrange(width)]
            if total <= 0.0:
                count += 1
    return (count + 1) / (draws + 1)


def drop_top_days(
    champion: list[dict[str, Any]],
    challenger: list[dict[str, Any]],
    calendar: list[date],
) -> tuple[list[date], SliceStats, SliceStats]:
    champ_daily = daily_pnl(champion, calendar)
    chall_daily = daily_pnl(challenger, calendar)
    ranked = sorted(calendar, key=lambda day: chall_daily[day] - champ_daily[day], reverse=True)
    dropped = ranked[: min(TOP_DAYS, len(ranked))]
    dropped_set = set(dropped)
    kept_days = [day for day in calendar if day not in dropped_set]
    # Recompute from the trades that remain, so expectancy is per remaining trade.
    champ_left = [trade for trade in champion if trade["day"] not in dropped_set]
    chall_left = [trade for trade in challenger if trade["day"] not in dropped_set]
    # Dollar totals have to include flat days, which carry no trade row.
    champ_stats = slice_stats(champ_left)
    chall_stats = slice_stats(chall_left)
    champ_stats.net = sum(champ_daily[day] for day in kept_days)
    chall_stats.net = sum(chall_daily[day] for day in kept_days)
    if champ_stats.trades:
        champ_stats.expectancy = champ_stats.net / champ_stats.trades
    if chall_stats.trades:
        chall_stats.expectancy = chall_stats.net / chall_stats.trades
    return dropped, chall_stats, champ_stats


def _assert_preholdout(trades: list[dict[str, Any]], label: str) -> None:
    leaked = [trade["day"] for trade in trades if trade["day"] >= HOLDOUT_START]
    if leaked:
        raise RuntimeError(f"{label} includes holdout day {min(leaked)}")


def _shortfalls(challenger: SliceStats, champion: SliceStats) -> list[str]:
    """Which of the three 'better' measures the challenger missed."""
    other_exp = 0.0 if champion.expectancy is None else champion.expectancy
    other_bps = 0.0 if champion.avg_bps is None else champion.avg_bps
    if challenger.trades < 1 or challenger.expectancy is None or challenger.avg_bps is None:
        return ["net, dollars per trade, and basis points per trade"]
    missing = []
    if challenger.net <= champion.net + 1e-6:
        missing.append("net")
    if challenger.expectancy <= other_exp + 1e-9:
        missing.append("dollars per trade")
    if challenger.avg_bps <= other_bps + 1e-9:
        missing.append("basis points per trade")
    return missing or ["the combined bar"]


def _fmt_money(stats: SliceStats) -> str:
    exp = "n/a" if stats.expectancy is None else f"${stats.expectancy:.2f}/trade"
    bps = "n/a" if stats.avg_bps is None else f"{stats.avg_bps:.1f} bp"
    return f"${stats.net:.0f} on {stats.trades} trades, {exp}, {bps}"


def judge(
    candidate_id: str,
    champion: list[dict[str, Any]],
    challenger: list[dict[str, Any]],
    *,
    calendar: list[date],
    regimes: dict[date, Regime],
    ideas_tried: int,
    fresh_champion: list[dict[str, Any]] | None = None,
    fresh_challenger: list[dict[str, Any]] | None = None,
    n_boot: int | None = None,
    seed: int = SEED,
) -> GateVerdict:
    """Score one challenger. A missing fresh slice fails bar 2 and does not peek."""
    _assert_preholdout(champion, "champion")
    _assert_preholdout(challenger, candidate_id)
    if any(day >= HOLDOUT_START for day in calendar):
        raise RuntimeError("selection calendar includes a holdout day")
    # One session index for the paired tests and the window sums.
    calendar_set = set(calendar)
    champion = [trade for trade in champion if trade["day"] in calendar_set]
    challenger = [trade for trade in challenger if trade["day"] in calendar_set]
    champ_pooled = slice_stats(champion)
    chall_pooled = slice_stats(challenger)
    windows = score_windows(champion, challenger, regimes)
    by_family: dict[str, list[WindowScore]] = {}
    for window in windows:
        by_family.setdefault(window.family, []).append(window)
    reasons: list[str] = []
    bars = {"walk_forward": False, "fresh_slice": False, "consistency": False}

    if not chall_pooled.better_than(champ_pooled):
        reasons.append(
            f"Pooled sample does not beat the champion on net and expectancy "
            f"(challenger {_fmt_money(chall_pooled)}; champion {_fmt_money(champ_pooled)})."
        )
    regime_wins = [window.name for window in by_family.get("regime", []) if window.win]
    missing_regimes = [name for name in REGIMES if name not in regime_wins]
    if missing_regimes:
        reasons.append(
            "Does not beat the champion in every market regime (" + ", ".join(missing_regimes) + ")."
        )
    group_wins = [window.name for window in by_family.get("ticker_group", []) if window.win]
    missing_groups = [name for name in TICKER_GROUPS if name not in group_wins]
    if missing_groups:
        reasons.append(
            "Does not beat the champion in every ticker group (" + ", ".join(missing_groups) + ")."
        )
    half_wins = [window for window in by_family.get("half_year", []) if window.win]
    if len(half_wins) < MIN_HALF_YEAR_WINS:
        noun = "half-year" if len(half_wins) == 1 else "half-years"
        reasons.append(
            f"Beats the champion in {len(half_wins)} {noun}; need at least {MIN_HALF_YEAR_WINS}."
        )
    bars["walk_forward"] = not any(
        reason.startswith("Pooled") or reason.startswith("Does not beat") or reason.startswith("Beats the champion in")
        for reason in reasons
    )

    needed = majority_needed(len(windows))
    wins = sum(1 for window in windows if window.win)
    if wins < needed:
        reasons.append(f"Improves in {wins} of {len(windows)} windows; need at least {needed} (75%).")
    severe = [window for window in windows if window.severe]
    for window in severe:
        reasons.append(f"Severe regression in {window.name}: {window.severe_reason}.")
    dropped, trimmed_chall, trimmed_champ = drop_top_days(champion, challenger, calendar)
    trimmed_ok = trimmed_chall.better_than(trimmed_champ)
    if not trimmed_ok:
        behind = _shortfalls(trimmed_chall, trimmed_champ)
        reasons.append(
            f"After removing the top {len(dropped)} days by daily gap "
            f"({', '.join(day.isoformat() for day in dropped)}), the challenger is behind on "
            f"{', '.join(behind)} "
            f"(challenger {_fmt_money(trimmed_chall)}; champion {_fmt_money(trimmed_champ)})."
        )
    diffs = []
    champ_daily = daily_pnl(champion, calendar)
    chall_daily = daily_pnl(challenger, calendar)
    for day in calendar:
        diffs.append(chall_daily[day] - champ_daily[day])
    draws = n_boot or draws_for(ideas_tried)
    alpha = bonferroni_alpha(ideas_tried)
    rng_boot = random.Random(seed)
    rng_perm = random.Random(seed + 1)
    bootstrap_p = _one_sided_p(diffs, draws, rng_boot, permute=False)
    permutation_p = _one_sided_p(diffs, draws, rng_perm, permute=True)
    if bootstrap_p >= alpha or permutation_p >= alpha:
        reasons.append(
            f"Paired tests do not clear the Bonferroni line for {ideas_tried} ideas tried "
            f"(bootstrap p={bootstrap_p:.4f}, permutation p={permutation_p:.4f}, alpha={alpha:.5f})."
        )
    consistency_failures = [
        reason
        for reason in reasons
        if reason.startswith("Improves")
        or reason.startswith("Severe")
        or reason.startswith("After removing")
        or reason.startswith("Paired tests")
    ]
    bars["consistency"] = not consistency_failures

    fresh_evaluated = fresh_champion is not None or fresh_challenger is not None
    if fresh_champion is None and fresh_challenger is None:
        reasons.append(
            "Fresh out-of-sample slice was not read. It opens only when this challenger is the "
            "only one that has already passed the walk-forward and consistency bars. The holdout was not read."
        )
    else:
        if fresh_champion is None or fresh_challenger is None:
            raise RuntimeError("a fresh slice needs both the champion and the challenger")
        pre = [trade["day"] for trade in fresh_champion + fresh_challenger if trade["day"] < HOLDOUT_START]
        if pre:
            raise RuntimeError("fresh slice contains a pre-holdout day")
        fresh_champ = slice_stats(fresh_champion)
        fresh_chall = slice_stats(fresh_challenger)
        if fresh_chall.trades < MIN_WINDOW_TRADES or not fresh_chall.better_than(fresh_champ):
            reasons.append(
                f"Fresh slice does not beat the champion "
                f"(challenger {_fmt_money(fresh_chall)}; champion {_fmt_money(fresh_champ)})."
            )
    bars["fresh_slice"] = fresh_evaluated and not any(reason.startswith("Fresh") for reason in reasons)
    # Bar 2 is a pass only when the slice was actually read and beat the champion.
    # Leaving it closed is a fail, which is what keeps the holdout shut.
    passed = all(bars.values())
    return GateVerdict(
        candidate_id=candidate_id,
        passed=passed,
        decision="promoted" if passed else "rejected",
        reasons=reasons,
        bars=bars,
        windows=windows,
        champion_pooled=champ_pooled,
        challenger_pooled=chall_pooled,
        trimmed_challenger_net=trimmed_chall.net,
        trimmed_champion_net=trimmed_champ.net,
        trimmed_challenger_expectancy=trimmed_chall.expectancy,
        trimmed_champion_expectancy=trimmed_champ.expectancy,
        bootstrap_p=bootstrap_p,
        permutation_p=permutation_p,
        alpha=alpha,
        ideas_tried=ideas_tried,
        fresh_evaluated=fresh_evaluated,
        dropped_days=dropped,
    )


def promote(verdict: GateVerdict, champion_record: dict[str, Any]) -> dict[str, Any]:
    """Return an updated champion record. Refuses unless every bar passed."""
    if not verdict.passed or verdict.decision != "promoted" or not verdict.bars.get("fresh_slice"):
        raise RuntimeError(
            f"refusing to replace the champion with {verdict.candidate_id}: "
            + (verdict.reason_text() or "gate not passed")
        )
    updated = dict(champion_record)
    updated["id"] = verdict.candidate_id
    updated["replaced"] = True
    updated["previousId"] = champion_record.get("id")
    return updated


def preserve_marked_section(new_log: str, old_log: str, begin: str, end: str) -> str:
    """Keep one marked block when a log is regenerated."""
    old_start = old_log.find(begin)
    old_stop = old_log.find(end)
    if old_start < 0 or old_stop < old_start:
        return new_log
    block = old_log[old_start : old_stop + len(end)]
    new_start = new_log.find(begin)
    if new_start >= 0:
        new_stop = new_log.find(end)
        if new_stop < 0:
            return new_log
        return new_log[:new_start] + block + new_log[new_stop + len(end) :]
    return new_log.rstrip() + "\n\n" + block + "\n"


def preserve_gate_section(new_log: str, old_log: str) -> str:
    """Keep the gate and research-area write-ups when the hypothesis log is regenerated."""
    from backtest.areas import AREAS_BEGIN, AREAS_END
    from backtest.daily import DAILY_BEGIN, DAILY_END

    kept = preserve_marked_section(new_log, old_log, GATE_BEGIN, GATE_END)
    kept = preserve_marked_section(kept, old_log, AREAS_BEGIN, AREAS_END)
    return preserve_marked_section(kept, old_log, DAILY_BEGIN, DAILY_END)
