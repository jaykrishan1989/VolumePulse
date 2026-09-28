# Right Time to Buy — measured results

Verdict: **do not trade it.** The rule is now the round trip from the moment a name appears on the list to the moment it leaves. Twelve validation trials, including hysteresis so names do not flicker, all lost money after IBKR commissions and 2 bp of slippage on a US$2,120 account. The least-bad cell was read once on the locked holdout and lost there too. The tab still emits BUY and SELL for a person to confirm. It does not place orders.

## Appear, then disappear

A BUY is the bar a ticker joins the Right Time to Buy list. The fill is the next 5-minute bar's open, worsened by 2 bp. A SELL is the bar it leaves. The fill is the next bar's open, again worsened by 2 bp. One off bar can be ignored when exit lag is greater than 1, and the name has to stay on for the confirm bars before the buy exists. Anything still open is flat on the close of the 15:50 ET bar (15:55). The stop printed on the buy bar is a safety net. Results are reported with that stop and without it. Cash left over can fund a second share in another name. Whole shares only.

The account is US$2,120, which is CA$3,000 at 1.4165. Tiered commission is max(US$0.35, US$0.0035/share), cap 1% of notional. Fixed is max(US$1, US$0.005/share). Sells add SEC US$27.80 per US$1M and FINRA TAF US$0.000166/share. The scorer is still `diagnose_entry`. These trials do not change its numeric gates. They decide which of its prints become a list membership, and when that membership ends.

| Window | Dates | Role |
| --- | --- | --- |
| Train | 2022-01-01 – 2024-06-30 | Description only. Not used to pick. |
| Validate | 2024-07-01 – 2026-03-31 | The only window that ranks rules. 439 sessions. |
| Holdout | 2026-04-01 – end of the files (~Sep 2026) | Read once, after the pick was frozen. 123 sessions. |

Eight cells were written down first: appear on the first on-list bar and leave on the first off bar; wait 2 off bars; wait 3; require 2 on bars and 2 off bars; score at least 80; 10:00–12:00 ET; VWAP reclaim; reward/risk at least 2. All eight lost on validation, so one disclosed second pass added four cells from those summaries: a 1.5× wider stop, the next hysteresis step, a tighter or shifted clock, and the next score or reward/risk step. That is 12 trials. A cell needed at least 80 portfolio trades. The pick is the eligible cell with the highest validation net dollars after the tiered schedule, 2 bp, and the hard stop. Holdout dates were not in that ranking.

Validation portfolio, tiered, 2 bp, with the stop:

| Rule | Trades | /day | Win | Net | Return | Avg | Max DD | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| midmorning 10:00–11:00 | 628 | 1.43 | 30.9% | −$864 | −40.8% | −10.8 bp | $882 | 0.43 |
| confirm 3, lag 3 | 1,298 | 2.96 | 24.6% | −$1,744 | −82.3% | −18.2 bp | $1,791 | 0.32 |
| morning 10:00–12:00 | 1,408 | 3.21 | 25.8% | −$1,574 | −74.2% | −14.4 bp | $1,574 | 0.39 |
| VWAP reclaim | 1,382 | 3.15 | 25.1% | −$1,598 | −75.4% | −12.9 bp | $1,598 | 0.31 |
| score ≥ 85 | 1,818 | 4.14 | 18.4% | −$1,931 | −91.1% | −18.1 bp | $1,931 | 0.25 |
| confirm 2, lag 2 | 1,691 | 3.85 | 22.5% | −$1,941 | −91.5% | −21.1 bp | $1,972 | 0.29 |
| lag 3 | 1,798 | 4.10 | 27.3% | −$1,951 | −92.0% | −20.5 bp | $2,013 | 0.40 |
| lag 2 | 1,821 | 4.15 | 24.4% | −$1,953 | −92.1% | −20.8 bp | $2,000 | 0.35 |
| score ≥ 80 | 1,777 | 4.05 | 19.7% | −$1,963 | −92.6% | −19.5 bp | $1,963 | 0.26 |
| reward/risk ≥ 2 | 1,795 | 4.09 | 20.0% | −$1,966 | −92.7% | −21.1 bp | $1,977 | 0.24 |
| appear/disappear, no extra lag | 1,790 | 4.08 | 18.4% | −$1,985 | −93.7% | −22.5 bp | $1,985 | 0.25 |
| wider stop 1.5× | 1,786 | 4.07 | 18.9% | −$1,985 | −93.6% | −22.6 bp | $1,985 | 0.25 |

