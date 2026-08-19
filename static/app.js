const heatEl = document.getElementById("heat");
const boardBody = document.getElementById("boardBody");
const detailEl = document.getElementById("detail");
const tapeEl = document.getElementById("tape");
const alertBar = document.getElementById("alertBar");
const metaLine = document.getElementById("metaLine");
const sessionChip = document.getElementById("sessionChip");
const sessionLabel = document.getElementById("sessionLabel");
const nyClock = document.getElementById("nyClock");
const modePill = document.getElementById("modePill");
const linkText = document.getElementById("linkText");
const sortBy = document.getElementById("sortBy");
const filterEl = document.getElementById("filter");

let selected = null;
let lastPrintKey = "";
let feedMode = "connecting";
let viewMode = "bubbles";
let lastRows = [];
let lastSnap = null;
const flashUntil = new Map();
const vizWrap = document.getElementById("vizWrap");
const bubbleStage = document.getElementById("bubbleStage");
const BUBBLE_LIMIT = 18;

function tickerVolume(row) {
  const session = lastSnap?.session || {};
  if (session.extended) return Math.max(0, row.extVolume || row.volume || 0);
  return Math.max(0, row.volume || row.extVolume || 0);
}

function bubbleTone(changePct) {
  const t = Math.max(-1, Math.min(1, (changePct ?? 0) / 3.2));
  const g = Math.abs(t);
  if (t >= 0) {
    return {
      hi: `hsl(148, ${72 + g * 18}%, ${58 + g * 16}%)`,
      mid: `hsl(152, ${70 + g * 12}%, ${26 + g * 12}%)`,
      lo: `hsl(160, 68%, ${10 + g * 8}%)`,
      glow: `rgba(61, 214, 140, ${0.28 + g * 0.55})`,
      ring: `rgba(180, 255, 214, ${0.25 + g * 0.45})`,
    };
  }
  return {
    hi: `hsl(356, ${70 + g * 16}%, ${60 + g * 10}%)`,
    mid: `hsl(354, ${68 + g * 10}%, ${32 + g * 8}%)`,
    lo: `hsl(352, 64%, ${16 + g * 6}%)`,
    glow: `rgba(255, 93, 108, ${0.22 + g * 0.45})`,
    ring: `rgba(255, 190, 198, ${0.2 + g * 0.35})`,
  };
}

const PHY = {
  g: 110,
  basin: 0.38,
  attract: 168,
  soften: 96,
  rest: 0.8,
  wallRest: 0.52,
  friction: 0.08,
  drag: 0.08,
  swirl: 22,
  gap: 2.2,
  maxV: 980,
  maxA: 2200,
  grab: 52,
};

