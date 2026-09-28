# Research log

One entry per theory. The walk-forward window ends on 2026-03-31. The holdout from 2026-04-01 is not used to choose among these ideas.

Holdout looks so far: **2**. Look 1 was the 60-minute bracket (baseline and the morning filter). Look 2 was the appear-to-disappear rule frozen at 10:00–11:00 ET. This batch did not open the holdout. The next look is allowed only as a milestone for a single rule that has already passed the walk-forward gate, and it has to be recorded in `holdout_looks.csv`.

Costs on every new row: US$2,120, whole shares, concurrent while cash remains, tiered IBKR commissions (US$0.35 minimum per side) unless a row says fixed, 2 bp slippage each side, flat by 15:55 ET. The decision column uses the hard stop. The no-stop and fixed-commission nets are reported beside it and are not a second search.

How to add a hypothesis: write a generator in `backtest/hypotheses.py`, append a `Hypothesis` to `REGISTRY` with the source, the economic rationale, and the frozen setup, then run `python -m backtest.run_hypotheses`. Do not change a threshold after reading the result. Do not pass `--milestone` unless that one id has decision `adopt_pending_holdout`.

## Already tested

### bracket_baseline

The 60-minute stop/target bracket on the live score. Validation average was −9.4 bp. Holdout look 1 was −5.9 bp per trade. Rejected. Full table in `RESULTS.md`.

### appear_disappear_midmorning

Buy the next open after a name appears, sell the next open after it leaves, 10:00–11:00 ET. Validation portfolio −$864 (−40.8%). Holdout look 2 was −$268 (−12.7%, −8.4 bp) on 191 trades. Rejected as a trade. The tab still emits the signal so it can be confirmed by hand, with that loss on the card.

## h1_spy

**Source.** Gao, L., Han, Y., Li, S. Z., and Zhou, G. (2018). Market intraday momentum. Journal of Financial Economics, 129(2), 394–414. https://doi.org/10.1016/j.jfineco.2018.05.009

**Hypothesis.** SPY's return from the prior cash close to 10:00 ET predicts a positive last-half-hour return. Buy SPY at the 15:30 open when that return is positive, and sell the close of the 15:50 bar.

