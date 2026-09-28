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
let sortDir = "desc";
let midMoverFilter = null;
let lastPrintKey = "";
let feedMode = "connecting";
let viewMode = "bubbles";
let lastRows = [];
let lastSnap = null;
const flashUntil = new Map();
const vizWrap = document.getElementById("vizWrap");
const bubbleStage = document.getElementById("bubbleStage");
const etfBoard = document.getElementById("etfBoard");
const overviewBoard = document.getElementById("overviewBoard");
const midBoard = document.getElementById("midBoard");
const entryBoard = document.getElementById("entryBoard");
const printsBoard = document.getElementById("printsBoard");
const printsBody = document.getElementById("printsBody");
const printsBtn = document.getElementById("printsBtn");
const printLookupForm = document.getElementById("printLookupForm");
const printTicker = document.getElementById("printTicker");
const printLookupMsg = document.getElementById("printLookupMsg");
const BUBBLE_LIMIT = 18;
let watchedSymbols = [];
let tickerTap = { t: 0, symbol: null };
let expandedEtfIndustry = null;

function tickerVolume(row) {
  const session = lastSnap?.session || {};
  if (session.extended) return Math.max(0, row.extVolume || row.volume || 0);
  return Math.max(0, row.volume || row.extVolume || 0);
}

function bubbleWeight(row, scan) {
  if (scan === "top_percent_gain") return Math.max(0, row.changePct || 0);
  if (scan === "top_percent_lose") return Math.max(0, -(row.changePct || 0));
  return tickerVolume(row);
}

