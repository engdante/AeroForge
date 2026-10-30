/**
 * ui.js — четене/писане на формата и рендиране на резултатите.
 */
const UI = {
  presets: null,

  $(id) { return document.getElementById(id); },

  el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  },

  /** Зарежда справочните данни в селектите и панелите. */
  setPresets(p) {
    this.presets = p;

    const mission = this.$("missionSelect");
    mission.innerHTML = "";
    p.missions.forEach((m) => {
      const opt = this.el("option", null, m.label);
      opt.value = m.key;
      opt.title = m.description;
      mission.appendChild(opt);
    });

    const airfoil = this.$("airfoilSelect");
    airfoil.innerHTML = "";
    p.airfoils.forEach((a) => {
      const opt = this.el("option", null, `${a.name} — ${a.use}`);
      opt.value = a.key;
      airfoil.appendChild(opt);
    });

    const filament = this.$("filamentSelect");
    filament.innerHTML = "";
    p.filaments.forEach((f) => {
      const opt = this.el("option", null,
        `${f.name} (${f.printed_density.toFixed(2)} g/cm³)`);
      opt.value = f.key;
      opt.title = f.notes;
      filament.appendChild(opt);
    });

    const prop = this.$("propSize");
    prop.innerHTML = '<option value="">авто</option>';
    p.prop_sizes.forEach((d) => {
      const opt = this.el("option", null, d + "″");
      opt.value = String(d);
      prop.appendChild(opt);
    });

    const preset = this.$("presetSelect");
    preset.innerHTML = '<option value="">+ от списък…</option>';
    p.component_presets.forEach((cp, i) => {
      const opt = this.el("option", null,
        `${cp.name} (${cp.unit_mass_g} g)`);
      opt.value = String(i);
      preset.appendChild(opt);
    });

    this.$("designsPath").textContent = "Дизайни: " + p.paths.designs;
    this.updateMissionInfo();
    this.updateFilamentInfo();
    this.updateAirfoilInfo();
  },

  /** Прилага шрифта и размера от настройките (CSS променливи). */
  applyFont(ui) {
    if (!ui) return;
    const root = document.documentElement;
    const size = Math.min(20, Math.max(11,
      Math.round(Number(ui.size) || 13)));
    const css = ui.css || (this.presets && this.presets.ui && this.presets.ui.css)
      || '"Segoe UI", Tahoma, sans-serif';
    root.style.setProperty("--ui-font", css);
    root.style.setProperty("--ui-font-size", size + "px");
    root.style.setProperty("--ui-scale", String(size / 13));
  },

  updateMissionInfo() {
    const key = this.$("missionSelect").value;
    const m = this.presets.missions.find((x) => x.key === key);
    if (!m) return;
    this.$("missionChip").textContent = m.label;
    this.$("missionDesc").textContent = m.description;
    const stats = this.$("missionStats");
    stats.innerHTML = "";
    const items = [
      ["Натоварване", `${m.wing_loading} g/dm²`],
      ["Диапазон", `${m.wing_loading_range[0]}–${m.wing_loading_range[1]}`],
      ["AR / свиване", `${m.aspect_ratio} / ${m.taper}`],
      ["Тяга : тегло", `${m.thrust_to_weight}`],
      ["Мощност", `${m.power_to_weight} W/kg`],
      ["Статичен запас", `${Math.round(m.static_margin * 100)} %`],
      ["Опашка", m.has_tail ? `V_h ${m.vh} / V_v ${m.vv}` : "без опашка"],
      ["Натоварване n", `${m.n_limit} g`],
    ];
    items.forEach(([k, v]) => {
      const div = this.el("div");
      div.appendChild(this.el("span", null, k + ": "));
      div.appendChild(this.el("b", null, v));
      stats.appendChild(div);
    });
    this.$("wingLoadingHint").textContent =
      `Автоматично за „${m.label}“: ${m.wing_loading} g/dm² ` +
      `(типично ${m.wing_loading_range[0]}–${m.wing_loading_range[1]}).`;
  },

  updateFilamentInfo() {
    const key = this.$("filamentSelect").value;
    const f = this.presets.filaments.find((x) => x.key === key);
    if (!f) return;
    this.$("filamentInfo").textContent =
      `${f.notes} Плътност ${f.printed_density.toFixed(2)} g/cm³, ` +
      `~${f.price_per_kg} €/kg.`;
  },

  updateAirfoilInfo() {
    const key = this.$("airfoilSelect").value;
    const a = this.presets.airfoils.find((x) => x.key === key);
    if (!a) return;
    this.$("airfoilInfo").textContent =
      `${a.name}: CL_max ${a.cl_max}, CD_min ${a.cd_min}, ` +
      `Re ${(a.re_range[0] / 1000).toFixed(0)}k–` +
      `${(a.re_range[1] / 1000).toFixed(0)}k.`;
    this.drawAirfoil(a);
  },

  async drawAirfoil(airfoil) {
    const canvas = this.$("airfoilCanvas");
    if (!canvas) return;
    try {
      const shape = await API.airfoilShape(airfoil.key);
      if (shape && shape.ok && shape.upper && shape.upper.length) {
        const source = shape.approximate
          ? "приблизителен контур (дебелина и камера от каталога)"
          : "контур по NACA";
        Charts.airfoil(canvas, shape.upper, shape.lower,
          `${airfoil.name} — ${source}`);
      } else {
        Charts.airfoil(canvas, null, null,
          `${airfoil.name} — няма контур за този профил`);
      }
    } catch (err) {
      Charts.airfoil(canvas, null, null,
        "контурът не е достъпен (няма връзка със сървъра)");
    }
  },

  // ---------------------------------------------------------------- форми
  _num(id) {
    const el = this.$(id);
    if (!el) return null;
    const raw = String(el.value || "").trim();
    if (raw === "") return null;
    const value = Number(raw.replace(",", "."));
    return Number.isFinite(value) ? value : null;
  },

  addComponentRow(component) {
    const row = this.el("div", "component-row");
    const c = component || {};

    const name = this.el("input", "c-name");
    name.type = "text";
    name.placeholder = "име";
    name.value = c.name || "";

    const cat = this.el("select", "c-cat");
    this.presets.categories.forEach((category) => {
      const opt = this.el("option", null, category.label);
      opt.value = category.key;
      cat.appendChild(opt);
    });
    cat.value = c.category || "other";

    const qty = this.el("input", "c-qty");
    qty.type = "number";
    qty.min = "0";
    qty.step = "1";
    qty.value = c.qty !== undefined ? c.qty : 1;

    const mass = this.el("input", "c-mass");
    mass.type = "number";
    mass.min = "0";
    mass.step = "0.5";
    mass.placeholder = "g";
    mass.value = c.unit_mass_g !== undefined ? c.unit_mass_g : "";

    const x = this.el("input", "c-x");
    x.type = "number";
    x.step = "5";
    x.placeholder = "авто";
    x.value = (c.x_mm !== null && c.x_mm !== undefined) ? c.x_mm : "";

    const del = this.el("button", "row-del", "✕");
    del.type = "button";
    del.title = "Изтрий реда";
    del.addEventListener("click", () => row.remove());

    row.append(name, cat, qty, mass, x, del);
    this.$("componentRows").appendChild(row);
  },

  readInputs() {
    const modeEl = document.querySelector(
      'input[name="payloadMode"]:checked');
    const mode = modeEl ? modeEl.value : "simple";

    const components = [];
    // В simple режим редовете са скрити, но остават в DOM. Не ги изпращай,
    // иначе backend-ът ги добавя към общото тегло и масата се брои двойно.
    if (mode === "components") {
      document.querySelectorAll("#componentRows .component-row").forEach((row) => {
        const name = row.querySelector(".c-name").value.trim();
        const mass = row.querySelector(".c-mass").value.trim();
        if (!name && !mass) return;
        const xRaw = row.querySelector(".c-x").value.trim();
        components.push({
          name: name || "Компонент",
          category: row.querySelector(".c-cat").value,
          qty: Number(row.querySelector(".c-qty").value || 1),
          unit_mass_g: Number(String(mass).replace(",", ".") || 0),
          x_mm: xRaw === "" ? null : Number(xRaw.replace(",", ".")),
        });
      });
    }

    const marginPct = this._num("staticMargin");
    const wingLePct = this._num("wingLeRatio");
    const bedX = this._num("bedX") || 220;
    const bedY = this._num("bedY") || 220;
    const bedZ = this._num("bedZ") || 250;

    return {
      name: this.$("designName").value.trim() || "Нов дизайн",
      mission: this.$("missionSelect").value,
      payload: {
        mode,
        total_g: this._num("payloadTotal") || 0,
        components,
      },
      wing: {
        wing_loading: this._num("wingLoading"),
        aspect_ratio: this._num("aspectRatio"),
        taper: this._num("taper"),
        dihedral_deg: this._num("dihedral"),
        airfoil: this.$("airfoilSelect").value,
        wing_le_ratio: wingLePct === null ? 0.30 : wingLePct / 100,
      },
      tail: {
        vh: this._num("vh"),
        vv: this._num("vv"),
        tail_arm_ratio: this._num("tailArm"),
        static_margin: marginPct === null ? null : marginPct / 100,
        airfoil: "naca0009",
      },
      propulsion: {
        cells: this._num("cells") || 3,
        capacity_mah: this._num("capacity"),
        endurance_min: this._num("endurance") || 8,
        thrust_to_weight: this._num("tw"),
        power_to_weight: this._num("pw"),
        prop_d_in: this._num("propSize"),
      },
      print: {
        filament: this.$("filamentSelect").value,
        nozzle: Number(this.$("nozzle").value),
        perimeters: this._num("perimeters"),
        infill: this._num("infill"),
        layer_height: this._num("layerHeight") || 0.2,
        bed: [bedX, bedY, bedZ],
      },
      structure: {
        n_limit: this._num("nLimit"),
        safety_factor: this._num("safetyFactor") || 1.5,
      },
    };
  },

  writeInputs(inputs) {
    const set = (id, value) => {
      const el = this.$(id);
      if (!el) return;
      el.value = (value === null || value === undefined) ? "" : value;
    };
    const inp = inputs || {};

    this.$("designName").value = inp.name || "Нов дизайн";
    if (inp.mission) this.$("missionSelect").value = inp.mission;

    const payload = inp.payload || {};
    const mode = payload.mode === "components" ? "components" : "simple";
    document.querySelectorAll('input[name="payloadMode"]').forEach((r) => {
      r.checked = (r.value === mode);
    });
    this.togglePayloadMode();
    set("payloadTotal", payload.total_g !== undefined ? payload.total_g : 600);

    this.$("componentRows").innerHTML = "";
    (payload.components || []).forEach((c) => this.addComponentRow(c));

    const wing = inp.wing || {};
    set("wingLoading", wing.wing_loading);
    set("aspectRatio", wing.aspect_ratio);
    set("taper", wing.taper);
    set("dihedral", wing.dihedral_deg);
    set("wingLeRatio", Math.round((wing.wing_le_ratio !== undefined
      ? wing.wing_le_ratio : 0.30) * 100));
    if (wing.airfoil) this.$("airfoilSelect").value = wing.airfoil;

    const tail = inp.tail || {};
    set("vh", tail.vh);
    set("vv", tail.vv);
    set("tailArm", tail.tail_arm_ratio);
    set("staticMargin", (tail.static_margin === null
      || tail.static_margin === undefined)
      ? null : Math.round(tail.static_margin * 100));

    const power = inp.propulsion || {};
    set("cells", power.cells || 3);
    set("capacity", power.capacity_mah);
    set("endurance", power.endurance_min || 8);
    set("tw", power.thrust_to_weight);
    set("pw", power.power_to_weight);
    set("propSize", power.prop_d_in ? String(power.prop_d_in) : "");

    const print = inp.print || {};
    if (print.filament) this.$("filamentSelect").value = print.filament;
    if (print.nozzle) this.$("nozzle").value = String(print.nozzle);
    set("perimeters", print.perimeters);
    set("infill", print.infill);
    set("layerHeight", print.layer_height || 0.2);
    const bed = print.bed || [220, 220, 250];
    set("bedX", bed[0]);
    set("bedY", bed[1]);
    set("bedZ", bed[2]);

    const structure = inp.structure || {};
    set("nLimit", structure.n_limit);
    set("safetyFactor", structure.safety_factor || 1.5);

    this.updateMissionInfo();
    this.updateFilamentInfo();
    this.updateAirfoilInfo();
  },

  togglePayloadMode() {
    const modeEl = document.querySelector(
      'input[name="payloadMode"]:checked');
    const mode = modeEl ? modeEl.value : "simple";
    this.$("simpleBox").classList.toggle("hidden", mode !== "simple");
    this.$("componentsBox").classList.toggle("hidden", mode !== "components");
  },

  /** Показва „авто“ стойностите като placeholder. */
  syncAutoHints(res) {
    if (!res || !res.resolved) return;
    const r = res.resolved;
    const setPh = (id, value) => {
      const el = this.$(id);
      if (!el) return;
      const isAuto = String(el.value || "").trim() === "";
      el.placeholder = isAuto ? "авто: " + value : "авто";
    };
    setPh("wingLoading", fmt(r.wing_loading, 0));
    setPh("aspectRatio", fmt(r.aspect_ratio, 1));
    setPh("taper", fmt(r.taper, 2));
    setPh("dihedral", fmt(r.dihedral_deg, 1));
    setPh("vh", fmt(r.vh, 2));
    setPh("vv", fmt(r.vv, 3));
    setPh("tailArm", fmt(r.tail_arm_ratio, 2));
    setPh("staticMargin", fmt(r.static_margin * 100, 0));
    setPh("tw", fmt(r.thrust_to_weight, 2));
    setPh("pw", fmt(r.power_to_weight, 0));
    setPh("perimeters", r.perimeters);
    setPh("infill", r.infill);
  },

  // ------------------------------------------------------------- рендиране
  fillKv(table, rows) {
    table.innerHTML = "";
    rows.forEach(([label, value]) => {
      const tr = this.el("tr");
      tr.appendChild(this.el("td", null, label));
      tr.appendChild(this.el("td", null, value));
      table.appendChild(tr);
    });
  },

  fillData(table, headers, rows, totalRow) {
    table.innerHTML = "";
    const thead = this.el("thead");
    const trh = this.el("tr");
    headers.forEach((h) => trh.appendChild(this.el("th", null, h)));
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = this.el("tbody");
    rows.forEach((row) => {
      const tr = this.el("tr");
      row.forEach((cell) => tr.appendChild(this.el("td", null, cell)));
      tbody.appendChild(tr);
    });
    if (totalRow) {
      const tr = this.el("tr", "total");
      totalRow.forEach((cell) => tr.appendChild(this.el("td", null, cell)));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
  },

  showError(message) {
    this.$("verdict").className = "verdict error";
    this.$("verdict").textContent = "⚠ Грешка при изчислението";
    this.$("verdictStats").textContent = message;
  },

  renderResult(res) {
    if (!res || res.ok === false) {
      this.showError((res && res.error) || "неизвестна грешка");
      return;
    }

    const g = res.geometry;
    const a = res.aero;
    const w = res.weights;
    const s = res.stability;
    const p = res.propulsion;
    const st = res.structure;
    const pr = res.print;
    const bat = p.battery;

    const counts = { ok: 0, warn: 0, error: 0, info: 0 };
    res.checks.forEach((c) => {
      counts[c.level] = (counts[c.level] || 0) + 1;
    });
    const verdict = this.$("verdict");
    if (counts.error > 0) {
      verdict.className = "verdict error";
      verdict.textContent =
        `❌ ${counts.error} критични проблема — дизайнът не е готов за полет`;
    } else if (counts.warn > 0) {
      verdict.className = "verdict warn";
      verdict.textContent = `⚠️ Лети, но с ${counts.warn} забележки`;
    } else {
      verdict.className = "verdict ok";
      verdict.textContent = "✅ Дизайнът минава всички проверки";
    }
    this.$("verdictStats").textContent =
      `${res.mission.label} · ${res.checks.length} проверки · ` +
      `итерации ${w.iterations}`;

    const cards = this.$("cards");
    cards.innerHTML = "";
    const addCard = (k, v, sub, hl) => {
      const card = this.el("div", "card" + (hl ? " hl" : ""));
      card.appendChild(this.el("div", "k", k));
      card.appendChild(this.el("div", "v", v));
      if (sub) card.appendChild(this.el("div", "s", sub));
      cards.appendChild(card);
    };
    addCard("Обща маса", fmt0(w.total_g) + " g",
      `товар ${fmt0(w.payload_g)} · печат ${fmt0(w.airframe_g)} g`, true);
    addCard("Размах", fmt0(g.span_mm) + " mm",
      `площ ${fmt(g.area_dm2, 1)} dm² · AR ${fmt(g.aspect_ratio, 1)}`);
    addCard("Натоварване", fmt(g.wing_loading_g_dm2, 1) + " g/dm²",
      `коренов хорд ${fmt0(g.c_root_mm)} mm` +
      (res.resolved.wing_loading_escalated
        ? ` · вдигнато от ${fmt(res.resolved.wing_loading_requested, 0)}`
        : ""),
      res.resolved.wing_loading_escalated);
    addCard("V_stall", fmt(a.v_stall_ms, 1) + " m/s",
      fmt0(a.v_stall_kmh) + " km/h");
    addCard("Крейсер", fmt(a.v_cruise_ms, 1) + " m/s",
      `L/D ${fmt(a.ld_max, 1)} · Re ${Math.round(a.re_cruise / 1000)}k`);
    addCard("Тяга : тегло", fmt(p.thrust_to_weight_actual, 2) + " : 1",
      `${fmt0(p.p_max_elec_w)} W · витло ${p.prop_d_in}″`);
    addCard("Време на полет", "~" + fmt0(bat.endurance_min) + " мин",
      `${bat.cells}S ${fmt0(bat.capacity_mah)} mAh`);
    addCard("ЦТ", fmt(s.cg_pct_mac, 1) + " % MAC",
      `статичен запас ${fmt(s.static_margin_pct, 0)} %` +
      (s.battery_feasible === false ? " · ⚠️ балансът не е постижим" : ""),
      s.battery_feasible === false);
    addCard("Профил", g.airfoil.name,
      `CL_max ${fmt(g.airfoil.cl_max, 2)} · t/c ` +
      `${fmt(st.thickness_ratio * 100, 0)} %`);
    addCard("Печат", fmt0(pr.total_mass_g) + " g",
      `${fmt(pr.time_h, 1)} h · ${fmt0(pr.cost)} € · ${pr.pieces} части`);

    const checks = this.$("checks");
    checks.innerHTML = "";
    const icons = { ok: "✅", warn: "⚠️", error: "❌", info: "ℹ️" };
    res.checks.forEach((c) => {
      const box = this.el("div", "check " + c.level);
      box.appendChild(this.el("div", "icon", icons[c.level] || "•"));
      const body = this.el("div");
      body.appendChild(this.el("div", "t", c.title));
      body.appendChild(this.el("div", "d", c.detail));
      box.appendChild(body);
      checks.appendChild(box);
    });

    this.fillKv(this.$("geometryTable"), [
      ["Площ на крилото",
        `${fmt(g.area_dm2, 1)} dm² (${fmt(g.area_m2, 3)} m²)`],
      ["Размах", `${fmt0(g.span_mm)} mm`],
      ["Коренов / върхов хорд",
        `${fmt0(g.c_root_mm)} / ${fmt0(g.c_tip_mm)} mm`],
      ["MAC", `${fmt0(g.mac_mm)} mm`],
      ["Разтежение / свиване",
        `${fmt(g.aspect_ratio, 2)} / ${fmt(g.taper, 2)}`],
      ["Диаедър", `${fmt(g.dihedral_deg, 1)}°`],
      ["Профил", `${g.airfoil.name} (CL_max ${fmt(g.airfoil.cl_max, 2)})`],
      ["CL_max при Re",
        `${fmt(a.cl_max, 2)} (каталожно ${fmt(a.cl_max_catalog, 2)})`],
      ["Re в крейсер", fmt0(a.re_cruise)],
      ["L/D max", `${fmt(a.ld_max, 1)} при CL ${fmt(a.cl_at_ld_max, 2)}`],
      ["CD0 / Oswald", `${fmt(a.cd0, 3)} / ${fmt(a.oswald, 2)}`],
      ["Нужна мощност в крейсер", `${fmt0(a.power_required_w)} W`],
      ["Фюзелаж (Д×Ш×В)",
        `${fmt0(g.fuselage.length_mm)} × ${fmt0(g.fuselage.width_mm)} × ` +
        `${fmt0(g.fuselage.height_mm)} mm`],
      ["Крило от носа",
        `${fmt0(g.wing_le_mm)} mm` + (g.wing_le_recommended_mm &&
        Math.abs(g.wing_le_recommended_mm - g.wing_le_mm) > 5
          ? ` (препоръка ${fmt0(g.wing_le_recommended_mm)} mm)` : "")],
    ]);

    this.fillKv(this.$("propulsionTable"), [
      ["Максимална мощност",
        `${fmt0(p.p_max_elec_w)} W (вал ${fmt0(p.p_max_shaft_w)} W)`],
      ["Тяга (статична)",
        `${fmt(p.thrust_avail_n, 1)} N ≈ ${fmt(p.thrust_avail_kg, 2)} kg`],
      ["Витло", `${p.prop_d_in}×${p.prop_pitch_in} инча`],
      ["Обороти", `${fmt0(p.rpm_target)} об/мин (J ${fmt(p.advance_ratio_cruise, 2)}, лимит ${fmt0(p.rpm_tip)})`],
      ["Kv на мотора", fmt0(p.kv)],
      ["Максимален ток",
        `${fmt(p.i_max_a, 1)} A → ESC ${p.esc_a} A` +
        (p.esc_saturated ? " ⚠️" : "")],
      ["Батерия",
        `${bat.cells}S ${fmt0(bat.capacity_mah)} mAh, ` +
        `${fmt(bat.energy_wh, 1)} Wh`],
      ["Нужен C-рейтинг", `${fmt(bat.c_rating_needed, 0)}C`],
      ["Маса на батерията",
        `${fmt0(bat.mass_g)} g (${bat.mass_source || "оценка"})`],
      ["Време на полет",
        `${fmt(bat.endurance_min, 0)} мин (цел ` +
        `${fmt(bat.endurance_target_min, 0)})`],
      ["Крейсер",
        `${fmt(p.cruise.v_ms, 1)} m/s · ${fmt0(p.cruise.p_elec_w)} W · ` +
        `съпротивление ${fmt(p.cruise.drag_n, 2)} N`],
    ]);

    this.fillKv(this.$("stabilityTable"), [
      ["ЦТ",
        `${fmt0(s.x_cg_mm)} mm от носа (${fmt(s.cg_pct_mac, 1)} % MAC)`],
      ["Аеродинамичен център", `${fmt0(s.x_ac_mm)} mm`],
      ["Неутрална точка",
        `${fmt0(s.x_np_mm)} mm (с приноса на опашката)`],
      ["Целеви ЦТ", `${fmt0(s.x_target_mm)} mm`],
      ["Статичен запас",
        `${fmt(s.static_margin_pct, 1)} % (цел ` +
        `${fmt(s.static_margin_target * 100, 0)} %)`],
      ["Място за батерията",
        s.battery_x_required_mm !== null
          ? (s.battery_feasible === false
            ? `${fmt0(s.battery_x_required_mm)} mm от носа — извън обхвата, ` +
              `сложена на ${fmt0(s.battery_x_placed_mm)} mm`
            : `${fmt0(s.battery_x_required_mm)} mm от носа`)
          : "—"],
      ["Отместване спрямо авто", `${fmt0(s.battery_shift_mm)} mm`],
      ["Опашка (S_h / S_v)", res.mission.has_tail
        ? `${fmt(g.tail.s_h_dm2, 1)} / ${fmt(g.tail.s_v_dm2, 1)} dm²`
        : "без опашка"],
      ["Рамо на опашката",
        `${fmt0(g.tail.l_h_mm)} mm` +
        (g.tail.tail_fit_limited
          ? ` (конфиг. ${fmt0(g.tail.l_h_configured_mm)})` : "")],
      ["Обемни коефициенти",
        `V_h ${fmt(g.tail.vh, 2)} · V_v ${fmt(g.tail.vv, 3)}`],
    ]);

    this.fillKv(this.$("structureTable"), [
      ["Коренов момент",
        `${fmt(st.m_root_nm, 1)} N·m (граничен ${fmt(st.m_ult_nm, 1)})`],
      ["Натоварване / сигурност",
        `${fmt(st.n_limit, 1)} g / SF ${fmt(st.safety_factor, 2)}`],
      ["Височина на спаровия пояс", `${fmt(st.spar_height_mm, 1)} mm`],
      ["Нужна площ на капсите", `${fmt(st.cap_area_req_mm2, 1)} mm²`],
      ["Печатани капси", `${fmt(st.cap_area_print_mm2, 1)} mm²`],
      ["Решение", st.solution],
      ["Карбон (ако е нужен)", st.carbon_required
        ? `${st.carbon.width_mm}×${st.carbon.thickness_mm} mm × ` +
          `${st.carbon.count}` +
          (st.carbon_for_stiffness ? " (за коравина)" : "")
        : "не е нужен"],
      ["Съединителна тръба",
        `⌀${st.joiner_tube.od_mm}×${st.joiner_tube.id_mm} mm × ` +
        `${st.joiner_tube.length_mm} mm`],
      ["Деформация на върха",
        `${fmt(st.carbon_required ? st.deflection_carbon_mm
          : st.deflection_print_mm, 1)} mm ` +
        `(лимит ${fmt0(st.deflection_limit_mm)})`],
    ]);

    const partRows = pr.parts.map((part) => [
      part.name, part.pieces, fmt(part.volume_cm3, 1),
      fmt0(part.mass_g), fmt(part.filament_m, 1),
      fmt(part.time_h, 1), fmt(part.cost, 2),
    ]);
    this.fillData(this.$("printTable"),
      ["Част", "Бр.", "Обем cm³", "Маса g", "Филамент m", "Време h",
       "Цена €"],
      partRows,
      ["Общо", pr.pieces, "", fmt0(pr.total_mass_g),
       fmt(pr.filament_m, 1), fmt(pr.time_h, 1), fmt(pr.cost, 2)]);

    const massRows = w.components.map((c) => [
      c.name + (c.estimated ? " (оценка)" : ""),
      c.category_label, fmt(c.qty, 0), fmt(c.unit_mass_g, 1),
      fmt(c.mass_g, 1),
      fmt0(c.x_placed_mm !== undefined ? c.x_placed_mm : c.x_mm),
    ]);
    this.fillData(this.$("massTable"),
      ["Компонент", "Категория", "Бр.", "Ед. g", "Общо g", "X mm"],
      massRows,
      ["Конструкция (печат)", "—", "—", "—", fmt0(w.airframe_g), "—"]);

    const filRows = w.filament_comparison.map((f) => [
      f.name, fmt0(f.mass_g), fmt(f.cost, 0),
    ]);
    this.fillData(this.$("filamentTable"),
      ["Филамент", "Маса g", "Цена €"], filRows);

    const curves = res.curves || {};
    const ldPoints = (curves.v || []).map((v, i) => [v, curves.ld[i]]);
    Charts.line(this.$("chartLD"),
      [{ name: "L/D", color: Charts.COLORS.line1, points: ldPoints }],
      {
        markers: [
          { x: a.v_stall_ms, label: "V_stall" },
          { x: a.v_cruise_ms, label: "крейсер", color: Charts.COLORS.line3 },
        ],
      });

    const reqPoints = (curves.v || []).map((v, i) => [v, curves.p_req[i]]);
    const availPoints = (curves.v || []).map((v, i) => [v, curves.p_avail[i]]);
    Charts.line(this.$("chartPower"), [
      { name: "нужна", color: Charts.COLORS.line1, points: reqPoints },
      { name: "налична", color: Charts.COLORS.line2, points: availPoints },
    ], {
      markers: [
        { x: a.v_stall_ms, label: "V_stall" },
        { x: a.v_cruise_ms, label: "крейсер", color: Charts.COLORS.line3 },
      ],
    });

    this.syncAutoHints(res);
    // контурът винаги да отговаря на избрания профил (и след първо свързване)
    this.updateAirfoilInfo();
  },
};





