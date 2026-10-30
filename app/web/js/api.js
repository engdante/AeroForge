/**
 * api.js — тънък слой над Eel.
 *
 * Eel 0.18 връща функция, която трябва да се извика за Promise; по-старите
 * версии връщат Promise директно. Поддържаме и двата варианта.
 */
const API = {
  available() {
    return typeof eel !== "undefined" && eel !== null;
  },

  async call(name, ...args) {
    if (!this.available() || typeof eel[name] !== "function") {
      throw new Error(
        "Eel не е налично. Стартирай приложението с start.bat " +
        "(или python app\\server.py)."
      );
    }
    const result = eel[name](...args);
    if (typeof result === "function") {
      return await result();
    }
    return await result;
  },

  presets() { return this.call("get_presets"); },
  compute(inputs) { return this.call("compute_design", inputs); },
  exportReport(inputs) { return this.call("export_report", inputs); },
  saveDesign(name, inputs) { return this.call("save_design", name, inputs); },
  loadDesign(name) { return this.call("load_design", name); },
  listDesigns() { return this.call("list_designs"); },
  deleteDesign(name) { return this.call("delete_design", name); },
  paths() { return this.call("get_paths"); },
  openFolder(which) { return this.call("open_folder", which); },
  airfoilShape(key) { return this.call("airfoil_shape", key, 81); },
  model3d(inputs) { return this.call("get_model3d", inputs); },
  getSettings() { return this.call("get_settings"); },
  saveSettings(payload) { return this.call("save_settings", payload); },
  resetSettings() { return this.call("reset_settings"); },
};

/** Форматира число с фиксирани знаци; null/undefined -> „—“ */
function fmt(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("bg-BG", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Форматира цяло число с разделител за хиляди */
function fmt0(value) { return fmt(value, 0); }

/** Дебаунс за преизчисляване при писане */
function debounce(fn, delay = 250) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}
