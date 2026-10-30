/**
 * settings.js — прозорец „Настройки“: каталог на филаментите и базови
 * стойности за нов дизайн (пази се в settings.json до приложението).
 */
const Settings = {
  data: null,

  $(id) { return document.getElementById(id); },

  async open() {
    const modal = this.$("settingsModal");
    modal.classList.remove("hidden");
    this.$("settingsStatus").textContent = "зарежда…";
    try {
      this.data = await API.getSettings();
      this.render();
      this.$("settingsStatus").textContent = this.data.custom
        ? "използват се твоите настройки"
        : "използват се вградените стойности";
    } catch (err) {
      this.$("settingsStatus").textContent = err.message;
    }
  },

  close() {
    this.$("settingsModal").classList.add("hidden");
  },

  render() {
    const d = this.data;
    this.renderFilaments(d.filaments);
    this.$("settingsPathInfo").textContent = "Файл: " + d.path +
      (d.error ? "  ·  " + d.error : "");

    const filSelect = this.$("setDefaultFilament");
    filSelect.innerHTML = "";
    d.filaments.forEach((f) => {
      const opt = UI.el("option", null, f.name);
      opt.value = f.key;
      filSelect.appendChild(opt);
    });
    const defaults = d.defaults || {};
    const prt = defaults.print || {};
    const prop = defaults.propulsion || {};
    const des = defaults.design || {};
    filSelect.value = prt.filament || (d.filaments[0] || {}).key;

    const missionSelect = this.$("setDefaultMission");
    missionSelect.innerHTML = "";
    (UI.presets ? UI.presets.missions : []).forEach((m) => {
      const opt = UI.el("option", null, m.label);
      opt.value = m.key;
      missionSelect.appendChild(opt);
    });
    missionSelect.value = des.mission || "trainer";

    this.$("setPayload").value = des.payload_total_g || 600;
    this.$("setNozzle").value = String(prt.nozzle || 0.4);
    this.$("setPerimeters").value =
      prt.perimeters === null || prt.perimeters === undefined
        ? "" : prt.perimeters;
    this.$("setInfill").value =
      prt.infill === null || prt.infill === undefined ? "" : prt.infill;
    this.$("setLayer").value = prt.layer_height || 0.2;
    this.$("setCells").value = prop.cells || 3;
    this.$("setEndurance").value = prop.endurance_min || 8;
    const bed = prt.bed || [220, 220, 250];
    this.$("setBedX").value = bed[0];
    this.$("setBedY").value = bed[1];
    this.$("setBedZ").value = bed[2];
  },

  renderFilaments(filaments) {
    const box = this.$("filamentRows");
    box.innerHTML = "";
    filaments.forEach((f) => this.addRow(f));
  },

  addRow(spec) {
    const f = spec || {};
    const row = UI.el("div", "fil-row");
    row.dataset.key = f.key || "";

    const fields = [
      ["name", "text", f.name || "", "име"],
      ["printed_density", "number", f.printed_density, "1.24"],
      ["price_per_kg", "number", f.price_per_kg, "20"],
      ["tensile_mpa", "number", f.tensile_mpa, "50"],
      ["e_mpa", "number", f.e_mpa, "3500"],
      ["layer_factor", "number", f.layer_factor, "0.65"],
      ["max_flow", "number", f.max_flow, "11"],
      ["expansion", "number", f.expansion, "1"],
    ];
    fields.forEach(([name, type, value, placeholder]) => {
      const input = UI.el("input", "fil-" + name);
      input.type = type;
      input.placeholder = placeholder;
      if (type === "number") {
        input.step = (name === "layer_factor" || name === "expansion")
          ? "0.01" : "0.1";
        input.min = "0";
      }
      input.value = (value === undefined || value === null) ? "" : value;
      row.appendChild(input);
    });

    const del = UI.el("button", "row-del", "✕");
    del.type = "button";
    del.title = "Изтрий филамента";
    del.addEventListener("click", () => row.remove());
    row.appendChild(del);

    this.$("filamentRows").appendChild(row);
  },

  makeKey(name) {
    const used = new Set(Array.from(
      this.$("filamentRows").querySelectorAll(".fil-row"))
      .map((r) => r.dataset.key)
      .filter(Boolean));
    const base = String(name || "filament").trim().toLowerCase()
      .replace(/[^a-z0-9а-я]+/gi, "_").replace(/^_+|_+$/g, "")
      .slice(0, 30) || "filament";
    let key = base;
    let i = 2;
    while (used.has(key)) { key = base + "_" + i; i += 1; }
    return key;
  },

  readFilaments() {
    const out = {};
    this.$("filamentRows").querySelectorAll(".fil-row").forEach((row) => {
      const val = (cls) => row.querySelector(".fil-" + cls).value.trim();
      const name = val("name");
      if (!name) return;
      let key = row.dataset.key;
      if (!key) {
        key = this.makeKey(name);
        row.dataset.key = key;
      }
      out[key] = {
        key: key,
        name: name,
        printed_density: val("printed_density"),
        price_per_kg: val("price_per_kg"),
        tensile_mpa: val("tensile_mpa"),
        e_mpa: val("e_mpa"),
        layer_factor: val("layer_factor"),
        max_flow: val("max_flow"),
        expansion: val("expansion"),
      };
    });
    return out;
  },

  readDefaults() {
    const num = (id) => {
      const raw = this.$(id).value.trim();
      if (raw === "") return null;
      const v = Number(raw.replace(",", "."));
      return Number.isFinite(v) ? v : null;
    };
    return {
      print: {
        filament: this.$("setDefaultFilament").value,
        nozzle: num("setNozzle") || 0.4,
        perimeters: num("setPerimeters"),
        infill: num("setInfill"),
        layer_height: num("setLayer") || 0.2,
        bed: [num("setBedX") || 220, num("setBedY") || 220,
              num("setBedZ") || 250],
      },
      propulsion: {
        cells: num("setCells") || 3,
        endurance_min: num("setEndurance") || 8,
      },
      design: {
        mission: this.$("setDefaultMission").value,
        payload_total_g: num("setPayload") || 600,
      },
    };
  },

  async save() {
    const status = this.$("settingsStatus");
    status.textContent = "записва…";
    try {
      const payload = {
        filaments: this.readFilaments(),
        defaults: this.readDefaults(),
      };
      const res = await API.saveSettings(payload);
      if (!res.ok) {
        status.textContent = "грешка: " + res.error;
        return;
      }
      this.data = res.settings;
      this.close();
      await App.refreshFromSettings();
      document.getElementById("calcStatus").textContent =
        "настройките са запазени";
    } catch (err) {
      status.textContent = err.message;
    }
  },

  async reset() {
    if (!confirm("Да върна ли вградените филаменти и стойности?")) return;
    const status = this.$("settingsStatus");
    status.textContent = "възстановява…";
    try {
      const res = await API.resetSettings();
      if (!res.settings) {
        status.textContent = "грешка: " + (res.error || "неизвестна");
        return;
      }
      this.data = res.settings;
      this.render();
      await App.refreshFromSettings();
      status.textContent = "възстановени вградени стойности";
    } catch (err) {
      status.textContent = err.message;
    }
  },

  bind() {
    this.$("btnSettings").addEventListener("click", () => this.open());
    this.$("btnCloseSettings").addEventListener("click", () => this.close());
    this.$("btnCancelSettings").addEventListener("click", () => this.close());
    this.$("settingsModal").addEventListener("click", (event) => {
      if (event.target.id === "settingsModal") this.close();
    });
    this.$("btnSaveSettings").addEventListener("click", () => this.save());
    this.$("btnResetSettings").addEventListener("click", () => this.reset());
    this.$("btnAddFilament").addEventListener("click", () => this.addRow({
      name: "Нов филамент",
      printed_density: 1.24,
      price_per_kg: 25,
      tensile_mpa: 45,
      e_mpa: 2500,
      layer_factor: 0.65,
      max_flow: 11,
      expansion: 1,
    }));
  },
};


