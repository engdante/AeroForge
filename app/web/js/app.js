/**
 * app.js — свързване на UI със сървъра, състояние и експорти.
 */
const App = {
  result: null,
  busy: false,
  paths: null,

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
    document.querySelectorAll(".viewer-bar [data-view]").forEach((btn) => {
      btn.addEventListener("click", () => Viewer.setView(btn.dataset.view));
    });
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
      .addEventListener("click", () => this.exportReport());
    document.getElementById("btnLoad")
      .addEventListener("click", () => this.openDesigns());
    document.getElementById("btnCloseModal")
      .addEventListener("click", () => this.closeDesigns());
    document.getElementById("designsModal")
      .addEventListener("click", (event) => {
        if (event.target.id === "designsModal") this.closeDesigns();
      });
    document.getElementById("btnExample")
      .addEventListener("click", () => this.loadExample());
    document.getElementById("btnReset")
      .addEventListener("click", () => this.reset());

    const status = document.getElementById("calcStatus");
    status.style.cursor = "pointer";
    status.title = "Двойно щракване отваря папката с отчети";
    status.addEventListener("dblclick", () => API.openFolder("exports"));

    window.addEventListener("resize", debounce(() => {
      if (this.result) UI.renderResult(this.result);
    }, 300));
  },

  switchTab(name) {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === name);
    });
    document.querySelectorAll(".pane").forEach((pane) => {
      pane.classList.toggle("active", pane.id === "pane-" + name);
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

  async exportReport() {
    const status = document.getElementById("calcStatus");
    status.textContent = "записва отчет…";
    try {
      const res = await API.exportReport(UI.readInputs());
      if (res.ok) {
        status.textContent = "отчет: " + res.paths.folder;
        status.title = res.paths.folder + " (двойно щракване за отваряне)";
      } else {
        status.textContent = "грешка: " + res.error;
      }
    } catch (err) {
      status.textContent = err.message;
    }
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
        dihedral_deg: null, airfoil: "naca2412", wing_le_ratio: 0.30,
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

