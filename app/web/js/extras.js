/**
 * extras.js — прозорец „Допълнения“: APC витла и SolidCraft.
 *
 * При старт проверява какво липсва (точка на бутона); първия път, когато
 * нещо липсва, отваря прозореца сам. Изтеглянето върви на сървъра във фонова
 * нишка — тук само питаме за напредъка.
 */
const Extras = {
  status: null,
  timer: null,
  SEEN_KEY: "aeroforge.extrasSeen",

  $(id) { return document.getElementById(id); },

  async init() {
    this.$("btnExtras").addEventListener("click", () => this.open());
    this.$("btnCloseExtras").addEventListener("click", () => this.close());
    this.$("btnExtrasDone").addEventListener("click", () => this.close());
    this.$("btnApcDownload").addEventListener("click", () => this.installApc());
    this.$("btnScDownload").addEventListener("click", () => this.installSolidcraft());
    this.$("btnScLatest").addEventListener("click", () => this.installSolidcraft(true));
    this.$("btnScSetPath").addEventListener("click", () => this.setCliPath());
    await this.refresh();
    const missing = this.missing();
    let seen = false;
    try { seen = localStorage.getItem(this.SEEN_KEY) === "1"; } catch (err) { seen = false; }
    if (missing.length && !seen) this.open();
  },

  missing() {
    const st = this.status || {};
    const out = [];
    if (!(st.apc && st.apc.present)) out.push("apc");
    if (!(st.solidcraft && st.solidcraft.present)) out.push("solidcraft");
    return out;
  },

  async open() {
    this.$("extrasModal").classList.remove("hidden");
    try { localStorage.setItem(this.SEEN_KEY, "1"); } catch (err) { /* няма */ }
    await this.refresh();
    this.checkLatest();
  },

  /** Последната версия в GitHub (мрежа — не спира прозореца). */
  async checkLatest() {
    const el = this.$("scLatest");
    el.textContent = "Проверявам последната версия в GitHub…";
    try {
      const r = await API.extrasSolidcraftLatest();
      if (!r.ok) throw new Error(r.error);
      this.latest = r;
      const mine = ((this.status || {}).solidcraft || {}).version;
      const size = r.size ? ` (${(r.size / 1048576).toFixed(0)} MB)` : "";
      let text = `Последна версия: ${r.version || "?"} — ${r.name}${size}.`;
      if (mine && r.version && mine === r.version) text += " ✓ имаш я.";
      else if (mine && r.version) text += ` Имаш ${mine} — може да обновиш.`;
      el.textContent = text;
      this.$("btnScLatest").textContent = mine
        ? (mine === r.version ? "⟳ Изтегли отново" : `⬇ Обнови до ${r.version}`)
        : `⬇ Изтегли SolidCraft ${r.version || ""}`.trim();
    } catch (err) {
      el.textContent = "Няма връзка с GitHub: " + err.message;
    }
  },

  close() {
    this.$("extrasModal").classList.add("hidden");
  },

  async refresh() {
    try {
      const st = await API.extrasStatus();
      if (!st.ok) throw new Error(st.error || "грешка");
      this.status = st;
    } catch (err) {
      this.status = null;
      this.$("apcMsg").textContent = err.message;
      return;
    }
    this.render();
    this.showProgress(this.status.progress || {});
  },

  render() {
    const st = this.status;
    const apc = st.apc || {};
    const sc = st.solidcraft || {};
    const mark = (el, ok, okText, badText) => {
      el.textContent = ok ? okText : badText;
      el.classList.toggle("ok", !!ok);
    };
    mark(this.$("apcState"), apc.present, "✓ има", "липсва");
    this.$("apcInfo").textContent = apc.present
      ? `${apc.count} витла в ${apc.dir}`
      : `Няма APC файлове в ${apc.dir}.`;
    this.$("btnApcDownload").textContent = apc.present
      ? "⟳ Обнови от apcprop.com" : "⬇ Изтегли от apcprop.com";
    mark(this.$("scState"), sc.present, "✓ намерен", "не е намерен");
    this.$("scInfo").textContent = sc.present
      ? `Инсталиран: ${sc.version || "?"}${sc.portable ? " (portable)" : ""} — ${sc.cli}`
      : "solidcraft-cli не е намерен.";
    const pathInput = this.$("scCliPath");
    if (sc.cli && !pathInput.value) pathInput.value = sc.cli;
    const urlInput = this.$("scUrl");
    if (sc.url && !urlInput.value) urlInput.value = sc.url;
    this.$("extrasDot").classList.toggle("hidden", this.missing().length === 0);
  },

  showProgress(progress) {
    let running = false;
    for (const [key, box, msg] of [["apc", "apcProgress", "apcMsg"],
      ["solidcraft", "scProgress", "scMsg"]]) {
      const p = progress[key] || {};
      const el = this.$(box);
      const bar = el.querySelector(".bar");
      const active = p.state === "running";
      running = running || active;
      el.classList.toggle("hidden", !active);
      el.classList.toggle("indeterminate", active && !(p.total > 0));
      if (active && p.total > 0) {
        bar.style.width = `${Math.min(100, (100 * p.done) / p.total)}%`;
      }
      const mb = (b) => (b / 1048576).toFixed(1);
      let text = "";
      if (active) {
        text = (p.message || "…") + (p.done ? ` ${mb(p.done)}` +
          (p.total ? ` / ${mb(p.total)} MB` : " MB") : "");
      } else if (p.state === "done") {
        text = "✓ " + (p.message || "готово");
      } else if (p.state === "error") {
        text = "⚠ " + (p.message || "грешка");
      }
      this.$(msg).textContent = text;
    }
    this.$("btnApcDownload").disabled = (progress.apc || {}).state === "running";
    const scBusy = (progress.solidcraft || {}).state === "running";
    this.$("btnScDownload").disabled = scBusy;
    this.$("btnScLatest").disabled = scBusy;
    if (running && !this.timer) {
      this.timer = setInterval(() => this.poll(), 600);
    } else if (!running && this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  },

  async poll() {
    try {
      const r = await API.extrasProgress();
      const p = r.progress || {};
      const wasRunning = !!this.timer;
      this.showProgress(p);
      if (wasRunning && !this.timer) await this.finished();
    } catch (err) {
      clearInterval(this.timer);
      this.timer = null;
    }
  },

  async finished() {
    const st = await API.extrasStatus();
    if (st.ok) {
      this.status = st;
      this.render();
      this.showProgress(st.progress || {});
    }
    if (this.latest) this.checkLatest();
    // панелът „Витло“ чете списъка наново (ако е зареден)
    if (typeof UI !== "undefined" && typeof UI.loadPropellers === "function") {
      try { await UI.loadPropellers(); } catch (err) { /* не е критично */ }
    }
  },

  async installApc() {
    const r = await API.extrasInstallApc();
    this.showProgress(r.progress || {});
  },

  async installSolidcraft(latest = false) {
    const url = latest ? null : this.$("scUrl").value.trim();
    if (!latest && !url) {
      this.$("scMsg").textContent = "Въведи адрес на архива (.zip / .tar.gz).";
      return;
    }
    const r = await API.extrasInstallSolidcraft(url);
    if (!r.ok) {
      this.$("scMsg").textContent = "⚠ " + r.error;
      return;
    }
    this.showProgress(r.progress || {});
  },

  async setCliPath() {
    const path = this.$("scCliPath").value.trim();
    const r = await API.extrasSetCli(path);
    this.$("scMsg").textContent = r.ok ? `✓ пътят е запазен: ${r.cli}` : `⚠ ${r.error}`;
    if (r.ok) await this.refresh();
  },
};