Waiting through extra off bars raised the win rate from 18% to 27% and did not produce a profit. Dropping the stop on the plain appear/disappear rule changed validation from −$1,985 to −$1,985. The loss is the round trip, not the stop. The fixed US$1 minimum made the same rule about −56 bp per trade. Train, which was not used to pick, lost −$2,094 (−48.5 bp) on the plain rule.

The frozen rule is **10:00–11:00 ET, confirm 1, exit lag 1, hard stop on**. Its validation variants:

| | Trades | Win | Net | Return | Avg | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Tiered, with stop | 628 | 30.9% | −$864 | −40.8% | −10.8 bp / −$1.38 | $882 |
| Tiered, no stop | 628 | 31.1% | −$862 | −40.7% | −11.0 bp / −$1.37 | $882 |
| Fixed US$1, with stop | 632 | 16.6% | −$1,555 | −73.4% | −31.8 bp / −$2.46 | $1,560 |

Holdout of that one rule, read once. Worth trading required holdout portfolio net above zero, a day-bootstrap p < 0.05, and a random-entry test (same symbol, same clock minute, same hold, same percent stop, another session) beaten at p < 0.05. None of that happened.

| | Tiered, with stop | Tiered, no stop | Fixed US$1, with stop |
| --- | ---: | ---: | ---: |
| Trades | 191 | 187 | 189 |
| Trades / session | 1.55 | 1.52 | 1.54 |
| Win rate | 37.2% | 38.0% | 23.8% |
| Net | **−$268** | −$250 | −$518 |
| Return on US$2,120 | **−12.7%** | −11.8% | −24.4% |
| Avg | **−8.4 bp / −$1.41** | −7.5 bp / −$1.34 | −21.1 bp / −$2.74 |
| Profit factor | 0.53 | 0.55 | 0.28 |
| Max drawdown | $321 | $304 | $540 |
| Day-bootstrap p (total ≤ 0) | 0.9995 | | |
| vs random entries | p = 0.225 (rule −6.5 bp, random −7.9 bp, full ticket) | | |

Exits on the holdout with the stop: 175 sells, 16 stops, no 15:55 flats in the taken book. The rule was a fraction of a basis point less bad than holding a random bar of the same length, and that gap is not significant. Both sides lost. The bootstrap says the dollar loss is stable. Removing the stop saved about $18 on the holdout and left the strategy unprofitable. The fixed schedule roughly doubled the loss.

### What changed versus the 60-minute bracket

The previous rule bought the first bar of a trigger and held until the stop, the target, 12 bars, or 15:55. On the holdout that was 1,984 signals, a 36.6% win rate, and **−5.9 bp (−$1.18) per trade**, with about 45% stopped, 45% timed out, and 4% hitting the target. The printed reward/risk was not the realized trade. That study used US$2,160 and did not change the live gates, because the morning bracket was only less bad and had already been seen on the holdout.

This study throws that exit away. The position lasts only while the name stays on the list. The account is US$2,120. Several names can be open when a share still fits; at these prices the book is usually one position, and skipped signals are why 6,169 validation spells became 1,790 portfolio trades. The live list now uses the frozen 10:00–11:00 window, so a row on the list is the BUY and the row leaving is the SELL. `ENTRY` itself is unchanged. The card shows this holdout, not the old bracket. A delayed or stale quote is still hidden and is not a BUY.

## Delayed quotes, 28 Sep 2026

A live check around 13:10 ET found the dashboard on IBKR **delayed** data, about 15 minutes behind. AAPL's real price was already under its stop when the row appeared. XOM filled and stopped within a minute. Both hit the stop and neither hit the target. A delayed row is not a current entry.

The live tab now does four things:

1. A banner across the dashboard when market data type is 3 or 4, or when a Right Time to Buy bar is stale.
2. A setup is not listed as a buy when its quote is delayed, when the last 5-minute bar closed more than a minute ago, or when the last trade is more than a minute behind the clock. Those rows are shown grey, marked hidden, and are not clickable buys. A forming bar is still fresh: IB stamps the bar at its open, so the check uses the bar's close.
3. The paper log stores `delayed`, `data_type`, `lag_sec`, and `withhold` on every setup. A withheld row is not an open paper trade and is not marked as a later target.
4. Before a row is listed, the latest price is checked again. At or through the stop, or at or through the target, the row is dropped.

Demo mode is unchanged unless `RTTB_FORCE_DELAY=1`, which only previews the banner. The measured P&L in this file uses the historical bars, not this live-tape fix. Those bars already lose after costs. Delayed data makes a live row worse, because the stop can be gone before it is visible.

The app still shows the list. A new name is a BUY alert, a name that leaves is a SELL, a print through the stop is a STOP, and 15:55 is a FLAT. Each one is logged and, if a webhook or ntfy topic is set, pinged with the words that it is not an order. The owner confirms every trade. Each card carries the holdout win rate and expectancy of the appear-to-disappear rule above. Nothing in this repo places an order.

## Previous test: 60-minute bracket

The numbers below are the earlier exit. They are not the rule the tab trades now, and they were not used to choose the 10:00–11:00 window above.

## Account and costs

- Ticket: US$2,160 (about CA$3,000), whole shares, one fill per signal, not compounded.
- Primary commission: IBKR tiered, max(US$0.35, US$0.0035/share), cap 1% of notional. Sells add SEC US$27.80 per US$1M and FINRA TAF US$0.000166/share.
- Slippage: 2 bp against the fill on entry and on exit (buy higher, sell lower). This is the success test. A 5 bp slip and the US$1 fixed minimum are stress checks, not a way to pick a rule.
- Flat by the close of the 15:50 ET bar (15:55). Entry is the next bar's open. If a bar trades through both stop and target, the stop fills and the target does not.
- Shorts were not tested and are not shipped. A cash account this size at IBKR Canada generally cannot borrow the stock.

## How the test was locked

| Window | Dates | Role |
| --- | --- | --- |
| Train | 2022-01-01 – 2024-06-30 | Description only. Not used to pick. |
| Validate | 2024-07-01 – 2026-03-31 | The only window that ranks configs. |
| Holdout | 2026-04-01 – end of the files (~Sep 2026) | Read once, after the pick was frozen. |

Bars are IBKR 5-minute RTH trades for AAPL, AMD, AMZN, GOOGL, META, MSFT, NVDA, and TSLA, with SPY and QQQ for the market gate. The parquet files stay out of git (`data/raw5` or `RTTB_RAW`). The scorer is `diagnose_entry` in `app/entry.py`, the same function the live tab calls. QQQ stands in for the sector ETF because those ETF bars are not in the file. A name is counted once per trigger, on the first bar it qualifies.

The grid was fixed before the ranking was read: baseline, minimum RVOL 1.0 and 1.5, VWAP reclaim, price above VWAP, reward/risk at least 2, SPY and QQQ above session VWAP, 10:00–12:00 ET, prior 5-day return positive, score at least 80, a 1R target, a 30-minute time stop, an ATR trail, and two stricter bundles. A config had to have at least 80 validation trades to be eligible. The pick is the eligible config with the highest validation mean net bps. Holdout was then read for that pick and for the unmodified baseline. Those two reads did not change the pick.

Worth trading required all three: holdout mean net bps above zero, day-bootstrap p < 0.05 for that mean, and a random-entry baseline (same symbol, same minute, other session, same percent stop and target) beaten at p < 0.05. None of that happened.

## Before: the live rule

Tiered commission, 2 bp slippage, 60-minute cap, the stop and target the card shows.

