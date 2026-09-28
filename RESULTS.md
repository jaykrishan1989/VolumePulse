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

## Research areas

Fifteen overlays were scored on the same promotion gate, on 2023-01-01 through 2026-03-31, with the holdout left shut. The Bonferroni line for this batch is 0.05/48. Sizing, liquidity, and regime keep the live 10:00–11:00 signals. Time of day keeps the same confirm, exit lag, and stop, and keeps a spell only when the on-list bar falls in that clock. The champion on this window is still 1,234 trades, −$1,475, −$1.20 per trade, −16.8 bp. Every overlay was rejected. No half-year was a profit. `models/ACTIVE` stays v0.1. No checkpoint was issued. The sources and the window tables are in `research/RESEARCH_LOG.md`.

| Overlay | Trades | Net | Per trade | Windows |
| --- | ---: | ---: | ---: | ---: |
| 1% risk to the stop | 1,243 | −$1,477 | −$1.19, −16.5 bp | 4/12 |
| 0.5% risk to the stop | 1,342 | −$1,480 | −$1.10, −18.1 bp | 0/12 |
| One open position | 1,115 | −$1,420 | −$1.27, −11.5 bp | 0/12 |
| Stop after a 1% day or two losses | 1,057 | −$1,339 | −$1.27, −16.9 bp | 3/12 |
| Fractional Kelly, cap 25% | 0 | $0 | n/a | 0/12 |
| Open, 9:45–10:30 | 517 | −$657 | −$1.27, −13.2 bp | 4/12 |
| Midday, 11:00–13:00 | 1,876 | −$1,999 | −$1.07, −27.6 bp | 0/12 |
| Afternoon, 13:00–14:30 | 1,719 | −$1,859 | −$1.08, −21.7 bp | 0/12 |
| Last hour, 14:30–15:30 | 1,095 | −$1,280 | −$1.17, −15.7 bp | 6/12 |
| Half-spread slippage | 1,056 | −$1,901 | −$1.80, −32.3 bp | 0/12 |
| Square-root participation | 1,207 | −$1,518 | −$1.26, −17.7 bp | 0/12 |
| $5M dollar-volume floor | 1,234 | −$1,475 | −$1.20, −16.8 bp | 0/12 |
| SPY at or above VWAP | 751 | −$931 | −$1.24, −14.2 bp | 4/12 |
| Stand aside after a wide SPY day | 923 | −$1,219 | −$1.32, −16.4 bp | 1/12 |
| Stand aside when SPY is down 0.30% | 1,025 | −$1,257 | −$1.23, −14.0 bp | 4/12 |

**Position sizing.** A 1% risk budget reduced the share count on 95 fills the full ticket also took. The rest were unchanged, because a stop tighter than about 1% of price asks for more shares than the cash can buy, and the cash cap wins. The book still lost $1,477. The 0.5% budget cut 486 of those fills and let extra names in with the leftover cash. That raised the trade count and made the per-trade loss worse, −18.1 bp, because the US$0.35 minimum is a larger fraction of a thinner ticket. One open position lost fewer dollars (−$1,420) and the daily-gap p-values cleared 0.00104 (bootstrap 0.0004, permutation 0.0002), but dollars per trade got worse (−$1.27) and no window won. The daily stop lost $1,339, which is a smaller hole, and still lost −$1.27 per trade on 3 of 12 windows. Kelly, estimated from earlier full-ticket champion returns and capped at 25%, was zero on all 1,799 spells: the past mean is negative, so the formula bets nothing. An empty book is not a promotion. Its tiny p-value is the champion's losses showing up as a positive daily gap against a book that did not trade. The gate rejects it because it has no trades.

**Time of day.** The scorer already drops the first and last 15 minutes, so 9:30–9:45 is empty on purpose. The open window lost −$657 on 517 trades, −13.2 bp. Fewer trades make a smaller dollar hole, and the paired p-value is 0.0002, but dollars per trade (−$1.27) do not beat the champion and only 4 windows won. Midday was the worst clock, −$1,999 and −27.6 bp, with severe regressions in both directions and both volatility buckets. By 2025H2 the account was about $121, under one share of these names, so the later midday folds have no fills. Afternoon lost −$1,859 and −21.7 bp. The last hour was the only clock ahead of the champion on all three pooled measures, by about three cents a trade and 1.1 bp, and it won 6 of 12 windows. Every half-year was still a loss. Dropping the five best days removed the per-trade dollar edge, and the paired p-values were 0.12. The live list stays 10:00–11:00.