**Economic rationale.** Gao, Han, Li, and Zhou find this on SPY itself and tie it to two paying counterparties: late-informed traders who wait for the open to confirm overnight news, and institutions that rebalance near the close (Bogousslavsky's infrequent-rebalancing channel, as they cite it). The other side of the 15:30 buy is a dealer selling into that demand and charging for inventory into the cash close. This account can hold that inventory only until 15:55, so the test keeps the paper's direction and gives up the last five minutes, including the closing auction.

**Test setup.** Instrument: SPY only, the paper's market. Signal: 9:55-bar close divided by the prior regular-session close, minus one, must be strictly positive. Entry: 15:30 open. Exit: 15:50 close (15:55). Protective stop: one 14-bar ATR under the entry open, ATR carried from prior bars. No other threshold. With-stop tiered fills are the decision; no-stop and fixed commissions are reported.

**Walk-forward, with stop.** Pooled 2023-01-01 to 2026-03-31: 466 trades, 0.57/session, win 23.8%, net $-619 (-29.2%), avg -8.8 bp, max drawdown $622. Validation window 2024-07-01 to 2026-03-31: 243 trades, 0.55/session, win 23.0%, net $-343 (-16.2%), avg -8.9 bp, max drawdown $351. Most recent slice 2025-07-01 to 2026-03-31: 101 trades, 0.53/session, win 20.8%, net $-139 (-6.5%), avg -8.2 bp, max drawdown $145.

Semi-annual folds, same costs:

| Fold | Trades | Win | Net | Return | Avg | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023H1 | 71 | 29.6% | $-85 | -4.0% | -6.3 bp | $85 |
| 2023H2 | 79 | 13.9% | $-156 | -7.3% | -11.0 bp | $156 |
| 2024H1 | 73 | 32.9% | $-75 | -3.5% | -5.3 bp | $76 |
| 2024H2 | 79 | 24.1% | $-132 | -6.2% | -9.6 bp | $136 |
| 2025H1 | 63 | 30.2% | $-88 | -4.2% | -7.7 bp | $95 |
| 2025H2 | 71 | 21.1% | $-113 | -5.3% | -9.1 bp | $113 |
| 2026Q1 | 30 | 20.0% | $-30 | -1.4% | -4.8 bp | $36 |

**Without the stop.** 466 trades, 0.57/session, win 25.8%, net $-605 (-28.5%), avg -8.6 bp, max drawdown $613.

**Fixed US$1 minimum, with stop.** 466 trades, 0.57/session, win 7.9%, net $-1179 (-55.6%), avg -22.4 bp, max drawdown $1179.

**Holdout.** Not checked in this batch.

**Decision.** Rejected. Pooled net is not positive after costs; 2024-07 through 2026-03 net is not positive; 2025-07 through 2026-03 net is not positive; only 0 of 6 semi-annual folds made money

## h1_stocks

**Source.** Gao, L., Han, Y., Li, S. Z., and Zhou, G. (2018). Market intraday momentum. Journal of Financial Economics, 129(2), 394–414. The published evidence is ETFs; this row asks whether the same clock-time pattern appears in the eight-stock book.

**Hypothesis.** Each stock's own return from the prior close to 10:00 predicts its last half hour. Buy at 15:30 when that return is positive and sell the 15:50 close.

**Economic rationale.** If late-day demand is index rebalancing, the pattern should be strongest in the ETF and weaker, noisier, or absent in single names after a $0.35 commission. Testing the eight names separately from SPY keeps a failure on the stocks from being read as a failure of the paper's own asset.

**Test setup.** Same clock and stop as h1_spy, applied independently to AAPL, AMD, AMZN, GOOGL, META, MSFT, NVDA, and TSLA. When several names trigger at 15:30, the larger morning return is funded first.

**Walk-forward, with stop.** Pooled 2023-01-01 to 2026-03-31: 961 trades, 1.18/session, win 31.0%, net $-1187 (-56.0%), avg -25.0 bp, max drawdown $1189. Validation window 2024-07-01 to 2026-03-31: 519 trades, 1.18/session, win 36.4%, net $-576 (-27.1%), avg -15.5 bp, max drawdown $620. Most recent slice 2025-07-01 to 2026-03-31: 215 trades, 1.14/session, win 39.1%, net $-210 (-9.9%), avg -10.6 bp, max drawdown $233.

Semi-annual folds, same costs:

| Fold | Trades | Win | Net | Return | Avg | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023H1 | 161 | 28.6% | $-339 | -16.0% | -41.6 bp | $347 |
| 2023H2 | 162 | 25.9% | $-290 | -13.7% | -40.3 bp | $314 |
| 2024H1 | 153 | 34.0% | $-120 | -5.7% | -19.7 bp | $169 |
| 2024H2 | 157 | 35.7% | $-181 | -8.5% | -19.5 bp | $225 |
| 2025H1 | 136 | 36.0% | $-191 | -9.0% | -14.8 bp | $216 |
| 2025H2 | 145 | 40.0% | $-117 | -5.5% | -9.9 bp | $140 |
| 2026Q1 | 63 | 39.7% | $-96 | -4.5% | -10.1 bp | $98 |

**Without the stop.** 978 trades, 1.20/session, win 30.9%, net $-1234 (-58.2%), avg -25.5 bp, max drawdown $1234.

**Fixed US$1 minimum, with stop.** 812 trades, 1.00/session, win 15.9%, net $-1945 (-91.8%), avg -73.1 bp, max drawdown $1945.

**Holdout.** Not checked in this batch.

**Decision.** Rejected. Pooled net is not positive after costs; 2024-07 through 2026-03 net is not positive; 2025-07 through 2026-03 net is not positive; only 0 of 6 semi-annual folds made money

## h2_opening_reversal

**Source.** Heston, S. L., Korajczyk, R. A., and Sadka, R. (2010). Intraday patterns in the cross-section of stock returns. Journal of Finance, 65(4), 1369–1407. https://doi.org/10.1111/j.1540-6261.2010.01573.x

**Hypothesis.** A stock that falls at least 0.50% from the 9:30 open to the 10:00 close bounces over the next hour. Buy the 10:00 open and sell the 11:00 open.

**Economic rationale.** Heston, Korajczyk, and Sadka show that short-horizon reversal is a liquidity imbalance that dies inside an hour, with part of the quote-level effect coming from bid-ask bounce. The paying side is the trader who sells into the open and demands immediacy; the bid that takes that flow should earn the imbalance back as the book refills. On five-minute bars the bounce is already averaged, so the remaining edge has to clear 2 bp of slippage and the $0.35 minimum. A loss after costs is the result the spread argument predicts, and it is still the right test of the direction.

**Test setup.** Own-stock return from the 9:30 open to the 9:55 close, threshold −0.50% fixed in advance. Entry 10:00 open, exit 11:00 open, stop one ATR under the entry. One trade a day. The deeper drop is funded first.

**Walk-forward, with stop.** Pooled 2023-01-01 to 2026-03-31: 766 trades, 0.94/session, win 33.3%, net $-734 (-34.6%), avg -17.2 bp, max drawdown $910. Validation window 2024-07-01 to 2026-03-31: 419 trades, 0.95/session, win 36.3%, net $-340 (-16.0%), avg -8.2 bp, max drawdown $581. Most recent slice 2025-07-01 to 2026-03-31: 182 trades, 0.96/session, win 38.5%, net $101 (4.8%), avg -1.7 bp, max drawdown $236.

Semi-annual folds, same costs:

| Fold | Trades | Win | Net | Return | Avg | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023H1 | 120 | 25.8% | $-255 | -12.0% | -43.8 bp | $275 |
| 2023H2 | 114 | 28.9% | $-145 | -6.8% | -28.0 bp | $229 |
| 2024H1 | 118 | 39.8% | $0 | 0.0% | -0.3 bp | $164 |
| 2024H2 | 109 | 30.3% | $-257 | -12.1% | -16.3 bp | $295 |
| 2025H1 | 123 | 34.1% | $-145 | -6.8% | -14.2 bp | $368 |
| 2025H2 | 121 | 39.7% | $89 | 4.2% | 0.8 bp | $221 |
| 2026Q1 | 60 | 36.7% | $10 | 0.5% | -5.0 bp | $65 |

**Without the stop.** 787 trades, 0.97/session, win 42.4%, net $-1171 (-55.2%), avg -21.8 bp, max drawdown $1208.

**Fixed US$1 minimum, with stop.** 748 trades, 0.92/session, win 27.4%, net $-1719 (-81.1%), avg -46.0 bp, max drawdown $1721.

**Holdout.** Not checked in this batch.

**Decision.** Rejected. Pooled net is not positive after costs; 2024-07 through 2026-03 net is not positive; only 2 of 6 semi-annual folds made money

## h3_vwap_shortfall

**Source.** Berkowitz, S. A., Logue, D. E., and Noser, E. A. (1988). The total cost of transactions on the NYSE. Journal of Finance, 43(1), 97–112. Almgren, R., and Chriss, N. (2001). Optimal execution of portfolio transactions. Journal of Risk, 3(2), 5–39.

**Hypothesis.** The first time after 10:30 that price closes at least 0.6 ATR below session VWAP, buy the next open and sell the next open after price closes back at VWAP, or after 60 minutes, whichever comes first.

**Economic rationale.** VWAP is the benchmark execution desks are measured against (Berkowitz, Logue, and Noser). A schedule that is behind a falling price can wait; a schedule that can buy below VWAP beats the benchmark by lifting the offer there, so latent buy interest sits under VWAP (the participation trade-off in Almgren and Chriss). The other side is a seller who needs immediacy and walks price through that bid. This long is on the side of the benchmarked buyer. The distance 0.6 ATR is a single pre-set gate so the test is not a search over how far is far enough.

**Test setup.** Session VWAP from 9:30 using typical price times volume. First signal at or after 10:30 and before 15:00. Entry is the next bar's open. Exit is the open after the first later close back at or above VWAP, else 12 bars later, else the 15:50 close. Stop is one ATR under the entry, ATR as of the signal bar. One spell a day. Larger shortfall is funded first.

**Walk-forward, with stop.** Pooled 2023-01-01 to 2026-03-31: 2044 trades, 2.51/session, win 35.1%, net $-1943 (-91.7%), avg -25.5 bp, max drawdown $1994. Validation window 2024-07-01 to 2026-03-31: 1311 trades, 2.99/session, win 39.3%, net $-1289 (-60.8%), avg -13.6 bp, max drawdown $1382. Most recent slice 2025-07-01 to 2026-03-31: 587 trades, 3.11/session, win 40.2%, net $-743 (-35.1%), avg -12.3 bp, max drawdown $760.

Semi-annual folds, same costs:

| Fold | Trades | Win | Net | Return | Avg | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023H1 | 377 | 39.0% | $-394 | -18.6% | -31.3 bp | $460 |
| 2023H2 | 400 | 38.2% | $-442 | -20.8% | -21.0 bp | $442 |
| 2024H1 | 395 | 40.5% | $-559 | -26.4% | -16.0 bp | $613 |
| 2024H2 | 373 | 41.8% | $-278 | -13.1% | -11.0 bp | $416 |
| 2025H1 | 363 | 41.6% | $-416 | -19.6% | -12.9 bp | $444 |
| 2025H2 | 397 | 38.8% | $-572 | -27.0% | -13.7 bp | $587 |
| 2026Q1 | 184 | 42.9% | $-190 | -9.0% | -8.7 bp | $196 |

**Without the stop.** 1902 trades, 2.34/session, win 41.4%, net $-1856 (-87.6%), avg -26.4 bp, max drawdown $1915.

**Fixed US$1 minimum, with stop.** 972 trades, 1.20/session, win 22.6%, net $-2034 (-96.0%), avg -68.9 bp, max drawdown $2072.

**Holdout.** Not checked in this batch.

**Decision.** Rejected. Pooled net is not positive after costs; 2024-07 through 2026-03 net is not positive; 2025-07 through 2026-03 net is not positive; only 0 of 6 semi-annual folds made money

## h4_opening_range

**Source.** Holmberg, U., Lönnbark, C., and Lundström, C. (2013). Assessing the profitability of intraday opening range breakout strategies. Finance Research Letters, 10(1), 27–33. https://doi.org/10.1016/j.frl.2012.09.001. Practitioner source: Crabel, T. (1990). Day Trading With Short Term Price Patterns and Opening Range Breakout. Traders Press.

**Hypothesis.** A close above the high of the first 15 minutes continues to the cash close. Buy the next open and sell the 15:50 close. The protective stop is the opening-range low.

**Economic rationale.** The opening range is where overnight information meets the book. A break is the informed flow that could not finish inside that range; the other side is liquidity posted at the range high. Holmberg, Lönnbark, and Lundström found a positive ORB result on crude oil, and later work from the same line ties the profits to high-volatility stretches rather than a steady edge. On mega-cap stocks the range high is a crowded stop-in, so false breaks pay the breakout buyer. The test uses one range length, 15 minutes, and does not search it.

**Test setup.** Range is the high and low of the 9:30, 9:35, and 9:40 bars, complete at 9:45. First later close above that high, entry on the next open, exit on the 15:50 close. Stop at the range low. One trade a day. A larger break, scaled by ATR, is funded first.

**Walk-forward, with stop.** Pooled 2023-01-01 to 2026-03-31: 1174 trades, 1.44/session, win 39.1%, net $-789 (-37.2%), avg -21.5 bp, max drawdown $1485. Validation window 2024-07-01 to 2026-03-31: 611 trades, 1.39/session, win 37.5%, net $-1063 (-50.1%), avg -24.3 bp, max drawdown $1309. Most recent slice 2025-07-01 to 2026-03-31: 273 trades, 1.44/session, win 36.6%, net $-702 (-33.1%), avg -25.5 bp, max drawdown $773.

Semi-annual folds, same costs:

| Fold | Trades | Win | Net | Return | Avg | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023H1 | 201 | 40.3% | $459 | 21.6% | -22.6 bp | $210 |
| 2023H2 | 187 | 38.0% | $-241 | -11.4% | -38.0 bp | $509 |
| 2024H1 | 178 | 43.3% | $155 | 7.3% | -8.7 bp | $296 |
| 2024H2 | 165 | 40.6% | $-307 | -14.5% | -18.5 bp | $588 |
| 2025H1 | 172 | 38.4% | $-191 | -9.0% | -20.4 bp | $487 |
| 2025H2 | 186 | 35.5% | $-554 | -26.1% | -31.0 bp | $584 |
| 2026Q1 | 82 | 43.9% | $-204 | -9.6% | -11.4 bp | $319 |

**Without the stop.** 1082 trades, 1.33/session, win 40.5%, net $-1003 (-47.3%), avg -25.6 bp, max drawdown $2006.

**Fixed US$1 minimum, with stop.** 1117 trades, 1.37/session, win 31.8%, net $-1804 (-85.1%), avg -52.0 bp, max drawdown $2268.

**Holdout.** Not checked in this batch.

**Decision.** Rejected. Pooled net is not positive after costs; 2024-07 through 2026-03 net is not positive; 2025-07 through 2026-03 net is not positive; only 2 of 6 semi-annual folds made money

## h5_gap_down

**Source.** Lou, D., Polk, C., and Skouras, S. (2019). A tug of war: Overnight versus intraday expected returns. Journal of Financial Economics, 134(1), 192–213. https://doi.org/10.1016/j.jfineco.2019.03.011

**Hypothesis.** A stock that opens at least 0.40% below the prior cash close has a positive intraday return. Buy the 9:45 open and sell the 15:50 close. An up gap is not bought.

**Economic rationale.** Lou, Polk, and Skouras decompose returns into an overnight clientele and an intraday clientele that pull in opposite directions: firm-level continuation inside each piece, and a cross-period reversal between them. Momentum profits in their sample accrue overnight, which this account cannot earn because it is flat by 15:55. The piece a day-trader can hold is the intraday reversal of the overnight move. The other side of a down-gap buy is the overnight seller whose flow is being offset by the intraday clientele. Buying up gaps would be the overnight-momentum trade held at the wrong time of day.

**Test setup.** Gap is the 9:30 open over the prior regular-session close, threshold −0.40% fixed in advance. Entry waits until the 9:45 open so the first 15 minutes are not a fill. Exit is the 15:50 close. Stop is one ATR under that entry. The larger down gap is funded first.

**Walk-forward, with stop.** Pooled 2023-01-01 to 2026-03-31: 705 trades, 0.87/session, win 22.4%, net $-183 (-8.6%), avg -13.0 bp, max drawdown $1174. Validation window 2024-07-01 to 2026-03-31: 353 trades, 0.80/session, win 21.5%, net $-161 (-7.6%), avg -7.2 bp, max drawdown $694. Most recent slice 2025-07-01 to 2026-03-31: 145 trades, 0.77/session, win 22.1%, net $121 (5.7%), avg 0.1 bp, max drawdown $325.

Semi-annual folds, same costs:

| Fold | Trades | Win | Net | Return | Avg | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023H1 | 140 | 22.9% | $339 | 16.0% | -21.3 bp | $153 |
| 2023H2 | 102 | 22.5% | $-18 | -0.9% | -17.3 bp | $199 |
| 2024H1 | 110 | 23.6% | $-323 | -15.2% | -24.0 bp | $336 |
| 2024H2 | 98 | 15.3% | $-483 | -22.8% | -32.4 bp | $483 |
| 2025H1 | 104 | 25.0% | $366 | 17.3% | 10.5 bp | $331 |
| 2025H2 | 90 | 23.3% | $207 | 9.8% | 6.9 bp | $206 |
| 2026Q1 | 51 | 21.6% | $-84 | -4.0% | -14.1 bp | $235 |

**Without the stop.** 706 trades, 0.87/session, win 44.5%, net $-589 (-27.8%), avg -18.9 bp, max drawdown $1808.

**Fixed US$1 minimum, with stop.** 710 trades, 0.87/session, win 20.8%, net $-1103 (-52.0%), avg -38.2 bp, max drawdown $1489.

**Holdout.** Not checked in this batch.

**Decision.** Rejected. Pooled net is not positive after costs; 2024-07 through 2026-03 net is not positive; only 3 of 6 semi-annual folds made money

## Not tested yet

These stay queued because the bars on hand cannot support them, or because this batch already had six frozen tests.

- Same clock-time continuation from Heston, Korajczyk, and Sadka: yesterday's return at a given half hour predicts today's return at that half hour. Needs a wider cross-section than eight names to match their sort.
- Order-flow imbalance and signed volume. These files are five-minute OHLC, not aggressor prints, so a flow hypothesis would be invented rather than measured.
- A short book. The account is a small Canadian cash account and the prior brief kept it long-only.

<!-- GATE_BEGIN -->
## Promotion gate

Champion: `appear_disappear_midmorning` (live rule `midmorning` in `app/signal_rule.json`). Costs: US$2,120, tiered commissions, 2 bp slippage, hard stop, flat by 15:55. Ideas already tried, and therefore the Bonferroni denominator: 33. The holdout from 2026-04-01 was not opened. Look count remains 2. The champion file was not changed.

Rules are in `research/GATE.md`. A window win needs at least 20 challenger trades and a better net, a better dollar expectancy, and a better per-trade basis-point expectancy than the champion. Voting windows are six half-years, four SPY regimes (up, down, high vol, low vol), and two ticker groups (megacap, high_beta). 2026Q1 is inside the pooled sample and is not its own vote.

| Candidate | Pooled challenger | Pooled champion | Windows | Bootstrap p | Permutation p | Decision |
| --- | --- | --- | ---: | ---: | ---: | --- |
| h1_spy | $-619 / -8.8 bp | $-1475 / -16.8 bp | 3/12 | 0.0002 | 0.0002 | REJECTED |
| h1_stocks | $-1187 / -25.0 bp | $-1475 / -16.8 bp | 1/12 | 0.0772 | 0.0804 | REJECTED |
| h2_opening_reversal | $-734 / -17.2 bp | $-1475 / -16.8 bp | 7/12 | 0.0094 | 0.0118 | REJECTED |
| h3_vwap_shortfall | $-1943 / -25.5 bp | $-1475 / -16.8 bp | 0/12 | 0.9752 | 0.9758 | REJECTED |
| h4_opening_range | $-789 / -21.5 bp | $-1475 / -16.8 bp | 2/12 | 0.2356 | 0.2304 | REJECTED |
| h5_gap_down | $-183 / -13.0 bp | $-1475 / -16.8 bp | 7/12 | 0.0216 | 0.0260 | REJECTED |

### h1_spy

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-619 on 466 trades, $-1.33/trade, -8.8 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Improves in 3 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2023-01-26, 2023-08-07, 2023-04-11, 2023-11-30, 2023-03-21), the challenger is behind on dollars per trade (challenger $-624 on 461 trades, $-1.35/trade, -9.0 bp; champion $-1363 on 1220 trades, $-1.12/trade, -16.4 bp). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

