/**
 * charts.js — прости графики върху canvas 2D (без външни библиотеки).
 */
const Charts = {
  COLORS: {
    grid: "#242e3c",
    axis: "#3d4d63",
    text: "#7f90a8",
    line1: "#39c2ff",
    line2: "#f0c04a",
    line3: "#5fd787",
    marker: "#ff7a7a",
  },

  /** Подготвя canvas за HiDPI и връща контекст + размери. */
  prepare(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width;
    const h = canvas.height;
    if (canvas.dataset.dpr !== String(dpr)) {
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.dataset.dpr = String(dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return { ctx, w, h };
  },

  /**
   * Линейна графика.
   * series: [{name, color, points: [[x, y], ...]}]
   * options: {yMin, yMax, markers: [{x, label, color}]}
   */
  line(canvas, series, options = {}) {
    const { ctx, w, h } = this.prepare(canvas);
    const pad = { l: 44, r: 10, t: 12, b: 26 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;

    const allPoints = series.flatMap((s) => s.points || []);
    if (!allPoints.length) {
      ctx.fillStyle = this.COLORS.text;
      ctx.font = "12px Segoe UI, sans-serif";
      ctx.fillText("няма данни", pad.l, pad.t + 20);
      return;
    }

    let xMin = Math.min(...allPoints.map((p) => p[0]));
    let xMax = Math.max(...allPoints.map((p) => p[0]));
    let yMin = options.yMin !== undefined
      ? options.yMin : Math.min(...allPoints.map((p) => p[1]));
    let yMax = options.yMax !== undefined
      ? options.yMax : Math.max(...allPoints.map((p) => p[1]));
    if (xMax - xMin < 1e-6) xMax = xMin + 1;
    if (yMax - yMin < 1e-6) yMax = yMin + 1;
    yMin = Math.max(0, yMin - (yMax - yMin) * 0.08);
    yMax = yMax + (yMax - yMin) * 0.08;

    const sx = (x) => pad.l + (x - xMin) / (xMax - xMin) * plotW;
    const sy = (y) => pad.t + plotH - (y - yMin) / (yMax - yMin) * plotH;

    ctx.strokeStyle = this.COLORS.grid;
    ctx.lineWidth = 1;
    ctx.font = "10px Segoe UI, sans-serif";
    ctx.fillStyle = this.COLORS.text;
    const yTicks = 4;
    for (let i = 0; i <= yTicks; i++) {
      const y = pad.t + plotH * i / yTicks;
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(pad.l + plotW, y);
      ctx.stroke();
      const value = yMax - (yMax - yMin) * i / yTicks;
      ctx.fillText(value.toFixed(value > 100 ? 0 : 1), 4, y + 3);
    }
    const xTicks = 4;
    for (let i = 0; i <= xTicks; i++) {
      const x = pad.l + plotW * i / xTicks;
      ctx.beginPath();
      ctx.moveTo(x, pad.t);
      ctx.lineTo(x, pad.t + plotH);
      ctx.stroke();
      const value = xMin + (xMax - xMin) * i / xTicks;
      ctx.fillText(value.toFixed(0), x - 8, h - 8);
    }

    ctx.strokeStyle = this.COLORS.axis;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, pad.t + plotH);
    ctx.lineTo(pad.l + plotW, pad.t + plotH);
    ctx.stroke();

    series.forEach((s) => {
      const pts = (s.points || []).filter((p) => p && Number.isFinite(p[1]));
      if (!pts.length) return;
      ctx.strokeStyle = s.color || this.COLORS.line1;
      ctx.lineWidth = 2;
      ctx.beginPath();
      let started = false;
      pts.forEach(([x, y]) => {
        const px = sx(x);
        const py = sy(y);
        if (!started) { ctx.moveTo(px, py); started = true; }
        else { ctx.lineTo(px, py); }
      });
      ctx.stroke();
    });

    (options.markers || []).forEach((m) => {
      const x = sx(m.x);
      ctx.strokeStyle = m.color || this.COLORS.marker;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(x, pad.t);
      ctx.lineTo(x, pad.t + plotH);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = m.color || this.COLORS.marker;
      ctx.font = "10px Segoe UI, sans-serif";
      const labelWidth = ctx.measureText(m.label).width;
      ctx.fillText(m.label, Math.min(x + 3, pad.l + plotW - labelWidth),
                   pad.t + 10);
    });

    let lx = pad.l + 8;
    const ly = pad.t + plotH - 8;
    ctx.font = "10px Segoe UI, sans-serif";
    series.forEach((s) => {
      if (!s.name) return;
      ctx.fillStyle = s.color || this.COLORS.line1;
      ctx.fillRect(lx, ly - 7, 9, 3);
      ctx.fillStyle = this.COLORS.text;
      ctx.fillText(s.name, lx + 13, ly - 2);
      lx += 13 + ctx.measureText(s.name).width + 14;
    });
  },

  /** Чертае контур на профил (нормализирани координати 0..1). */
  airfoil(canvas, upper, lower, meta) {
    const { ctx, w, h } = this.prepare(canvas);
    const pad = 14;
    const plotW = w - 2 * pad;
    const plotH = h - 2 * pad - 12;

    ctx.strokeStyle = "#243044";
    ctx.lineWidth = 1;
    for (let i = 1; i < 4; i++) {
      const y = pad + plotH * i / 4;
      ctx.beginPath();
      ctx.moveTo(pad, y);
      ctx.lineTo(pad + plotW, y);
      ctx.stroke();
    }

    if (!upper || !lower || !upper.length) {
      ctx.fillStyle = "#7f90a8";
      ctx.font = "11px Segoe UI, sans-serif";
      ctx.fillText(meta || "Няма контур за този профил", pad, h / 2);
      return;
    }

    const ys = upper.concat(lower).map((p) => p[1]);
    const yMin = Math.min(...ys);
    const yMax = Math.max(...ys);
    const span = Math.max(1e-6, yMax - yMin);
    const sy = (y) => pad + plotH - (y - yMin) / span * plotH;
    const sx = (x) => pad + x * plotW;

    ctx.beginPath();
    upper.forEach(([x, y], i) => {
      const px = sx(x), py = sy(y);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    for (let i = lower.length - 1; i >= 0; i--) {
      ctx.lineTo(sx(lower[i][0]), sy(lower[i][1]));
    }
    ctx.closePath();
    ctx.fillStyle = "rgba(57, 194, 255, 0.12)";
    ctx.fill();
    ctx.strokeStyle = "#39c2ff";
    ctx.lineWidth = 1.6;
    ctx.stroke();

    ctx.strokeStyle = "#3d4d63";
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(pad, sy(0));
    ctx.lineTo(pad + plotW, sy(0));
    ctx.stroke();
    ctx.setLineDash([]);

    if (meta) {
      ctx.fillStyle = "#7f90a8";
      ctx.font = "10px Segoe UI, sans-serif";
      ctx.fillText(meta, pad, h - 4);
    }
  },
};