const bubbleSim = {
  nodes: new Map(),
  running: false,
  raf: 0,
  lastT: 0,
  grab: null,
  dragMoved: false,
  bound: false,
  start() {
    if (this.running) return;
    this.bindPointer();
    this.running = true;
    this.lastT = 0;
    const tick = (now) => {
      if (!this.running) return;
      const dt = this.lastT ? Math.min(0.033, (now - this.lastT) / 1000) : 1 / 60;
      this.lastT = now;
      this.step(dt);
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  },
  stop() {
    this.running = false;
    cancelAnimationFrame(this.raf);
    this.lastT = 0;
  },
  bindPointer() {
    if (this.bound || !bubbleStage) return;
    this.bound = true;
    const toLocal = (ev) => {
      const box = bubbleStage.getBoundingClientRect();
      return { x: ev.clientX - box.left, y: ev.clientY - box.top };
    };
    bubbleStage.addEventListener("pointerdown", (ev) => {
      const btn = ev.target.closest(".bubble");
      if (!btn) return;
      const node = this.nodes.get(btn.dataset.symbol);
      if (!node) return;
      const p = toLocal(ev);
      this.grab = { node, dx: p.x - node.x, dy: p.y - node.y, px: p.x, py: p.y };
      this.dragMoved = false;
      node.el.classList.add("grabbing");
      node.el.setPointerCapture(ev.pointerId);
      ev.preventDefault();
    });
    bubbleStage.addEventListener("pointermove", (ev) => {
      if (!this.grab) return;
      const p = toLocal(ev);
      const g = this.grab;
      if (Math.hypot(p.x - g.px, p.y - g.py) > 5) this.dragMoved = true;
      g.px = p.x;
      g.py = p.y;
    });
    const endGrab = () => {
      if (!this.grab) return;
      this.grab.node.el.classList.remove("grabbing");
      this.grab = null;
    };
    bubbleStage.addEventListener("pointerup", endGrab);
    bubbleStage.addEventListener("pointercancel", endGrab);
  },
  setRows(rows, selectedSymbol) {
    if (!bubbleStage) return;
    const ranked = [...rows]
      .sort((a, b) => tickerVolume(b) - tickerVolume(a))
      .slice(0, BUBBLE_LIMIT);
    const w = Math.max(280, bubbleStage.clientWidth || vizWrap?.clientWidth || 800);
    const h = Math.max(280, bubbleStage.clientHeight || 560);
    const maxVol = Math.max(1, ...ranked.map(tickerVolume));
    const maxD = Math.min(w, h) * 0.34;
    const minD = 58;
    const keep = new Set();
    ranked.forEach((row, i) => {
      keep.add(row.symbol);
      const unit = Math.sqrt(tickerVolume(row) / maxVol);
      const d = minD + Math.pow(unit, 0.7) * (maxD - minD);
      let node = this.nodes.get(row.symbol);
      if (!node) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = "bubble";
        el.innerHTML = `<span class="b-gloss"></span><span class="b-sym"></span><span class="b-chg"></span><span class="b-vol"></span>`;
        bubbleStage.appendChild(el);
        const col = i % 6;
        const lane = Math.floor(i / 6);
        node = {
          symbol: row.symbol,
          el,
          symEl: el.querySelector(".b-sym"),
          chgEl: el.querySelector(".b-chg"),
          volEl: el.querySelector(".b-vol"),
          x: w * (0.16 + col * 0.14) + (Math.random() - 0.5) * 30,
          y: 28 + lane * 64 + Math.random() * 36,
          vx: (Math.random() - 0.5) * 90,
          vy: 50 + Math.random() * 110,
          r: d / 2,
          tr: d / 2,
          mass: 1,
          ax: 0,
          ay: 0,
          drawnR: 0,
        };
        this.nodes.set(row.symbol, node);
      }
      node.row = row;
      node.tr = d / 2;
      elSync(node, {
        symbol: row.symbol,
        selected: row.symbol === selectedSymbol,
        cls: chgClass(row.changePct),
        chg: signedPct(row.changePct),
        vol: fmtVol(tickerVolume(row)),
        tone: bubbleTone(row.changePct),
      });
    });
    for (const [symbol, node] of this.nodes) {
      if (keep.has(symbol)) continue;
      if (this.grab?.node === node) this.grab = null;
      node.el.remove();
      this.nodes.delete(symbol);
    }
  },
  step(dt) {
    if (!bubbleStage || viewMode !== "bubbles") return;
    const w = bubbleStage.clientWidth;
    const h = bubbleStage.clientHeight;
    if (w < 40 || h < 40) return;
    const list = [...this.nodes.values()];
    if (!list.length) return;
    const pad = 8;
    const cx = w / 2;
    let maxMass = 1;
    for (const n of list) {
      n.r += (n.tr - n.r) * (1 - Math.exp(-dt * 5));
      n.mass = Math.PI * n.r * n.r;
      if (n.mass > maxMass) maxMass = n.mass;
      n.ax = 0;
      n.ay = 0;
    }
    for (let i = 0; i < list.length; i += 1) {
      const a = list[i];
      for (let j = i + 1; j < list.length; j += 1) {
        const b = list[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const d2 = dx * dx + dy * dy + PHY.soften * PHY.soften;
        const invD = 1 / Math.sqrt(d2);
        const nx = dx * invD;
        const ny = dy * invD;
        const accelA = Math.min(PHY.maxA, PHY.attract * b.mass * invD * invD);
        const accelB = Math.min(PHY.maxA, PHY.attract * a.mass * invD * invD);
        a.ax += nx * accelA;
        a.ay += ny * accelA;
        b.ax -= nx * accelB;
        b.ay -= ny * accelB;
      }
    }
    let comX = 0;
    let comY = 0;
    let massSum = 0;
    for (const n of list) {
      comX += n.x * n.mass;
      comY += n.y * n.mass;
      massSum += n.mass;
    }
    comX /= massSum;
    comY /= massSum;
    const grabbed = this.grab?.node || null;
    for (const n of list) {
      if (n === grabbed) continue;
      const heavy = n.mass / maxMass;
      n.ax += (cx - n.x) * PHY.basin;
      n.ay += PHY.g * (0.12 + 1.35 * heavy) - 85 * (1 - heavy);
      n.ax += -PHY.swirl * (n.y - comY) / Math.max(h, 1);
      n.ay += PHY.swirl * (n.x - comX) / Math.max(w, 1);
      n.vx += n.ax * dt;
      n.vy += n.ay * dt;
      const drag = Math.exp(-PHY.drag * (0.35 + 0.9 * (1 - heavy)) * dt);
      n.vx *= drag;
      n.vy *= drag;
      const spd = Math.hypot(n.vx, n.vy);
      if (spd > PHY.maxV) {
        n.vx *= PHY.maxV / spd;
        n.vy *= PHY.maxV / spd;
      }
      n.x += n.vx * dt;
      n.y += n.vy * dt;
    }
    if (grabbed) {
      const g = this.grab;
      const tx = g.px - g.dx;
      const ty = g.py - g.dy;
      const ox = grabbed.x;
      const oy = grabbed.y;
      grabbed.x += (tx - grabbed.x) * Math.min(1, PHY.grab * dt);
      grabbed.y += (ty - grabbed.y) * Math.min(1, PHY.grab * dt);
      grabbed.vx = (grabbed.x - ox) / Math.max(dt, 1 / 120);
      grabbed.vy = (grabbed.y - oy) / Math.max(dt, 1 / 120);
    }
    for (let pass = 0; pass < 4; pass += 1) {
      for (let i = 0; i < list.length; i += 1) {
        for (let j = i + 1; j < list.length; j += 1) {
          collide(list[i], list[j], grabbed);
        }
      }
      for (const n of list) bounceWalls(n, w, h, pad, n === grabbed);
    }
    for (const n of list) {
      const d = Math.max(48, Math.round(n.r * 2));
      if (n.drawnR !== d) {
        n.drawnR = d;
        n.el.style.width = `${d}px`;
        n.el.style.height = `${d}px`;
        if (n.symEl) n.symEl.style.fontSize = `${Math.max(11, n.r * 0.28)}px`;
        if (n.chgEl) n.chgEl.style.fontSize = `${Math.max(9, n.r * 0.18)}px`;
        if (n.volEl) {
          n.volEl.style.fontSize = `${Math.max(8, n.r * 0.14)}px`;
          n.volEl.style.display = n.r < 34 ? "none" : "";
        }
      }
      n.el.style.transform = `translate3d(${(n.x - n.r).toFixed(2)}px, ${(n.y - n.r).toFixed(2)}px, 0)`;
      n.el.style.zIndex = String(200 + Math.round(n.r) + (n === grabbed ? 80 : 0));
    }
  },
};

function collide(a, b, grabbed) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const dist = Math.hypot(dx, dy) || 0.0001;
  const min = a.r + b.r + PHY.gap;
  if (dist >= min) return;
  const nx = dx / dist;
  const ny = dy / dist;
  const overlap = min - dist;
  const invA = 1 / a.mass;
  const invB = 1 / b.mass;
  const invSum = invA + invB;
  if (a !== grabbed) {
    a.x -= nx * overlap * (invA / invSum);
    a.y -= ny * overlap * (invA / invSum);
  }
  if (b !== grabbed) {
    b.x += nx * overlap * (invB / invSum);
    b.y += ny * overlap * (invB / invSum);
  }
  const rvx = b.vx - a.vx;
  const rvy = b.vy - a.vy;
  const relN = rvx * nx + rvy * ny;
  if (relN > 0) return;
  const j = -(1 + PHY.rest) * relN / invSum;
  if (a !== grabbed) {
    a.vx -= j * invA * nx;
    a.vy -= j * invA * ny;
  }
  if (b !== grabbed) {
    b.vx += j * invB * nx;
    b.vy += j * invB * ny;
  }
  const tx = -ny;
  const ty = nx;
  const relT = rvx * tx + rvy * ty;
  let jt = -relT / invSum;
  const maxF = Math.abs(j) * PHY.friction;
  if (jt > maxF) jt = maxF;
  if (jt < -maxF) jt = -maxF;
  if (a !== grabbed) {
    a.vx -= jt * invA * tx;
    a.vy -= jt * invA * ty;
  }
  if (b !== grabbed) {
    b.vx += jt * invB * tx;
    b.vy += jt * invB * ty;
  }
}