| Window | Challenger | Champion | Win |
| --- | --- | --- | --- |
| 2023H1 | $-85, 71 trades, -6.3 bp | $-251, 168 trades, -19.1 bp | yes |
| 2023H2 | $-152, 79 trades, -11.1 bp | $-303, 212 trades, -20.5 bp | no |
| 2024H1 | $-66, 73 trades, -6.0 bp | $-261, 214 trades, -15.0 bp | yes |
| 2024H2 | $-119, 79 trades, -10.1 bp | $-150, 168 trades, -10.4 bp | no |
| 2025H1 | $-70, 63 trades, -9.4 bp | $-186, 161 trades, -15.2 bp | yes |
| 2025H2 | $-98, 71 trades, -10.5 bp | $-222, 217 trades, -17.3 bp | no |
| up | $-361, 338 trades, -7.2 bp | $-718, 677 trades, -13.9 bp | no |
| down | $-258, 128 trades, -12.9 bp | $-757, 557 trades, -20.3 bp | no |
| high_vol | $-303, 228 trades, -8.9 bp | $-739, 596 trades, -16.8 bp | no |
| low_vol | $-315, 238 trades, -8.7 bp | $-736, 638 trades, -16.8 bp | no |
| megacap | $0, 0 trades, n/a | $-937, 708 trades, -13.7 bp | no |
| high_beta | $0, 0 trades, n/a | $-538, 526 trades, -20.9 bp | no |

### h1_stocks

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1187 on 961 trades, $-1.24/trade, -25.0 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Beats the champion in 1 half-year; need at least 2. Improves in 1 of 12 windows; need at least 9 (75%). Severe regression in 2023H1: expectancy is 22.6 bp worse than the champion, past the 15 bp limit. Severe regression in 2023H2: expectancy is 19.9 bp worse than the champion, past the 15 bp limit. After removing the top 5 days by daily gap (2023-01-26, 2023-08-07, 2024-04-29, 2024-05-23, 2023-03-21), the challenger is behind on dollars per trade, basis points per trade (challenger $-1248 on 956 trades, $-1.31/trade, -25.5 bp; champion $-1384 on 1217 trades, $-1.14/trade, -16.6 bp). Paired tests do not clear the Bonferroni line for 33 ideas tried (bootstrap p=0.0772, permutation p=0.0804, alpha=0.00152). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

| Window | Challenger | Champion | Win |
| --- | --- | --- | --- |
| 2023H1 | $-339, 161 trades, -41.6 bp | $-251, 168 trades, -19.1 bp | severe |
| 2023H2 | $-257, 158 trades, -40.3 bp | $-303, 212 trades, -20.5 bp | severe |
| 2024H1 | $-114, 153 trades, -20.0 bp | $-261, 214 trades, -15.0 bp | no |
| 2024H2 | $-159, 149 trades, -17.8 bp | $-150, 168 trades, -10.4 bp | no |
| 2025H1 | $-153, 137 trades, -20.4 bp | $-186, 161 trades, -15.2 bp | no |
| 2025H2 | $-102, 138 trades, -11.6 bp | $-222, 217 trades, -17.3 bp | yes |
| up | $-448, 571 trades, -22.0 bp | $-718, 677 trades, -13.9 bp | no |
| down | $-739, 390 trades, -29.4 bp | $-757, 557 trades, -20.3 bp | no |
| high_vol | $-740, 471 trades, -27.2 bp | $-739, 596 trades, -16.8 bp | no |
| low_vol | $-447, 490 trades, -22.9 bp | $-736, 638 trades, -16.8 bp | no |
| megacap | $-665, 372 trades, -21.0 bp | $-937, 708 trades, -13.7 bp | no |
| high_beta | $-522, 589 trades, -27.5 bp | $-538, 526 trades, -20.9 bp | no |

