# v0.1 baseline

This is the live list as of 28 Sep 2026. A name that appears between 10:00 and 11:00 ET is a BUY. When it leaves the list, that is a SELL. Both fills are the next bar's open. There is a hard stop, and the book is flat by 15:55. One on-bar confirms the buy, and one off-bar confirms the sell.

Nothing here was working well enough to trade. On the locked holdout (from 1 Apr 2026, read once) the account lost $268, which is 12.7 percent. About 37 percent of 191 trades won. The average trade lost $1.41, or 8.4 bp. The deepest drawdown was $321. A typical session had about 1.6 trades.

The same rule lost $864 on the earlier validation window and $1,475 from 2023 through March 2026. A day-by-day resample almost always stayed negative (p = 0.9995). Matched random entries were not reliably worse (p = 0.225). That is why this is v0.1, a baseline, and not v1.0.

The least-bad detail is narrow: the stop fired on 16 of the 191 holdout trades, and the morning window lost less than the all-day version of the same list. Less bad is still a loss. Confirm any signal by hand. Volume Pulse does not place orders.
