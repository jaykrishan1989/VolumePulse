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
