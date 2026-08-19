function createBubbleField(canvas) {
  if (!canvas || typeof canvas.getContext !== "function") {
    return {
      setData() {},
      setSelected() {},
      onSelect() {},
      start() {},
      stop() {},
      resize() {},
    };
  }
  const ctx = canvas.getContext("2d");
  const nodes = new Map();
  let selected = null;
  let active = false;
  let width = 0;
  let height = 0;
  let dpr = 1;
  let raf = 0;
  let hover = null;
  let onSelect = () => {};

  function volumeOf(row) {
    return Math.max(0, row.extVolume || row.volume || 0);
  }

  function resize() {
    const parent = canvas.parentElement;
    const nextW = Math.max(320, parent.clientWidth || 640);
    const nextH = 560;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (width === nextW && height === nextH && canvas.width === Math.floor(nextW * dpr)) {
      return;
    }
    width = nextW;
    height = nextH;
    canvas.width = Math.floor(nextW * dpr);
    canvas.height = Math.floor(nextH * dpr);
    canvas.style.width = `${nextW}px`;
    canvas.style.height = `${nextH}px`;
  }

  function spawn(symbol) {
    const angle = Math.random() * Math.PI * 2;
    const dist = Math.min(width, height) * (0.18 + Math.random() * 0.22);
    return {
      symbol,
      x: width / 2 + Math.cos(angle) * dist,
      y: height / 2 + Math.sin(angle) * dist,
      vx: (Math.random() - 0.5) * 0.6,
      vy: (Math.random() - 0.5) * 0.6,
      r: 8,
      tr: 24,
      row: null,
    };
  }

  function setData(rows, selectedSymbol) {
    selected = selectedSymbol;
    const maxVol = Math.max(1, ...rows.map(volumeOf));
    const maxR = Math.min(width, height) * 0.17;
    const minR = 20;
    const keep = new Set();
    for (const row of rows) {
      keep.add(row.symbol);
      let node = nodes.get(row.symbol);
      if (!node) {
        node = spawn(row.symbol);
        nodes.set(row.symbol, node);
      }
      node.row = row;
      const unit = Math.sqrt(volumeOf(row) / maxVol);
      node.tr = minR + unit * (maxR - minR);
    }
    for (const symbol of [...nodes.keys()]) {
      if (!keep.has(symbol)) nodes.delete(symbol);
    }
  }

  function step() {
    const cx = width / 2;
    const cy = height * 0.46;
    const list = [...nodes.values()];
    const maxR = Math.min(width, height) * 0.17 || 80;

    for (const node of list) {
      node.r += (node.tr - node.r) * 0.08;
      const weight = 0.35 + node.r / maxR;
      node.vx += (cx - node.x) * 0.006 * weight;
      node.vy += (cy - node.y) * 0.005 * weight;
      node.vy += 0.14 * (node.r / maxR);
      node.vx += Math.sin((performance.now() / 900) + node.x * 0.02) * 0.08;
      node.vy += Math.cos((performance.now() / 1100) + node.y * 0.02) * 0.05;
      node.vx *= 0.88;
      node.vy *= 0.88;
      node.x += node.vx;
      node.y += node.vy;
    }

    for (let i = 0; i < list.length; i += 1) {
      for (let j = i + 1; j < list.length; j += 1) {
        const a = list[i];
        const b = list[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.hypot(dx, dy) || 0.001;
        const minDist = a.r + b.r + 10;
        if (dist >= minDist) continue;
        const nx = dx / dist;
        const ny = dy / dist;
        const overlap = minDist - dist;
        const massA = a.r * a.r;
        const massB = b.r * b.r;
        const total = massA + massB || 1;
        a.x -= nx * overlap * (massB / total);
        a.y -= ny * overlap * (massB / total);
        b.x += nx * overlap * (massA / total);
        b.y += ny * overlap * (massA / total);
        const bump = overlap * 0.08;
        a.vx -= nx * bump;
        a.vy -= ny * bump;
        b.vx += nx * bump;
        b.vy += ny * bump;
      }
    }

    for (const node of list) {
      const pad = node.r + 8;
      node.x = Math.max(pad, Math.min(width - pad, node.x));
      node.y = Math.max(pad, Math.min(height - pad, node.y));
    }
  }

  function bubbleFill(changePct, alpha) {
    const t = Math.max(-1, Math.min(1, (changePct || 0) / 3.5));
    if (t >= 0) {
      return `rgba(61, 214, 140, ${0.42 + t * 0.45})`;
    }
    return `rgba(255, 93, 108, ${0.42 + Math.abs(t) * 0.45})`;
  }

  function draw() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const floor = ctx.createLinearGradient(0, height * 0.55, 0, height);
    floor.addColorStop(0, "rgba(0,0,0,0)");
    floor.addColorStop(1, "rgba(0,0,0,0.18)");
    ctx.fillStyle = floor;
    ctx.fillRect(0, 0, width, height);

    const ordered = [...nodes.values()].sort((a, b) => a.r - b.r);
    for (const node of ordered) {
      const row = node.row || {};
      const isSel = node.symbol === selected;
      const isHover = node.symbol === hover;
      const x = node.x;
      const y = node.y;
      const r = node.r;

      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y + r * 0.18, r * 0.72, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(0, 0, 0, 0.22)";
      ctx.fill();
      ctx.restore();

      const glow = ctx.createRadialGradient(x, y, r * 0.2, x, y, r);
      glow.addColorStop(0, bubbleFill(row.changePct, 1));
      glow.addColorStop(1, "rgba(16, 21, 30, 0.18)");
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = glow;
      ctx.fill();
      ctx.lineWidth = isSel ? 2.4 : isHover ? 1.6 : 1;
      ctx.strokeStyle = isSel
        ? "rgba(231, 184, 74, 0.95)"
        : isHover
          ? "rgba(231, 237, 246, 0.45)"
          : "rgba(255,255,255,0.12)";
      ctx.stroke();

      const shine = ctx.createRadialGradient(x - r * 0.28, y - r * 0.32, 2, x - r * 0.1, y - r * 0.15, r * 0.7);
      shine.addColorStop(0, "rgba(255,255,255,0.22)");
      shine.addColorStop(1, "rgba(255,255,255,0)");
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = shine;
      ctx.fill();

      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#e7edf6";
      ctx.font = `600 ${Math.max(10, Math.min(18, r * 0.34))}px "IBM Plex Mono", monospace`;
      ctx.fillText(node.symbol, x, y - (r > 36 ? 7 : 0));
      if (r > 34) {
        ctx.font = `500 ${Math.max(9, r * 0.18)}px "IBM Plex Mono", monospace`;
        ctx.fillStyle = row.changePct >= 0 ? "#3dd68c" : "#ff5d6c";
        ctx.fillText(signedPct(row.changePct), x, y + 10);
      }
      if (r > 48) {
        ctx.fillStyle = "rgba(231, 237, 246, 0.72)";
        ctx.font = `500 ${Math.max(9, r * 0.16)}px "IBM Plex Sans", sans-serif`;
        ctx.fillText(fmtVol(volumeOf(row)), x, y + 24);
      }
    }
  }

  function loop() {
    if (!active) return;
    resize();
    step();
    draw();
    raf = requestAnimationFrame(loop);
  }

  function hit(mx, my) {
    const ordered = [...nodes.values()].sort((a, b) => b.r - a.r);
    for (const node of ordered) {
      if (Math.hypot(mx - node.x, my - node.y) <= node.r) return node.symbol;
    }
    return null;
  }

  function localPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  canvas.addEventListener("click", (event) => {
    const { x, y } = localPoint(event);
    const symbol = hit(x, y);
    if (symbol) onSelect(symbol);
  });
  canvas.addEventListener("mousemove", (event) => {
    const { x, y } = localPoint(event);
    const symbol = hit(x, y);
    hover = symbol;
    canvas.style.cursor = symbol ? "pointer" : "default";
  });
  canvas.addEventListener("mouseleave", () => {
    hover = null;
  });

  return {
    setData,
    setSelected(symbol) {
      selected = symbol;
    },
    onSelect(fn) {
      onSelect = fn;
    },
    start() {
      if (active) return;
      active = true;
      resize();
      loop();
    },
    stop() {
      active = false;
      cancelAnimationFrame(raf);
    },
    resize,
  };
}
