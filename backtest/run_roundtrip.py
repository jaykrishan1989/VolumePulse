"""Select an appear-to-disappear rule on validation, then read the holdout once.

``python -m backtest.run_roundtrip select`` never scores a holdout date.
``python -m backtest.run_roundtrip holdout`` reads the frozen spec and evaluates
it one time. Do not edit the frozen id after that read.

Nothing in this module places an order.
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from backtest.data import CANDIDATES, bars_from_frame, load_symbol, sessions
from backtest.periods import HOLDOUT_START, TRAIN_END, TRAIN_START, VALIDATE_END, VALIDATE_START
from backtest.scan import CACHE_DIR, load_membership
from backtest.spells import ACCOUNT_USD, SLIP_BPS, build_spells, portfolio, selection_hits, simulate_spell, summarize_portfolio

# Eight cells, written down before the membership scan was scored.
PASS1: list[dict[str, Any]] = [
    {"id": "confirm1_lag1", "confirm": 1, "exit_lag": 1},
    {"id": "lag2", "confirm": 1, "exit_lag": 2},
    {"id": "lag3", "confirm": 1, "exit_lag": 3},
    {"id": "confirm2_lag2", "confirm": 2, "exit_lag": 2},
    {"id": "score80", "confirm": 1, "exit_lag": 1, "min_score": 80},
    {"id": "morning", "confirm": 1, "exit_lag": 1, "minute_from": 600, "minute_to": 720},
    {"id": "vwap_reclaim", "confirm": 1, "exit_lag": 1, "require_vwap_reclaim": True},
    {"id": "rr2", "confirm": 1, "exit_lag": 1, "min_rr": 2.0},
]

FROZEN_PATH = CACHE_DIR / "roundtrip_frozen.json"
SELECTION_PATH = CACHE_DIR / "roundtrip_selection.json"
HOLDOUT_PATH = CACHE_DIR / "roundtrip_holdout.json"
RULE_PATH = Path(__file__).resolve().parents[1] / "app" / "signal_rule.json"
STATS_PATH = Path(__file__).resolve().parents[1] / "app" / "research_stats.json"
MIN_TRADES = 80


def _trading_days(book: dict[tuple[str, date], list[dict[str, Any]]], start: date, end: date) -> int:
    days = {day for (symbol, day) in book if symbol == "AAPL" and start <= day <= end}
    if not days:
        days = {day for (_symbol, day) in book if start <= day <= end}
    return len(days)


def _profit_factor(trades: list[dict[str, Any]]) -> float | None:
    wins = sum(trade["net"] for trade in trades if trade["net"] > 0)
    losses = sum(-trade["net"] for trade in trades if trade["net"] < 0)
    if losses <= 1e-9:
        return None
    return wins / losses


def _window(hits: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [hit for hit in hits if start <= hit["day"] <= end]


def evaluate(
    hits: list[dict[str, Any]],
    book: dict[tuple[str, date], list[dict[str, Any]]],
    spec: dict[str, Any],
    start: date,
    end: date,
    *,
    keep_trades: bool = False,
) -> dict[str, Any]:
    if any(hit["day"] >= HOLDOUT_START for hit in hits) and end >= HOLDOUT_START and start < HOLDOUT_START:
        raise RuntimeError("selection window leaked into the holdout")
    spells = build_spells(_window(hits, start, end), book, spec)
    days = _trading_days(book, start, end)
    variants = {
        "withStop": {"use_stop": True, "schedule": "tiered"},
        "withoutStop": {"use_stop": False, "schedule": "tiered"},
        "fixedStop": {"use_stop": True, "schedule": "fixed"},
    }
    out: dict[str, Any] = {"id": spec["id"], "spec": spec, "spells": len(spells)}
    for label, kwargs in variants.items():
        result = portfolio(spells, equity=ACCOUNT_USD, slip_bps=SLIP_BPS, **kwargs)
        stats = summarize_portfolio(result, days)
        stats["profitFactor"] = _profit_factor(result["trades"])
        out[label] = stats
        if keep_trades and label == "withStop":
            out["taken"] = result["trades"]
            out["spellByKey"] = {(spell["symbol"], int(spell["entry_t"])): spell for spell in spells}
    return out


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "spec": row["spec"],
        "spells": row["spells"],
        "withStop": row["withStop"],
        "withoutStop": row["withoutStop"],
        "fixedStop": row["fixedStop"],
        "eligible": (row["withStop"]["trades"] or 0) >= MIN_TRADES,
    }


def _rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> tuple:
        eligible = (row["withStop"]["trades"] or 0) >= MIN_TRADES
        net = row["withStop"]["net"]
        return (0 if eligible else 1, -(net if net is not None else -1e18))

    return sorted(rows, key=key)


def propose_second_pass(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """At most four cells. The branch uses only validation summaries already in hand."""
    by_id = {row["id"]: row for row in rows}
    base = by_id["confirm1_lag1"]
    specs: list[dict[str, Any]] = []
    reasons = base["withStop"].get("reasons") or {}
    total = sum(reasons.values()) or 1
    if reasons.get("stop", 0) / total >= 0.4 or base["withoutStop"]["net"] > base["withStop"]["net"]:
        specs.append({"id": "wide_stop_1_5", "confirm": 1, "exit_lag": 1, "stop_scale": 1.5})
    lag_ids = ["confirm1_lag1", "lag2", "lag3", "confirm2_lag2"]
    best_lag = max(lag_ids, key=lambda item: by_id[item]["withStop"]["net"])
    if best_lag == "lag3":
        specs.append({"id": "lag4", "confirm": 1, "exit_lag": 4})
    elif best_lag == "confirm2_lag2":
        specs.append({"id": "confirm3_lag3", "confirm": 3, "exit_lag": 3})
    else:
        specs.append({"id": "confirm2_lag1", "confirm": 2, "exit_lag": 1})
    if by_id["morning"]["withStop"]["net"] > base["withStop"]["net"]:
        specs.append({"id": "midmorning", "confirm": 1, "exit_lag": 1, "minute_from": 600, "minute_to": 660})
    else:
        specs.append({"id": "midday", "confirm": 1, "exit_lag": 1, "minute_from": 660, "minute_to": 840})
    if by_id["score80"]["withStop"]["net"] > base["withStop"]["net"]:
        specs.append({"id": "score85", "confirm": 1, "exit_lag": 1, "min_score": 85})
    else:
        specs.append({"id": "rr_1_5", "confirm": 1, "exit_lag": 1, "min_rr": 1.5})
    return specs[:4]


def _load_book() -> dict[tuple[str, date], list[dict[str, Any]]]:
    book: dict[tuple[str, date], list[dict[str, Any]]] = {}
    for symbol in CANDIDATES:
        print(f"loading {symbol}", flush=True)
        for day, frame in sessions(load_symbol(symbol)):
            book[(symbol, day)] = bars_from_frame(frame)
    return book


def _write_rule(spec: dict[str, Any]) -> None:
    payload = {
        "id": spec["id"],
        "confirm": int(spec.get("confirm") or 1),
        "exit_lag": int(spec.get("exit_lag") or 1),
        "min_score": spec.get("min_score"),
        "min_rr": spec.get("min_rr"),
        "min_rvol": spec.get("min_rvol"),
        "require_vwap_reclaim": bool(spec.get("require_vwap_reclaim") or False),
        "minute_from": spec.get("minute_from"),
        "minute_to": spec.get("minute_to"),
        "stop_scale": float(spec.get("stop_scale") or 1.0),
        "use_stop": True,
        "note": "Frozen on the validation window. The holdout was not used to pick this.",
    }
    RULE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def select() -> dict[str, Any]:
    raw = load_membership()
    pre = selection_hits(raw)
    if any(hit["day"] >= HOLDOUT_START for hit in pre):
        raise RuntimeError("holdout row leaked into selection")
    validation = _window(pre, VALIDATE_START, VALIDATE_END)
    train = _window(pre, TRAIN_START, TRAIN_END)
    print(f"validation on-list bars {len(validation)} train {len(train)}", flush=True)
    book = _load_book()
    rows = []
    for spec in PASS1:
        print(f"pass1 {spec['id']}", flush=True)
        rows.append(evaluate(validation, book, spec, VALIDATE_START, VALIDATE_END))
    ranked = _rank(rows)
    positive = [row for row in ranked if row["withStop"]["net"] > 0 and (row["withStop"]["trades"] or 0) >= MIN_TRADES]
    second: list[dict[str, Any]] = []
    if not positive:
        extra = propose_second_pass(rows)
        print("pass1 had no net-positive eligible rule", flush=True)
        for spec in extra:
            print(f"pass2 {spec['id']}", flush=True)
            second.append(evaluate(validation, book, spec, VALIDATE_START, VALIDATE_END))
        ranked = _rank(rows + second)
        positive = [row for row in ranked if row["withStop"]["net"] > 0 and (row["withStop"]["trades"] or 0) >= MIN_TRADES]
    chosen = ranked[0]
    train_base = evaluate(train, book, PASS1[0], TRAIN_START, TRAIN_END)
    payload = {
        "accountUsd": ACCOUNT_USD,
        "slipBps": SLIP_BPS,
        "minTrades": MIN_TRADES,
        "pass1": [_public(row) for row in rows],
        "pass2": [_public(row) for row in second],
        "chosenId": chosen["id"],
        "chosenSpec": chosen["spec"],
        "validationPositive": bool(positive),
        "trainBaseline": _public(train_base),
        "trials": len(rows) + len(second),
        "note": (
            "Chosen by validation portfolio net dollars after tiered commissions, "
            "2 bp slippage, and the hard stop, on a US$2,120 account. "
            "Holdout dates were excluded."
        ),
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SELECTION_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    frozen = {"id": chosen["id"], "spec": chosen["spec"], "validationNet": chosen["withStop"]["net"]}
    FROZEN_PATH.write_text(json.dumps(frozen, indent=2) + "\n", encoding="utf-8")
    _write_rule(chosen["spec"])
    print(
        f"froze {chosen['id']} validation net {chosen['withStop']['net']:.2f} "
        f"trades {chosen['withStop']['trades']}",
        flush=True,
    )
    return payload


def _bootstrap_dollars(trades: list[dict[str, Any]], draws: int = 2000, seed: int = 7) -> dict[str, Any]:
    by_day: dict[date, float] = defaultdict(float)
    for trade in trades:
        by_day[trade["day"]] += trade["net"]
    days = list(by_day.values())
    if not days:
        return {"draws": 0, "pValue": None}
    rng = random.Random(seed)
    n_days = len(days)
    below = 0
    for _ in range(draws):
        total = sum(days[rng.randrange(n_days)] for _ in range(n_days))
        if total <= 0:
            below += 1
    return {"draws": draws, "pValue": below / draws, "days": n_days}


def _random_p(
    trades: list[dict[str, Any]],
    spell_by_key: dict[tuple[str, int], dict[str, Any]],
    book: dict[tuple[str, date], list[dict[str, Any]]],
    *,
    use_stop: bool,
    draws: int = 200,
    seed: int = 11,
) -> dict[str, Any]:
    """Same symbol, same entry minute, same hold, another session."""
    usable_days: dict[str, list[date]] = defaultdict(list)
    minute_index: dict[tuple[str, date], dict[int, int]] = {}
    for (symbol, day), bars in book.items():
        usable_days[symbol].append(day)
        minute_index[(symbol, day)] = {int(bar["minute"]): index for index, bar in enumerate(bars)}
    plans = []
    for trade in trades:
        spell = spell_by_key.get((trade["symbol"], trade["entry_t"]))
        if spell is None:
            continue
        entry_open = float(spell["entry_bar"]["open"])
        if entry_open <= 0:
            continue
        plans.append(
            {
                "symbol": trade["symbol"],
                "day": trade["day"],
                "entry_minute": int(spell["entry_bar"]["minute"]),
                "exit_minute": int(spell["exit_bar"]["minute"]),
                "exit_kind": spell["exit_kind"],
                "entry_open": entry_open,
                "stop_gap": entry_open - float(spell["stop"]),
            }
        )
    if not plans:
        return {"draws": 0, "pValue": None, "randomMeanBps": None}
    actual = []
    for trade in trades:
        spell = spell_by_key.get((trade["symbol"], trade["entry_t"]))
        if spell is None:
            continue
        full = simulate_spell(spell, use_stop=use_stop, equity=ACCOUNT_USD)
        if full is not None:
            actual.append(full["ret"] * 10_000.0)
    if not actual:
        return {"draws": 0, "pValue": None, "randomMeanBps": None}
    actual_mean = sum(actual) / len(actual)
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        rets = []
        for plan in plans:
            days = usable_days.get(plan["symbol"]) or []
            if len(days) < 2:
                continue
            for _try in range(8):
                day = days[rng.randrange(len(days))]
                if day == plan["day"]:
                    continue
                index = minute_index.get((plan["symbol"], day)) or {}
                entry_i = index.get(plan["entry_minute"])
                exit_i = index.get(plan["exit_minute"])
                if entry_i is None or exit_i is None or exit_i <= entry_i:
                    continue
                bars = book[(plan["symbol"], day)]
                entry_open = float(bars[entry_i]["open"])
                scale = entry_open / plan["entry_open"] if plan["entry_open"] else 1.0
                spell = {
                    "symbol": plan["symbol"],
                    "day": day,
                    "entry_t": int(bars[entry_i].get("t") or 0),
                    "exit_t": int(bars[exit_i].get("t") or 0),
                    "stop": entry_open - plan["stop_gap"] * scale,
                    "score": 0,
                    "entry_bar": bars[entry_i],
                    "exit_bar": bars[exit_i],
                    "path": bars[entry_i:exit_i],
                    "exit_kind": plan["exit_kind"],
                }
                break
            else:
                continue
            trade_sim = simulate_spell(spell, use_stop=use_stop, equity=ACCOUNT_USD)
            if trade_sim is not None:
                rets.append(trade_sim["ret"] * 10_000.0)
        if rets:
            means.append(sum(rets) / len(rets))
    if not means:
        return {"draws": 0, "pValue": None, "randomMeanBps": None, "strategyMeanBps": actual_mean}
    beaten = sum(1 for value in means if value + 1e-9 >= actual_mean)
    return {
        "draws": len(means),
        "pValue": beaten / len(means),
        "randomMeanBps": sum(means) / len(means),
        "strategyMeanBps": actual_mean,
    }


def holdout() -> dict[str, Any]:
    if not FROZEN_PATH.exists():
        raise RuntimeError("freeze a validation rule before reading the holdout")
    frozen = json.loads(FROZEN_PATH.read_text(encoding="utf-8"))
    spec = frozen["spec"]
    raw = load_membership()
    # One read. The spec above was frozen without these dates.
    window = [hit for hit in raw if hit["day"] >= HOLDOUT_START]
    print(f"holdout on-list bars {len(window)} spec {spec['id']}", flush=True)
    book = _load_book()
    scored = evaluate(window, book, spec, HOLDOUT_START, date(2026, 12, 31), keep_trades=True)
    trades = scored.pop("taken")
    spell_by_key = scored.pop("spellByKey")
    boot = _bootstrap_dollars(trades)
    print("random entries", flush=True)
    random_vs = _random_p(trades, spell_by_key, book, use_stop=True)
    net = scored["withStop"]["net"]
    worth = bool(net > 0 and (boot.get("pValue") or 1) < 0.05 and (random_vs.get("pValue") or 1) < 0.05)
    if worth:
        verdict = (
            f"{spec['id']} was net positive on the locked holdout after costs and beat random entries. "
            "Signals are still manual. Volume Pulse does not place orders."
        )
    else:
        verdict = (
            "No appear-to-disappear rule kept a cost-inclusive edge on the locked holdout. Do not trade it."
        )
    previous = {}
    if STATS_PATH.exists():
        try:
            previous = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    bracket = previous.get("bracket") or {
        "chosenId": previous.get("chosenId"),
        "shippedRule": previous.get("shippedRule"),
        "holdout": previous.get("holdout"),
        "validation": previous.get("validation"),
        "accountUsd": previous.get("accountUsd"),
        "verdict": previous.get("verdict"),
    }
    payload = {
        "rule": "appear_disappear",
        "chosenId": spec["id"],
        "shippedRule": spec["id"],
        "spec": spec,
        "worthTrading": worth,
        "verdict": verdict,
        "accountUsd": ACCOUNT_USD,
        "slipBps": SLIP_BPS,
        "schedule": "tiered",
        "holdout": scored["withStop"],
        "holdoutWithoutStop": scored["withoutStop"],
        "holdoutFixed": scored["fixedStop"],
        "validationNet": frozen.get("validationNet"),
        "bootstrap": boot,
        "random": random_vs,
        "trials": json.loads(SELECTION_PATH.read_text(encoding="utf-8")).get("trials") if SELECTION_PATH.exists() else None,
        "bracket": bracket,
    }
    STATS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    scored_public = dict(scored)
    scored_public["bootstrap"] = boot
    scored_public["random"] = random_vs
    scored_public["worthTrading"] = worth
    scored_public["verdict"] = verdict
    HOLDOUT_PATH.write_text(json.dumps(scored_public, indent=2) + "\n", encoding="utf-8")
    print(verdict, flush=True)
    print(
        f"holdout net {net:.2f} ({scored['withStop']['returnPct']:.2f}%) "
        f"trades {scored['withStop']['trades']} win {scored['withStop']['winRate']}",
        flush=True,
    )
    return payload


def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else "select"
    if phase == "select":
        select()
    elif phase == "holdout":
        holdout()
    else:
        raise SystemExit("use select or holdout")


if __name__ == "__main__":
    main()