function bounceWalls(n, w, h, pad, frozen) {
  const minX = n.r + pad;
  const maxX = w - n.r - pad;
  const minY = n.r + pad;
  const maxY = h - n.r - pad;
  if (n.x < minX) {
    n.x = minX;
    if (!frozen) n.vx = Math.abs(n.vx) * PHY.wallRest;
  } else if (n.x > maxX) {
    n.x = maxX;
    if (!frozen) n.vx = -Math.abs(n.vx) * PHY.wallRest;
  }
  if (n.y < minY) {
    n.y = minY;
    if (!frozen) n.vy = Math.abs(n.vy) * PHY.wallRest;
  } else if (n.y > maxY) {
    n.y = maxY;
    if (!frozen) {
      n.vy = -Math.abs(n.vy) * PHY.wallRest;
      n.vx *= 0.98;
    }
  }
}

function elSync(node, { symbol, selected, cls, chg, vol, tone }) {
  const el = node.el;
  el.dataset.symbol = symbol;
  const grab = el.classList.contains("grabbing") ? " grabbing" : "";
  el.className = `bubble ${cls}${selected ? " selected" : ""}${grab}`;
  el.style.background = `radial-gradient(circle at 32% 28%, ${tone.hi}, ${tone.mid} 56%, ${tone.lo})`;
  el.style.boxShadow = selected
    ? `0 0 0 3px rgba(231, 184, 74, 0.7), 0 0 36px ${tone.glow}`
    : `inset 0 -18px 28px rgba(0,0,0,0.28), 0 0 0 1px ${tone.ring}, 0 0 28px ${tone.glow}, 0 16px 30px rgba(0,0,0,0.45)`;
  if (node.symEl && node.symEl.textContent !== symbol) node.symEl.textContent = symbol;
  if (node.chgEl && node.chgEl.textContent !== chg) node.chgEl.textContent = chg;
  if (node.volEl && node.volEl.textContent !== vol) node.volEl.textContent = vol;
}

