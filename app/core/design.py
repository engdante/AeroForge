"""
design.py — оркестратор: от входните данни до пълен дизайн.

compute() е чиста функция (dict -> dict) и се използва както от Eel
backend-а, така и от тестовете.
"""

from . import aero
from . import airfoils
from . import cg
from . import materials
from . import presets
from . import printcost
from . import propulsion
from . import settings as app_settings
from . import structure
from . import weight

VERSION = "0.1.0"


def default_inputs():
    """
    Входни данни по подразбиране.

    Идват от „Настройки“ (settings.json), за да може потребителят да зададе
    своя филамент, дюза, легло и т.н. като база за новите дизайни.
    """
    d = app_settings.get_defaults()
    prt = d["print"]
    prop = d["propulsion"]
    des = d["design"]
    return {
        "name": "Нов дизайн",
        "mission": des["mission"],
        "payload": {
            "mode": "simple",
            "total_g": des["payload_total_g"],
            "components": [],
        },
        "wing": {
            "wing_loading": None,
            "aspect_ratio": None,
            "taper": None,
            "dihedral_deg": None,
            "airfoil": airfoils.DEFAULT_AIRFOIL,
            "wing_le_ratio": 0.30,
        },
        "tail": {
            "type": "conventional",
            "vh": None,
            "vv": None,
            "static_margin": None,
            "tail_arm_ratio": None,
            "airfoil": airfoils.DEFAULT_TAIL_AIRFOIL,
        },
        "propulsion": {
            "cells": prop["cells"],
            "capacity_mah": None,
            "endurance_min": prop["endurance_min"],
            "thrust_to_weight": None,
            "power_to_weight": None,
            "prop_d_in": None,
        },
        "print": {
            "filament": prt["filament"],
            "nozzle": prt["nozzle"],
            "perimeters": prt["perimeters"],
            "infill": prt["infill"],
            "layer_height": prt["layer_height"],
            "bed": list(prt["bed"]),
        },
        "structure": {
            "n_limit": None,
            "safety_factor": 1.5,
        },
    }


def _num(value, default=None):
    """Безопасно число от вход (низ от браузъра, запетая или точка)."""
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _merge(dst, src):
    """Рекурсивно сливане на dict-ове (src върху dst)."""
    for key, value in (src or {}).items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _merge(dst[key], value)
        else:
            dst[key] = value
    return dst


def normalize(inputs):
    """Слива входа с подразбиращите се стойности и привежда типовете."""
    base = default_inputs()
    if inputs is not None and not isinstance(inputs, dict):
        raise ValueError("Входните данни трябва да са dict, получено: %s"
                         % type(inputs).__name__)
    merged = _merge(default_inputs(), inputs or {})

    mission_key = merged.get("mission")
    if mission_key not in presets.MISSIONS:
        mission_key = base["mission"]

    payload = merged.get("payload") or {}
    components = []
    for i, comp in enumerate(payload.get("components") or []):
        if not isinstance(comp, dict):
            continue
        cat = comp.get("category") or "other"
        components.append({
            "id": comp.get("id") or "c%d" % i,
            "name": comp.get("name") or weight.CATEGORIES.get(cat, "Друго"),
            "category": cat if cat in weight.CATEGORIES else "other",
            "qty": max(0.0, _num(comp.get("qty"), 1.0)),
            "unit_mass_g": max(0.0, _num(comp.get("unit_mass_g"), 0.0)),
            "x_mm": _num(comp.get("x_mm"), None),
            "note": comp.get("note", ""),
        })

    bed = merged["print"].get("bed") or list(printcost.DEFAULT_BED)
    try:
        bed = [max(50.0, float(b)) for b in list(bed)[:3]]
    except (TypeError, ValueError):
        bed = list(printcost.DEFAULT_BED)
    while len(bed) < 3:
        bed.append(printcost.DEFAULT_BED[len(bed)])

    wing = merged.get("wing") or {}
    tail = merged.get("tail") or {}
    prop = merged.get("propulsion") or {}
    prt = merged.get("print") or {}
    stc = merged.get("structure") or {}

    return {
        "name": str(merged.get("name") or base["name"])[:60],
        "mission": mission_key,
        "payload": {
            "mode": ("components" if payload.get("mode") == "components"
                     else "simple"),
            "total_g": max(0.0, _num(payload.get("total_g"),
                                     base["payload"]["total_g"])),
            "components": components,
        },
        "wing": {
            "wing_loading": _num(wing.get("wing_loading")),
            "aspect_ratio": _num(wing.get("aspect_ratio")),
            "taper": _num(wing.get("taper")),
            "dihedral_deg": _num(wing.get("dihedral_deg")),
            "airfoil": wing.get("airfoil") or base["wing"]["airfoil"],
            "wing_le_ratio": _num(wing.get("wing_le_ratio"), 0.30),
        },
        "tail": {
            "type": tail.get("type") or "conventional",
            "vh": _num(tail.get("vh")),
            "vv": _num(tail.get("vv")),
            "static_margin": _num(tail.get("static_margin")),
            "tail_arm_ratio": _num(tail.get("tail_arm_ratio")),
            "airfoil": tail.get("airfoil") or base["tail"]["airfoil"],
        },
        "propulsion": {
            "cells": int(presets.clamp(
                _num(prop.get("cells"), 3), 1, 14)),
            "capacity_mah": _num(prop.get("capacity_mah")),
            "endurance_min": _num(prop.get("endurance_min"), 8.0),
            "thrust_to_weight": _num(prop.get("thrust_to_weight")),
            "power_to_weight": _num(prop.get("power_to_weight")),
            "prop_d_in": _num(prop.get("prop_d_in")),
        },
        "print": {
            "filament": prt.get("filament") or materials.DEFAULT_FILAMENT,
            "nozzle": _num(prt.get("nozzle"), 0.4),
            "perimeters": _num(prt.get("perimeters")),
            "infill": _num(prt.get("infill")),
            "layer_height": _num(prt.get("layer_height"), 0.2),
            "bed": bed,
        },
        "structure": {
            "n_limit": _num(stc.get("n_limit")),
            "safety_factor": _num(stc.get("safety_factor"), 1.5),
        },
    }


