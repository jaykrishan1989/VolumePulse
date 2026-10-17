# Economic hypotheses

These are mechanisms, written down before the fill. A rule that is only a transformed price path on the eight mega-cap names is not on this list. Those paths were already scored, and they lose before commission.

The account is US$2,120, long only, whole shares, flat by 15:55 ET. A fill is an open. The live cost is tiered IBKR commission (US$0.35 minimum per side, exchange and regulatory fees on the sell) plus 2 bp of slippage per side. On a full ticket that round trip is about 8 bp. On a quarter ticket the US$0.35 minimum is about 15 to 20 bp before slippage. A book that cannot clear about 8 bp on one SPY ticket does not pay for itself. Nothing here places an order.

Three of the mechanisms below have already been scored on these files. Two more cannot be scored because the identifying data is not on disk. One cannot be scored honestly because the published clock belongs to a settlement regime this sample does not have. One can be scored, as a report, because the calendar is already frozen and the account can hold the slice of the day the paper says carries the drift. That one is registered at the end. It is not adoptable.

## 1. Intraday momentum into the close

Gao, Han, Li, and Zhou, "Market intraday momentum," Journal of Financial Economics, 2018 (DOI 10.1016/j.jfineco.2018.05.009). SPY, February 1993 through December 2013.

**Mechanism.** The first half-hour return predicts the last half-hour return on the same day. Their first half-hour is the previous cash close to 10:00 ET, so it includes the overnight gap. The last half-hour runs from 15:30 to 16:00. Two paying stories, both in the paper. Bogousslavsky (Journal of Finance, 2016) has some institutions rebalance at the open and others, slower, rebalance at the close in the same direction. Separately, traders who learn the morning news late still want to act before the cash close, because they do not want the overnight gap, and the close is the liquid time left. Either flow leans on the close in the direction of the morning.

**Who is on the other side.** The late rebalancer and the late-informed buyer are the demand. The other side of a 15:30 buy is whoever sells into that demand: a dealer who will not carry the inventory through the auction for free, or a holder who is indifferent to the clock. They are not donating the edge. They are charging for immediacy, or they are not trading the signal.

**Size against the ticket.** In their sample the sign of the first half-hour, used to go long or short the last half-hour, earned 6.67 percent a year (Sharpe ratio 1.08). An always-long last half-hour earned −1.11 percent a year. Spread over about 252 sessions, 6.67 percent is about 2.6 bp a day, and that figure uses both signs and holds through the auction. This account can take only the long side, and it is flat at 15:55, so it gives up 15:55 to 16:00. A few basis points does not clear an 8 bp round trip.

**Data.** On disk. Already used. The paper's own signal is `h1_spy`: the 9:55 close over the prior regular-session close, buy SPY at the 15:30 open, sell the 15:50 close. With a one-ATR stop the validation book was −$343, −8.9 bp. Without that stop, 466 pooled trades, −$605, −8.6 bp. Dropping the stop did not create the edge. `m_lasthour` is a different trade, the strongest of the eight stocks rather than SPY, and it lost −$479 on validation, −$181 of that before commission. Neither is reopened. The open-to-10:00 return is not their predictor. Scoring it now would be a second definition of a rejected paper, which is the pattern mining this note is here to stop.

## 2. Overnight clientele versus intraday clientele

Lou, Polk, and Skouras, "A tug of war: Overnight versus intraday expected returns," Journal of Financial Economics, 2019 (DOI 10.1016/j.jfineco.2019.03.011).

**Mechanism.** Two clienteles pull the same stock in opposite directions. One trades overnight and the other trades the cash session. Firm-level momentum in their sample accrues overnight. The cash session reverses the overnight move. A day trader who is flat by 15:55 can hold only the reversal, and only the long side of it.

**Who is on the other side.** The overnight seller, often a holder who does not want the news gap, is the flow the intraday buyer takes the other side of. That seller accepts the concession because the constraint is the overnight exposure, not the cash-session price. The account cannot sit on the other leg. The overnight continuation is the paper's momentum profit, and this account has no position from 15:55 to 9:30.

**Size against the ticket.** The cash-session reversal has to clear about 8 bp after the gap has already printed. `h5_gap_down` bought a down gap of 0.40 percent or worse at the 9:45 open and held to the flat, with a one-ATR stop. It was rejected. A later zero-commission rerank made the pooled book +$350 (+6.2 bp) and the validation book +$194, and the promotion gate still failed. Six basis points did not survive the gate, and the live cost is no longer zero. The −0.40 percent line is not retuned. Buying up gaps would be the overnight-momentum trade held at the wrong time of day. It was not the tested trade, and it is not added now.