function fmtNum(n, digits = 2) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtVol(n) {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return Math.round(n).toString();
}

function fmtX(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n.toFixed(2)}×`;
}

function chgClass(n) {
  if (n == null || Math.abs(n) < 0.005) return "flat";
  return n > 0 ? "up" : "down";
}

function signedPct(n) {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function signedChg(n) {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}`;
}

function heatColor(changePct) {
  if (changePct == null) return "rgba(40, 48, 62, 0.95)";
  const t = Math.max(-1, Math.min(1, changePct / 4));
  if (t >= 0) {
    const a = 0.18 + t * 0.42;
    return `rgba(61, 214, 140, ${a})`;
  }
  const a = 0.18 + Math.abs(t) * 0.42;
  return `rgba(255, 93, 108, ${a})`;
}

function dataTypeLabel(type, mode) {
  if (mode === "demo") return ["DEMO", "demo"];
  if (type === 3 || type === 4) return ["DELAYED", "delayed"];
  return ["LIVE", "live"];
}

function sparkPath(values, w = 88, h = 28) {
  const nums = (values || []).filter((v) => v != null && Number.isFinite(v));
  if (nums.length < 2) return "";
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  return nums
    .map((v, i) => {
      const x = (i / (nums.length - 1)) * (w - 2) + 1;
      const y = h - 2 - ((v - min) / span) * (h - 4);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

function sortTickers(tickers, key) {
  const copy = [...tickers];
  copy.sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    if (av == null && bv == null) return (a.rank ?? 99) - (b.rank ?? 99);
    if (av == null) return 1;
    if (bv == null) return -1;
    return Math.abs(bv) - Math.abs(av);
  });
  return copy;
}

function render(snap) {
  lastSnap = snap;
  feedMode = snap.mode;
  const [pillText, pillClass] = dataTypeLabel(snap.marketDataType, snap.mode);
  modePill.textContent = pillText;
  modePill.className = `pill ${pillClass}`;
  linkText.textContent = `${snap.host}:${snap.port}`;

  const session = snap.session || {};
  sessionLabel.textContent = session.label || "—";
  nyClock.textContent = session.nyTime ? `${session.nyTime} ET` : "";
  sessionChip.className = `session ${snap.mode} ${session.label || ""}`;

  if (snap.mode === "demo") {
    alertBar.hidden = false;
    alertBar.textContent =
      "SIMULATED TAPE — not IBKR. Gateway is not connected on 127.0.0.1:4001. Log into IBKR Gateway, keep API socket 4001 enabled, then refresh. Do not trade off these prices.";
  } else if (snap.lastError && snap.mode !== "live") {
    alertBar.hidden = false;
    alertBar.textContent = snap.lastError;
  } else if (snap.mode === "live" && !snap.usingScanner) {
    alertBar.hidden = false;
    alertBar.textContent = snap.scan === "sp500"
      ? "S&P 500 mode — showing liquid index names ranked by volume. IBKR’s raw hot-volume scan had few S&P 500 hits this session."
      : "Scanner unavailable — ranking a liquid US list by volume instead. Add US equity market data in IBKR if you expected Hot by Volume.";
  } else if (snap.lastError && snap.mode === "live") {
    alertBar.hidden = false;
    alertBar.textContent = snap.lastError;
  } else {
    alertBar.hidden = true;
  }

  const sessionName = session.label || "—";
  const volHead = document.getElementById("volHeading");
  if (volHead) {
    volHead.textContent =
      sessionName === "afterhours" ? "AH vol" :
      sessionName === "overnight" ? "ON vol" :
      sessionName === "premarket" ? "PM vol" : "Volume";
  }
  const legend = document.getElementById("legendText");
  if (legend && viewMode === "bubbles") {
    legend.innerHTML =
      "Area is <strong>volume</strong>. Mass scales with area — heavy names sink, pull lighter ones in, and win collisions. Color is <strong>green up / red down</strong>. Drag a name to toss it.";
  } else if (legend && session.extended) {
    legend.innerHTML =
      "Tile size is <strong>extended-hours volume</strong> since the cash close. Color is <strong>change vs regular-session close</strong>, not yesterday’s close.";
  } else if (legend) {
    legend.innerHTML =
      "Tile size is <strong>pace</strong> — today’s volume vs a typical full day, adjusted for how much of the session has elapsed. Color is <strong>price change</strong>.";
  }

  const scanAgo = snap.lastScanAt
    ? Math.max(0, Math.round(Date.now() / 1000 - snap.lastScanAt))
    : null;
  const md =
    snap.marketDataType === 3 || snap.marketDataType === 4
      ? "delayed quotes"
      : "real-time quotes";
  metaLine.textContent = snap.mode === "live"
    ? `${snap.tickers.length} names · ${md} · scanner ${scanAgo == null ? "…" : scanAgo + "s ago"} · session ${fmtNum((session.fraction || 0) * 100, 0)}% elapsed`
    : "Simulated tape until Gateway accepts the socket on port 4001";

  const q = filterEl.value.trim().toUpperCase();
  let rows = snap.tickers || [];
  if (q) rows = rows.filter((r) => r.symbol.includes(q));
  rows = sortTickers(rows, sortBy.value);
  lastRows = rows;

  if (selected && !rows.some((r) => r.symbol === selected)) {
    selected = rows[0]?.symbol ?? null;
  }
  if (!selected && rows[0]) selected = rows[0].symbol;

  const maxPace = Math.max(1, ...rows.map((r) => r.pace || 0));
  const now = Date.now();

  if (viewMode === "bubbles") {
    vizWrap.dataset.mode = "bubbles";
    bubbleSim.setRows(rows, selected);
    bubbleSim.start();
  } else {
    bubbleSim.stop();
    vizWrap.dataset.mode = "tiles";
    heatEl.innerHTML = rows
      .map((r) => {
        const weight = Math.max(0.35, r.extVolume || r.volume || r.pace || 0.35);
        const flashing = (flashUntil.get(r.symbol) || 0) > now;
        return `<button class="tile ${r.symbol === selected ? "selected" : ""} ${flashing ? "flash" : ""}"
        data-symbol="${r.symbol}"
        style="flex:${weight} 1 120px; background:${heatColor(r.changePct)}">
        <div class="sym">${r.symbol}${feedMode === "demo" ? " · SIM" : ""}</div>
        <div class="chg ${chgClass(r.changePct)}">${signedPct(r.changePct)}</div>
        <div class="pace">${session.extended ? `${fmtVol(r.extVolume || r.volume)} since cash close` : `${fmtX(r.pace)} pace · ${fmtVol(r.volume)}`}</div>
      </button>`;
      })
      .join("");
  }

  boardBody.innerHTML = rows
    .map((r, i) => {
      const bar = Math.min(100, ((r.pace || 0) / Math.max(maxPace, 3)) * 100);
      const path = sparkPath(session.extended ? r.priceSpark || r.spark : r.spark);
      const flashing = (flashUntil.get(r.symbol) || 0) > now;
      return `<tr data-symbol="${r.symbol}" class="${r.symbol === selected ? "selected" : ""} ${flashing ? "flash" : ""}">
        <td class="num">${i + 1}</td>
        <td class="sym-cell">${r.symbol}</td>
        <td class="num">${fmtNum(r.last)}</td>
        <td class="num ${chgClass(r.change)}">${signedChg(r.change)}</td>
        <td class="num ${chgClass(r.changePct)}">${signedPct(r.changePct)}</td>
        <td class="num">${fmtVol(r.volume)}</td>
        <td class="num">${fmtVol(r.avgVolume)}</td>
        <td class="num">${fmtX(r.rvol)}</td>
        <td class="num">${fmtX(r.pace)}</td>
        <td><div class="pacebar"><i style="width:${bar}%"></i></div></td>
        <td class="num">${fmtVol(r.volumeRate)}</td>
        <td><svg class="spark" viewBox="0 0 88 28" aria-hidden="true"><path d="${path}" fill="none" stroke="${r.changePct >= 0 ? "#3dd68c" : "#ff5d6c"}" stroke-width="1.6"/></svg></td>
      </tr>`;
    })
    .join("");

  const pinned = rows.find((r) => r.symbol === selected) || rows[0];
  renderDetail(pinned);

  const prints = snap.prints || [];
  const newest = prints[0];
  if (newest) {
    const key = `${newest.symbol}-${newest.t}-${newest.size}`;
    if (key !== lastPrintKey) {
      lastPrintKey = key;
      flashUntil.set(newest.symbol, Date.now() + 450);
    }
  }
  tapeEl.innerHTML = prints
    .map((p) => {
      const t = new Date((p.t || 0) * 1000);
      const hh = t.toLocaleTimeString("en-US", { hour12: false, timeZone: "America/New_York" });
      return `<div class="print"><span>${hh}</span><b>${p.symbol}</b><span class="${chgClass(p.changePct)}">${fmtVol(p.size)} @ ${fmtNum(p.price)}</span></div>`;
    })
    .join("");
}

function renderDetail(row) {
  if (!row) {
    detailEl.innerHTML = `<div class="detail-empty">Waiting for tickers…</div>`;
    return;
  }
  const bar = Math.min(100, ((row.pace || 0) / 4) * 100);
  detailEl.innerHTML = `
    <h3>${row.symbol}${feedMode === "demo" ? " · SIM" : ""}</h3>
    <div class="px ${chgClass(row.changePct)}">${fmtNum(row.last)}</div>
    <div class="${chgClass(row.changePct)}">${signedChg(row.change)} (${signedPct(row.changePct)})</div>
    <div class="meter"><i style="width:${bar}%"></i></div>
    <div class="kv">
      <div><span>Bid / Ask</span><b>${fmtNum(row.bid)} / ${fmtNum(row.ask)}</b></div>
      <div><span>Spread</span><b>${fmtNum(row.spread, 3)}</b></div>
      <div><span>${row.extended ? "Vs cash close" : "Vs prev close"}</span><b>${fmtNum(row.close)}</b></div>
      <div><span>RTH volume</span><b>${fmtVol(row.rthVolume)}</b></div>
      <div><span>${row.extended ? "Ext. volume" : "Volume"}</span><b>${fmtVol(row.extVolume || row.volume)}</b></div>
      <div><span>Avg volume</span><b>${fmtVol(row.avgVolume)}</b></div>
      <div><span>RVOL</span><b>${fmtX(row.rvol)}</b></div>
      <div><span>Pace</span><b>${fmtX(row.pace)}</b></div>
      <div><span>Vol / min</span><b>${fmtVol(row.volumeRate)}</b></div>
      <div><span>Trades / min</span><b>${fmtNum(row.tradeRate, 1)}</b></div>
      <div><span>Day range</span><b>${fmtNum(row.low)} – ${fmtNum(row.high)}</b></div>
      <div><span>VWAP</span><b>${fmtNum(row.vwap)}</b></div>
      <div><span>$ volume</span><b>${fmtVol(row.dollarVolume)}</b></div>
      <div><span>52-week</span><b>${fmtNum(row.low52)} – ${fmtNum(row.high52)}</b></div>
    </div>
  `;
}

const FROM_FILE = location.protocol === "file:";
const API_BASE = FROM_FILE ? "http://127.0.0.1:8080" : "";

function pinSymbol(symbol) {
  if (!symbol) return;
  selected = symbol;
  const row = lastRows.find((r) => r.symbol === symbol);
  if (row) renderDetail(row);
  bubbleSim.nodes.forEach((node) => {
    node.el.classList.toggle("selected", node.symbol === symbol);
  });
  boardBody.querySelectorAll("tr[data-symbol]").forEach((tr) => {
    tr.classList.toggle("selected", tr.dataset.symbol === symbol);
  });
}

function bindClicks() {
  heatEl.addEventListener("click", (e) => {
    const tile = e.target.closest("[data-symbol]");
    if (tile) pinSymbol(tile.dataset.symbol);
  });
  bubbleStage.addEventListener("click", (e) => {
    if (bubbleSim.dragMoved) {
      bubbleSim.dragMoved = false;
      return;
    }
    const bubble = e.target.closest("[data-symbol]");
    if (bubble) pinSymbol(bubble.dataset.symbol);
  });
  boardBody.addEventListener("click", (e) => {
    const row = e.target.closest("[data-symbol]");
    if (row) pinSymbol(row.dataset.symbol);
  });
  document.querySelectorAll(".view").forEach((btn) => {
    btn.addEventListener("click", () => {
      viewMode = btn.dataset.view;
      document.querySelectorAll(".view").forEach((item) => item.classList.toggle("on", item === btn));
      vizWrap.dataset.mode = viewMode;
      if (viewMode === "bubbles") {
        bubbleSim.start();
        if (lastRows.length) bubbleSim.setRows(lastRows, selected);
      } else {
        bubbleSim.stop();
        if (lastSnap) render(lastSnap);
      }
    });
  });
  document.querySelectorAll(".scan").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".scan").forEach((b) => b.classList.toggle("on", b === btn));
      fetch(`${API_BASE}/api/scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scan: btn.dataset.scan }),
      }).catch(() => {});
    });
  });
}

let socket;
let backoff = 800;

function connect() {
  const url = FROM_FILE
    ? "ws://127.0.0.1:8080/ws"
    : `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
  socket = new WebSocket(url);
  socket.onopen = () => {
    backoff = 800;
  };
  socket.onmessage = (ev) => {
    try {
      render(JSON.parse(ev.data));
    } catch (err) {
      console.error(err);
    }
  };
  socket.onclose = () => {
    modePill.textContent = "OFF";
    modePill.className = "pill";
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 1.6, 8000);
  };
}

bindClicks();
connect();