def resolve(inp):
    """
    Прилага пресета на мисията върху незададените стойности.

    Така UI-ът може да показва „авто“ стойности, преди потребителят да
    ги промени.
    """
    mission = presets.mission(inp["mission"])
    filament = materials.get(inp["print"]["filament"])

    lw = filament["printed_density"] < 0.8 * filament["density"]
    perimeters = inp["print"]["perimeters"]
    if perimeters is None:
        perimeters = 1 if lw else 2
    infill = inp["print"]["infill"]
    if infill is None:
        infill = 0 if perimeters <= 1 else 12

    airfoil_key = inp["wing"]["airfoil"]
    if airfoil_key not in airfoils.AIRFOILS:
        airfoil_key = airfoils.DEFAULT_AIRFOIL

    wing_loading = inp["wing"]["wing_loading"] or mission["wing_loading"]
    return {
        "mission": mission,
        "mission_key": inp["mission"],
        "filament": filament,
        "airfoil": airfoils.get(airfoil_key),
        "airfoil_key": airfoil_key,
        "tail_airfoil": (inp["tail"].get("airfoil")
                         or airfoils.DEFAULT_TAIL_AIRFOIL),
        "wing_loading": presets.clamp(wing_loading, 10.0, 250.0),
        "aspect_ratio": presets.clamp(
            inp["wing"]["aspect_ratio"] or mission["aspect_ratio"], 3.0, 16.0),
        "taper": presets.clamp(
            inp["wing"]["taper"] or mission["taper"], 0.25, 1.0),
        "dihedral_deg": (inp["wing"]["dihedral_deg"]
                         if inp["wing"]["dihedral_deg"] is not None
                         else mission["dihedral_deg"]),
        "wing_le_ratio": presets.clamp(inp["wing"]["wing_le_ratio"], 0.10, 0.60),
        "vh": (inp["tail"]["vh"] if inp["tail"]["vh"] is not None
               else mission["vh"]),
        "vv": (inp["tail"]["vv"] if inp["tail"]["vv"] is not None
               else mission["vv"]),
        "tail_arm_ratio": (inp["tail"]["tail_arm_ratio"]
                           if inp["tail"]["tail_arm_ratio"] is not None
                           else mission["tail_arm_ratio"]),
        "static_margin": (inp["tail"]["static_margin"]
                          if inp["tail"]["static_margin"] is not None
                          else mission["static_margin"]),
        "tail_type": inp["tail"].get("type") or "conventional",
        "cells": inp["propulsion"]["cells"],
        "capacity_mah": inp["propulsion"]["capacity_mah"],
        "endurance_min": inp["propulsion"]["endurance_min"] or 8.0,
        "thrust_to_weight": (inp["propulsion"]["thrust_to_weight"]
                             or mission["thrust_to_weight"]),
        "power_to_weight": (inp["propulsion"]["power_to_weight"]
                            or mission["power_to_weight"]),
        "prop_d_in": inp["propulsion"]["prop_d_in"],
        "nozzle": presets.clamp(inp["print"]["nozzle"] or 0.4, 0.2, 1.2),
        "perimeters": int(presets.clamp(perimeters, 1, 6)),
        "infill": presets.clamp(infill, 0.0, 100.0),
        "layer_height": presets.clamp(
            inp["print"]["layer_height"] or 0.2, 0.08, 0.6),
        "bed": inp["print"]["bed"],
        "n_limit": inp["structure"]["n_limit"],
        "safety_factor": presets.clamp(
            inp["structure"]["safety_factor"] or 1.5, 1.0, 3.0),
        "has_tail": bool(mission.get("has_tail", True)),
    }


# Разпределение на общото тегло, когато потребителят дава само едно число
SIMPLE_SHARES = [
    ("motor", 0.15),
    ("esc", 0.08),
    ("prop", 0.03),
    ("battery", 0.42),
    ("servo", 0.12),
    ("rx", 0.03),
    ("camera", 0.10),
    ("other", 0.07),
]


def _shadow_components(total_g):
    """Виртуални компоненти за ЦТ, когато е зададено само общо тегло."""
    out = []
    for i, (cat, share) in enumerate(SIMPLE_SHARES):
        out.append({
            "id": "s%d" % i,
            "name": weight.CATEGORIES.get(cat, cat),
            "category": cat,
            "qty": 1,
            "unit_mass_g": total_g * share,
            "estimated": True,
            "note": "разпределение на общото тегло",
        })
    return out