### h2_opening_reversal

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-734 on 766 trades, $-0.96/trade, -17.2 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (down, high_vol). Improves in 7 of 12 windows; need at least 9 (75%). Severe regression in 2023H1: expectancy is 24.7 bp worse than the champion, past the 15 bp limit. Severe regression in down: net is $300 worse than the champion, past the $212 limit. After removing the top 5 days by daily gap (2023-01-31, 2024-06-10, 2025-04-23, 2024-05-28, 2023-10-23), the challenger is behind on dollars per trade, basis points per trade (challenger $-994 on 761 trades, $-1.31/trade, -19.5 bp; champion $-1473 on 1225 trades, $-1.20/trade, -16.8 bp). Paired tests do not clear the Bonferroni line for 33 ideas tried (bootstrap p=0.0094, permutation p=0.0118, alpha=0.00152). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

| Window | Challenger | Champion | Win |
| --- | --- | --- | --- |
| 2023H1 | $-255, 120 trades, -43.8 bp | $-251, 168 trades, -19.1 bp | severe |
| 2023H2 | $-137, 115 trades, -28.1 bp | $-303, 212 trades, -20.5 bp | no |
| 2024H1 | $-8, 121 trades, -4.3 bp | $-261, 214 trades, -15.0 bp | yes |
| 2024H2 | $-229, 108 trades, -19.3 bp | $-150, 168 trades, -10.4 bp | no |
| 2025H1 | $-114, 117 trades, -11.8 bp | $-186, 161 trades, -15.2 bp | yes |
| 2025H2 | $22, 125 trades, -2.5 bp | $-222, 217 trades, -17.3 bp | yes |
| up | $323, 411 trades, -1.4 bp | $-718, 677 trades, -13.9 bp | yes |
| down | $-1057, 355 trades, -35.6 bp | $-757, 557 trades, -20.3 bp | severe |
| high_vol | $-371, 384 trades, -19.3 bp | $-739, 596 trades, -16.8 bp | no |
| low_vol | $-363, 382 trades, -15.2 bp | $-736, 638 trades, -16.8 bp | yes |
| megacap | $-223, 242 trades, -10.0 bp | $-937, 708 trades, -13.7 bp | yes |
| high_beta | $-511, 524 trades, -20.6 bp | $-538, 526 trades, -20.9 bp | yes |

### h3_vwap_shortfall

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1943 on 2044 trades, $-0.95/trade, -25.5 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Beats the champion in 0 half-years; need at least 2. Improves in 0 of 12 windows; need at least 9 (75%). Severe regression in 2025H2: expectancy is 24.6 bp worse than the champion, past the 15 bp limit. Severe regression in down: net is $503 worse than the champion, past the $212 limit. Severe regression in low_vol: net is $277 worse than the champion, past the $212 limit. Severe regression in high_beta: net is $341 worse than the champion, past the $212 limit. After removing the top 5 days by daily gap (2023-07-21, 2023-01-04, 2023-01-26, 2023-04-11, 2023-05-25), the challenger is behind on net, basis points per trade (challenger $-2028 on 2031 trades, $-1.00/trade, -25.6 bp; champion $-1398 on 1220 trades, $-1.15/trade, -16.7 bp). Paired tests do not clear the Bonferroni line for 33 ideas tried (bootstrap p=0.9752, permutation p=0.9758, alpha=0.00152). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

| Window | Challenger | Champion | Win |
| --- | --- | --- | --- |
| 2023H1 | $-394, 377 trades, -31.3 bp | $-251, 168 trades, -19.1 bp | no |
| 2023H2 | $-415, 391 trades, -26.1 bp | $-303, 212 trades, -20.5 bp | no |
| 2024H1 | $-421, 385 trades, -16.2 bp | $-261, 214 trades, -15.0 bp | no |
| 2024H2 | $-267, 367 trades, -17.3 bp | $-150, 168 trades, -10.4 bp | no |
| 2025H1 | $-282, 321 trades, -28.8 bp | $-186, 161 trades, -15.2 bp | no |
| 2025H2 | $-154, 186 trades, -41.9 bp | $-222, 217 trades, -17.3 bp | severe |
| up | $-683, 1116 trades, -19.6 bp | $-718, 677 trades, -13.9 bp | no |
| down | $-1260, 928 trades, -32.7 bp | $-757, 557 trades, -20.3 bp | severe |
| high_vol | $-930, 1020 trades, -26.9 bp | $-739, 596 trades, -16.8 bp | no |
| low_vol | $-1013, 1024 trades, -24.2 bp | $-736, 638 trades, -16.8 bp | severe |
| megacap | $-1063, 1084 trades, -18.2 bp | $-937, 708 trades, -13.7 bp | no |
| high_beta | $-880, 960 trades, -33.8 bp | $-538, 526 trades, -20.9 bp | severe |

### h4_opening_range

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-789 on 1174 trades, $-0.67/trade, -21.5 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Beats the champion in 1 half-year; need at least 2. Improves in 2 of 12 windows; need at least 9 (75%). Severe regression in 2025H2: net is $292 worse than the champion, past the $212 limit. Severe regression in down: net is $3786 worse than the champion, past the $212 limit. Severe regression in megacap: net is $574 worse than the champion, past the $212 limit. After removing the top 5 days by daily gap (2025-04-09, 2023-02-01, 2023-08-14, 2025-10-08, 2023-01-06), the challenger is behind on net, dollars per trade, basis points per trade (challenger $-1641 on 1168 trades, $-1.40/trade, -25.5 bp; champion $-1488 on 1230 trades, $-1.21/trade, -16.9 bp). Paired tests do not clear the Bonferroni line for 33 ideas tried (bootstrap p=0.2356, permutation p=0.2304, alpha=0.00152). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

| Window | Challenger | Champion | Win |
| --- | --- | --- | --- |
| 2023H1 | $459, 201 trades, -22.6 bp | $-251, 168 trades, -19.1 bp | no |
| 2023H2 | $-285, 195 trades, -30.4 bp | $-303, 212 trades, -20.5 bp | no |
| 2024H1 | $207, 182 trades, -8.7 bp | $-261, 214 trades, -15.0 bp | yes |
| 2024H2 | $-328, 174 trades, -17.1 bp | $-150, 168 trades, -10.4 bp | no |
| 2025H1 | $-186, 164 trades, -21.3 bp | $-186, 161 trades, -15.2 bp | no |
| 2025H2 | $-514, 180 trades, -28.2 bp | $-222, 217 trades, -17.3 bp | severe |
| up | $3755, 692 trades, 16.8 bp | $-718, 677 trades, -13.9 bp | yes |
| down | $-4543, 482 trades, -76.5 bp | $-757, 557 trades, -20.3 bp | severe |
| high_vol | $-550, 585 trades, -23.7 bp | $-739, 596 trades, -16.8 bp | no |
| low_vol | $-238, 589 trades, -19.4 bp | $-736, 638 trades, -16.8 bp | no |
| megacap | $-1511, 598 trades, -22.1 bp | $-937, 708 trades, -13.7 bp | severe |
| high_beta | $723, 576 trades, -21.0 bp | $-538, 526 trades, -20.9 bp | no |

### h5_gap_down

**Decision.** Rejected. Does not beat the champion in every market regime (down, low_vol). Improves in 7 of 12 windows; need at least 9 (75%). Severe regression in 2024H2: net is $322 worse than the champion, past the $212 limit. Severe regression in down: net is $737 worse than the champion, past the $212 limit. Severe regression in low_vol: net is $255 worse than the champion, past the $212 limit. After removing the top 5 days by daily gap (2025-04-07, 2023-01-06, 2023-02-14, 2025-04-09, 2023-03-13), the challenger is behind on dollars per trade, basis points per trade (challenger $-919 on 697 trades, $-1.32/trade, -20.1 bp; champion $-1500 on 1230 trades, $-1.22/trade, -16.9 bp). Paired tests do not clear the Bonferroni line for 33 ideas tried (bootstrap p=0.0216, permutation p=0.0260, alpha=0.00152). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

| Window | Challenger | Champion | Win |
| --- | --- | --- | --- |
| 2023H1 | $339, 140 trades, -21.3 bp | $-251, 168 trades, -19.1 bp | no |
| 2023H2 | $-15, 104 trades, -18.5 bp | $-303, 212 trades, -20.5 bp | yes |
| 2024H1 | $-366, 110 trades, -23.7 bp | $-261, 214 trades, -15.0 bp | no |
| 2024H2 | $-471, 96 trades, -33.1 bp | $-150, 168 trades, -10.4 bp | severe |
| 2025H1 | $243, 111 trades, 9.4 bp | $-186, 161 trades, -15.2 bp | yes |
| 2025H2 | $172, 90 trades, 10.6 bp | $-222, 217 trades, -17.3 bp | yes |
| up | $1312, 333 trades, 19.0 bp | $-718, 677 trades, -13.9 bp | yes |
| down | $-1495, 372 trades, -41.6 bp | $-757, 557 trades, -20.3 bp | severe |
| high_vol | $808, 358 trades, -1.1 bp | $-739, 596 trades, -16.8 bp | yes |
| low_vol | $-991, 347 trades, -25.3 bp | $-736, 638 trades, -16.8 bp | severe |
| megacap | $-332, 263 trades, -11.1 bp | $-937, 708 trades, -13.7 bp | yes |
| high_beta | $150, 442 trades, -14.1 bp | $-538, 526 trades, -20.9 bp | yes |

<!-- GATE_END -->

<!-- AREAS_BEGIN -->
## Research areas

