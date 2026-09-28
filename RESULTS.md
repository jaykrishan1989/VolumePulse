# Right Time to Buy — measured results

Verdict: **do not trade it.** No pre-registered configuration has a cost-inclusive edge on the locked holdout. That includes the live rule and the least-bad filter the validation window could find. This is not a forecast that every future day loses money. It is the out-of-sample result: after commissions and 2 bp of slippage, the average trade lost money, and the loss is not a sampling fluke in the direction of a profit.

The app still shows the setups. Each card carries the holdout win rate and expectancy of the rule that is actually on screen (the unmodified baseline). The paper log records live appearances and later marks stop, target, or the 15:55 exit. Nothing in this repo places an order.

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

## How to reproduce

```powershell
python -m unittest tests.test_entry tests.test_harness tests.test_outcomes
python -m backtest.scan
python -m backtest.run_search
```

`backtest.scan` writes `backtest_cache/signals.pkl` (gitignored). `run_search` writes `backtest_cache/report.json` and refreshes `app/research_stats.json`, which is what the tab displays. Re-running the search repeats the same locked holdout; it does not authorize a new grid.