def capacity_from_mass(mass_g, cells):
    """Капацитет [mAh], който отговаря на дадена маса на LiPo пакет."""
    if not mass_g or mass_g <= 0:
        return None
    voltage = max(1, int(cells)) * propulsion.LIPO_CELL_V
    energy_wh = mass_g / 1000.0 * presets.BATTERY_SPECIFIC_ENERGY_WH_KG
    return energy_wh / voltage * 1000.0


def compute(inputs):
    """
    Главна функция: входни данни -> пълен дизайн (dict).

    Итерира, докато масата на конструкцията и оборудването се стабилизират
    (масата зависи от размерите, а размерите — от масата).
    """
    inp = normalize(inputs)
    cfg = resolve(inp)
    mission = cfg["mission"]
    mission_key = cfg["mission_key"]
    fil = cfg["filament"]
    mode = inp["payload"]["mode"]

    user_components = [weight.normalize_component(c, 0.0, i)
                       for i, c in enumerate(inp["payload"]["components"])]
    payload_known = weight.components_total_g(user_components)

    if mode == "simple":
        payload_known = inp["payload"]["total_g"]
        provided = set(weight.CATEGORIES.keys())   # нищо не се оценява
        capacity = capacity_from_mass(0.42 * payload_known, cfg["cells"])
    else:
        if payload_known <= 0:
            payload_known = inp["payload"]["total_g"]
        provided = weight.provided_categories(user_components)
        battery_g = sum(c["mass_g"] for c in user_components
                        if c["category"] == "battery")
        capacity = cfg["capacity_mah"] or capacity_from_mass(battery_g,
                                                            cfg["cells"])

    print_cfg = {
        "nozzle": cfg["nozzle"],
        "perimeters": cfg["perimeters"],
        "infill": cfg["infill"],
        "layer_height": cfg["layer_height"],
        "bed": cfg["bed"],
    }

    def evaluate(total_g, wing_loading):
        """Една пълна оценка при фиксирана обща маса и натоварване."""
        area = aero.area_from_wing_loading(total_g, wing_loading)
        geom = aero.wing_geometry(area, cfg["aspect_ratio"], cfg["taper"])
        stall = aero.stall_analysis(total_g / 1000.0, area, geom["mac_m"],
                                    cfg["airfoil"]["cl_max"])
        v_cruise = stall["v_stall_ms"] * mission["cruise_factor"]
        spec = propulsion.size_system(
            total_g / 1000.0, geom, stall["v_stall_ms"], v_cruise, mission,
            cells=cfg["cells"], capacity_mah=capacity,
            endurance_min=cfg["endurance_min"],
            thrust_to_weight=cfg["thrust_to_weight"],
            power_to_weight=cfg["power_to_weight"],
            prop_d_in=cfg["prop_d_in"], cd0=mission["cd0"])
        est = ([] if mode == "simple"
               else propulsion.estimate_component_masses(spec, mission_key,
                                                         provided))
        est_mass = weight.components_total_g(est)
        fus_len_m = aero.fuselage_length(geom["span_m"],
                                         mission["fuselage_ratio"])
        fus = weight.fuselage_dimensions(spec["battery"]["volume_cm3"],
                                         total_g / 1000.0, fus_len_m * 1000.0)
        tail = aero.tail_areas(area, geom["span_m"], geom["mac_m"],
                               fus["length_mm"] / 1000.0,
                               cfg["tail_arm_ratio"], cfg["vh"], cfg["vv"])
        parts = printcost.estimate_airframe(geom, tail, fus, print_cfg, fil)
        airframe = sum(p["mass_g"] for p in parts)
        return {
            "total_g": total_g,
            "wing_loading": wing_loading,
            "geom": geom,
            "stall": stall,
            "v_cruise": v_cruise,
            "spec": spec,
            "est": est,
            "est_mass": est_mass,
            "fus": fus,
            "tail": tail,
            "parts": parts,
            "airframe_g": airframe,
        }

    def residual(mass_g, wing_loading):
        """Колко маса „липсва“ при дадена обща маса (0 = решение)."""
        st = evaluate(mass_g, wing_loading)
        return (payload_known + st["est_mass"] + st["airframe_g"] - mass_g), st

    def solve(wing_loading):
        """
        Намира общата маса чрез бисекция.

        Търсим корена на f(m) = товар + конструкция(m) + оборудване(m) − m.
        Ако конструкцията расте по-бързо от масата (например PLA с много
        периметри), решение НЯМА — връщаме feasible=False.
        """
        lo = max(10.0, 0.25 * payload_known)
        hi = max(200.0, 2.0 * payload_known + 300.0)
        evals = 0

        f_lo, st_lo = residual(lo, wing_loading)
        evals += 1
        if f_lo <= 0:
            return lo, st_lo, True, evals

        f_hi, st_hi = residual(hi, wing_loading)
        evals += 1
        max_hi = max(2000.0, 12.0 * payload_known)
        for _ in range(14):
            if f_hi <= 0 or hi >= max_hi:
                break
            lo, f_lo, st_lo = hi, f_hi, st_hi
            hi = min(max_hi, hi * 1.6)
            f_hi, st_hi = residual(hi, wing_loading)
            evals += 1
        if f_hi > 0:
            return hi, st_hi, False, evals

        for _ in range(48):
            mid = 0.5 * (lo + hi)
            f_mid, st_mid = residual(mid, wing_loading)
            evals += 1
            if abs(f_mid) < 0.2:
                return mid, st_mid, True, evals
            if f_mid > 0:
                lo, f_lo, st_lo = mid, f_mid, st_mid
            else:
                hi, f_hi, st_hi = mid, f_mid, st_mid

        mid = 0.5 * (lo + hi)
        return mid, evaluate(mid, wing_loading), True, evals + 1

    requested_wl = cfg["wing_loading"]
    wl_used = requested_wl
    total_g, state, feasible, iterations = solve(wl_used)

    if not feasible:
        # По-високо натоварване = по-малка площ на единица маса → по-малко
        # конструкция. Опитваме нагоре, докато решението стане възможно.
        for factor in (1.3, 1.7, 2.2, 2.8, 3.6, 4.5):
            wl_try = min(150.0, requested_wl * factor)
            if wl_try <= wl_used:
                continue
            t_try, s_try, ok, ev = solve(wl_try)
            iterations += ev
            if ok:
                wl_used = wl_try
                total_g, state, feasible = t_try, s_try, True
                break
            wl_used = wl_try

    cfg["wing_loading_requested"] = requested_wl
    cfg["wing_loading_used"] = wl_used
    converged = feasible

    return build_result(inp, cfg, state, user_components, mode, iterations,
                        converged, print_cfg, feasible)



