# Volume Pulse

Live dashboard of US stocks that are trading unusually heavy volume right now, streamed from **IBKR Gateway**.

The page ranks names by **pace**: today’s volume versus a typical full day, scaled for how much of the regular session has already elapsed. A 2.0× pace means the stock is on track for twice its normal volume. Tiles are sized by pace and colored by price change. Quotes refresh every second.

## What you need

1. IBKR Gateway (or TWS) running and logged in
2. **Configuration → API → Settings**
   - Enable ActiveX and Socket Clients
   - Socket port **4001** (live Gateway; paper is usually 4002)
   - Read-Only API can stay checked
   - Trusted IPs can stay 127.0.0.1

US equity market data subscriptions improve scanner quality and turn delayed quotes into live ones. Without them the app still runs: IBKR may send delayed data, and if the scanner is blocked the board ranks a liquid fallback list by live/delayed volume.

## Run

```powershell
cd C:\Users\jay_k\Documents\ibkr-volume-pulse
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080).

If Gateway is not up yet, the page shows a **DEMO** tape so you can learn the layout, then switches to live data as soon as the socket connects.

## Optional environment

| Variable | Default | Meaning |
|---|---|---|
| `IBKR_HOST` | `127.0.0.1` | Gateway host |
| `IBKR_PORT` | `4001` | Matches your API socket port |
| `IBKR_CLIENT_ID` | `7` | API client id (tries the next few if busy) |
| `IBKR_SCAN` | `sp500` | `sp500`, `etfs`, `overview`, `mid_price`, `right_time`, `hot_volume`, `most_active`, `top_percent_gain`, `top_percent_lose` |
| `IBKR_MKT_DATA_TYPE` | `3` | `1` live, `3` delayed (needed without exchange subscriptions) |

## How to read the board

- **RVOL** — shares printed today ÷ typical daily volume
- **Pace** — RVOL ÷ fraction of the 9:30–16:00 ET session elapsed (the “is this actually busy *right now*?” number)
- **Vol / min** — IBKR volume rate (generic tick 295)
- **Flow** — last ~90 seconds of volume rate
- **Prints** — last size/price updates as they land

The heatmap and table are the same universe: IBKR `HOT_BY_VOLUME` on `STK.US.MAJOR` by default, refreshed about every 20 seconds, with market data streaming in between.

## Right Time to Buy

The **Right Time to Buy** tab lists names that are at a short-term **intraday long** entry *right now*. A row means the tape just confirmed a rebound. It drops off by itself once that setup is stale, the rebound low breaks, price runs too far above VWAP, or SPY/QQQ (or the sector ETF) is falling.

This is **not financial advice**. Volume Pulse connects to Gateway with the **read-only** API socket and **never places orders**.

The filter is deliberately selective. All of the gates live in one place: `ENTRY` in `app/entry.py`.

A name has to pass every gate, then score at least `min_score` (70). Only the top `top_n` (8) are shown.

1. **Pullback.** The dip from the session high down to the trough is measured in 5-minute ATR, not a fixed percent. It has to be meaningful (about 3.2–11 ATR, sweet spot near 6) and at least 0.7% so quiet noise does not count. The high must print *before* the trough.
2. **Reversal.** At least two confirms after the trough: a higher low, a VWAP reclaim, a 9-EMA reclaim, RSI crossing up out of oversold, or a stochastic cross up from oversold. A reclaim that has already failed does not count.
3. **Volume.** Up-bar volume on the bounce beats down-bar volume (or session RVOL is elevated). Chips such as `Up-volume 1.8×` and `RVOL 3.4×` show which one fired.
4. **Quality.** Price at least $8, enough dollar volume for this point in the session, and — when bid/ask are present — a spread tighter than 18 bps. Missing quotes (common on delayed data) do not veto a setup; a wide spread does. Halted names are out.
5. **Clock.** Live signals only use today's regular-session bars, and only from 9:45 to 15:45 ET. The open and the close are skipped. The demo tape ignores the wall clock so the layout is visible overnight; the live tape does not.
6. **Do not chase.** No signal if price is back at the high or more than 1.6 ATR above VWAP.
7. **Room.** Stop sits under the rebound low. The first target is back toward the session high, and only if reward-to-risk is at least 1.3 from a fill at the top of the entry zone.
8. **Market.** If SPY or QQQ is falling over the last 30 minutes (or the stock's sector ETF is), new longs are hidden. Sector ETFs come from `app/sectors.py`.
9. **Freshness.** The setup completes when the second confirm prints. It must be within the last 3 bars. Score decays with each bar, then the name expires. There is no memory of an old signal.

Each card shows the score, reason chips, entry zone, stop, first target, reward-to-risk, and how long ago the trigger printed. Double-click a card for the existing 5-minute / 15-minute chart.

The live universe is a capped liquid list plus SPY, QQQ, and the sector ETFs those names need (`watch_symbols()`, at most 40 market-data lines). Five-minute bars are refreshed two historical requests at a time, oldest first, so Gateway pacing stays intact. Delayed market data (type 3) is scored off those bars; freshness is counted in bars on that tape, not the wall clock, so a 15-minute delay does not instantly expire a setup. After the close, or before the open window, the list is empty on purpose.

### Tests and replay

```powershell
python -m unittest tests.test_entry
```

The tests build synthetic 5-minute sequences: a clear rebound qualifies; a steady downtrend, an illiquid tape, a wide spread, and a stale trigger do not.

To see how signals would have done over the next 15, 30, and 60 minutes, run this **on the PC that can see Gateway**. It only requests historical bars. It does not trade.

```powershell
python scripts/replay_entries.py --days 5
python scripts/replay_entries.py --symbols NVDA,AMD,JPM --days 3
```

### Does the setup pay for itself?

On the stored 5-minute bars, no. The trade the research targets is the round trip from appearing on the list to leaving it: buy the next bar's open, sell the next bar's open after it drops off, flat by 15:55, with a hard stop reported both on and off. `RESULTS.md` is the locked test on a US$2,120 ticket (CA$3,000 at 1.4165), tiered commissions (about US$0.35 minimum per side) and the US$1 fixed minimum, plus 2 bp of slippage. Twelve validation trials all lost money. The least-bad one, names only from 10:00–11:00 ET, was still **−$268 (−12.7%, −8.4 bp)** on the locked holdout from April 2026, 191 trades, 37% winners, $321 max drawdown. It did not beat random entries of the same length. Do not trade it.

The tab shows that holdout on each card. A name that joins the list raises a **BUY**. A name that leaves raises a **SELL**. A print through the stop raises a **STOP**, and 15:55 raises a **FLAT**. Those are alerts and a local log (`data/outcomes.sqlite`), not orders. You confirm each one. A webhook in `ALERT_WEBHOOK_URL` or an ntfy topic in `ALERT_NTFY_TOPIC` can ping the same text. Gateway stays read-only.

If Gateway is on delayed data (market data type 3 or 4), or the last bar is more than a minute behind the clock, a banner says so and Right Time to Buy does not list that setup. A last price already through the stop or the target is dropped too. The paper log records the delay on each row. On 28 Sep 2026 the delayed tape showed AAPL and XOM after the real price had already stopped out.

```powershell
python -m unittest tests.test_entry tests.test_harness tests.test_outcomes tests.test_freshness tests.test_spells tests.test_signals tests.test_hypotheses tests.test_gate tests.test_areas tests.test_models
python -m backtest.scan
python -m backtest.run_search
python -m backtest.run_roundtrip select
python -m backtest.run_roundtrip holdout
```

New ideas are registered in `backtest/hypotheses.py` and scored with `python -m backtest.run_hypotheses`. The write-up is `research/RESEARCH_LOG.md`, with `research/hypotheses.csv` beside it. Replacing the live champion is a separate check, `python -m backtest.run_gate`, specified in `research/GATE.md`: a challenger has to beat the current rule across half-years, market regimes, and ticker groups, with the improvement surviving a top-five-day removal and a multiple-testing correction. Position size, time of day, liquidity, and market regime are the fifteen overlays in `backtest/areas.py`, scored with `python -m backtest.run_areas` on that same gate. The holdout has been read for the bracket, the appear-to-disappear rule, the daily-frequency finalist, one 60-minute model, a down-gap variant, and the profit-search winner. Look 5 is an invalid same-day peek and is not a result. A research run does not read the holdout again.

A later batch asked for a signal on essentially every session. Five frozen rules (morning leader versus SPY, the name furthest under VWAP, the first opening-range break, the first opening pullback, the first VWAP reclaim) are in `backtest/daily.py`. All five lose money after tiered commissions and 2 bp. The morning leader fires every day and was the validation finalist. Its pre-holdout result is −$318 (−1.8 bp). The one holdout read was +$90 and the same trades lose $134 on the fixed US$1 schedule. It was not deployed. `RESULTS.md` has the table.

IBKR is the data source. Execution is modeled on a different, zero-commission platform (`app/cost_model.json`): no commission and 2 bp of slippage on the next bar's open. Re-scoring the same frozen rules on that cost leaves two pooled nets above zero: the down-gap hold (+$350, +6.2 bp) and the morning leader (+$302, +2.1 bp). The morning leader still loses $98 on the validation window that is allowed to rank rules. Both fail the promotion gate. Nothing was deployed.

One LightGBM model (`ml_lgb_60m`) predicts the 60-minute forward return and buys when that prediction is at least 20 bp. The threshold was chosen on validation, where every candidate lost money. Pooled result: 270 trades, a trade on 11.9% of days, 46.7% winners, −$319 (−$1.18 per trade, −6.6 bp), $456 max drawdown. Holdout look 4: 29 trades, +$77, day-bootstrap p = 0.197. The promotion gate wins 1 of 12 windows. No checkpoint. The files are in `models/ml/ml_lgb_60m/`. The live list is still v0.1.

A later search ranked 427 books by validation dollars after slippage. The winner predicts the return to the 15:50 close and buys the first name whose forecast reaches 20 bp. Holdout look 7: 19 trades, +$297, +$2.42 per session, 68.4% winners, $73 max drawdown. The best validation rule, a 1.5% down open held to the close, made +$210 on the same holdout (look 6, 52 trades). The model made more. It was not deployed.

The same gate rejected fifteen further overlays: 1% and 0.5% risk to the stop, one open position, a daily loss stop, fractional Kelly, four clocks (9:45–10:30, midday, afternoon, last hour), a high-low spread, square-root impact, a $5 million dollar-volume floor, and three SPY regime filters. Kelly bets nothing, because the champion's past mean is negative. The last hour was the least-bad clock and was still a loss in every half-year. No overlay won 9 of 12 windows. Nothing was promoted. `RESULTS.md` has the table.

The live list loads `models/ACTIVE`. That pointer is `v0.1`, a baseline, because the holdout lost money and did not beat a random entry. A passing rule would be tagged `v1.0` and up. `models/CHANGELOG.md` is the history. `python -m models.cli list`, `show`, and `restore` are the checkpoint commands. The paper log is watched against the checkpoint expectancy; the rule is in `models/ROLLBACK.md`.

Bar files live in `data/raw5/<SYMBOL>/*.parquet` (or `RTTB_RAW`). They are not committed.