Four areas, fifteen pre-registered overlays. Sizing, liquidity, and regime keep the live 10:00–11:00 signals. Time-of-day keeps the same confirm, exit lag, and stop, and keeps a spell only when the on-list bar is inside that clock. The 10:00–11:00 clock is the champion and is not retested. Costs: US$2,120, tiered commissions, hard stop, flat by 15:55. Slippage is 2 bp except where a liquidity rule adds a spread or an impact. Bonferroni denominator, including these fifteen ids: 48. The holdout from 2026-04-01 was not opened. Look count remains 2. `models/ACTIVE` stays `v0.1`. No checkpoint was issued.

Rules are in `research/GATE.md`. A window win needs at least 20 challenger trades and a better net, a better dollar expectancy, and a better per-trade basis-point expectancy than the champion. 2026Q1 is inside the pooled sample and is not its own vote. An empty book does not beat a loss, so a Kelly fraction of zero is a rejection, not a live rule that trades nothing.

| Candidate | Area | Pooled challenger | Windows | Bootstrap p | Permutation p | Decision |
| --- | --- | --- | ---: | ---: | ---: | --- |
| sz_risk_1pct | position_sizing | $-1477 on 1243 trades, -16.5 bp | 4/12 | 0.5271 | 0.5483 | REJECTED |
| sz_risk_half_pct | position_sizing | $-1480 on 1342 trades, -18.1 bp | 0/12 | 0.5379 | 0.5365 | REJECTED |
| sz_one_position | position_sizing | $-1420 on 1115 trades, -11.5 bp | 0/12 | 0.0004 | 0.0002 | REJECTED |
| sz_daily_stop | position_sizing | $-1339 on 1057 trades, -16.9 bp | 3/12 | 0.0056 | 0.0068 | REJECTED |
| sz_kelly_cap | position_sizing | $0 on 0 trades, n/a | 0/12 | 0.0002 | 0.0002 | REJECTED |
| tod_open | time_of_day | $-657 on 517 trades, -13.2 bp | 4/12 | 0.0002 | 0.0002 | REJECTED |
| tod_midday | time_of_day | $-1999 on 1876 trades, -27.6 bp | 0/12 | 0.9992 | 0.9988 | REJECTED |
| tod_afternoon | time_of_day | $-1859 on 1719 trades, -21.7 bp | 0/12 | 0.9836 | 0.9786 | REJECTED |
| tod_last_hour | time_of_day | $-1280 on 1095 trades, -15.7 bp | 6/12 | 0.1236 | 0.1208 | REJECTED |
| liq_half_spread | liquidity | $-1901 on 1056 trades, -32.3 bp | 0/12 | 1.0000 | 1.0000 | REJECTED |
| liq_participation | liquidity | $-1518 on 1207 trades, -17.7 bp | 0/12 | 0.9974 | 0.9982 | REJECTED |
| liq_dvol | liquidity | $-1475 on 1234 trades, -16.8 bp | 0/12 | 1.0000 | 1.0000 | REJECTED |
| reg_spy_vwap | market_regime | $-931 on 751 trades, -14.2 bp | 4/12 | 0.0002 | 0.0002 | REJECTED |
| reg_high_range | market_regime | $-1219 on 923 trades, -16.4 bp | 1/12 | 0.0004 | 0.0002 | REJECTED |
| reg_falling_tape | market_regime | $-1257 on 1025 trades, -14.0 bp | 4/12 | 0.0002 | 0.0004 | REJECTED |

### sz_risk_1pct

**Area.** position_sizing.

**Source.** Kelly (1956), Bell System Technical Journal; Thorp, fractional Kelly. Fixed-fractional risk is the retail cap used here, not a fitted Kelly fraction. Vince optimal-f is the aggressive cousin and is not searched.

**Hypothesis.** Risking 1% of current equity to the stop, in whole shares, loses less to a single gap than a full US$2,120 ticket and still clears the minimum commission.

**Economic rationale.** On a US$2,120 account one full ticket is often the whole account. A stop a few dollars under a US$100 name can remove several percent of equity, and the US$0.35 minimum is already a few basis points on a two-share fill. Capping the loss at 1% of equity (cash plus open cost) keeps a gap from dominating the book. The other side of a too-small fill is the minimum commission, which the whole-share round-down does not waive.

**Test setup.** Same midmorning spells. risk_fraction=0.01. Shares = floor(equity × 0.01 / (slipped entry − stop)), then reduced until notional plus the buy commission fits cash. Skip when that is under one share.

**Sample note.** Same midmorning signals. Only the size or the daily stop changes.

**Walk-forward.** Challenger $-1477 on 1243 trades, -16.5 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 172 | $-257 | -18.0 bp | yes |
| 2023H2 | 214 | $-306 | -19.2 bp | yes |
| 2024H1 | 211 | $-259 | -14.3 bp | yes |
| 2024H2 | 170 | $-140 | -9.8 bp | yes |
| 2025H1 | 165 | $-188 | -16.8 bp | yes |
| 2025H2 | 221 | $-237 | -18.1 bp | yes |
| 2026Q1 | 90 | $-91 | -20.4 bp | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1477 on 1243 trades, $-1.19/trade, -16.5 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, low_vol). Does not beat the champion in every ticker group (megacap). Beats the champion in 1 half-year; need at least 2. Improves in 4 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2023-03-10, 2024-08-14, 2026-02-06, 2025-04-11, 2026-02-10), the challenger is behind on net, dollars per trade (challenger $-1483 on 1230 trades, $-1.21/trade, -16.6 bp; champion $-1459 on 1220 trades, $-1.20/trade, -16.7 bp). Paired tests do not clear the Bonferroni line for 48 ideas tried (bootstrap p=0.5271, permutation p=0.5483, alpha=0.00104). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### sz_risk_half_pct

**Area.** position_sizing.

**Source.** Same as sz_risk_1pct. The live stop is already about one ATR, so 0.5% of equity per stop distance is the volatility-scaled cousin of the 1% rule. Both fractions were written down together. Neither is chosen because it lost less.

**Hypothesis.** Risking 0.5% of equity to the same stop is small enough that one loss cannot move the account, and large enough that the US$0.35 minimum does not take the whole edge on a typical mega-cap print.

**Economic rationale.** Half a percent is the pre-registered tighter cap. It is not a second look at the 1% result. If the champion's edge is negative, a smaller bet loses fewer dollars and can still lose on a per-trade basis once the minimum commission binds. The gate requires a better dollar total and a better per-trade expectancy, so shrinking a losing book is not by itself an improvement.

**Test setup.** Same midmorning spells. risk_fraction=0.005. Same whole-share and cash cap as the 1% rule.

**Sample note.** Same midmorning signals. Only the size or the daily stop changes.

**Walk-forward.** Challenger $-1480 on 1342 trades, -18.1 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 205 | $-271 | -21.1 bp | yes |
| 2023H2 | 237 | $-313 | -16.4 bp | yes |
| 2024H1 | 241 | $-271 | -16.2 bp | yes |
| 2024H2 | 184 | $-136 | -12.4 bp | yes |
| 2025H1 | 169 | $-182 | -18.9 bp | yes |
| 2025H2 | 216 | $-214 | -20.0 bp | yes |
| 2026Q1 | 90 | $-94 | -26.2 bp | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1480 on 1342 trades, $-1.10/trade, -18.1 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Beats the champion in 0 half-years; need at least 2. Improves in 0 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2023-03-20, 2023-01-26, 2024-08-14, 2024-07-01, 2023-08-07), the challenger is behind on net, basis points per trade (challenger $-1451 on 1325 trades, $-1.10/trade, -17.9 bp; champion $-1394 on 1223 trades, $-1.14/trade, -16.6 bp). Paired tests do not clear the Bonferroni line for 48 ideas tried (bootstrap p=0.5379, permutation p=0.5365, alpha=0.00104). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### sz_one_position

**Area.** position_sizing.

**Source.** Concentration and gap risk on a cash account that cannot borrow. One open long is the tightest concurrent-position cap.

**Hypothesis.** Allowing only one open position removes the case where several names gap through their stops together and the cash account cannot fund the later, better signal.

**Economic rationale.** The champion spends remaining cash on every new name. Two or three mega-caps can each gap through a stop in the same bar. A one-position book gives up later signals in exchange for a smaller overnight-style intraday gap. Alphabetical order still breaks ties, matching the champion.

**Test setup.** Same midmorning spells and full-ticket size. max_concurrent=1. A name is skipped while another fill is still open.

**Sample note.** Same midmorning signals. Only the size or the daily stop changes.

**Walk-forward.** Challenger $-1420 on 1115 trades, -11.5 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 149 | $-239 | -8.3 bp | yes |
| 2023H2 | 186 | $-284 | -9.3 bp | yes |
| 2024H1 | 184 | $-248 | -10.0 bp | yes |
| 2024H2 | 157 | $-150 | -8.2 bp | yes |
| 2025H1 | 146 | $-182 | -12.7 bp | yes |
| 2025H2 | 201 | $-215 | -15.1 bp | yes |
| 2026Q1 | 92 | $-103 | -20.0 bp | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1420 on 1115 trades, $-1.27/trade, -11.5 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Beats the champion in 0 half-years; need at least 2. Improves in 0 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2024-02-06, 2025-01-29, 2024-03-13, 2025-11-12, 2024-06-04), the challenger is behind on dollars per trade (challenger $-1425 on 1101 trades, $-1.29/trade, -11.6 bp; champion $-1466 on 1207 trades, $-1.21/trade, -16.6 bp). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### sz_daily_stop

