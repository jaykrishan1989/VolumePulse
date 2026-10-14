# What professional intraday traders actually do, and what this book can test

This note is the source of the 15-minute tiers in `backtest/grid15.py`. The tiers were not taken from a list of ideas to try. They are the practices that show up, in the same words, across prop desks, institutional execution, and the published record of discretionary intraday traders. Each practice is then cut down to something the files can measure: eight mega-caps plus SPY and QQQ, regular-hours 5-minute bars, no quotes.

The primary book is `pro_aplus`. It was frozen before the validation fill. Ablations turn one tier off. They are a report, not a menu. A better ablation is not adopted after the fact.

## What these files cannot do

Say this first, because several famous practices are not in the data.

- **There is no premarket.** The parquet files are regular hours, 9:30–15:55 ET. Premarket high, low, and volume, which SMB and most opening-drive traders treat as the real levels, are absent. The premarket tier abstains. The only overnight information is the gap from the prior regular close to the 9:30 open.
- **There is no tape.** No prints, no bid/ask, no Lee-Ready aggressor flag. A "volume rate" built from 5-minute bars is a proxy. It is not the tape a prop trader reads. `n_flow` already recorded the same limit.
- **There is no news feed and no earnings calendar.** Earnings are a large gap against the name's own recent gaps. That flags a possible catalyst. It does not know the company reported.
- **There are no sector ETFs.** XLK and the others are still absent. Relative strength is against SPY, not against a sector. QQQ is mostly these same names, so it is a second index check, not an independent breadth market.
- **These are not stocks in play.** SMB's playbook is a small list of names with a catalyst and several times normal volume, often small and mid caps. AAPL on an ordinary Tuesday is the opposite. The relative-volume gate is the same idea scaled down to what a mega-cap actually does. It will not reproduce a momentum-day tape.
- **Contest standings are not a rule set.** The US Investing Championship publishes returns, not a 15-minute checklist. The Robbins World Cup Trading Championship does the same. Many public winners are swing traders or futures traders. Nothing in those standings is a codeable entry on these ten names.
- **Bar-by-bar discretion does not survive a freeze.** Al Brooks's setup list is a way of reading one chart. Encoding twenty of his patterns and keeping the winner would be a search. The engine keeps two of his robust distinctions: a break that fails back inside the range, and the refusal to trade the middle of the day.
- **The bare opening-range breakout was already rejected here.** `h4_opening_range` and `d_orb` bought a close through the first 15-minute high and lost after costs. `n_orb_fail` bought the failed breakdown and did not survive losing its largest days. This run does not search a new range length. Fifteen minutes stays because that length is already frozen. The new question is whether the checklist around that break changes the result under the live cost model (no commission, 2 bp a side, US$2,120).

## Sources

The mapping below paraphrases the practice. It does not invent a quotation.

- Toby Crabel, *Day Trading With Short Term Price Patterns and Opening Range Breakout* (Traders Press, 1990). The opening range is the balance of the overnight book. A break is the trade. He studied more than one range length. This project already locked 15 minutes.
- Ulf Holmberg, Carl Lönnbark, and Christian Lundström, "Assessing the profitability of intraday opening range breakout strategies," *Finance Research Letters* 10(1), 2013. The published ORB result they report is on crude oil, and they tie it to high-volatility stretches. It is not a result on these eight stocks. `h4_opening_range` already cited this paper.
- Linda Bradford Raschke and Larry Connors, *Street Smarts* (1995). The useful pieces here are the opening drive, the refusal to trade midday chop, and a pullback in an already-established trend (their "holy grail" is an ADX trend plus a pullback to a short moving average). The afternoon book uses VWAP as the average we actually have. It is not their formula.
- Raschke's interviews in Jack Schwager's *Market Wizards* and *The New Market Wizards*. The repeated operational point is small risk and standing aside. There is no 15-minute mega-cap recipe in those interviews.
- Mike Bellafiore, *One Good Trade* (Wiley, 2010) and *The Playbook* (Wiley, 2012), and the SMB Capital desk process those books describe. Stocks in play, a written A+ checklist, a daily loss limit, and paying up only when the open shows real participation.
- Al Brooks, *Reading Price Charts Bar by Bar* (Wiley, 2009). Trend versus trading range. Failed breakouts. He trades a lot of index futures on a 5-minute chart; the pattern catalogue is discretionary.
- Mark Minervini, *Trade Like a Stock Market Wizard* (McGraw-Hill, 2013) and *Think and Trade Like a Champion*. The system is a swing system (trend template, volatility contraction). What carries to this book is the risk rule, about one percent of equity or less at the stop, buying strength rather than laggards, and relative strength. His intraday work, as he describes it, is execution of a swing entry, not a 15-minute scalp of AAPL.
- Brett Steenbarger, *The Daily Trading Coach* (Wiley, 2009) and *Enhancing Trader Performance* (Wiley, 2006). Sit out when the day's play is not there. A daily stop is a process rule, not an entry signal.
- Institutional execution: VWAP is the benchmark a desk is measured against. That use is in every broker algo guide; it is not a proprietary indicator. Session VWAP from the cash open is the version these bars support. A swing-anchored VWAP needs a discretionary anchor. We do not invent one.
- Calendars, used only as same-day context, not as a fitted effect. FOMC statement days are the second day of each meeting, statement at 14:00 ET, from the Federal Reserve's FOMC calendar (https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm). CPI dates are the BLS 8:30 ET releases (https://www.bls.gov/schedule/news_release/cpi.htm and the archived news releases). The employment-situation day is the first Friday of the month, which is the BLS convention, with three documented delays written in the code. Monthly options expiration is the third Friday. None of these dates were chosen because a backtest liked them.

