# Handoff

Branch: `cursor/right-time-to-buy-79f9`
PR: https://github.com/jaykrishan1989/VolumePulse/pull/1 (base `main`, draft)
Last research result on this branch: slippage is the only execution cost. IBKR is the data source. The owner does not trade through IBKR.
Working tree at the start of this handoff was clean and matched `origin/cursor/right-time-to-buy-79f9`.
Live pointer: `models/ACTIVE` is `v0.1`. Git tag `v0.1` is commit `1b720b2`. Do not move the tag.
The app never places orders.

## What's done

Right Time to Buy is a read-only IBKR dashboard. The live rule buys when a name appears on the list between 10:00 and 11:00 ET and sells when it leaves. Confirm 1, exit lag 1, hard stop on, flat by 15:55. Account US$2,120 (CA$3,000 at 1.4165). Jay trades through IBKR. The live cost model in `app/cost_model.json` is tiered commission (US$0.35 minimum per side, plus sell-side regulatory fees) and 2 bp slippage per side. The app does not place orders.

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

Tests last run: `python -m unittest discover -s tests -q` — 151 tests, OK. The model does not change the dashboard, so no new browser pass was required.

## What's in progress

The intraday model `ml_lgb_60m` is scored and rejected. Pooled −$319 on 270 trades. Holdout look 4: +$77 on 29 trades, bootstrap p 0.197. Gate 1/12. No checkpoint. Do not run `python -m backtest.run_ml` again.

The profit search is also scored. `python -m backtest.run_profit` ranked 427 candidates on validation dollars. The winner predicts the return to the 15:50 close and buys the first name of the day whose forecast is at least 20 bp, full ticket, one ATR stop. Holdout look 7: 19 trades, +$297, +$15.65/trade, +$2.42/day, 68.4% winners, max DD $73. The best validation rule is a 1.5% down gap held to the close. Holdout look 6: 52 trades, +$210, +$4.03/trade, +$1.70/day, 36.5% winners, max DD $223. The model made more holdout profit. Nothing was deployed.

Look 5 (`profit_ml`, a stack that waited for the best later bar of the day) is not tradable. Its +$1,398 is archived in `research/profit_lookahead_summary.json`. Do not cite it as a result.

Do not run `python -m backtest.run_profit` again. The summary file exists and the command refuses a second holdout read. Do not point ACTIVE at `models/ml/profit_ml/`. Do not retune the frozen rules.

The live cost is schedule `zero` in `app/cost_model.json` and `backtest/costs.py`: US$0 commission, no regulatory fee, 2 bp slippage on the next bar's open. `python -m backtest.run_costs` writes `research/cost_rerank.csv`, `research/cost_summary.json`, and `research/cost_selection.json`. The selection file is written from validation nets before either holdout restatement is loaded. That rerun did not append a look. There is no IBKR commission column. The look count is now 7, and look 5 is invalid.

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

Closed, and not authorized as a silent next search:

- Heston same-clock continuation was scored as `n_clock` and lost $132 on validation. The noon reversal, `n_mid_reversal`, lost $488. Do not retune either.
- Order-flow imbalance. `n_flow` is a close-versus-WAP proxy and was not adopted. These files are OHLC. There are no aggressor prints.
- Shorts. Canadian cash account, long-only.
- Any retune of the frozen thresholds in `backtest/areas.py`, `backtest/hypotheses.py`, or `backtest/daily.py`.
- Another holdout read. Looks 1 through 7 are on file, and look 5 is invalid. `fresh_slice` and `milestone` still raise.

## Exact next steps

The daily-frequency rule family is closed. Do not deploy `d_rs_leader` or `h5_gap_down`. Do not move a rule threshold after seeing +$350 or +$302. Do not add an IBKR commission column.

The intraday model and the profit search are both closed. Stay on v0.1. Do not deploy `models/ml/`. Look count is 7. Look 5 is invalid. Do not open look 8. Bonferroni denominator for the old gate is 54. Do not rewrite `research/gate_results.csv` or `research/areas.csv`.

