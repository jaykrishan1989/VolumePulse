"""Pick one book by validation dollars, then read the holdout once.

``python -m backtest.run_profit`` does not open a Gateway socket and does not
place an order. The selection file is written before either holdout fill.
``models/ACTIVE`` stays ``v0.1``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from backtest.costs import PRIMARY_SCHEDULE
from backtest.daily import DAILY_REGISTRY, build_sessions
from backtest.hypotheses import REGISTRY, allow_holdout_days
from backtest.ml_panel import build_frame
from backtest.ml_registry import SEEDS
from backtest.periods import HOLDOUT_END, HOLDOUT_START, VALIDATE_END, VALIDATE_START
from backtest.profit_grid import (
    BOOKS,
    GAP_EXITS,
    GAPS,
    LABEL_CLIP,
    MIN_TRADES,
    PROFIT_BEGIN,
    PROFIT_END,
    ROUNDS,
    SEQ_COLUMNS,
    SIZES,
    SMALL_PARAMS,
    STOPS,
    THRESHOLDS_BPS,
    WIDE_PARAMS,
    add_return_lags,
    assert_preholdout_days,
    best_of,
    choose_winner,
    gap_spells,
    ml_spells,
    model_specs,
    stack_oos,
    take_spells,
    with_size,
)
from backtest.run_daily import LOOKS_PATH, pack, record_look, spy_days
from backtest.run_gate import champion_record
from backtest.run_ml import QUARTERS, _look_count, _look_for, load_ml_book, train_cut
from backtest.spells import ACCOUNT_USD, SLIP_BPS, portfolio

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
RULE_PATH = ROOT / "app" / "signal_rule.json"
ACTIVE_PATH = ROOT / "models" / "ACTIVE"
LOG_PATH = RESEARCH / "RESEARCH_LOG.md"
SELECTION_PATH = RESEARCH / "profit_selection.json"
SUMMARY_PATH = RESEARCH / "profit_summary.json"
GRID_PATH = RESEARCH / "profit_grid.csv"
MODEL_DIR = ROOT / "models" / "ml" / "profit_ml"
LOOKAHEAD_SUMMARY = RESEARCH / "profit_lookahead_summary.json"
ML_LOOK_ID = "profit_ml_causal"

# Published slippage-only validation net for the frozen down-gap rule.
H5_VALIDATION_NET = 194.14669214287954
PARAMS = {"small": SMALL_PARAMS, "wide": WIDE_PARAMS}


def _portfolio(spells: list[dict[str, Any]], use_stop: bool) -> dict[str, Any]:
    return portfolio(spells, use_stop=use_stop, schedule=PRIMARY_SCHEDULE, equity=ACCOUNT_USD, slip_bps=SLIP_BPS)


def _row(spec_id: str, family: str, spells: list[dict[str, Any]], sessions: int, use_stop: bool, **extra: Any) -> dict[str, Any]:
    result = _portfolio(spells, use_stop)
    packed = pack(result["trades"], spells, sessions, result["maxDrawdown"])
    packed.update({"id": spec_id, "family": family, "window_end": VALIDATE_END.isoformat(), **extra})
    return packed


def _fit(train: pd.DataFrame, features: list[str], label: str, params: dict[str, Any], rounds: int) -> list[lgb.Booster]:
    if len(train) < 5000:
        raise RuntimeError(f"training fold has {len(train)} rows")
    labels = train[label].clip(-LABEL_CLIP, LABEL_CLIP).to_numpy(dtype=np.float64)
    matrix = train.loc[:, features].to_numpy(dtype=np.float64)
    dataset = lgb.Dataset(matrix, label=labels, feature_name=list(features), free_raw_data=False)
    models = []
    for seed in SEEDS:
        fitted = dict(params)
        fitted["seed"] = seed
        fitted["bagging_seed"] = seed
        fitted["feature_fraction_seed"] = seed
        models.append(lgb.train(fitted, dataset, num_boost_round=rounds))
    return models


def _predict(models: list[lgb.Booster], frame: pd.DataFrame, features: list[str]) -> np.ndarray:
    matrix = frame.loc[:, features].to_numpy(dtype=np.float64)
    total = np.zeros(len(frame), dtype=np.float64)
    for model in models:
        total += model.predict(matrix)
    return np.clip(total / len(models), -LABEL_CLIP, LABEL_CLIP)


def _walk(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    assert_preholdout_days(list(frame["day"].unique()), spec["name"])
    features = list(spec["features"])
    label = spec["label"]
    usable = frame.dropna(subset=features + [label, "atr"]).copy()
    params = PARAMS[spec["params"]]
    rounds = ROUNDS[spec["params"]]
    parts = []
    for start, end in QUARTERS:
        cut = train_cut(start)
        train = usable.loc[usable["day"] < cut]
        test = usable.loc[(usable["day"] >= start) & (usable["day"] <= end)]
        if test.empty:
            continue
        print(f"  {spec['name']} {start} train {len(train)} test {len(test)}", flush=True)
        models = _fit(train, features, label, params, rounds)
        chunk = test.loc[:, ["symbol", "day", "minute", "atr", "fwd_flat", label]].copy()
        chunk["pred"] = _predict(models, test, features)
        parts.append(chunk)
    if not parts:
        raise RuntimeError(f"{spec['name']} produced no walk-forward rows")
    return pd.concat(parts, ignore_index=True)


def _ml_policies(
    name: str,
    preds: pd.DataFrame,
    book: dict[tuple[str, date], list[dict[str, Any]]],
    spec: dict[str, Any],
    sessions: int,
) -> list[dict[str, Any]]:
    window = preds.loc[(preds["day"] >= VALIDATE_START) & (preds["day"] <= VALIDATE_END)].copy()
    assert_preholdout_days(list(window["day"].unique()) if len(window) else [], name)
    rows = []
    horizon = int(spec["horizon"])
    for exit_mode in spec["exits"]:
        for stop in STOPS:
            prebuilt = ml_spells(
                window,
                book,
                horizon=horizon,
                exit_mode=exit_mode,
                stop_mode=stop,
                min_pred=0.0,
            )
            print(f"  {name} {exit_mode} {stop} candidates {len(prebuilt)}", flush=True)
            for threshold in THRESHOLDS_BPS:
                floor = threshold / 10_000.0
                passed = [spell for spell in prebuilt if float(spell["priority"]) >= floor]
                for book_mode in BOOKS:
                    taken = take_spells(passed, book_mode)
                    for size in SIZES:
                        spec_id = f"ml:{name}:{exit_mode}:{stop}:{book_mode}:{size:g}:{threshold:g}"
                        rows.append(
                            _row(
                                spec_id,
                                "ml",
                                with_size(taken, size),
                                sessions,
                                stop == "1atr",
                                model=name,
                                exit=exit_mode,
                                stop=stop,
                                book=book_mode,
                                size=size,
                                threshold_bps=threshold,
                                horizon=horizon,
                            )
                        )
    return rows


def _gap_policies(book: dict[tuple[str, date], list[dict[str, Any]]], sessions: int) -> list[dict[str, Any]]:
    rows = []
    days = [day for day in spy_days(book, VALIDATE_START, VALIDATE_END)]
    for gap in GAPS:
        for stop in STOPS:
            for exit_mode in GAP_EXITS:
                spells = [
                    spell
                    for spell in gap_spells(book, gap_max=gap, stop_mode=stop, exit_mode=exit_mode)
                    if VALIDATE_START <= spell["day"] <= VALIDATE_END
                ]
                for size in SIZES:
                    spec_id = f"gap:{gap:.3f}:{stop}:{exit_mode}:{size:g}"
                    rows.append(
                        _row(
                            spec_id,
                            "rule",
                            with_size(spells, size),
                            len(days) or sessions,
                            stop == "1atr",
                            kind="gap",
                            gap_max=gap,
                            exit=exit_mode,
                            stop=stop,
                            size=size,
                        )
                    )
    return rows


def _frozen_policies(book: dict[tuple[str, date], list[dict[str, Any]]], sessions: int) -> list[dict[str, Any]]:
    rows = []
    for item in REGISTRY:
        spells = [spell for spell in item.spells(book) if VALIDATE_START <= spell["day"] <= VALIDATE_END]
        print(f"  frozen {item.id} spells {len(spells)}", flush=True)
        rows.append(_row(item.id, "rule", spells, sessions, True, kind="frozen"))
    sessions_map = build_sessions(book)
    days = [day for day in spy_days(book, VALIDATE_START, VALIDATE_END)]
    for rule in DAILY_REGISTRY:
        spells = rule.spells(sessions_map, days)
        early = [spell["day"] for spell in spells if spell["day"] < VALIDATE_START or spell["day"] > VALIDATE_END]
        if early:
            raise RuntimeError(f"{rule.id} left the validation window")
        print(f"  frozen {rule.id} spells {len(spells)}", flush=True)
        rows.append(_row(rule.id, "rule", spells, len(days), True, kind="frozen"))
    return rows


def _compact(row: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "id",
        "family",
        "kind",
        "model",
        "exit",
        "stop",
        "book",
        "size",
        "threshold_bps",
        "horizon",
        "gap_max",
        "trades",
        "net",
        "per_trade",
        "per_day",
        "bps",
        "win_rate",
        "max_drawdown",
        "trades_per_day",
        "fill_day_frac",
    )
    return {key: row.get(key) for key in keep if key in row}


def _holdout_ml(
    book: dict[tuple[str, date], list[dict[str, Any]]],
    frame: pd.DataFrame,
    chosen: dict[str, Any],
    oos: dict[str, pd.DataFrame],
) -> tuple[dict[str, Any], list[lgb.Booster] | None, dict[str, Any] | None]:
    name = chosen["model"]
    specs = {spec["name"]: spec for spec in model_specs()}
    cut = train_cut(HOLDOUT_START)
    holdout_days = [day for day in spy_days(book, HOLDOUT_START, HOLDOUT_END)]
    if name == "stack":
        coef = _stack_coef(oos)
        parts = []
        saved: list[lgb.Booster] = []
        for component in ("h3", "h6", "h12"):
            spec = specs[component]
            train = frame.loc[frame["day"] < cut].dropna(subset=list(spec["features"]) + [spec["label"], "atr"])
            test = frame.loc[frame["day"] >= HOLDOUT_START].dropna(subset=list(spec["features"]) + ["atr"])
            models = _fit(train, list(spec["features"]), spec["label"], PARAMS[spec["params"]], ROUNDS[spec["params"]])
            saved.extend(models)
            piece = test.loc[:, ["symbol", "day", "minute", "atr"]].copy()
            piece[component] = _predict(models, test, list(spec["features"]))
            parts.append(piece)
        merged = parts[0]
        for piece in parts[1:]:
            merged = merged.merge(piece, on=["symbol", "day", "minute", "atr"], how="inner")
        matrix = np.column_stack([np.ones(len(merged)), merged[["h3", "h6", "h12"]].to_numpy(dtype=np.float64)])
        merged["pred"] = np.clip(matrix @ coef, -LABEL_CLIP, LABEL_CLIP)
        spec_info = {"name": "stack", "horizon": 12, "exits": ("flat",)}
        use_spec = spec_info
        models_out = saved
        extra = {"stack_coef": [float(value) for value in coef]}
    else:
        spec = specs[name]
        features = list(spec["features"])
        train = frame.loc[frame["day"] < cut].dropna(subset=features + [spec["label"], "atr"])
        test = frame.loc[frame["day"] >= HOLDOUT_START].dropna(subset=features + ["atr"])
        print(f"holdout model {name} train {len(train)} cut {cut}", flush=True)
        models_out = _fit(train, features, spec["label"], PARAMS[spec["params"]], ROUNDS[spec["params"]])
        test = test.copy()
        test["pred"] = _predict(models_out, test, features)
        merged = test
        use_spec = spec
        extra = None
    early = merged.loc[merged["day"] < HOLDOUT_START, "day"]
    if len(early):
        raise RuntimeError("holdout frame contains a pre-holdout day")
    spells = ml_spells(
        merged,
        book,
        horizon=int(chosen["horizon"]),
        exit_mode=str(chosen["exit"]),
        stop_mode=str(chosen["stop"]),
        min_pred=float(chosen["threshold_bps"]) / 10_000.0,
        allow_holdout=True,
    )
    spells = take_spells(spells, str(chosen["book"]))
    spells = with_size(spells, float(chosen["size"]))
    leaked = [spell["day"] for spell in spells if spell["day"] < HOLDOUT_START or spell["day"] > HOLDOUT_END]
    if leaked:
        raise RuntimeError(f"ml holdout spell on {min(leaked)}")
    result = _portfolio(spells, chosen["stop"] == "1atr")
    packed = pack(result["trades"], spells, len(holdout_days), result["maxDrawdown"])
    packed["id"] = chosen["id"]
    if extra:
        packed.update(extra)
    return packed, models_out, extra


def _stack_coef(oos: dict[str, pd.DataFrame]) -> np.ndarray:
    merged = oos["h3"][["symbol", "day", "minute", "fwd_flat", "pred"]].rename(columns={"pred": "h3"})
    for name in ("h6", "h12"):
        piece = oos[name][["symbol", "day", "minute", "pred"]].rename(columns={"pred": name})
        merged = merged.merge(piece, on=["symbol", "day", "minute"], how="inner")
    cut = train_cut(HOLDOUT_START)
    fit_rows = merged.loc[merged["day"] < cut].dropna(subset=["h3", "h6", "h12", "fwd_flat"])
    assert_preholdout_days(list(fit_rows["day"].unique()), "stack weights")
    matrix = np.column_stack([np.ones(len(fit_rows)), fit_rows[["h3", "h6", "h12"]].to_numpy(dtype=np.float64)])
    target = fit_rows["fwd_flat"].to_numpy(dtype=np.float64)
    coef, *_rest = np.linalg.lstsq(matrix, target, rcond=None)
    return coef


def _holdout_rule(book: dict[tuple[str, date], list[dict[str, Any]]], chosen: dict[str, Any]) -> dict[str, Any]:
    days = [day for day in spy_days(book, HOLDOUT_START, HOLDOUT_END)]
    if chosen.get("kind") == "gap":
        spells = gap_spells(
            book,
            gap_max=float(chosen["gap_max"]),
            stop_mode=str(chosen["stop"]),
            exit_mode=str(chosen["exit"]),
            allow_holdout=True,
        )
        spells = [spell for spell in spells if HOLDOUT_START <= spell["day"] <= HOLDOUT_END]
        spells = with_size(spells, float(chosen["size"]))
        use_stop = chosen["stop"] == "1atr"
    else:
        hypothesis = next((item for item in REGISTRY if item.id == chosen["id"]), None)
        if hypothesis is not None:
            with allow_holdout_days():
                spells = hypothesis.spells(book)
            spells = [spell for spell in spells if HOLDOUT_START <= spell["day"] <= HOLDOUT_END]
            use_stop = True
        else:
            rule = next(item for item in DAILY_REGISTRY if item.id == chosen["id"])
            spells = rule.spells(build_sessions(book), days)
            use_stop = True
    leaked = [spell["day"] for spell in spells if spell["day"] < HOLDOUT_START or spell["day"] > HOLDOUT_END]
    if leaked:
        raise RuntimeError(f"rule holdout spell on {min(leaked)}")
    result = _portfolio(spells, use_stop)
    packed = pack(result["trades"], spells, len(days), result["maxDrawdown"])
    packed["id"] = chosen["id"]
    return packed


def _recommend(finalist_family: str, ml_net: float, rule_net: float) -> str:
    if ml_net <= 0 and rule_net <= 0:
        return "Neither the selected model nor the selected rule made money on the holdout. Do not trade either."
    if rule_net > ml_net:
        winner = "The rule made more money on the holdout than the model."
    elif ml_net > rule_net:
        winner = "The model made more money on the holdout than the rule."
    else:
        winner = "The model and the rule made the same holdout profit."
    picked = "The validation pick was the rule." if finalist_family == "rule" else "The validation pick was the model."
    return f"{winner} {picked} Nothing was deployed."


def _write_marked(path: Path, section: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    start = existing.find(PROFIT_BEGIN)
    stop = existing.find(PROFIT_END)
    if start >= 0 and stop >= start:
        updated = existing[:start] + section + existing[stop + len(PROFIT_END) :]
    else:
        updated = existing.rstrip() + "\n\n" + section + "\n"
    path.write_text(updated, encoding="utf-8")


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "−" if value < 0 else ""
    return f"{sign}${abs(value):.0f}"


def _markdown(summary: dict[str, Any]) -> str:
    ml = summary["holdout_ml"]
    rule = summary["holdout_rule"]
    lines = [
        PROFIT_BEGIN,
        "## Profit search",
        "",
        "Candidates were ranked on validation net dollars after 2 bp slippage. "
        f"The minimum was {MIN_TRADES} trades. One name a day means the first bar that qualifies, not a later peak. "
        "Look 5 used the later peak and is not a tradable result. "
        "The holdout below was read after `research/profit_selection.json` was written. "
        f"Headline is the validation winner's holdout: `{summary['finalist']}`, {_money(summary['headline_net'])}. "
        f"{summary['recommendation']} `models/ACTIVE` stays `v0.1`.",
        "",
        "| Book | Validation net | Holdout net | Holdout trades | Trades/day | Win | Per day | Max DD |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| Model `{summary['best_ml']['id']}` | {_money(summary['best_ml']['net'])} | {_money(ml['net'])} | "
            f"{ml['trades']} | {ml['trades_per_day']:.2f} | {_pct(ml['win_rate'])} | {_money(ml['per_day'])} | {_money(ml['max_drawdown'])} |"
        ),
        (
            f"| Rule `{summary['best_rule']['id']}` | {_money(summary['best_rule']['net'])} | {_money(rule['net'])} | "
            f"{rule['trades']} | {rule['trades_per_day']:.2f} | {_pct(rule['win_rate'])} | {_money(rule['per_day'])} | {_money(rule['max_drawdown'])} |"
        ),
        "",
        PROFIT_END,
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    if SUMMARY_PATH.exists():
        raise SystemExit("profit summary already exists; refusing a second holdout read")
    if ACTIVE_PATH.read_text(encoding="utf-8").strip() != "v0.1":
        raise SystemExit("refusing to run while ACTIVE is not v0.1")
    if PRIMARY_SCHEDULE != "zero":
        raise SystemExit("refusing to run while the cost config is not zero commission")
    looks_before = _look_count()
    rule_before = RULE_PATH.read_bytes()
    print("loading bars", flush=True)
    book = load_ml_book()
    book_pre = {key: value for key, value in book.items() if key[1] < HOLDOUT_START}
    print("building features", flush=True)
    frame = add_return_lags(build_frame(book_pre))
    assert_preholdout_days(list(frame["day"].unique()), "feature frame")
    sessions = len([day for day in spy_days(book_pre, VALIDATE_START, VALIDATE_END)])
    print("scoring frozen rules", flush=True)
    rows = _frozen_policies(book_pre, sessions)
    h5 = next(row for row in rows if row["id"] == "h5_gap_down")
    if abs(float(h5["net"]) - H5_VALIDATION_NET) > 5:
        raise SystemExit(f"down-gap rescore {h5['net']:.2f} does not match the published validation net")
    print("scoring gap grid", flush=True)
    rows.extend(_gap_policies(book_pre, sessions))
    gap_frozen = next(row for row in rows if row["id"] == "gap:-0.004:1atr:flat:1")
    if abs(float(gap_frozen["net"]) - float(h5["net"])) > 1:
        raise SystemExit("gap grid does not reproduce the frozen down-gap validation net")
    oos: dict[str, pd.DataFrame] = {}
    print("walk-forward models", flush=True)
    for spec in model_specs():
        oos[spec["name"]] = _walk(frame, spec)
        rows.extend(_ml_policies(spec["name"], oos[spec["name"]], book_pre, spec, sessions))
    print("stacking horizon predictions", flush=True)
    merged = oos["h3"][["symbol", "day", "minute", "atr", "fwd_flat", "pred"]].rename(columns={"pred": "pred_h3"})
    for name in ("h6", "h12"):
        piece = oos[name][["symbol", "day", "minute", "pred"]].rename(columns={"pred": f"pred_{name}"})
        merged = merged.merge(piece, on=["symbol", "day", "minute"], how="inner")
    validation_days = sorted({day for day in merged["day"] if VALIDATE_START <= day <= VALIDATE_END})
    merged = merged.copy()
    merged["pred"] = stack_oos(merged, ["pred_h3", "pred_h6", "pred_h12"], "fwd_flat", validation_days)
    stack_spec = {"name": "stack", "horizon": 12, "exits": ("flat",)}
    rows.extend(_ml_policies("stack", merged.dropna(subset=["pred"]), book_pre, stack_spec, sessions))
    for row in rows:
        row["window_end"] = VALIDATE_END.isoformat()
    winner = choose_winner(rows)
    ml_choice = best_of(rows, "ml")
    rule_choice = best_of(rows, "rule")
    payload = {
        "holdout_used": False,
        "chosen_on": "validation net dollars, 2024-07-01..2026-03-31, minimum 50 trades",
        "finalist": winner["id"],
        "finalist_family": winner["family"],
        "best_ml": _compact(ml_choice),
        "best_rule": _compact(rule_choice),
        "h5_validation_net": h5["net"],
        "candidates": len(rows),
    }
    SELECTION_PATH.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    GRID_PATH.write_text(pd.DataFrame([_compact(row) for row in rows]).sort_values("net", ascending=False).to_csv(index=False), encoding="utf-8")
    frozen = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    if frozen["holdout_used"] or frozen["finalist"] != winner["id"]:
        raise SystemExit("selection file does not match the validation winner")
    print(f"winner {winner['id']} validation {winner['net']:.0f}; holdout starts now", flush=True)
    print("building holdout features", flush=True)
    full = add_return_lags(build_frame(book))
    holdout_ml, models, extra = _holdout_ml(book, full, frozen["best_ml"], oos)
    archived = json.loads(LOOKAHEAD_SUMMARY.read_text(encoding="utf-8")) if LOOKAHEAD_SUMMARY.exists() else None
    reuse_rule = (
        archived is not None
        and archived.get("best_rule", {}).get("id") == frozen["best_rule"]["id"]
        and _look_for("profit_rule") is not None
    )
    if reuse_rule:
        holdout_rule = archived["holdout_rule"]
        rule_look = _look_for("profit_rule")
        new_looks = 1
    else:
        holdout_rule = _holdout_rule(book, frozen["best_rule"])
        rule_look = record_look("profit_rule", f"Validation winner among rules: {frozen['best_rule']['id']}. Not used to choose it.")
        new_looks = 2
    ml_look = record_look(ML_LOOK_ID, f"Validation winner among models after the same-day top1 leak was removed: {frozen['best_ml']['id']}.")
    if _look_count() != looks_before + new_looks:
        raise SystemExit("holdout looks were not the expected new rows")
    if models:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        for index, model in enumerate(models):
            model.save_model(str(MODEL_DIR / f"booster_{index}.txt"))
        (MODEL_DIR / "config.json").write_text(
            json.dumps(
                {
                    "id": frozen["best_ml"]["id"],
                    "schedule": PRIMARY_SCHEDULE,
                    "slip_bps": SLIP_BPS,
                    "train_last_day": train_cut(HOLDOUT_START).isoformat(),
                    "holdout_used_to_train": False,
                    "stack_coef": None if extra is None else extra.get("stack_coef"),
                    "features": list(SEQ_COLUMNS) if frozen["best_ml"].get("model") == "h12_seq" else "see profit_selection.json",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    headline = holdout_rule if frozen["finalist_family"] == "rule" else holdout_ml
    summary = {
        "finalist": frozen["finalist"],
        "finalist_family": frozen["finalist_family"],
        "headline_net": headline["net"],
        "best_ml": frozen["best_ml"],
        "best_rule": frozen["best_rule"],
        "holdout_ml": holdout_ml,
        "holdout_rule": holdout_rule,
        "holdout_ml_look": ml_look,
        "holdout_rule_look": rule_look,
        "candidates": frozen["candidates"],
        "recommendation": _recommend(frozen["finalist_family"], float(holdout_ml["net"]), float(holdout_rule["net"])),
        "active": "v0.1",
    }
    if ACTIVE_PATH.read_text(encoding="utf-8").strip() != "v0.1":
        raise SystemExit("ACTIVE changed during the run")
    if RULE_PATH.read_bytes() != rule_before:
        raise SystemExit("live signal rule was modified")
    if champion_record().get("replaced"):
        raise SystemExit("champion record was replaced")
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    _write_marked(LOG_PATH, _markdown(summary))
    print(
        f"headline {summary['finalist']} {_money(summary['headline_net'])} "
        f"ml {_money(holdout_ml['net'])} rule {_money(holdout_rule['net'])}",
        flush=True,
    )
    print(summary["recommendation"], flush=True)


if __name__ == "__main__":
    main()