**Data.** On disk. The prior close is the previous 15:55 close inside these regular-hours files.

## 3. Liquidity-provision premium

Nagel, "Evaporating liquidity," Review of Financial Studies, 2012. Hendershott and Menkveld, "Price pressures," Journal of Financial Economics, 2014. Campbell, Grossman, and Wang, Journal of Finance, 1993, for the volume state variable.

**Mechanism.** A short-horizon reversal is the payment to the trader who absorbs someone else's inventory. The premium is large when liquidity is scarce and small when anyone will hold the shares. It is earned by the passive quote, the bid that was already there, not by the order that crosses the spread a few minutes later.

**Who is on the other side.** The impatient seller. That seller pays the concession on purpose: the alternative is not trading. The account that buys the next open is the impatient side. It pays 2 bp to get in and 2 bp to get out, and then the commission. It does not earn the maker premium. On these names the half-spread is on the order of a basis point. An OHLC stand-in in the earlier liquidity overlay averaged 4.5 bp and that book lost more, not less. Either number is below an 8 bp round trip.

**Size against the ticket.** Already measured, all after 2 bp and before commission: the full-ticket slot fade was about −$59, the 30 bp residual versus SPY was −$359, the 30 bp VWAP discount was −$360, the −40 bp bar was −$429, and the heavy-volume down bar was −$278. The price path does not pay the ticket. No new reversal, residual, or VWAP band is registered.

**Data.** On disk, and already used. Quotes are not requested. Slippage stays 2 bp per side. A quote file would be a different cost model, not a new signal.

## 4. The pre-FOMC announcement drift

Lucca and Moench, "The pre-FOMC announcement drift," Journal of Finance, 2015 (DOI 10.1111/jofi.12196).

**Mechanism.** From September 1994 through March 2011 the S&P 500 rose, on average, 49 bp in the 24 hours from 14:00 the day before a scheduled FOMC announcement to 14:00 on the announcement day, before the decision (131 meetings, t-statistic above 4.5 on their robust errors). The return does not reverse over the following days. Their intraday figure rises modestly on the prior afternoon and then sharply on the morning of the announcement. By the release, the index sat about 50 bp above the previous day's open. After the release the path is flat. In the same paper, other major macro announcements do not produce a pre-announcement equity drift. That is why CPI days and payroll days, which are already coded, are not added to this test.

**Who is on the other side.** The paper's own conclusion is that a standard risk premium is a poor fit: realized volatility is lower, not higher, before the release, and Treasuries do not show the same drift. The practical other side of a morning buy is anyone selling equities that day for a reason that is not the clock. A rebalancer, a hedger, or a holder with a redemption. They are not agreeing to lose 49 bp. They are not trading the announcement. The limit that protects the drift is the one in Shleifer and Vishny (Journal of Finance, 1997): eight days a year is an awkward book for a mandate that is judged on tracking error. A US$2,120 account has no tracking-error mandate. It also cannot hold the overnight half of the 24 hours, which is the part of the paper this test gives up.

**Size against the ticket.** 49 bp is the full 24-hour window, and the "about 50 bp above the previous day's open" path mixes the prior afternoon, the overnight, and the morning. The morning's share is not a number this note invents. The full-ticket cost is about 8 bp. The morning has to clear that on its own. The validation window contains on the order of fourteen statement days. Fourteen trades cannot clear the frozen 80-trade screen. A positive mean on fourteen trades does not open the holdout and does not lower the screen.

**Data.** The statement dates are the frozen set in `backtest/grid15.py` (`FOMC_STATEMENT_DAYS`), taken from the Federal Reserve calendar. No date is added for this test. August 22, 2025 was a notation vote and is not in the set. The bars are the SPY session already on disk.

**What is registered.** `e_fomc`. SPY only. Buy the 9:30 open on a statement day. Sell the 13:55 open, which is five minutes before a 14:00 statement and does not include the release. Their sample released at 14:15; this sample releases at 14:00, so the exit is earlier than their 14:00 endpoint by those five minutes. A 100 bp stop is the account disaster cap. It is not a searched exit. One full ticket. No magnitude filter, and no second asset.

**The control, which is not a strategy.** `e_morning` is the same clock on every other session. That is their comparison, all other days, restricted to the hours this account can hold. A profitable control is a statement that ordinary mornings pay the ticket. It is not a book. It is not adoptable. CPI and payroll dates stay in the control. Moving them out after seeing the fill would be a search, and their paper says those dates do not carry this drift.

No coefficient is estimated from past returns. The calendar is public before the open.