| | Train | Validation | Holdout |
| --- | ---: | ---: | ---: |
| Trades | 10,568 | 7,388 | 1,984 |
| Win rate | 37.6% | 35.0% | 36.6% |
| Avg net | −6.8 bp / −$1.41 | −9.4 bp / −$1.91 | **−5.9 bp / −$1.18** |
| Avg R | −0.21 | −0.32 | −0.25 |
| Profit factor | 0.72 | 0.57 | 0.72 |
| Signals per session | 16.9 | 16.8 | 16.1 |
| One-position P&L | −$3,356 (2,526 trades) | −$3,340 (1,935) | **−$753 (567)** |
| One-position avg | −6.4 bp | −8.5 bp | −6.8 bp |

Holdout exits: stop 890, time 888, 15:55 flat 118, target 88. The printed reward/risk is not what the trade realizes. Targets fill about 4% of the time.

Validation day-bootstrap p-value for a positive mean: 1.00 (every resample was still a loss). Against random entries, p = 0.99, and the random entries lost less (−8.4 bp versus −9.4 bp). The live rule does not beat a coin-flip entry at the same clock time.

With slippage set to 0, the same baseline trades are +0.9 bp gross on train and −2.8 bp after commission; validation is already −1.7 bp before commission; holdout is +2.0 bp before commission and −1.9 bp after. The 2 bp slip the account has to assume takes the holdout to −5.9 bp. There is no price edge large enough to pay the ticket.

## After: the validation pick, then the holdout

Every eligible config lost money on validation. Ranked by mean net bps:

| Config | Trades | Win rate | Avg net | Profit factor |
| --- | ---: | ---: | ---: | ---: |
| morning (10:00–12:00) | 2,641 | 38.1% | −8.0 bp / −$1.62 | 0.67 |
| VWAP reclaim | 1,317 | 35.9% | −8.8 bp | 0.60 |
| SPY and QQQ above VWAP | 3,029 | 35.1% | −9.0 bp | 0.57 |
| exit at 1R | 7,388 | 42.1% | −9.1 bp | 0.56 |
| price above VWAP | 1,232 | 36.0% | −9.1 bp | 0.59 |
| 30-minute time stop | 7,388 | 34.5% | −9.4 bp | 0.49 |
| prior 5-day return > 0 | 4,236 | 34.6% | −9.4 bp | 0.55 |
| ATR trail | 7,388 | 28.5% | −9.4 bp | 0.51 |
| baseline | 7,388 | 35.0% | −9.4 bp | 0.57 |
| score ≥ 80 | 4,636 | 34.8% | −9.6 bp | 0.56 |
| reward/risk ≥ 2 | 6,112 | 33.1% | −10.2 bp | 0.53 |
| RVOL ≥ 1.0 | 733 | 29.3% | −14.9 bp | 0.45 |
| RVOL ≥ 1.5 | 261 | 29.5% | −17.8 bp | 0.39 |

Two bundles were below 80 trades, so they were not eligible and were not read on the holdout. The combined bundle was +11.6 bp on 17 validation trades. That is not a result.

The frozen pick is **morning**. Its own validation bootstrap p-value is 1.00, and it does not beat random entries (p = 0.46, random mean −8.1 bp).

Holdout of that pick, read once:

| | Morning, tiered, 2 bp | Fixed US$1 min | Tiered, 5 bp slip |
| --- | ---: | ---: | ---: |
| Trades | 736 | 736 | 736 |
| Win rate | 40.2% | 36.3% | 36.7% |
| Avg net | **−1.7 bp / −$0.36** | −8.3 bp / −$1.66 | −7.7 bp / −$1.54 |
| Avg R | −0.09 | −0.26 | −0.22 |
| Profit factor | 0.93 | 0.71 | 0.72 |
| One-position P&L | −$162 (215 trades) | −$442 | −$417 |
| Day-bootstrap p (mean ≤ 0) | 0.67 |  |  |
| vs random entries | p = 0.075 (random mean −4.4 bp) |  |  |

The morning holdout is a smaller loss than the baseline holdout. It is still a loss. It is not significant, it fails the 5 bp and fixed-commission stresses, and it was not used as a reason to change the live thresholds. Doing that after seeing the holdout would be a second pick. The live `ENTRY` gates are unchanged.

