# Model changelog

Versions live in this file, in `models/checkpoints/`, and in the git tag of the same name. `models/ACTIVE` is the one pointer the live app reads. Restoring a version points that file at a checkpoint. It does not place an order.

## How numbers are issued

`v0.x` is a baseline. It is restorable, and it did not beat costs and a random entry on the locked slice. The bar is in `models/registry.py` (`passes_costs_and_random`): holdout net after costs above zero, a day-bootstrap share of non-positive totals under 5 percent, and a random-entry p-value under 5 percent. Failing any one of those keeps the version at v0.

`v1.0`, then `v1.1`, `v1.2`, and so on, are issued only by `create_passing_checkpoint` after that bar passes. None has been issued. The promotion gate in `research/GATE.md` is an additional bar a challenger must clear before it can replace a champion; it does not by itself mint a v1 number. A v1 also has to make money after costs and beat random entries on a fresh slice.

The rollback rule is in `models/ROLLBACK.md`. Thirty paper trades, 10 bp worse than the checkpoint expectancy, and a binomial p-value under 5 percent. With no passing checkpoint on file, a trip holds ACTIVE where it is and logs the hold below.

## v0.1 — 2026-09-28 — baseline, not a pass

**What changed.** The live list buys when a name appears between 10:00 and 11:00 ET and sells when it leaves. Confirm is one 5-minute bar. Exit lag is one bar. Fill is the next bar's open. Hard stop on, scale 1. Flat by 15:55. No score, RVOL, or reward/risk extra gate.

**Why.** Twelve validation trials of the appear-to-disappear round trip all lost money after tiered commissions and 2 bp of slippage on US$2,120. This clock was the least-negative eligible portfolio on the validation window, so it became the frozen live rule. The holdout was not used to pick it.

**Result.** It does not pass the costs-and-random bar, so it is not v1.0.

| Slice | Trades | Win | Net | Expectancy | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: |
| Validation, 2024-07-01 to 2026-03-31 | 628 | 30.9% | −$864 (−40.8%) | −10.8 bp | $882 |
| Holdout, from 2026-04-01, one read | 191 | 37.2% | −$268 (−12.7%) | −8.4 bp, −$1.41 | $321 |
| Gate comparison, 2023-01-01 to 2026-03-31 | 1,234 |  | −$1,475 | −16.8 bp, −$1.20 |  |

Holdout day-bootstrap p of a non-positive total: 0.9995. Versus random entries of the same length: p = 0.225. About 1.6 trades per session on the holdout. Tag: `v0.1`. Plain note: `models/checkpoints/v0.1/NOTE.md`.

## Rejected, and not given a live version

These were measured and left off ACTIVE. The write-ups are `RESULTS.md` and `research/RESEARCH_LOG.md`.

