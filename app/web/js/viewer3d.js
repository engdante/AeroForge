/**
 * viewer3d.js — 3D преглед на модела.
 *
 * Рендерът е **WebGL**: истински z-buffer, нормали по връх и осветяване по
 * фрагмент (истински гладки повърхности), backface culling и антиалиасинг.
 * Ако WebGL липсва, се ползва резервен вариант с canvas 2D (сортиране по
 * дълбочина), за да работи приложението навсякъде.
 *
 * Решетката и надписите „размах/дължина“ са на отделен прозрачен canvas
 * отгоре (#model3dOverlay) — текстът в WebGL е излишно усложнение.
 * Геометрията идва от Python (core/geometry3d.py), за да има един източник
 * на истина с изчисленията.
 */
const Viewer = {
  canvas: null,
  gl: null,
  overlay: null,
  ctx2d: null,
  model: null,
  yaw: -0.78,
  pitch: 0.36,
  zoom: 1,
  scale: 1,
  depthSpan: 1,
  fitOffset: [0, 0, 0],
  center: [0, 0, 0],
  size: [1, 1, 1],
  radius: 1,
  w: 900,
  h: 460,
  dragging: false,
  dragMode: "rotate",      // "rotate" | "pan"
  lastX: 0,
  lastY: 0,
  // Камера: въртенето е около `pivot` — точката в центъра на изгледа.
  // В началния изглед pivot = центърът на модела и рамката се пасва
  // автоматично; след местене/приближаване (custom) мащабът и pivot-ът
  // остават, каквито ги е оставил потребителят.
  pivot: null,
  custom: false,
  ZOOM_MIN: 0.2,
  ZOOM_MAX: 40,
  useGL: false,
  // „Вътрешност“: обшивката е полупрозрачна, спарът и джойнерът се виждат
  xray: false,
  XRAY_ALPHA: 0.24,
  program: null,
  buffers: [],
  _mesh: null,
  _meshFor: null,

  init() {
    this.canvas = document.getElementById("model3d");
    if (!this.canvas) return;
    try { this.xray = localStorage.getItem("aeroforge.xray") === "1"; }
    catch (err) { this.xray = false; }
    this.overlay = document.getElementById("model3dOverlay");
    if (this.overlay) {
      this.overlayCtx = this.overlay.getContext("2d");
    }
    this.useGL = this._initGL();
    if (!this.useGL) {
      // WebGL контекстът вече заема канваса — за 2D трябва нов елемент
      this._fallback2D();
    }
    this.bind();
    this.render();
  },

  /** Нов канвас на мястото на стария (след като WebGL го е заел). */
  _replaceCanvas() {
    if (!this.canvas || !this.canvas.parentNode) return;
    const fresh = this.canvas.cloneNode(false);
    fresh.removeAttribute("width");
    fresh.removeAttribute("height");
    if (fresh.dataset) delete fresh.dataset.dpr;
    this.canvas.parentNode.replaceChild(fresh, this.canvas);
    this.canvas = fresh;
    this._freeBuffers();
  },

  /** Резервен вариант: 2D контекст върху нов канвас. */
  _fallback2D() {
    this.useGL = false;
    this.gl = null;
    this.program = null;
    this._replaceCanvas();
    this.ctx2d = this.canvas ? this.canvas.getContext("2d") : null;
    this.bind();
  },

  _freeBuffers() {
    const gl = this.gl;
    if (gl) {
      [this.bufPos, this.bufNormal, this.bufColor, this.bufIndex]
        .forEach((buffer) => {
          if (buffer) gl.deleteBuffer(buffer);
        });
    }
    this.bufPos = null;
    this.bufNormal = null;
    this.bufColor = null;
    this.bufIndex = null;
    this.indexCount = 0;
  },

  bind() {
    this._bindCanvas();
    if (this._windowBound) return;
    this._windowBound = true;

    window.addEventListener("mouseup", () => {
      if (this.dragging && this.dragMode === "pan") {
        // след местене въртенето е около частта в центъра на изгледа
        this._snapPivotDepth();
        this.render();
      }
      this.dragging = false;
      if (this.canvas) this.canvas.style.cursor = "grab";
    });
    window.addEventListener("mousemove", (event) => {
      if (!this.dragging) return;
      const dx = event.clientX - this.lastX;
      const dy = event.clientY - this.lastY;
      this.lastX = event.clientX;
      this.lastY = event.clientY;
      if (this.dragMode === "pan") {
        this.panBy(dx, dy);
        return;
      }
      this.yaw -= dx * 0.008;
      this.pitch = Math.max(-1.35, Math.min(1.35, this.pitch + dy * 0.006));
      this.render();
    });
    window.addEventListener("resize", () => {
      if (this.model) this.render();
    });
  },

  _bindCanvas() {
    const canvas = this.canvas;
    if (!canvas) return;

    canvas.addEventListener("mousedown", (event) => {
      // десен/среден бутон или Shift + ляв → местене (pan); ляв → въртене
      const pan = event.button === 1 || event.button === 2 || event.shiftKey;
      if (event.button === 1) event.preventDefault();   // без автоскрол
      this.dragging = true;
      this.dragMode = pan ? "pan" : "rotate";
      this.lastX = event.clientX;
      this.lastY = event.clientY;
      canvas.style.cursor = pan ? "move" : "grabbing";
    });
    canvas.addEventListener("contextmenu", (event) => event.preventDefault());
    canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect
        ? canvas.getBoundingClientRect() : { left: 0, top: 0 };
      this.zoomAt(Math.exp(-event.deltaY * 0.0012),
                  event.clientX - rect.left, event.clientY - rect.top);
    }, { passive: false });
    canvas.addEventListener("dblclick", () => this.setView("iso"));
    canvas.style.cursor = "grab";
  },

  setModel(model) {
    this.model = model;
    this._mesh = null;
    this._meshFor = null;
    this._freeBuffers();
    this.frameModel();
    this.render();
    const info = document.getElementById("modelInfo");
    if (!info) return;
    if (!model || !model.parts || !model.parts.length) {
      info.textContent = "няма модел";
      return;
    }
    info.textContent =
      `размах ${Math.round(model.size.span_mm)} mm · ` +
      `дължина ${Math.round(model.size.length_mm)} mm · ` +
      `опашка ${model.info && model.info.tail_airfoil || "—"}` +
      (model.info && model.info.fin_airfoil
        && model.info.fin_airfoil !== model.info.tail_airfoil
        ? ` / кил ${model.info.fin_airfoil}` : "") + " · " +
      `${model.triangles} триъгълника` +
      (model.quality ? ` · качество ${model.quality}` : "") +
      ` · ${this.rendererName()}`;
  },

  /** Кой път рисува — за да се вижда веднага, ако WebGL не работи. */
  rendererName() {
    if (!this.useGL) return "рендер 2D (резервен)";
    const err = this.gl ? this.gl.getError() : 0;
    return err ? `WebGL (грешка ${err})` : "WebGL";
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
    // при преизчисление (нов модел) свободната камера остава, където е
    if (!this.custom || !this.pivot) {
      this.pivot = this.center.slice();
      this.custom = false;
    }
  },

  /** Включва/изключва полупрозрачната обшивка (виж слоевете на частите). */
  setXray(on) {
    this.xray = !!on;
    try { localStorage.setItem("aeroforge.xray", this.xray ? "1" : "0"); }
    catch (err) { /* без localStorage — само за сесията */ }
    this.render();
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
    this.resetCamera();
    this.render();
  },

  /** Началната камера: pivot = центърът на модела, рамката се пасва сама. */
  resetCamera() {
    this.pivot = (this.center || [0, 0, 0]).slice();
    this.custom = false;
    this.zoom = 1;
  },

  /** Посоките на екрана в света: надясно, нагоре (за местене и приближаване). */
  _screenAxes() {
    const cy = Math.cos(this.yaw);
    const sy = Math.sin(this.yaw);
    const cp = Math.cos(this.pitch);
    const sp = Math.sin(this.pitch);
    return { right: [cy, -sy, 0], up: [sy * sp, cy * sp, cp] };
  },

  /**
   * Преминава от автоматична рамка към свободна камера: точката, която е
   * в центъра на екрана, става pivot, а мащабът се запазва — нищо не
   * подскача.
   */
  _enterCustom() {
    if (this.custom) return;
    if (!this.pivot) this.pivot = (this.center || [0, 0, 0]).slice();
    const off = this.fitOffset || [0, 0, 0];
    const { right, up } = this._screenAxes();
    for (let k = 0; k < 3; k++) {
      this.pivot[k] += right[k] * off[0] + up[k] * off[1];
    }
    this.fitOffset = [0, 0, off[2]];
    this.custom = true;
  },

  /**
   * Слага точката на въртене върху частта в центъра на екрана: най-
   * близкият до камерата връх около лъча през центъра. Без това pivot-ът
   * остава на дълбочината на центъра на модела (във въздуха пред/зад
   * гледаната част) и при завъртане тя „отлита“ встрани.
   */
  _snapPivotDepth() {
    if (!this.model || !this.pivot) return;
    const mesh = this.meshData();
    if (!mesh || !mesh.vlist.length) return;
    const s = this.scale * this.zoom || 1;
    const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw);
    const cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
    const depthAxis = [sy * cp, cy * cp, -sp];
    for (const px of [24, 72, 200]) {
      const r = px / s;
      let best = null;
      for (const v of mesh.vlist) {
        const [X, up, depth] = this._viewPoint(v[0], v[1], v[2]);
        if (Math.abs(X) <= r && Math.abs(up) <= r
            && (best === null || depth < best)) {
          best = depth;          // по-малка дълбочина = по-близо до камерата
        }
      }
      if (best !== null) {
        for (let k = 0; k < 3; k++) this.pivot[k] += depthAxis[k] * best;
        return;
      }
    }
  },

  /** Местене (pan) с dx, dy пиксела: моделът следва мишката. */
  panBy(dx, dy) {
    if (!this.model) return;
    this._enterCustom();
    const s = this.scale * this.zoom || 1;
    const { right, up } = this._screenAxes();
    for (let k = 0; k < 3; k++) {
      this.pivot[k] += (-right[k] * dx + up[k] * dy) / s;
    }
    this.render();
  },

  /**
   * Приближаване с `factor` към точката (mx, my) в пиксели от горния ляв
   * ъгъл: точката под курсора остава на мястото си.
   */
  zoomAt(factor, mx, my) {
    if (!this.model) return;
    this._enterCustom();
    const s0 = this.scale * this.zoom || 1;
    const zoom = Math.max(this.ZOOM_MIN, Math.min(this.ZOOM_MAX, this.zoom * factor));
    const s1 = this.scale * zoom || 1;
    const ox = (Number.isFinite(mx) ? mx : this.w / 2) - this.w / 2;
    const oy = (Number.isFinite(my) ? my : this.h / 2) - this.h / 2;
    const { right, up } = this._screenAxes();
    for (let k = 0; k < 3; k++) {
      // точката под курсора: pivot + right·ox/s − up·oy/s (при s0 и при s1)
      const target = this.pivot[k] + right[k] * ox / s0 - up[k] * oy / s0;
      this.pivot[k] = target - right[k] * ox / s1 + up[k] * oy / s1;
    }
    this.zoom = zoom;
    this._snapPivotDepth();
    this.render();
  },

  /**
   * Размер на сцената в CSS px: следва обвивката .viewer-canvas (CSS задава
   * ширина 100 % и височина спрямо прозореца). Без layout (скрит елемент,
   * тестове) се връща резервният размер 900×460.
   */
  viewSize() {
    const box = this.canvas && this.canvas.parentNode;
    const w = box ? Math.floor(box.clientWidth || 0) : 0;
    const h = box ? Math.floor(box.clientHeight || 0) : 0;
    if (w >= 120 && h >= 80) return [w, h];
    return [900, 460];
  },

  prepare() {
    const dpr = window.devicePixelRatio || 1;
    const [w, h] = this.viewSize();
    const key = `${dpr}:${w}x${h}`;
    const setup = (canvas) => {
      if (!canvas) return null;
      if (canvas.dataset.dpr !== key) {
        // и двата канваса се разтягат от CSS (100 % / inset: 0)
        canvas.width = Math.floor(w * dpr);
        canvas.height = Math.floor(h * dpr);
        canvas.dataset.dpr = key;
      }
      return canvas;
    };
    setup(this.canvas, false);
    setup(this.overlay, true);
    this.w = w;
    this.h = h;
  },

  _viewPoint(x, y, z) {
    // само завъртане около pivot: [екран X, екран Y (нагоре), дълбочина]
    const c = this.pivot || this.center;
    const cx = x - c[0];
    const cy = y - c[1];
    const cz = z - c[2];

    const cyaw = Math.cos(this.yaw);
    const syaw = Math.sin(this.yaw);
    const X = cx * cyaw - cy * syaw;
    const Y = cx * syaw + cy * cyaw;

    const cp = Math.cos(this.pitch);
    const sp = Math.sin(this.pitch);
    return [X, Y * sp + cz * cp, Y * cp - cz * sp];
  },

  project(x, y, z) {
    const [X, up, depth] = this._viewPoint(x, y, z);
    const s = this.scale * this.zoom;
    const off = this.fitOffset || [0, 0, 0];
    return [this.w / 2 + (X - off[0]) * s,
            this.h / 2 - (up - off[1]) * s,
            depth - off[2]];
  },

  /**
   * Пасва модела точно в прозореца за текущия ъгъл.
   *
   * Раньше мащабът се смяташе по половин диагонал спрямо по-малкия габарит
   * на canvas-а — при размах 1300 mm това рисуваше крилото в ~1/3 от
   * ширината.  Сега се мерят реалните екранни размери по X и по Y.
   */
  fit() {
    if (!this.model || !this.model.parts.length) {
      this.scale = 1;
      this.depthSpan = 1;
      return;
    }
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    let minD = Infinity, maxD = -Infinity;
    this.model.parts.forEach((part) => {
      const p = part.points;
      for (let i = 0; i < p.length; i += 3) {
        const [X, up, depth] = this._viewPoint(p[i], p[i + 1], p[i + 2]);
        if (X < minX) minX = X;
        if (X > maxX) maxX = X;
        if (up < minY) minY = up;
        if (up > maxY) maxY = up;
        if (depth < minD) minD = depth;
        if (depth > maxD) maxD = depth;
      }
    });
    if (this.custom) {
      // свободна камера: мащабът и центърът са на потребителя, тук само
      // дълбочината (иначе WebGL изрязва модела)
      this.fitOffset = [0, 0, (minD + maxD) / 2];
      this.depthSpan = Math.max(1e-6, (maxD - minD) / 2 * 1.02);
      return;
    }
    const width = Math.max(1e-6, maxX - minX);
    const height = Math.max(1e-6, maxY - minY);
    // центърът на екранната рамка не е задължително центърът на модела
    this.fitOffset = [(minX + maxX) / 2, (minY + maxY) / 2,
                      (minD + maxD) / 2];
    this.depthSpan = Math.max(1e-6, (maxD - minD) / 2 * 1.02);
    this.scale = Math.min((this.w * 0.92) / width, (this.h * 0.90) / height);
  },

  render() {
    if (!this.canvas) return;
    this.prepare();
    this.fit();

    if (this.useGL) {
      this._renderGL();
    } else {
      this._render2D();
    }
    this.drawOverlay();
  },

  // ---------------------------------------------------------------- WebGL
  _initGL() {
    let gl = null;
    try {
      gl = this.canvas.getContext("webgl", {
        antialias: true,
        alpha: false,
        depth: true,
        premultipliedAlpha: false,
      }) || this.canvas.getContext("experimental-webgl");
    } catch (err) {
      gl = null;
    }
    if (!gl || typeof gl.createShader !== "function") return false;
    this.gl = gl;
    const program = this._glProgram();
    if (!program) {
      this.gl = null;
      return false;
    }
    this.program = program;
    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    // Без culling: рендерът не зависи от намотката на триъгълниците.
    // При затворен модел z-buffer-ът сам решава кой е отпред, а двойното
    // осветяване прави и обърнатите лица видими, ако има такива.
    gl.disable(gl.CULL_FACE);
    gl.clearColor(0.055, 0.078, 0.114, 1.0);
    return true;
  },

  _glProgram() {
    const gl = this.gl;
    const vsSource = [
      "attribute vec3 aPos;",
      "attribute vec3 aNormal;",
      "attribute vec3 aColor;",
      "uniform mat4 uView;",
      "uniform vec3 uScale;",
      "varying vec3 vNormal;",
      "varying vec3 vColor;",
      "void main() {",
      "  vec4 v = uView * vec4(aPos, 1.0);",
      "  gl_Position = vec4(v.x * uScale.x, v.y * uScale.y,",
      "                     v.z * uScale.z, 1.0);",
      "  vNormal = mat3(uView) * aNormal;",
      "  vColor = aColor;",
      "}",
    ].join("\n");
    const fsSource = [
      "precision mediump float;",
      "varying vec3 vNormal;",
      "varying vec3 vColor;",
      "uniform vec3 uLight;",
      "uniform float uAlpha;",
      "void main() {",
      "  vec3 n = normalize(vNormal);",
      "  // двустранно: abs() → осветено и когато нормалата сочи обратно",
      "  float diff = abs(dot(n, uLight));",
      "  float spec = pow(diff, 14.0) * 0.16;",
      "  vec3 col = vColor * (0.34 + 0.60 * diff) + vec3(spec);",
      "  gl_FragColor = vec4(min(col, vec3(1.0)), uAlpha);",
      "}",
    ].join("\n");

    const make = (type, source) => {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        console.error(gl.getShaderInfoLog(shader));
        return null;
      }
      return shader;
    };
    const vs = make(gl.VERTEX_SHADER, vsSource);
    const fs = make(gl.FRAGMENT_SHADER, fsSource);
    if (!vs || !fs) return null;
    const program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error(gl.getProgramInfoLog(program));
      return null;
    }
    return program;
  },

  _uploadMesh() {
    const gl = this.gl;
    const mesh = this.meshData();
    if (!mesh || !mesh.tris.length) return;

    const position = new Float32Array(mesh.vlist.length * 3);
    mesh.vlist.forEach((p, i) => {
      position[i * 3] = p[0];
      position[i * 3 + 1] = p[1];
      position[i * 3 + 2] = p[2];
    });
    const normals = new Float32Array(mesh.vnorm.length * 3);
    mesh.vnorm.forEach((n, i) => {
      normals[i * 3] = n[0];
      normals[i * 3 + 1] = n[1];
      normals[i * 3 + 2] = n[2];
    });
    const colors = new Float32Array(mesh.vcolor.length * 3);
    mesh.vcolor.forEach((c, i) => {
      colors[i * 3] = c[0] / 255;
      colors[i * 3 + 1] = c[1] / 255;
      colors[i * 3 + 2] = c[2] / 255;
    });
    const indices = new Uint32Array(mesh.indices);
    const useUint = mesh.vlist.length >= 65536;
    if (useUint && !gl.getExtension("OES_element_index_uint")) {
      // без разширението моделът не може да се индексира с 32 бита →
      // нов канвас и резервен 2D рендер
      this._fallback2D();
      return;
    }

    const makeBuf = (target, data) => {
      const buf = gl.createBuffer();
      gl.bindBuffer(target, buf);
      gl.bufferData(target, data, gl.STATIC_DRAW);
      return buf;
    };
    this.bufPos = makeBuf(gl.ARRAY_BUFFER, position);
    this.bufNormal = makeBuf(gl.ARRAY_BUFFER, normals);
    this.bufColor = makeBuf(gl.ARRAY_BUFFER, colors);
    this.bufIndex = makeBuf(gl.ELEMENT_ARRAY_BUFFER,
                            useUint ? indices : new Uint16Array(indices));
    this.indexCount = indices.length;
    this.indexType = useUint ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT;
  },

  _viewMatrix() {
    const cy = Math.cos(this.yaw);
    const sy = Math.sin(this.yaw);
    const cp = Math.cos(this.pitch);
    const sp = Math.sin(this.pitch);
    // редове: екран X, екран Y (нагоре), дълбочина — както в 2D варианта
    const r00 = cy, r01 = -sy, r02 = 0;
    const r10 = sy * sp, r11 = cy * sp, r12 = cp;
    const r20 = sy * cp, r21 = cy * cp, r22 = -sp;
    const off = this.fitOffset || [0, 0, 0];
    // центърът на модела (отместването се вади след завъртането)
    const pv = this.pivot || this.center;
    const cx = pv[0];
    const cyy = pv[1];
    const cz = pv[2];
    let tx = -(r00 * cx + r01 * cyy + r02 * cz);
    let ty = -(r10 * cx + r11 * cyy + r12 * cz);
    let tz = -(r20 * cx + r21 * cyy + r22 * cz);
    // изваждаме и отместването (във view space), за да е центриран кадърът
    tx -= off[0];
    ty -= off[1];
    tz -= off[2];
    // column-major (както очаква WebGL)
    return new Float32Array([
      r00, r10, r20, 0,
      r01, r11, r21, 0,
      r02, r12, r22, 0,
      tx, ty, tz, 1,
    ]);
  },

  _renderGL() {
    const gl = this.gl;
    const canvas = this.canvas;
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!this.model || !this.model.parts.length) return;
    if (!this.bufPos) this._uploadMesh();
    if (!this.useGL) {
      // WebGL се отказа по средата (напр. липсва OES_element_index_uint)
      this._render2D();
      return;
    }
    if (!this.bufPos) return;

    const program = this.program;
    gl.useProgram(program);

    const s = this.scale * this.zoom;
    // Дълбочината се нормира по реалния обхват на модела за този ъгъл,
    // иначе всичко извън [-1, 1] се изрязва и екранът остава празен.
    const depthSpan = this.depthSpan || 1;
    gl.uniform3f(gl.getUniformLocation(program, "uScale"),
                 (2 * s) / this.w, (2 * s) / this.h, 1.0 / depthSpan);
    gl.uniformMatrix4fv(gl.getUniformLocation(program, "uView"), false,
                        this._viewMatrix());
    gl.uniform3f(gl.getUniformLocation(program, "uLight"), -0.38, -0.62, 0.68);

    const bind = (name, buffer, size) => {
      const loc = gl.getAttribLocation(program, name);
      if (loc < 0) return;
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
      gl.enableVertexAttribArray(loc);
    };
    bind("aPos", this.bufPos, 3);
    bind("aNormal", this.bufNormal, 3);
    bind("aColor", this.bufColor, 3);

    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.bufIndex);
    const alpha = gl.getUniformLocation(program, "uAlpha");
    const mesh = this._mesh || {};
    const skin = mesh.skinCount || 0;
    if (!this.xray || !skin) {
      gl.uniform1f(alpha, 1.0);
      gl.drawElements(gl.TRIANGLES, this.indexCount, this.indexType, 0);
      return;
    }
    // първо плътните части (спар, джойнер, опашка…), после обшивката —
    // полупрозрачна и без запис в z-buffer-а, за да не скрива вътрешността
    const solid = this.indexCount - skin;
    const bytes = this.indexType === gl.UNSIGNED_INT ? 4 : 2;
    gl.uniform1f(alpha, 1.0);
    if (solid > 0) {
      gl.drawElements(gl.TRIANGLES, solid, this.indexType, 0);
    }
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.depthMask(false);
    gl.uniform1f(alpha, this.XRAY_ALPHA);
    gl.drawElements(gl.TRIANGLES, skin, this.indexType, solid * bytes);
    gl.depthMask(true);
    gl.disable(gl.BLEND);
  },

  // ------------------------------------------------------- обща геометрия
  /**
   * Подготвя мрежата веднъж за модела: заварени върхове, нормали по лице
   * и по връх (за гладко осветяване), цвят по връх и индекси.
   */
  meshData() {
    if (this._meshFor === this.model && this._mesh) return this._mesh;
    const map = new Map();
    const vlist = [];
    const vcolor = [];
    const tris = [];

    // заваряване на върховете само в рамките на една част: иначе цветът
    // и нормалите на обшивката и вътрешните части се смесват
    let partKey = "";
    const addVert = (x, y, z, color) => {
      const key = partKey + x + "," + y + "," + z;
      let idx = map.get(key);
      if (idx === undefined) {
        idx = vlist.length;
        map.set(key, idx);
        vlist.push([x, y, z]);
        vcolor.push(color);
      }
      return idx;
    };

    this.model.parts.forEach((part, partIndex) => {
      const p = part.points;
      const color = this.parseColor(part.color);
      const layer = part.layer || "solid";
      partKey = partIndex + ":";
      const partTris = [];
      for (let i = 0; i < p.length; i += 9) {
        const ax = p[i], ay = p[i + 1], az = p[i + 2];
        const bx = p[i + 3], by = p[i + 4], bz = p[i + 5];
        const cx = p[i + 6], cy = p[i + 7], cz = p[i + 8];
        const ux = bx - ax, uy = by - ay, uz = bz - az;
        const vx = cx - ax, vy = cy - ay, vz = cz - az;
        let nx = uy * vz - uz * vy;
        let ny = uz * vx - ux * vz;
        let nz = ux * vy - uy * vx;
        const len = Math.hypot(nx, ny, nz) || 1;
        nx /= len; ny /= len; nz /= len;
        partTris.push({
          i: [addVert(ax, ay, az, color),
              addVert(bx, by, bz, color),
              addVert(cx, cy, cz, color)],
          n: [nx, ny, nz],
          color,
          skin: layer === "skin",
        });
      }
      // предпазна мярка: ако частта е с обърната намотка, обръщаме я
      let vol = 0;
      for (let i = 0; i < p.length; i += 9) {
        const ax = p[i], ay = p[i + 1], az = p[i + 2];
        const bx = p[i + 3], by = p[i + 4], bz = p[i + 5];
        const cx = p[i + 6], cy = p[i + 7], cz = p[i + 8];
        vol += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx)
          + az * (bx * cy - by * cx);
      }
      if (vol < 0) {
        partTris.forEach((t) => {
          const tmp = t.i[1];
          t.i[1] = t.i[2];
          t.i[2] = tmp;
          t.n[0] = -t.n[0];
          t.n[1] = -t.n[1];
          t.n[2] = -t.n[2];
        });
      }
      partTris.forEach((t) => tris.push(t));
    });

    const acc = vlist.map(() => [0, 0, 0]);
    tris.forEach((t) => {
      t.i.forEach((vi) => {
        acc[vi][0] += t.n[0];
        acc[vi][1] += t.n[1];
        acc[vi][2] += t.n[2];
      });
    });
    const vnorm = acc.map((a) => {
      const l = Math.hypot(a[0], a[1], a[2]) || 1;
      return [a[0] / l, a[1] / l, a[2] / l];
    });
    // индексите: първо плътните триъгълници, после обшивката (за X-ray)
    const indices = [];
    let skinCount = 0;
    tris.forEach((t) => {
      if (!t.skin) indices.push(t.i[0], t.i[1], t.i[2]);
    });
    tris.forEach((t) => {
      if (t.skin) {
        indices.push(t.i[0], t.i[1], t.i[2]);
        skinCount += 3;
      }
    });
    this._mesh = { vlist, vnorm, vcolor, tris, indices, skinCount };
    this._meshFor = this.model;
    return this._mesh;
  },

  // --------------------------------------------- резервен вариант canvas 2D

  _render2D() {
    const ctx = this.ctx2d;
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#0e141d";
    ctx.fillRect(0, 0, this.w, this.h);
    if (!this.model || !this.model.parts.length) return;
    this.drawParts2D(ctx);
  },

  drawParts2D(ctx) {
    const light = [-0.38, -0.62, 0.68];
    const mesh = this.meshData();
    if (!mesh.tris.length) return;

    const proj = mesh.vlist.map(([x, y, z]) => this.project(x, y, z));
    const faces = [];
    mesh.tris.forEach((t) => {
      const a = proj[t.i[0]], b = proj[t.i[1]], c = proj[t.i[2]];
      const va = mesh.vnorm[t.i[0]], vb = mesh.vnorm[t.i[1]];
      const vc = mesh.vnorm[t.i[2]];
      let nx = va[0] + vb[0] + vc[0];
      let ny = va[1] + vb[1] + vc[1];
      let nz = va[2] + vb[2] + vc[2];
      const nl = Math.hypot(nx, ny, nz) || 1;
      nx /= nl; ny /= nl; nz /= nl;
      // двустранно осветяване — не зависи от намотката
      const dot = Math.abs(nx * light[0] + ny * light[1] + nz * light[2]);
      faces.push({
        a, b, c,
        alpha: (this.xray && t.skin) ? this.XRAY_ALPHA : 1,
        depth: (a[2] + b[2] + c[2]) / 3,
        color: t.color,
        shade: 0.30 + 0.62 * dot + 0.14 * Math.pow(dot, 8),
      });
    });
    // painter's algorithm: най-далечното първо (без изхвърляне на лица)
    faces.sort((t1, t2) => t2.depth - t1.depth);

    faces.forEach((t) => {
      const col = "rgb(" +
        Math.min(255, Math.round(t.color[0] * t.shade)) + "," +
        Math.min(255, Math.round(t.color[1] * t.shade)) + "," +
        Math.min(255, Math.round(t.color[2] * t.shade)) + ")";
      ctx.fillStyle = col;
      ctx.globalAlpha = t.alpha;
      ctx.beginPath();
      ctx.moveTo(t.a[0], t.a[1]);
      ctx.lineTo(t.b[0], t.b[1]);
      ctx.lineTo(t.c[0], t.c[1]);
      ctx.closePath();
      ctx.fill();
    });
    ctx.globalAlpha = 1;
  },


  // ------------------------------------------------ решетка и надписи (2D)
  drawOverlay() {
    const ctx = this.overlayCtx;
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, this.w, this.h);
    if (!this.model || !this.model.parts || !this.model.parts.length) {
      ctx.fillStyle = "#6f8098";
      ctx.font = "12px Segoe UI, sans-serif";
      ctx.fillText("моделът ще се появи след изчислението", 16, this.h / 2);
      return;
    }
    this.drawGrid(ctx);
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
      const y = y0 + i * (span / 8);
      const a = this.project(x0, y, z);
      const b = this.project(x0 + length, y, z);
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
      ctx.stroke();

      const x = x0 + i * (length / 8);
      const c = this.project(x, y0, z);
      const d = this.project(x, y0 + span, z);
      ctx.beginPath();
      ctx.moveTo(c[0], c[1]);
      ctx.lineTo(d[0], d[1]);
      ctx.stroke();
    }
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