function bubbleTone(changePct) {
  const t = Math.max(-1, Math.min(1, (changePct ?? 0) / 3.2));
  const g = Math.abs(t);
  if (t >= 0) {
    return {
      hi: `hsl(210, ${72 + g * 18}%, ${58 + g * 12}%)`,
      mid: `hsl(212, ${70 + g * 12}%, ${32 + g * 10}%)`,
      lo: `hsl(214, 68%, ${12 + g * 8}%)`,
      glow: `rgba(77, 159, 255, ${0.28 + g * 0.55})`,
      ring: `rgba(180, 220, 255, ${0.25 + g * 0.45})`,
    };
  }
  return {
    hi: `hsl(0, ${62 + g * 12}%, ${38 + g * 8}%)`,
    mid: `hsl(0, ${60 + g * 10}%, ${24 + g * 6}%)`,
    lo: `hsl(0, 58%, ${12 + g * 5}%)`,
    glow: `rgba(139, 26, 26, ${0.32 + g * 0.45})`,
    ring: `rgba(198, 70, 70, ${0.22 + g * 0.35})`,
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
  volRef: 0,
  running: false,
  raf: 0,
  lastT: 0,
  grab: null,
  dragMoved: false,
  lastTap: null,
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
    const endGrab = (ev) => {
      const symbol = this.grab?.node?.symbol;
      const moved = this.dragMoved;
      if (this.grab) {
        this.grab.node.el.classList.remove("grabbing");
        this.grab = null;
      }
      if (!ev || ev.type === "pointercancel" || !symbol || moved || lastSnap?.scan !== "sp500") return;
      const now = performance.now();
      if (this.lastTap && this.lastTap.symbol === symbol && now - this.lastTap.t < 360) {
        this.lastTap = null;
        if (typeof openTickerChart === "function") {
          openTickerChart(symbol, lastRows.find((r) => r.symbol === symbol));
        }
        return;
      }
      this.lastTap = { t: now, symbol };
    };
    bubbleStage.addEventListener("pointerup", endGrab);
    bubbleStage.addEventListener("pointercancel", endGrab);
  },
  setRows(rows, selectedSymbol) {
    if (!bubbleStage) return;
    const scan = lastSnap?.scan;
    const byPct = scan === "top_percent_gain" || scan === "top_percent_lose";
    const ranked = [...rows]
      .sort((a, b) => bubbleWeight(b, scan) - bubbleWeight(a, scan))
      .slice(0, BUBBLE_LIMIT);
    const w = Math.max(280, bubbleStage.clientWidth || vizWrap?.clientWidth || 800);
    const h = Math.max(280, bubbleStage.clientHeight || 560);
    const weights = ranked.map((row) => bubbleWeight(row, scan));
    const maxW = Math.max(0.01, ...weights);
    if (!byPct) {
      const vols = ranked.map(tickerVolume);
      const avgs = ranked.map((r) => r.avgVolume || 0);
      const maxVol = Math.max(1, ...vols);
      const typical = Math.max(25e6, ...(avgs.length ? avgs.map((n) => n * 0.4) : [0]));
      if (!this.volRef) this.volRef = Math.max(typical, maxVol * 1.45);
      if (maxVol > this.volRef * 1.12) {
        this.volRef += (maxVol - this.volRef) * 0.06;
      }
    }
    const maxD = Math.min(w, h) * (byPct ? 0.44 : 0.38);
    const minD = byPct ? 50 : 64;
    const keep = new Set();
    ranked.forEach((row, i) => {
      keep.add(row.symbol);
      const weight = bubbleWeight(row, scan);
      const unit = byPct
        ? Math.sqrt(weight / maxW)
        : Math.sqrt(tickerVolume(row) / this.volRef);
      const d = minD + Math.min(1.05, unit) * (maxD - minD);
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
          baseR: d / 2,
          vol: 0,
          inflate: 0,
          mass: 1,
          ax: 0,
          ay: 0,
          drawnR: 0,
        };
        this.nodes.set(row.symbol, node);
      }
      node.row = row;
      if (weight > (node.vol || 0) && node.vol) {
        const jump = (weight - node.vol) / Math.max(node.vol, 0.01);
        node.inflate = Math.min(0.2, (node.inflate || 0) + Math.min(0.14, jump * 6));
      }
      node.vol = weight;
      node.baseR = d / 2;
      node.tr = node.baseR * (1 + (node.inflate || 0));
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
      n.inflate = Math.max(0, (n.inflate || 0) - dt * 1.35);
      n.tr = (n.baseR || n.tr) * (1 + n.inflate);
      n.r += (n.tr - n.r) * (1 - Math.exp(-dt * 2.4));
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
        if (n.symEl) n.symEl.style.fontSize = `${Math.max(13, Math.min(26, n.r * 0.34))}px`;
        if (n.chgEl) n.chgEl.style.fontSize = `${Math.max(11, Math.min(16, n.r * 0.2))}px`;
        if (n.volEl) {
          n.volEl.style.fontSize = `${Math.max(10, Math.min(13, n.r * 0.155))}px`;
          n.volEl.style.display = n.r < 30 ? "none" : "";
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

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function entryAge(row) {
  const bars = row.entryBars;
  if (bars == null) return "—";
  if (bars <= 0) return "this bar";
  const mins = row.entryAgoSec != null ? Math.max(0, Math.round(row.entryAgoSec / 60)) : bars * 5;
  return `${bars} bar${bars === 1 ? "" : "s"} · ${mins}m`;
}

function entryPlan(row) {
  if (row.entryScore == null) return "";
  const chips = (row.entryReasons || [])
    .map((reason) => `<span class="reason-chip">${esc(reason)}</span>`)
    .join("");
  return `<div class="entry-side">
    <div class="reason-row">${chips}</div>
    <div class="kv">
      <div><span>Entry</span><b>${fmtNum(row.entryLow)} – ${fmtNum(row.entryHigh)}</b></div>
      <div><span>Stop</span><b>${fmtNum(row.entryStop)}</b></div>
      <div><span>Target</span><b>${fmtNum(row.entryTarget)}</b></div>
      <div><span>Reward / risk</span><b>${fmtX(row.entryRR)}</b></div>
      <div><span>Since trigger</span><b>${esc(entryAge(row))}</b></div>
    </div>
  </div>`;
}

function fmtBps(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const value = Number(n);
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)} bp`;
}

function fmtSignedMoney(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const value = Number(n);
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

function entryHistLine(row) {
  if (row.entryHistBps == null && row.entryHistWin == null) return "";
  const win = row.entryHistWin == null ? "—" : `${(Number(row.entryHistWin) * 100).toFixed(0)}%`;
  return `<div class="entry-hist">This rule, holdout: ${win} wins · ${fmtBps(row.entryHistBps)} · ${fmtSignedMoney(row.entryHistDollars)} · n=${row.entryHistTrades ?? "—"}</div>`;
}

function researchPanel(snap) {
  const research = snap.entryResearch || {};
  const paper = snap.entryPaper || {};
  const hold = research.holdout || {};
  const verdict = research.verdict || "Measured holdout stats load with the published backtest.";
  const win = hold.winRate == null ? "—" : `${(Number(hold.winRate) * 100).toFixed(1)}%`;
  const paperWin = paper.winRate == null ? "—" : `${(Number(paper.winRate) * 100).toFixed(0)}% wins`;
  return `<section class="entry-research">
    <p class="entry-verdict">${esc(verdict)}</p>
    <div class="entry-stats">
      <div><span>Holdout win</span><b>${win}</b></div>
      <div><span>Expectancy</span><b>${fmtBps(hold.avgNetBps)}</b></div>
      <div><span>Avg $ / trade</span><b>${fmtSignedMoney(hold.avgNetDollars)}</b></div>
      <div><span>Holdout trades</span><b>${hold.trades ?? "—"}</b></div>
      <div><span>Paper open</span><b>${paper.open ?? 0}</b></div>
      <div><span>Paper closed</span><b>${paper.closed ?? 0} · ${paperWin} · ${fmtSignedMoney(paper.avgNetDollars)}</b></div>
    </div>
  </section>`;
}

function renderEntryBoard(snap, rows, selectedSymbol) {
  if (!entryBoard) return;
  const cards = rows.length
    ? `<div class="entry-list">${rows.map((row) => `
        <button type="button" class="entry-card${row.symbol === selectedSymbol ? " selected" : ""}" data-symbol="${esc(row.symbol)}">
          <div class="entry-score">${row.entryScore ?? "—"}<span>score</span></div>
          <div>
            <div class="entry-top">
              <div class="entry-sym">${esc(row.symbol)}${feedMode === "demo" ? " · SIM" : ""}</div>
              <div class="entry-last"><b>${fmtNum(row.last)}</b> <span class="${chgClass(row.changePct)}">${signedPct(row.changePct)}</span> · ${esc(entryAge(row))}</div>
            </div>
            <div class="reason-row">${(row.entryReasons || []).map((reason) => `<span class="reason-chip">${esc(reason)}</span>`).join("")}</div>
            <div class="entry-metrics">
              <div><span>Entry</span><b>${fmtNum(row.entryLow)} – ${fmtNum(row.entryHigh)}</b></div>
              <div class="stop"><span>Stop</span><b>${fmtNum(row.entryStop)}</b></div>
              <div class="target"><span>Target</span><b>${fmtNum(row.entryTarget)}</b></div>
              <div><span>Reward / risk</span><b>${fmtX(row.entryRR)}</b></div>
              <div><span>VWAP</span><b>${fmtNum(row.vwap)}</b></div>
              <div><span>RVOL</span><b>${fmtX(row.rvol)}</b></div>
            </div>
            ${entryHistLine(row)}
          </div>
        </button>`).join("")}</div>`
    : `<p class="entry-empty">${esc(snap.entryNote || "No fresh long entry on this tape.")}</p>`;
  entryBoard.innerHTML = `
    <p class="entry-disclaimer">${esc(snap.entryDisclaimer || "Not financial advice. Volume Pulse never places orders.")}</p>
    ${researchPanel(snap)}
    ${rows.length ? `<p class="entry-note">${esc(snap.entryNote || "")}</p>` : ""}
    ${cards}
  `;
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
    const a = 0.22 + t * 0.5;
    return `rgba(77, 159, 255, ${a})`;
  }
  const a = 0.28 + Math.abs(t) * 0.5;
  return `rgba(139, 26, 26, ${a})`;
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

function sortTickers(tickers, key, dir = "desc") {
  const copy = [...tickers];
  const sign = dir === "asc" ? -1 : 1;
  const signed = key === "changePct" || key === "change" || key === "last";
  copy.sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    if (av == null && bv == null) return (a.rank ?? 99) - (b.rank ?? 99);
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp = signed ? bv - av : Math.abs(bv) - Math.abs(av);
    return sign * cmp || String(a.symbol).localeCompare(String(b.symbol));
  });
  return copy;
}

function groupEtfs(rows, industryOrder) {
  const by = new Map();
  for (const row of rows) {
    const key = row.industry || "Other";
    if (!by.has(key)) by.set(key, []);
    by.get(key).push(row);
  }
  const order = (industryOrder || []).length
    ? industryOrder
    : [...by.keys()];
  return order
    .filter((key) => by.has(key))
    .map((industry) => {
      const items = sortTickers(by.get(industry), "changePct");
      const chgs = items.map((r) => r.changePct).filter((n) => n != null);
      const avg = chgs.length ? chgs.reduce((a, b) => a + b, 0) / chgs.length : null;
      return { industry, rows: items, avg };
    });
}

function renderEtfTable(rows, industryOrder, selectedSymbol, expandedIndustry, holdings) {
  const etfs = (rows || []).filter((row) => row.industry);
  const bySym = quoteMap(rows);
  const groups = groupEtfs(etfs, industryOrder);
  etfBoard.innerHTML = `
    <table class="etf-board">
      <thead>
        <tr>
          <th>Industry</th>
          <th>Symbol</th>
          <th>Fund</th>
          <th class="num">Last</th>
          <th class="num">Chg %</th>
          <th class="num">Volume</th>
        </tr>
      </thead>
      <tbody>
        ${groups.map((group) => {
          const open = group.industry === expandedIndustry;
          const names = open ? (holdings || []) : [];
          return `
          <tr class="etf-group ${open ? "open" : ""}" data-industry="${group.industry}" title="Double-click to show stocks in this category">
            <td colspan="4">${group.industry}${open ? " · stocks" : ""}</td>
            <td class="num group-chg ${chgClass(group.avg)}">${signedPct(group.avg)}</td>
            <td></td>
          </tr>
          ${group.rows.map((r) => `
            <tr data-symbol="${r.symbol}" class="${r.symbol === selectedSymbol ? "selected" : ""}">
              <td></td>
              <td class="sym-cell">${r.symbol}</td>
              <td class="etf-name">${r.name || ""}</td>
              <td class="num">${fmtNum(r.last)}</td>
              <td class="num ${chgClass(r.changePct)}">${signedPct(r.changePct)}</td>
              <td class="num">${fmtVol(r.volume)}</td>
            </tr>
          `).join("")}
          ${open ? (
            names.length
              ? names.map((sym) => {
                  const r = quoteFor(sym, bySym) || { symbol: sym };
                  const label = r.symbol || sym;
                  return `
            <tr data-symbol="${label}" class="etf-holding ${label === selectedSymbol ? "selected" : ""}">
              <td></td>
              <td class="sym-cell">${label}</td>
              <td class="etf-name">Stock</td>
              <td class="num">${fmtNum(r.last)}</td>
              <td class="num ${chgClass(r.changePct)}">${signedPct(r.changePct)}</td>
              <td class="num">${fmtVol(r.volume)}</td>
                </tr>`;
                }).join("")
              : `<tr class="etf-holding empty"><td></td><td colspan="5">${
                  group.industry === "Treasuries & credit" || group.industry === "Commodities"
                  || (lastSnap?.etfIndustry === group.industry && !(lastSnap.industryStocks || []).length)
                    ? "No stock list for this category"
                    : "Loading stocks…"
                }</td></tr>`
          ) : ""}`;
        }).join("")}
      </tbody>
    </table>
  `;
}

function quoteMap(rows) {
  const bySym = new Map();
  for (const row of rows || []) {
    bySym.set(row.symbol, row);
    bySym.set(row.symbol.replaceAll(".", " "), row);
    bySym.set(row.symbol.replaceAll(" ", "."), row);
  }
  return bySym;
}

function quoteFor(symbol, bySym) {
  return bySym.get(symbol) || bySym.get(symbol.replaceAll(".", " ")) || bySym.get(symbol.replaceAll(" ", "."));
}

function renderOverview(rows, sectors, sectorId, selectedSymbol) {
  const bySym = quoteMap(rows);
  if (sectorId) {
    const spec = (sectors || []).find((s) => s.id === sectorId);
    const names = spec?.stocks?.length ? spec.stocks : (rows || []).map((r) => r.symbol);
    const merged = names.map((sym) => {
      const row = quoteFor(sym, bySym);
      return row ? { ...row, symbol: row.symbol || sym } : { symbol: sym };
    });
    overviewBoard.innerHTML = `
      <div class="ov-head">
        <button type="button" class="ov-back">← Market Overview</button>
        <h2>${spec?.name || "Sector"}</h2>
      </div>
      <table class="ov-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th class="num">Last</th>
            <th class="num">Chg %</th>
            <th class="num">Volume</th>
          </tr>
        </thead>
        <tbody>
          ${sortTickers(merged, "changePct").map((r) => `
            <tr data-symbol="${r.symbol}" class="${r.symbol === selectedSymbol ? "selected" : ""}">
              <td class="sym-cell">${r.symbol}</td>
              <td class="num">${fmtNum(r.last)}</td>
              <td class="num ${chgClass(r.changePct)}">${signedPct(r.changePct)}</td>
              <td class="num">${fmtVol(r.volume)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
    return;
  }
  overviewBoard.innerHTML = `
    <div class="ov-grid">
      ${(sectors || []).map((s) => {
        const row = quoteFor(s.etf, bySym);
        const pct = row?.changePct;
        return `<button type="button" class="ov-card ${chgClass(pct)}" data-sector="${s.id}">
          <span class="ov-name">${s.name}</span>
          <span class="ov-etf">${s.etf}</span>
          <span class="ov-pct ${chgClass(pct)}">${signedPct(pct)}</span>
        </button>`;
      }).join("")}
    </div>
  `;
}

function vsOpenLine(row) {
  const open = row.open;
  const last = row.last;
  const prevOpen = row.prevOpen;
  if (open == null || last == null) {
    return `<div class="vs-open empty"><span class="vs-open-track"></span></div>`;
  }
  const high = row.high != null ? row.high : last;
  const low = row.low != null ? row.low : last;
  const extent = Math.max(
    Math.abs(high - open),
    Math.abs(low - open),
    Math.abs(last - open),
    prevOpen != null ? Math.abs(prevOpen - open) : 0,
    Math.abs(open) * 0.012,
    0.02
  );
  const pct = 50 + (50 * (last - open)) / extent;
  const left = Math.max(8, Math.min(92, pct));
  const side = last > open ? "up" : last < open ? "down" : "flat";
  let prevMark = "";
  if (prevOpen != null) {
    const prevPct = 50 + (50 * (prevOpen - open)) / extent;
    const prevLeft = Math.max(8, Math.min(92, prevPct));
    prevMark = `<span class="vs-open-prev" style="left:${prevLeft.toFixed(1)}%">
      <i></i><em>YEST (${fmtNum(prevOpen)})</em>
    </span>`;
  }
  const title = prevOpen != null
    ? `YEST (${fmtNum(prevOpen)}) · OPEN (${fmtNum(open)}) · NOW (${fmtNum(last)})`
    : `OPEN (${fmtNum(open)}) · NOW (${fmtNum(last)})`;
  return `<div class="vs-open ${side}" title="${title}">
    <div class="vs-open-track">
      ${prevMark}
      <i class="vs-open-tick"></i>
      <span class="vs-open-mid">OPEN (${fmtNum(open)})</span>
      <b class="vs-open-bubble" style="left:${left.toFixed(1)}%">NOW (${fmtNum(last)})</b>
    </div>
  </div>`;
}

function midBandRows(rows) {
  return (rows || []).filter((r) => {
    const px = r.last ?? r.close;
    return px != null && px >= 10 && px <= 50;
  });
}

function midMoverLists(rows) {
  return {
    up2: sortTickers((rows || []).filter((r) => Number(r.changePct) >= 2), "changePct", "desc"),
    down4: sortTickers((rows || []).filter((r) => Number(r.changePct) <= -4), "changePct", "asc"),
  };
}

function midMoverColumn(title, key, rows, selectedSymbol) {
  const on = midMoverFilter === key ? " on" : "";
  const body = rows.length
    ? rows.map((r) => `
        <button type="button" class="mid-mover ${chgClass(r.changePct)}${r.symbol === selectedSymbol ? " selected" : ""}" data-symbol="${r.symbol}">
          <b>${r.symbol}</b>
          <span>${signedPct(r.changePct)}</span>
        </button>`).join("")
    : `<p class="mid-mover-empty">None right now</p>`;
  return `
    <aside class="mid-movers ${key}${on}">
      <button type="button" class="mid-movers-head" data-mid-filter="${key}">${title}</button>
      <div class="mid-movers-list">${body}</div>
    </aside>`;
}

function renderMidTable(rows, selectedSymbol, universe) {
  const chgDir = sortBy.value === "changePct" ? sortDir : "";
  const movers = midMoverLists(universe || rows);
  midBoard.innerHTML = `
    <div class="mid-layout">
      <div class="mid-main">
        <table class="ov-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th class="num">Last</th>
              <th class="num sortable${chgDir ? " on" : ""}" data-sort="changePct" data-dir="${chgDir}">Chg %</th>
              <th class="num">Volume</th>
              <th>YEST · OPEN · NOW</th>
            </tr>
          </thead>
          <tbody>
            ${rows.length ? rows.map((r) => `
              <tr data-symbol="${r.symbol}" class="${r.symbol === selectedSymbol ? "selected" : ""}">
                <td class="sym-cell">${r.symbol}</td>
                <td class="num">${fmtNum(r.last)}</td>
                <td class="num ${chgClass(r.changePct)}">${signedPct(r.changePct)}</td>
                <td class="num">${fmtVol(r.volume)}</td>
                <td class="vs-cell">${vsOpenLine(r)}</td>
              </tr>
            `).join("") : `<tr><td colspan="5" class="empty">No names in this cut.</td></tr>`}
          </tbody>
        </table>
      </div>
      ${midMoverColumn("+2%", "up2", movers.up2, selectedSymbol)}
      ${midMoverColumn("−4%", "down4", movers.down4, selectedSymbol)}
    </div>
  `;
}

function printTime(t) {
  return new Date((t || 0) * 1000).toLocaleTimeString("en-US", {
    hour12: false,
    timeZone: "America/Los_Angeles",
  }) + " PT";
}

function printTapeRows(prints, emptyText) {
  if (!prints.length) {
    return `<tr><td colspan="4">${emptyText}</td></tr>`;
  }
  return prints.map((p) => `
    <tr class="print-row ${p.side || "unknown"}">
      <td>${printTime(p.t)}</td>
      <td class="num">${fmtVol(p.size)}</td>
      <td class="num">${fmtNum(p.price)}</td>
      <td class="num">${p.size && p.price ? "$" + fmtVol(p.size * p.price) : "—"}</td>
    </tr>`).join("");
}

function printFlow(bought, sold) {
  const buy = Number(bought || 0);
  const sell = Number(sold || 0);
  const total = buy + sell;
  if (total <= 0) {
    return { side: "flat", title: "NO FLOW", lean: "—", detail: "Waiting for prints", buyPct: 50, hasFlow: false };
  }
  const buyPct = (buy / total) * 100;
  if (buy > sell) {
    return { side: "up", title: "BUYING", lean: "BUY", detail: `${buyPct.toFixed(0)}% of share volume`, buyPct, hasFlow: true };
  }
  if (sell > buy) {
    return { side: "down", title: "SELLING", lean: "SELL", detail: `${(100 - buyPct).toFixed(0)}% of share volume`, buyPct, hasFlow: true };
  }
  return { side: "flat", title: "EVEN", lean: "EVEN", detail: "Buy and sell volume match", buyPct: 50, hasFlow: true };
}

function renderPrintsBoard(snap, rows, selectedSymbol) {
  if (!printsBody) return;
  const statsMap = snap.printStats || {};
  const book = snap.printsBySymbol || {};
  const extras = [...new Set([...(snap.extraWatches || []), ...watchedSymbols])];
  const have = new Set(rows.map((r) => r.symbol));
  extras.forEach((sym) => {
    if (!have.has(sym)) {
      const extraRow = (snap.tickers || []).find((r) => r.symbol === sym) || { symbol: sym };
      rows = [...rows, extraRow];
      have.add(sym);
    }
  });
  const ranked = [...rows].sort((a, b) => {
    const ta = (statsMap[a.symbol]?.bought || 0) + (statsMap[a.symbol]?.sold || 0);
    const tb = (statsMap[b.symbol]?.bought || 0) + (statsMap[b.symbol]?.sold || 0);
    return tb - ta;
  });
  const symbol = selectedSymbol && ranked.some((r) => r.symbol === selectedSymbol)
    ? selectedSymbol
    : ranked[0]?.symbol;
  const stats = statsMap[symbol] || {};
  const prints = book[symbol] || [];
  const buys = prints.filter((p) => p.side === "buy");
  const sells = prints.filter((p) => p.side === "sell");
  const bought = stats.bought || 0;
  const sold = stats.sold || 0;
  const net = Number(stats.net || bought - sold);
  const flow = printFlow(bought, sold);
  const netLabel = net === 0 ? "Even" : net > 0 ? "Net buying" : "Net selling";
  printsBody.innerHTML = `
    <div class="prints-layout">
      <div class="prints-names">
        <table class="ov-table prints-tickers">
          <thead>
            <tr>
              <th>Symbol</th>
              <th class="num">Buy</th>
              <th class="num">Sell</th>
              <th>Flow</th>
            </tr>
          </thead>
          <tbody>
            ${ranked.map((r) => {
              const s = statsMap[r.symbol] || {};
              const rowFlow = printFlow(s.bought, s.sold);
              return `<tr class="${r.symbol === symbol ? "selected" : ""}" data-symbol="${r.symbol}">
                <td>${r.symbol}</td>
                <td class="num up">${fmtVol(s.bought)}</td>
                <td class="num down">${fmtVol(s.sold)}</td>
                <td class="prints-flow" title="${rowFlow.title}${rowFlow.hasFlow ? " · " + rowFlow.detail : ""}">
                  <span class="prints-lean ${rowFlow.side}">${rowFlow.lean}</span>
                  <span class="prints-mini"><i style="width:${rowFlow.buyPct.toFixed(1)}%"></i></span>
                </td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>
      <div class="prints-detail">
        <div class="prints-summary">
          <div class="prints-hero">
            <h2>${symbol || "—"}</h2>
            <div class="prints-bias ${flow.side}">
              <strong>${flow.title}</strong>
              <span>${flow.detail}</span>
            </div>
          </div>
          <div class="prints-kpis">
            <div><span>Bought</span><b class="up">${fmtVol(bought)} sh · $${fmtVol(stats.boughtDollars)}</b></div>
            <div><span>Sold</span><b class="down">${fmtVol(sold)} sh · $${fmtVol(stats.soldDollars)}</b></div>
            <div><span>${netLabel}</span><b class="${flow.side === "flat" ? "" : flow.side}">${fmtVol(Math.abs(net))} sh</b></div>
            <div><span>Orders</span><b>${stats.count || 0}</b></div>
          </div>
          <div class="prints-bar" title="Buy ${flow.buyPct.toFixed(0)}% · Sell ${(100 - flow.buyPct).toFixed(0)}%">
            <i style="width:${flow.buyPct.toFixed(1)}%"></i>
          </div>
          <div class="prints-bar-labels">
            <span class="up">${flow.hasFlow ? `Buy ${flow.buyPct.toFixed(0)}%` : "Buy —"}</span>
            <span class="down">${flow.hasFlow ? `Sell ${(100 - flow.buyPct).toFixed(0)}%` : "Sell —"}</span>
          </div>
        </div>
        <div class="prints-tapes">
          <div>
            <h3 class="up">Buys</h3>
            <table class="ov-table prints-tape">
              <thead>
                <tr>
                  <th>Time</th>
                  <th class="num">Size</th>
                  <th class="num">Price</th>
                  <th class="num">$</th>
                </tr>
              </thead>
              <tbody>${printTapeRows(buys, "No buys yet for this name.")}</tbody>
            </table>
          </div>
          <div>
            <h3 class="down">Sells</h3>
            <table class="ov-table prints-tape">
              <thead>
                <tr>
                  <th>Time</th>
                  <th class="num">Size</th>
                  <th class="num">Price</th>
                  <th class="num">$</th>
                </tr>
              </thead>
              <tbody>${printTapeRows(sells, "No sells yet for this name.")}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  `;
}

function postScan(scan, sector) {
  document.querySelectorAll(".scan").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.scan === scan);
  });
  if (scan !== "etfs") expandedEtfIndustry = null;
  fetch(`${API_BASE}/api/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scan, sector: sector || null }),
  }).catch(() => {});
}

function toggleEtfIndustry(industry) {
  const next = expandedEtfIndustry === industry ? null : industry;
  expandedEtfIndustry = next;
  if (lastSnap?.scan === "etfs") {
    renderEtfTable(
      lastRows,
      lastSnap.industries,
      selected,
      expandedEtfIndustry,
      next === lastSnap.etfIndustry ? (lastSnap.industryStocks || []) : []
    );
  }
  fetch(`${API_BASE}/api/etf-industry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ industry: next }),
  }).catch(() => {});
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
      "SIMULATED TAPE — Gateway is not connected. Click 127.0.0.1:4001 above, log into IBKR Gateway on this computer, then Connect. This site never asks for your IBKR password.";
  } else if (snap.lastError && snap.mode !== "live") {
    alertBar.hidden = false;
    alertBar.textContent = snap.lastError;
  } else if (snap.mode === "live" && !snap.usingScanner && snap.scan !== "etfs" && snap.scan !== "overview" && snap.scan !== "mid_price" && snap.scan !== "right_time") {
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
  if (legend && viewMode === "prints") {
    legend.innerHTML =
      "The badge and <strong>Flow</strong> column show whether <strong>buy volume</strong> beats <strong>sell volume</strong>. <strong>BUY</strong> is at/above the ask; <strong>SELL</strong> is at/below the bid.";
  } else if (legend && snap.scan === "etfs") {
    legend.innerHTML =
      "Major US ETFs grouped by <strong>industry</strong>. Color is <strong>% change</strong> vs the cash close. <strong>Double-click</strong> a category for the stocks in that group.";
  } else if (legend && snap.scan === "overview" && snap.sector) {
    legend.innerHTML =
      "Names in this category. Color is <strong>% change</strong>. Click a row for the full tape on the right.";
  } else if (legend && snap.scan === "overview") {
    legend.innerHTML =
      "Each card is a <strong>market category</strong>. The large number is that group’s ETF move — <strong>blue up / dark red down</strong>. Click a card to see the stocks.";
  } else if (legend && snap.scan === "right_time") {
    legend.innerHTML =
      "A name is here only while it is a <strong>fresh intraday long</strong>: a real pullback that just turned up, with volume behind the bounce and room back toward the high. It <strong>leaves the list</strong> once that setup is stale, broken, or extended. Double-click for the chart. <strong>Not financial advice</strong> — this app never places orders.";
  } else if (legend && snap.scan === "mid_price") {
    legend.innerHTML =
      "S&amp;P 500 names trading <strong>$10–$50</strong> with established financials. Color is <strong>% vs yesterday’s close</strong>. Click <strong>+2%</strong> or <strong>−4%</strong> for quality names up at least 2% or down at least 4%.";
  } else if (legend && snap.scan === "sp500") {
    legend.innerHTML = viewMode === "tiles"
      ? "Tile size is <strong>pace</strong>. Color is <strong>price change</strong>. The spark is recent flow. <strong>Double-click</strong> a tile for MACD, RSI, and the 5-day mean ±1σ."
      : "Area is <strong>volume</strong>. Color is <strong>blue up / dark red down</strong>. <strong>Double-click</strong> a name for a 5-day chart with MACD, RSI, and the 5-day mean ±1σ. Scroll to zoom.";
  } else if (legend && viewMode === "bubbles" && lastSnap?.scan === "top_percent_gain") {
    legend.innerHTML =
      "Circle area is <strong>% gain</strong> — the bigger the move, the bigger the bubble. Color is <strong>blue up / dark red down</strong>.";
  } else if (legend && viewMode === "bubbles" && lastSnap?.scan === "top_percent_lose") {
    legend.innerHTML =
      "Circle area is <strong>% decline</strong> — the bigger the drop, the bigger the bubble. Color is <strong>blue up / dark red down</strong>.";
  } else if (legend && viewMode === "bubbles") {
    legend.innerHTML =
      "Area is <strong>volume</strong> and grows as shares print. Heavy names sink and pull lighter ones. Color is <strong>blue up / dark red down</strong>. Drag a name to toss it.";
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
  let midUniverse = [];
  if (snap.scan !== "mid_price") midMoverFilter = null;
  if (q && snap.scan !== "overview") rows = rows.filter((r) => r.symbol.includes(q));
  if (snap.scan === "mid_price" && viewMode !== "prints") {
    midUniverse = midBandRows(snap.tickers || []);
    rows = q ? midUniverse.filter((r) => r.symbol.includes(q)) : midUniverse;
    if (midMoverFilter === "up2") rows = midMoverLists(rows).up2;
    else if (midMoverFilter === "down4") rows = midMoverLists(rows).down4;
  }
  if (snap.scan === "right_time") {
    rows = [...rows].sort((a, b) => (b.entryScore || 0) - (a.entryScore || 0) || String(a.symbol).localeCompare(String(b.symbol)));
  } else if (!(snap.scan === "mid_price" && midMoverFilter)) {
    const sortKey = snap.scan === "mid_price" && sortBy.value === "pace" ? "volume" : sortBy.value;
    rows = sortTickers(rows, sortKey, sortKey === "changePct" ? sortDir : "desc");
  }
  lastRows = rows;

  const extras = new Set([...(snap.extraWatches || []), ...watchedSymbols]);
  if (selected && !rows.some((r) => r.symbol === selected)) {
    if (!(viewMode === "prints" && extras.has(selected))) {
      selected = rows[0]?.symbol ?? null;
    }
  }
  if (!selected && rows[0]) selected = rows[0].symbol;

  document.querySelectorAll(".scan").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.scan === snap.scan);
  });
  document.querySelector(".app")?.classList.toggle(
    "etf-mode",
    viewMode === "prints" || snap.scan === "etfs" || snap.scan === "overview" || snap.scan === "mid_price" || snap.scan === "right_time"
  );
  printsBtn?.classList.toggle("on", viewMode === "prints");

  const maxPace = Math.max(1, ...rows.map((r) => r.pace || 0));
  const now = Date.now();

  if (viewMode === "prints") {
    bubbleSim.stop();
    vizWrap.dataset.mode = "prints";
    renderPrintsBoard(snap, rows, selected);
  } else if (snap.scan === "etfs") {
    bubbleSim.stop();
    vizWrap.dataset.mode = "etfs";
    if (Object.prototype.hasOwnProperty.call(snap, "etfIndustry")) {
      expandedEtfIndustry = snap.etfIndustry || null;
    }
    renderEtfTable(rows, snap.industries, selected, expandedEtfIndustry, snap.industryStocks || []);
  } else if (snap.scan === "overview") {
    bubbleSim.stop();
    vizWrap.dataset.mode = "overview";
    renderOverview(rows, snap.sectors, snap.sector, selected);
  } else if (snap.scan === "mid_price") {
    bubbleSim.stop();
    vizWrap.dataset.mode = "mid";
    renderMidTable(rows, selected, midUniverse);
  } else if (snap.scan === "right_time") {
    bubbleSim.stop();
    vizWrap.dataset.mode = "entry";
    renderEntryBoard(snap, rows, selected);
  } else if (viewMode === "bubbles") {
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
        const spark = sparkPath(session.extended ? r.priceSpark || r.spark : r.spark, 120, 32);
        return `<button class="tile ${r.symbol === selected ? "selected" : ""} ${flashing ? "flash" : ""}"
        data-symbol="${r.symbol}"
        title="Double-click for MACD / RSI / ±1σ"
        style="flex:${weight} 1 120px; background:${heatColor(r.changePct)}">
        <div class="sym">${r.symbol}${feedMode === "demo" ? " · SIM" : ""}</div>
        <div class="chg ${chgClass(r.changePct)}">${signedPct(r.changePct)}</div>
        <div class="pace">${session.extended ? `${fmtVol(r.extVolume || r.volume)} since cash close` : `${fmtX(r.pace)} pace · ${fmtVol(r.volume)}`}</div>
        ${spark ? `<svg class="tile-spark" viewBox="0 0 120 32" preserveAspectRatio="none" aria-hidden="true"><path d="${spark}" fill="none" stroke="rgba(255,255,255,0.88)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>` : ""}
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
        <td><svg class="spark" viewBox="0 0 88 28" aria-hidden="true"><path d="${path}" fill="none" stroke="${r.changePct >= 0 ? "#4d9fff" : "#c62828"}" stroke-width="1.6"/></svg></td>
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
      const hh = t.toLocaleTimeString("en-US", { hour12: false, timeZone: "America/Los_Angeles" }) + " PT";
      const sideClass = p.side === "buy" ? "up" : p.side === "sell" ? "down" : chgClass(p.changePct);
      const tag = p.side === "buy" ? "B" : p.side === "sell" ? "S" : "";
      return `<div class="print"><span>${hh}</span><b>${p.symbol}</b><span class="${sideClass}">${tag} ${fmtVol(p.size)} @ ${fmtNum(p.price)}</span></div>`;
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
    ${entryPlan(row)}
    <div class="meter"><i style="width:${bar}%"></i></div>
    <div class="kv">
      <div><span>Bid / Ask</span><b>${fmtNum(row.bid)} / ${fmtNum(row.ask)}</b></div>
      <div><span>Spread</span><b>${fmtNum(row.spread, 3)}</b></div>
      <div><span>${lastSnap?.session?.label === "afterhours" ? "Vs cash close" : "Vs prev close"}</span><b>${fmtNum(row.close)}</b></div>
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

function openSp500Chart(symbol) {
  if (!symbol || lastSnap?.scan !== "sp500" || typeof openTickerChart !== "function") return false;
  openTickerChart(symbol, lastRows.find((r) => r.symbol === symbol) || (lastSnap?.tickers || []).find((r) => r.symbol === symbol));
  return true;
}

function activateTicker(symbol) {
  if (!symbol) return;
  const now = performance.now();
  if (tickerTap.symbol === symbol && now - tickerTap.t < 420) {
    tickerTap = { t: 0, symbol: null };
    if (openSp500Chart(symbol)) return;
  }
  tickerTap = { t: now, symbol };
  pinSymbol(symbol);
}

function pinSymbol(symbol) {
  if (!symbol) return;
  selected = symbol;
  const row = lastRows.find((r) => r.symbol === symbol)
    || (lastSnap?.tickers || []).find((r) => r.symbol === symbol);
  if (row) renderDetail(row);
  bubbleSim.nodes.forEach((node) => {
    node.el.classList.toggle("selected", node.symbol === symbol);
  });
  boardBody.querySelectorAll("tr[data-symbol]").forEach((tr) => {
    tr.classList.toggle("selected", tr.dataset.symbol === symbol);
  });
  etfBoard.querySelectorAll("tr[data-symbol]").forEach((tr) => {
    tr.classList.toggle("selected", tr.dataset.symbol === symbol);
  });
  overviewBoard.querySelectorAll("tr[data-symbol]").forEach((tr) => {
    tr.classList.toggle("selected", tr.dataset.symbol === symbol);
  });
  midBoard.querySelectorAll("tr[data-symbol]").forEach((tr) => {
    tr.classList.toggle("selected", tr.dataset.symbol === symbol);
  });
  entryBoard?.querySelectorAll("[data-symbol]").forEach((el) => {
    el.classList.toggle("selected", el.dataset.symbol === symbol);
  });
  if (viewMode === "prints" && lastSnap) {
    renderPrintsBoard(lastSnap, lastRows, symbol);
    return;
  }
  printsBoard.querySelectorAll("[data-symbol]").forEach((el) => {
    el.classList.toggle("selected", el.dataset.symbol === symbol);
  });
}

function bindClicks() {
  heatEl.addEventListener("click", (e) => {
    const tile = e.target.closest("[data-symbol]");
    if (tile) activateTicker(tile.dataset.symbol);
  });
  boardBody.addEventListener("click", (e) => {
    const row = e.target.closest("[data-symbol]");
    if (row) activateTicker(row.dataset.symbol);
  });
  bubbleStage.addEventListener("click", (e) => {
    if (bubbleSim.dragMoved) {
      bubbleSim.dragMoved = false;
      return;
    }
    const bubble = e.target.closest("[data-symbol]");
    if (bubble) pinSymbol(bubble.dataset.symbol);
  });
  etfBoard.addEventListener("click", (e) => {
    const group = e.target.closest("tr.etf-group");
    if (group) {
      const industry = group.dataset.industry;
      if (!industry) return;
      const now = performance.now();
      if (tickerTap.symbol === `etf:${industry}` && now - tickerTap.t < 420) {
        tickerTap = { t: 0, symbol: null };
        toggleEtfIndustry(industry);
        return;
      }
      tickerTap = { t: now, symbol: `etf:${industry}` };
      return;
    }
    const row = e.target.closest("tr[data-symbol]");
    if (row) pinSymbol(row.dataset.symbol);
  });
  overviewBoard.addEventListener("click", (e) => {
    const back = e.target.closest(".ov-back");
    if (back) {
      postScan("overview", null);
      return;
    }
    const card = e.target.closest("[data-sector]");
    if (card) {
      postScan("overview", card.dataset.sector);
      return;
    }
    const row = e.target.closest("tr[data-symbol]");
    if (row) pinSymbol(row.dataset.symbol);
  });
  midBoard.addEventListener("click", (e) => {
    const filterBtn = e.target.closest("[data-mid-filter]");
    if (filterBtn) {
      const key = filterBtn.dataset.midFilter;
      midMoverFilter = midMoverFilter === key ? null : key;
      if (midMoverFilter === "up2") {
        sortBy.value = "changePct";
        sortDir = "desc";
      } else if (midMoverFilter === "down4") {
        sortBy.value = "changePct";
        sortDir = "asc";
      }
      if (lastSnap) render(lastSnap);
      return;
    }
    const head = e.target.closest("th[data-sort]");
    if (head) {
      const key = head.dataset.sort;
      midMoverFilter = null;
      if (sortBy.value === key) {
        sortDir = sortDir === "desc" ? "asc" : "desc";
      } else {
        sortBy.value = key;
        sortDir = "desc";
      }
      if (lastSnap) render(lastSnap);
      return;
    }
    const hit = e.target.closest("[data-symbol]");
    if (hit) pinSymbol(hit.dataset.symbol);
  });
  entryBoard?.addEventListener("click", (e) => {
    const card = e.target.closest("[data-symbol]");
    if (!card) return;
    const symbol = card.dataset.symbol;
    const now = performance.now();
    if (tickerTap.symbol === symbol && now - tickerTap.t < 420) {
      tickerTap = { t: 0, symbol: null };
      const row = lastRows.find((item) => item.symbol === symbol);
      if (typeof openTickerChart === "function") openTickerChart(symbol, row);
      return;
    }
    tickerTap = { t: now, symbol };
    pinSymbol(symbol);
  });
  printsBoard.addEventListener("click", (e) => {
    const row = e.target.closest("[data-symbol]");
    if (row) pinSymbol(row.dataset.symbol);
  });
  printLookupForm?.addEventListener("submit", (e) => {
    e.preventDefault();
    const symbol = (printTicker?.value || "").trim().toUpperCase().replace(/\./g, " ").replace(/\s+/g, " ");
    if (!symbol) return;
    if (printLookupMsg) printLookupMsg.textContent = "";
    fetch(`${API_BASE}/api/watch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol }),
    })
      .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
      .then(({ ok, data }) => {
        if (!ok || !data.ok) {
          if (printLookupMsg) printLookupMsg.textContent = data.error || "Could not watch that ticker.";
          return;
        }
        watchedSymbols = [data.symbol, ...watchedSymbols.filter((item) => item !== data.symbol)].slice(0, 12);
        if (printTicker) printTicker.value = data.symbol;
        viewMode = "prints";
        document.querySelectorAll(".view").forEach((item) => item.classList.toggle("on", item.dataset.view === "prints"));
        pinSymbol(data.symbol);
        if (lastSnap) render(lastSnap);
      })
      .catch(() => {
        if (printLookupMsg) printLookupMsg.textContent = "Could not watch that ticker.";
      });
  });
  printsBtn?.addEventListener("click", () => {
    viewMode = "prints";
    document.querySelectorAll(".view").forEach((item) => item.classList.toggle("on", item.dataset.view === "prints"));
    if (lastSnap) render(lastSnap);
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
      if (!btn.dataset.scan) return;
      if (viewMode === "prints") {
        viewMode = "bubbles";
        document.querySelectorAll(".view").forEach((item) => {
          item.classList.toggle("on", item.dataset.view === "bubbles");
        });
      }
      postScan(btn.dataset.scan, null);
    });
  });
  sortBy?.addEventListener("change", () => {
    sortDir = "desc";
    if (lastSnap) render(lastSnap);
  });
  filterEl?.addEventListener("input", () => {
    if (lastSnap) render(lastSnap);
  });
  bindConnectModal();
}

function bindConnectModal() {
  const modal = document.getElementById("connectModal");
  const form = document.getElementById("connectForm");
  const status = document.getElementById("connectStatus");
  const submit = document.getElementById("connectSubmit");
  if (!modal || !form) return;

  function loadSaved() {
    try {
      return JSON.parse(localStorage.getItem("vp_gateway") || "null");
    } catch {
      return null;
    }
  }

  function fillForm() {
    const saved = loadSaved();
    const host = saved?.host || lastSnap?.host || "127.0.0.1";
    const port = String(saved?.port || lastSnap?.port || 4001);
    const clientId = saved?.clientId ?? lastSnap?.clientId ?? 7;
    const dataType = String(saved?.marketDataType || lastSnap?.marketDataType || 3);
    document.getElementById("gwHost").value = host;
    const portEl = document.getElementById("gwPort");
    if (![...portEl.options].some((opt) => opt.value === port)) {
      portEl.add(new Option(port, port));
    }
    portEl.value = port;
    document.getElementById("gwClient").value = clientId;
    document.getElementById("gwData").value = dataType === "1" ? "1" : "3";
    status.textContent = "";
  }

  document.getElementById("linkChip").addEventListener("click", () => {
    fillForm();
    modal.showModal();
  });
  document.getElementById("connectCancel").addEventListener("click", () => modal.close());
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const payload = {
      host: document.getElementById("gwHost").value.trim() || "127.0.0.1",
      port: Number(document.getElementById("gwPort").value),
      clientId: Number(document.getElementById("gwClient").value),
      marketDataType: Number(document.getElementById("gwData").value),
    };
    status.textContent = "Connecting to Gateway…";
    submit.disabled = true;
    try {
      const res = await fetch(`${API_BASE}/api/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!data.ok) {
        status.textContent = data.error || "Could not connect.";
        return;
      }
      localStorage.setItem("vp_gateway", JSON.stringify(payload));
      status.textContent = `Connected to ${data.host}:${data.port}.`;
      setTimeout(() => modal.close(), 700);
    } catch {
      status.textContent = "Could not reach the Volume Pulse server. Run python run.py locally.";
    } finally {
      submit.disabled = false;
    }
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