- **60-minute bracket** (the score held to a stop, a target, or 60 minutes). Validation −9.4 bp. Holdout look 1 was −5.9 bp. Not a baseline the app can still run; the live engine is appear/disappear.
- **The other 11 appear/disappear trials** (lag, score, VWAP, reward/risk, a wider stop). All lost on validation. The midmorning cell above was the least bad and is v0.1.
- **Six research hypotheses** (SPY last half-hour, the same clock on the eight names, opening reversal, VWAP shortfall, opening-range break, down-gap hold). Walk-forward 2023 through March 2026, all rejected after costs. The promotion gate then rejected all six against v0.1. The down-gap rule was the only one ahead on pooled net and expectancy (−$183, −13.0 bp versus the champion's −$1,475, −16.8 bp) and it still won 7 of 12 windows, with severe losses on down days and low-vol days. Holdout was not opened. Look count remains 2.

<!-- AREAS_CHANGELOG_BEGIN -->
## Research areas — 2026-09-28 — no checkpoint

Fifteen pre-registered overlays were scored on the promotion gate: position size and risk, time of day, liquidity, and market regime. Every one was rejected. `models/ACTIVE` stays `v0.1`. No v1 checkpoint was written and the `v0.1` tag was not moved. The write-up is the research-areas section of `research/RESEARCH_LOG.md`.

| Id | Trades | Net | Windows | Decision |
| --- | ---: | ---: | ---: | --- |
| sz_risk_1pct | 1243 | $-1477 | 4/12 | rejected |
| sz_risk_half_pct | 1342 | $-1480 | 0/12 | rejected |
| sz_one_position | 1115 | $-1420 | 0/12 | rejected |
| sz_daily_stop | 1057 | $-1339 | 3/12 | rejected |
| sz_kelly_cap | 0 | $0 | 0/12 | rejected |
| tod_open | 517 | $-657 | 4/12 | rejected |
| tod_midday | 1876 | $-1999 | 0/12 | rejected |
| tod_afternoon | 1719 | $-1859 | 0/12 | rejected |
| tod_last_hour | 1095 | $-1280 | 6/12 | rejected |
| liq_half_spread | 1056 | $-1901 | 0/12 | rejected |
| liq_participation | 1207 | $-1518 | 0/12 | rejected |
| liq_dvol | 1234 | $-1475 | 0/12 | rejected |
| reg_spy_vwap | 751 | $-931 | 4/12 | rejected |
| reg_high_range | 923 | $-1219 | 1/12 | rejected |
| reg_falling_tape | 1025 | $-1257 | 4/12 | rejected |
<!-- AREAS_CHANGELOG_END -->

<!-- DAILY_CHANGELOG_BEGIN -->
## Daily frequency — 2026-09-28 — no checkpoint

Five pre-registered daily-frequency rules were scored. None replaced v0.1. The live list was not edited and no order was placed. The validation finalist was `d_rs_leader`.

| Id | Signal days | Trades | Net | $/trade | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| d_rs_leader | 100.0% | 813 | −$318 | −$0.39 | rejected |
| d_vwap_stretch | 100.0% | 813 | −$1143 | −$1.41 | rejected |
| d_orb | 94.2% | 766 | −$773 | −$1.01 | rejected |
| d_pullback | 99.9% | 812 | −$853 | −$1.05 | rejected |
| d_vwap_reclaim | 99.8% | 811 | −$991 | −$1.22 | rejected |

Holdout of `d_rs_leader`, one read: 123 trades, 26.8% wins, $90 net, $0.73/trade, $0.73/session, 3.2 bp, max DD $243. Signal days 100.0%. Not deployed.
<!-- DAILY_CHANGELOG_END -->

<!-- COSTS_CHANGELOG_BEGIN -->
## Slippage-only cost — 2026-09-28 — no checkpoint

IBKR is data only. The same frozen rules were re-scored with no commission and 2 bp slippage per side. No IBKR commission column. The daily finalist on validation was `d_rs_leader`. None replaced v0.1. The live list was not edited and no order was placed.

| Id | Net |
| --- | ---: |
| appear_disappear_midmorning | −$786 |
| h1_spy | −$302 |
| h1_stocks | −$553 |
| h2_opening_reversal | −$134 |
| h3_vwap_shortfall | −$883 |
| h4_opening_range | −$187 |
| h5_gap_down | $350 |
| d_rs_leader | $302 |
| d_vwap_stretch | −$656 |
| d_orb | −$336 |
| d_pullback | −$307 |
| d_vwap_reclaim | −$556 |
<!-- COSTS_CHANGELOG_END -->

<!-- ML_CHANGELOG_BEGIN -->
## Intraday model — 2026-09-28 — no checkpoint

`ml_lgb_60m` is a three-seed LightGBM of the 60-minute forward return. Threshold 20 bp, chosen on validation before holdout look 4. Pooled −$319 on 270 trades (−6.6 bp). Holdout +$77 on 29 trades, bootstrap p 0.197. Gate rejected, 1/12. ACTIVE stays v0.1. No order was placed.
<!-- ML_CHANGELOG_END -->

<!-- PROFIT_CHANGELOG_BEGIN -->
## Profit search — 2026-09-28 — no checkpoint

Validation dollars picked `ml:flat:flat:1atr:top1:1:20`. Holdout look 7: +$297 on 19 trades. The best rule, a 1.5% down gap, made +$210 on look 6. The model made more. Look 5 is an invalid same-day peek. ACTIVE stays v0.1. No order was placed.
<!-- PROFIT_CHANGELOG_END -->

<!-- NEXT_CHANGELOG_BEGIN -->
## Next batch — 2026-10-13 — no checkpoint

Seven books, frozen before the fill, scored on validation only (2024-07-01 through 2026-03-31). Costs: no commission, 2 bp per side, one US$2,120 name, flat by 15:55. The holdout was not loaded. Look count stays 7.

| Id | Trades | Win | Net | bp | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| n_clock | 410 | 15.9% | −$132 | −1.5 | rejected |
| n_orb_fail | 407 | 31.4% | +$186 | +3.1 | not adopted |
| n_prior_reversal | 373 | 13.1% | +$936 | +11.3 | not adopted |
| n_flow | 410 | 26.1% | +$288 | +4.0 | not adopted |
| n_volume_reversal | 308 | 12.7% | +$493 | +7.9 | not adopted |
| n_residual | 415 | 13.5% | +$1,007 | +10.7 | not adopted |
| n_late_reversal | 401 | 27.7% | −$303 | −4.1 | rejected |

`n_residual` is the best of the seven and is $254 short of the published model validation net of $1,261. Its five largest trades made $1,081 and the other 410 trades lost $75. Those five trades are the same sessions as `n_prior_reversal`, including AMD on 2025-04-09 for $464. Removing the five largest trades leaves every book negative. The promotion gate was not run. Look 8 was not opened. The published holdout stays look 7 +$297 on 19 trades and look 6 +$210 on 52 trades. ACTIVE stays v0.1. No order was placed.
<!-- NEXT_CHANGELOG_END -->

<!-- NEXT2_CHANGELOG_BEGIN -->
## Ordinary sessions — 2026-10-13 — no checkpoint

Three books, frozen before the fill, scored on validation only. They were built to trade more often than the 85-trade hold-to-close model without buying yesterday's loser into the close. Costs: no commission, 2 bp per side, US$2,120, flat by 15:55. The holdout was not loaded. Look count stays 7.

| Id | Fills | Win | Net | bp | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| n_intraday_cont | 722 | 9.7% | −$312 | −4.6 | rejected |
| n_mid_reversal | 388 | 31.7% | −$488 | −7.3 | rejected |
| n_close_reversal | 386 | 15.0% | −$154 | −2.1 | rejected |

All three lost money. `n_intraday_cont` did fire more often (1.64 fills a day, 722 against 85) and the dollars were not a crash-day lottery. The book still lost, with 649 of 722 trades stopped. Noon reversal and the last-25-minute reversal, both short holds, also lost. Nothing was adopted. The promotion gate was not run. Look 8 was not opened. The published holdout stays look 7 +$297 on 19 trades and look 6 +$210 on 52 trades. ACTIVE stays v0.1. No order was placed.
<!-- NEXT2_CHANGELOG_END -->

<!-- REVERT_CHANGELOG_BEGIN -->
## Trough model — 2026-10-14 — no checkpoint

LightGBM on multi-timeframe troughs. A row is a new 30-minute low under VWAP in the bottom 40% of the day's range. Label: plus one ATR before minus one ATR or the 15:55 flat. Four names can be open, each a quarter of US$2,120. Thresholds 0.55, 0.60, 0.65, 0.70 were frozen. Selection is the best validation net inside 1.5 to 8 fills a day. The holdout was not loaded.

The unconditional trough hits the target 50.2% of the time. The chosen probability, 0.55, filled 767 times (1.75 a day), won 51.1%, and lost $146. Average win $1.01, average loss $1.44, max drawdown $173. Without the five best days the loss is $177. Those five days made $31 together. This is not a crash-day lottery. 0.60 and above are too rare to be the 2–6 fill book, and they lose too. A sequence model was not fit. ACTIVE stays v0.1. No order was placed.
<!-- REVERT_CHANGELOG_END -->

<!-- GRID15_CHANGELOG_BEGIN -->
## 15-minute pro-trader grid — 2026-10-14 — no checkpoint

The stack in `backtest/grid15.py` follows `research/RESEARCH_PRO_TRADERS.md`. `pro_aplus` buys the first 15-minute close through the opening range only when VWAP, relative volume, relative strength, internals, the gap, prior-day extension, the morning clock, the 20-day trend, and the event calendar all agree. Risk is 0.5% at the range low. Half exits at 1R and the runner aims at 2R. Flat by lunch or 15:55. The thresholds were frozen before the fill. The holdout was not loaded.

Validation, 2024-07-01 through 2026-03-31: 58 fills, 29 entries, 0.13 fills a day, win 27.6%, −$36. Average win $1.26, average loss $1.33, max drawdown $43. Without the five best days, −$53. Of 433 sessions, 405 had no fill. The bare opening-range break, same costs and exits, lost $167 on 1,189 fills (2.75 a day) and $238 without its five best days. Removing any one tier left a loss. The afternoon VWAP book lost $9. The short failed-break lost $31, and $84 without its five best days. Session VWAP never vetoed a break that the range itself had not already put above VWAP. ACTIVE stays v0.1. No order was placed.
<!-- GRID15_CHANGELOG_END -->

<!-- GRID15_NEXT_CHANGELOG_BEGIN -->
## Exit tests and daily top-k — 2026-10-14 — no checkpoint

`backtest/grid15_next.py` freezes five exits of the same opening-range break, and a separate book that buys the four highest slot scores each day. Costs are tiered IBKR commission and 2 bp per side on US$2,120. The stop and target on the rank book are that slot's own historical standard deviation, with a 20 bp floor. A regime switch sits out only when both SPY and QQQ closed under their 20-day average. The holdout was not loaded.

Validation: every exit lost. The 30-minute time stop was −$676 on 814 fills (1.88 a day). Holding to 15:55 was −$815 on 793 fills. The trail was −$776. After slippage and before commission the price path was still negative, from −$99 to −$253. The rank book traded 431 of 433 sessions. Momentum lost $1,098 on 1,266 fills (2.92 a day). Reversion lost $926 on 1,304 fills (3.01 a day); after slippage and before commission that book was −$1, so the $925 of commission is the loss. Gating on the two indexes cut the dollar loss in proportion to the trades removed. No book cleared the frozen screen. ACTIVE stays v0.1. No order was placed.
<!-- GRID15_NEXT_CHANGELOG_END -->

<!-- GRID15_COST_CHANGELOG_BEGIN -->
## Cost hurdle — 2026-10-15 — no checkpoint

Jay trades through IBKR. `app/cost_model.json` is tiered commission plus 2 bp of slippage. The cost-clearing books in `backtest/grid15_next.py` were frozen before the fill: one full ticket, two half tickets, a 40 bp volatility floor, a 1.5 sigma dislocation, and a slot whose own history reverted by more than 20 bp. The package is `c_primary`. The holdout was not loaded.

Validation: one full ticket lost $383 on 433 fills (1.00 a day), win 52.4%, −4.9 bp, and −$449 without the five best days. Two names lost $587, −9.2 bp. The 40 bp floor lost $812, −18.5 bp. The 1.5 sigma fade lost $724, −22.1 bp, win 38.3%. The 20 bp historical filter never qualified a slot in the validation window, so the package did not trade. The best slot at the end of the sample had reverted 4.6 bp. ACTIVE stays v0.1. No order was placed.
<!-- GRID15_COST_CHANGELOG_END -->

<!-- SESSION_EDGE_CHANGELOG_BEGIN -->
## Session edge — 2026-10-16 — no checkpoint

`backtest/session_edge.py` freezes six long-only books before the fill. The primary buys the name at least 30 bp behind its walk-forward beta to SPY, one full ticket, held 60 minutes. The other books are a 15 bp SPY impulse, a 40 bp bar fade, a 40 bp bar continuation, a 30 bp VWAP discount, and the Gao, Han, Li, and Zhou last half-hour as a time exit. Costs are tiered IBKR commission and 2 bp. The holdout was not loaded.

Validation, 439 SPY sessions: the residual book lost $681 on 431 fills (0.98 a day), win 43.6%, −9.5 bp, and −$896 without the five best days. After slippage and before commission it was −$359. The impulse slice lost $358, −11.2 bp, on 176 fills. The down-bar fade lost $746. The up-bar lost $479, −6.2 bp. The VWAP discount lost $659. The last half-hour lost $479, −6.9 bp, with the 100 bp stop binding 21 times. The median day's worst residual was −178 bp, so the 30 bp band was not a rare dislocation. ACTIVE stays v0.1. No order was placed.
<!-- SESSION_EDGE_CHANGELOG_END -->

<!-- VOLUME_EDGE_CHANGELOG_BEGIN -->
## Same-minute volume — 2026-10-17 — no checkpoint

Price-path rules on the eight names are negative before commission, across 15 to 60 minutes and the flat. `backtest/volume_edge.py` freezes the missing field: a bar from 10:00 to 14:00 whose volume is at least twice the prior 20 sessions of that same minute, and up at least 10 bp. One full ticket, 30 minutes. The fade of a heavy down bar and a quiet up bar are controls. The holdout was not loaded. Earnings dates were not invented.

Validation, 439 SPY sessions: the loud up bar lost $722 on 423 fills (0.96 a day), win 38.8%, −10.3 bp, and −$939 without the five best days. After slippage and before commission it was −$406. The fade lost $580, −8.3 bp. The quiet bar lost $502, −10.2 bp. A 2× up bar exists on 96.8% of sessions, so the multiple is not a rare-event filter. ACTIVE stays v0.1. No order was placed.
<!-- VOLUME_EDGE_CHANGELOG_END -->



