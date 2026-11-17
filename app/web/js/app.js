/**
 * app.js — свързване на UI със сървъра, състояние и експорти.
 */
const App = {
  result: null,
  busy: false,
  paths: null,
  lastFolder: null,

  async init() {
    try {
      const presets = await API.presets();
      UI.setPresets(presets);
      UI.applyFont(presets.ui);
      this.paths = presets.paths;
      UI.writeInputs(presets.defaults);
    } catch (err) {
      UI.showError(err.message);
      document.getElementById("calcStatus").textContent =
        "няма връзка с Python backend";
      return;
    }
    this.bind();
    Settings.bind();
    Viewer.init();
    UI.loadPropellers();
    document.querySelectorAll(".viewer-bar [data-view]").forEach((btn) => {
      btn.addEventListener("click", () => Viewer.setView(btn.dataset.view));
    });
    this.bindViewerFullscreen();
    this.bindChartInfo();
    const xray = document.getElementById("btnXray");
    if (xray) {
      const sync = () => {
        xray.classList.toggle("active", Viewer.xray);
        xray.setAttribute("aria-pressed", String(Viewer.xray));
      };
      xray.addEventListener("click", () => { Viewer.setXray(!Viewer.xray); sync(); });
      sync();
    }
    await this.compute();
  },

  /** Презарежда справочните данни след промяна в „Настройки“. */
  async refreshFromSettings() {
    const current = UI.readInputs();
    try {
      const presets = await API.presets();
      UI.setPresets(presets);
      UI.applyFont(presets.ui);
      this.paths = presets.paths;
      const keys = presets.filaments.map((f) => f.key);
      if (!keys.includes(current.print.filament)) {
        current.print.filament = presets.defaults.print.filament;
      }
      UI.writeInputs(current);
      await this.compute();
    } catch (err) {
      document.getElementById("calcStatus").textContent = err.message;
    }
  },

  /** Обновява 3D прегледа (отделен RPC, за да не тежи на изчислението). */
  async updateModel(inputs) {
    const token = (this._modelToken = (this._modelToken || 0) + 1);
    const info = document.getElementById("modelInfo");
    try {
      const model = await API.model3d(inputs);
      if (token !== this._modelToken) return;   // има по-ново извикване
      if (model && model.ok) {
        Viewer.setModel(model);
      } else if (info) {
        info.textContent = (model && model.error) || "няма модел";
      }
    } catch (err) {
      if (info) info.textContent = "3D моделът не е достъпен";
    }
  },

  bind() {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => this.switchTab(btn.dataset.tab));
    });

    const recompute = debounce(() => this.compute(), 280);

    // Делегиране: работи и за динамично добавени редове с компоненти
    const side = document.querySelector(".side");
    side.addEventListener("input", recompute);
    side.addEventListener("change", recompute);

    document.querySelectorAll('input[name="payloadMode"]').forEach((r) => {
      r.addEventListener("change", () => {
        UI.togglePayloadMode();
        this.compute();
      });
    });

    document.getElementById("missionSelect")
      .addEventListener("change", () => UI.updateMissionInfo());
    document.getElementById("filamentSelect")
      .addEventListener("change", () => UI.updateFilamentInfo());
    document.getElementById("airfoilSelect")
      .addEventListener("change", () => UI.updateAirfoilInfo());
    document.getElementById("btnPropCheck")
      .addEventListener("click", () => UI.checkPropeller());
    document.getElementById("btnPropStl")
      .addEventListener("click", () => UI.exportPropellerStl());
    document.getElementById("profileSelect")
      .addEventListener("change", (event) => UI.applyProfile(event.target.value));
    document.getElementById("bedPreset")
      .addEventListener("change", (event) => UI.applyBedPreset(event.target.value));
    document.getElementById("tipStyle")
      .addEventListener("change", () => UI.syncWinglet());

    document.getElementById("btnAddComponent")
      .addEventListener("click", () => {
        UI.addComponentRow({ qty: 1, category: "other" });
        this.compute();
      });

    document.getElementById("presetSelect")
      .addEventListener("change", (event) => {
        const index = event.target.value;
        if (index === "") return;
        const preset = UI.presets.component_presets[Number(index)];
        UI.addComponentRow({
          name: preset.name,
          category: preset.category,
          qty: 1,
          unit_mass_g: preset.unit_mass_g,
        });
        event.target.value = "";
        this.compute();
      });

    document.getElementById("btnSave")
      .addEventListener("click", () => this.save());
    document.getElementById("btnExport")
      .addEventListener("click", () => this.exportAll());

    // Отместване на крилото: плъзгач (в % от височината) и число (mm)
    const offsetRange = document.getElementById("wingOffsetRange");
    if (offsetRange) {
      offsetRange.addEventListener("input", () => {
        const height = UI._heightMm || 0;
        const mm = (Number(offsetRange.value) / 100) * height;
        UI.setWingOffset(mm);
        recompute();
      });
    }
    document.querySelectorAll("[data-offset]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const preset = (UI.wingPresets || [])
          .find((item) => item.key === btn.dataset.offset);
        const ratio = preset && preset.offset_ratio !== undefined
          ? preset.offset_ratio : 0;
        UI.setWingOffset(ratio * (UI._heightMm || 0));
        this.compute();
      });
    });
    document.getElementById("btnLoad")
      .addEventListener("click", () => this.openDesigns());
    document.getElementById("btnCloseModal")
      .addEventListener("click", () => this.closeDesigns());
    document.getElementById("btnCloseExport")
      .addEventListener("click", () => this.closeExportPanel());
    document.getElementById("exportModal")
      .addEventListener("click", (event) => {
        if (event.target.id === "exportModal") this.closeExportPanel();
      });
    document.getElementById("btnExportCancel")
      .addEventListener("click", async () => {
        this.exportCancel = true;
        if (this.exportJob) {
          try { await API.exportCancel(this.exportJob); } catch (err) { /* ignore */ }
        }
        const log = document.getElementById("exportLog");
        if (log) {
          log.textContent += "\n— отказ: спирам след текущата стъпка —";
          log.scrollTop = log.scrollHeight;
        }
      });
    document.getElementById("btnExportFolder")
      .addEventListener("click", () => {
        if (this.lastFolder) API.openExport(this.lastFolder);
      });
    document.getElementById("btnExportDone")
      .addEventListener("click", () => this.closeExportPanel());
    document.getElementById("designsModal")
      .addEventListener("click", (event) => {
        if (event.target.id === "designsModal") this.closeDesigns();
      });
    document.getElementById("btnExample")
      .addEventListener("click", () => this.loadExample());
    document.getElementById("btnReset")
      .addEventListener("click", () => this.reset());

    // Резултатните секции се сгъват/разгъват с клик върху заглавието
    document.querySelectorAll(".block > h3").forEach((h) => {
      h.classList.add("collapsible");
      h.title = "Щракни, за да сгънеш или разгънеш";
      h.addEventListener("click", () => h.parentElement.classList.toggle("collapsed"));
    });

    const status = document.getElementById("calcStatus");
    status.style.cursor = "pointer";
    status.title = "Двойно щракване отваря последната папка с файлове";
    status.addEventListener("dblclick", () => {
      if (this.lastFolder) {
        API.openExport(this.lastFolder);
      } else {
        API.openFolder("exports");
      }
    });

    this.bindSplitter();

    window.addEventListener("resize", debounce(() => {
      if (this.result) {
        UI.renderResult(this.result);
        Charts.fuselageSide(document.getElementById("fuselageCanvas"),
                            this.result);
      }
    }, 300));
  },

  switchTab(name) {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === name);
    });
    document.querySelectorAll(".pane").forEach((pane) => {
      pane.classList.toggle("active", pane.id === "pane-" + name);
    });
    // мини-графиките в скрит таб нямат ширина — прерисуване при показване
    this.redrawSidePreviews();
  },

  redrawSidePreviews() {
    UI.updateAirfoilInfo();
    if (this.result) {
      Charts.fuselageSide(document.getElementById("fuselageCanvas"),
                          this.result);
    }
  },

  /**
   * Разделител между панела с параметрите и резултатите: влачене променя
   * ширината (пази се локално), двойно щракване връща подразбиращата се.
   */
  bindSplitter() {
    const splitter = document.getElementById("splitter");
    const side = document.querySelector(".side");
    if (!splitter || !side) return;
    const KEY = "aeroforge.sideWidth";
    const apply = (px) => {
      if (px) {
        const max = Math.max(380, window.innerWidth - 420);
        side.style.setProperty("--side-w",
          Math.round(Math.min(max, Math.max(340, px))) + "px");
      } else {
        side.style.removeProperty("--side-w");
      }
    };
    const relayout = () => window.dispatchEvent(new Event("resize"));
    try {
      const saved = Number(localStorage.getItem(KEY));
      if (saved > 0) apply(saved);
    } catch (err) { /* без localStorage — ширината по подразбиране */ }

    splitter.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      splitter.setPointerCapture(event.pointerId);
      splitter.classList.add("dragging");
      document.body.classList.add("resizing");
      const left = side.getBoundingClientRect().left;
      const move = (ev) => apply(ev.clientX - left);
      const up = () => {
        splitter.removeEventListener("pointermove", move);
        splitter.removeEventListener("pointerup", up);
        splitter.removeEventListener("pointercancel", up);
        splitter.classList.remove("dragging");
        document.body.classList.remove("resizing");
        try {
          localStorage.setItem(KEY, String(Math.round(side.offsetWidth)));
        } catch (err) { /* няма значение */ }
        relayout();
      };
      splitter.addEventListener("pointermove", move);
      splitter.addEventListener("pointerup", up);
      splitter.addEventListener("pointercancel", up);
    });
    splitter.addEventListener("dblclick", () => {
      apply(0);
      try { localStorage.removeItem(KEY); } catch (err) { /* няма значение */ }
      relayout();
    });
  },

  /** Бутоните „ⓘ Какво виждам?“ над графиките → прозорец с обяснения. */
  bindChartInfo() {
    const modal = document.getElementById("chartInfoModal");
    if (!modal) return;
    const titles = {
      ld: "Аеродинамично качество L/D",
      power: "Мощност: нужна / налична",
    };
    const close = () => modal.classList.add("hidden");
    document.querySelectorAll("[data-chart-info]").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();   // заглавието на блока не се сгъва
        const kind = btn.dataset.chartInfo;
        document.getElementById("chartInfoTitle").textContent = titles[kind] || "";
        document.getElementById("chartInfoBody").innerHTML =
          UI.chartInfoHtml(kind, this.result);
        modal.classList.remove("hidden");
      });
    });
    document.getElementById("btnCloseChartInfo").addEventListener("click", close);
    modal.addEventListener("click", (event) => {
      if (event.target === modal) close();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") close();
    });
  },

  /** 3D прегледът на цял екран (Esc излиза). */
  bindViewerFullscreen() {
    const btn = document.getElementById("btnViewerFull");
    // на цял екран отива целият блок — бутоните за изглед остават видими
    const box = document.querySelector(".block-viewer");
    if (!btn || !box || !box.requestFullscreen) {
      if (btn) btn.classList.add("hidden");
      return;
    }
    btn.addEventListener("click", () => {
      if (document.fullscreenElement) {
        document.exitFullscreen();
      } else {
        box.requestFullscreen().catch(() => {});
      }
    });
    document.addEventListener("fullscreenchange", () => {
      // размерът на сцената се сменя — прерисуване в новия размер
      requestAnimationFrame(() => Viewer.render());
    });
  },

  async compute() {
    if (this.busy) {
      this._pending = true;
      return;
    }
    this.busy = true;
    const status = document.getElementById("calcStatus");
    status.textContent = "изчислява…";
    try {
      const inputs = UI.readInputs();
      const res = await API.compute(inputs);
      this.result = res;
      UI.renderResult(res);
      Charts.fuselageSide(document.getElementById("fuselageCanvas"), res);
      this.updateModel(inputs);
      status.textContent = res.ok
        ? `готово · ${new Date().toLocaleTimeString("bg-BG")}`
        : "грешка: " + (res.error || "");
    } catch (err) {
      UI.showError(err.message);
      status.textContent = "грешка";
    } finally {
      this.busy = false;
      if (this._pending) {
        this._pending = false;
        this.compute();
      }
    }
  },

  async save() {
    const inputs = UI.readInputs();
    const status = document.getElementById("calcStatus");
    try {
      const res = await API.saveDesign(inputs.name, inputs);
      status.textContent = res.ok
        ? "записано: " + res.file + ".json"
        : "грешка: " + res.error;
    } catch (err) {
      status.textContent = err.message;
    }
  },

  /**
   * Един експорт, на стъпки: сечения + 3MF → SolidCraft (loft + join) →
   * STEP + 3MF + превю.
   *
   * Всяка стъпка е отделен RPC, за да е реален прогресът: панелът показва
   * кой етап върви, колко е минало, колко остава и какво е готово. Отказ
   * спира след текущата стъпка (SolidCraft не може да се прекъсне
   * насред boolean, но следващите стъпки не се пускат).
   */
  async exportAll() {
    if (this.exportRunning) return;
    this.exportRunning = true;
    this.exportCancel = false;
    const status = document.getElementById("calcStatus");
    const btn = document.getElementById("btnExport");
    btn.disabled = true;
    btn.textContent = "⏳ Експорт…";
    this.openExportPanel();
    this.setExportSummary("подготовка…");
    try {
      let res = await API.exportPlan(UI.readInputs(), this.exportOptions());
      if (!res || !res.ok) {
        this.setExportSummary("грешка: " +
          ((res && res.error) || "неуспешен експорт"));
        status.textContent = "грешка при експорт";
        return;
      }
      this.exportJob = res.job;
      this.lastFolder = res.folder;
      this.renderExportState(res);
      const total = (res.steps || []).length;
      for (let i = 0; i < total; i += 1) {
        if (this.exportCancel) break;
        this.markExportStep(i);
        res = await API.exportStep(this.exportJob, i);
        if (!res || !res.ok) {
          this.setExportSummary("грешка: " +
            ((res && res.error) || "стъпката се провали"));
          break;
        }
        this.renderExportState(res);
        const step = (res.steps || [])[i];
        status.textContent = `експорт ${i + 1}/${total}` +
          (step ? `: ${step.label}` : "");
      }
      if (res && res.ok) {
        await this.finishExportPanel(res);
        status.textContent = this.exportCancel
          ? "експортът е отказан"
          : `модел: ${(res.bodies || []).length} тела · ` +
            `${res.step ? "STEP" : "без STEP"}` +
            `${res.three_mf ? " + 3MF" : ""} → ${res.folder}`;
      }
    } catch (err) {
      this.setExportSummary("грешка: " + err.message);
    } finally {
      this.exportRunning = false;
      btn.disabled = false;
      btn.textContent = "📤 Експорт";
    }
  },

  /** Опции на експорта (по подразбиране: SolidCraft + 3MF + дизайн). */
  exportOptions() {
    return {
      run: true,
      split: true,
      exact_tail: false,
      join_tail: false,     // стабилизаторът остава отделно тяло (boolean виси)
      quality_3mf: "fine",
      save_design: true,
    };
  },

  openExportPanel() {
    const modal = document.getElementById("exportModal");
    if (!modal) return;
    modal.classList.remove("hidden");
    document.getElementById("exportResult").classList.add("hidden");
    document.getElementById("exportLog").textContent = "";
    document.getElementById("exportBar").style.width = "0%";
    document.getElementById("exportSteps").innerHTML = "";
    document.getElementById("btnExportCancel").disabled = false;
    document.getElementById("btnExportFolder").disabled = true;
    document.getElementById("btnExportDone").disabled = true;
  },

  closeExportPanel() {
    const modal = document.getElementById("exportModal");
    if (modal) modal.classList.add("hidden");
  },

  setExportSummary(text, time) {
    const el = document.getElementById("exportSummary");
    if (el) el.textContent = text;
    const timeEl = document.getElementById("exportTime");
    if (timeEl && time !== undefined) timeEl.textContent = time;
  },
  /** Маркира текущата стъпка като „работи“ още преди отговора на RPC-то. */
  markExportStep(index) {
    document.querySelectorAll("#exportSteps li").forEach((li, i) => {
      li.classList.toggle("running", i === index);
      if (i === index) {
        const mark = li.querySelector(".mark");
        if (mark) mark.textContent = "⟳";
      }
    });
  },

  /** Рисува състоянието от backend-а: чеклист, бар, лог, времена. */
  renderExportState(res) {
    const steps = res.steps || [];
    const list = document.getElementById("exportSteps");
    const marks = { pending: "·", running: "⟳", done: "✓", skipped: "!",
                    error: "✕" };
    if (list) {
      list.innerHTML = "";
      steps.forEach((step) => {
        const li = UI.el("li", step.state);
        li.appendChild(UI.el("span", "mark", marks[step.state] || "·"));
        li.appendChild(UI.el("span", "label", step.label));
        const meta = step.error
          ? step.error
          : [step.detail,
             step.ms ? `${(step.ms / 1000).toFixed(1)} s` : null]
            .filter(Boolean).join(" · ");
        li.appendChild(UI.el("span", "meta", meta || ""));
        if (step.error) li.title = step.error;
        list.appendChild(li);
      });
    }
    const bar = document.getElementById("exportBar");
    if (bar) bar.style.width = `${Math.round(res.progress || 0)}%`;
    const parts = [`${(res.bodies || []).length} тела`,
                   `${res.sections || 0} сечения`];
    if ((res.joins || []).length) parts.push(`${res.joins.length} join`);
    this.setExportSummary(parts.join(" · "),
      `изтекло ${Math.round(res.elapsed_s || 0)} s` +
      (res.eta_s ? ` · остават ~${Math.round(res.eta_s)} s` : ""));
    const log = document.getElementById("exportLog");
    if (log && res.log) {
      log.textContent = res.log
        .map((row) => `${String(row.t).padStart(5)} s  ${row.text}`)
        .join("\n");
      log.scrollTop = log.scrollHeight;
    }
  },

  /** След последната стъпка: резюме, превю, бутони. */
  async finishExportPanel(res) {
    const box = document.getElementById("exportResult");
    if (!box) return;
    box.innerHTML = "";
    box.classList.remove("hidden");
    const files = res.files || {};
    const lines = [];
    if (files.aircraft_step) {
      lines.push("aircraft.step — solid, " +
        (files.aircraft_step.bytes / 1e6).toFixed(1) + " MB");
    }
    const mesh = files.aircraft_3mf || {};
    if (mesh.path) {
      lines.push("aircraft.3mf — мрежа, " +
        (mesh.bytes / 1e6).toFixed(2) + " MB" +
        (mesh.source === "solidcraft" ? " (от solid-а)" : " (от мрежата)"));
    }
    if (files.aircraft_design) {
      lines.push("aircraft.sc — само профили (без loft), " +
        (files.aircraft_design.bytes / 1e6).toFixed(1) + " MB");
    }
    if (files.loft_design) {
      lines.push("steps/loft.sc — същите профили + loft + join, " +
        (files.loft_design.bytes / 1e6).toFixed(1) + " MB");
    }
    if (files.preview) lines.push("preview.png — iso изглед");
    const evalInfo = res.eval || null;
    if (evalInfo && evalInfo.body_count !== undefined) {
      const closed = (evalInfo.bodies || []).filter((b) => b.closed).length;
      lines.push("тела в STEP: " + evalInfo.body_count +
        ", затворени: " + closed);
    }
    const filesBox = UI.el("div", "files");
    lines.forEach((text) => filesBox.appendChild(UI.el("div", null, text)));
    if (res.warning) filesBox.appendChild(UI.el("div", "warn", "⚠ " + res.warning));
    filesBox.appendChild(UI.el("div", "hint", res.folder));
    box.appendChild(filesBox);
    if (res.preview) {
      const img = document.createElement("img");
      img.alt = "превю на модела";
      try {
        const url = await API.exportPreview(res.job);
        if (url) img.src = url;
      } catch (err) { /* превюто не е критично */ }
      box.appendChild(img);
    }
    document.getElementById("btnExportCancel").disabled = true;
    document.getElementById("btnExportFolder").disabled = false;
    document.getElementById("btnExportDone").disabled = false;
  },



  async openDesigns() {
    const modal = document.getElementById("designsModal");
    const list = document.getElementById("designsList");
    list.innerHTML = "";
    modal.classList.remove("hidden");
    try {
      const designs = await API.listDesigns();
      if (!designs.length) {
        list.appendChild(UI.el("p", "hint",
          "Още няма записани дизайни. Натисни „💾 Запази“."));
        return;
      }
      designs.forEach((design) => {
        const item = UI.el("div", "design-item");
        const info = UI.el("div", "grow");
        info.appendChild(UI.el("div", "dn", design.name));
        info.appendChild(UI.el("div", "dm",
          `${design.mission || ""} · ${design.saved || ""}`));

        const loadBtn = UI.el("button", "btn btn-sm", "Зареди");
        loadBtn.addEventListener("click", () => this.loadDesign(design.file));

        const delBtn = UI.el("button", "btn btn-sm btn-danger", "✕");
        delBtn.title = "Изтрий";
        delBtn.addEventListener("click", async () => {
          if (!confirm(`Да изтрия ли „${design.name}“?`)) return;
          await API.deleteDesign(design.file);
          this.openDesigns();
        });

        item.append(info, loadBtn, delBtn);
        list.appendChild(item);
      });
    } catch (err) {
      list.appendChild(UI.el("p", "hint", err.message));
    }
  },

  closeDesigns() {
    document.getElementById("designsModal").classList.add("hidden");
  },

  async loadDesign(file) {
    const status = document.getElementById("calcStatus");
    try {
      const res = await API.loadDesign(file);
      if (!res.ok) {
        status.textContent = res.error;
        return;
      }
      UI.writeInputs(res.inputs);
      this.closeDesigns();
      status.textContent = "заредено: " + res.name;
      await this.compute();
    } catch (err) {
      status.textContent = err.message;
    }
  },

  async loadExample() {
    const example = {
      name: "Trainer 1.3",
      mission: "trainer",
      payload: {
        mode: "components",
        total_g: 0,
        components: [
          { name: "Мотор 2212 1400Kv", category: "motor", qty: 1,
            unit_mass_g: 55 },
          { name: "ESC 30A", category: "esc", qty: 1, unit_mass_g: 30 },
          { name: "LiPo 3S 2200 mAh", category: "battery", qty: 1,
            unit_mass_g: 180 },
          { name: "Витло 10x6", category: "prop", qty: 1, unit_mass_g: 16 },
          { name: "Серва 9 g", category: "servo", qty: 4, unit_mass_g: 9 },
          { name: "Приемник", category: "rx", qty: 1, unit_mass_g: 10 },
          { name: "Лепило и крепеж", category: "hardware", qty: 1,
            unit_mass_g: 30 },
        ],
      },
      wing: {
        wing_loading: null, aspect_ratio: null, taper: null,
        dihedral_deg: null, tip_style: null, tip_frac: null,
        washout_deg: null,
        winglet: { enabled: false, height_mm: null, cant_deg: 85, toe_deg: 0,
                   chord_mm: null },
        airfoil: "naca2412", wing_le_ratio: 0.30,
      },
      tail: {
        vh: null, vv: null, tail_arm_ratio: null, static_margin: null,
        airfoil: "naca0009",
      },
      propulsion: {
        cells: 3, capacity_mah: 2200, endurance_min: 8,
        thrust_to_weight: null, power_to_weight: null, prop_d_in: 10,
      },
      print: {
        filament: "lw_pla", nozzle: 0.4, perimeters: 1, infill: 0,
        layer_height: 0.2, bed: [220, 220, 250],
      },
      structure: { n_limit: 4, safety_factor: 1.5 },
    };
    UI.writeInputs(example);
    await this.compute();
  },

  async reset() {
    try {
      const presets = await API.presets();
      UI.writeInputs(presets.defaults);
      await this.compute();
    } catch (err) {
      document.getElementById("calcStatus").textContent = err.message;
    }
  },
};

window.addEventListener("DOMContentLoaded", () => App.init());