The current 5-minute book is too thin for that profit result (19 holdout trades, one name a day). More bars are requested in `DATA_REQUEST.md`. The owner runs `scripts/fetch_history.py` on the PC that hosts Gateway. This VM must not open the socket.

`backtest/next_batch.py` freezes seven books. They were scored on 2026-10-13 from the restored `data/raw5` files (ten symbols, gitignored). Best validation net is `n_residual` at +$1,007 on 415 trades, short of the published $1,261. `n_clock` (−$132) and `n_late_reversal` (−$303) are rejected. The other four are positive and not adopted: each book's profit sits in its five largest trades, and removing those five leaves a loss. `python -m backtest.run_next_batch` does not open the holdout.

`backtest/next_batch2.py` freezes three ordinary-session books. Scored the same day: `n_intraday_cont` −$312 on 722 fills, `n_mid_reversal` −$488 on 388, `n_close_reversal` −$154 on 386. All rejected. The continuation book did trade more often than the 85-trade model, and it still lost. Do not retune the two-name weight or add a magnitude gate after seeing those losses.

`backtest/revert_ml.py` is the trough LightGBM. Scored 2026-10-14 on validation only. Probability 0.55 is the only threshold inside the fill-rate band: 767 fills, 1.75 a day, win 51.1%, −$146. Average win $1.01, average loss $1.44. Without the five best days, −$177. Higher probabilities barely trade and also lose. Do not retune the ATR multiple or the 0.40 session-position gate after seeing that. A sequence model was not fit.

`backtest/grid15.py` is the 15-minute grid. The source note is `research/RESEARCH_PRO_TRADERS.md`. Scored 2026-10-14 on validation only, after the rules were committed. `pro_aplus`: 58 fills, 29 entries, 0.13 fills a day, win 27.6%, −$36, and −$53 without the five best days. 405 of 433 sessions had no fill. The bare opening-range break lost $167 on 1,189 fills. Every leave-one-out book lost. The afternoon VWAP book lost $9. The short failed-break lost $31, and $84 without its five best days. Session VWAP never blocked a range break. Do not lower the 1.2 opening-volume multiple, widen the morning window, or promote the least-bad ablation. `python -m backtest.run_grid15` does not open the holdout.

`backtest/grid15_next.py` freezes five exits of that same opening-range entry, and a separate top-4 rank of slot z-scores. Scored the same day on tiered IBKR commission plus 2 bp. Every exit lost: 30 minutes −$676 on 814 fills, hold to the flat −$815 on 793, trail −$776 on 798. The price path after slippage was negative at each horizon, from −$99 to −$253, and commission was about $560 more. The rank traded 431 of 433 sessions. Momentum −$1,098 on 1,266 fills (2.92 a day). Reversion −$926 on 1,304 fills (3.01 a day), and −$1 after slippage before commission. The both-indexes-under-SMA20 gate did not improve the per-trade result. No book cleared the screen. Do not adopt the smallest loss, and do not lower the 20 bp cost floor or change K from 4. `python -m backtest.run_grid15_next` does not open the holdout. The twelve names are not the binding constraint for this loss.

`app/cost_model.json` is tiered IBKR commission plus 2 bp. Jay trades through IBKR. The cost-clearing books were scored 2026-10-15, after the rules were written down. `c_ticket`, one full ticket on the most negative slot: 433 fills, 1.00 a day, win 52.4%, −$383, −4.9 bp, −$449 without the five best days. `c_two` −$587, −9.2 bp. `c_vol` −$812, −18.5 bp. `c_move` −$724, −22.1 bp, win 38.3%. `c_edge` and `c_primary` did not trade. The best slot's own historical fade at the end of the sample was 4.6 bp. Do not adopt `c_ticket`, and do not lower the 1.5 sigma bar, the 40 bp volatility floor, or the 20 bp historical hurdle. `python -m backtest.run_grid15_cost` does not open the holdout.

Look count stays 7. Do not open look 8 unless a new frozen id first beats $1,261 on validation, stays positive with its five best days removed, and then passes `research/GATE.md` before any holdout read. `models/ACTIVE` stays `v0.1`. The twelve names and six sector ETFs in `DATA_REQUEST.md` are still absent.

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