A hard RVOL floor, which would have hidden a name printing 0.23×, was one of the worst validation cells. The card now shows session VWAP (computed from the bars, not the often-blank delayed quote) and the RVOL number, including when it is below 1.

## What was not a candidate

The earlier LightGBM ensemble (5 models, 60-minute return, 51 features) is not in this repo. Its own write-up already reported a walk-forward that failed a day-bootstrap and a cost stress, with the profit concentrated on one day. It was not rebuilt and it is not a gate.

## Research log

Six further ideas, taken from the intraday-momentum, liquidity-reversal, VWAP, opening-range, and overnight/intraday papers cited in `research/RESEARCH_LOG.md`, were walk-forward tested on 2023 through March 2026 and rejected. None cleared a pre-registered screen that requires a positive pooled net, a positive validation window, a positive most-recent slice, at least 80 trades, and at least four of six semi-annual folds in the black, all after tiered commissions and 2 bp. The least-bad pooled result was buying a down open and holding to 15:55 (−$183, −8.6%). Three of its six folds made money, which is short of that screen, and the threshold was not moved after seeing that. The holdout was not opened. Look count remains 2. `research/holdout_looks.csv` is the tally.

## Promotion gate

The live champion stays the 10:00–11:00 appear-to-disappear rule. A challenger replaces it only by passing `research/GATE.md`: better net, dollars per trade, and basis points per trade on the pooled 2023-01-01 to 2026-03-31 sample; the same improvement in up and down markets, high and low volatility, and both ticker groups; wins in at least 9 of 12 windows; no window more than $212 or 15 bp worse; the per-trade edge still ahead after the five best days are removed; and paired bootstrap and sign-flip p-values under 0.05/33. The fresh slice is the locked holdout, and this batch did not open it.

On that pre-holdout sample the champion itself lost $1,475 on 1,234 trades (−$1.20 per trade, −16.8 bp). That is a longer window than the −$864 validation result and it is not the holdout. All six challengers were rejected. The down-gap rule was the only one ahead of the champion on all three pooled measures (−$183, −$0.26 per trade, −13.0 bp) and it still won only 7 of 12 windows, with severe regressions on down days, low-volatility days, and 2024H2. Its daily-gap p-values were about 0.02, which does not clear 0.00152. Dropping its five best days left the dollar total ahead and the per-trade edge behind. No live threshold moved.

## Versions

There is no v1.0. The live rule failed the costs-and-random bar (holdout net −$268, bootstrap p = 0.9995, random-entry p = 0.225), so the checkpoint is **v0.1 baseline**. `models/ACTIVE` points at it. The git tag is `v0.1`. Parameters, windows, and the holdout summary are in `models/checkpoints/v0.1/`. A plain note is `NOTE.md` in that folder. The history of rejected rules is `models/CHANGELOG.md`.

The monitor trips when the last 30 closed paper trades average at least 10 bp worse than this checkpoint's −8.4 bp expectancy and a binomial test of that shortfall is under 5 percent. With no passing checkpoint on file, ACTIVE stays at v0.1 and the screen shows a held rollback. `python -m models.cli list` shows the pointer.

## How to reproduce

```powershell
python -m unittest tests.test_entry tests.test_harness tests.test_outcomes tests.test_freshness tests.test_spells tests.test_signals tests.test_hypotheses tests.test_gate tests.test_models
python -m backtest.scan
python -m backtest.run_search
python -c "from backtest.scan import scan_membership; scan_membership()"
python -m backtest.run_roundtrip select
python -m backtest.run_roundtrip holdout
python -m backtest.run_hypotheses
python -m backtest.run_gate
```

`backtest.scan` writes `backtest_cache/signals.pkl` (gitignored). `scan_membership` writes `backtest_cache/membership.pkl`, every on-list bar, which the bracket cache cannot rebuild. `run_roundtrip select` freezes `app/signal_rule.json` without reading the holdout. `holdout` reads that file once and refreshes `app/research_stats.json`. Re-running holdout repeats the same locked window. It does not authorize another grid. `run_hypotheses` rewrites the research log from the frozen registry, keeps the promotion-gate section, and does not open the holdout. `run_gate` scores the registry against the live champion and does not write `app/signal_rule.json`.