## 5. Month-end payment cycle

Etula, Rinne, Suominen, and Vaittinen, "Dash for cash: Monthly market impact of institutional liquidity needs," Review of Financial Studies, 2020 (DOI 10.1093/rfs/hhz054). The older turn-of-the-month fact is Ariel (Journal of Financial Economics, 1987), Lakonishok and Smidt (Review of Financial Studies, 1988), and McConnell and Xu (Financial Analysts Journal, 2008). This note follows Etula, Rinne, Suominen, and Vaittinen because they tie the days to a constraint.

**Mechanism.** Pensions and other institutions have cash due at month end. Under the T+3 settlement rule in force for their equity sample, a sale on T−4 settles in time for a payment on the morning of T, where T is the last business day of the month. They are net sellers into that date. Prices are soft from T−8 to T−4 and rebound from T−3 to T−1. New cash arrives around T and T+1, and prices are firm from T through T+3. In their post-1995 sample the CRSP value-weighted holding-period return averages −17 bp from T−8 to T−4 and +77 bp from T−3 to T+3. Abnormal returns, after subtracting the sample's average day, are about −37 bp and, on T−3 to T−1, about +25 bp. Those are close-to-close numbers in a sample that ends in 2013.

**Who is on the other side.** The fund that must have the cash. It sells into a soft market because the payment is a constraint. It accepts the concession the way any forced seller does. Hedge funds that raise their market exposure on T−3 are the liquidity suppliers in the paper. This account could in principle be that supplier. It cannot short the selling-pressure days, and it cannot hold a three-day or seven-day rebound overnight.

**Size against the ticket.** A few to low tens of basis points per session if their multi-day total were spread evenly across the days, and less than that once the overnight piece is removed. That is the same order as the 8 bp ticket, so the intraday slice could go either way. It is not scored. The reason is the settlement regime, not the bars.

**Why there is no fill.** Their identifying variation is the settlement lag. They use a change in settlement conventions as a difference-in-differences. The United States left T+3 in 2017 and moved to T+1 on May 28, 2024. The validation window opens July 1, 2024, so every validation session is a T+1 session. The published labels T−4 and T−3 are the T+3 labels. Applying them here would test a stale calendar and call it a mechanism. Shifting the labels by the new lag is a new theory: the payment can be due on T or on T+1, the cash can be needed the morning before settlement or the morning of settlement, and each choice moves the long by a day. That choice is not in their tables. It will not be made after a fill, and it will not be made before one either. The session calendar is not the missing data. A published T+1 replication would be. Until that exists, this mechanism stays a document.

## 6. Closing auctions, index additions, and ETF baskets

Cushing and Madhavan, "Stock returns and trading at the close," Journal of Financial Markets, 2000. Chang, Hong, and Liskovich, "Regression discontinuity and the price effects of stock market indexing," Journal of Finance, 2015. Madhavan, "The Russell reconstitution effect," Financial Analysts Journal, 2003.

**Mechanism.** Some flow does not choose its price. An index fund that tracks a published membership list must buy the addition and sell the deletion. An authorized participant that creates or redeems an ETF must trade the basket. A market-on-close order must trade in the auction. Cushing and Madhavan show that the signed closing imbalance moves the close and that part of the move reverses after it. Chang, Hong, and Liskovich use the Russell rank cutoff as a discontinuity: the addition is demanded because of the list, not because of news that day.

**Who is on the other side.** The indexer, the authorized participant, and the market-on-close desk. They accept a worse price because the mandate is the benchmark, the creation, or the instruction to trade at the close. A small account that can trade before the auction, in the direction of a known imbalance, is the textbook other side. This account is flat at 15:55, so it cannot hold the auction itself. It could hold the half hour before the auction if it knew the sign.

**Size against the ticket.** The addition premium in the Russell papers is large relative to 8 bp, and it is concentrated on a handful of days a year, often in the closing print. The eight names already on disk are incumbents in the major indexes. They are not the additions. An imbalance of unknown sign has expectation zero, and an unconditional buy at 15:30 is the last-half-hour clock already rejected in section 1.

**Data.** Not on disk. Do not guess an add or a deletion, and do not treat a Friday or a quarter-end as a substitute for the imbalance. The request is in `DATA_REQUEST.md`.

## 7. Dealer gamma and pinning

Ni, Pearson, and Poteshman, "Stock price clustering on option expiration dates," Journal of Financial Economics, 2005. Baltussen, Da, Lammers, and Martens, "Hedging demand and market intraday momentum," Journal of Finance, 2021.

