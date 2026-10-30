/**
 * viewer3d.js — опростен 3D преглед на модела (canvas 2D, без зависимости).
 *
 * Използва ортографска проекция и „художников“ алгоритъм (сортиране по
 * дълбочина) с плоско осветяване — достатъчно, за да се видят пропорциите.
 * Геометрията идва от Python (core/geometry3d.py), за да има един източник
 * на истина с изчисленията.
 */
const Viewer = {
  canvas: null,
  ctx: null,
  model: null,
  yaw: -0.78,
  pitch: 0.36,
  zoom: 1,
  scale: 1,
  center: [0, 0, 0],
  size: [1, 1, 1],
  w: 900,
  h: 460,
  dragging: false,
  lastX: 0,
  lastY: 0,

  init() {
    this.canvas = document.getElementById("model3d");
    if (!this.canvas) return;
    this.ctx = this.canvas.getContext("2d");
    this.bind();
  },

  bind() {
    const canvas = this.canvas;

    canvas.addEventListener("mousedown", (event) => {
      this.dragging = true;
      this.lastX = event.clientX;
      this.lastY = event.clientY;
      canvas.style.cursor = "grabbing";
    });
    window.addEventListener("mouseup", () => {
      this.dragging = false;
      if (this.canvas) this.canvas.style.cursor = "grab";
    });
    window.addEventListener("mousemove", (event) => {
      if (!this.dragging) return;
      const dx = event.clientX - this.lastX;
      const dy = event.clientY - this.lastY;
      this.lastX = event.clientX;
      this.lastY = event.clientY;
      this.yaw -= dx * 0.008;
      this.pitch = Math.max(-1.35, Math.min(1.35, this.pitch + dy * 0.006));
      this.render();
    });
    canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      const factor = Math.exp(-event.deltaY * 0.0012);
      this.zoom = Math.max(0.35, Math.min(3.5, this.zoom * factor));
      this.render();
    }, { passive: false });
    canvas.addEventListener("dblclick", () => this.setView("iso"));
    canvas.style.cursor = "grab";

    window.addEventListener("resize", () => {
      if (this.model) this.render();
    });
  },

  setModel(model) {
    this.model = model;
    this.frameModel();
    this.render();
    const info = document.getElementById("modelInfo");
    if (info) {
      if (!model || !model.parts || !model.parts.length) {
        info.textContent = "няма модел";
        return;
      }
      info.textContent =
        `размах ${Math.round(model.size.span_mm)} mm · ` +
        `дължина ${Math.round(model.size.length_mm)} mm · ` +
        `${model.triangles} триъгълника`;
    }
  },

  frameModel() {
    if (!this.model || !this.model.parts.length) return;
    let minX = Infinity, minY = Infinity, minZ = Infinity;
    let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
    this.model.parts.forEach((part) => {
      const p = part.points;
      for (let i = 0; i < p.length; i += 3) {
        if (p[i] < minX) minX = p[i];
        if (p[i] > maxX) maxX = p[i];
        if (p[i + 1] < minY) minY = p[i + 1];
        if (p[i + 1] > maxY) maxY = p[i + 1];
        if (p[i + 2] < minZ) minZ = p[i + 2];
        if (p[i + 2] > maxZ) maxZ = p[i + 2];
      }
    });
    this.center = [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2];
    this.size = [maxX - minX, maxY - minY, maxZ - minZ];
  },

  setView(name) {
    const views = {
      iso: [-0.78, 0.36],
      top: [0.0, 1.35],
      side: [0.0, 0.06],
      front: [-Math.PI / 2, 0.10],
    };
    const view = views[name] || views.iso;
    this.yaw = view[0];
    this.pitch = view[1];
    this.zoom = 1;
    this.render();
  },

  prepare() {
    const canvas = this.canvas;
    const dpr = window.devicePixelRatio || 1;
    const w = 900;
    const h = 460;
    if (canvas.dataset.dpr !== String(dpr)) {
      canvas.style.width = "100%";
      canvas.style.maxWidth = w + "px";
      canvas.style.height = "auto";
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.dataset.dpr = String(dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.w = w;
    this.h = h;
    return { ctx, w, h };
  },

  project(x, y, z) {
    const cx = x - this.center[0];
    const cy = y - this.center[1];
    const cz = z - this.center[2];

    const cyaw = Math.cos(this.yaw);
    const syaw = Math.sin(this.yaw);
    const X = cx * cyaw - cy * syaw;
    const Y = cx * syaw + cy * cyaw;

    const cp = Math.cos(this.pitch);
    const sp = Math.sin(this.pitch);
    const depth = Y * cp - cz * sp;
    const up = Y * sp + cz * cp;

    const s = this.scale * this.zoom;
    return [this.w / 2 + X * s, this.h / 2 - up * s, depth];
  },

  render() {
    if (!this.ctx) return;
    const { ctx, w, h } = this.prepare();

    ctx.fillStyle = "#0e141d";
    ctx.fillRect(0, 0, w, h);

    if (!this.model || !this.model.parts || !this.model.parts.length) {
      ctx.fillStyle = "#6f8098";
      ctx.font = "12px Segoe UI, sans-serif";
      ctx.fillText("моделът ще се появи след изчислението", 16, h / 2);
      return;
    }

    const radius = 0.5 * Math.hypot(this.size[0], this.size[1], this.size[2]);
    this.scale = (Math.min(w, h) * 0.84) / (2 * (radius || 1));

    this.drawGrid(ctx);
    this.drawParts(ctx);
    this.drawDimensions(ctx);
  },

  drawGrid(ctx) {
    const span = this.size[1] || 1;
    const length = this.size[0] || 1;
    const step = Math.max(span, length) / 8;
    const y0 = this.center[1] - span / 2;
    const x0 = this.center[0] - length / 2;
    const z = 0;

    ctx.strokeStyle = "rgba(80, 105, 135, 0.32)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 8; i++) {
      const y = y0 + i * step;
      const a = this.project(x0, y, z);
      const b = this.project(x0 + length, y, z);
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
      ctx.stroke();

      const x = x0 + i * step;
      const c = this.project(x, y0, z);
      const d = this.project(x, y0 + span, z);
      ctx.beginPath();
      ctx.moveTo(c[0], c[1]);
      ctx.lineTo(d[0], d[1]);
      ctx.stroke();
    }
  },

  drawParts(ctx) {
    const light = [-0.38, -0.62, 0.68];
    const tris = [];

    this.model.parts.forEach((part) => {
      const p = part.points;
      const color = this.parseColor(part.color);
      for (let i = 0; i < p.length; i += 9) {
        const a = this.project(p[i], p[i + 1], p[i + 2]);
        const b = this.project(p[i + 3], p[i + 4], p[i + 5]);
        const c = this.project(p[i + 6], p[i + 7], p[i + 8]);
        tris.push({ a, b, c, depth: (a[2] + b[2] + c[2]) / 3, color });
      }
    });

    tris.sort((t1, t2) => t2.depth - t1.depth);

    tris.forEach((t) => {
      const ux = t.b[0] - t.a[0];
      const uy = t.b[1] - t.a[1];
      const uz = t.b[2] - t.a[2];
      const vx = t.c[0] - t.a[0];
      const vy = t.c[1] - t.a[1];
      const vz = t.c[2] - t.a[2];
      let nx = uy * vz - uz * vy;
      let ny = uz * vx - ux * vz;
      let nz = ux * vy - uy * vx;
      const len = Math.hypot(nx, ny, nz) || 1;
      nx /= len;
      ny /= len;
      nz /= len;
      const dot = Math.abs(nx * light[0] + ny * light[1] + nz * light[2]);
      const shade = 0.34 + 0.66 * dot;
      const col = "rgb(" +
        Math.round(t.color[0] * shade) + "," +
        Math.round(t.color[1] * shade) + "," +
        Math.round(t.color[2] * shade) + ")";
      ctx.fillStyle = col;
      ctx.strokeStyle = col;
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(t.a[0], t.a[1]);
      ctx.lineTo(t.b[0], t.b[1]);
      ctx.lineTo(t.c[0], t.c[1]);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    });
  },

  drawDimensions(ctx) {
    const span = this.size[1];
    const length = this.size[0];
    const zTop = this.center[2] + this.size[2] / 2;
    const xMid = this.center[0];
    const yLeft = this.center[1] - span / 2;
    const yRight = this.center[1] + span / 2;

    ctx.strokeStyle = "rgba(120, 170, 210, 0.75)";
    ctx.fillStyle = "rgba(155, 195, 230, 0.95)";
    ctx.lineWidth = 1;
    ctx.font = "11px Segoe UI, sans-serif";

    const a = this.project(xMid, yLeft, zTop);
    const b = this.project(xMid, yRight, zTop);
    ctx.beginPath();
    ctx.moveTo(a[0], a[1]);
    ctx.lineTo(b[0], b[1]);
    ctx.stroke();
    ctx.fillText(`размах ${Math.round(span)} mm`,
                 (a[0] + b[0]) / 2 - 42, Math.min(a[1], b[1]) - 8);

    const c = this.project(this.center[0] - length / 2, this.center[1], zTop);
    const d = this.project(this.center[0] + length / 2, this.center[1], zTop);
    ctx.beginPath();
    ctx.moveTo(c[0], c[1]);
    ctx.lineTo(d[0], d[1]);
    ctx.stroke();
    ctx.fillText(`дължина ${Math.round(length)} mm`,
                 Math.max(c[0], d[0]) + 8, (c[1] + d[1]) / 2);
  },

  parseColor(hex) {
    const clean = String(hex || "#9fb0c6").replace("#", "");
    const value = parseInt(clean, 16);
    if (!Number.isFinite(value)) return [160, 176, 198];
    return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
  },
};


