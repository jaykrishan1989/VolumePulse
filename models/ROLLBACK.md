# Rollback monitor

The active checkpoint's expected result is its holdout expectancy, in basis points per trade, stored on that checkpoint. The monitor compares new evidence with that number. It never places an order.

## Paper log

Use the most recent 30 closed BUY round-trips in the outcome log (status sell, stop, or flat). Trip only when both of these are true:

- The mean net basis points of those 30 trades is at least 10 bp worse than the checkpoint expectancy.
- The count of those trades that landed below the checkpoint expectancy is high enough that a fair coin would do it less than 5 percent of the time. The p-value is the upper binomial tail at probability one half.

Fewer than 30 closed trades does not trip. One bad day does not trip.

## A new backtest

Trip when the new summary has at least 80 trades and its average net basis points is at least 10 bp worse than the same checkpoint expectancy. This is coarser than the paper test because a summary has no trade list. A different date window is not automatically a deterioration of the holdout; pass the summary only when it is a new read of this same rule.

## What a trip does

If some other checkpoint has `passedGate: true`, `models/ACTIVE` switches to the latest of those and the change is appended to `models/CHANGELOG.md`.

If no checkpoint has passed, ACTIVE stays on the current version. The same sample is logged once. The screen shows a rollback-held flag. v0.1 is in that second case: it is the live baseline, and it did not pass the costs-and-random bar, so there is nowhere better to go.
