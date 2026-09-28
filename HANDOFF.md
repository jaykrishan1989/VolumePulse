# Handoff

Branch: `cursor/right-time-to-buy-79f9`
PR: https://github.com/jaykrishan1989/VolumePulse/pull/1 (base `main`, draft)
Last research result on this branch: slippage is the only execution cost. IBKR is the data source. The owner does not trade through IBKR.
Working tree at the start of this handoff was clean and matched `origin/cursor/right-time-to-buy-79f9`.
Live pointer: `models/ACTIVE` is `v0.1`. Git tag `v0.1` is commit `1b720b2`. Do not move the tag.
The app never places orders.

## What's done

Right Time to Buy is a read-only IBKR dashboard. IBKR is the market-data API, not the broker. The live rule buys when a name appears on the list between 10:00 and 11:00 ET and sells when it leaves. Confirm 1, exit lag 1, hard stop on, flat by 15:55. Account US$2,120 (CA$3,000 at 1.4165). The live cost model in `app/cost_model.json` is no commission and 2 bp slippage per side.

That rule is baseline **v0.1**, not v1.0. It failed the costs-and-random bar. Holdout, read once as look 2: 191 trades, win 37.2%, −$268 (−12.7%), −8.43 bp. Bootstrap p of a non-positive total 0.9995. Versus random entries p = 0.225. `worthTrading` is false.

Earlier, also done and pushed:

- Bracket backtest had no cost-inclusive edge. Holdout look 1. Live numeric entry gates were not changed.
- Delayed-tape banner and grey hidden cards. Demo runs without `RTTB_FORCE_DELAY`.
- Six pre-registered hypotheses, all rejected after costs. Holdout not opened.
- Promotion gate in `research/GATE.md` and `backtest/gate.py`. All six hypotheses rejected against the champion. The six-hypothesis table in `research/gate_results.csv` used Bonferroni denominator 33. Do not rewrite those p-values.
- Checkpoint, changelog, CLI (`python -m models.cli list|show|restore|check`), and rollback monitor. No passing checkpoint exists, so a trip holds v0.1.

The four research areas requested in the latest amendment are done. Fifteen frozen overlays in `backtest/areas.py` were scored by `python -m backtest.run_areas` on 2023-01-01 through 2026-03-31. All rejected. No half-year was a profit. Look count remains 2 (`research/holdout_looks.csv`). Champion on the gate window: 1,234 trades, −$1,475, −$1.20/trade, −16.8 bp. Bonferroni denominator is now 48 (15 bracket specs + 12 appear/disappear trials + 6 hypotheses + 15 area ids). Alpha is 0.05/48 ≈ 0.001042.

| Overlay | Trades | Net | Per trade | Windows |
| --- | ---: | ---: | ---: | ---: |
| sz_risk_1pct | 1,243 | −$1,477 | −$1.19, −16.5 bp | 4/12 |
| sz_risk_half_pct | 1,342 | −$1,480 | −$1.10, −18.1 bp | 0/12 |
| sz_one_position | 1,115 | −$1,420 | −$1.27, −11.5 bp | 0/12 |
| sz_daily_stop | 1,057 | −$1,339 | −$1.27, −16.9 bp | 3/12 |
| sz_kelly_cap | 0 | $0 | n/a | 0/12 |
| tod_open (9:45–10:30) | 517 | −$657 | −$1.27, −13.2 bp | 4/12 |
| tod_midday (11:00–13:00) | 1,876 | −$1,999 | −$1.07, −27.6 bp | 0/12 |
| tod_afternoon (13:00–14:30) | 1,719 | −$1,859 | −$1.08, −21.7 bp | 0/12 |
| tod_last_hour (14:30–15:30) | 1,095 | −$1,280 | −$1.17, −15.7 bp | 6/12 |
| liq_half_spread | 1,056 | −$1,901 | −$1.80, −32.3 bp | 0/12 |
| liq_participation | 1,207 | −$1,518 | −$1.26, −17.7 bp | 0/12 |
| liq_dvol | 1,234 | −$1,475 | −$1.20, −16.8 bp | 0/12 |
| reg_spy_vwap | 751 | −$931 | −$1.24, −14.2 bp | 4/12 |
| reg_high_range | 923 | −$1,219 | −$1.32, −16.4 bp | 1/12 |
| reg_falling_tape | 1,025 | −$1,257 | −$1.23, −14.0 bp | 4/12 |

Findings worth keeping:

- The 1% risk cap bound on 95 fills the full ticket also took. A tighter stop asks for more shares than cash allows, so the cash cap wins. The 0.5% cap cut 486 fills and the extra names made basis points worse (−18.1 bp), because the US$0.35 minimum is a larger fraction of a thinner ticket.
- One open position, the open clock, and the three regime filters lost fewer dollars. Several of those paired p-values cleared 0.00104. Dollars per trade did not improve. An empty or smaller book is not a promotion.
- Kelly (`sz_kelly_cap`) stood aside on all 1,799 spells. Do not adopt "trade nothing."
- Last hour was the only clock ahead on all three pooled measures, by about three cents a trade and 1.1 bp, 6/12 windows. Every half-year still lost. Dropping the top 5 days removed the per-trade dollar edge. Paired p ≈ 0.12. Do not move the live window.
- Midday lost about $1,999. By 2025H2 equity was about $121, under one share, so later midday folds have no fills.
- Corwin–Schultz half-spread (OHLC stand-in, not a quote) averaged 4.5 bp extra. That book lost −32.3 bp. Square-root impact averaged 0.27 bp. The minimum commission, about 3.5 bp round trip, is the binding friction. The US$5,000,000 dollar-volume floor kept all 1,799 spells and matched the champion.

Write-ups: `research/RESEARCH_LOG.md` (marked `<!-- AREAS_BEGIN -->`), `research/areas.csv`, `research/area_folds.csv`, `research/area_summary.json`, `RESULTS.md`, `README.md`, `models/CHANGELOG.md` (marked `<!-- AREAS_CHANGELOG_BEGIN -->`). `backtest/run_hypotheses.py` preserves both the gate section and the areas section via `preserve_gate_section`.

Tests last run: `python -m unittest discover -s tests -q` — 103 tests, OK. The model does not change the dashboard, so no new browser pass was required.

## What's in progress

The intraday model is scored and rejected. `ml_lgb_60m` is a three-seed LightGBM of the 60-minute forward return. The validation threshold is 20 bp (`research/ml_selection.json`, written before the holdout fit). Pooled 2023-01-01..2026-03-31: 270 trades, 11.9% of days, win 46.7%, −$319, −$1.18/trade, −$0.39/day, −6.6 bp, max DD $456. Holdout look 4: 29 trades, 8 days, win 48.3%, +$77, +$2.66/trade, +12.6 bp, max DD $86. Day-bootstrap p 0.197. Random-entry p 0.03. Gate 1/12, paired p 0.107 and 0.107 versus alpha 0.00093. No checkpoint. `models/ACTIVE` is `v0.1`. The boosters are `models/ml/ml_lgb_60m/seed_{7,11,21}.txt`.

Do not run `python -m backtest.run_ml` again. Look 4 is already the one authorized read. Do not move the 20 bp threshold. Do not add a sequence model after this loss. Do not point ACTIVE at the model files. Do not retune the frozen rules.

The live cost is schedule `zero` in `app/cost_model.json` and `backtest/costs.py`: US$0 commission, no regulatory fee, 2 bp slippage on the next bar's open. `python -m backtest.run_costs` writes `research/cost_rerank.csv`, `research/cost_summary.json`, and `research/cost_selection.json`. The selection file is written from validation nets before either holdout restatement is loaded. Look count is 4. Do not append look 5. There is no IBKR commission column.

Pooled 2023-01-01 through 2026-03-31. Positive means net above zero.

| Rule | Net | Validation | Gate |
| --- | ---: | ---: | --- |
| appear_disappear_midmorning | −$786, −4.2 bp | −$452 | reference |
| h5_gap_down | +$350, +6.2 bp | +$194 | rejected, 8/12 |
| d_rs_leader | +$302, +2.1 bp | −$98 | rejected, 8/12 |
| h2_opening_reversal | −$134, +0.2 bp | −$23 | rejected, 9/12 |
| h4_opening_range | −$187, −2.2 bp | −$710 | rejected, 5/12 |
| d_pullback | −$307 | −$166 | rejected, 8/12 |
| d_orb | −$336 | −$760 | rejected, 6/12 |
| h1_spy | −$302 | −$172 | rejected, 4/12 |
| d_vwap_reclaim | −$556 | −$744 | rejected, 5/12 |
| h1_stocks | −$553 | −$208 | rejected, 6/12 |
| d_vwap_stretch | −$656 | −$478 | rejected, 5/12 |
| h3_vwap_shortfall | −$883 | −$481 | rejected, 6/12 |

`h5_gap_down` and `d_rs_leader` are positive on the pooled window. On the validation window, only `h5_gap_down` is positive. The daily rank, highest validation net first, is `d_rs_leader` −$98, `d_pullback` −$166, `d_vwap_stretch` −$478, `d_vwap_reclaim` −$744, `d_orb` −$760. The finalist is still `d_rs_leader` because every daily validation net is a loss and it clears the 95% coverage bar.

`h5_gap_down` fails the gate: 8 of 12 windows, severe losses on down days and low-vol days, and −$485 after its best five days are removed. Paired p-values 0.063 and 0.066 versus 0.00094. Drawdown $1,012. Its holdout was not opened.

