"""Walk-forward the one pre-registered intraday model.

``python -m backtest.run_ml`` reads the stored 5-minute bars. It does not open
a Gateway socket and it does not place an order.

The entry threshold is chosen on the validation window only. The holdout is
read once after that choice is on disk. Predictions in a test fold come from a
model trained on earlier days, with the day before the fold removed.
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from backtest.costs import PRIMARY_SCHEDULE
from backtest.gate import (
    HALF_YEARS,
    POOLED_END,
    POOLED_START,
    GateVerdict,
    ideas_tried,
    judge,
    label_regimes,
)
from backtest.ml_panel import build_frame
from backtest.ml_registry import (
    FEATURE_COLUMNS,
    ML_BEGIN,
    ML_END,
    MODEL_ID,
    NUM_BOOST_ROUND,
    SEEDS,
    THRESHOLDS_BPS,
)
from backtest.periods import FLAT_MINUTE, HOLDOUT_END, HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.run_daily import LOOKS_PATH, pack, record_look, spy_days
from backtest.run_gate import _calendar, _spy_closes, champion_record, champion_trades
from backtest.data import CONTEXT, bars_from_frame, load_symbol, sessions
from backtest.run_hypotheses import load_book
from backtest.scan import load_membership
from backtest.spells import ACCOUNT_USD, SLIP_BPS, build_spells, portfolio
from models.registry import Store, create_passing_checkpoint, passes_costs_and_random

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
RULE_PATH = ROOT / "app" / "signal_rule.json"
ACTIVE_PATH = ROOT / "models" / "ACTIVE"
LOG_PATH = RESEARCH / "RESEARCH_LOG.md"
SELECTION_PATH = RESEARCH / "ml_selection.json"
SUMMARY_PATH = RESEARCH / "ml_summary.json"
MODEL_DIR = ROOT / "models" / "ml" / MODEL_ID

QUARTERS: list[tuple[date, date]] = [
    (date(2023, 1, 1), date(2023, 3, 31)),
    (date(2023, 4, 1), date(2023, 6, 30)),
    (date(2023, 7, 1), date(2023, 9, 30)),
    (date(2023, 10, 1), date(2023, 12, 31)),
    (date(2024, 1, 1), date(2024, 3, 31)),
    (date(2024, 4, 1), date(2024, 6, 30)),
    (date(2024, 7, 1), date(2024, 9, 30)),
    (date(2024, 10, 1), date(2024, 12, 31)),
    (date(2025, 1, 1), date(2025, 3, 31)),
    (date(2025, 4, 1), date(2025, 6, 30)),
    (date(2025, 7, 1), date(2025, 9, 30)),
    (date(2025, 10, 1), date(2025, 12, 31)),
    (date(2026, 1, 1), date(2026, 3, 31)),
]

PARAMS = {
    "objective": "regression",
    "metric": "l2",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_data_in_leaf": 500,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "num_threads": 4,
    "force_col_wise": True,
}


def load_ml_book() -> dict[tuple[str, date], list[dict[str, Any]]]:
    """Stored bars for the eight names plus SPY and QQQ. No Gateway socket.

    ``load_book`` already includes SPY. QQQ is context only, so it is attached
    here rather than added to the tradeable book those other runners walk.
    """
    book = load_book(include_holdout=True)
    for symbol in CONTEXT:
        if any(key[0] == symbol for key in book):
            continue
        print(f"loading {symbol}", flush=True)
        for day, frame in sessions(load_symbol(symbol)):
            book[(symbol, day)] = bars_from_frame(frame)
    missing = [symbol for symbol in CONTEXT if not any(key[0] == symbol for key in book)]
    if missing:
        raise RuntimeError("market context missing: " + ", ".join(missing))
    return book


def train_cut(test_start: date) -> date:
    """Last day allowed in a training set. Drops the embargo day and the holdout."""
    embargo = test_start - timedelta(days=1)
    holdout_cut = HOLDOUT_START - timedelta(days=1)
    return min(embargo, holdout_cut)


def _params(seed: int) -> dict[str, Any]:
    out = dict(PARAMS)
    out["seed"] = seed
    out["bagging_seed"] = seed
    out["feature_fraction_seed"] = seed
    return out


def fit_models(train: pd.DataFrame) -> list[lgb.Booster]:
    if len(train) < 5000:
        raise RuntimeError(f"training fold has {len(train)} rows")
    labels = train["y_scaled"].clip(-5.0, 5.0).to_numpy()
    matrix = train.loc[:, FEATURE_COLUMNS].to_numpy(dtype=np.float64)
    dataset = lgb.Dataset(matrix, label=labels, feature_name=list(FEATURE_COLUMNS), free_raw_data=False)
    models = []
    for seed in SEEDS:
        models.append(lgb.train(_params(seed), dataset, num_boost_round=NUM_BOOST_ROUND))
    return models


def predict_scaled(models: list[lgb.Booster], frame: pd.DataFrame) -> np.ndarray:
    matrix = frame.loc[:, FEATURE_COLUMNS].to_numpy(dtype=np.float64)
    total = np.zeros(len(frame), dtype=np.float64)
    for model in models:
        total += model.predict(matrix)
    return total / len(models)


def walk_forward(frame: pd.DataFrame) -> pd.DataFrame:
    """Out-of-sample predictions for days before the holdout."""
    leaked = frame.loc[frame["day"] >= HOLDOUT_START, "day"]
    if len(leaked):
        raise RuntimeError("walk-forward frame includes a holdout day")
    parts = []
    for start, end in QUARTERS:
        cut = train_cut(start)
        train = frame.loc[frame["day"] < cut]
        test = frame.loc[(frame["day"] >= start) & (frame["day"] <= end)]
        if test.empty:
            continue
        print(f"fold {start}..{end} train {len(train)} test {len(test)} cut {cut}", flush=True)
        models = fit_models(train)
        pred = predict_scaled(models, test)
        chunk = test.copy()
        chunk["pred_scaled"] = pred
        chunk["pred_ret"] = pred * chunk["vol"].to_numpy()
        parts.append(chunk)
    if not parts:
        raise RuntimeError("walk-forward produced no predictions")
    return pd.concat(parts, ignore_index=True)


def make_spell(
    book: dict[tuple[str, date], list[dict[str, Any]]],
    row: Any,
    pred_ret: float,
) -> dict[str, Any] | None:
    bars = book.get((row.symbol, row.day))
    if not bars:
        return None
    by_minute = {int(bar["minute"]): index for index, bar in enumerate(bars)}
    signal = by_minute.get(int(row.minute))
    flat_index = by_minute.get(FLAT_MINUTE)
    if signal is None or flat_index is None:
        return None
    entry_index = signal + 1
    if entry_index >= len(bars):
        return None
    exit_index = entry_index + 12
    if exit_index >= len(bars) or int(bars[exit_index]["minute"]) >= FLAT_MINUTE:
        exit_index = flat_index
        exit_kind = "flat"
    else:
        exit_kind = "sell"
    if exit_index <= entry_index:
        return None
    entry_bar = bars[entry_index]
    atr = float(row.atr)
    if atr <= 0:
        return None
    return {
        "symbol": row.symbol,
        "day": row.day,
        "entry_t": int(entry_bar["t"]),
        "exit_t": int(bars[exit_index]["t"]),
        "stop": float(entry_bar["open"]) - atr,
        "priority": float(pred_ret),
        "entry_bar": entry_bar,
        "exit_bar": bars[exit_index],
        "path": bars[entry_index:exit_index],
        "exit_kind": exit_kind,
    }


def spells_for(
    frame: pd.DataFrame,
    book: dict[tuple[str, date], list[dict[str, Any]]],
    threshold: float,
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    ordered = frame.sort_values(["entry_t", "pred_ret"], ascending=[True, False])
    busy: dict[str, int] = {}
    spells = []
    for row in ordered.itertuples(index=False):
        if float(row.pred_ret) < threshold:
            continue
        if int(row.entry_t) < busy.get(row.symbol, 0):
            continue
        spell = make_spell(book, row, float(row.pred_ret))
        if spell is None:
            continue
        spells.append(spell)
        busy[row.symbol] = int(spell["exit_t"])
    return spells


def run_spells(spells: list[dict[str, Any]]) -> dict[str, Any]:
    return portfolio(spells, use_stop=True, schedule=PRIMARY_SCHEDULE, equity=ACCOUNT_USD, slip_bps=SLIP_BPS)


def choose_threshold(
    predictions: pd.DataFrame,
    book: dict[tuple[str, date], list[dict[str, Any]]],
) -> tuple[float, list[dict[str, Any]]]:
    leaked = predictions.loc[predictions["day"] >= HOLDOUT_START, "day"]
    if len(leaked):
        raise RuntimeError("threshold selection saw a holdout day")
    validation = predictions.loc[(predictions["day"] >= VALIDATE_START) & (predictions["day"] <= VALIDATE_END)]
    if validation.empty:
        raise RuntimeError("validation window has no predictions")
    rows = []
    best_bps = None
    best_net = None
    for bps in THRESHOLDS_BPS:
        result = run_spells(spells_for(validation, book, bps / 10_000.0))
        net = float(result["net"])
        print(f"threshold {bps:.0f} bp validation net {net:.0f} trades {len(result['trades'])}", flush=True)
        rows.append({"threshold_bps": bps, "net": net, "trades": len(result["trades"])})
        if best_net is None or net > best_net + 1e-9 or (abs(net - best_net) <= 1e-9 and bps > (best_bps or -1)):
            best_net = net
            best_bps = bps
    if best_bps is None:
        raise RuntimeError("no threshold was scored")
    return best_bps, rows


def _money0(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "−" if value < 0 else ""
    return f"{sign}${abs(value):.0f}"


def _money2(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "−" if value < 0 else ""
    return f"{sign}${abs(value):.2f}"


def _bps(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "−" if value < 0 else ""
    return f"{sign}{abs(value):.1f} bp"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _window_stats(
    predictions: pd.DataFrame,
    book: dict[tuple[str, date], list[dict[str, Any]]],
    threshold: float,
    start: date,
    end: date,
) -> dict[str, Any]:
    window = predictions.loc[(predictions["day"] >= start) & (predictions["day"] <= end)]
    days = [day for day in spy_days(book, start, end)]
    spells = spells_for(window, book, threshold)
    result = run_spells(spells)
    return pack(result["trades"], spells, len(days), result["maxDrawdown"]), result["trades"]


def calibration_rows(predictions: pd.DataFrame) -> list[dict[str, Any]]:
    validation = predictions.loc[(predictions["day"] >= VALIDATE_START) & (predictions["day"] <= VALIDATE_END)].copy()
    if len(validation) < 100:
        return []
    validation["bin"] = pd.qcut(validation["pred_ret"], 10, labels=False, duplicates="drop")
    rows = []
    for bin_id, chunk in validation.groupby("bin"):
        rows.append(
            {
                "bin": int(bin_id),
                "rows": int(len(chunk)),
                "mean_pred_bps": float(chunk["pred_ret"].mean() * 10_000.0),
                "mean_realized_bps": float(chunk["fwd_ret"].mean() * 10_000.0),
            }
        )
    return rows


def importance_rows(models: list[lgb.Booster]) -> list[dict[str, Any]]:
    total = np.zeros(len(FEATURE_COLUMNS))
    for model in models:
        total += model.feature_importance(importance_type="gain")
    total /= len(models)
    order = np.argsort(-total)
    return [{"feature": FEATURE_COLUMNS[int(index)], "gain": float(total[int(index)])} for index in order]


def _write_marked(path: Path, section: str, begin: str, end: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    start = existing.find(begin)
    stop = existing.find(end)
    if start >= 0 and stop >= start:
        updated = existing[:start] + section + existing[stop + len(end) :]
    else:
        updated = existing.rstrip() + "\n\n" + section + "\n"
    path.write_text(updated, encoding="utf-8")


def markdown(
    pooled: dict[str, Any],
    validation: dict[str, Any],
    holdout: dict[str, Any],
    folds: list[dict[str, Any]],
    verdict: GateVerdict,
    threshold_bps: float,
    tried: int,
    look: int,
) -> str:
    wins = sum(1 for window in verdict.windows if window.win)
    lines = [
        ML_BEGIN,
        "## Intraday model",
        "",
        f"`{MODEL_ID}` predicts the 60-minute forward return from the next bar's open, scaled by the prior-day ATR. "
        "Three LightGBM seeds are averaged. Features stop at the signal bar's close. "
        f"The entry threshold is {threshold_bps:.0f} bp of predicted return, chosen on the validation window from "
        "0, 10, 20 and 30 bp before the holdout was loaded. "
        f"Costs are the live model: no commission, {SLIP_BPS:.0f} bp slippage per side, next-bar open, "
        f"US${ACCOUNT_USD:.0f}, flat by 15:55, one ATR stop. "
        f"Bonferroni denominator {tried}. Gate {verdict.decision}, {wins}/{len(verdict.windows)} windows. "
        f"Holdout look {look} was not used to pick the threshold. A checkpoint is written only when the gate "
        "and the costs-and-random bar both pass. `models/ACTIVE` stays `v0.1`. No order was placed.",
        "",
        "| Slice | Trades | Days with a trade | Trades/day | Win | Net | $/trade | bp | Max DD |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, stats in (("Pooled 2023-01-01..2026-03-31", pooled), ("Validation", validation), ("Holdout", holdout)):
        lines.append(
            f"| {name} | {stats['trades']} | {_pct(stats['fill_day_frac'])} | {stats['trades_per_day']:.2f} | "
            f"{_pct(stats['win_rate'])} | {_money0(stats['net'])} | {_money2(stats['per_trade'])} | "
            f"{_bps(stats['bps'])} | {_money0(stats['max_drawdown'])} |"
        )
    lines.append("")
    lines.append("| Window | Trades | Net | $/trade | bp |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for fold in folds:
        per = fold["per_trade"]
        per_text = "n/a" if per is None else (("−" if per < 0 else "") + f"${abs(per):.2f}")
        lines.append(
            f"| {fold['fold']} | {fold['trades']} | {_money0(fold['net'])} | {per_text} | {_bps(fold['bps'])} |"
        )
    lines.append("")
    lines.append(verdict.reason_text())
    lines.append(ML_END)
    return "\n".join(lines) + "\n"


def _champion_holdout(book: dict[tuple[str, date], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    spec = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    hits = [
        hit
        for hit in load_membership()
        if hit["day"] is not None and HOLDOUT_START <= hit["day"] <= HOLDOUT_END
    ]
    early = [hit["day"] for hit in hits if hit["day"] < HOLDOUT_START]
    if early:
        raise RuntimeError(f"champion holdout hit on {min(early)}")
    spells = build_spells(hits, book, spec)
    early_spells = [spell["day"] for spell in spells if spell["day"] < HOLDOUT_START]
    if early_spells:
        raise RuntimeError(f"champion holdout spell on {min(early_spells)}")
    result = portfolio(spells, use_stop=True, schedule=PRIMARY_SCHEDULE, equity=ACCOUNT_USD, slip_bps=SLIP_BPS)
    return list(result["trades"])


def _day_bootstrap(trades: list[dict[str, Any]], draws: int = 2000, seed: int = 7) -> dict[str, Any]:
    by_day: dict[date, float] = {}
    for trade in trades:
        by_day[trade["day"]] = by_day.get(trade["day"], 0.0) + float(trade["net"])
    days = list(by_day.values())
    if not days:
        return {"draws": 0, "pValue": None, "days": 0}
    rng = np.random.default_rng(seed)
    values = np.asarray(days, dtype=np.float64)
    picks = rng.integers(0, len(values), size=(draws, len(values)))
    totals = values[picks].sum(axis=1)
    return {"draws": draws, "pValue": float(np.mean(totals <= 0)), "days": len(values)}


def _random_p(
    frame: pd.DataFrame,
    book: dict[tuple[str, date], list[dict[str, Any]]],
    actual_net: float,
    trade_count: int,
    draws: int = 100,
) -> dict[str, Any]:
    if trade_count < 1 or frame.empty:
        return {"draws": 0, "pValue": None}
    rng = np.random.default_rng(11)
    beaten = 0
    done = 0
    for _ in range(draws):
        sample = frame.sample(frac=1.0, random_state=int(rng.integers(0, 1_000_000_000)))
        busy: dict[str, int] = {}
        spells = []
        for row in sample.itertuples(index=False):
            if int(row.entry_t) < busy.get(row.symbol, 0):
                continue
            spell = make_spell(book, row, 0.0)
            if spell is None:
                continue
            spells.append(spell)
            busy[row.symbol] = int(spell["exit_t"])
            if len(spells) >= trade_count:
                break
        if len(spells) < trade_count:
            continue
        net = float(run_spells(spells)["net"])
        done += 1
        if net + 1e-9 >= actual_net:
            beaten += 1
    if done == 0:
        return {"draws": 0, "pValue": None}
    return {"draws": done, "pValue": beaten / done}


def _look_count() -> int:
    return sum(1 for _row in csv.DictReader(LOOKS_PATH.open(encoding="utf-8")))


def _look_for(rule_id: str) -> int | None:
    found = None
    for row in csv.DictReader(LOOKS_PATH.open(encoding="utf-8")):
        if rule_id in row["rules"]:
            found = int(row["look"])
    return found


def main() -> None:
    looks_before = _look_count()
    prior_look = _look_for(MODEL_ID)
    rule_before = RULE_PATH.read_bytes()
    if ACTIVE_PATH.read_text(encoding="utf-8").strip() != "v0.1":
        raise SystemExit("refusing to train while ACTIVE is not v0.1")
    if PRIMARY_SCHEDULE != "zero":
        raise SystemExit("refusing to train while the cost config is not zero commission")
    print("loading bars", flush=True)
    book = load_ml_book()
    print("building features", flush=True)
    frame = build_frame(book)
    pre = frame.loc[frame["day"] < HOLDOUT_START].copy()
    post = frame.loc[frame["day"] >= HOLDOUT_START].copy()
    print(f"rows pre {len(pre)} holdout {len(post)}", flush=True)
    predictions = walk_forward(pre)
    threshold_bps, threshold_rows = choose_threshold(predictions, book)
    SELECTION_PATH.write_text(
        json.dumps(
            {
                "id": MODEL_ID,
                "threshold_bps": threshold_bps,
                "thresholds": threshold_rows,
                "holdout_used": False,
                "chosen_on": "validation net, 2024-07-01..2026-03-31",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"threshold {threshold_bps:.0f} bp written before the holdout fit", flush=True)
    threshold = threshold_bps / 10_000.0
    pooled_preds = predictions.loc[(predictions["day"] >= POOLED_START) & (predictions["day"] <= POOLED_END)]
    validation_preds = predictions.loc[(predictions["day"] >= VALIDATE_START) & (predictions["day"] <= VALIDATE_END)]
    pooled, pooled_trades = _window_stats(pooled_preds, book, threshold, POOLED_START, POOLED_END)
    validation, _validation_trades = _window_stats(validation_preds, book, threshold, VALIDATE_START, VALIDATE_END)
    print(f"pooled net {pooled['net']:.0f} trades {pooled['trades']}", flush=True)

    tried = ideas_tried()
    champion = champion_trades(book, schedule=PRIMARY_SCHEDULE)
    verdict_preview = judge(
        MODEL_ID,
        champion,
        pooled_trades,
        calendar=_calendar(book),
        regimes=label_regimes(_spy_closes(book), POOLED_START, POOLED_END),
        ideas_tried=tried,
    )
    print(f"pre-holdout gate {verdict_preview.decision}", flush=True)

    cut = train_cut(HOLDOUT_START)
    final_train = pre.loc[pre["day"] < cut]
    print(f"holdout model train {len(final_train)} cut {cut}", flush=True)
    models = fit_models(final_train)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for seed, model in zip(SEEDS, models):
        model.save_model(str(MODEL_DIR / f"seed_{seed}.txt"))
    (MODEL_DIR / "config.json").write_text(
        json.dumps(
            {
                "id": MODEL_ID,
                "schedule": PRIMARY_SCHEDULE,
                "slip_bps": SLIP_BPS,
                "threshold_bps": threshold_bps,
                "features": list(FEATURE_COLUMNS),
                "seeds": list(SEEDS),
                "num_boost_round": NUM_BOOST_ROUND,
                "params": {key: value for key, value in PARAMS.items() if key != "verbose"},
                "train_last_day": cut.isoformat(),
                "holdout_used_to_train": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    importances = importance_rows(models)
    holdout_frame = post.copy()
    if not holdout_frame.empty:
        scaled = predict_scaled(models, holdout_frame)
        holdout_frame["pred_scaled"] = scaled
        holdout_frame["pred_ret"] = scaled * holdout_frame["vol"].to_numpy()
    holdout, holdout_trades = _window_stats(holdout_frame, book, threshold, HOLDOUT_START, HOLDOUT_END)
    fresh_champion = _champion_holdout(book)
    verdict = judge(
        MODEL_ID,
        champion,
        pooled_trades,
        calendar=_calendar(book),
        regimes=label_regimes(_spy_closes(book), POOLED_START, POOLED_END),
        ideas_tried=tried,
        fresh_champion=fresh_champion,
        fresh_challenger=holdout_trades,
    )
    folds = []
    for name, start, end in list(HALF_YEARS) + [("2026Q1", date(2026, 1, 1), date(2026, 3, 31))]:
        stats, _fold_trades = _window_stats(predictions, book, threshold, start, end)
        folds.append({"fold": name, **stats})
        print(f"  {name} net {stats['net']:.0f}", flush=True)
    boot = _day_bootstrap(holdout_trades)
    random_vs = _random_p(holdout_frame, book, float(holdout["net"]), int(holdout["trades"]))
    print(
        f"holdout look {look} net {holdout['net']:.0f} trades {holdout['trades']} "
        f"bootstrap {boot.get('pValue')} random {random_vs.get('pValue')}",
        flush=True,
    )
    look = record_look(
        MODEL_ID,
        "One read after the validation threshold was frozen. Not used to pick the threshold.",
    )
    if _look_for(MODEL_ID) != look or (prior_look is None and _look_count() != looks_before + 1):
        raise SystemExit("holdout look was not the single new row")
    version_results = {"holdout": holdout, "bootstrap": boot, "random": random_vs}
    costs_ok, cost_reasons = passes_costs_and_random(version_results)
    checkpoint = None
    if verdict.passed and costs_ok:
        checkpoint = create_passing_checkpoint(
            Store(),
            version_results,
            {
                "passedGate": True,
                "liveCapable": False,
                "kind": MODEL_ID,
                "status": "passing",
                "signalRule": {"id": MODEL_ID, "note": "Record only. The live list stays appear/disappear."},
                "costs": {"accountUsd": ACCOUNT_USD, "slipBps": SLIP_BPS, "schedule": PRIMARY_SCHEDULE, "flat": "15:55 ET"},
                "thresholdBps": threshold_bps,
                "modelDir": str(MODEL_DIR.relative_to(ROOT)),
            },
        )
        print(f"checkpoint {checkpoint} written; ACTIVE left at v0.1", flush=True)
    elif verdict.passed:
        print("gate passed; no checkpoint: " + "; ".join(cost_reasons), flush=True)
    if ACTIVE_PATH.read_text(encoding="utf-8").strip() != "v0.1":
        raise SystemExit("ACTIVE changed during the run")
    if RULE_PATH.read_bytes() != rule_before:
        raise SystemExit("live signal rule was modified")
    if champion_record().get("replaced"):
        raise SystemExit("champion record was replaced")

    summary = {
        "id": MODEL_ID,
        "threshold_bps": threshold_bps,
        "thresholds": threshold_rows,
        "ideas_tried": tried,
        "decision": verdict.decision,
        "reasons": verdict.reasons,
        "bars": verdict.bars,
        "windows_won": sum(1 for window in verdict.windows if window.win),
        "windows": len(verdict.windows),
        "bootstrap_p": verdict.bootstrap_p,
        "permutation_p": verdict.permutation_p,
        "alpha": verdict.alpha,
        "pooled": pooled,
        "validation": validation,
        "holdout": holdout,
        "holdout_look": look,
        "holdout_bootstrap": boot,
        "holdout_random": random_vs,
        "folds": folds,
        "calibration": calibration_rows(predictions),
        "importance": importances,
        "checkpoint": checkpoint,
        "costs_and_random": costs_ok,
        "cost_reasons": cost_reasons,
        "active": "v0.1",
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    with (RESEARCH / "ml_folds.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["fold", "trades", "net", "per_trade", "bps", "win_rate", "max_drawdown"])
        writer.writeheader()
        for fold in folds:
            writer.writerow({key: fold.get(key) for key in writer.fieldnames})
    with (RESEARCH / "ml_importance.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["feature", "gain"])
        writer.writeheader()
        writer.writerows(importances)
    with (RESEARCH / "ml_calibration.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["bin", "rows", "mean_pred_bps", "mean_realized_bps"])
        writer.writeheader()
        writer.writerows(summary["calibration"])
    with (RESEARCH / "ml_thresholds.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["threshold_bps", "net", "trades"])
        writer.writeheader()
        writer.writerows(threshold_rows)
    _write_marked(
        LOG_PATH,
        markdown(pooled, validation, holdout, folds, verdict, threshold_bps, tried, look),
        ML_BEGIN,
        ML_END,
    )
    print("model files written; champion untouched; no orders", flush=True)


if __name__ == "__main__":
    main()