**Liquidity.** These files are OHLC, not quotes. The Corwin-Schultz half-spread, applied to the entry bar and the bar before it, averaged 4.5 bp on top of the 2 bp already charged. The book then lost −32.3 bp per trade. That gap is wider than 4.5 bp because stops and leftover cash change which fills happen (1,056 trades against the champion's 1,234). Square-root impact of a US$2,120 ticket averaged 0.27 bp. The US$0.35 minimum is about 3.5 bp round trip on this account, so the commission binds and participation does not. Charging the 0.27 bp left the book at −17.7 bp, a bit worse than the champion. A US$5,000,000 dollar-volume floor kept all 1,799 spells. A filter that matches the champion is not an improvement.

**Market regime.** Buying the dip only while SPY was at or above its session VWAP cut the loss to −$931 and −14.2 bp, stood aside on 786 spells, and won 4 of 12 windows. Dollars per trade were worse (−$1.24). Standing aside after a prior SPY day in the top quartile of the previous 60 ranges lost −$1,219 and won 1 window. Standing aside when SPY was already down 0.30% from the 9:30 open lost −$1,257 and −14.0 bp, on 4 windows. Those three lost fewer dollars than the champion, and their paired p-values cleared 0.00104, because skipping a negative-edge trade shrinks the hole. None of them improved dollars per trade, and none won 9 windows. They were not adopted, and the direction of each filter was not flipped after the run.

## Every session

The live midmorning book does not wait for a rare day. On 2023-01-01 through 2026-03-31 it filled on 563 of 813 SPY sessions (69%). The request was a book that signals on essentially every session, still intraday, still flat by 15:55, still on the eight stored stocks, still at US$2,120 with tiered and fixed commissions and 2 bp of slippage. Five rules were frozen in `backtest/daily.py` and scored with `python -m backtest.run_daily`. The finalist had to cover at least 95% of validation sessions and then have the highest validation net. The holdout was read once for that rule (look 3) and was not used to pick it. Nothing was deployed.

| Rule | Sessions with a signal | Trades/day | Win | Net | Per trade | Per day | Max DD | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Morning leader vs SPY, hold to the close | 100% | 1.00 | 25.6% | −$318 | −$0.39 | −$0.39 | $812 | 8/12, rejected |
| Furthest under VWAP at 10:30 | 100% | 1.00 | 46.0% | −$1,143 | −$1.41 | −$1.41 | $1,160 | 4/12, rejected |
| First opening-range break | 94.2% | 0.94 | 43.5% | −$773 | −$1.01 | −$0.95 | $1,386 | 6/12, rejected |
| First pullback after the open | 99.9% | 1.00 | 21.7% | −$853 | −$1.05 | −$1.05 | $932 | 8/12, rejected |
| First VWAP reclaim | 99.8% | 1.00 | 22.8% | −$992 | −$1.22 | −$1.22 | $1,576 | 5/12, rejected |

None of them shows a cost-inclusive edge. Every pooled net is negative. The fixed US$1 minimum makes each one worse (the morning leader falls from −$318 to −$1,338).

The morning leader is the validation finalist because it signals every session and its validation loss (−$367) was the smallest among the rules that cleared 95% coverage. It is still a loss: −1.8 bp per trade, a $812 drawdown, and a 25.6% win rate, which means the one-ATR stop is the usual exit. Three of the six half-years made money and three lost, including −$387 in 2025H2. Against the champion it won 8 of 12 windows, short of 9. Down days were a severe regression, $1,680 worse. The paired p-values were 0.047 and 0.056, against a Bonferroni line of 0.00094. Dropping the five best days left it behind on dollars per trade.

Its holdout, look 3, was a signal every session: 123 trades, 26.8% winners, +$90, +3.2 bp, $243 max drawdown. The same trades lose $134 under the fixed US$1 minimum. The validation window had already lost $367. One green slice after that loss is not an edge, and the live rule was left at v0.1.

## Slippage-only cost

IBKR is the data source. The owner does not trade through it. Execution is modeled on a zero-commission platform. The live config is `app/cost_model.json`: no broker commission, no regulatory fee, 2 bp slippage on the next bar's open. There is no IBKR commission column. The same frozen rules were re-scored. Thresholds were not moved. The Bonferroni denominator stays 53. Look count stays 3. `models/ACTIVE` stays `v0.1`. Tables earlier in this file are the old IBKR-assumption measurements. They are not the execution cost.

Pooled window 2023-01-01 through 2026-03-31. Positive means the portfolio net is above zero.

| Rule | Trades | Win | Net | Per trade | Gate |
| --- | ---: | ---: | ---: | ---: | --- |
| Live midmorning book | 1,228 | 40.0% | −$786 | −$0.64, −4.2 bp | reference |
| SPY last half-hour | 466 | 35.2% | −$302 | −$0.65, −3.9 bp | 4/12, rejected |
| Same clock, eight stocks | 1,009 | 45.9% | −$553 | −$0.55, −4.1 bp | 6/12, rejected |
| Opening reversal | 790 | 39.6% | −$134 | −$0.17, +0.2 bp | 9/12, rejected |
| VWAP shortfall | 2,470 | 47.0% | −$883 | −$0.36, −2.8 bp | 6/12, rejected |
| Opening-range break | 1,195 | 46.2% | −$187 | −$0.16, −2.2 bp | 5/12, rejected |
| Down-gap hold | 703 | 23.8% | +$350 | +$0.50, +6.2 bp | 8/12, rejected |
| Morning leader vs SPY | 813 | 25.6% | +$302 | +$0.37, +2.1 bp | 8/12, rejected |
| Furthest under VWAP | 813 | 47.7% | −$656 | −$0.81, −4.8 bp | 5/12, rejected |
| First opening-range break, daily | 766 | 44.6% | −$336 | −$0.44, −1.7 bp | 6/12, rejected |
| First pullback | 812 | 22.0% | −$307 | −$0.38, −1.7 bp | 8/12, rejected |
| First VWAP reclaim | 811 | 24.9% | −$556 | −$0.69, −4.1 bp | 5/12, rejected |

**What stays positive.** Two pooled nets are above zero: the down-gap hold (+$350) and the morning leader (+$302). On the validation window, only the down-gap hold is positive (+$194, +2.8 bp).

**Daily-frequency rank**, validation window only, highest net first: morning leader −$98, first pullback −$166, furthest under VWAP −$478, first VWAP reclaim −$744, first opening-range break −$760. The opening-range break also misses the 95% coverage bar (93.8% of validation sessions). Every validation net is a loss, so the finalist is still the morning leader, as the smallest loss among the rules that fire often enough. Its pooled +$302 is the earlier part of the sample. The window that is allowed to rank rules lost $98.

**Down-gap hold.** Pooled +$350, +6.2 bp, 703 trades, win rate 23.8%, drawdown $1,012. Validation +$194. It still fails the gate: 8 of 12 windows, severe losses on down days, low-volatility days, and 2024H2. Removing its five best days leaves −$485 and −$0.70 per trade. Paired p-values are 0.063 and 0.066, against 0.00094. Its holdout was not opened.

**Morning leader.** Pooled +$302, +2.1 bp, a trade every session, win rate 25.6%, drawdown $596. Validation −$98. The gate wins 8 of 12 windows. Down days are $2,059 worse than the champion. Paired p-values are 0.090 and 0.101. Look 3 was already on file, so those same trades were restated and not used to rank: +$170, +6.9 bp. A green holdout after a losing validation window is not a promotion.

**What stays negative.** The opening reversal loses $134. Its average trade is about +0.2 bp because that average does not weight the dollar size the way the portfolio does, and it still fails on down days. The opening-range break is −$187. The live book is −$786 (−4.2 bp). Look 2 restated on that rule is −$141 (−3.2 bp, 190 trades).

## Intraday model

One pre-registered model, `ml_lgb_60m`. LightGBM regression of the 60-minute forward return from the next bar's open, divided by the prior-day ATR as a fraction of the prior close. Three frozen seeds (7, 11, 21) are averaged. Eighty rounds, 15 leaves. Features stop at the signal bar's close: multi-horizon returns, volatility, relative volume, VWAP distance, time of day, prior-day context, cross-sectional ranks, and SPY/QQQ context. The label is not inside the features, and slippage is charged at the fill, not inside the label.

The entry is the next bar's open when the predicted raw return is at least the chosen threshold. The exit is the open 60 minutes later, or the 15:50 bar if that horizon would still be open at the flat. One ATR under the entry open is a stop. Same-name overlap is blocked. The book is flat by 15:55. Account US$2,120. No commission. 2 bp slippage per side.

The threshold was chosen on the validation window only, from 0, 10, 20, and 30 bp, before the holdout model was fit. Every cell lost money. 20 bp was the least-bad (−$93, 126 trades), a dollar ahead of 10 bp. That choice is `research/ml_selection.json` with `holdout_used` false. Walk-forward test folds are quarterly from 2023Q1 through 2026Q1. Training drops the day before the fold and never includes a holdout day.

| Slice | Trades | Days with a trade | Trades/day | Win | Net | Per trade | Per day | bp | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pooled 2023-01-01..2026-03-31 | 270 | 11.9% | 0.33 | 46.7% | −$319 | −$1.18 | −$0.39 | −6.6 | $456 |
| Validation | 126 | 9.1% | 0.29 | 46.8% | −$93 | −$0.74 | −$0.21 | −10.4 | $358 |
| Holdout, look 4 | 29 | 6.5% | 0.24 | 48.3% | +$77 | +$2.66 | +$0.63 | +12.6 | $86 |

Per day is the portfolio net divided by SPY sessions in the window, including sessions with no trade. The model does not produce a signal on most days. A lower threshold would. At 0 bp the validation book lost $1,436 on 2,348 trades, so the frozen rule kept the higher bar.

| Window | Trades | Net | Per trade | bp |
| --- | ---: | ---: | ---: | ---: |
| 2023H1 | 109 | −$93 | −$0.85 | −3.7 |
| 2023H2 | 28 | −$122 | −$4.35 | −23.0 |
| 2024H1 | 19 | −$37 | −$1.93 | +11.0 |
| 2024H2 | 34 | −$13 | −$0.40 | −10.4 |
| 2025H1 | 66 | −$122 | −$1.85 | −14.3 |
| 2025H2 | 12 | +$61 | +$5.05 | +25.4 |
| 2026Q1 | 10 | −$11 | −$1.14 | −7.8 |

2025H2 is the only half-year with a positive dollar net. 2024H1 is positive in basis points and negative in dollars.

**Calibration, validation bars only.** Ten equal-count bins of predicted return. The top bin averages a predicted +10.5 bp and a realized −2.1 bp. Realized return does not rise with the prediction. The 20 bp entries sit in that top tail.

**Feature gain** on the final pre-holdout boosters, highest first: prior-day QQQ return, prior-day SPY return, QQQ return from the open, SPY return from the open, prior-day range over ATR. The stock's own one-bar return and the cross-sectional rank of the 12-bar return have zero gain.

**Against the rules.** The promotion gate compares with the live midmorning book under the same zero-commission cost. The model loses fewer dollars (−$319 versus −$786) because it trades 270 times instead of 1,228. It loses more per trade (−$1.18 versus −$0.64) and more per trade in basis points (−6.6 versus −4.2). It wins 1 of 12 windows and no half-year. Down days, both volatility buckets, and both ticker groups fail. After the five best days are removed the model is −$644. Paired bootstrap p = 0.107 and permutation p = 0.107, against alpha 0.05/54 = 0.00093. Decision: rejected.

The best pre-holdout rule on the validation window is still the down-gap hold (+$194 there, +$350 pooled). The model is negative on both of those windows. That rule's holdout was not opened. The morning leader is positive pooled (+$302) and negative on validation (−$98).

**Holdout, look 4, one read.** 29 trades, 8 of 123 sessions, win rate 48.3%, +$77, +$2.66 per trade, +12.6 bp, max drawdown $86. Day-bootstrap p of a non-positive total is 0.197 (2,000 draws, 8 days). Versus random entries of the same count, p = 0.03 (100 shuffles). The fresh slice does beat the restated midmorning holdout (−$141, look 2). The profit is not significant at 5 percent, so `passes_costs_and_random` fails. No v1 checkpoint. `models/ACTIVE` stays `v0.1`. The three boosters and the config are in `models/ml/ml_lgb_60m/`. They are a record of this fit, not a live signal.

A second architecture was not fit. The spec above was frozen before the run. Another model would be a new idea and another holdout look.

## Profit objective

The ranking above asks whether a model beats the live book. This section asks a different question: which book makes the most dollars after 2 bp of slippage. Four hundred twenty-seven candidates were scored on the validation window only (2024-07-01 through 2026-03-31), with a floor of 50 trades. The menu was LightGBM at 15, 30, and 60 minutes, a wider tree, lagged returns, a stack of those forecasts, the frozen rules, and a down-gap grid. Threshold, stop, size, and exit were part of the score. The winner was written to `research/profit_selection.json` before its holdout fill.

One name a day means the first bar that clears the threshold. A later, stronger bar is ignored. An earlier pass waited for that later bar. Its holdout, look 5, was +$1,398 and is not tradable. The files are `research/profit_lookahead_summary.json`.

**Headline holdout, look 7: +$297.**

The validation winner is a LightGBM that predicts the return from the next bar's open to the 15:50 close. The first time that prediction reaches 20 bp, it buys the strongest name at that minute with the full US$2,120, sets a stop one ATR under the entry, and exits on the 15:50 close.

| Book | Window | Trades | Trades/day | Days with a trade | Win | Net | Per trade | Per day | bp | Max DD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Model | Validation | 85 | 0.19 | 19.4% | 57.6% | +$1,261 | +$14.83 | +$2.87 | +60.3 | $237 |
| Model | Holdout, look 7 | 19 | 0.15 | 15.4% | 68.4% | **+$297** | +$15.65 | +$2.42 | +82.6 | $73 |
| 1.5% down-gap rule | Validation | 146 | 0.33 | 29.8% | 26.7% | +$467 | +$3.20 | +$1.06 | +15.6 | $428 |
| 1.5% down-gap rule | Holdout, look 6 | 52 | 0.42 | 35.0% | 36.5% | +$210 | +$4.03 | +$1.70 | +41.0 | $223 |

The model made more holdout profit than the rule ($297 versus $210). That is the comparison. The holdout sample is 19 trades. The rule trades more often and made $210 on 52 trades, with a deeper drawdown ($223 versus $73).

The best frozen rule on the validation window is still the original 0.40% down-gap hold, at +$194. The 1.5% gap beat it on validation, which is why the 1.5% rule was the one read on the holdout. The 0.40% rule's holdout was not opened.

Nothing was deployed. `models/ACTIVE` stays `v0.1`. The three boosters are in `models/ml/profit_ml/`.

## More bars

The holdout book traded 19 times because the eight names often never cleared 20 bp. `DATA_REQUEST.md` asks for twelve more liquid names a US$2,120 account can buy several shares of (JPM, BAC, V, XOM, CVX, JNJ, UNH, WMT, PG, HON, NFLX, ORCL), 5-minute regular-hours bars from 2021-12-23 through 2026-09-25, plus a backfill of the current files to 2018-01-02 and six sector ETFs as context. `scripts/fetch_history.py` is the read-only fetch. It was not run here. No new holdout was opened.

## Versions

There is no v1.0. The live rule failed the costs-and-random bar (holdout net −$268, bootstrap p = 0.9995, random-entry p = 0.225), so the checkpoint is **v0.1 baseline**. `models/ACTIVE` points at it. The git tag is `v0.1`. Parameters, windows, and the holdout summary are in `models/checkpoints/v0.1/`. A plain note is `NOTE.md` in that folder. The history of rejected rules is `models/CHANGELOG.md`.

The monitor trips when the last 30 closed paper trades average at least 10 bp worse than this checkpoint's −8.4 bp expectancy and a binomial test of that shortfall is under 5 percent. With no passing checkpoint on file, ACTIVE stays at v0.1 and the screen shows a held rollback. `python -m models.cli list` shows the pointer.

## How to reproduce

```powershell
python -m unittest discover -s tests -q
python -m backtest.scan
python -m backtest.run_search
python -c "from backtest.scan import scan_membership; scan_membership()"
python -m backtest.run_roundtrip select
python -m backtest.run_roundtrip holdout
python -m backtest.run_hypotheses
python -m backtest.run_gate
python -m backtest.run_areas
python -m backtest.run_daily
python -m backtest.run_costs
python -m backtest.run_ml
```

`backtest.scan` writes `backtest_cache/signals.pkl` (gitignored). `scan_membership` writes `backtest_cache/membership.pkl`, every on-list bar, which the bracket cache cannot rebuild. `run_roundtrip select` freezes `app/signal_rule.json` without reading the holdout. `holdout` reads that file once and refreshes `app/research_stats.json`. Re-running holdout repeats the same locked window. It does not authorize another grid. `run_hypotheses` rewrites the research log from the frozen registry, keeps the promotion-gate section and the research-areas section, and does not open the holdout. `run_gate` scores the registry against the live champion and does not write `app/signal_rule.json`. `run_areas` scores the fifteen position-size, clock, liquidity, and regime overlays on the same gate and does not open the holdout or move `models/ACTIVE`. `run_daily` scores the five daily-frequency rules and reads the holdout once for the validation finalist. `run_costs` re-scores the frozen rules with the live cost model in `app/cost_model.json`: no commission and 2 bp slippage per side. It does not append a holdout look. `run_ml` fits `ml_lgb_60m`. That command has already recorded holdout look 4. Do not run it again. `run_profit` ranks the dollar search and has already recorded the causal holdout. Do not run it again.