## Practice to tier

| Practice | Where it comes from | Tier | What the code actually does | What it does not do |
| --- | --- | --- | --- | --- |
| Opening range | Crabel; Holmberg, Lönnbark, Lundström | `opening_range` | First 15 minutes (9:30, 9:35, 9:40). A later 15-minute bucket **closes** above that high. One break a day. | No other range length. No intrabar touch. The fill is the next 5-minute open, so a break inside the bucket waits. |
| Opening drive | Crabel; SMB | `volume_rate` | The open prints at least 1.2× its own prior-20-session median. The breakout bucket closes up, and its volume is at least its own slot median. After the first bucket, volume must not be lower than the previous bucket. | Does not ask the 9:50 bar to outprint the opening auction. That auction is the volume climax on these names. |
| VWAP | Execution desks; Raschke's pullback, translated | `vwap` | Long break only if the signal close is above session VWAP. The secondary book buys a 14:00–15:00 reclaim of VWAP after a dip below it. | No swing-anchored VWAP. No standard-deviation bands. |
| Prior-day high, low, close | SMB levels; Brooks range | `prior_levels` | Chase veto: the close is more than one opening-range beyond the range high. A break through the prior-day high is recorded and paid first in cash. It is not required. | Prior-day low is not a long entry. The failed-breakdown long was `n_orb_fail`. |
| Premarket levels | SMB, almost every open playbook | `premarket` | Abstains. Reason is stored. | No invented premarket high. |
| Gap type | Crabel; SMB gap-and-go versus gap-fill | `gap` | A gap down of more than 1% versus the prior close vetoes the long break. A gap larger than twice the name's own 60-session median absolute gap is flagged as a possible catalyst and does not change size. | No true earnings file. The flag is not a trade. |
| Tape and volume rate | Prop tape readers; SMB | `tape` and `volume_rate` | `tape` abstains. `volume_rate` is the 5-minute proxy: relative volume, slot acceleration, and whether the bucket closed up. | No prints. An "unusual print" veto would block the break a continuation trader wants. It is not used on the long. |
| Internals | Desk "what's the market doing" | `internals` | SPY or QQQ down more than 0.50% from the open vetoes. If SPY is red and fewer than 5 of the 8 names are green, veto. | Not NYSE TICK, ADD, or TRIN. QQQ overlaps these names. |
| Relative strength | Minervini; SMB "strongest stock" | `relative_strength` | The name's return from the open must beat SPY's. | No sector residual. No IBD-style rating. |
| Time of day | Raschke; Brooks; SMB | `time_of_day` | New opening-range risk only on the buckets that end 9:55, 10:10, 10:25, 10:40, and 10:55 (entries 10:00–11:00). Lunch is a sit-out. The grid still evaluates all 26 buckets. | The window was not picked from a scan of hours. |
| Trend template, cut down | Minervini | `trend` | Prior close above the 20-day average. A name under that average is a laggard. | Not the full trend template. Not a volatility-contraction pattern. |
| Event days | Every desk's "don't be a hero" list | `events` | CPI or employment-situation day: no opening-range long (the first 15 minutes are the release). FOMC statement day: no new risk at 13:30 or later. Options expiration: three-quarter size. A 2-standard-deviation SPY day: half size. Month-end is recorded and does not change size. | CPI dates before July 2024 are omitted rather than guessed. They are before the validation window. |
| A+ checklist | SMB *The Playbook* | decision tree | The long is the conjunction. One failed tier and the day is a sit-out. There is no second break later in the morning. | No scored weighting that we then threshold-search. |
| Risk and the daily stop | Minervini; SMB; Steenbarger | risk, always on | Stop is the opening-range low. Distance must be between 12 bp and 2.5% of price, or the trade does not fit costs or the account. Risk 0.5% of equity at that stop, and never more than 25% of equity in the name. Half exits at 1R. The runner's stop moves to the entry after 1R prints, target 2R. Morning trades that have not finished are out at the 12:00 open. Day stops at a realized loss of 1.5% of the morning's equity. | The runner's breakeven stop starts the bar after 1R, because the same bar can tag 1R and the old stop and we cannot see the order. Adding to a winner is not modeled. |
| Sit out | Steenbarger; SMB | the vetoes above | No setup, news open, FOMC afternoon, lunch, laggard, thin or huge range. | "I don't like the feel" is not a rule. |

The grid is 26 buckets from 9:30 through 15:45. A decision uses only bars inside the bucket that just closed. The fill, when there is one, is the next 5-minute open, worsened by 2 bp. Anything open is flat on the 15:50 bar's close (15:55). Nothing in this stack places an order.

## The frozen primary, and the books that are not candidates

`pro_aplus` is the only adoptable book. It is the opening-range long with every tier above left on.

Leave-one-out books turn off exactly one of `vwap`, `volume_rate`, `relative_strength`, `internals`, `gap`, `prior_levels`, `events`, and `trend`. `bare_or` turns all eight off. Time-of-day and the risk geometry stay on in every one of those, because without them the trade is no longer an opening-range trade.

`pro_vwap` is a second pre-registered book: afternoon VWAP reclaim, SPY green on the day, relative strength, prior close above the 20-day average. It is Raschke's pullback translated onto the average these bars have. It is not eligible to replace `pro_aplus` after we see which one made more.

`pro_short` sells a morning break that closes back under the range, with the same relative-volume day filter. The cash account cannot short. The column is there so a short edge is not quietly ignored. It cannot be adopted.

Holdout stays closed unless `pro_aplus` alone clears the published validation net of $1,260.74 and is still positive with its five best days removed. A nicer ablation does not open that door.