**Area.** position_sizing.

**Source.** A daily loss limit is a hard risk budget, not a signal. The consecutive-loss stop is the same idea in trade counts. Both reset the next session and were fixed before the run.

**Hypothesis.** Stopping for the day after a 1% realized loss, or after two consecutive losing fills, avoids a session where the tape has already gone against every dip.

**Economic rationale.** If the morning is a one-way offer, later dip buys are the same informed seller. A 1% equity stop and a two-loss stop are crude ways to stand aside without fitting a new indicator. Realized losses count; an open trade does not trip the stop until it closes. A winner resets the consecutive-loss count. Neither threshold is moved after the run.

**Test setup.** Same midmorning spells and full-ticket size. daily_loss_fraction=0.01 of that session's starting equity, or max_consecutive_losses=2. Both reset the next session.

**Sample note.** Same midmorning signals. Only the size or the daily stop changes.

**Walk-forward.** Challenger $-1339 on 1057 trades, -16.9 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 145 | $-291 | -24.2 bp | yes |
| 2023H2 | 179 | $-219 | -19.1 bp | yes |
| 2024H1 | 171 | $-228 | -14.7 bp | yes |
| 2024H2 | 149 | $-134 | -10.4 bp | yes |
| 2025H1 | 145 | $-190 | -16.7 bp | yes |
| 2025H2 | 184 | $-175 | -15.3 bp | yes |
| 2026Q1 | 84 | $-102 | -19.6 bp | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1339 on 1057 trades, $-1.27/trade, -16.9 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol). Does not beat the champion in every ticker group (megacap, high_beta). Improves in 3 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2023-08-07, 2023-03-01, 2024-11-14, 2023-11-30, 2023-04-11), the challenger is behind on dollars per trade, basis points per trade (challenger $-1300 on 1046 trades, $-1.24/trade, -16.6 bp; champion $-1382 on 1216 trades, $-1.14/trade, -16.3 bp). Paired tests do not clear the Bonferroni line for 48 ideas tried (bootstrap p=0.0056, permutation p=0.0068, alpha=0.00104). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### sz_kelly_cap

**Area.** position_sizing.

**Source.** Kelly (1956); Thorp on fractional Kelly. The cap at one quarter is the pre-registered fractional-Kelly limit. It is not estimated from the holdout.

**Hypothesis.** A fractional Kelly fraction, estimated only from earlier full-ticket champion trades and capped at 25% of equity, bets more only when that past sample has a positive mean.

**Economic rationale.** Kelly's fraction is mean over variance. A negative mean is a zero bet: the formula says the game is not worth playing. That is the economic content. An empty book does not beat a losing champion on the gate, because an empty book has no trades. Standing aside is reported as a rejection, not adopted as a live rule that trades nothing. The estimator uses full-ticket returns so the US$0.35 minimum is in the same units as the live book. Fewer than 80 prior trades also bets nothing.

**Test setup.** invest_fraction = min(0.25, mean/variance) from champion trades whose session is strictly before the new entry day. f* <= 0 or fewer than 80 prior trades sets invest_fraction to 0 and the spell is skipped. Whole shares, cash cap unchanged.

**Sample note.** Kelly uses full-ticket champion returns from earlier sessions only, needs 80 of them, and caps f* at 25%. 0 of 1799 spells had f* > 0.

**Walk-forward.** Challenger $0 on 0 trades, n/a. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 0 | $0 | n/a | yes |
| 2023H2 | 0 | $0 | n/a | yes |
| 2024H1 | 0 | $0 | n/a | yes |
| 2024H2 | 0 | $0 | n/a | yes |
| 2025H1 | 0 | $0 | n/a | yes |
| 2025H2 | 0 | $0 | n/a | yes |
| 2026Q1 | 0 | $0 | n/a | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $0 on 0 trades, n/a, n/a; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Beats the champion in 0 half-years; need at least 2. Improves in 0 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2023-01-26, 2023-04-11, 2023-02-09, 2023-08-07, 2023-07-21), the challenger is behind on net, dollars per trade, and basis points per trade (challenger $0 on 0 trades, n/a, n/a; champion $-1350 on 1220 trades, $-1.11/trade, -16.5 bp). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### tod_open

**Area.** time_of_day.

**Source.** Admati and Pfleiderer (1988), Review of Financial Studies, volume and informed flow at the open and the close; Gao, Han, Li and Zhou, Journal of Financial Economics 2018, DOI 10.1016/j.jfineco.2018.05.009; Heston, Korajczyk and Sadka, Journal of Finance 2010, DOI 10.1111/j.1540-6261.2010.01573.x.

**Hypothesis.** Appearances from 9:45 to 10:30 have a different cost-inclusive edge from the rest of the day because the open concentrates volume.

**Economic rationale.** The open is when overnight inventory is unwound. Gao's first-half-hour pattern was already tested as its own trade and rejected; this overlay only asks whether the existing list is less bad in that window. The scorer drops the first 15 minutes, so 9:30–9:45 is empty on purpose and is not a missing file. The live 10:00–11:00 window is the champion and is not a challenger.

**Test setup.** Same confirm, exit lag, and stop as the live rule. Keep a spell only when the on-list bar is in [9:45, 10:30). The fill is still the next bar's open, which can fall a bar outside the window. Exit is still disappearance or 15:55.

**Sample note.** On-list bar in [585, 630) minutes from midnight. 712 of 11116 appearances.

**Walk-forward.** Challenger $-657 on 517 trades, -13.2 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 74 | $-100 | -19.2 bp | yes |
| 2023H2 | 84 | $-98 | -15.3 bp | yes |
| 2024H1 | 89 | $-114 | -13.5 bp | yes |
| 2024H2 | 65 | $-88 | -8.8 bp | yes |
| 2025H1 | 68 | $-77 | -13.9 bp | yes |
| 2025H2 | 99 | $-126 | -8.8 bp | yes |
| 2026Q1 | 38 | $-55 | -13.9 bp | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-657 on 517 trades, $-1.27/trade, -13.2 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol). Does not beat the champion in every ticker group (high_beta). Improves in 4 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2023-02-10, 2023-03-01, 2023-01-26, 2023-03-21, 2025-02-07), the challenger is behind on dollars per trade (challenger $-644 on 515 trades, $-1.25/trade, -13.1 bp; champion $-1375 on 1220 trades, $-1.13/trade, -16.4 bp). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### tod_midday

**Area.** time_of_day.

**Source.** Heston, Korajczyk and Sadka (2010), same-clock half-hour patterns; Admati and Pfleiderer (1988) on the midday lull in volume.

**Hypothesis.** Appearances from 11:00 to 13:00 are the quiet-tape book, and either pay after costs or are no better than the champion.

**Economic rationale.** Midday volume is thinner, so a listed dip is more likely a lack of bids than an informed buyer. If that is the case the window should not be adopted. The comparison is the champion's 10:00–11:00 book, not a search for the least-negative clock.

**Test setup.** On-list bar in [11:00, 13:00). Same confirm, exit lag, stop, and disappearance exit.

**Sample note.** On-list bar in [660, 780) minutes from midnight. 4844 of 11116 appearances.

**Walk-forward.** Challenger $-1999 on 1876 trades, -27.6 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 451 | $-631 | -23.5 bp | yes |
| 2023H2 | 454 | $-470 | -19.4 bp | yes |
| 2024H1 | 489 | $-510 | -22.9 bp | yes |
| 2024H2 | 366 | $-305 | -37.9 bp | yes |
| 2025H1 | 116 | $-83 | -62.3 bp | yes |
| 2025H2 | 0 | $0 | n/a | yes |
| 2026Q1 | 0 | $0 | n/a | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1999 on 1876 trades, $-1.07/trade, -27.6 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Beats the champion in 0 half-years; need at least 2. Improves in 0 of 12 windows; need at least 9 (75%). Severe regression in 2023H1: net is $379 worse than the champion, past the $212 limit. Severe regression in 2024H1: net is $250 worse than the champion, past the $212 limit. Severe regression in 2024H2: expectancy is 27.5 bp worse than the champion, past the 15 bp limit. Severe regression in 2025H1: expectancy is 47.0 bp worse than the champion, past the 15 bp limit. Severe regression in up: net is $233 worse than the champion, past the $212 limit. Severe regression in down: net is $291 worse than the champion, past the $212 limit. Severe regression in high_vol: net is $257 worse than the champion, past the $212 limit. Severe regression in low_vol: net is $267 worse than the champion, past the $212 limit. Severe regression in high_beta: net is $432 worse than the champion, past the $212 limit. After removing the top 5 days by daily gap (2023-01-26, 2023-03-01, 2023-02-09, 2023-08-07, 2024-08-06), the challenger is behind on net, basis points per trade (challenger $-1985 on 1857 trades, $-1.07/trade, -27.6 bp; champion $-1360 on 1219 trades, $-1.12/trade, -16.4 bp). Paired tests do not clear the Bonferroni line for 48 ideas tried (bootstrap p=0.9992, permutation p=0.9988, alpha=0.00104). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### tod_afternoon