def _check(level, title, detail):
    """Един ред в списъка с проверки."""
    return {"level": level, "title": title, "detail": detail}


def build_result(inp, cfg, state, user_components, mode, iterations,
                 converged, print_cfg, feasible=True):
    """Сглобява финалния резултат (dict), който отива към UI и отчета."""
    mission = cfg["mission"]
    fil = cfg["filament"]
    geom = state["geom"]
    spec = state["spec"]
    fus = state["fus"]
    tail = state["tail"]
    stall = state["stall"]
    parts = state["parts"]
    fus_len_mm = fus["length_mm"]

    if mode == "simple":
        base_components = list(inp["payload"]["components"]) + \
            _shadow_components(inp["payload"]["total_g"])
    else:
        base_components = list(inp["payload"]["components"]) + state["est"]
    components = [weight.normalize_component(c, fus_len_mm, i)
                  for i, c in enumerate(base_components)]

    payload_g = weight.components_total_g(components)
    airframe_g = state["airframe_g"]
    total_g = payload_g + airframe_g
    wing_le_mm = cfg["wing_le_ratio"] * fus_len_mm

    cg_res = cg.analyse(components, airframe_g, fus_len_mm, wing_le_mm,
                        geom["mac_mm"], cfg["static_margin"], cfg["has_tail"])

    # Ако батерията не може да балансира, търсим по-добра позиция на крилото
    wing_le_recommended = wing_le_mm
    if (cg_res.get("battery_x_required_mm") is None
            or not cg_res.get("battery_feasible")):
        best = None
        lo_x, hi_x = 0.06 * fus_len_mm, 0.45 * fus_len_mm
        for i in range(15):
            ratio = 0.10 + 0.025 * i
            wl_mm = ratio * fus_len_mm
            trial = cg.analyse(components, airframe_g, fus_len_mm, wl_mm,
                               geom["mac_mm"], cfg["static_margin"],
                               cfg["has_tail"])
            xb = trial.get("battery_x_required_mm")
            if xb is None:
                continue
            if lo_x <= xb <= hi_x:
                score = abs(xb - 0.20 * fus_len_mm)
                if best is None or score < best[0]:
                    best = (score, wl_mm)
        if best is not None:
            wing_le_recommended = best[1]

    st = structure.analyse(
        total_g / 1000.0, geom, fil, mission, cfg["airfoil_key"],
        n_limit=cfg["n_limit"], safety_factor=cfg["safety_factor"],
        perimeters=cfg["perimeters"], nozzle=cfg["nozzle"])

    ld_max, cl_opt = aero.best_ld(geom["aspect_ratio"], mission["oswald"],
                                  mission["cd0"])
    re_cruise = aero.reynolds(state["v_cruise"], geom["mac_m"])
    wing_loading = aero.wing_loading_g_dm2(total_g, geom["area_m2"])
    summary = printcost.summarize(parts)

    curves = aero.speed_sweep(
        total_g / 1000.0, geom["area_m2"], geom["aspect_ratio"],
        mission["oswald"], mission["cd0"],
        0.8 * stall["v_stall_ms"], 2.2 * state["v_cruise"], 18,
        propulsion.ETA_PROP, p_shaft_available=spec["p_max_shaft_w"] * 0.85,
        cl_max=stall["cl_max"])

    total_volume_cm3 = sum(p["volume_cm3"] for p in parts)
    filament_cmp = []
    for fkey in materials.FILAMENTS:
        f = materials.get(fkey)
        f_mass = total_volume_cm3 * f["printed_density"]
        filament_cmp.append({
            "key": fkey,
            "name": f["name"],
            "mass_g": f_mass,
            "cost": f_mass / 1000.0 * f["price_per_kg"],
        })
    filament_cmp.sort(key=lambda x: x["mass_g"])

    checks = build_checks(cfg, geom, stall, spec, cg_res, st, summary,
                          total_g, airframe_g, payload_g, wing_loading,
                          re_cruise, converged, fus, tail, feasible)

    if abs(wing_le_recommended - wing_le_mm) > 5.0:
        checks.insert(0, _check(
            "info", "По-добра позиция на крилото",
            "Постави водещия ръб на крилото на %.0f mm от носа (сега е на "
            "%.0f mm) — така батерията пада на удобно място за баланс."
            % (wing_le_recommended, wing_le_mm)))

    return {
        "ok": True,
        "version": VERSION,
        "inputs": inp,
        "mission": {
            "key": cfg["mission_key"],
            "label": mission["label"],
            "description": mission["description"],
            "has_tail": cfg["has_tail"],
        },
        "filament": {
            "key": fil["key"],
            "name": fil["name"],
            "printed_density": fil["printed_density"],
            "price_per_kg": fil["price_per_kg"],
            "notes": fil["notes"],
        },
        "resolved": {
            "wing_loading": cfg.get("wing_loading_used", cfg["wing_loading"]),
            "wing_loading_requested": cfg.get("wing_loading_requested",
                                              cfg["wing_loading"]),
            "feasible": feasible,
            "aspect_ratio": cfg["aspect_ratio"],
            "taper": cfg["taper"],
            "dihedral_deg": cfg["dihedral_deg"],
            "vh": cfg["vh"],
            "vv": cfg["vv"],
            "tail_arm_ratio": cfg["tail_arm_ratio"],
            "static_margin": cfg["static_margin"],
            "power_to_weight": cfg["power_to_weight"],
            "thrust_to_weight": cfg["thrust_to_weight"],
            "perimeters": cfg["perimeters"],
            "infill": cfg["infill"],
            "nozzle": cfg["nozzle"],
            "layer_height": cfg["layer_height"],
        },
        "weights": {
            "components": components,
            "payload_g": payload_g,
            "airframe_g": airframe_g,
            "total_g": total_g,
            "airframe_pct": (100.0 * airframe_g / total_g
                             if total_g > 0 else 0.0),
            "payload_pct": (100.0 * payload_g / total_g
                            if total_g > 0 else 0.0),
            "breakdown": weight.breakdown(components, airframe_g),
            "filament_comparison": filament_cmp,
            "iterations": iterations,
            "converged": converged,
            "mode": mode,
        },
        "geometry": {
            "area_m2": geom["area_m2"],
            "area_dm2": geom["area_dm2"],
            "span_mm": geom["span_mm"],
            "span_m": geom["span_m"],
            "c_root_mm": geom["c_root_mm"],
            "c_tip_mm": geom["c_tip_mm"],
            "mac_mm": geom["mac_mm"],
            "aspect_ratio": geom["aspect_ratio"],
            "taper": geom["taper"],
            "wing_loading_g_dm2": wing_loading,
            "dihedral_deg": cfg["dihedral_deg"],
            "wing_le_mm": wing_le_mm,
            "wing_le_recommended_mm": wing_le_recommended,
            "fuselage": fus,
            "tail": {
                "type": cfg["tail_type"],
                "s_h_dm2": tail["s_h_dm2"],
                "s_v_dm2": tail["s_v_dm2"],
                "l_h_mm": tail["l_h_mm"],
                "l_v_mm": tail["l_v_mm"],
                "vh": cfg["vh"],
                "vv": cfg["vv"],
                "s_h_ratio_pct": (100.0 * tail["s_h_m2"] / geom["area_m2"]
                                  if geom["area_m2"] > 0 else 0.0),
                "s_v_ratio_pct": (100.0 * tail["s_v_m2"] / geom["area_m2"]
                                  if geom["area_m2"] > 0 else 0.0),
            },
            "airfoil": {
                "key": cfg["airfoil_key"],
                "name": cfg["airfoil"]["name"],
                "kind": cfg["airfoil"]["kind"],
                "cl_max": cfg["airfoil"]["cl_max"],
                "re_range": list(cfg["airfoil"]["re_range"]),
                "use": cfg["airfoil"]["use"],
                "has_coords": cfg["airfoil"]["has_coords"],
                "code": cfg["airfoil"]["code"],
            },
            "tail_airfoil": cfg["tail_airfoil"],
        },
        "aero": {
            "v_stall_ms": stall["v_stall_ms"],
            "v_stall_kmh": stall["v_stall_ms"] * 3.6,
            "v_cruise_ms": state["v_cruise"],
            "v_cruise_kmh": state["v_cruise"] * 3.6,
            "cl_max_catalog": stall["cl_max_catalog"],
            "cl_max": stall["cl_max"],
            "cl_cruise": spec["cruise"]["cl"],
            "cd_cruise": spec["cruise"]["cd"],
            "drag_cruise_n": spec["cruise"]["drag_n"],
            "re_cruise": re_cruise,
            "re_stall": stall["re_stall"],
            "ld_max": ld_max,
            "cl_at_ld_max": cl_opt,
            "cd0": mission["cd0"],
            "oswald": mission["oswald"],
            "lift_slope_per_rad": aero.lift_slope(geom["aspect_ratio"],
                                                  mission["oswald"]),
            "power_required_w": spec["cruise"]["p_elec_w"],
            "glide_ratio": ld_max,
            "sink_rate_ms": (state["v_cruise"] / ld_max
                             if ld_max > 0 else 0.0),
        },
        "propulsion": spec,
        "stability": cg_res,
        "structure": st,
        "print": summary,
        "checks": checks,
        "curves": curves,
    }