`d_rs_leader` fails the same gate: validation −$98, 8 of 12 windows, down days $2,059 worse than the champion, paired p-values 0.090 and 0.101. Look 3 restated, not used to rank: +$170, +6.9 bp. Look 2 restated: −$141, −3.2 bp, 190 trades.

The tiered daily table below is the earlier IBKR-assumption measurement. It is not the execution cost.

The live midmorning book filled on 563 of 813 SPY sessions (69.2%) from 2023-01-01 through 2026-03-31. Five frozen rules in `backtest/daily.py` were built to signal more often. Finalist rule, chosen on validation coverage (≥95%) and then validation net, before the holdout load: `d_rs_leader`. Look 3 is that one read. `models/ACTIVE` is still `v0.1`. `app/signal_rule.json` was not edited.

| Rule | Signal days | Trades/day | Win | Net | $/trade | $/day | Max DD | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| d_rs_leader | 100% | 1.00 | 25.6% | −$318 | −$0.39 | −$0.39 | $812 | rejected, 8/12 |
| d_vwap_stretch | 100% | 1.00 | 46.0% | −$1,143 | −$1.41 | −$1.41 | $1,160 | rejected, 4/12 |
| d_orb | 94.2% | 0.94 | 43.5% | −$773 | −$1.01 | −$0.95 | $1,386 | rejected, 6/12 |
| d_pullback | 99.9% | 1.00 | 21.7% | −$853 | −$1.05 | −$1.05 | $932 | rejected, 8/12 |
| d_vwap_reclaim | 99.8% | 1.00 | 22.8% | −$992 | −$1.22 | −$1.22 | $1,576 | rejected, 5/12 |

`d_rs_leader` validation net −$367. Holdout look 3: 123 trades, every session, win 26.8%, +$90, +3.2 bp, max DD $243. Fixed US$1 minimum on that same slice: −$134. Pooled tiered result −$318, −1.8 bp. Down days were $1,680 worse than the champion. Paired p 0.047 and 0.056 versus alpha 0.00094. No cost-inclusive edge. Do not trade it and do not retune it off the holdout print.

Look 3 is the daily finalist. Look 4 is `ml_lgb_60m` and is already written. Do not append look 5. `record_look` will reuse look 3 if `run_daily` is repeated for `d_rs_leader`.

Not started, and not authorized as a silent next search:

- Heston same-clock continuation across days. Needs a wider cross-section than these eight names.
- Order-flow imbalance. These files are OHLC. There are no aggressor prints.
- Shorts. Canadian cash account, long-only.
- Any retune of the frozen thresholds in `backtest/areas.py`, `backtest/hypotheses.py`, or `backtest/daily.py`.
- Another holdout read. Looks 1 through 4 are already on file. `fresh_slice` and `milestone` still raise.

## Exact next steps

The daily-frequency rule family is closed. Do not deploy `d_rs_leader` or `h5_gap_down`. Do not move a rule threshold after seeing +$350 or +$302. Do not add an IBKR commission column.

The intraday model is also closed. `ml_lgb_60m` failed the promotion gate (1/12) and failed `passes_costs_and_random` (holdout bootstrap p 0.197). Stay on v0.1. Do not deploy the files in `models/ml/`. Do not open look 5. Bonferroni denominator is 54. Do not rewrite `research/gate_results.csv` or `research/areas.csv`.

Nothing further is authorized until the owner asks. No new data and no Gateway socket.

## Commands to resume

```powershell
git fetch origin cursor/right-time-to-buy-79f9
git checkout cursor/right-time-to-buy-79f9
git pull origin cursor/right-time-to-buy-79f9
git status
python -m unittest discover -s tests -q
python -m models.cli show v0.1
```

Re-score the fifteen overlays, still without the holdout:

```powershell
python -m backtest.run_areas
```

Score the five daily-frequency rules. This command reads the holdout once if a validation finalist clears 95 percent coverage:

```powershell
python -m backtest.run_daily
```

Re-score the frozen rules on the live cost model (no commission, 2 bp slippage). This does not append a holdout look:

```powershell
python -m backtest.run_costs
```

That rewrites the areas section of `research/RESEARCH_LOG.md`, `research/areas.csv`, `research/area_folds.csv`, `research/area_summary.json`, and the marked block in `models/CHANGELOG.md`. It refuses to run if `models/ACTIVE` is not `v0.1`, and it refuses if the live rule file changes. Parquets live in `data/raw5/<SYMBOL>/` (gitignored). Membership cache is `backtest_cache/membership.pkl` (gitignored).

Do not run `python -m backtest.run_roundtrip holdout` again. That slice has already been read.
