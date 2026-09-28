# Handoff

Branch: `cursor/right-time-to-buy-79f9`
PR: https://github.com/jaykrishan1989/VolumePulse/pull/1 (base `main`, draft)
Last research result on this branch: the commission-free rerank. The owner's account pays US$0 broker commission. Slippage and regulatory fees stay. IBKR Pro fixed commissions are the sensitivity column.
Working tree at the start of this handoff was clean and matched `origin/cursor/right-time-to-buy-79f9`.
Live pointer: `models/ACTIVE` is `v0.1`. Git tag `v0.1` is commit `1b720b2`. Do not move the tag.
The app never places orders.

## What's done

Right Time to Buy is a read-only IBKR dashboard. The live rule buys when a name appears on the list between 10:00 and 11:00 ET and sells when it leaves. Confirm 1, exit lag 1, hard stop on, flat by 15:55. Account US$2,120 (CA$3,000 at 1.4165), tiered commissions with a US$0.35 minimum, 2 bp slippage, whole shares.

That rule is baseline **v0.1**, not v1.0. It failed the costs-and-random bar. Holdout, read once as look 2: 191 trades, win 37.2%, −$268 (−12.7%), −8.43 bp. Bootstrap p of a non-positive total 0.9995. Versus random entries p = 0.225. `worthTrading` is false.

Earlier, also done and pushed:

- Bracket backtest had no cost-inclusive edge. Holdout look 1. Live numeric entry gates were not changed.
- Delayed-tape banner and grey hidden cards. Demo runs without `RTTB_FORCE_DELAY`.
- Six pre-registered hypotheses, all rejected after costs. Holdout not opened.
- Promotion gate in `research/GATE.md` and `backtest/gate.py`. All six hypotheses rejected against the champion. The six-hypothesis table in `research/gate_results.csv` used Bonferroni denominator 33. Do not rewrite those p-values.
- Checkpoint, changelog, CLI (`python -m models.cli list|show|restore|check`), and rollback monitor. No passing checkpoint exists, so a trip holds v0.1.

The four research areas requested in the latest amendment are done. Fifteen frozen overlays in `backtest/areas.py` were scored by `python -m backtest.run_areas` on 2023-01-01 through 2026-03-31. All rejected. No half-year was a profit. Look count remains 2 (`research/holdout_looks.csv`). Champion on the gate window: 1,234 trades, −$1,475, −$1.20/trade, −16.8 bp. Bonferroni denominator is now 48 (15 bracket specs + 12 appear/disappear trials + 6 hypotheses + 15 area ids). Alpha is 0.05/48 ≈ 0.001042.

| Overlay | Trades | Net | Per trade | Windows |
| --- | ---: | ---: | ---: | ---: |
| sz_risk_1pct | 1,243 | −$1,477 | −$1.19, −16.5 bp | 4/12 |
| sz_risk_half_pct | 1,342 | −$1,480 | −$1.10, −18.1 bp | 0/12 |
| sz_one_position | 1,115 | −$1,420 | −$1.27, −11.5 bp | 0/12 |
| sz_daily_stop | 1,057 | −$1,339 | −$1.27, −16.9 bp | 3/12 |
| sz_kelly_cap | 0 | $0 | n/a | 0/12 |
| tod_open (9:45–10:30) | 517 | −$657 | −$1.27, −13.2 bp | 4/12 |
| tod_midday (11:00–13:00) | 1,876 | −$1,999 | −$1.07, −27.6 bp | 0/12 |
| tod_afternoon (13:00–14:30) | 1,719 | −$1,859 | −$1.08, −21.7 bp | 0/12 |
| tod_last_hour (14:30–15:30) | 1,095 | −$1,280 | −$1.17, −15.7 bp | 6/12 |
| liq_half_spread | 1,056 | −$1,901 | −$1.80, −32.3 bp | 0/12 |
| liq_participation | 1,207 | −$1,518 | −$1.26, −17.7 bp | 0/12 |
| liq_dvol | 1,234 | −$1,475 | −$1.20, −16.8 bp | 0/12 |
| reg_spy_vwap | 751 | −$931 | −$1.24, −14.2 bp | 4/12 |
| reg_high_range | 923 | −$1,219 | −$1.32, −16.4 bp | 1/12 |
| reg_falling_tape | 1,025 | −$1,257 | −$1.23, −14.0 bp | 4/12 |

Findings worth keeping:

- The 1% risk cap bound on 95 fills the full ticket also took. A tighter stop asks for more shares than cash allows, so the cash cap wins. The 0.5% cap cut 486 fills and the extra names made basis points worse (−18.1 bp), because the US$0.35 minimum is a larger fraction of a thinner ticket.
- One open position, the open clock, and the three regime filters lost fewer dollars. Several of those paired p-values cleared 0.00104. Dollars per trade did not improve. An empty or smaller book is not a promotion.
- Kelly (`sz_kelly_cap`) stood aside on all 1,799 spells. Do not adopt "trade nothing."
- Last hour was the only clock ahead on all three pooled measures, by about three cents a trade and 1.1 bp, 6/12 windows. Every half-year still lost. Dropping the top 5 days removed the per-trade dollar edge. Paired p ≈ 0.12. Do not move the live window.
- Midday lost about $1,999. By 2025H2 equity was about $121, under one share, so later midday folds have no fills.
- Corwin–Schultz half-spread (OHLC stand-in, not a quote) averaged 4.5 bp extra. That book lost −32.3 bp. Square-root impact averaged 0.27 bp. The minimum commission, about 3.5 bp round trip, is the binding friction. The US$5,000,000 dollar-volume floor kept all 1,799 spells and matched the champion.

Write-ups: `research/RESEARCH_LOG.md` (marked `<!-- AREAS_BEGIN -->`), `research/areas.csv`, `research/area_folds.csv`, `research/area_summary.json`, `RESULTS.md`, `README.md`, `models/CHANGELOG.md` (marked `<!-- AREAS_CHANGELOG_BEGIN -->`). `backtest/run_hypotheses.py` preserves both the gate section and the areas section via `preserve_gate_section`.

Tests last run: `python -m unittest discover -s tests -q` — 97 tests, OK. The cost rerank does not change the dashboard, so no new browser pass was required.

## What's in progress

Nothing. The commission-free rerank is scored and not deployed.

Primary cost is schedule `regulatory` in `backtest/costs.py`: US$0 broker commission, 2 bp slippage on the next bar's open, SEC US$27.80 per US$1M and FINRA TAF US$0.000166 per share on sells. Secondary cost is schedule `fixed`: max(US$1.00, US$0.005 per share), plus the same slippage and regulatory fees. `python -m backtest.run_costs` writes `research/cost_rerank.csv`, `research/cost_summary.json`, and `research/cost_selection.json`. The selection file is written from validation nets before either holdout restatement is loaded. Look count is still 3. Do not append look 4.

Pooled 2023-01-01 through 2026-03-31. Positive means net above zero.

| Rule | Commission-free | Fixed | Validation, commission-free | Gate |
| --- | ---: | ---: | ---: | --- |
| appear_disappear_midmorning | −$824, −4.8 bp | −$1,971 | −$475 | reference |
| h5_gap_down | +$313, +4.6 bp | −$1,103 | +$139 | rejected, 8/12 |
| d_rs_leader | +$228, +1.8 bp | −$1,338 | −$124 | rejected, 8/12 |
| h2_opening_reversal | −$182, −0.02 bp | −$1,719 | −$34 | rejected, 9/12 |
| h4_opening_range | −$210, −2.5 bp | −$1,804 | −$733 | rejected, 6/12 |
| d_pullback | −$334 | −$1,758 | −$202 | rejected, 8/12 |
| d_orb | −$347 | −$1,498 | −$770 | rejected, 6/12 |
| d_vwap_reclaim | −$582 | −$1,668 | −$757 | rejected, 5/12 |
| h1_spy | −$324 | −$1,179 | −$183 | rejected, 4/12 |
| h1_stocks | −$599 | −$1,945 | −$233 | rejected, 6/12 |
| d_vwap_stretch | −$693 | −$1,845 | −$500 | rejected, 5/12 |
| h3_vwap_shortfall | −$953 | −$2,034 | −$518 | rejected, 5/12 |

Under commission-free costs, `h5_gap_down` and `d_rs_leader` are positive on the pooled window. Under fixed commissions, none is positive. On the validation window, only `h5_gap_down` is positive (+$139). The daily rank, highest validation net first, is `d_rs_leader` −$124, `d_pullback` −$202, `d_vwap_stretch` −$500, `d_vwap_reclaim` −$757, `d_orb` −$770. The finalist is still `d_rs_leader` because every daily validation net is a loss and it clears the 95% coverage bar.

`h5_gap_down` fails the gate: 8 of 12 windows, severe losses on down days and low-vol days, and −$514 after its best five days are removed. Paired p-values 0.061 and 0.064 versus 0.00094. Drawdown $1,019. Its holdout was not opened.

`d_rs_leader` fails the same gate: validation −$124, 8 of 12 windows, down days $2,039 worse than the champion, paired p-values 0.094 and 0.101. Look 3 restated, not used to rank: commission-free +$163 (+6.6 bp), fixed −$134. Look 2 restated: commission-free −$149 (−3.5 bp, 190 trades), fixed −$518.

The tiered daily table below is the previous cost. It is not the owner's account.

The live midmorning book filled on 563 of 813 SPY sessions (69.2%) from 2023-01-01 through 2026-03-31. Five frozen rules in `backtest/daily.py` were built to signal more often. Finalist rule, chosen on validation coverage (≥95%) and then validation net, before the holdout load: `d_rs_leader`. Look 3 is that one read. `models/ACTIVE` is still `v0.1`. `app/signal_rule.json` was not edited.

