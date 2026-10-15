"""Exit diagnosis and a daily top-k book. Frozen before the validation fill.

The bare opening-range break already lost with a noon exit and a fixed stop.
These exit books keep that entry and change only the exit, so a difference is
the exit and not a new filter. The top-k books are a separate question: rank
every name and slot, trade the four highest scores that day, and size the
stop and target to that slot's own prior forward standard deviation.

A book can reach the promotion gate only if the screen below is true. The
screen was written before the fill. Two passes do not open the holdout.
Nothing here places an order.

Jay trades through IBKR. The decision cost is tiered commission and 2 bp of
slippage per side, on US$2,120. The cost-clearing books below are a later
batch: fewer names, a larger ticket, and a slot whose own move can clear a
20 bp round trip. Only ``c_primary`` may open the holdout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backtest.data import CANDIDATES, CONTEXT
from backtest.grid15 import (
    FLAT_MINUTE,
    MORNING_STARTS,
    OPEN_MINUTE,
    OR_START,
    SLOT_STARTS,
    DayView,
    TierVote,
    _exit_index,
    _index_at,
    assert_no_holdout,
    plan_exit,
    prepare_day,
    signal_minute,
    slot_bars,
)
from backtest.periods import HOLDOUT_START, TRAIN_START, VALIDATE_END, VALIDATE_START

# Frozen. Not a search.
MIN_HISTORY = 40
MIN_STD = 0.0020
TOP_K = 4
INVEST_FRACTION = 0.25
MIN_STOP = 0.0012
MAX_STOP = 0.025
SMA_DAYS = 20
SCREEN_MIN_TRADES = 80
SCREEN_MIN_DAY_SHARE = 0.80
SCREEN_MIN_HALVES = 4
# A quarter ticket paid about 20 bp round trip. A 20 bp target only ties that.
# The higher floor makes the target twice the cost. Neither number is a search.
COST_HURDLE = 0.0020
VOL_FLOOR = 0.0040
DISLOCATION_Z = 1.5

ENTRY_CUTOFF = 15 * 60 + 15
TRADE_STARTS = tuple(start for start in SLOT_STARTS if signal_minute(start) + 5 <= ENTRY_CUTOFF)
RANK_SYMBOLS = tuple(CANDIDATES) + tuple(CONTEXT)
HALVES = (
    (date(2023, 1, 1), date(2023, 6, 30)),
    (date(2023, 7, 1), date(2023, 12, 31)),
    (date(2024, 1, 1), date(2024, 6, 30)),
    (date(2024, 7, 1), date(2024, 12, 31)),
    (date(2025, 1, 1), date(2025, 6, 30)),
    (date(2025, 7, 1), date(2025, 12, 31)),
)
RECENT_START = date(2025, 7, 1)


@dataclass(frozen=True)
class BookSpec:
    name: str
    kind: str  # exit or rank
    exit: str = ""
    side: str = ""
    regime: bool = False
    min_z: float = 0.0
    require_edge: bool = False
    rank_by_edge: bool = False
    min_std: float = MIN_STD
    top_k: int = TOP_K
    invest_fraction: float = INVEST_FRACTION


# Exit books share one entry. Rank books share one sizer. Regime is a switch.
BOOKS = (
    BookSpec("x_flat", "exit", exit="flat"),
    BookSpec("x_30", "exit", exit="30"),
    BookSpec("x_60", "exit", exit="60"),
    BookSpec("x_noon", "exit", exit="noon"),
    BookSpec("x_trail", "exit", exit="trail"),
    BookSpec("k_mom", "rank", side="mom"),
    BookSpec("k_mom_regime", "rank", side="mom", regime=True),
    BookSpec("k_rev", "rank", side="rev"),
    BookSpec("k_rev_regime", "rank", side="rev", regime=True),
)


# One lever each, plus the package. Only c_primary may open the holdout.
# The levers are a report. They are not a menu.
COST_BOOKS = (
    BookSpec("c_ticket", "rank", side="rev", top_k=1, invest_fraction=1.0),
    BookSpec("c_two", "rank", side="rev", top_k=2, invest_fraction=0.5),
    BookSpec("c_vol", "rank", side="rev", min_std=VOL_FLOOR),
    BookSpec("c_move", "rank", side="rev", min_z=DISLOCATION_Z),
    BookSpec("c_edge", "rank", side="rev", require_edge=True),
    BookSpec(
        "c_primary",
        "rank",
        side="rev",
        top_k=1,
        invest_fraction=1.0,
        min_z=DISLOCATION_Z,
        require_edge=True,
        rank_by_edge=True,
        min_std=VOL_FLOOR,
    ),
)
ADOPTABLE = frozenset({"c_primary"})


@dataclass
class Running:
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def add(self, value: float) -> None:
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (value - self.mean)

    def std(self) -> float | None:
        if self.n < MIN_HISTORY:
            return None
        if self.n < 2:
            return None
        return (self.m2 / (self.n - 1)) ** 0.5


@dataclass
class SymbolMemory:
    buckets: dict[int, Running] = field(default_factory=dict)
    forwards: dict[int, Running] = field(default_factory=dict)
    down_forwards: dict[int, Running] = field(default_factory=dict)
    closes: list[float] = field(default_factory=list)

    def bucket(self, start: int) -> Running:
        return self.buckets.setdefault(start, Running())

    def forward(self, start: int) -> Running:
        return self.forwards.setdefault(start, Running())

    def down_forward(self, start: int) -> Running:
        return self.down_forwards.setdefault(start, Running())

    def z(self, start: int, value: float) -> float | None:
        stats = self.buckets.get(start)
        if stats is None:
            return None
        scale = stats.std()
        if scale is None or scale <= 0:
            return None
        return (value - stats.mean) / scale

    def forward_std(self, start: int) -> float | None:
        stats = self.forwards.get(start)
        if stats is None:
            return None
        return stats.std()

    def down_forward_mean(self, start: int) -> float | None:
        """Mean forward return on days this slot's own bucket was down.

        The mean is prior days only. The caller adds today's return after the decision.
        """
        stats = self.down_forwards.get(start)
        if stats is None or stats.n < MIN_HISTORY:
            return None
        return stats.mean

    def below_average(self) -> bool | None:
        if len(self.closes) < SMA_DAYS:
            return None
        window = self.closes[-SMA_DAYS:]
        return self.closes[-1] < (sum(window) / len(window))


def vote_impulse(z: float | None, side: str) -> TierVote:
    """Momentum wants the slot that just ran. Reversion wants the slot that just fell."""
    if z is None:
        return TierVote("impulse", 0.0, True, 1.0, "thin slot history")
    if side == "mom":
        return TierVote("impulse", z, z <= 0.0, 1.0, f"z {z:.3f}")
    if side == "rev":
        return TierVote("impulse", -z, z >= 0.0, 1.0, f"z {z:.3f}")
    raise ValueError(side)


def vote_slot_scale(scale: float | None, floor: float = MIN_STD) -> TierVote:
    """One historical standard deviation is the stop and the target.

    The original books keep the 20 bp floor. A caller can pass a higher floor.
    The number is an argument, not a search.
    """
    if scale is None:
        return TierVote("slot_scale", 0.0, True, 1.0, "thin forward history")
    if scale < floor:
        return TierVote("slot_scale", scale, True, 1.0, f"std {scale:.4f} below the cost floor")
    return TierVote("slot_scale", scale, False, 1.0, f"std {scale:.4f}")


def vote_dislocation(z: float | None, side: str, min_z: float) -> TierVote:
    """A one-sigma move is a dislocation. Zero means the impulse vote is enough."""
    if min_z <= 0:
        return TierVote("dislocation", 1.0, False, 1.0, "no dislocation floor")
    if z is None:
        return TierVote("dislocation", 0.0, True, 1.0, "thin slot history")
    if side == "rev" and z > -min_z:
        return TierVote("dislocation", -z, True, 1.0, f"z {z:.3f} inside {min_z:.1f} sigma")
    if side == "mom" and z < min_z:
        return TierVote("dislocation", z, True, 1.0, f"z {z:.3f} inside {min_z:.1f} sigma")
    return TierVote("dislocation", abs(z), False, 1.0, f"z {z:.3f}")


def vote_historical_edge(mean: float | None, *, mode: str) -> TierVote:
    """The slot's own average forward return after a down bucket.

    ``rank`` keeps a slot whose history reverted at all. ``clear`` keeps a
    slot whose history cleared the 20 bp round trip. ``off`` does not vote.
    """
    if mode == "off":
        return TierVote("hist_edge", 0.0, False, 1.0, "historical edge off")
    if mean is None:
        return TierVote("hist_edge", 0.0, True, 1.0, "thin down-slot history")
    floor = COST_HURDLE if mode == "clear" else 0.0
    if mean <= floor:
        return TierVote("hist_edge", mean, True, 1.0, f"down-slot mean {mean:.5f} does not clear {floor:.5f}")
    return TierVote("hist_edge", mean, False, 1.0, f"down-slot mean {mean:.5f}")


def vote_regime(spy_below: bool | None, qqq_below: bool | None, *, enabled: bool) -> TierVote:
    """Shut the whole day only when both indexes closed under their 20-day average."""
    if not enabled:
        return TierVote("regime", 1.0, False, 1.0, "regime gate off")
    if spy_below is None or qqq_below is None:
        return TierVote("regime", 1.0, False, 1.0, "20-day average not ready")
    blocked = spy_below and qqq_below
    if blocked:
        return TierVote("regime", 0.0, True, 1.0, "SPY and QQQ both under the 20-day average")
    return TierVote("regime", 1.0, False, 1.0, "regime open")


def rank_candidates(rows: list[dict[str, Any]], k: int, regime_off: bool) -> list[dict[str, Any]]:
    """One slot per symbol, then the k highest scores. Ties break on the symbol."""
    if regime_off or k <= 0:
        return []
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("veto"):
            continue
        current = best.get(row["symbol"])
        if current is None or float(row["score"]) > float(current["score"]):
            best[row["symbol"]] = row
        elif current is not None and float(row["score"]) == float(current["score"]) and row["start"] < current["start"]:
            best[row["symbol"]] = row
    ordered = sorted(best.values(), key=lambda row: (-float(row["score"]), row["symbol"], row["start"]))
    return ordered[:k]


def screen_failures(
    *,
    validate_net: float,
    pooled_net: float,
    recent_net: float,
    validate_trades: int,
    positive_halves: int,
    ex_top5: float,
    days_with_fill: int,
    sessions: int,
) -> list[str]:
    """Frozen before the fill. A failure keeps the holdout shut."""
    reasons = []
    if validate_net <= 0:
        reasons.append("validation net is not positive")
    if pooled_net <= 0:
        reasons.append("pooled net from 2023-01-01 is not positive")
    if recent_net <= 0:
        reasons.append("recent net from 2025-07-01 is not positive")
    if validate_trades < SCREEN_MIN_TRADES:
        reasons.append("fewer than 80 validation trades")
    if positive_halves < SCREEN_MIN_HALVES:
        reasons.append("fewer than 4 of 6 half-years are positive")
    if ex_top5 <= 0:
        reasons.append("validation net without the five best days is not positive")
    share = (days_with_fill / sessions) if sessions else 0.0
    if share < SCREEN_MIN_DAY_SHARE:
        reasons.append("fills on fewer than 80% of validation sessions")
    return reasons


def cost_screen_failures(
    *,
    validate_net: float,
    pooled_net: float,
    recent_net: float,
    validate_trades: int,
    positive_halves: int,
    ex_top5: float,
    avg_bps: float,
) -> list[str]:
    """Frozen before the fill. Fewer trades are allowed. The edge still has to clear costs.

    A day-share rule would reject the larger-move book this batch is testing.
    The fill rate is reported. It is not a pass condition.
    """
    reasons = []
    if validate_net <= 0:
        reasons.append("validation net is not positive")
    if pooled_net <= 0:
        reasons.append("pooled net from 2023-01-01 is not positive")
    if recent_net <= 0:
        reasons.append("recent net from 2025-07-01 is not positive")
    if validate_trades < SCREEN_MIN_TRADES:
        reasons.append("fewer than 80 validation trades")
    if positive_halves < SCREEN_MIN_HALVES:
        reasons.append("fewer than 4 of 6 half-years are positive")
    if ex_top5 <= 0:
        reasons.append("validation net without the five best days is not positive")
    if avg_bps <= 0:
        reasons.append("average net basis points do not clear the round-trip cost")
    return reasons


def _stamp(bar: dict[str, Any], *, flat: bool) -> int:
    stamp = int(bar.get("t") or 0)
    if flat and stamp:
        return stamp + 300
    return stamp


def _finish(
    spell: dict[str, Any],
    *,
    symbol: str,
    day: date,
    entry: dict[str, Any],
    score: float,
    invest_fraction: float = INVEST_FRACTION,
) -> dict[str, Any]:
    spell.update(
        {
            "symbol": symbol,
            "day": day,
            "buy_minute": int(entry["minute"]),
            "entry_t": int(entry.get("t") or 0),
            "score": score,
            "priority": score,
            "invest_fraction": invest_fraction,
            "side": "long",
        }
    )
    return spell


def fixed_spell(
    view: DayView,
    entry_index: int,
    stop: float,
    target: float | None,
    exit_minute: int,
) -> dict[str, Any] | None:
    located = _exit_index(view, entry_index, exit_minute)
    if located is None:
        return None
    exit_index, exit_kind = located
    return plan_exit(view.ordered, entry_index, exit_index, stop, target, exit_kind, breakeven_after=None)


def trail_spell(view: DayView, entry_index: int, stop: float, width: float) -> dict[str, Any] | None:
    """Trail one opening-range under the highest high. The ratchet waits for the next bar.

    The bar that makes the high is still protected by the previous stop. The
    file does not say whether the high or the low printed first.
    """
    if width <= 0 or stop >= float(view.ordered[entry_index]["open"]):
        return None
    flat_index = _index_at(view, FLAT_MINUTE)
    if flat_index is None or flat_index <= entry_index:
        return None
    bars = view.ordered
    active = stop
    last_ratchet = entry_index - 1
    highest = float(bars[entry_index]["open"])
    hit_index = flat_index
    reason = "flat"
    for index in range(entry_index, flat_index + 1):
        bar = bars[index]
        if float(bar["low"]) <= active:
            hit_index = index
            reason = "stop"
            break
        if index == flat_index:
            break
        highest = max(highest, float(bar["high"]))
        raised = max(active, highest - width)
        if raised > active + 1e-9:
            active = raised
            last_ratchet = index
    path_start = last_ratchet + 1
    if path_start > hit_index:
        return None
    kind = "flat"
    planned: dict[str, Any] = {
        "stop": float(active if reason == "stop" or last_ratchet >= entry_index else stop),
        "entry_bar": bars[entry_index],
        "exit_bar": bars[hit_index],
        "path": bars[path_start:hit_index],
        "exit_kind": kind,
        "exit_t": _stamp(bars[hit_index], flat=True),
        "planned_reason": reason,
    }
    # A time-style flat exit that never ratcheted keeps the original stop so
    # resolve_exit checks the whole path against that stop.
    if reason != "stop" and last_ratchet < entry_index:
        planned["stop"] = float(stop)
        planned["path"] = bars[entry_index:hit_index]
    elif reason != "stop":
        planned["stop"] = float(active)
    return planned


def _exit_minute(entry_minute: int, kind: str) -> int:
    if kind == "flat" or kind == "trail":
        return FLAT_MINUTE
    if kind == "30":
        return entry_minute + 30
    if kind == "60":
        return entry_minute + 60
    if kind == "noon":
        return 12 * 60
    raise ValueError(kind)


def _orb_spell(view: DayView, day: date, symbol: str, spec: BookSpec) -> dict[str, Any] | None:
    opening = slot_bars(view, OR_START)
    if opening is None:
        return None
    or_high = max(float(bar["high"]) for bar in opening)
    or_low = min(float(bar["low"]) for bar in opening)
    width = or_high - or_low
    if width <= 0:
        return None
    for start in MORNING_STARTS:
        bars = slot_bars(view, start)
        if bars is None:
            continue
        close = float(bars[-1]["close"])
        if close <= or_high:
            continue
        if width / close < MIN_STOP or width / close > MAX_STOP:
            return None
        entry_minute = signal_minute(start) + 5
        entry_index = _index_at(view, entry_minute)
        if entry_index is None:
            return None
        entry_open = float(view.ordered[entry_index]["open"])
        if entry_open <= or_low:
            return None
        distance = (entry_open - or_low) / entry_open
        if distance < MIN_STOP or distance > MAX_STOP:
            return None
        if spec.exit == "trail":
            planned = trail_spell(view, entry_index, or_low, width)
        else:
            planned = fixed_spell(view, entry_index, or_low, None, _exit_minute(entry_minute, spec.exit))
        if planned is None:
            return None
        return _finish(planned, symbol=symbol, day=day, entry=view.ordered[entry_index], score=0.0)
    return None


def _bucket_return(bars: list[dict[str, Any]]) -> float | None:
    opened = float(bars[0]["open"])
    if opened <= 0:
        return None
    return float(bars[-1]["close"]) / opened - 1.0


def _forward_return(view: DayView, start: int) -> float | None:
    entry_minute = signal_minute(start) + 5
    entry = view.by_minute.get(entry_minute)
    done = view.by_minute.get(min(entry_minute + 10, FLAT_MINUTE))
    if entry is None or done is None or float(entry["open"]) <= 0:
        return None
    return float(done["close"]) / float(entry["open"]) - 1.0


def _rank_rows(
    spec: BookSpec,
    day: date,
    prepared: dict[str, DayView],
    memory: dict[str, SymbolMemory],
    regime: TierVote,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol in RANK_SYMBOLS:
        view = prepared.get(symbol)
        if view is None:
            continue
        mem = memory[symbol]
        for start in TRADE_STARTS:
            bars = slot_bars(view, start)
            if bars is None:
                continue
            impulse = _bucket_return(bars)
            if impulse is None:
                continue
            z = mem.z(start, impulse)
            scale = mem.forward_std(start)
            impulse_vote = vote_impulse(z, spec.side)
            scale_vote = vote_slot_scale(scale, spec.min_std)
            disloc_vote = vote_dislocation(z, spec.side, spec.min_z)
            if spec.require_edge:
                edge_mode = "clear"
            elif spec.rank_by_edge:
                edge_mode = "rank"
            else:
                edge_mode = "off"
            edge_mean = mem.down_forward_mean(start) if edge_mode != "off" else None
            edge_vote = vote_historical_edge(edge_mean, mode=edge_mode)
            veto = regime.veto or impulse_vote.veto or scale_vote.veto or disloc_vote.veto or edge_vote.veto
            if veto:
                continue
            entry_minute = signal_minute(start) + 5
            entry_index = _index_at(view, entry_minute)
            if entry_index is None or scale is None:
                continue
            entry_open = float(view.ordered[entry_index]["open"])
            stop = entry_open * (1.0 - scale)
            target = entry_open * (1.0 + scale)
            if stop <= 0 or (entry_open - stop) / entry_open > MAX_STOP:
                continue
            planned = fixed_spell(view, entry_index, stop, target, entry_minute + 30)
            if planned is None:
                continue
            score = impulse_vote.score
            if spec.rank_by_edge:
                score = float(edge_vote.score) * float(impulse_vote.score)
            _finish(
                planned,
                symbol=symbol,
                day=day,
                entry=view.ordered[entry_index],
                score=score,
                invest_fraction=spec.invest_fraction,
            )
            planned["start"] = start
            planned["z"] = z
            rows.append(planned)
    return rows


def _update_memory(mem: SymbolMemory, view: DayView) -> None:
    flat = view.by_minute.get(FLAT_MINUTE)
    if flat is not None and float(flat["close"]) > 0:
        mem.closes.append(float(flat["close"]))
    for start in SLOT_STARTS:
        bars = slot_bars(view, start)
        if bars is None:
            continue
        impulse = _bucket_return(bars)
        if impulse is not None:
            mem.bucket(start).add(impulse)
        forward = _forward_return(view, start)
        if forward is not None:
            mem.forward(start).add(forward)
        if impulse is not None and impulse < 0 and forward is not None:
            mem.down_forward(start).add(forward)


@dataclass
class NextResult:
    spells: dict[str, list[dict[str, Any]]]
    sessions: list[date]


def run_next(
    book: dict[tuple[str, date], list[dict[str, Any]]],
    specs: tuple[BookSpec, ...] = BOOKS,
    *,
    allow_holdout: bool = False,
) -> NextResult:
    assert_no_holdout(book, allow_holdout=allow_holdout)
    names = list(dict.fromkeys([*RANK_SYMBOLS]))
    memory = {symbol: SymbolMemory() for symbol in names}
    spells: dict[str, list[dict[str, Any]]] = {spec.name: [] for spec in specs}
    sessions: list[date] = []
    days = sorted({day for (_symbol, day) in book})
    for day in days:
        if day >= HOLDOUT_START and not allow_holdout:
            raise RuntimeError(f"holdout day {day} leaked into the next grid batch")
        prepared: dict[str, DayView] = {}
        for symbol in names:
            bars = book.get((symbol, day))
            if not bars:
                continue
            view = prepare_day(bars)
            if view is not None:
                prepared[symbol] = view
        if VALIDATE_START <= day <= VALIDATE_END and "SPY" in prepared:
            sessions.append(day)
        spy = memory["SPY"].below_average() if "SPY" in memory else None
        qqq = memory["QQQ"].below_average() if "QQQ" in memory else None
        for spec in specs:
            if spec.kind == "exit":
                for symbol in CANDIDATES:
                    view = prepared.get(symbol)
                    if view is None:
                        continue
                    spell = _orb_spell(view, day, symbol, spec)
                    if spell is not None:
                        spells[spec.name].append(spell)
                continue
            regime = vote_regime(spy, qqq, enabled=spec.regime)
            chosen = rank_candidates(_rank_rows(spec, day, prepared, memory, regime), spec.top_k, regime.veto)
            for spell in chosen:
                spell.pop("start", None)
                spells[spec.name].append(spell)
        for symbol, view in prepared.items():
            _update_memory(memory[symbol], view)
    return NextResult(spells, sessions)


def in_pooled(day: date) -> bool:
    return TRAIN_START <= day <= VALIDATE_END and day >= date(2023, 1, 1)


def in_validation(day: date) -> bool:
    return VALIDATE_START <= day <= VALIDATE_END


def in_recent(day: date) -> bool:
    return RECENT_START <= day <= VALIDATE_END
