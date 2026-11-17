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

  /**
   * Логически размер (CSS px) на графиката. Канвас с `data-fluid` следва
   * ширината на родителя си; височината е `data-h` или пропорционална на
   * началните width/height атрибути. Скрит канвас (неактивен таб) запазва
   * началния размер, а CSS го разтяга до следващото прерисуване.
   */
  size(canvas) {
    const ds = canvas.dataset;
    if (!ds.baseW) {
      ds.baseW = String(canvas.width);
      ds.baseH = String(canvas.height);
    }
    const baseW = Number(ds.baseW);
    const baseH = Number(ds.baseH);
    if (ds.fluid === undefined) return [baseW, baseH];
    const box = canvas.parentNode;
    const cw = box ? Math.floor(box.clientWidth || 0) : 0;
    if (cw < 60) return [baseW, baseH];
    const h = ds.h ? Number(ds.h) : Math.round(cw * baseH / baseW);
    return [cw, Math.max(80, Math.min(h, 520))];
  },

  /** Подготвя canvas за HiDPI и връща контекст + размери. */
  prepare(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const [w, h] = this.size(canvas);
    const key = `${dpr}:${w}x${h}`;
    if (canvas.dataset.dpr !== key) {
      canvas.style.width = canvas.dataset.fluid !== undefined ? "100%" : w + "px";
      canvas.style.height = canvas.dataset.fluid !== undefined ? "auto" : h + "px";
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.dataset.dpr = key;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return { ctx, w, h };
  },

  /** Кръгла стъпка на деленията (1, 2, 2.5 или 5 × 10ⁿ), ≥ raw. */
  niceStep(raw) {
    if (!(raw > 0)) return 1;
    const pow = Math.pow(10, Math.floor(Math.log10(raw)));
    const f = raw / pow;
    const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
    return nice * pow;
  },

  /**
   * Линейна графика.
   * series: [{name, color, points: [[x, y], ...]}]
   * options: {yMin, yMax, markers: [{x, label, color}], xLabel, yLabel}
   * xLabel / yLabel — надписите на осите с мерните единици.
   */
  line(canvas, series, options = {}) {
    const { ctx, w, h } = this.prepare(canvas);
    // широките графики (в резултатите) — по-едър текст и по-гъста решетка
    const big = w >= 600;
    const font = (big ? 12 : 10) + "px Segoe UI, sans-serif";
    const pad = big ? { l: 52, r: 14, t: 16, b: 30 }
                    : { l: 44, r: 10, t: 12, b: 26 };
    // място за надписите на осите (с мерните единици)
    if (options.yLabel) pad.l += big ? 18 : 14;
    if (options.xLabel) pad.b += big ? 18 : 14;
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
    ctx.font = font;
    ctx.fillStyle = this.COLORS.text;
    const yTicks = big ? 5 : 4;
    for (let i = 0; i <= yTicks; i++) {
      const y = pad.t + plotH * i / yTicks;
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(pad.l + plotW, y);
      ctx.stroke();
      const value = yMax - (yMax - yMin) * i / yTicks;
      const text = value.toFixed(value > 100 ? 0 : 1);
      ctx.textAlign = "right";
      ctx.fillText(text, pad.l - 6, y + (big ? 4 : 3));
      ctx.textAlign = "left";
    }
    // кръгли деления по X (1, 2, 2.5, 5 × 10ⁿ), а не равни части от обхвата
    const xStep = this.niceStep((xMax - xMin) / (big ? 8 : 4));
    const xDigits = Number.isInteger(Math.round(xStep * 1000) / 1000) ? 0 : 1;
    for (let value = Math.ceil(xMin / xStep - 1e-9) * xStep;
      value <= xMax + 1e-9; value += xStep) {
      const x = sx(value);
      ctx.beginPath();
      ctx.moveTo(x, pad.t);
      ctx.lineTo(x, pad.t + plotH);
      ctx.stroke();
      ctx.textAlign = "center";
      ctx.fillText(value.toFixed(xDigits), x, pad.t + plotH + (big ? 17 : 14));
      ctx.textAlign = "left";
    }

    // надписи на осите с мерните единици
    ctx.fillStyle = "#a9b8cc";
    if (options.xLabel) {
      ctx.textAlign = "center";
      ctx.fillText(options.xLabel, pad.l + plotW / 2, h - 6);
      ctx.textAlign = "left";
    }
    if (options.yLabel) {
      ctx.save();
      ctx.translate(big ? 14 : 11, pad.t + plotH / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = "center";
      ctx.fillText(options.yLabel, 0, 0);
      ctx.restore();
    }
    ctx.fillStyle = this.COLORS.text;

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
      ctx.font = font;
      const labelWidth = ctx.measureText(m.label).width;
      ctx.fillText(m.label, Math.min(x + 3, pad.l + plotW - labelWidth),
                   pad.t + (big ? 13 : 10));
    });

    let lx = pad.l + 8;
    const ly = pad.t + plotH - 8;
    ctx.font = font;
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

  /**
   * Страничен изглед на тялото: форма, крило, батерия, мотор и опашка.
   * Ползва същите числа, с които смята backend-ът (без собствена физика).
   */
  fuselageSide(canvas, res) {
    if (!canvas || !res || !res.ok) return;
    const g = res.geometry || {};
    const fus = g.fuselage || {};
    const lay = res.layout || {};
    const stab = res.stability || {};
    const prop = res.propulsion || {};
    const L = Number(fus.length_mm) || 0;
    if (L <= 0) return;

    const { ctx, w, h } = this.prepare(canvas);
    const pad = { l: 8, r: 8, t: 10, b: 16 };
    const scale = (w - pad.l - pad.r) / L;
    const baseY = h - pad.b - 10;
    const z0 = baseY - (Number(fus.height_mm) || 0) * scale * 0.5;

    // Същата функция като fuselage.radius_factor
    const rf = (t) => {
      const nose = Number(fus.nose_ratio) || 0.14;
      const cabin = Number(fus.cabin_ratio) || 0.42;
      const taper = Number(fus.tail_taper) || 0.38;
      if (t <= 0) return 0.05;
      if (t < nose) return 0.30 + 0.70 * Math.sin(t / nose * Math.PI / 2);
      if (t < cabin) return 1.0;
      const u = (t - cabin) / Math.max(1e-6, 1 - cabin);
      return 1 - (1 - taper) * Math.pow(u, 1.25);
    };
    const X = (mm) => pad.l + mm * scale;
    const Z = (mm) => z0 - mm * scale;

    // земя
    ctx.strokeStyle = this.COLORS.grid;
    ctx.beginPath();
    ctx.moveTo(pad.l, baseY + 6);
    ctx.lineTo(w - pad.r, baseY + 6);
    ctx.stroke();

    // тяло
    const H = Number(fus.height_mm) || 0;
    ctx.beginPath();
    for (let i = 0; i <= 60; i++) {
      const t = i / 60;
      const zt = Z(rf(t) * H / 2);
      if (i === 0) ctx.moveTo(X(t * L), zt); else ctx.lineTo(X(t * L), zt);
    }
    for (let i = 60; i >= 0; i--) {
      const t = i / 60;
      ctx.lineTo(X(t * L), Z(-rf(t) * H / 2));
    }
    ctx.closePath();
    ctx.fillStyle = "rgba(207, 216, 227, 0.16)";
    ctx.fill();
    ctx.strokeStyle = "#cfd8e3";
    ctx.lineWidth = 1.4;
    ctx.stroke();

    // крило (височината идва от отместването, не от класа)
    const wingLe = Number(g.wing_le_mm) || 0;
    const cRoot = Number(g.c_root_mm) || 0;
    const zWing = lay.wing_z_mm !== undefined && lay.wing_z_mm !== null
      ? Z(lay.wing_z_mm)
      : Z((lay.wing_position === "mid" ? 0.50
        : lay.wing_position === "low" ? 0.18 : 0.92) * H);
    ctx.strokeStyle = "#4db3e6";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(X(wingLe), zWing);
    ctx.lineTo(X(wingLe + cRoot), zWing);
    ctx.stroke();

    // батерия
    const box = fus.battery_box_mm || [];
    const bx = Number(stab.battery_x_placed_mm);
    if (box.length === 3 && Number.isFinite(bx)) {
      const bl = box[0] * scale;
      const bh = Math.max(3, box[2] * scale);
      ctx.fillStyle = "rgba(95, 215, 135, 0.35)";
      ctx.strokeStyle = "#5fd787";
      ctx.lineWidth = 1;
      ctx.fillRect(X(bx) - bl / 2, z0 - bh / 2, bl, bh);
      ctx.strokeRect(X(bx) - bl / 2, z0 - bh / 2, bl, bh);
    }

    // опашка
    const tail = g.tail || {};
    const tailX = (chord) => Math.max(
      wingLe + cRoot, (Number(tail.tail_ac_mm) || 0) - 0.25 * chord);
    const cV = Number(tail.c_v_mm) || 0;
    const bV = Number(tail.b_v_mm) || 0;
    if (cV > 0) {
      const xTailMm = tailX(cV);
      const zFinBase = z0 - rf(Math.min(1, xTailMm / L)) * H / 2;
      const xv = X(xTailMm);
      ctx.fillStyle = "rgba(143, 162, 186, 0.35)";
      ctx.strokeStyle = "#8fa2ba";
      ctx.beginPath();
      ctx.moveTo(xv, zFinBase);
      ctx.lineTo(xv + cV * scale, zFinBase);
      ctx.lineTo(xv + cV * 0.55 * scale, zFinBase - bV * scale);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
    const cH = Number(tail.c_h_mm) || 0;
    if (cH > 0) {
      const xTailMm = tailX(cH);
      const zStab = z0 - rf(Math.min(1, xTailMm / L)) * H / 2;
      ctx.strokeStyle = "#9fb0c6";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(X(xTailMm), zStab);
      ctx.lineTo(X(xTailMm + cH), zStab);
      ctx.stroke();
    }

    // витло
    const dProp = (Number(prop.prop_d_in) || 0) * 25.4;
    if (dProp > 0 && lay.propulsion !== "twin") {
      const xProp = lay.propulsion === "pusher" ? 0.985 * L : 0.02 * L;
      ctx.strokeStyle = "#f0c04a";
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(X(xProp), z0 - dProp * scale / 2);
      ctx.lineTo(X(xProp), z0 + dProp * scale / 2);
      ctx.stroke();
    }

    ctx.fillStyle = this.COLORS.text;
    ctx.font = "10px Segoe UI, sans-serif";
    ctx.fillText(`${fmt0(L)} × ${fmt0(fus.width_mm)} × ${fmt0(H)} mm`,
                 pad.l, h - 3);
  },

  // ------------------------------------------------- спар и джойнер

  SPAR: {
    skin: "#7fb2ff",
    skinFill: "rgba(57, 194, 255, .07)",
    cap: "#f0a64a",
    strip: "#d6dee8",
    stripEdge: "#ffffff",
    bore: "#8ea0b8",
    tube: { carbon: "#5a6573", aluminium: "#aeb9c5", fibreglass: "#d9cf9a",
            steel: "#8d98a5", wood: "#b0884f" },
  },

  _emptySpar(ctx, w, h, text) {
    ctx.fillStyle = this.COLORS.text;
    ctx.font = "12px Segoe UI, sans-serif";
    ctx.fillText(text, 14, h / 2);
  },

  /** Път на контура на профила (mm → px чрез fx/fy). */
  _sparOutline(ctx, view, fx, fy) {
    const pts = view.upper.concat(view.lower.slice().reverse());
    ctx.beginPath();
    pts.forEach(([x, y], i) => {
      if (i === 0) ctx.moveTo(fx(x), fy(y));
      else ctx.lineTo(fx(x), fy(y));
    });
    ctx.closePath();
  },

  /** Капси, лента и джойнер в координати на сечението (mm). */
  _sparParts(ctx, view, fx, fy, s) {
    const C = this.SPAR;
    const cap = view.cap;
    const wall = view.wall_mm;
    const x0 = cap.x_mm - cap.width_mm / 2;
    const ranges = cap.strips === 2
      ? [[x0, x0 + cap.strip_width_mm],
         [x0 + cap.width_mm - cap.strip_width_mm, x0 + cap.width_mm]]
      : [[x0, x0 + cap.width_mm]];
    const rect = (xa, ya, xb, yb, fill, edge) => {
      const px = fx(Math.min(xa, xb));
      const py = fy(Math.max(ya, yb));
      const pw = Math.abs(fx(xb) - fx(xa));
      const ph = Math.abs(fy(yb) - fy(ya));
      ctx.fillStyle = fill;
      ctx.fillRect(px, py, Math.max(1, pw), Math.max(1, ph));
      if (edge) {
        ctx.strokeStyle = edge;
        ctx.lineWidth = 1;
        ctx.strokeRect(px, py, Math.max(1, pw), Math.max(1, ph));
      }
    };
    [[cap.y_top_mm, -1], [cap.y_bottom_mm, 1]].forEach(([base, dir]) => {
      const yIn = base + dir * wall;
      ranges.forEach(([xa, xb]) => {
        rect(xa, yIn, xb, yIn + dir * cap.thickness_mm, C.cap);
      });
      const cb = view.carbon;
      if (cb.needed && cb.width_mm) {
        const t = (cb.thickness_mm || 0.5) * (cb.count || 1);
        rect(cap.x_mm - cb.width_mm / 2, yIn,
             cap.x_mm + cb.width_mm / 2, yIn + dir * t, C.strip, C.stripEdge);
      }
    });
    const j = view.joiner;
    if (j) {
      const cx = fx(j.x_mm);
      const cy = fy(j.y_mm);
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = j.ok ? C.bore : this.COLORS.marker;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(cx, cy, Math.max(1.5, j.bore_mm / 2 * s), 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = C.tube[j.material] || C.tube.carbon;
      ctx.beginPath();
      ctx.arc(cx, cy, Math.max(1, j.od_mm / 2 * s), 0, Math.PI * 2);
      if (j.id_mm) {
        ctx.arc(cx, cy, Math.max(0.5, j.id_mm / 2 * s), 0, Math.PI * 2, true);
      }
      ctx.fill("evenodd");
      ctx.strokeStyle = "#dfe5ee";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(cx, cy, Math.max(1, j.od_mm / 2 * s), 0, Math.PI * 2);
      ctx.stroke();
    }
  },

  /**
   * Кореново сечение на крилото: горе целият профил в мащаб 1:1 (с рамка
   * на увеличения участък), долу — увеличен детайл около спара и джойнера.
   * view = structure_view от compute_design (printgeom.spar_section).
   */
  sparSection(canvas, view) {
    if (!canvas) return;
    const { ctx, w, h } = this.prepare(canvas);
    if (!view || !view.upper || !view.upper.length) {
      this._emptySpar(ctx, w, h, "Схемата ще се появи след изчислението");
      return;
    }
    const C = this.SPAR;
    const chord = view.chord_mm;
    const ys = view.upper.concat(view.lower).map((p) => p[1]);
    const yMin = Math.min(...ys);
    const yMax = Math.max(...ys);
    const font = (w >= 500 ? 11 : 10) + "px Segoe UI, sans-serif";

    // --- горе: целият профил (еднакъв мащаб по x и y)
    const pad = 12;
    const topH = Math.min(h * 0.36, (w - 2 * pad) / chord * (yMax - yMin) + 36);
    const s1 = Math.min((w - 2 * pad) / chord, (topH - 36) / (yMax - yMin));
    const ox1 = (w - chord * s1) / 2;
    const oy1 = 26 + yMax * s1;
    const f1x = (x) => ox1 + x * s1;
    const f1y = (y) => oy1 - y * s1;
    this._sparOutline(ctx, view, f1x, f1y);
    ctx.fillStyle = C.skinFill;
    ctx.fill();
    ctx.strokeStyle = C.skin;
    ctx.lineWidth = 1.3;
    ctx.stroke();
    this._sparParts(ctx, view, f1x, f1y, s1);

    // участък за увеличение: капсите + каналът, с малко поле
    const cap = view.cap;
    const j = view.joiner;
    let xa = cap.x_mm - cap.width_mm / 2;
    let xb = cap.x_mm + cap.width_mm / 2;
    if (j) {
      xa = Math.min(xa, j.x_mm - j.bore_mm / 2);
      xb = Math.max(xb, j.x_mm + j.bore_mm / 2);
    }
    const margin = Math.max(4, (xb - xa) * 0.25);
    xa = Math.max(0, xa - margin);
    xb = Math.min(chord, xb + margin);
    ctx.strokeStyle = "#5d7d99";
    ctx.setLineDash([4, 3]);
    ctx.strokeRect(f1x(xa), f1y(yMax) - 3, (xb - xa) * s1, (yMax - yMin) * s1 + 6);
    ctx.setLineDash([]);
    ctx.fillStyle = this.COLORS.text;
    ctx.font = font;
    ctx.fillText(`хорда ${fmt0(chord)} mm · ${view.airfoil.toUpperCase()}`, pad, 12);

    // --- долу: детайл (еднакъв мащаб, вписан в оставащата площ)
    const top2 = topH + 18;
    const boxH = h - top2 - 18;
    const s2 = Math.min((w - 2 * pad - 150) / (xb - xa), boxH / (yMax - yMin));
    const ox2 = pad + (w - 2 * pad - 150 - (xb - xa) * s2) / 2 - xa * s2;
    const oy2 = top2 + (boxH - (yMax - yMin) * s2) / 2 + yMax * s2;
    const f2x = (x) => ox2 + x * s2;
    const f2y = (y) => oy2 - y * s2;
    ctx.save();
    ctx.beginPath();
    ctx.rect(f2x(xa), top2 - 4, (xb - xa) * s2, boxH + 8);
    ctx.clip();
    this._sparOutline(ctx, view, f2x, f2y);
    ctx.fillStyle = C.skinFill;
    ctx.fill();
    ctx.strokeStyle = C.skin;
    ctx.lineWidth = 1.6;
    ctx.stroke();
    this._sparParts(ctx, view, f2x, f2y, s2);
    ctx.restore();
    ctx.strokeStyle = "#2b3444";
    ctx.strokeRect(f2x(xa), top2 - 4, (xb - xa) * s2, boxH + 8);

    // височина на спара (между външните повърхности на капсите)
    const xd = f2x(xb) + 10;
    ctx.strokeStyle = this.COLORS.text;
    ctx.beginPath();
    ctx.moveTo(xd, f2y(cap.y_top_mm));
    ctx.lineTo(xd, f2y(cap.y_bottom_mm));
    ctx.moveTo(xd - 4, f2y(cap.y_top_mm));
    ctx.lineTo(xd + 4, f2y(cap.y_top_mm));
    ctx.moveTo(xd - 4, f2y(cap.y_bottom_mm));
    ctx.lineTo(xd + 4, f2y(cap.y_bottom_mm));
    ctx.stroke();

    // легенда вдясно от детайла
    const lx = xd + 16;
    let ly = top2 + 6;
    const item = (color, text, ring) => {
      if (ring) {
        ctx.strokeStyle = color;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.arc(lx + 5, ly - 4, 5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      } else {
        ctx.fillStyle = color;
        ctx.fillRect(lx, ly - 9, 10, 10);
      }
      ctx.fillStyle = this.COLORS.text;
      ctx.fillText(text, lx + 16, ly);
      ly += 17;
    };
    ctx.font = font;
    ctx.fillStyle = this.COLORS.text;
    ctx.fillText(`h = ${fmt(view.spar_height_mm, 1)} mm`, lx, ly);
    ly += 20;
    item(C.cap, "печатан капс");
    if (view.carbon.needed) item(C.strip, "лента на спара");
    if (j) {
      item(C.tube[j.material] || C.tube.carbon, "джойнер ⌀" + fmt(j.od_mm, 0));
      item(j.ok ? C.bore : this.COLORS.marker, "канал ⌀" + fmt(j.bore_mm, 1), true);
    }
  },

  /**
   * Изглед отгоре на цялото крило: спарът по размаха и джойнерът през
   * корена (по L/2 във всяка половина). Схема без тялото, предният ръб прав.
   */
  sparPlan(canvas, view) {
    if (!canvas) return;
    const { ctx, w, h } = this.prepare(canvas);
    if (!view || !view.planform) {
      this._emptySpar(ctx, w, h, "Схемата ще се появи след изчислението");
      return;
    }
    const C = this.SPAR;
    const pf = view.planform;
    const semi = pf.semispan_mm;
    const cr = pf.c_root_mm;
    const ct = pf.c_tip_mm || cr;
    const font = (w >= 500 ? 11 : 10) + "px Segoe UI, sans-serif";
    const pad = { l: 12, r: 12, t: 20, b: 22 };
    const s = Math.min((w - pad.l - pad.r) / (2 * semi), (h - pad.t - pad.b) / cr);
    const cx = w / 2;
    const top = pad.t + ((h - pad.t - pad.b) - cr * s) / 2;
    const X = (span) => cx + span * s;          // span: −semi…+semi
    const Y = (chordPos) => top + chordPos * s;  // от предния ръб надолу
    const chordAt = (span) => cr + (ct - cr) * Math.abs(span) / semi;

    // контур на крилото
    ctx.beginPath();
    ctx.moveTo(X(-semi), Y(0));
    ctx.lineTo(X(semi), Y(0));
    ctx.lineTo(X(semi), Y(ct));
    ctx.lineTo(X(0), Y(cr));
    ctx.lineTo(X(-semi), Y(ct));
    ctx.closePath();
    ctx.fillStyle = C.skinFill;
    ctx.fill();
    ctx.strokeStyle = C.skin;
    ctx.lineWidth = 1.3;
    ctx.stroke();
    // делителна линия между двете половини
    ctx.strokeStyle = "#3d4d63";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(X(0), Y(0) - 6);
    ctx.lineTo(X(0), Y(cr) + 6);
    ctx.stroke();
    ctx.setLineDash([]);

    // спар: ос на капсите (30 % хорда) по целия размах
    const frac = view.cap.x_mm / cr;
    const capW = Math.max(2, view.cap.width_mm * s);
    ctx.strokeStyle = C.cap;
    ctx.lineWidth = capW;
    ctx.globalAlpha = 0.75;
    ctx.beginPath();
    ctx.moveTo(X(-semi), Y(frac * chordAt(semi)));
    ctx.lineTo(X(0), Y(frac * cr));
    ctx.lineTo(X(semi), Y(frac * chordAt(semi)));
    ctx.stroke();
    ctx.globalAlpha = 1;
    if (view.carbon.needed) {
      ctx.strokeStyle = C.strip;
      ctx.lineWidth = Math.max(1.5, (view.carbon.width_mm || 3) * s);
      ctx.beginPath();
      ctx.moveTo(X(-semi), Y(frac * chordAt(semi)));
      ctx.lineTo(X(0), Y(frac * cr));
      ctx.lineTo(X(semi), Y(frac * chordAt(semi)));
      ctx.stroke();
    }

    // джойнер: тръба през корена, по L/2 във всяка половина
    const j = view.joiner;
    ctx.font = font;
    if (j && j.length_mm) {
      const half = j.length_mm / 2;
      const jy = Y(j.x_mm);
      const jh = Math.max(3, j.od_mm * s);
      ctx.fillStyle = C.tube[j.material] || C.tube.carbon;
      ctx.fillRect(X(-half), jy - jh / 2, half * 2 * s, jh);
      ctx.strokeStyle = "#dfe5ee";
      ctx.lineWidth = 1;
      ctx.strokeRect(X(-half), jy - jh / 2, half * 2 * s, jh);
      // размер на джойнера
      const dy = Y(cr) + 12;
      ctx.strokeStyle = this.COLORS.text;
      ctx.beginPath();
      ctx.moveTo(X(-half), dy);
      ctx.lineTo(X(half), dy);
      ctx.moveTo(X(-half), dy - 4);
      ctx.lineTo(X(-half), dy + 4);
      ctx.moveTo(X(half), dy - 4);
      ctx.lineTo(X(half), dy + 4);
      ctx.stroke();
      ctx.fillStyle = this.COLORS.text;
      const label = `джойнер ${fmt0(j.length_mm)} mm`;
      ctx.fillText(label, X(half) + 8, dy + 4);
    }
    ctx.fillStyle = this.COLORS.text;
    ctx.fillText(`размах ${fmt0(semi * 2)} mm · спар на ${fmt0(frac * 100)} % хорда`,
                 pad.l, 13);
  },
};