| Rule | Signal days | Trades/day | Win | Net | $/trade | $/day | Max DD | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| d_rs_leader | 100% | 1.00 | 25.6% | −$318 | −$0.39 | −$0.39 | $812 | rejected, 8/12 |
| d_vwap_stretch | 100% | 1.00 | 46.0% | −$1,143 | −$1.41 | −$1.41 | $1,160 | rejected, 4/12 |
| d_orb | 94.2% | 0.94 | 43.5% | −$773 | −$1.01 | −$0.95 | $1,386 | rejected, 6/12 |
| d_pullback | 99.9% | 1.00 | 21.7% | −$853 | −$1.05 | −$1.05 | $932 | rejected, 8/12 |
| d_vwap_reclaim | 99.8% | 1.00 | 22.8% | −$992 | −$1.22 | −$1.22 | $1,576 | rejected, 5/12 |

`d_rs_leader` validation net −$367. Holdout look 3: 123 trades, every session, win 26.8%, +$90, +3.2 bp, max DD $243. Fixed US$1 minimum on that same slice: −$134. Pooled tiered result −$318, −1.8 bp. Down days were $1,680 worse than the champion. Paired p 0.047 and 0.056 versus alpha 0.00094. No cost-inclusive edge. Do not trade it and do not retune it off the holdout print.

Look count is 3. Do not append look 4. `record_look` will reuse look 3 if `run_daily` is repeated for `d_rs_leader`.

Not started, and not authorized as a silent next search:

- Heston same-clock continuation across days. Needs a wider cross-section than these eight names.
- Order-flow imbalance. These files are OHLC. There are no aggressor prints.
- Shorts. Canadian cash account, long-only.
- Any retune of the frozen thresholds in `backtest/areas.py`, `backtest/hypotheses.py`, or `backtest/daily.py`.
- A second holdout read. Look count is 2 until `run_daily` appends look 3 for the one validation finalist. `fresh_slice` and `milestone` still raise.

## Exact next steps

Stop. The commission-free rerank is finished. Two pooled nets are above zero and neither passed the gate. Nothing stays positive once IBKR Pro's US$1 minimum is charged. Do not deploy `d_rs_leader` or `h5_gap_down`. Do not open the holdout. Do not move a threshold after seeing +$313 or +$228.

The Bonferroni denominator is 53. Do not rewrite `research/gate_results.csv` (scored at 33) or `research/areas.csv` (scored at 48).

Only if the owner adds a further pre-registered idea:

1. Add one frozen id. A threshold tweak is a new id, written down before the run. Do not edit the champion in place.
2. `ideas_tried()` already counts `AREA_REGISTRY`. A new id raises the denominator. Update `tests/test_gate.py` to the new total. Do not rewrite old rows in `research/gate_results.csv` or `research/areas.csv`.
3. Score it with the promotion gate on 2023-01-01..2026-03-31 only. Require a better net, better dollars per trade, and better basis points per trade in at least 9 of 12 windows, no severe regression, the edge surviving the top 5 days, and both paired p-values under 0.05/ideas_tried.
4. Do not open the holdout in the batch command. It opens only when exactly one challenger has already passed the other bars alone, as a separate milestone, and that read appends `research/holdout_looks.csv`.
5. A v1 checkpoint also has to pass `passes_costs_and_random` in `models/registry.py` (holdout net > 0, bootstrap p < 0.05, random-entry p < 0.05). Failing that stays v0.x. `create_passing_checkpoint` refuses v0.1's published results.
6. Commit and push after every meaningful step. Update PR #1 with `ManagePullRequest` (`branch_name` `cursor/right-time-to-buy-79f9`, `base_branch` `main`). Do not put agent metadata or cursor.com links in the PR body.

After `research/daily_summary.json` exists, stop. Do not fish a new threshold. Do not add an idea unless the owner registers one.

## Commands to resume

```powershell
git fetch origin cursor/right-time-to-buy-79f9
git checkout cursor/right-time-to-buy-79f9
git pull origin cursor/right-time-to-buy-79f9
git status
python -m unittest discover -s tests -q
python -m models.cli show v0.1
```

Re-score the fifteen overlays, still without the holdout:

```powershell
python -m backtest.run_areas
```

Score the five daily-frequency rules. This command reads the holdout once if a validation finalist clears 95 percent coverage:

```powershell
python -m backtest.run_daily
```

Re-score the frozen rules on the commission-free account. This does not append a holdout look:

```powershell
python -m backtest.run_costs
```

That rewrites the areas section of `research/RESEARCH_LOG.md`, `research/areas.csv`, `research/area_folds.csv`, `research/area_summary.json`, and the marked block in `models/CHANGELOG.md`. It refuses to run if `models/ACTIVE` is not `v0.1`, and it refuses if the live rule file changes. Parquets live in `data/raw5/<SYMBOL>/` (gitignored). Membership cache is `backtest_cache/membership.pkl` (gitignored).

Do not run `python -m backtest.run_roundtrip holdout` again. That slice has already been read.
