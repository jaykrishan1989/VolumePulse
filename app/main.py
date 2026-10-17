"""Volume Pulse web server — FastAPI + IBKR Gateway."""

from __future__ import annotations

import asyncio
import json
import math
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.ibkr import SCAN_CODES, VolumeFeed, allowed_gateway_host
from app.etfs import industry_stocks

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

feed = VolumeFeed()


def json_safe(value):
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(feed.run(), name="ibkr-feed")
    yield
    await feed.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Volume Pulse", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ScanBody(BaseModel):
    scan: str
    sector: str | None = None


class ConnectBody(BaseModel):
    host: str = "127.0.0.1"
    port: int = 4001
    clientId: int = 7
    marketDataType: int = 3


class WatchBody(BaseModel):
    symbol: str


class EtfIndustryBody(BaseModel):
    industry: str | None = None


NO_STORE = {"Cache-Control": "no-store, max-age=0"}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers=NO_STORE)


@app.get("/styles.css")
async def styles() -> FileResponse:
    return FileResponse(STATIC / "styles.css", headers=NO_STORE)


@app.get("/app.js")
async def script() -> FileResponse:
    return FileResponse(STATIC / "app.js", media_type="application/javascript", headers=NO_STORE)


@app.get("/bubbles.js")
async def bubbles() -> FileResponse:
    return FileResponse(STATIC / "bubbles.js", media_type="application/javascript")


@app.get("/chart.js")
async def chart_script() -> FileResponse:
    return FileResponse(STATIC / "chart.js", media_type="application/javascript", headers=NO_STORE)


@app.get("/api/status")
async def status() -> JSONResponse:
    snap = feed.snapshot()
    return JSONResponse(
        {
            "connected": snap["connected"],
            "mode": snap["mode"],
            "host": snap["host"],
            "port": snap["port"],
            "scan": snap["scan"],
            "scans": list(SCAN_CODES),
            "lastError": snap["lastError"],
            "session": snap["session"],
        }
    )


@app.post("/api/scan")
async def set_scan(body: ScanBody) -> JSONResponse:
    try:
        await feed.set_scan(body.scan, body.sector)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "scan": feed.scan_key, "sector": feed.sector_id})


@app.post("/api/etf-industry")
async def etf_industry(body: EtfIndustryBody) -> JSONResponse:
    try:
        await feed.set_etf_industry(body.industry)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse(
        {
            "ok": True,
            "industry": feed.etf_industry,
            "stocks": industry_stocks(feed.etf_industry),
        }
    )


@app.post("/api/watch")
async def watch_symbol(body: WatchBody) -> JSONResponse:
    try:
        symbol = await feed.watch_symbol(body.symbol)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "symbol": symbol})


@app.get("/api/chart")
async def chart(symbol: str, interval: int = 5) -> JSONResponse:
    minutes = 15 if interval == 15 else 5
    try:
        payload = await feed.chart_bars(symbol, minutes)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse(json_safe({"ok": True, **payload}))


@app.post("/api/chart/stop")
async def chart_stop() -> JSONResponse:
    await feed.stop_chart_stream()
    return JSONResponse({"ok": True})


@app.post("/api/connect")
async def connect_gateway(body: ConnectBody) -> JSONResponse:
    if not allowed_gateway_host(body.host):
        return JSONResponse(
            {"ok": False, "error": "Host must be localhost or a private LAN address."},
            status_code=400,
        )
    try:
        result = await feed.reconnect(body.host, body.port, body.clientId, body.marketDataType)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse(result)


@app.websocket("/ws")
async def websocket_feed(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            payload = json.dumps(json_safe(feed.snapshot()), allow_nan=False)
            await websocket.send_text(payload)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
    except Exception:
        return
