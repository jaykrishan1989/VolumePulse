# Data request

The current 5-minute files are not enough for the profit objective. The winning book buys at most one name a day, and only when a forecast of the hold-to-close return clears 20 bp. On the eight names already on disk it stood aside on about four of every five validation sessions (85 trades, 19.4% of days, +$1,261). The holdout was the same shape: 19 trades, 15.4% of 123 sessions, +$297. Those eight names are one tape (mega-cap growth). Adding another name from that tape rarely creates a new day. A bank, an oil major, or a staples name can clear 20 bp on a day the Nasdaq book does not.

Nothing below was downloaded here. IB Gateway is on the owner's PC at `127.0.0.1:4001` and is not reachable from this VM. The causal profit result stands. Look 8 was not opened.

## Run this

From the repo root, on the PC where Gateway is logged in:

```powershell
pip install ib-insync pandas pyarrow tzdata
python scripts/fetch_history.py --dry-run
python scripts/fetch_history.py --max-priority 3
```

`--dry-run` does not connect. `--max-priority 3` is the upload that unblocks the next fit (5,720 requests, about 17.5 hours). A later run with no priority flag continues with sector ETFs and the 2018 backfill of the new names (10,364 requests, about 31.7 hours in total) and skips days already saved. Ctrl+C is safe. Run it again to resume.

Gateway must already be running. The script uses client id **19** (the dashboard uses 7). It does not place, cancel, or preview orders, and it does not request positions, executions, or account updates.

## What to fetch

5-minute, regular-hours, `TRADES` bars only. Each request is one week, which is IB's maximum for this bar size. Requests are at least 11 seconds apart and at most 50 in any 10 minutes (IB's cap is 60). A pacing reply waits two minutes and retries.

| Priority | Symbols | Start | End | Role | Requests | About |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | JPM, BAC, V, XOM, CVX, JNJ, UNH, WMT, PG, HON, NFLX, ORCL | 2021-12-23 | 2026-09-25 | tradeable | 3,480 | 10.6 h |
| 2 | AAPL, AMD, AMZN, GOOGL, META, MSFT, NVDA | 2018-01-02 | 2021-12-22 | backfill | 1,694 | 5.2 h |
| 3 | SPY, QQQ, TSLA | 2018-01-02 | 2020-12-23 | backfill | 546 | 1.7 h |
| 4 | XLK, XLF, XLE, XLV, XLP, XLI | 2021-12-23 | 2026-09-25 | context, not traded | 1,740 | 5.3 h |
| 5 | the 12 new names | 2018-01-02 | 2021-12-22 | backfill | 2,904 | 8.9 h |

Counts are one request per 6-day step. Days already in `data/raw5` are omitted, so priorities 2 and 3 do not re-download the files on disk. The end date is the last bar already stored (2026-09-25). Do not extend it; a newer session would sit outside the locked sample.

### Why these names

Whole shares, US$2,120, long only. A name has to leave room for several shares or the P&L is one tick. Prices are the 2026-09-28 Yahoo regular-session print, used only as a share-count screen.

| Symbol | Price | Shares | Why it can add a trade day |
| --- | ---: | ---: | --- |
| JPM | 336.59 | 6 | Banks. A different tape from the eight growth names. |
| BAC | 55.47 | 38 | Same, with a tight spread and a full lot of shares. |
| V | 367.74 | 5 | Payments. Not a bank and not Nasdaq beta. |
| XOM | 162.52 | 13 | Energy. |
| CVX | 206.37 | 10 | Energy, and it does not move as one print with XOM. |
| JNJ | 271.95 | 7 | Health. |
| UNH | 377.83 | 5 | Health, different business from JNJ. |
| WMT | 108.73 | 19 | Staples / retail. |
| PG | 149.03 | 14 | Staples. |
| HON | 211.52 | 10 | Industrials. |
| NFLX | 69.23 | 30 | Liquid, and not one of the eight. |
| ORCL | 132.60 | 15 | Software. Less overlap with NVDA/AMD than another chip name. |

Priority 1 is the profit lever: same dates the model already uses, twelve more names it can rank at the first bar of the day. If the per-name hit rate stays near the current one, idle days fall and dollar P&L moves because each added trade is the same full ticket, 2 bp, hold to 15:50. That is the reason to fetch. It is not a dollar forecast.

### Why the longer history

AAPL, AMD, AMZN, GOOGL, META, MSFT, and NVDA start on 2021-12-23. Every walk-forward fold is trained inside that sample, so the model never sees 2018Q4 or the 2020 crash. SPY, QQQ, and TSLA start on 2020-12-24, which includes the crash and still misses 2018–2019. Extending those files to 2018-01-02 adds those regimes as training rows. The holdout window stays 2026-04-01 through 2026-09-25. Priority 5 gives the new names the same start, so the cross-section does not change size in the backfill years.

2018 is the cutoff. Another year at this symbol list is about five hours of pacing, and 2022 is already in the file. The missing stress window is 2018 through 2021.

### Why the sector ETFs

Published importance on the current model is dominated by QQQ and SPY. Once the book includes banks and energy, one index treats a weak tech day like a weak everything day. XLK, XLF, XLE, XLV, XLP, and XLI are context features, not positions. They are priority 4 because the new stocks matter more.

## Where the files go

```
data/raw5/<SYMBOL>/YYYYMMDD.parquet
```

Same columns as the files already there:

| column | type |
| --- | --- |
| date | datetime64[us, US/Eastern], bar start, 09:30–15:55 |
| open, high, low, close, volume, average | float64 |
| barCount | int64 |

`average` is IB's bar WAP. The file name is the date of the last bar in that week. A boundary day can land in two files; the loader drops duplicate timestamps. Upload the symbol folders. `data/raw5/_fetch_log.csv` is only a resume note so empty holiday weeks are not requested again. The loader ignores it.

## Not requested

- **15-minute bars.** They are an aggregation of the 5-minute files.
- **1-minute bars.** The book enters on a 5-minute open and holds to 15:50. IB allows one day of 1-minute bars per request, so the same history is tens of thousands of requests, and the label would not change.
- **Daily bars from IB, and free Yahoo/Stooq daily bars.** The overnight gap and the prior close are already the 9:30 open versus the previous 15:55 close inside these regular-hours files. A second daily source can disagree on the auction and on splits, and it would not change the 2 bp cost or the hold-to-close label.
- **Bid, ask, or tick data.** Slippage stays 2 bp per side. Quotes would be a different cost model.
- **Names that do not fit the account.** LLY was about $1,184 (one share). MU was about $1,054 and is the same semiconductor tape as NVDA and AMD. GS (~$916) and COST (~$923) leave only two shares; JPM and WMT already cover those sectors with a fuller ticket. AVGO is affordable and liquid, and it was left out so the request spends its hours on ORCL instead of another chip name.

## After the upload

The next fit stays on validation dollars after 2 bp, then one holdout read of the single winner. That read is not authorized by this file. `models/ACTIVE` stays `v0.1`.