**Mechanism.** An option dealer who is short gamma buys as the underlying rises and sells as it falls, which extends the move. A dealer who is long gamma does the opposite, which pulls price back toward the strike and, on expiration, pins it there. Ni, Pearson, and Poteshman show the clustering at strikes on expiration dates. Baltussen, Da, Lammers, and Martens argue that the Gao pattern in section 1 is stronger when hedging demand has the sign that extends the morning move into the close.

**Who is on the other side.** The dealer hedge is not a view. It is the delta of a book the dealer was paid to hold. The dealer accepts the impact because the alternative is an unhedged option. The other side of a negative-gamma hedge is whoever takes the liquidity the hedge consumes. Knowing the sign requires the open interest, or a dealer-gamma estimate, by strike. The account can trade the underlying. It cannot see the hedge.

**Size against the ticket.** The published interaction is a difference in the last-half-hour drift, itself only a few basis points in section 1, concentrated on days when gamma has the right sign. Without the sign, the average day is the mixture, and the mixture is the rejected Gao book. Expiration Friday is a date. Trading every expiration afternoon is a clock. It is not registered.

**Data.** Not on disk. Option open interest by strike, known before the entry, is the request in `DATA_REQUEST.md`. A guessed strike will not be written into a book.

## 8. Earnings as an information event

Bernard and Thomas, "Post-earnings-announcement drift: Delayed price response or risk premium?," Journal of Accounting and Economics, 1989.

**Mechanism.** Prices continue in the direction of an earnings surprise for weeks after the announcement. The intraday piece a flat-by-15:55 account could hold is the cash session of the first day the news is public: the session after an after-close release, or the session of a before-open release. The drift is the slow part. The open already contains the fast part.

**Who is on the other side.** A holder who does not reprice the full implication at the open, or a mandate that cannot trade the name that day. They do not set out to lose the drift. They are slow, or they are constrained. The classic limit is attention and mandate design, not a missing arbitrageur with US$2,120.

**Size against the ticket.** The post-announcement drift in the literature is a multi-day object. The first cash session can be large, and it can also be the reversal of an overreaction at the open. Which one it is depends on the surprise, which these files do not contain. Eight names and four announcements a year is about 32 sessions. That fails a near-daily book by itself, and it fails the 80-trade screen. It is still the right sit-out list for any rule that was not built for a gap, once the dates exist.

**Data.** Not on disk. `DATA_REQUEST.md` already asks for `data/events/earnings.csv` with the timestamp known before the entry. Dates are not invented here. A wrong date is worse than a missing file.

## What a US$2,120 account can and cannot be

Shleifer and Vishny, "The limits of arbitrage," Journal of Finance, 1997. Specialized capital avoids a mispricing that can get worse before it pays, or that is too small and too rare for the mandate. This account is the other shape. Its order is about a quarter of a basis point of square-root impact in these bars, so it is not the flow in sections 3, 6, or 7. It has no tracking-error rule, so the eight FOMC mornings a year are not an awkward book for it. It can buy odd lots.

It cannot short, so it cannot sell the overnight winner or the rich residual. It cannot hold inventory through the night, so it cannot earn the liquidity-provision premium or the overnight momentum premium, and it cannot hold the 24-hour FOMC window or the multi-day month-end rebound. It cannot see a closing imbalance or a gamma sign. The US$0.35 minimum is about 4 bp on a full SPY ticket, and 2 bp a side is another 4 bp. The drift that fits is a long, known before the open, finished before 15:55, and larger than about 8 bp.

On that filter the eight mechanisms sort as follows. Sections 1, 2, and 3 were the right trades for the constraint and they did not pay. Sections 5, 6, 7, and 8 are the right economic objects and this sample cannot identify them. Section 4 is the one object the frozen calendar and the SPY bars can score, and only as the morning slice of a 24-hour result.

## Registered for the fill

| Id | What it is | Adoptable |
| --- | --- | --- |
| `e_fomc` | SPY, statement day, 9:30 open to 13:55 open, 100 bp disaster stop, full ticket | No. About fourteen validation days. |
| `e_morning` | The same clock on every other session. The control. | No. A clock is not a candidate. |

`ADOPTABLE` is empty. The holdout is not loaded. `ideas_tried()` stays 54. No threshold is fit on validation returns. The estimand is the average net basis-point gap between `e_fomc` and `e_morning`, together with the dollar result of `e_fomc` after tiered commission and 2 bp. The gap is a report. It is not a promotion rule. A positive gap on fourteen days does not lower the 80-trade bar, the half-of-sessions bar, or the published-net lock of $1,260.74.
