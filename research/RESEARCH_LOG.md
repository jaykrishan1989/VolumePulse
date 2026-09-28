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
