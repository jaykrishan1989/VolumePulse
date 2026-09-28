# Promotion gate

The live champion is the appear-to-disappear rule frozen at 10:00–11:00 ET (`appear_disappear_midmorning`, `app/signal_rule.json`). It is replaced only when one challenger passes every bar in this file. One good backtest is not a promotion. A failed bar is logged as rejected in `research/RESEARCH_LOG.md` and the champion file is left as it is.

The same bars apply to a new research idea and to a threshold tweak. A tweak is a new challenger id with its thresholds written down before the run. It is not a silent edit of the champion.

Costs on every comparison: US$2,120, whole shares, concurrent while cash remains, tiered IBKR commissions (US$0.35 minimum per side), 2 bp slippage each side, hard stop on, flat by the close of the 15:50 bar. Dollar net is the sum of those fills. Expectancy is the mean net per trade, in dollars and in basis points. "Better" means strictly better on all three: net dollars, dollars per trade, and basis points per trade.

Nothing in this gate places an order.

## Sample

Walk-forward and consistency use sessions from 2023-01-01 through 2026-03-31. The paired tests line both books up on the SPY session calendar. A session with no fill is a zero. Trades off that calendar are dropped from the comparison.

The fresh slice is the locked holdout from 2026-04-01 onward. It is not loaded for a batch. It is read once, and only after exactly one challenger has already passed the walk-forward bar and the consistency bar alone. That read is a new row in `research/holdout_looks.csv`. Two challengers clearing the earlier bars at once do not open it: the holdout is not a way to choose between them.

## Voting windows

Twelve windows. A year is not a separate vote, because it is the sum of its halves. The partial quarter 2026Q1 stays inside the pooled sample and is not a vote.

| Family | Windows |
| --- | --- |
| Half-year | 2023H1, 2023H2, 2024H1, 2024H2, 2025H1, 2025H2 |
| Regime | up, down, high vol, low vol |
| Ticker group | megacap (AAPL, MSFT, GOOGL, AMZN, META), high beta (NVDA, AMD, TSLA) |

A window is a win only when the challenger has at least 20 trades in it and is better on net, dollars per trade, and basis points per trade. Fewer than 20 trades is not a win. An empty book does not beat a loss.

Regimes come from SPY, not from the traded name. Up means that session's close is above the prior session's close. Down is every other labeled session. Volatility is the sample standard deviation of the previous 20 close-to-close returns, so the label is known before the open. High vol is a trailing vol at or above the median of those labels on the comparison sample; low vol is the rest. The median is one split for the whole sample. It is not refit inside a half-year and it is not a trading threshold. Sessions without 20 prior returns are left out of the vol windows.

Group P&L is the sum of the fills in that group after the shared cash account has already decided which names were funded. It is not a second account.

## Bar 1 — walk-forward, regimes, and groups

All of these have to be true:

- On the pooled sample, the challenger is better on net, dollars per trade, and basis points per trade.
- The challenger wins the up window and the down window.
- The challenger wins the high-vol window and the low-vol window.
- The challenger wins both ticker groups.
- The challenger wins at least two of the six half-years.

Beating the champion in aggregate and missing a regime or a group fails the bar.

## Bar 2 — fresh out-of-sample slice

On the holdout, the challenger needs at least 20 trades and has to be better on net, dollars per trade, and basis points per trade. This bar is a fail when the slice was not read. Leaving it closed is how a batch avoids spending a holdout look.

## Bar 3 — consistency

All of these have to be true on the pre-holdout sample:

- The challenger wins at least 75% of the twelve windows. 75% of 12 is 9, so nine wins are required. The count is `ceil(0.75 × windows)`.
- No severe regression in any of the twelve windows. Severe means the challenger's net is more than US$212 worse than the champion in that window (10% of the US$2,120 account), or, when both sides have at least one trade, its per-trade basis-point expectancy is more than 15 bp worse.
- The edge is not a handful of days. Drop the five sessions with the largest daily dollar gap (challenger minus champion). On what remains, the challenger still has to be better on net, dollars per trade, and basis points per trade.
- The mean daily dollar gap is greater than zero on two paired tests, and both p-values have to sit under the Bonferroni line. The bootstrap p-value is the share of resampled daily-gap sums that are <= 0. The permutation p-value is a sign flip: the share of randomly signed sums that are at least as large as the observed sum. Both use add-one smoothing, `(count + 1) / (draws + 1)`. A sign flip that only asked whether the flipped sum was negative would stay near one half even when every day favored the challenger, so that is not the test.

## Multiple comparisons

The family-wise alpha is 0.05 divided by the number of ideas already tried. That count is the bracket grid (15 specs in `backtest/grid.py`) plus the 12 appear-to-disappear validation trials plus every id in `backtest/hypotheses.py` plus every id in `backtest/areas.py`, plus any new challenger that is not already in those lists. The six hypotheses and the fifteen area overlays are already inside the registries, so the denominator is 15 + 12 + 6 + 15 = 48 and the line is 0.05 / 48. Adding an idea later raises the denominator. The line is not refit after seeing a p-value. The six-hypothesis table in `research/gate_results.csv` was scored when the denominator was 33. Those rows are not rewritten.

Draws default to 5,000, and rise if that would leave the smallest reportable p-value above the Bonferroni line. The smallest p-value is `1 / (draws + 1)`. The draw formula is fixed before the run.

## What a pass does, and what a fail does

Fail any bar and the decision is rejected. The reasons name the bar and the numbers. `app/signal_rule.json` is not written. `research/champion.json` keeps the current id.

A pass is the only input `promote` will accept, and only when the fresh slice was actually evaluated. This command (`python -m backtest.run_gate`) does not load the holdout, so it cannot promote. A later milestone that has exactly one pre-cleared id may read the holdout once and only then call `promote`.

The older research screen in `backtest/run_hypotheses.py` is still in force for new ideas: a negative pooled net, a negative validation window, a negative recent slice, fewer than 80 trades, or fewer than four positive half-years stays rejected there too. Clearing that screen does not replace the champion. The promotion gate does.
