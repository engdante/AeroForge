/**
 * ui.js — четене/писане на формата и рендиране на резултатите.
 */

/** Процент от формата (25) → дял (0.25); празно → null. */
function pctOrNull(value) {
  return (value === null || value === undefined) ? null : value / 100;
}

/** Имена на конструктивните материали (ключове от ядрото). */
const MATERIAL_LABELS = {
  carbon: "Карбон", aluminium: "Алуминий", fibreglass: "Стъклопласт",
  steel: "Стомана", wood: "Дърво",
};

/**
 * Към кой таб на панела се отнася дадена проверка (по заглавието ѝ).
 * Редът е важен: първото съвпадение печели (напр. „деформация на крилото“
 * е конструкция, не крило).
 */
const CHECK_TABS = [
  ["structure",
    /спар|джойнер|лепилн|капс|стена|деформация|изкълчване|карбон|коравин/i],
  ["wing", /профил|reflex/i],
  ["fuselage", /фюзелаж|носа|къс нос|тялото/i],
  ["payload", /товар|масов|батерия в списъка|баланс|разместване/i],
  ["power", /тяга|тягата|мощност|батерия|време на полет|по-малко време|витл|esc/i],
  ["tail", /опашк|V_h|V_v|статичен запас|център на тежестта|ЦТ/i],
  ["print", /печат|конструкция|infill/i],
  ["wing", /крило|рейнолдс|загуба|хвърляне|профил|reflex/i],
];

