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
| `IBKR_SCAN` | `hot_volume` | `hot_volume`, `most_active`, `top_percent_gain`, `top_percent_lose` |
| `IBKR_MKT_DATA_TYPE` | `3` | `1` live, `3` delayed (needed without exchange subscriptions) |

## How to read the board

- **RVOL** — shares printed today ÷ typical daily volume
- **Pace** — RVOL ÷ fraction of the 9:30–16:00 ET session elapsed (the “is this actually busy *right now*?” number)
- **Vol / min** — IBKR volume rate (generic tick 295)
- **Flow** — last ~90 seconds of volume rate
- **Prints** — last size/price updates as they land

The heatmap and table are the same universe: IBKR `HOT_BY_VOLUME` on `STK.US.MAJOR` by default, refreshed about every 20 seconds, with market data streaming in between.
