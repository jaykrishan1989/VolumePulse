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

On the stored 5-minute bars, no. `RESULTS.md` is the locked test: train through mid-2024, choose on July 2024–March 2026, then one holdout from April 2026. Costs are tiered IBKR commissions on a US$2,160 ticket and 2 bp of slippage each side. The live rule's holdout is about **−5.9 bp (−$1.18) per trade**. Every filter with enough validation trades also lost money. The least-bad one (only 10:00–12:00 ET) was still **−1.7 bp** on the holdout and was not significant, so the live thresholds were left alone.

The tab shows that holdout expectancy on each card, keeps a local paper log (`data/outcomes.sqlite`) of live setups, and can POST a notice to `ALERT_WEBHOOK_URL` or an ntfy topic in `ALERT_NTFY_TOPIC`. The notice is not an order. Gateway stays read-only.

```powershell
python -m unittest tests.test_entry tests.test_harness tests.test_outcomes
python -m backtest.scan
python -m backtest.run_search
```

Bar files live in `data/raw5/<SYMBOL>/*.parquet` (or `RTTB_RAW`). They are not committed.
