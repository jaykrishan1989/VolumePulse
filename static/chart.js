(() => {
  const API_BASE = location.protocol === "file:" ? "http://127.0.0.1:8080" : "";
  const overlay = document.getElementById("chartOverlay");
  const priceEl = document.getElementById("chartPrice");
  const macdEl = document.getElementById("chartMacd");
  const rsiEl = document.getElementById("chartRsi");
  const symbolEl = document.getElementById("chartSymbol");
  const metaEl = document.getElementById("chartMeta");
  const statsEl = document.getElementById("chartStats");
  const statusEl = document.getElementById("chartStatus");
  const closeBtn = document.getElementById("chartClose");

  const UP = "#4d9fff";
  const DOWN = "#8b1a1a";
  const DOWN_WICK = "#c62828";

  let charts = [];
  let rangeSync = false;
  let resizeObs = null;
  let requestId = 0;
  let barMinutes = 5;
  let showMa5 = false;
  let lastSymbol = "";
  let lastRow = null;
  let lastPayload = null;
  let series = {};
  let liveTimer = null;
  let liveBusy = false;
  let lastBarKey = "";

  try {
    if (localStorage.getItem("vp-chart-interval") === "15") barMinutes = 15;
    if (localStorage.getItem("vp-chart-ma5") === "1") showMa5 = true;
  } catch (_) { /* ignore */ }

  function setIntervalUi() {
    document.querySelectorAll(".chart-iv").forEach((btn) => {
      btn.classList.toggle("on", Number(btn.dataset.interval) === barMinutes);
    });
    document.getElementById("chartMa5")?.classList.toggle("on", showMa5);
  }

  function sma(values, period) {
    const out = new Array(values.length).fill(null);
    let acc = 0;
    for (let i = 0; i < values.length; i++) {
      acc += values[i];
      if (i >= period) acc -= values[i - period];
      if (i >= period - 1) out[i] = acc / period;
    }
    return out;
  }

  function ema(values, period) {
    const k = 2 / (period + 1);
    const out = new Array(values.length).fill(null);
    let prev = null;
    let acc = 0;
    let n = 0;
    for (let i = 0; i < values.length; i++) {
      const value = values[i];
      if (value == null) continue;
      if (prev == null) {
        acc += value;
        n += 1;
        if (n === period) {
          prev = acc / period;
          out[i] = prev;
        }
      } else {
        prev = value * k + prev * (1 - k);
        out[i] = prev;
      }
    }
    return out;
  }

  function rsiWilder(values, period = 14) {
    const out = new Array(values.length).fill(null);
    let avgGain = 0;
    let avgLoss = 0;
    for (let i = 1; i < values.length; i++) {
      const change = values[i] - values[i - 1];
      const gain = Math.max(0, change);
      const loss = Math.max(0, -change);
      if (i < period) {
        avgGain += gain;
        avgLoss += loss;
        continue;
      }
      if (i === period) {
        avgGain = (avgGain + gain) / period;
        avgLoss = (avgLoss + loss) / period;
      } else {
        avgGain = (avgGain * (period - 1) + gain) / period;
        avgLoss = (avgLoss * (period - 1) + loss) / period;
      }
      const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
      out[i] = 100 - 100 / (1 + rs);
    }
    return out;
  }

  function meanStd(values) {
    const xs = values.filter((v) => v != null && Number.isFinite(v));
    if (!xs.length) return { mean: null, sd: null };
    const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
    if (xs.length < 2) return { mean, sd: 0 };
    const variance = xs.reduce((a, b) => a + (b - mean) ** 2, 0) / (xs.length - 1);
    return { mean, sd: Math.sqrt(variance) };
  }

  function nyDay(ts) {
    return new Date(ts * 1000).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
  }

  function lastFiveSessions(bars) {
    const days = [];
    for (let i = bars.length - 1; i >= 0; i--) {
      const day = nyDay(bars[i].t);
      if (!days.length || days[0] !== day) days.unshift(day);
      if (days.length > 5) break;
    }
    const keep = new Set(days.slice(-5));
    return bars.filter((bar) => keep.has(nyDay(bar.t)));
  }

  function fmt(n, d = 2) {
    if (n == null || !Number.isFinite(n)) return "—";
    return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  function baseChart(el, height) {
    return LightweightCharts.createChart(el, {
      width: el.clientWidth,
      height,
      layout: {
        background: { type: "solid", color: "transparent" },
        textColor: "#8b97aa",
        fontFamily: '"IBM Plex Sans", "Segoe UI", sans-serif',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(29, 38, 51, 0.7)" },
        horzLines: { color: "rgba(29, 38, 51, 0.7)" },
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
        vertLine: { color: "rgba(231, 184, 74, 0.35)", width: 1, style: 0, labelBackgroundColor: "#e7b84a" },
        horzLine: { color: "rgba(139, 151, 170, 0.35)", labelBackgroundColor: "#1d2633" },
      },
      rightPriceScale: {
        borderColor: "#1d2633",
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderColor: "#1d2633",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
        barSpacing: barMinutes === 15 ? 11 : 7,
        minBarSpacing: 0.4,
        shiftVisibleRangeOnNewBar: false,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
        axisDoubleClickReset: true,
      },
    });
  }

  function syncTimeScales(list) {
    list.forEach((chart) => {
      chart.timeScale().subscribeVisibleTimeRangeChange((range) => {
        if (!range || rangeSync) return;
        rangeSync = true;
        list.forEach((other) => {
          if (other !== chart) {
            try { other.timeScale().setVisibleRange(range); } catch (_) { /* mismatched data */ }
          }
        });
        rangeSync = false;
      });
    });
  }

  function destroy() {
    stopLive();
    if (resizeObs) {
      resizeObs.disconnect();
      resizeObs = null;
    }
    charts.forEach((chart) => {
      try { chart.remove(); } catch (_) { /* already gone */ }
    });
    charts = [];
    series = {};
    lastBarKey = "";
    [priceEl, macdEl, rsiEl].forEach((el) => { if (el) el.innerHTML = ""; });
  }

  function sizePanes() {
    const shell = overlay?.querySelector(".chart-panes");
    if (!shell) return { w: 800, price: 420, sub: 140 };
    const w = Math.max(320, shell.clientWidth);
    const h = Math.max(360, shell.clientHeight);
    const price = Math.round(h * 0.58);
    const sub = Math.max(92, Math.floor((h - price - 36) / 2));
    return { w, price, sub };
  }

  function applySizes() {
    const { w, price, sub } = sizePanes();
    if (charts[0]) charts[0].applyOptions({ width: w, height: price });
    if (charts[1]) charts[1].applyOptions({ width: w, height: sub });
    if (charts[2]) charts[2].applyOptions({ width: w, height: sub });
  }

  function captureTimeRange() {
    try {
      return charts[0] ? charts[0].timeScale().getVisibleRange() : null;
    } catch (_) {
      return null;
    }
  }

  function restoreTimeRange(range) {
    if (!range || range.from == null || range.to == null || !charts[0]) return false;
    try {
      rangeSync = true;
      charts.forEach((chart) => chart.timeScale().setVisibleRange(range));
      rangeSync = false;
      return true;
    } catch (_) {
      rangeSync = false;
      return false;
    }
  }

  function stopLive() {
    if (liveTimer) {
      clearInterval(liveTimer);
      liveTimer = null;
    }
    liveBusy = false;
  }

  function startLive() {
    stopLive();
    liveTimer = setInterval(() => {
      if (overlay?.hidden || !lastSymbol) return;
      loadChart({ silent: true });
    }, 1500);
  }

  function indicators(bars) {
    const closes = bars.map((b) => b.close);
    const { mean, sd } = meanStd(closes);
    const ema12 = ema(closes, 12);
    const ema26 = ema(closes, 26);
    const macd = closes.map((_, i) => (ema12[i] != null && ema26[i] != null ? ema12[i] - ema26[i] : null));
    const signal = ema(macd.map((v) => (v == null ? 0 : v)), 9).map((v, i) => (macd[i] == null ? null : v));
    const hist = macd.map((v, i) => (v == null || signal[i] == null ? null : v - signal[i]));
    const rsi = rsiWilder(closes, 14);
    const ma5 = sma(closes, 5);
    return { closes, mean, sd, macd, signal, hist, rsi, ma5 };
  }

  function ensureCharts() {
    if (charts.length) return;
    const { w, price: ph, sub } = sizePanes();
    const priceChart = baseChart(priceEl, ph);
    const macdChart = baseChart(macdEl, sub);
    const rsiChart = baseChart(rsiEl, sub);
    priceChart.applyOptions({ width: w });
    macdChart.applyOptions({ width: w, timeScale: { visible: false } });
    rsiChart.applyOptions({ width: w, timeScale: { visible: true } });

    series.candles = priceChart.addCandlestickSeries({
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: "#8cc4ff",
      wickDownColor: DOWN_WICK,
    });
    series.macd = macdChart.addLineSeries({ color: "#7ab8ff", lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
    series.sig = macdChart.addLineSeries({ color: "#e7b84a", lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
    series.hist = macdChart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
    series.zero = macdChart.addLineSeries({ color: "rgba(139,151,170,0.5)", lineWidth: 1, lastValueVisible: false, priceLineVisible: false });
    series.rsi = rsiChart.addLineSeries({ color: "#c08bff", lineWidth: 2, priceLineVisible: false });
    series.rsi.createPriceLine({ price: 70, color: "rgba(198,40,40,0.85)", lineWidth: 1, lineStyle: 2, title: "70" });
    series.rsi.createPriceLine({ price: 30, color: "rgba(77,159,255,0.8)", lineWidth: 1, lineStyle: 2, title: "30" });
    series.rsi.createPriceLine({ price: 50, color: "rgba(139,151,170,0.45)", lineWidth: 1, lineStyle: 3, title: "50" });
    rsiChart.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: 0.08 } });

    charts = [priceChart, macdChart, rsiChart];
    syncTimeScales(charts);
    resizeObs = new ResizeObserver(() => applySizes());
    if (overlay.querySelector(".chart-panes")) resizeObs.observe(overlay.querySelector(".chart-panes"));
  }

  function setBand(price, key, opts) {
    if (price == null || !series.candles) return;
    if (!series[key]) series[key] = series.candles.createPriceLine({ ...opts, price });
    else series[key].applyOptions({ price });
  }

  function applyChart(symbol, row, payload, { fit = false, range = null, silent = false } = {}) {
    if (typeof LightweightCharts === "undefined") {
      if (!silent) statusEl.textContent = "Chart library did not load. Open http://127.0.0.1:8080 instead of the HTML file.";
      return;
    }
    lastPayload = payload;
    const bars = lastFiveSessions(payload.bars || []);
    if (bars.length < 20) {
      if (!silent) statusEl.textContent = "Not enough bars to draw MACD / RSI.";
      return;
    }
    const ind = indicators(bars);
    ensureCharts();
    const last = bars[bars.length - 1];
    const key = `${bars.length}:${bars[0].t}:${last.t}`;
    const lastCandle = { time: last.t, open: last.open, high: last.high, low: last.low, close: last.close };
    const lastIdx = bars.length - 1;

    if (silent && lastBarKey === key && series.candles) {
      series.candles.update(lastCandle);
      if (showMa5 && series.ma && ind.ma5[lastIdx] != null) {
        series.ma.update({ time: last.t, value: ind.ma5[lastIdx] });
      }
      if (ind.macd[lastIdx] != null) series.macd.update({ time: last.t, value: ind.macd[lastIdx] });
      if (ind.signal[lastIdx] != null) series.sig.update({ time: last.t, value: ind.signal[lastIdx] });
      if (ind.hist[lastIdx] != null) {
        series.hist.update({
          time: last.t,
          value: ind.hist[lastIdx],
          color: ind.hist[lastIdx] >= 0 ? "rgba(77,159,255,0.7)" : "rgba(139,26,26,0.85)",
        });
      }
      if (ind.rsi[lastIdx] != null) series.rsi.update({ time: last.t, value: ind.rsi[lastIdx] });
    } else {
      if (!silent) {
        const spacing = payload.barMinutes === 15 ? 11 : 7;
        charts.forEach((chart) => chart.applyOptions({ timeScale: { barSpacing: spacing } }));
      }
      series.candles.setData(bars.map((b) => ({
        time: b.t,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })));
      setBand(ind.mean, "meanLine", { color: "#e7b84a", lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: "5d μ" });
      if (ind.sd > 0) {
        setBand(ind.mean + ind.sd, "plusLine", { color: "rgba(231,184,74,0.7)", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "+1σ" });
        setBand(ind.mean - ind.sd, "minusLine", { color: "rgba(231,184,74,0.7)", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "−1σ" });
      }
      if (showMa5) {
        if (!series.ma) {
          series.ma = charts[0].addLineSeries({
            color: "#f0f4fa",
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: true,
            crosshairMarkerVisible: true,
          });
        }
        series.ma.setData(bars.map((b, i) => (ind.ma5[i] == null ? { time: b.t } : { time: b.t, value: ind.ma5[i] })));
      } else if (series.ma) {
        try { charts[0].removeSeries(series.ma); } catch (_) { /* gone */ }
        series.ma = null;
      }
      series.macd.setData(bars.map((b, i) => (ind.macd[i] == null ? { time: b.t } : { time: b.t, value: ind.macd[i] })));
      series.sig.setData(bars.map((b, i) => (ind.signal[i] == null ? { time: b.t } : { time: b.t, value: ind.signal[i] })));
      series.hist.setData(bars.map((b, i) => (
        ind.hist[i] == null ? { time: b.t } : { time: b.t, value: ind.hist[i], color: ind.hist[i] >= 0 ? "rgba(77,159,255,0.7)" : "rgba(139,26,26,0.85)" }
      )));
      series.zero.setData(bars.map((b) => ({ time: b.t, value: 0 })));
      series.rsi.setData(bars.map((b, i) => (ind.rsi[i] == null ? { time: b.t } : { time: b.t, value: ind.rsi[i] })));
      lastBarKey = key;
    }
    const chg = row?.changePct;
    const minutes = payload.barMinutes === 15 ? 15 : 5;
    const barLabel = minutes === 15 ? "15-minute" : "5-minute";
    const liveTag = payload.live ? "Live · " : "";
    symbolEl.textContent = symbol;
    metaEl.textContent = payload.simulated
      ? `${liveTag}Simulated 5-day path · ${barLabel} bars`
      : `${liveTag}Last 5 sessions · ${barLabel} RTH bars`;
    statsEl.innerHTML = `
      <div><span>Last</span><b>${fmt(last.close)}</b></div>
      <div><span>Change</span><b class="${(chg || 0) >= 0 ? "up" : "down"}">${chg == null ? "—" : (chg >= 0 ? "+" : "") + fmt(chg, 2) + "%"}</b></div>
      <div><span>5-day mean</span><b>${fmt(ind.mean)}</b></div>
      <div><span>+1σ</span><b class="up">${fmt(ind.mean + ind.sd)}</b></div>
      <div><span>−1σ</span><b class="down">${fmt(ind.mean - ind.sd)}</b></div>
      ${showMa5 ? `<div><span>5-period avg</span><b>${fmt(ind.ma5.at(-1))}</b></div>` : ""}
    `;
    if (!silent) {
      statusEl.textContent = payload.note || "Scroll to zoom · drag to pan · double-click the axis to reset";
    }
    if (!silent || range) {
      requestAnimationFrame(() => {
        if (!silent) applySizes();
        requestAnimationFrame(() => {
          if (range) restoreTimeRange(range);
          else if (fit) charts.forEach((chart) => chart.timeScale().fitContent());
        });
      });
    }
  }

  async function loadChart({ preserveRange = false, silent = false } = {}) {
    if (!lastSymbol) return;
    if (silent && (!charts.length || liveBusy)) return;
    const range = preserveRange ? captureTimeRange() : null;
    const id = silent ? requestId : ++requestId;
    if (silent) liveBusy = true;
    if (!silent) {
      setIntervalUi();
      if (!charts.length) {
        symbolEl.textContent = lastSymbol;
        metaEl.textContent = `Loading 5-day tape · ${barMinutes}-minute bars…`;
        statsEl.innerHTML = "";
        statusEl.textContent = "Fetching IBKR bars…";
      } else {
        statusEl.textContent = `Loading ${barMinutes}-minute bars…`;
      }
    }
    try {
      const res = await fetch(`${API_BASE}/api/chart?symbol=${encodeURIComponent(lastSymbol)}&interval=${barMinutes}`);
      const data = await res.json();
      if (id !== requestId) return;
      if (!data.ok) {
        if (!silent) statusEl.textContent = data.error || "Could not load chart.";
        return;
      }
      applyChart(data.symbol || lastSymbol, lastRow, data, {
        fit: !silent && !preserveRange,
        range: silent ? null : range,
        silent,
      });
    } catch (_) {
      if (id !== requestId) return;
      if (!silent) statusEl.textContent = "Could not load chart. Is the server running at 127.0.0.1:8080?";
    } finally {
      if (silent) liveBusy = false;
    }
  }

  function closeChart() {
    requestId += 1;
    stopLive();
    overlay.hidden = true;
    overlay.classList.remove("on");
    destroy();
    lastPayload = null;
    document.body.classList.remove("chart-open");
    fetch(`${API_BASE}/api/chart/stop`, { method: "POST" }).catch(() => {});
  }

  async function openTickerChart(symbol, row) {
    if (!overlay || !symbol) return;
    lastSymbol = symbol;
    lastRow = row || lastRow;
    overlay.hidden = false;
    overlay.classList.add("on");
    document.body.classList.add("chart-open");
    setIntervalUi();
    await loadChart({ preserveRange: false });
    startLive();
  }

  document.querySelectorAll(".chart-iv").forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = Number(btn.dataset.interval) === 15 ? 15 : 5;
      if (next === barMinutes) return;
      barMinutes = next;
      try { localStorage.setItem("vp-chart-interval", String(barMinutes)); } catch (_) { /* ignore */ }
      setIntervalUi();
      if (lastSymbol && overlay && !overlay.hidden) loadChart({ preserveRange: true });
    });
  });
  document.getElementById("chartMa5")?.addEventListener("click", () => {
    showMa5 = !showMa5;
    try { localStorage.setItem("vp-chart-ma5", showMa5 ? "1" : "0"); } catch (_) { /* ignore */ }
    setIntervalUi();
    if (lastPayload && lastSymbol && overlay && !overlay.hidden) {
      applyChart(lastSymbol, lastRow, lastPayload, { range: captureTimeRange(), silent: true });
    }
  });
  setIntervalUi();

  closeBtn?.addEventListener("click", closeChart);
  overlay?.addEventListener("click", (e) => {
    if (e.target === overlay) closeChart();
  });
  overlay?.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay && !overlay.hidden) closeChart();
  });

  window.openTickerChart = openTickerChart;
  window.closeTickerChart = closeChart;
})();