**Area.** time_of_day.

**Source.** Heston, Korajczyk and Sadka (2010). Afternoon half-hours are a different clock from the open and from the last hour.

**Hypothesis.** Appearances from 13:00 to 14:30 carry the same list edge without the open's inventory shock or the close's hedging flow.

**Economic rationale.** A window that is merely less negative than another losing window is not a promotion. It has to beat the champion on net and on expectancy in the gate's windows. This clock was written down with the others and is not a fallback if the open fails.

**Test setup.** On-list bar in [13:00, 14:30). Same confirm, exit lag, stop, and disappearance exit.

**Sample note.** On-list bar in [780, 870) minutes from midnight. 2896 of 11116 appearances.

**Walk-forward.** Challenger $-1859 on 1719 trades, -21.7 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 275 | $-340 | -23.6 bp | yes |
| 2023H2 | 274 | $-350 | -18.7 bp | yes |
| 2024H1 | 322 | $-341 | -16.0 bp | yes |
| 2024H2 | 283 | $-326 | -19.0 bp | yes |
| 2025H1 | 246 | $-229 | -21.3 bp | yes |
| 2025H2 | 225 | $-199 | -29.4 bp | yes |
| 2026Q1 | 94 | $-74 | -36.0 bp | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1859 on 1719 trades, $-1.08/trade, -21.7 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Beats the champion in 0 half-years; need at least 2. Improves in 0 of 12 windows; need at least 9 (75%). Severe regression in down: net is $303 worse than the champion, past the $212 limit. Severe regression in low_vol: net is $260 worse than the champion, past the $212 limit. Severe regression in high_beta: net is $215 worse than the champion, past the $212 limit. After removing the top 5 days by daily gap (2023-01-26, 2023-04-11, 2023-07-21, 2023-07-10, 2023-08-07), the challenger is behind on net, basis points per trade (challenger $-1884 on 1702 trades, $-1.11/trade, -21.9 bp; champion $-1360 on 1218 trades, $-1.12/trade, -16.3 bp). Paired tests do not clear the Bonferroni line for 48 ideas tried (bootstrap p=0.9836, permutation p=0.9786, alpha=0.00104). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### tod_last_hour

**Area.** time_of_day.

**Source.** Gao, Han, Li and Zhou (2018), last-half-hour return; Admati and Pfleiderer (1988), volume at the close. The live book is flat by 15:55 and does not trade the closing auction.

**Hypothesis.** Appearances from 14:30 to 15:30 still have time to exit on a disappearance or the 15:55 flat, and the close's volume is enough to pay the ticket.

**Economic rationale.** The published last-half-hour effect is a long into the auction. This book is flat before the auction, so the economic claim is weaker: only that a late appearance of the same dip is a better or worse trade than a midmorning one. The scorer also drops the last 15 minutes, so the window stops at 15:30.

**Test setup.** On-list bar in [14:30, 15:30). Same confirm, exit lag, stop, and disappearance or 15:55 flat.

**Sample note.** On-list bar in [870, 930) minutes from midnight. 1577 of 11116 appearances.

**Walk-forward.** Challenger $-1280 on 1095 trades, -15.7 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 157 | $-278 | -26.7 bp | yes |
| 2023H2 | 175 | $-193 | -17.3 bp | yes |
| 2024H1 | 172 | $-167 | -11.9 bp | yes |
| 2024H2 | 149 | $-204 | -13.5 bp | yes |
| 2025H1 | 162 | $-166 | -12.6 bp | yes |
| 2025H2 | 186 | $-176 | -12.8 bp | yes |
| 2026Q1 | 94 | $-95 | -15.8 bp | no |

**Decision.** Rejected. Does not beat the champion in every market regime (up, down, high_vol). Does not beat the champion in every ticker group (high_beta). Improves in 6 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2023-01-26, 2023-02-09, 2023-04-11, 2023-10-25, 2023-03-01), the challenger is behind on dollars per trade (challenger $-1279 on 1085 trades, $-1.18/trade, -15.4 bp; champion $-1355 on 1218 trades, $-1.11/trade, -16.4 bp). Paired tests do not clear the Bonferroni line for 48 ideas tried (bootstrap p=0.1236, permutation p=0.1208, alpha=0.00104). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### liq_half_spread

**Area.** liquidity.

**Source.** Corwin and Schultz, Journal of Finance 2012, DOI 10.1111/j.1540-6261.2011.01694.x. These files are OHLC, not quotes, so the two-bar high-low estimator stands in for the spread.

**Hypothesis.** Adding half the estimated spread to the 2 bp slippage removes trades whose edge was only an ignored bid-ask bounce, or shows that the spread is too small to matter next to the commission.

**Economic rationale.** A marketable buy pays the half-spread on top of any delay. If the expected rebound is a few basis points and the spread is wider than that, the fill erases it. The estimator returns zero when alpha is non-positive, and zero when the entry bar has no previous bar. It is not a quote, and a zero is not evidence that the spread was zero.

**Test setup.** slip_bps = 2 + half the Corwin-Schultz spread in basis points, from the entry bar and the previous bar. Same midmorning signals and full-ticket size.

**Sample note.** Mean extra slippage 4.494 bp. 0 spells had no previous bar and kept a zero spread.

**Walk-forward.** Challenger $-1901 on 1056 trades, -32.3 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 165 | $-530 | -31.7 bp | yes |
| 2023H2 | 205 | $-480 | -26.6 bp | yes |
| 2024H1 | 216 | $-353 | -29.4 bp | yes |
| 2024H2 | 166 | $-220 | -27.5 bp | yes |
| 2025H1 | 145 | $-176 | -38.9 bp | yes |
| 2025H2 | 122 | $-109 | -42.8 bp | yes |
| 2026Q1 | 37 | $-34 | -45.6 bp | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1901 on 1056 trades, $-1.80/trade, -32.3 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Beats the champion in 0 half-years; need at least 2. Improves in 0 of 12 windows; need at least 9 (75%). Severe regression in 2023H1: net is $278 worse than the champion, past the $212 limit. Severe regression in 2024H2: expectancy is 17.1 bp worse than the champion, past the 15 bp limit. Severe regression in 2025H1: expectancy is 23.6 bp worse than the champion, past the 15 bp limit. Severe regression in 2025H2: expectancy is 25.5 bp worse than the champion, past the 15 bp limit. Severe regression in up: net is $322 worse than the champion, past the $212 limit. Severe regression in down: expectancy is 15.3 bp worse than the champion, past the 15 bp limit. Severe regression in high_vol: net is $281 worse than the champion, past the $212 limit. Severe regression in low_vol: expectancy is 15.5 bp worse than the champion, past the 15 bp limit. Severe regression in high_beta: net is $354 worse than the champion, past the $212 limit. After removing the top 5 days by daily gap (2026-01-02, 2025-12-04, 2024-11-14, 2025-02-25, 2025-02-07), the challenger is behind on net, dollars per trade, basis points per trade (challenger $-1881 on 1047 trades, $-1.80/trade, -32.1 bp; champion $-1416 on 1218 trades, $-1.16/trade, -16.4 bp). Paired tests do not clear the Bonferroni line for 48 ideas tried (bootstrap p=1.0000, permutation p=1.0000, alpha=0.00104). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### liq_participation

**Area.** liquidity.

**Source.** Kyle, Econometrica 1985; Almgren, Thum, Hauptmann and Li, Risk 2005, square-root impact.

**Hypothesis.** Impact of a US$2,120 ticket in a mega-cap 5-minute bar is a fraction of a basis point, so the US$0.35 minimum, not participation, is the binding friction.

**Economic rationale.** Temporary impact in the square-root model scales with volatility times the square root of order size over volume. A two-thousand-dollar order against tens of millions of dollars in a 5-minute bar is invisible. Charging it anyway is the test. If the mean impact is far below the minimum commission, a participation filter will not create an edge.

**Test setup.** impact_bps = 10000 × ((open − stop) / open) × sqrt(notional / entry-bar dollar volume), notional = floor(2120 / price) × price. slip_bps = 2 + impact. Missing volume skips the spell.

**Sample note.** Skipped 0 of 1799 spells with no dollar volume. Mean square-root impact 0.266 bp.

**Walk-forward.** Challenger $-1518 on 1207 trades, -17.7 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 169 | $-273 | -21.3 bp | yes |
| 2023H2 | 208 | $-314 | -19.8 bp | yes |
| 2024H1 | 213 | $-273 | -17.1 bp | yes |
| 2024H2 | 163 | $-159 | -10.4 bp | yes |
| 2025H1 | 157 | $-185 | -16.6 bp | yes |
| 2025H2 | 213 | $-221 | -17.4 bp | yes |
| 2026Q1 | 84 | $-92 | -23.4 bp | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1518 on 1207 trades, $-1.26/trade, -17.7 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Beats the champion in 0 half-years; need at least 2. Improves in 0 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2026-02-10, 2026-02-06, 2026-02-09, 2025-11-12, 2025-01-29), the challenger is behind on net, dollars per trade, basis points per trade (challenger $-1514 on 1200 trades, $-1.26/trade, -17.7 bp; champion $-1454 on 1218 trades, $-1.19/trade, -16.6 bp). Paired tests do not clear the Bonferroni line for 48 ideas tried (bootstrap p=0.9974, permutation p=0.9982, alpha=0.00104). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### liq_dvol