function checkTab(title) {
  const hit = CHECK_TABS.find(([, re]) => re.test(title || ""));
  return hit ? hit[0] : null;
}

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

    // Тяло и конфигурация
    const fill = (id, items, labelKey) => {
      const el = this.$(id);
      if (!el) return;
      el.innerHTML = "";
      (items || []).forEach((item) => {
        const opt = this.el("option", null, item[labelKey || "label"]);
        opt.value = item.key;
        if (item.description) opt.title = item.description;
        el.appendChild(opt);
      });
    };
    const extras = p.fuselage || {};
    fill("fusShape", extras.shapes);
    fill("tailBoom", extras.booms);
    const lay = p.layout || {};
    this.wingPresets = lay.wing_positions || [];
    fill("propulsionLayout", lay.propulsion, "label");
    fill("wingPosition", lay.wing_positions);
    fill("tailType", lay.tail_types);
    fill("tailPlanform", lay.tail_planforms);
    fill("tailTipStyle", lay.tail_tip_styles);
    fill("tailAirfoil", p.airfoils, "name");
    fill("tipStyle", p.tip_styles);
    // плъзгачът на отместването: ±44% от височината на тялото
    const limitPct = Math.round((lay.wing_offset_limit || 0.44) * 100);
    const range = this.$("wingOffsetRange");
    if (range) {
      range.min = String(-limitPct);
      range.max = String(limitPct);
    }

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
      `${f.notes} Плътност ${f.printed_density.toFixed(2)} g/cm³.`;
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
    // Празно поле = подразбиращото се за нов дизайн (10 mm); виж writeInputs
    // за стари дизайни, където липсващият ключ значи 0.
    const wingGap = this._num("wingRootGap");
    const tailGap = this._num("tailRootGap");

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
        tip_style: this.$("tipStyle").value || null,
        tip_frac: (this._num("tipFrac") === null ? null
          : this._num("tipFrac") / 100),
        washout_deg: this._num("washout"),
        winglet: {
          // уинглетът има смисъл само при тип връх „уинглет“
          enabled: (this.$("tipStyle").value === "winglet"
            && (this._num("wingletHeight") || 0) > 0),
          height_mm: this._num("wingletHeight"),
          cant_deg: this._num("wingletCant"),
          toe_deg: this._num("wingletToe"),
          chord_mm: null,
        },
        airfoil: this.$("airfoilSelect").value,
        // елерони в проценти (празно = авто, хорда 0 = без елерони)
        ailerons: {
          chord_frac: this._num("aileronChord"),
          start_frac: this._num("aileronStart"),
          end_frac: this._num("aileronEnd"),
        },
        // празно = автоматично позициониране (null)
        wing_le_ratio: wingLePct === null ? null : wingLePct / 100,
      },
      tail: {
        // кормила в проценти (празно = авто, 0 = без)
        controls: {
          elevator_frac: this._num("elevatorChord"),
          rudder_frac: this._num("rudderChord"),
        },
        type: this.$("tailType").value || "conventional",
        vh: this._num("vh"),
        vv: this._num("vv"),
        tail_arm_ratio: this._num("tailArm"),
        static_margin: marginPct === null ? null : marginPct / 100,
        airfoil: this.$("tailAirfoil").value || "naca0009",
        planform: this.$("tailPlanform").value || "tapered",
        tip_style: this.$("tailTipStyle").value || "square",
        v_deg: this._num("vTailDeg"),
      },
      fuselage: {
        length_mm: this._num("fusLength"),
        length_ratio: this._num("fusLengthRatio"),
        width_mm: this._num("fusWidth"),
        height_mm: this._num("fusHeight"),
        shape: this.$("fusShape").value || "ellipse",
        nose_ratio: pctOrNull(this._num("fusNose")),
        cabin_ratio: pctOrNull(this._num("fusCabin")),
        tail_taper: pctOrNull(this._num("fusTaper")),
        height_ratio: this._num("fusHeightRatio"),
        tail_boom: this.$("tailBoom").value || "printed",
        frames: this._num("fusFrames") || 0,
      },
      layout: {
        propulsion: this.$("propulsionLayout").value || "tractor",
        // отместване на крилото от средното положение, mm (+ нагоре)
        wing_offset_mm: this._num("wingOffset"),
        wing_root_gap_mm: wingGap === null ? 10 : wingGap,
        tail_root_gap_mm: tailGap === null ? 10 : tailGap,
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
        spar_material: this.$("sparMaterial").value,
        joiner_material: this.$("joinerMaterial").value,
      },
      bom: {
        profile: this.$("profileSelect").value || null,
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
    if (wing.tip_style) this.$("tipStyle").value = wing.tip_style;
    set("tipFrac", (wing.tip_frac === null || wing.tip_frac === undefined)
      ? null : Math.round(wing.tip_frac * 100));
    set("washout", wing.washout_deg);
    const wl = wing.winglet || {};
    set("wingletHeight", wl.height_mm || null);
    set("wingletCant", wl.cant_deg);
    set("wingletToe", wl.toe_deg);
    this.syncWinglet();
    const tcIn = ((inp.tail || {}).controls) || {};
    const pctT = (v) => (v === null || v === undefined) ? null
      : Math.round((v > 1 ? v : v * 100) * 10) / 10;
    set("elevatorChord", pctT(tcIn.elevator_frac));
    set("rudderChord", pctT(tcIn.rudder_frac));
    const ail = wing.ailerons || {};
    const pct = (v) => (v === null || v === undefined) ? null
      : Math.round((v > 1 ? v : v * 100) * 10) / 10;
    set("aileronChord", pct(ail.chord_frac));
    set("aileronStart", pct(ail.start_frac));
    set("aileronEnd", pct(ail.end_frac));
    const wlr = wing.wing_le_ratio;
    set("wingLeRatio", (wlr === null || wlr === undefined)
      ? null : Math.round(wlr * 100));
    if (wing.airfoil) this.$("airfoilSelect").value = wing.airfoil;

    const tail = inp.tail || {};
    if (tail.type) this.$("tailType").value = tail.type;
    if (tail.planform) this.$("tailPlanform").value = tail.planform;
    if (tail.tip_style) this.$("tailTipStyle").value = tail.tip_style;
    if (tail.airfoil) this.$("tailAirfoil").value = tail.airfoil;
    set("vh", tail.vh);
    set("vv", tail.vv);
    set("tailArm", tail.tail_arm_ratio);
    set("vTailDeg", tail.v_deg);
    set("staticMargin", (tail.static_margin === null
      || tail.static_margin === undefined)
      ? null : Math.round(tail.static_margin * 100));

    const fus = inp.fuselage || {};
    set("fusLength", fus.length_mm);
    set("fusLengthRatio", fus.length_ratio);
    set("fusWidth", fus.width_mm);
    set("fusHeight", fus.height_mm);
    if (fus.shape) this.$("fusShape").value = fus.shape;
    set("fusNose", fus.nose_ratio === null || fus.nose_ratio === undefined
      ? null : Math.round(fus.nose_ratio * 100));
    set("fusCabin", fus.cabin_ratio === null || fus.cabin_ratio === undefined
      ? null : Math.round(fus.cabin_ratio * 100));
    set("fusTaper", fus.tail_taper === null || fus.tail_taper === undefined
      ? null : Math.round(fus.tail_taper * 100));
    set("fusHeightRatio", fus.height_ratio);
    if (fus.tail_boom) this.$("tailBoom").value = fus.tail_boom;
    set("fusFrames", fus.frames || 0);

    const lay = inp.layout || {};
    if (lay.propulsion) this.$("propulsionLayout").value = lay.propulsion;
    if (lay.wing_offset_mm !== null && lay.wing_offset_mm !== undefined) {
      this.setWingOffset(lay.wing_offset_mm);
    }
    // Старите дизайни нямат тези ключове: тогава луфт е 0 (крилото/опашката
    // са били неделима част от модела), а не новото подразбиране 10 mm.
    set("wingRootGap", lay.wing_root_gap_mm === undefined ? 0 : lay.wing_root_gap_mm);
    set("tailRootGap", lay.tail_root_gap_mm === undefined ? 0 : lay.tail_root_gap_mm);

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
    this.$("sparMaterial").value = structure.spar_material || "carbon";
    this.$("joinerMaterial").value = structure.joiner_material || "carbon";

    this.updateMissionInfo();
    this.updateFilamentInfo();
    this.updateAirfoilInfo();
    if (document.getElementById("tipStyle")) this.syncWinglet();
  },

  /**
   * Уинглетът е възможен само при тип връх „Уинглет“ — тук полетата се
   * заключват/освобождават, за да не може число в тях да включи уинглет
   * при друг тип (ядрото също го налага).
   */
  syncWinglet() {
    const tip = this.$("tipStyle");
    const active = !!tip && tip.value === "winglet";
    ["wingletHeight", "wingletCant", "wingletToe"].forEach((id) => {
      const el = this.$(id);
      if (!el) return;
      el.disabled = !active;
      if (el.parentElement) {
        // Скрито, а не само затъмнено: при друг тип връх няма какво да се въвежда.
        el.parentElement.style.display = active ? "" : "none";
      }
    });
    const hint = this.$("wingletHint");
    if (hint) {
      hint.textContent = active
        ? "Височина ~4–6 % от размаха; над 6 % торсията става риск."
        : "Уинглетът се включва само при тип на върха „Уинглет“.";
    }
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

    const g = res.geometry || {};
    const fus = g.fuselage || {};
    const auto = fus.auto || {};
    setPh("fusLength", fmt0(auto.length_mm));
    setPh("fusLengthRatio", fmt(auto.length_ratio, 2));
    setPh("fusWidth", fmt0(auto.width_mm));
    setPh("fusHeight", fmt0(auto.height_mm));
    setPh("fusNose", fmt(fus.nose_ratio * 100, 0));
    setPh("fusCabin", fmt(fus.cabin_ratio * 100, 0));
    setPh("fusTaper", fmt(fus.tail_taper * 100, 0));
    setPh("fusHeightRatio", fmt(fus.height_ratio, 2));
    setPh("vTailDeg", fmt((res.layout || {}).v_tail_deg, 0));
    const tc = g.tail_controls || {};
    const el = tc.elevator || {};
    const ru = tc.rudder || {};
    setPh("elevatorChord", fmt((el.auto_frac || 0) * 100, 0));
    setPh("rudderChord", fmt((ru.auto_frac || 0) * 100, 0));
    const vTail = el.kind === "ruddervator";
    const elLabel = this.$("elevatorChordLabel");
    if (elLabel) {
      elLabel.textContent = vTail ? "Руддерватор — хорда (%)"
        : "Кормило за височина — хорда (%)";
    }
    const rudderField = this.$("rudderChord");
    if (rudderField && rudderField.parentElement) {
      // при V-опашка посоката е в руддерваторите
      rudderField.parentElement.style.display = vTail ? "none" : "";
    }
    const tcHint = this.$("tailControlsHint");
    if (tcHint) {
      const srv = ((res.servos || {}).surfaces || []);
      const servoText = (key) => {
        const x = srv.find((s) => s.key === key);
        return x ? ` — серво ${x.servo.label}, нужни ${fmt(x.torque_kgcm, 2)}` +
          ` kg·cm (запас ×${fmt(x.margin, 1)})` : "";
      };
      if (!(res.mission || {}).has_tail) {
        tcHint.textContent = "Крило без опашка: управлението е с елевоните.";
      } else if (vTail) {
        tcHint.textContent = el.enabled
          ? `Руддерватори ${fmt(el.chord_frac * 100, 0)} % от хордата на ` +
            `всеки панел (височина + посока, смесени в предавателя)` +
            servoText("ruddervator") + "."
          : "Без руддерватори.";
      } else {
        const parts = [];
        parts.push(el.enabled
          ? `Височина ${fmt(el.chord_frac * 100, 0)} %, две половини, едно ` +
            `серво с две тяги` + servoText("elevator")
          : "без кормило за височина");
        parts.push(ru.enabled
          ? `посока ${fmt(ru.chord_frac * 100, 0)} %` + servoText("rudder")
          : "без кормило за посока");
        tcHint.textContent = parts.join("; ") + ".";
      }
    }
    const ail = g.ailerons || {};
    const ailAuto = ail.auto || {};
    setPh("aileronChord", fmt((ailAuto.chord_frac || 0) * 100, 0));
    setPh("aileronStart", fmt((ailAuto.start_frac || 0) * 100, 0));
    setPh("aileronEnd", fmt((ailAuto.end_frac || 0) * 100, 0));
    const ailHint = this.$("aileronHint");
    if (ailHint) {
      ailHint.textContent = ail.enabled
        ? `${ail.kind === "elevon" ? "Елевони" : "Елерони"}: ` +
          `${fmt0(ail.span_mm)} mm по размаха, хорда ` +
          `${fmt0(ail.chord_inboard_mm)}→${fmt0(ail.chord_outboard_mm)} mm, ` +
          `${fmt(ail.area_ratio * 100, 1)} % от площта на крилото ` +
          `(процеп ${fmt(ail.hinge_gap_mm, 1)} mm по пантата).`
        : "Без елерони (хорда 0).";
      const servos = ((res.servos || {}).surfaces || [])
        .find((s) => s.key === "aileron" || s.key === "elevon");
      if (servos) {
        ailHint.textContent += ` Серво: ${servos.servo.label} — нужни ` +
          `${fmt(servos.torque_kgcm, 2)} kg·cm, има ` +
          `${fmt(servos.servo.torque_kgcm, 1)} (запас ×${fmt(servos.margin, 1)}).`;
      }
    }

    const hint = this.$("fusHint");
    if (hint) {
      hint.textContent = `Сега: ${fmt0(fus.length_mm)} × ` +
        `${fmt0(fus.width_mm)} × ${fmt0(fus.height_mm)} mm, ` +
        `обем ${fmt0(fus.volume_cm3)} cm³. Празно поле = авто; ` +
        `нос/кабина/край задават формата.`;
    }
    const propHint = this.$("propulsionHint");
    if (propHint && res.layout) {
      propHint.textContent = res.layout.propulsion_label +
        (res.layout.motor_count > 1
          ? ` (${res.layout.motor_count} мотора)` : "") +
        " — моторът се позиционира автоматично.";
    }
    const tailHint = this.$("tailTypeHint");
    if (tailHint && res.layout) {
      tailHint.textContent = res.layout.tail_type_label +
        (res.layout.tail_type === "v_tail"
          ? `, ъгъл ${fmt(res.layout.v_tail_deg, 0)}°` : "") + ".";
    }
    const planformHint = this.$("tailPlanformHint");
    if (planformHint && res.layout) {
      planformHint.textContent = res.layout.tail_planform_label +
        ", " + (res.layout.tail_tip_style_label || "").toLowerCase() +
        " · площта се запазва при смяна.";
    }
    const airfoilHint = this.$("tailAirfoilHint");
    if (airfoilHint && res.geometry && res.geometry.tail_airfoil) {
      const g = res.geometry;
      const nameOf = (key) => {
        const af = ((this.presets || {}).airfoils || []).find((x) => x.key === key);
        return af ? af.name : key;
      };
      const vTail = (res.layout || {}).tail_type === "v_tail";
      airfoilHint.textContent = vTail
        ? `Профил на V-опашката: ${nameOf(g.tail_airfoil)}.`
        : `Хоризонтална опашка: ${nameOf(g.tail_airfoil)}. Килът е винаги ` +
          `със симетричен профил: ${nameOf(g.fin_airfoil || g.tail_airfoil)}` +
          (g.fin_airfoil && g.fin_airfoil !== g.tail_airfoil
            ? " (най-близката дебелина)." : ".");
    }
    this.syncWingOffset(res);
  },

  /**
   * Отместването на крилото: mm от средното положение.
   *
   * Входът е в mm (реална величина), а плъзгачът — в % от височината на
   * тялото, за да е еднакъв за всички дизайни. Числото в полето винаги е
   * истинската стойност, която отива към ядрото.
   */
  setWingOffset(mm, { silent = false } = {}) {
    const num = this.$("wingOffset");
    if (!num) return;
    const value = Number(mm);
    if (Number.isFinite(value)) num.value = String(Math.round(value));
    else num.value = "";
    this.syncOffsetRange();
    if (!silent) this.updateWingOffsetLabel();
  },

  /** Плъзгачът (в %) следва числото (в mm). */
  syncOffsetRange() {
    const range = this.$("wingOffsetRange");
    const num = this.$("wingOffset");
    if (!range || !num) return;
    const height = this._heightMm || 0;
    const mm = Number(num.value);
    if (!height || !Number.isFinite(mm)) {
      range.value = "0";
      return;
    }
    const pct = Math.max(Number(range.min), Math.min(Number(range.max),
      Math.round((mm / height) * 100)));
    range.value = String(pct);
  },

  /** Живият прочит под полето: „+28 mm = 92 % от височината“. */
  updateWingOffsetLabel() {
    const label = this.$("wingOffsetValue");
    const hint = this.$("wingOffsetHint");
    const num = this.$("wingOffset");
    const height = this._heightMm || 0;
    const mm = num ? Number(num.value) : NaN;
    if (label) {
      label.textContent = Number.isFinite(mm) && height
        ? `${fmt(mm, 0)} mm · ${fmt((mm / height) * 100 + 50, 0)} %`
        : "средно положение";
    }
    if (hint) {
      hint.textContent = height
        ? `Средното положение е 50 % от височината (${fmt(height / 2, 0)} mm). ` +
          "Допустимо: ±" + fmt(height * 0.44, 0) + " mm."
        : "Отместване от средното положение на крилото.";
    }
  },

  /** Синхронизира полетата с резултата (след изчисляване). */
  syncWingOffset(res) {
    const fus = (res && res.geometry && res.geometry.fuselage) || null;
    if (fus && fus.height_mm) this._heightMm = Number(fus.height_mm);
    const lay = (res && res.layout) || null;
    const num = this.$("wingOffset");
    if (lay && num && document.activeElement !== num) {
      if (lay.wing_offset_mm !== null && lay.wing_offset_mm !== undefined) {
        num.value = String(Math.round(lay.wing_offset_mm));
      }
    }
    this.syncOffsetRange();
    this.updateWingOffsetLabel();
    const hint = this.$("wingOffsetHint");
    if (hint && lay && lay.wing_offset_desc) {
      hint.textContent = "Крило: " + lay.wing_offset_desc + "." +
        (lay.wing_offset_clamped
          ? " Стойността е ограничена до ръба на тялото." : "");
    }
  },

  /** Прилага готов комплект материали върху полетата на конструкцията. */
  applyProfile(key) {
    const profiles = {
      budget: { filament: "pla", spar: "aluminium", joiner: "aluminium",
                bed: "220x220x250" },
      standard: { filament: "pla_plus", spar: "carbon", joiner: "carbon",
                  bed: "220x220x250" },
      highend: { filament: "lw_pla", spar: "carbon", joiner: "carbon",
                 bed: "256x256x256" },
    };
    const p = profiles[key];
    if (!p) return;
    this.$("filamentSelect").value = p.filament;
    this.$("sparMaterial").value = p.spar;
    this.$("joinerMaterial").value = p.joiner;
    this.$("bedPreset").value = p.bed;
    this.applyBedPreset(p.bed);
    this.updateFilamentInfo();
  },

  /** Готов размер на леглото → полетата bedX/bedY/bedZ. */
  applyBedPreset(value) {
    if (!value) return;
    const [x, y, z] = value.split("x").map(Number);
    this.$("bedX").value = x;
    this.$("bedY").value = y;
    this.$("bedZ").value = z;
  },

  /**
   * Точка на таба, когато проверка с предупреждение/грешка се отнася до
   * него. Цветът е по най-тежкото ниво; подсказката изброява проверките.
   */
  markTabs(checks) {
    const rank = { warn: 1, error: 2 };
    const byTab = {};
    checks.forEach((c) => {
      if (!rank[c.level]) return;
      const tab = checkTab(c.title);
      if (!tab) return;
      const entry = byTab[tab] || (byTab[tab] = { level: "warn", titles: [] });
      if (rank[c.level] > rank[entry.level]) entry.level = c.level;
      entry.titles.push((c.level === "error" ? "✖ " : "⚠ ") + c.title);
    });
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      const entry = byTab[btn.dataset.tab];
      btn.classList.toggle("has-warn", !!entry && entry.level === "warn");
      btn.classList.toggle("has-error", !!entry && entry.level === "error");
      btn.title = entry ? entry.titles.join("\n") : "";
    });
  },

  /** Кратко описание на спара и джойнера под схемата. */
  renderSparInfo(view, st) {
    const box = this.$("sparInfo");
    if (!box) return;
    box.innerHTML = "";
    if (!view || !st) return;
    const cap = view.cap;
    const carbon = view.carbon;
    const j = view.joiner;
    const rows = [
      ["Печатани капси",
        `${cap.strips === 2 ? "2 ленти × " + fmt(cap.strip_width_mm, 1)
          : fmt(cap.width_mm, 1)} mm × ${fmt(cap.thickness_mm, 1)} mm, ` +
        `горе и долу на ${fmt0(cap.x_mm)} mm от предния ръб`],
      ["Височина на спара", `${fmt(view.spar_height_mm, 1)} mm`],
      ["Лента (спар)", carbon.needed
        ? `${MATERIAL_LABELS[carbon.material] || carbon.material} ` +
          `${fmt(carbon.width_mm, 1)}×${fmt(carbon.thickness_mm, 1)} mm × ` +
          `${carbon.count} — в процепа на капса` +
          (st.carbon_for_stiffness ? " (за коравина)" : "")
        : "не е нужна — печатаните капси стигат"],
    ];
    if (j) {
      rows.push(["Джойнер",
        `${MATERIAL_LABELS[j.material] || j.material} тръба ` +
        `⌀${fmt(j.od_mm, 1)}/${fmt(j.id_mm, 1)} mm × ${fmt0(j.length_mm)} mm` +
        (j.count > 1 ? ` (${j.count} бр.)` : "")]);
      rows.push(["Канал в крилото",
        `⌀${fmt(j.bore_mm, 1)} mm, дълбок ${fmt0(j.depth_mm)} mm, ` +
        `на ${fmt0(j.x_mm)} mm от предния ръб`]);
      rows.push(["Стена до повърхността",
        `${fmt(j.wall_margin_mm, 1)} mm ` + (j.ok ? "✓" : "⚠ твърде тънка")]);
    } else {
      rows.push(["Джойнер", "няма (без съединителна тръба)"]);
    }
    const table = this.el("table", "kv");
    this.fillKv(table, rows);
    box.appendChild(table);
  },

  /**
   * Числата зад графиките: от кривите (v, ld, p_req, p_avail) и aero.
   * Ползват се за маркерите и за прозореца „ⓘ“ с обясненията.
   */
  chartFacts(res) {
    const c = (res && res.curves) || {};
    const a = (res && res.aero) || {};
    const v = c.v || [];
    const ok = (x) => x !== null && x !== undefined && Number.isFinite(x);
    const at = (arr, x) => {
      // линейна интерполация по скоростта
      for (let i = 1; i < v.length; i++) {
        if (v[i] >= x) {
          const y0 = arr[i - 1], y1 = arr[i];
          if (!ok(y0) || !ok(y1)) return null;
          const t = (x - v[i - 1]) / ((v[i] - v[i - 1]) || 1);
          return y0 + t * (y1 - y0);
        }
      }
      return null;
    };
    const facts = {};
    const ld = c.ld || [];
    let best = -1;
    ld.forEach((x, i) => { if (ok(x) && (best < 0 || x > ld[best])) best = i; });
    if (best >= 0) { facts.ldMax = ld[best]; facts.vBestLd = v[best]; }
    if (a.v_best_ld_ms) facts.vBestLd = a.v_best_ld_ms;
    if (a.ld_max) facts.ldMax = a.ld_max;
    const req = c.p_req || [];
    const avail = c.p_avail || [];
    let pMin = -1;
    req.forEach((x, i) => { if (ok(x) && (pMin < 0 || x < req[pMin])) pMin = i; });
    if (pMin >= 0) { facts.pReqMin = req[pMin]; facts.vMinPower = v[pMin]; }
    // V_max: най-високата скорост, при която наличната ≥ нужната
    for (let i = 0; i < v.length; i++) {
      if (ok(avail[i]) && ok(req[i]) && avail[i] >= req[i]) facts.vMax = v[i];
    }
    const vc = a.v_cruise_ms;
    if (vc) {
      facts.ldCruise = at(ld, vc);
      facts.pReqCruise = at(req, vc);
      facts.pAvailCruise = at(avail, vc);
      const massKg = (((res || {}).weights || {}).total_g || 0) / 1000;
      if (ok(facts.pReqCruise) && ok(facts.pAvailCruise) && massKg > 0) {
        facts.pExcess = facts.pAvailCruise - facts.pReqCruise;
        facts.climb = facts.pExcess / (massKg * 9.81);
      }
    }
    return facts;
  },

  /** Съдържанието на прозореца „ⓘ“ за графика (kind = "ld" | "power"). */
  chartInfoHtml(kind, res) {
    const a = (res && res.aero) || {};
    const f = this.chartFacts(res);
    const n = (x, d) => (x === null || x === undefined || !Number.isFinite(x))
      ? "—" : fmt(x, d);
    const kmh = (x) => (x ? " (" + fmt(x * 3.6, 0) + " km/h)" : "");
    if (kind === "ld") {
      return [
        "<h4>Какво показва</h4>",
        "<p><b>Аеродинамичното качество L/D</b> е отношението на подемната",
        "сила към челното съпротивление при всяка скорост на хоризонтален",
        "полет. То показва колко метра планира моделът напред за всеки метър",
        "височина, ако моторът спре.</p>",
        "<h4>Оси</h4><ul>",
        "<li><b>X — скорост V, m/s</b> (1 m/s = 3.6 km/h).</li>",
        "<li><b>Y — L/D</b>, без мерна единица (отношение на две сили).</li></ul>",
        "<h4>Защо кривата има максимум</h4>",
        "<p>При ниска скорост крилото работи с голям ъгъл на атака и",
        "<b>индуктивното</b> съпротивление (вихрите от върховете на крилото) е",
        "голямо. При висока скорост расте <b>паразитното</b> съпротивление",
        "(триене и форма), пропорционално на V². Максимумът е там, където",
        "двете са равни.</p>",
        "<h4>Маркерите за този дизайн</h4><ul>",
        "<li><b>V_stall</b> " + n(a.v_stall_ms, 1) + " m/s" + kmh(a.v_stall_ms) +
          " — скорост на загуба на подемна сила; под нея моделът пада.</li>",
        "<li><b>Макс. L/D</b> " + n(f.ldMax, 1) + " при " + n(f.vBestLd, 1) +
          " m/s" + kmh(f.vBestLd) + " — най-доброто планиране: от 100 m " +
          "височина ~" + n((f.ldMax || 0) * 100, 0) + " m напред.</li>",
        "<li><b>Крейсер</b> " + n(a.v_cruise_ms, 1) + " m/s" + kmh(a.v_cruise_ms) +
          " — L/D " + n(f.ldCruise, 1) + ".</li>",
        "<li>Снижаване при планиране с най-добро L/D: ~" + n(a.sink_rate_ms, 2) +
          " m/s.</li></ul>",
        "<h4>Как да го четеш</h4><ul>",
        "<li>Крейсер близо до максимума = ефективен полет и по-дълго време на батерията.</li>",
        "<li>Крейсер доста вдясно = бърз модел, но харчи повече енергия.</li>",
        "<li>По-голямо разтежение (AR) и по-гладко тяло вдигат кривата нагоре.</li></ul>",
      ].join("\n");
    }
    return [
      "<h4>Какво показва</h4>",
      "<p>Две криви на мощността при хоризонтален полет:</p><ul>",
      "<li><b>Нужна</b> (синя) — мощността, която отива за преодоляване на",
      "съпротивлението: P = D · V.</li>",
      "<li><b>Налична</b> (жълта) — полезната мощност, която моторът и",
      "витлото дават като тяга при тази скорост (след КПД на витлото).</li></ul>",
      "<h4>Оси</h4><ul>",
      "<li><b>X — скорост V, m/s</b> (1 m/s = 3.6 km/h).</li>",
      "<li><b>Y — мощност P, W</b> (ватове).</li></ul>",
      "<h4>Защо нужната мощност е „корито“</h4>",
      "<p>При ниска скорост доминира индуктивното съпротивление (крилото",
      "„виси“ с голям ъгъл на атака), при висока — паразитното, което расте",
      "с V². Дъното на коритото е скоростта за <b>най-дълъг полет</b>.</p>",
      "<h4>Числата за този дизайн</h4><ul>",
      "<li><b>Минимална нужна мощност</b> " + n(f.pReqMin, 1) + " W при " +
        n(f.vMinPower, 1) + " m/s" + kmh(f.vMinPower) +
        " — най-дълго време във въздуха.</li>",
      "<li><b>Крейсер</b> " + n(a.v_cruise_ms, 1) + " m/s: нужни " +
        n(f.pReqCruise, 1) + " W, налични " + n(f.pAvailCruise, 1) + " W.</li>",
      "<li><b>Излишна мощност</b> " + n(f.pExcess, 1) + " W → скорост на " +
        "изкачване ~" + n(f.climb, 1) + " m/s (излишна мощност / тегло).</li>",
      "<li><b>V_max</b> " + n(f.vMax, 1) + " m/s" + kmh(f.vMax) +
        " — там кривите се пресичат; по-бързо в хоризонтален полет моделът не може.</li></ul>",
      "<h4>Как да го четеш</h4><ul>",
      "<li>Голямо разстояние между кривите при крейсер = бързо изкачване и запас.</li>",
      "<li>Ако кривите се допират близо до крейсера, моторът или витлото са слаби.</li>",
      "<li>V_max е основата и за оразмеряване на сервата (проектна скорост ×1.25 при пикиране).</li></ul>",
    ].join("\n");
  },

  /** Списък с APC витла за панела „Витло“. */
  async loadPropellers() {
    const sel = this.$("propSelect");
    if (!sel) return;
    const res = await API.propellerList();
    sel.innerHTML = "";
    if (!res.ok) {
      this.$("propResult").textContent = res.error;
      return;
    }
    res.items.forEach((item) => {
      const opt = this.el("option", null, item.label);
      opt.value = item.name;
      sel.appendChild(opt);
    });
  },

  /** Оценка за печат и проверки на избраното витло. */
  async checkPropeller() {
    const name = this.$("propSelect").value;
    const box = this.$("propResult");
    box.innerHTML = "";
    if (!name) return;
    const bed = [this._num("bedX") || 220, this._num("bedY") || 220,
                 this._num("bedZ") || 250];
    const res = await API.propellerSummary(
      name, this._num("propRpm") || 8000, this.$("propMaterial").value,
      (this._num("propInfill") || 100) / 100, bed);
    if (!res.ok) {
      box.textContent = res.error;
      return;
    }
    const s = res.summary;
    const e = s.estimate;
    const rows = [
      ["Диаметър", `${fmt(s.diameter_in, 1)} in`],
      ["Брой перки", String(s.blades)],
      ["Обем (перки, без хъб)", `${fmt(e.volume_cm3, 1)} cm³`],
      ["Маса за печат", `${fmt0(e.mass_g)} g`],
      ["Материал на печат", `${this.$("propMaterial").value.toUpperCase()}, запълване ${fmt0(e.infill * 100)} %`],
    ];
    if (s.bed) {
      rows.push(["Дължина на едно витло", `${fmt0(s.bed.length_mm)} mm — ` +
        (s.bed.fits ? "се побира на леглото" : "не се побира на леглото")]);
    }
    const table = this.el("table", "kv");
    this.fillKv(table, rows);
    box.appendChild(table);
    const icons = { ok: "✅", warn: "⚠️", error: "❌", info: "ℹ️" };
    this.sortChecks(s.checks).forEach((c) => {
      const row = this.el("div", "check " + c.level);
      row.appendChild(this.el("div", "icon", icons[c.level] || "•"));
      const body = this.el("div");
      body.appendChild(this.el("div", "t", c.title));
      body.appendChild(this.el("div", "d", c.detail));
      row.appendChild(body);
      box.appendChild(row);
    });
  },

  /** Записва STL на избраното витло в exports/propellers/. */
  async exportPropellerStl() {
    const info = this.$("propStlInfo");
    const res = await API.propellerStl(this.$("propSelect").value);
    info.textContent = res.ok
      ? `STL: ${res.path} (${res.triangles} триъгълника)`
      : res.error;
  },

  /** Грешки първо, после предупреждения, информация и „добре“. */
  sortChecks(checks) {
    const rank = { error: 0, warn: 1, info: 2, ok: 3 };
    return checks.slice().sort((a, b) =>
      (rank[a.level] ?? 9) - (rank[b.level] ?? 9));
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
        `❌ ${counts.error} критични проблема — дизайнът не минава проверките`;
    } else if (counts.warn > 0) {
      verdict.className = "verdict warn";
      verdict.textContent = `⚠️ Минава проверките с ${counts.warn} забележки`;
    } else {
      verdict.className = "verdict ok";
      verdict.textContent = "✅ Дизайнът минава всички проверки (не е изпробван в полет)";
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
      `${fmt(pr.time_h, 1)} h · ${fmt(pr.filament_m, 0)} m · ${pr.pieces} части`);

    const checks = this.$("checks");
    checks.innerHTML = "";
    const icons = { ok: "✅", warn: "⚠️", error: "❌", info: "ℹ️" };
    this.sortChecks(res.checks).forEach((c) => {
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
      ["Тип на върха", (() => {
        const el = document.getElementById("tipStyle");
        const opt = el ? el.querySelector(`option[value="${g.tip_style}"]`) : null;
        return opt ? opt.textContent : (g.tip_style || "square");
      })()],
      ["Усукване (washout)", `${fmt(g.washout_deg, 1)}°`],
      ["Профил", `${g.airfoil.name} (CL_max ${fmt(g.airfoil.cl_max, 2)})`],
      ["CL_max при Re",
        `${fmt(a.cl_max, 2)} (каталожно ${fmt(a.cl_max_catalog, 2)})`],
      ["Re в крейсер", fmt0(a.re_cruise)],
      ["L/D max", `${fmt(a.ld_max, 1)} при CL ${fmt(a.cl_at_ld_max, 2)}`],
      ["CD0 / Oswald", `${fmt(a.cd0, 3)} / ${fmt(a.oswald, 2)}` +
        (a.oswald_mission && Math.abs(a.oswald - a.oswald_mission) > 0.004
          ? ` (мисия ${fmt(a.oswald_mission, 2)})` : "")],
      ...(a.cl_tip_ratio
        ? [["Натоварване на върха", `${fmt0(a.cl_tip_ratio * 100)} % от cl`]]
        : []),
      ...(g.winglet && g.winglet.enabled
        ? [["Уинглет", `${fmt0(g.winglet.height_mm)} mm, ` +
            `${fmt(g.winglet.cant_deg, 0)}°, ${fmt(g.winglet.area_dm2, 2)} dm²`]]
        : []),
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
      ...(res.motor_view ? [
        ["Размер на мотора",
          `${res.motor_view.motor} (камбана Ø${fmt(res.motor_view.can_d_mm, 1)}` +
          `×${fmt0(res.motor_view.can_l_mm)} mm, вал Ø${res.motor_view.shaft_d_mm}` +
          ` mm, ~${fmt0(res.motor_view.mass_g)} g, до ` +
          `${fmt0(res.motor_view.p_max_w)} W)`],
        ["Монтаж", `кръст ${res.motor_view.mount_mm.join("/")} mm, 4×M3` +
          (res.motor_view.x_firewall_mm
            ? `, преграда ${fmt0(res.motor_view.x_firewall_mm)} mm от носа` : "")],
        ...(res.motor_view.below_belly_mm > 0 ? [[
          "Витлото под корема",
          `${fmt0(res.motor_view.below_belly_mm)} mm ⚠️ — колесник, ръчно ` +
          "хвърляне или сгъваемо витло"]] : []),
      ] : []),
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
      fmt(part.time_h, 1),
    ]);
    this.fillData(this.$("printTable"),
      ["Част", "Бр.", "Обем cm³", "Маса g", "Филамент m", "Време h"],
      partRows,
      ["Общо", pr.pieces, "", fmt0(pr.total_mass_g),
       fmt(pr.filament_m, 1), fmt(pr.time_h, 1)]);

    const matName = (k) => MATERIAL_LABELS[k] || k;
    const mats = res.material_comparison || [];
    const matRows = mats.map((r) => [
      matName(r.spar), matName(r.joiner), fmt0(r.spar_g), fmt0(r.joiner_g),
      fmt0(r.mass_g), r.ok ? "да" : "не",
    ]);
    this.fillData(this.$("materialTable"),
      ["Спар", "Джойнер", "Спар g", "Джойнер g", "Общо g", "Годен"],
      matRows, null);

    Charts.sparSection(this.$("sparCanvas"), res.structure_view);
    Charts.sparPlan(this.$("sparPlanCanvas"), res.structure_view);
    this.renderSparInfo(res.structure_view, st);
    this.markTabs(res.checks || []);

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
      f.name, fmt0(f.mass_g),
    ]);
    this.fillData(this.$("filamentTable"),
      ["Филамент", "Маса g"], filRows);

    const curves = res.curves || {};
    const facts = this.chartFacts(res);
    const ldPoints = (curves.v || []).map((v, i) => [v, curves.ld[i]]);
    const ldMarkers = [
      { x: a.v_stall_ms, label: "V_stall" },
      { x: a.v_cruise_ms, label: "крейсер", color: Charts.COLORS.line3 },
    ];
    if (facts.vBestLd) {
      ldMarkers.push({ x: facts.vBestLd, label: "макс. L/D", color: "#b48cff" });
    }
    Charts.line(this.$("chartLD"),
      [{ name: "L/D", color: Charts.COLORS.line1, points: ldPoints }],
      {
        markers: ldMarkers,
        xLabel: "Скорост V, m/s",
        yLabel: "Качество L/D (подемна / челна сила)",
      });

    const reqPoints = (curves.v || []).map((v, i) => [v, curves.p_req[i]]);
    const availPoints = (curves.v || []).map((v, i) => [v, curves.p_avail[i]]);
    const pMarkers = [
      { x: a.v_stall_ms, label: "V_stall" },
      { x: a.v_cruise_ms, label: "крейсер", color: Charts.COLORS.line3 },
    ];
    if (facts.vMax) {
      pMarkers.push({ x: facts.vMax, label: "V_max", color: "#ff9a3c" });
    }
    Charts.line(this.$("chartPower"), [
      { name: "нужна", color: Charts.COLORS.line1, points: reqPoints },
      { name: "налична", color: Charts.COLORS.line2, points: availPoints },
    ], {
      markers: pMarkers,
      xLabel: "Скорост V, m/s",
      yLabel: "Мощност P, W",
    });

    this.syncAutoHints(res);
    // контурът винаги да отговаря на избрания профил (и след първо свързване)
    this.updateAirfoilInfo();
  },
};