def build_checks(cfg, geom, stall, spec, cg_res, st, summary, total_g,
                 airframe_g, payload_g, wing_loading, re_cruise, converged,
                 fus, tail, feasible=True):
    """
    Проверки на дизайна — с обяснение „защо“.

    Нива: ok (всичко е наред), info (полезно), warn (внимавай),
    error (дизайнът няма да лети безопасно).
    """
    mission = cfg["mission"]
    checks = []
    total_kg = total_g / 1000.0

    # 1. Конвергенция на масовия бюджет
    if converged:
        checks.append(_check("ok", "Масовият бюджет е стабилен",
                             "Итерациите се събраха: конструкцията и "
                             "оборудването са в равновесие."))
    else:
        checks.append(_check("warn", "Масовият бюджет не се стабилизира",
                             "Достигнат е лимит на итерациите — стойностите "
                             "са близо до решението, но не точно."))

    # 1б. Възможно ли е изобщо това тегло при този филамент
    wl_req = cfg.get("wing_loading_requested", cfg["wing_loading"])
    wl_use = cfg.get("wing_loading_used", wl_req)
    if not feasible:
        checks.append(_check(
            "error", "Конструкцията не може да носи себе си",
            "При %.0f g/dm² и „%s“ печатната конструкция расте по-бързо от "
            "подемната сила — решение не съществува. Смени на LW-PLA, "
            "намали периметрите или намали натоварването на крилото."
            % (wl_req, cfg["filament"]["name"])))
    elif abs(wl_use - wl_req) > 0.5:
        checks.append(_check(
            "warn", "Натоварването на крилото е променено",
            "При %.0f g/dm² конструкцията не се носи; използвани са "
            "%.0f g/dm² (по-малка площ, по-висока скорост)." % (wl_req, wl_use)))

    # 2. Натоварване на крилото
    lo, hi = mission["wing_loading_range"]
    if lo <= wing_loading <= hi:
        checks.append(_check("ok", "Натоварване на крилото",
                             "%.1f g/dm² — в диапазона %.0f–%.0f g/dm² за "
                             "„%s“." % (wing_loading, lo, hi,
                                        mission["label"])))
    elif wing_loading < lo:
        checks.append(_check("warn", "Много ниско натоварване на крилото",
                             "%.1f g/dm² (под %.0f). Моделът ще е бавен и "
                             "чувствителен на вятър." % (wing_loading, lo)))
    else:
        checks.append(_check("warn", "Високо натоварване на крилото",
                             "%.1f g/dm² (над %.0f). По-висока скорост на "
                             "кацане и по-малко резерв." % (wing_loading, hi)))

    # 3. Скорост на загуба на подемна сила
    v_stall = stall["v_stall_ms"]
    if mission.get("hand_launch") and v_stall > 9.5:
        checks.append(_check("warn", "Трудно хвърляне от ръка",
                             "V_stall = %.1f m/s. За хвърляне от ръка е добре "
                             "под 8–9 m/s — увеличи площта или намали теглото."
                             % v_stall))
    else:
        checks.append(_check("ok", "Скорост на загуба на подемна сила",
                             "V_stall = %.1f m/s (%.0f km/h)."
                             % (v_stall, v_stall * 3.6)))

    # 4. Число на Рейнолдс
    if re_cruise < 60000:
        checks.append(_check("warn", "Много ниско число на Рейнолдс",
                             "Re = %.0f. Под 60 000 профилът губи подемна "
                             "сила — мини на по-дебел профил и по-голям хорд."
                             % re_cruise))
    elif re_cruise < 100000:
        checks.append(_check("warn", "Ниско число на Рейнолдс",
                             "Re = %.0f. CL_max е намален с ~%.0f%%; моделът "
                             "ще лети, но с по-ниско L/D."
                             % (re_cruise,
                                (1 - stall["cl_max"] / stall["cl_max_catalog"])
                                * 100.0)))
    else:
        checks.append(_check("ok", "Число на Рейнолдс",
                             "Re = %.0f — профилът работи в добрия си режим."
                             % re_cruise))

    # 5. Тяга
    tw_t = spec["thrust_to_weight_target"]
    tw_a = spec["thrust_to_weight_actual"]
    if tw_a < 0.9 * tw_t:
        checks.append(_check("warn", "Недостатъчна тяга",
                             "%.2f : 1 при цел %.2f : 1. Увеличи мощността "
                             "или диаметъра на витлото." % (tw_a, tw_t)))
    else:
        checks.append(_check("ok", "Тяга",
                             "%.2f : 1 (цел %.2f : 1) при %d W и витло "
                             "%d инча." % (tw_a, tw_t,
                                           round(spec["p_max_elec_w"]),
                                           spec["prop_d_in"])))

    # 6. Мощност
    p2w_act = spec["p_max_elec_w"] / total_kg if total_kg > 0 else 0.0
    if p2w_act < 0.85 * spec["power_to_weight"]:
        checks.append(_check("warn", "Ниска мощност за типа",
                             "%.0f W/kg при препоръчани %.0f W/kg."
                             % (p2w_act, spec["power_to_weight"])))
    else:
        checks.append(_check("ok", "Мощност",
                             "%.0f W/kg, макс. ток %.1f A (ESC %d A)."
                             % (p2w_act, spec["i_max_a"], spec["esc_a"])))

    # 7. Витло спрямо размаха
    prop_mm = spec["prop_d_in"] * 25.4
    if prop_mm > 0.32 * geom["span_mm"]:
        checks.append(_check("warn", "Голямо витло за размаха",
                             "%d инча (%.0f mm) при размах %.0f mm — провери "
                             "клиренса и реактивния момент."
                             % (spec["prop_d_in"], prop_mm, geom["span_mm"])))
    else:
        checks.append(_check("info", "Витло",
                             "%d×%d инча, ~%.0f об/мин, Kv ≈ %.0f."
                             % (spec["prop_d_in"], spec["prop_pitch_in"],
                                spec["rpm_target"], spec["kv"])))

    # 8. Батерия — ток и време
    c_needed = spec["battery"]["c_rating_needed"]
    if c_needed > 50:
        checks.append(_check("error", "Батерията е претоварена",
                             "Нужни са %.0fC — над 50C е рисковано. Вземи "
                             "по-голям капацитет или по-нисък Kv." % c_needed))
    elif c_needed > 35:
        checks.append(_check("warn", "Висок ток от батерията",
                             "Нужни са %.0fC. Вземи пакет с поне %.0fC."
                             % (c_needed, c_needed + 10)))
    else:
        checks.append(_check("ok", "Батерия — ток",
                             "Нужни са %.0fC; стандартен 30–45C пакет е "
                             "достатъчен." % c_needed))

    end_act = spec["battery"]["endurance_min"]
    end_tgt = spec["battery"]["endurance_target_min"]
    if end_act < 0.8 * end_tgt:
        checks.append(_check("warn", "По-малко време от желаното",
                             "%.0f мин при цел %.0f мин — батерията е "
                             "ограничена от теглото." % (end_act, end_tgt)))
    else:
        checks.append(_check("ok", "Време на полет",
                             "~%.0f мин в крейсер (%d mAh, %dS)."
                             % (end_act,
                                round(spec["battery"]["capacity_mah"]),
                                spec["cells"])))

    # 9. Център на тежестта
    sm = cg_res["static_margin_actual"]
    if sm < 0.02:
        checks.append(_check("error", "Опасен център на тежестта",
                             "ЦТ е на %.1f%% MAC — зад аеродинамичния център. "
                             "Моделът ще е нестабилен; премести маса напред."
                             % cg_res["cg_pct_mac"]))
    elif sm < 0.05:
        checks.append(_check("warn", "Малък статичен запас",
                             "%.0f%% MAC — допустимо за 3D, но не за треньор."
                             % (sm * 100.0)))
    elif sm <= 0.16:
        checks.append(_check("ok", "Статичен запас",
                             "%.0f%% MAC (цел %.0f%%), ЦТ на %.1f%% MAC."
                             % (sm * 100.0,
                                cg_res["static_margin_target"] * 100.0,
                                cg_res["cg_pct_mac"])))
    else:
        checks.append(_check("warn", "Голям статичен запас",
                             "%.0f%% MAC — носът е тежък, моделът ще иска "
                             "много тример." % (sm * 100.0)))

    shift = cg_res["battery_shift_mm"]
    x_bat = cg_res.get("battery_x_required_mm")
    if x_bat is None:
        checks.append(_check("warn", "Няма батерия в списъка",
                             "Добави батерия, за да може ЦТ да се балансира."))
    elif not cg_res["battery_feasible"]:
        if x_bat < 0:
            checks.append(_check(
                "error", "Моделът излиза тежък на опашка",
                "Дори батерия в самото начало на носа не стига за целта — "
                "конструкцията отзад е твърде тежка. Намали масата на "
                "опашката (LW-PLA, по-малко периметри) или премести сервата "
                "напред."))
        else:
            checks.append(_check(
                "error", "Батерията не може да балансира модела",
                "Тя трябва да е на %.0f mm от носа — извън фюзелажа "
                "(дължина %.0f mm). Премести компонентите."
                % (x_bat, fus["length_mm"])))
    elif abs(shift) <= 25:
        checks.append(_check("ok", "Баланс с батерията",
                             "Батерията на ~%.0f mm от носа е на добро място."
                             % x_bat))
    elif abs(shift) <= 60:
        checks.append(_check("warn", "Ще трябва разместване",
                             "Постави батерията на %.0f mm от носа "
                             "(по подразбиране %.0f mm)."
                             % (x_bat, cg_res["battery_x_default_mm"])))
    else:
        checks.append(_check("warn", "Голямо разместване на батерията",
                             "Постави батерията на %.0f mm от носа "
                             "(по подразбиране %.0f mm, отместване %.0f mm)."
                             % (x_bat, cg_res["battery_x_default_mm"],
                                abs(shift))))

    # 10. Маса на конструкцията
    air_pct = 100.0 * airframe_g / total_g if total_g > 0 else 0.0
    if air_pct > 60.0:
        checks.append(_check("error", "Прекалено тежка конструкция",
                             "%.0f%% от масата е печат. Смени на LW-PLA и "
                             "1 периметър." % air_pct))
    elif air_pct > 45.0:
        checks.append(_check("warn", "Тежка конструкция",
                             "%.0f%% от масата е печат (нормално 30–40%%). "
                             "LW-PLA или по-малко периметри ще помогнат."
                             % air_pct))
    else:
        checks.append(_check("ok", "Маса на конструкцията",
                             "%.0f g печат (%.0f%% от общата маса)."
                             % (airframe_g, air_pct)))

    # 11. Якост на спаровете
    if not st["print_ok"]:
        checks.append(_check("warn", "Печатан спар не е достатъчен",
                             "Нужни са %.1f mm² капси, печатани — %.1f mm². "
                             "Добави карбонова лента %.0f×%.1f mm × %d на "
                             "всеки капс."
                             % (st["cap_area_req_mm2"],
                                st["cap_area_print_mm2"],
                                st["carbon"]["width_mm"],
                                st["carbon"]["thickness_mm"],
                                st["carbon"]["count"])))
    else:
        checks.append(_check("ok", "Спарове",
                             "Печатани капси: %.1f mm² при нужни %.1f mm² "
                             "(височина на пояса %.1f mm, M_корен %.1f N·m)."
                             % (st["cap_area_print_mm2"],
                                st["cap_area_req_mm2"],
                                st["spar_height_mm"], st["m_root_nm"])))

    if not st["wall_ok"]:
        checks.append(_check("error", "Прекалено тънка стена",
                             "%.2f mm при минимум %.2f mm за тази дюза."
                             % (st["wall_mm"], st["min_wall_mm"])))
    if not st["deflection_ok"]:
        defl = (st["deflection_carbon_mm"] if st["carbon_required"]
                else st["deflection_print_mm"])
        checks.append(_check("error", "Голяма деформация на крилото",
                             "%.0f mm при лимит %.0f mm. Увеличи височината "
                             "на спаровия пояс или добави карбон."
                             % (defl, st["deflection_limit_mm"])))

    # 12. Печат
    total_h = summary["time_h"]
    if total_h > 40:
        checks.append(_check("warn", "Дълъг печат",
                             "~%.0f часа общо в %d части."
                             % (total_h, summary["pieces"])))
    else:
        checks.append(_check("ok", "Печат",
                             "~%.1f часа, %.0f g филамент, %.0f €, "
                             "%d части."
                             % (total_h, summary["total_mass_g"],
                                summary["cost"], summary["pieces"])))

    if not fus.get("battery_fits", True):
        checks.append(_check("warn", "Батерията не влиза в носа",
                             "Кутията за батерия е %.0f×%.0f×%.0f mm — "
                             "фюзелажът е къс."
                             % (fus["battery_box_mm"][0],
                                fus["battery_box_mm"][1],
                                fus["battery_box_mm"][2])))
    else:
        checks.append(_check("info", "Фюзелаж",
                             "%.0f × %.0f × %.0f mm (Д×Ш×В), място за "
                             "батерия %.0f×%.0f×%.0f mm."
                             % (fus["length_mm"], fus["width_mm"],
                                fus["height_mm"],
                                fus["battery_box_mm"][0],
                                fus["battery_box_mm"][1],
                                fus["battery_box_mm"][2])))

    # 13. Профил: крило без опашка / опашка
    if not cfg["has_tail"] and cfg["airfoil"]["kind"] != "reflexed":
        checks.append(_check("warn", "Профил за крило без опашка",
                             "Избраният профил не е reflexed — за flying "
                             "wing избери MH 45, иначе ще трябва тример."))
    elif cfg["has_tail"] and cfg["airfoil"]["kind"] == "reflexed":
        checks.append(_check("warn", "Reflex профил с опашка",
                             "MH 45 е за крило без опашка; за модел с "
                             "опашка избери NACA 2412 или Clark Y."))

    # 14. Обемни коефициенти на опашката
    if cfg["has_tail"]:
        s_h_ratio = (100.0 * tail["s_h_m2"] / geom["area_m2"]
                     if geom["area_m2"] > 0 else 0.0)
        if 0.35 <= cfg["vh"] <= 0.80:
            checks.append(_check("ok", "Хоризонтална опашка",
                                 "S_h = %.0f cm² (%.0f%% от крилото), "
                                 "V_h = %.2f, рамо %.0f mm."
                                 % (tail["s_h_dm2"] * 100.0, s_h_ratio,
                                    cfg["vh"], tail["l_h_mm"])))
        else:
            checks.append(_check("warn", "Нестандартен V_h",
                                 "V_h = %.2f (нормално 0.35–0.80)."
                                 % cfg["vh"]))
        if 0.015 <= cfg["vv"] <= 0.060:
            checks.append(_check("ok", "Вертикална опашка",
                                 "S_v = %.0f cm², V_v = %.3f е в нормата "
                                 "(0.015–0.060)."
                                 % (tail["s_v_dm2"] * 100.0, cfg["vv"])))
        else:
            checks.append(_check("warn", "Нестандартен V_v",
                                 "V_v = %.3f (нормално 0.015–0.060)."
                                 % cfg["vv"]))
    else:
        checks.append(_check("info", "Крило без опашка",
                             "Elevoni управляват наклон и тангаж; "
                             "статичният запас трябва да е 3–7%% MAC."))

    return checks









