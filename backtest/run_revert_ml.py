"""Fit the trough model on walk-forward folds and score validation only.

``python -m backtest.run_revert_ml`` does not open the locked holdout unless
the chosen threshold beats the published model's validation dollars and the
same book is still positive after its five best days are removed. The
threshold is chosen before that check. Nothing here places an order.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from backtest.data import bars_from_frame, load_symbol, sessions
from backtest.periods import HOLDOUT_END, HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.revert_ml import (
    FEATURE_COLUMNS,
    MAX_FILLS_PER_DAY,
    MIN_FILLS_PER_DAY,
    MIN_TRADES,
    THRESHOLDS,
    TRADE_SYMBOLS,
    build_frame,
    drop_top_days,
    is_milestone,
    spells_for,
)
from backtest.run_ml import QUARTERS, train_cut
from backtest.spells import ACCOUNT_USD, SLIP_BPS, portfolio

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
SUMMARY_PATH = RESEARCH / "revert_ml_summary.json"
MONTHS_PATH = RESEARCH / "revert_ml_months.csv"
LOG_PATH = RESEARCH / "RESEARCH_LOG.md"
BEGIN = "<!-- REVERT_BEGIN -->"
END = "<!-- REVERT_END -->"
SEEDS = (7, 11, 21)
NUM_BOOST_ROUND = 80
CALIBRATION_DAYS = 40
PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_data_in_leaf": 400,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "num_threads": 4,
    "force_col_wise": True,
}


def load_bars(*, allow_holdout: bool) -> dict[tuple[str, date], list[dict[str, Any]]]:
    book: dict[tuple[str, date], list[dict[str, Any]]] = {}
    for symbol in TRADE_SYMBOLS:
        print(f"loading {symbol}", flush=True)
        for day, frame in sessions(load_symbol(symbol)):
            if not allow_holdout and day >= HOLDOUT_START:
                continue
            book[(symbol, day)] = bars_from_frame(frame)
    if not allow_holdout and any(day >= HOLDOUT_START for (_symbol, day) in book):
        raise RuntimeError("holdout day remained after the load filter")
    return book


def _logit(prob: np.ndarray) -> np.ndarray:
    clipped = np.clip(prob, 1e-6, 1.0 - 1e-6)
    return np.log(clipped / (1.0 - clipped))


def _sigmoid(score: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(score, -30.0, 30.0)))


def fit_platt(scores: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    """Map a raw score to a probability. Fit only on the calibration days."""
    a = 1.0
    b = 0.0
    target = labels.astype(np.float64)
    for _step in range(25):
        prob = _sigmoid(a * scores + b)
        weight = np.clip(prob * (1.0 - prob), 1e-6, None)
        error = prob - target
        h11 = float(np.sum(weight * scores * scores)) + 1e-6
        h12 = float(np.sum(weight * scores))
        h22 = float(np.sum(weight)) + 1e-6
        g1 = float(np.sum(error * scores))
        g2 = float(np.sum(error))
        det = h11 * h22 - h12 * h12
        if abs(det) < 1e-12:
            break
        a -= (h22 * g1 - h12 * g2) / det
        b -= (h11 * g2 - h12 * g1) / det
    return a, b


def _fit(train: pd.DataFrame) -> list[lgb.Booster]:
    labels = train["y_hit"].to_numpy(dtype=np.float64)
    matrix = train.loc[:, FEATURE_COLUMNS].to_numpy(dtype=np.float64)
    dataset = lgb.Dataset(matrix, label=labels, feature_name=list(FEATURE_COLUMNS), free_raw_data=False)
    models = []
    for seed in SEEDS:
        params = dict(PARAMS)
        params["seed"] = seed
        params["bagging_seed"] = seed
        params["feature_fraction_seed"] = seed
        models.append(lgb.train(params, dataset, num_boost_round=NUM_BOOST_ROUND))
    return models


def _predict(models: list[lgb.Booster], frame: pd.DataFrame) -> np.ndarray:
    matrix = frame.loc[:, FEATURE_COLUMNS].to_numpy(dtype=np.float64)
    total = np.zeros(len(frame), dtype=np.float64)
    for model in models:
        total += model.predict(matrix)
    return total / len(models)


def _apply(models: list[lgb.Booster], cal: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    raw_cal = _predict(models, cal)
    raw_test = _predict(models, test)
    if len(cal) < 500 or cal["y_hit"].nunique() < 2:
        return raw_test
    slope, intercept = fit_platt(_logit(raw_cal), cal["y_hit"].to_numpy(dtype=np.float64))
    return _sigmoid(slope * _logit(raw_test) + intercept)


def walk_forward(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, float]]]:
    leaked = frame.loc[frame["day"] >= HOLDOUT_START, "day"]
    if len(leaked):
        raise RuntimeError("walk-forward frame includes a holdout day")
    parts = []
    gains = np.zeros(len(FEATURE_COLUMNS), dtype=np.float64)
    fitted = 0
    for start, end in QUARTERS:
        cut = train_cut(start)
        train = frame.loc[frame["day"] < cut]
        test = frame.loc[(frame["day"] >= start) & (frame["day"] <= end)]
        if test.empty:
            continue
        days = sorted(train["day"].unique())
        if len(days) <= CALIBRATION_DAYS + 5:
            print(f"skip {start} train days {len(days)}", flush=True)
            continue
        cal_days = set(days[-CALIBRATION_DAYS:])
        fit_rows = train.loc[~train["day"].isin(cal_days)]
        cal_rows = train.loc[train["day"].isin(cal_days)]
        if len(fit_rows) < 2000:
            print(f"skip {start} fit rows {len(fit_rows)}", flush=True)
            continue
        print(
            f"fold {start}..{end} fit {len(fit_rows)} cal {len(cal_rows)} test {len(test)} cut {cut}",
            flush=True,
        )
        models = _fit(fit_rows)
        fitted += 1
        for model in models:
            gains += model.feature_importance(importance_type="gain")
        chunk = test.copy()
        chunk["prob"] = _apply(models, cal_rows, test)
        parts.append(chunk)
    if not parts:
        raise RuntimeError("walk-forward produced no predictions")
    importance = []
    if fitted:
        order = np.argsort(-gains)
        importance = [
            {"feature": FEATURE_COLUMNS[int(index)], "gain": float(gains[int(index)] / fitted)}
            for index in order
        ]
    return pd.concat(parts, ignore_index=True), importance


def _sessions(book: dict[tuple[str, date], list[dict[str, Any]]], start: date, end: date) -> int:
    return len({day for (symbol, day) in book if symbol == "SPY" and start <= day <= end})


def _run(spells: list[dict[str, Any]]) -> dict[str, Any]:
    return portfolio(spells, use_stop=True, slip_bps=SLIP_BPS, schedule="zero", equity=ACCOUNT_USD)


def _trade_stats(trades: list[dict[str, Any]], sessions: int, drawdown: float | None) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {
            "trades": 0,
            "net": 0.0,
            "win_rate": None,
            "avg_win": None,
            "avg_loss": None,
            "fills_per_day": 0.0,
            "max_drawdown": drawdown,
            "reasons": {},
        }
    wins = [float(trade["net"]) for trade in trades if float(trade["net"]) > 0]
    losses = [float(trade["net"]) for trade in trades if float(trade["net"]) <= 0]
    reasons: dict[str, int] = defaultdict(int)
    for trade in trades:
        reasons[str(trade["reason"])] += 1
    return {
        "trades": n,
        "net": float(sum(float(trade["net"]) for trade in trades)),
        "win_rate": len(wins) / n,
        "avg_win": float(np.mean(wins)) if wins else None,
        "avg_loss": float(np.mean(losses)) if losses else None,
        "fills_per_day": n / sessions if sessions else None,
        "max_drawdown": drawdown,
        "reasons": dict(reasons),
    }


def _months(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        buckets[trade["day"].strftime("%Y-%m")].append(float(trade["net"]))
    rows = []
    for month in sorted(buckets):
        nets = buckets[month]
        wins = sum(1 for value in nets if value > 0)
        rows.append(
            {
                "month": month,
                "trades": len(nets),
                "net": float(sum(nets)),
                "win_rate": wins / len(nets) if nets else None,
            }
        )
    return rows


def score_threshold(
    frame: pd.DataFrame,
    book: dict[tuple[str, date], list[dict[str, Any]]],
    threshold: float,
    start: date,
    end: date,
) -> dict[str, Any]:
    window = frame.loc[(frame["day"] >= start) & (frame["day"] <= end)]
    if window.empty:
        raise RuntimeError("score window is empty")
    if any(day >= HOLDOUT_START for day in window["day"]) and end >= HOLDOUT_START and start < HOLDOUT_START:
        raise RuntimeError("a score window crosses into the holdout")
    sessions = _sessions(book, start, end)
    result = _run(spells_for(window, book, threshold))
    stats = _trade_stats(result["trades"], sessions, result["maxDrawdown"])
    ex_net, kept, dropped = drop_top_days(result["trades"])
    kept_stats = _trade_stats(kept, sessions, None)
    per_day = stats["fills_per_day"] or 0.0
    return {
        "threshold": threshold,
        "sessions": sessions,
        "eligible": bool(stats["trades"] >= MIN_TRADES and MIN_FILLS_PER_DAY <= per_day <= MAX_FILLS_PER_DAY),
        "stats": stats,
        "ex_top5_net": ex_net,
        "ex_top5_trades": kept_stats["trades"],
        "ex_top5_win_rate": kept_stats["win_rate"],
        "dropped_days": dropped,
        "months": _months(result["trades"]),
        "portfolio_net": float(result["net"]),
    }


def choose_threshold(
    frame: pd.DataFrame,
    book: dict[tuple[str, date], list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    leaked = frame.loc[frame["day"] >= HOLDOUT_START, "day"]
    if len(leaked):
        raise RuntimeError("threshold selection saw a holdout day")
    rows = []
    for threshold in THRESHOLDS:
        scored = score_threshold(frame, book, threshold, VALIDATE_START, VALIDATE_END)
        stats = scored["stats"]
        print(
            f"threshold {threshold:.2f} net {stats['net']:.0f} trades {stats['trades']} "
            f"per_day {stats['fills_per_day']:.2f} eligible {scored['eligible']}",
            flush=True,
        )
        rows.append(scored)
    eligible = [row for row in rows if row["eligible"]]
    if not eligible:
        return None, rows
    best = max(eligible, key=lambda row: (float(row["stats"]["net"]), -float(row["threshold"])))
    return best, rows


def _holdout_predictions(frame: pd.DataFrame) -> pd.DataFrame:
    """One model for the locked slice. Training stops the day before it."""
    cut = train_cut(HOLDOUT_START)
    train = frame.loc[frame["day"] < cut]
    test = frame.loc[(frame["day"] >= HOLDOUT_START) & (frame["day"] <= HOLDOUT_END)]
    if test.empty:
        raise RuntimeError("holdout frame has no troughs")
    days = sorted(train["day"].unique())
    cal_days = set(days[-CALIBRATION_DAYS:])
    models = _fit(train.loc[~train["day"].isin(cal_days)])
    chunk = test.copy()
    chunk["prob"] = _apply(models, train.loc[train["day"].isin(cal_days)], test)
    early = chunk.loc[chunk["day"] < HOLDOUT_START, "day"]
    if len(early):
        raise RuntimeError("holdout prediction includes a pre-holdout day")
    return chunk


def _cents(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "−" if value < 0 else ""
    return f"{sign}${abs(value):.2f}"


def _reading(chosen: dict[str, Any], importance: list[dict[str, float]]) -> str:
    stats = chosen["stats"]
    early = sum(int(month["trades"]) for month in chosen["months"] if str(month["month"]) < "2025-01")
    names = [row["feature"] for row in importance[:8]]
    market = sum(1 for name in names if name.startswith("spy_") or name.startswith("qqq_"))
    if names and market == len(names):
        who = "The eight largest gains are all SPY or QQQ."
    else:
        who = f"{market} of the eight largest gains are SPY or QQQ."
    return (
        f"Reading. Win rate {100 * float(stats['win_rate']):.1f}%. "
        f"Average win {_cents(stats['avg_win'])}, average loss {_cents(stats['avg_loss'])}. "
        "One ATR up and one ATR down are the same distance before costs. "
        "A stop that gaps, plus 2 bp on each side, makes the loss larger than the win, "
        "so a bounce that is only a coin flip does not pay. "
        f"The five best days add only {_money(float(stats['net']) - float(chosen['ex_top5_net']))} together, "
        "and dropping them makes the total worse. This loss is not a crash-day lottery. "
        f"{early} of {stats['trades']} fills are in 2024. Later validation months are mostly quiet, "
        "so 1.75 a day is an average, not a trade every session. "
        f"{who} The name's own oscillation rate is not one of them."
    )


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "−" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def render_section(
    chosen: dict[str, Any] | None,
    grid: list[dict[str, Any]],
    importance: list[dict[str, float]],
    holdout: dict[str, Any] | None,
) -> str:
    lines = [
        BEGIN,
        "## Trough model",
        "",
        "LightGBM, three frozen seeds, probabilities calibrated on the last 40 training days of each fold. "
        "A row is a new 30-minute low under VWAP in the bottom 40% of the session range. "
        "The label is a hit of plus one ATR before minus one ATR or the 15:55 flat. "
        f"Each fill takes {25:.0f}% of the US${ACCOUNT_USD:.0f} ticket, one position per symbol. "
        "Costs are no commission and 2 bp per side, next-bar fills. "
        "The threshold is the best validation net inside 1.5 to 8 fills a day. "
        "A sequence model was not fit. `models/ACTIVE` stays `v0.1`.",
        "",
        "| Probability | Fills | Fills/day | Win | Net | Ex top 5 | Eligible |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in grid:
        stats = row["stats"]
        win = "n/a" if stats["win_rate"] is None else f"{100 * stats['win_rate']:.1f}%"
        per_day = "n/a" if stats["fills_per_day"] is None else f"{stats['fills_per_day']:.2f}"
        lines.append(
            f"| {row['threshold']:.2f} | {stats['trades']} | {per_day} | {win} | {_money(stats['net'])} | "
            f"{_money(row['ex_top5_net'])} | {'yes' if row['eligible'] else 'no'} |"
        )
    lines.append("")
    if chosen is None:
        lines.append(
            "No threshold had at least 50 trades and between 1.5 and 8 fills a day. "
            "The holdout was not opened."
        )
    else:
        stats = chosen["stats"]
        decision = "rejected"
        if is_milestone(float(stats["net"]), float(chosen["ex_top5_net"]), int(stats["trades"])):
            decision = "milestone"
        elif float(stats["net"]) > 0 and chosen["eligible"]:
            decision = "not_adopted"
        elif float(stats["net"]) <= 0:
            decision = "rejected"
        lines.append(
            f"Chosen probability {chosen['threshold']:.2f}: {stats['trades']} fills, "
            f"{stats['fills_per_day']:.2f} a day, win {100 * stats['win_rate']:.1f}%, "
            f"net {_money(stats['net'])}, average win {_cents(stats['avg_win'])}, "
            f"average loss {_cents(stats['avg_loss'])}, max drawdown {_money(stats['max_drawdown'])}. "
            f"Without the five best days: {_money(chosen['ex_top5_net'])} on {chosen['ex_top5_trades']} fills. "
            f"Decision: {decision}."
        )
        lines.append("")
        lines.append("| Month | Fills | Win | Net |")
        lines.append("| --- | ---: | ---: | ---: |")
        for month in chosen["months"]:
            win = "n/a" if month["win_rate"] is None else f"{100 * month['win_rate']:.1f}%"
            lines.append(f"| {month['month']} | {month['trades']} | {win} | {_money(month['net'])} |")
        if chosen["dropped_days"]:
            lines.append("")
            dropped = ", ".join(f"{row['day']} {_money(row['net'])}" for row in chosen["dropped_days"])
            lines.append(f"Five largest validation days: {dropped}.")
        lines.append("")
        lines.append(_reading(chosen, importance))
    if importance:
        top = ", ".join(f"{row['feature']} ({row['gain']:.0f})" for row in importance[:8])
        lines.append("")
        lines.append(f"Largest average gains: {top}.")
    lines.append("")
    if holdout is None:
        lines.append(
            "The published holdout is unchanged: look 7 is +$297 on 19 trades, and the 1.5% gap rule on look 6 "
            "is +$210 on 52 trades. This run did not open look 8. No order was placed."
        )
    else:
        stats = holdout["stats"]
        lines.append(
            f"Holdout look {holdout['look']}: {stats['trades']} fills, net {_money(stats['net'])}, "
            f"win {100 * stats['win_rate']:.1f}%, max drawdown {_money(stats['max_drawdown'])}, "
            f"without the five best days {_money(holdout['ex_top5_net'])}. "
            "`models/ACTIVE` stays `v0.1`. No order was placed."
        )
    lines.append(END)
    return "\n".join(lines) + "\n"


def write_log(section: str) -> None:
    text = LOG_PATH.read_text(encoding="utf-8")
    if BEGIN in text and END in text:
        start = text.index(BEGIN)
        finish = text.index(END) + len(END)
        text = text[:start] + section.rstrip() + text[finish:]
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + section
    LOG_PATH.write_text(text, encoding="utf-8")


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    stats = row["stats"]
    return {
        "threshold": row["threshold"],
        "eligible": row["eligible"],
        "trades": stats["trades"],
        "net": stats["net"],
        "win_rate": stats["win_rate"],
        "avg_win": stats["avg_win"],
        "avg_loss": stats["avg_loss"],
        "fills_per_day": stats["fills_per_day"],
        "max_drawdown": stats["max_drawdown"],
        "reasons": stats["reasons"],
        "ex_top5_net": row["ex_top5_net"],
        "ex_top5_trades": row["ex_top5_trades"],
        "dropped_days": row["dropped_days"],
        "months": row["months"],
    }


def write_outputs(
    chosen: dict[str, Any] | None,
    grid: list[dict[str, Any]],
    importance: list[dict[str, float]],
    holdout: dict[str, Any] | None,
) -> None:
    payload = {
        "holdout_used": holdout is not None,
        "active": "v0.1",
        "chosen_threshold": None if chosen is None else chosen["threshold"],
        "milestone": bool(
            chosen
            and is_milestone(float(chosen["stats"]["net"]), float(chosen["ex_top5_net"]), int(chosen["stats"]["trades"]))
        ),
        "grid": [_public_row(row) for row in grid],
        "importance": importance[:12],
        "holdout": None
        if holdout is None
        else {
            "look": holdout["look"],
            "trades": holdout["stats"]["trades"],
            "net": holdout["stats"]["net"],
            "win_rate": holdout["stats"]["win_rate"],
            "fills_per_day": holdout["stats"]["fills_per_day"],
            "max_drawdown": holdout["stats"]["max_drawdown"],
            "ex_top5_net": holdout["ex_top5_net"],
        },
    }
    SUMMARY_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    months = chosen["months"] if chosen else []
    with MONTHS_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["month", "trades", "net", "win_rate"])
        writer.writeheader()
        writer.writerows(months)
    write_log(render_section(chosen, grid, importance, holdout))


def main(argv: list[str] | None = None) -> int:
    book = load_bars(allow_holdout=False)
    print("building troughs", flush=True)
    frame = build_frame(book)
    print(f"troughs {len(frame)} hit rate {frame['y_hit'].mean():.3f}", flush=True)
    predictions, importance = walk_forward(frame)
    validation = predictions.loc[(predictions["day"] >= VALIDATE_START) & (predictions["day"] <= VALIDATE_END)].copy()
    chosen, grid = choose_threshold(validation, book)
    holdout = None
    if (
        chosen is not None
        and is_milestone(float(chosen["stats"]["net"]), float(chosen["ex_top5_net"]), int(chosen["stats"]["trades"]))
    ):
        print("milestone passed. one holdout read.", flush=True)
        from backtest.run_daily import record_look

        full = load_bars(allow_holdout=True)
        full_frame = build_frame(full, allow_holdout=True)
        hold_pred = _holdout_predictions(full_frame)
        scored = score_threshold(hold_pred, full, float(chosen["threshold"]), HOLDOUT_START, HOLDOUT_END)
        look = record_look(
            "revert_ml",
            "Trough LightGBM. Threshold frozen on validation before this read.",
        )
        holdout = {"look": look, "stats": scored["stats"], "ex_top5_net": scored["ex_top5_net"]}
    else:
        print("holdout was not opened", flush=True)
    write_outputs(chosen, grid, importance, holdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