**Area.** liquidity.

**Source.** Kyle (1985). A dollar-volume floor is a crude participation limit when the spread itself is not observed.

**Hypothesis.** Skipping an entry bar under US$5,000,000 of dollar volume drops names where a small ticket could still move the print, and does nothing on bars that already trade far more than that.

**Economic rationale.** These eight names often print tens of millions of dollars in a 5-minute bar. A US$5,000,000 floor was frozen as a level that can bind on a quiet bar without being fit to the result. A filter that drops nothing matches the champion and is not an improvement. Missing volume skips the spell.

**Test setup.** Keep the spell only when entry-bar volume × close is at least US$5,000,000. Same size and 2 bp slippage otherwise.

**Sample note.** Entry-bar dollar volume at least $5,000,000. Kept 1799 of 1799.

**Walk-forward.** Challenger $-1475 on 1234 trades, -16.8 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 168 | $-251 | -19.1 bp | yes |
| 2023H2 | 212 | $-303 | -20.5 bp | yes |
| 2024H1 | 214 | $-261 | -15.0 bp | yes |
| 2024H2 | 168 | $-150 | -10.4 bp | yes |
| 2025H1 | 161 | $-186 | -15.2 bp | yes |
| 2025H2 | 217 | $-222 | -17.3 bp | yes |
| 2026Q1 | 94 | $-102 | -21.6 bp | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1475 on 1234 trades, $-1.20/trade, -16.8 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Beats the champion in 0 half-years; need at least 2. Improves in 0 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2023-01-03, 2023-01-04, 2023-01-05, 2023-01-06, 2023-01-09), the challenger is behind on net, dollars per trade, basis points per trade (challenger $-1498 on 1228 trades, $-1.22/trade, -17.0 bp; champion $-1498 on 1228 trades, $-1.22/trade, -17.0 bp). Paired tests do not clear the Bonferroni line for 48 ideas tried (bootstrap p=1.0000, permutation p=1.0000, alpha=0.00104). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### reg_spy_vwap

**Area.** market_regime.

**Source.** Berkowitz, Logue and Noser, Journal of Finance 1988, VWAP as the execution benchmark. The list is a dip in a single name.

**Hypothesis.** A long dip while SPY itself is offered under its session VWAP is a bid into a market that is already being sold, and should be skipped.

**Economic rationale.** The other side of a name trading under VWAP, while the index is also under VWAP, is more likely an index seller than a buyer of that name. Taking the dip only when SPY has reclaimed VWAP asks for the index bid to be present. The comparison uses the SPY bar at or before the on-list minute, so the fill one bar later is not in the signal. A missing SPY day skips the spell.

**Test setup.** Take the long only when the SPY close at or before the on-list bar is at or above the session VWAP of typical price × volume from 9:30 through that bar.

**Sample note.** Took 1013. Stood aside 786 under VWAP. Skipped 0 with no SPY bar.

**Walk-forward.** Challenger $-931 on 751 trades, -14.2 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 110 | $-165 | -24.4 bp | yes |
| 2023H2 | 122 | $-169 | -16.9 bp | yes |
| 2024H1 | 124 | $-179 | -12.8 bp | yes |
| 2024H2 | 112 | $-85 | -8.0 bp | yes |
| 2025H1 | 97 | $-126 | -11.8 bp | yes |
| 2025H2 | 120 | $-132 | -10.8 bp | yes |
| 2026Q1 | 66 | $-76 | -14.7 bp | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-931 on 751 trades, $-1.24/trade, -14.2 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, low_vol). Does not beat the champion in every ticker group (megacap). Improves in 4 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2023-02-09, 2023-01-26, 2023-03-21, 2025-02-07, 2024-09-10), the challenger is behind on dollars per trade (challenger $-911 on 750 trades, $-1.21/trade, -14.1 bp; champion $-1367 on 1222 trades, $-1.12/trade, -16.4 bp). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### reg_high_range

**Area.** market_regime.

**Source.** Grossman and Miller, Journal of Finance 1988, inventory risk after a large move. Wilder (1978) ADX is the practitioner cousin and is not used: the smoothing length would be another search.

**Hypothesis.** After a prior SPY day in the top quartile of recent ranges, the next open is a gap risk the US$2,120 account should not take.

**Economic rationale.** A wide prior day leaves dealers with inventory and leaves stops closer to the open. Standing aside is the pre-registered response. The 75th percentile of the previous 60 sessions is one frozen split. It is not refit inside a half-year, and it is not flipped to 'only trade wide days' if this direction loses. Fewer than 60 prior sessions means do not trade.

**Test setup.** Stand aside when yesterday's SPY (high − low) / close is at or above the 75th percentile of the previous 60 sessions, or when those 60 sessions do not exist yet.

**Sample note.** Stood aside 415 of 1799 after a wide prior SPY day, or before 60 prior sessions existed.

**Walk-forward.** Challenger $-1219 on 923 trades, -16.4 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 146 | $-271 | -22.5 bp | yes |
| 2023H2 | 169 | $-224 | -20.6 bp | yes |
| 2024H1 | 152 | $-209 | -15.9 bp | yes |
| 2024H2 | 116 | $-81 | -5.7 bp | yes |
| 2025H1 | 115 | $-144 | -14.1 bp | yes |
| 2025H2 | 166 | $-195 | -14.3 bp | yes |
| 2026Q1 | 59 | $-95 | -21.6 bp | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1219 on 923 trades, $-1.32/trade, -16.4 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, down, high_vol, low_vol). Does not beat the champion in every ticker group (megacap, high_beta). Beats the champion in 1 half-year; need at least 2. Improves in 1 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2023-08-07, 2024-08-06, 2024-04-19, 2023-09-27, 2024-07-01), the challenger is behind on dollars per trade (challenger $-1219 on 923 trades, $-1.32/trade, -16.4 bp; champion $-1397 on 1217 trades, $-1.15/trade, -16.5 bp). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

### reg_falling_tape

**Area.** market_regime.

**Source.** Kyle (1985): an informed seller makes the bid toxic. The −0.30% open-to-signal drop is frozen and is not the live scorer's −0.22% six-bar gate.

**Hypothesis.** Skipping the list when SPY is already down 0.30% from the 9:30 open to the on-list bar avoids buying a dip while the index seller is still active.

**Economic rationale.** A single-name pullback in a falling index is often the same trade as the index. The threshold is −0.30% from today's open, known at the on-list bar and before the next-bar fill. It was not chosen by looking at which side of zero lost less. The rule stands aside in that state and does not flip to short. A missing SPY day skips the spell.

**Test setup.** Stand aside when SPY close at the on-list bar / SPY 9:30 open − 1 is at or below −0.003. Otherwise the champion spell is unchanged.

**Sample note.** Took 1476. Stood aside 323 when SPY was down 0.30% or more from the open. Skipped 0 with no SPY bar.

**Walk-forward.** Challenger $-1257 on 1025 trades, -14.0 bp. Champion $-1475 on 1234 trades, -16.8 bp ($-1.20/trade).

Half-years are votes. 2026Q1 is reported and is not a vote.

| Fold | Trades | Net | Avg | Vote |
| --- | ---: | ---: | ---: | --- |
| 2023H1 | 130 | $-195 | -14.4 bp | yes |
| 2023H2 | 182 | $-243 | -18.7 bp | yes |
| 2024H1 | 181 | $-249 | -13.5 bp | yes |
| 2024H2 | 142 | $-144 | -8.4 bp | yes |
| 2025H1 | 129 | $-128 | -11.3 bp | yes |
| 2025H2 | 188 | $-208 | -14.1 bp | yes |
| 2026Q1 | 73 | $-89 | -18.4 bp | no |

**Decision.** Rejected. Pooled sample does not beat the champion on net and expectancy (challenger $-1257 on 1025 trades, $-1.23/trade, -14.0 bp; champion $-1475 on 1234 trades, $-1.20/trade, -16.8 bp). Does not beat the champion in every market regime (up, high_vol, low_vol). Does not beat the champion in every ticker group (megacap). Improves in 4 of 12 windows; need at least 9 (75%). After removing the top 5 days by daily gap (2025-02-07, 2023-08-02, 2023-05-12, 2024-04-17, 2023-08-08), the challenger is behind on dollars per trade (challenger $-1257 on 1025 trades, $-1.23/trade, -14.0 bp; champion $-1405 on 1217 trades, $-1.15/trade, -16.1 bp). Fresh out-of-sample slice was not read. It opens only when this challenger is the only one that has already passed the walk-forward and consistency bars. The holdout was not read.

**Holdout.** Not checked in this batch.

<!-- AREAS_END -->
