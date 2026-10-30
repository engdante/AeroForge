"""
design.py — оркестратор: от входните данни до пълен дизайн.

compute() е чиста функция (dict -> dict) и се използва както от Eel
backend-а, така и от тестовете.
"""

import math

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

VERSION = "0.2.0"

# Колко от общата маса може да е печатаната конструкция, за да има смисъл
# дизайнът. Над това масовият бюджет математически още има корен, но
# резултатът е безсмислен (напр. 8 kg „треньор“).
MAX_AIRFRAME_SHARE = 0.60
MAX_PAYLOAD_G = 50000.0        # горна граница за вход, за да няма абсурдни модели
MAX_COMPONENT_QTY = 1000.0
MAX_COMPONENT_MASS_G = 50000.0
MAX_MANUAL_X_MM = 20000.0


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
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


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
            "qty": min(MAX_COMPONENT_QTY,
                       max(0.0, _num(comp.get("qty"), 1.0))),
            "unit_mass_g": min(MAX_COMPONENT_MASS_G,
                               max(0.0, _num(comp.get("unit_mass_g"), 0.0))),
            "x_mm": (None if _num(comp.get("x_mm"), None) is None else
                     min(MAX_MANUAL_X_MM,
                         max(0.0, _num(comp.get("x_mm"), 0.0)))),
            "estimated": bool(comp.get("estimated", False)),
            "note": comp.get("note", ""),
        })

    bed = merged["print"].get("bed") or list(printcost.DEFAULT_BED)
    try:
        bed = [presets.clamp(_num(b, 220.0), 50.0, 2000.0)
               for b in list(bed)[:3]]
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
            "total_g": min(MAX_PAYLOAD_G,
                           max(0.0, _num(payload.get("total_g"),
                                         base["payload"]["total_g"]))),
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
            "capacity_mah": (
                None if _num(prop.get("capacity_mah")) is None else
                min(100000.0, max(0.0, _num(prop.get("capacity_mah"))))),
            "endurance_min": min(
                240.0, max(1.0, _num(prop.get("endurance_min"), 8.0))),
            "thrust_to_weight": _num(prop.get("thrust_to_weight")),
            "power_to_weight": _num(prop.get("power_to_weight")),
            "prop_d_in": (None if _num(prop.get("prop_d_in")) is None else
                          presets.clamp(_num(prop.get("prop_d_in")), 5.0, 24.0)),
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
        "cd0_used": aero.cd0_for_airfoil(mission["cd0"],
                                         airfoils.get(airfoil_key)),
        "tail_airfoil": (inp["tail"].get("airfoil")
                         or airfoils.DEFAULT_TAIL_AIRFOIL),
        "wing_loading": presets.clamp(wing_loading, 10.0, 250.0),
        "aspect_ratio": presets.clamp(
            inp["wing"]["aspect_ratio"] or mission["aspect_ratio"], 3.0, 16.0),
        "taper": presets.clamp(
            inp["wing"]["taper"] or mission["taper"], 0.25, 1.0),
        "dihedral_deg": presets.clamp(
            (inp["wing"]["dihedral_deg"]
             if inp["wing"]["dihedral_deg"] is not None
             else mission["dihedral_deg"]), -10.0, 20.0),
        "wing_le_ratio": presets.clamp(inp["wing"]["wing_le_ratio"], 0.10, 0.60),
        "vh": presets.clamp(
            (inp["tail"]["vh"] if inp["tail"]["vh"] is not None
             else mission["vh"]), 0.0, 1.2),
        "vv": presets.clamp(
            (inp["tail"]["vv"] if inp["tail"]["vv"] is not None
             else mission["vv"]), 0.0, 0.15),
        "tail_arm_ratio": presets.clamp(
            (inp["tail"]["tail_arm_ratio"]
             if inp["tail"]["tail_arm_ratio"] is not None
             else mission["tail_arm_ratio"]), 0.20, 0.95),
        "static_margin": presets.clamp(
            (inp["tail"]["static_margin"]
             if inp["tail"]["static_margin"] is not None
             else mission["static_margin"]), 0.0, 0.30),
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
    battery_mass_provided_g = sum(
        c["mass_g"] for c in user_components
        if c.get("category") == "battery")
    if mode == "simple":
        # В simple режим компонентите са скрити/игнорирани; батерията е
        # част от shadow-разпределението (42% от товара).
        battery_mass_provided_g = 0.0

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
            prop_d_in=cfg["prop_d_in"], cd0=cfg["cd0_used"],
            battery_mass_g=(battery_mass_provided_g
                            if battery_mass_provided_g > 0 else None))
        if (mode == "components" and not cfg["capacity_mah"]
                and battery_mass_provided_g > 0):
            spec["battery"]["capacity_source"] = (
                "от масата на батерията")
        est = ([] if mode == "simple"
               else propulsion.estimate_component_masses(spec, mission_key,
                                                         provided))
        if mode == "simple":
            # В simple режим батерията е част от зададения товар (42%),
            # затова капацитетът идва от масата, а времето е следствие.
            spec["battery"]["capacity_source"] = (
                "от масата на батерията (42% от товара)")
        est_mass = weight.components_total_g(est)
        fus_len_m = aero.fuselage_length(geom["span_m"],
                                         mission["fuselage_ratio"])
        fus = weight.fuselage_dimensions(spec["battery"]["volume_cm3"],
                                         total_g / 1000.0, fus_len_m * 1000.0)
        wing_le_m = cfg["wing_le_ratio"] * fus["length_mm"] / 1000.0
        tail = aero.tail_areas(area, geom["span_m"], geom["mac_m"],
                               fus["length_mm"] / 1000.0,
                               cfg["tail_arm_ratio"], cfg["vh"], cfg["vv"],
                               wing_le_m=wing_le_m)
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

        Ако конструкцията расте по-бързо от подемната сила (например PLA с
        много периметри), корен НЯМА: връщаме едноитерационен дизайн
        (m = товар + конструкция(товар)) с feasible=False, вместо безкрайно
        растящо решение.
        """
        lo = max(10.0, payload_known)
        hi = max(200.0, 2.0 * payload_known + 300.0)
        evals = 0

        f_lo, st_lo = residual(lo, wing_loading)
        evals += 1
        if f_lo <= 0:
            return lo, st_lo, True, evals, True

        # Дизайн „с една итерация“ — това е реалистичното число, когато
        # масовият бюджет не се събира.
        one_shot_m = lo + f_lo
        f_hi, st_hi = residual(hi, wing_loading)
        evals += 1
        max_hi = max(3000.0, 8.0 * one_shot_m)
        for _ in range(14):
            if f_hi <= 0 or hi >= max_hi:
                break
            lo, f_lo, st_lo = hi, f_hi, st_hi
            hi = min(max_hi, hi * 1.6)
            f_hi, st_hi = residual(hi, wing_loading)
            evals += 1
        if f_hi > 0:
            # Няма корен: конструкцията расте по-бързо от подемната сила.
            # Връщаме едностъпкова оценка и честно converged=False.
            return (one_shot_m, evaluate(one_shot_m, wing_loading),
                    False, evals, False)

        for _ in range(48):
            mid = 0.5 * (lo + hi)
            f_mid, st_mid = residual(mid, wing_loading)
            evals += 1
            if abs(f_mid) < 0.2:
                if st_mid["airframe_g"] > MAX_AIRFRAME_SHARE * mid:
                    # Корен има, но конструкцията е над допустимия дял.
                    return mid, st_mid, False, evals, True
                return mid, st_mid, True, evals, True
            if f_mid > 0:
                lo, f_lo, st_lo = mid, f_mid, st_mid
            else:
                hi, f_hi, st_hi = mid, f_mid, st_mid

        mid = 0.5 * (lo + hi)
        st = evaluate(mid, wing_loading)
        ok = st["airframe_g"] <= MAX_AIRFRAME_SHARE * mid
        return mid, st, ok, evals + 1, True

    requested_wl = cfg["wing_loading"]
    wl_used = requested_wl
    total_g, state, feasible, iterations, converged = solve(wl_used)

    if not feasible:
        # По-високо натоварване = по-малка площ на единица маса → по-малко
        # конструкция. Опитваме нагоре, но НЕ безкрайно: над 25% от исканото
        # дизайнът вече не е този модел и се връща честно „невъзможно“.
        wl_cap = min(150.0, requested_wl * 1.25)
        for factor in (1.05, 1.12, 1.18, 1.25):
            wl_try = min(wl_cap, requested_wl * factor)
            if wl_try <= wl_used:
                continue
            t_try, s_try, ok, ev, conv = solve(wl_try)
            iterations += ev
            converged = conv
            wl_used = wl_try
            if ok:
                total_g, state, feasible = t_try, s_try, True
                break
            total_g, state = t_try, s_try

    cfg["wing_loading_requested"] = requested_wl
    cfg["wing_loading_used"] = wl_used
    cfg["wing_loading_escalated"] = wl_used > requested_wl + 0.5

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
        # В simple режим списъкът с компоненти е скрит в UI, но може да
        # е останал от предишен режим. Той НЕ бива да се добавя към
        # shadow-разпределението — иначе масата се брои двойно и геометрията
        # (оразмерена само по total_g) престава да отговаря на масата.
        base_components = _shadow_components(inp["payload"]["total_g"])
    else:
        base_components = list(inp["payload"]["components"]) + state["est"]
    components = [weight.normalize_component(c, fus_len_mm, i)
                  for i, c in enumerate(base_components)]

    payload_g = weight.components_total_g(components)
    airframe_g = state["airframe_g"]
    total_g = payload_g + airframe_g
    # Масата, за която реално са оразмерени крилото/опашката. При
    # невъзможен масов бюджет тя се разминава с товар+конструкция; това
    # трябва да се вижда явно, а не да се представя за валиден дизайн.
    geometry_total_g = float(state.get("total_g", total_g))
    budget_gap_g = total_g - geometry_total_g
    budget_closed = abs(budget_gap_g) <= 0.5
    wing_le_mm = cfg["wing_le_ratio"] * fus_len_mm

    cg_res = cg.analyse(components, airframe_g, fus_len_mm, wing_le_mm,
                        geom["mac_mm"], cfg["static_margin"], cfg["has_tail"],
                        cfg["vh"])

    # BOM/отчетът трябва да показват РЕАЛНАТА позиция на батерията, а не
    # само позицията по подразбиране. Оригиналът x_mm се пази (за
    # сравнение/тестове), а x_placed_mm е балансираната стойност.
    placed_battery_x = cg_res.get("battery_x_placed_mm")
    if placed_battery_x is not None:
        for c in components:
            if c.get("category") == "battery":
                c["x_placed_mm"] = placed_battery_x

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
                               cfg["has_tail"], cfg["vh"])
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
                                  cfg["cd0_used"])
    # Скоростта при максимално качество (за реален деградиент/скорост на
    # снижаване), а не крейсерската — иначе сензорът е +20–30% погрешен.
    v_best_ld = aero.speed_for_cl(total_g / 1000.0, geom["area_m2"], cl_opt)
    re_cruise = aero.reynolds(state["v_cruise"], geom["mac_m"])
    wing_loading = aero.wing_loading_g_dm2(total_g, geom["area_m2"])
    summary = printcost.summarize(parts)

    curves = aero.speed_sweep(
        total_g / 1000.0, geom["area_m2"], geom["aspect_ratio"],
        mission["oswald"], cfg["cd0_used"],
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

    if not budget_closed:
        checks.append(_check(
            "error", "Масовият бюджет не се затваря",
            "Геометрията е оразмерена за %.0f g, а товар + конструкция = "
            "%.0f g (разлика %.0f g). Дизайнът е невалиден: числата за "
            "скорости/якост не отговарят на реалната маса."
            % (geometry_total_g, total_g, budget_gap_g)))

    if abs(wing_le_recommended - wing_le_mm) > 5.0:
        checks.insert(0, _check(
            "warn" if not cg_res.get("cg_achievable", True) else "info",
            "По-добра позиция на крилото",
            "Постави водещия ръб на крилото на %.0f mm от носа (сега е на "
            "%.0f mm) — така батерията пада на удобно място за баланс."
            % (wing_le_recommended, wing_le_mm)))

    # ready_to_fly е обобщен флаг: не само ЦТ, а и масовият бюджет,
    # якостта/деформацията и всички error-проверки.
    error_checks = [c for c in checks if c["level"] == "error"]
    cg_res["cg_ready"] = bool(cg_res.get("battery_feasible")
                              and cg_res.get("cg_achievable"))
    cg_res["blocking_checks"] = [c["title"] for c in error_checks]
    cg_res["ready_to_fly"] = bool(feasible and cg_res["cg_ready"]
                                  and not error_checks)

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
            "density": fil["density"],
            "printed_density": fil["printed_density"],
            "tensile_mpa": fil["tensile_mpa"],
            "e_mpa": fil["e_mpa"],
            "layer_factor": fil["layer_factor"],
            "max_flow": fil["max_flow"],
            "price_per_kg": fil["price_per_kg"],
            "notes": fil["notes"],
        },
        "resolved": {
            "wing_loading": cfg.get("wing_loading_used", cfg["wing_loading"]),
            "wing_loading_requested": cfg.get("wing_loading_requested",
                                              cfg["wing_loading"]),
            "wing_loading_escalated": bool(
                cfg.get("wing_loading_escalated", False)),
            "feasible": feasible,
            "budget_closed": budget_closed,
            "cd0": cfg["cd0_used"],
            "cd_min_airfoil": cfg["airfoil"]["cd_min"],
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
            "budget_closed": budget_closed,
            "budget_gap_g": budget_gap_g,
            "geometry_total_g": geometry_total_g,
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
                "l_h_configured_mm": tail.get("l_h_configured_mm",
                                              tail["l_h_mm"]),
                "l_eff_mm": tail.get("l_eff_mm", tail["l_h_mm"]),
                "tail_fit_limited": bool(tail.get("tail_fit_limited", False)),
                "tail_ac_mm": tail.get("tail_ac_mm", 0.0),
                "c_h_mm": tail.get("c_h_mm", 0.0),
                "c_v_mm": tail.get("c_v_mm", 0.0),
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
                "cd_min": cfg["airfoil"]["cd_min"],
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
            "cd0": cfg["cd0_used"],
            "cd0_mission": mission["cd0"],
            "cd_min_airfoil": cfg["airfoil"]["cd_min"],
            "oswald": mission["oswald"],
            "lift_slope_per_rad": aero.lift_slope(geom["aspect_ratio"],
                                                  mission["oswald"]),
            "power_required_w": spec["cruise"]["p_elec_w"],
            "glide_ratio": ld_max,
            "v_best_ld_ms": v_best_ld,
            "sink_rate_ms": (v_best_ld / ld_max if ld_max > 0 else 0.0),
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
    if converged and feasible:
        checks.append(_check("ok", "Масовият бюджет е стабилен",
                             "Итерациите се събраха: конструкцията и "
                             "оборудването са в равновесие."))
    elif converged:
        checks.append(_check("info", "Масовият бюджет има решение",
                             "Равновесието съществува, но дизайнът е "
                             "недопустим по друга проверка (виж грешките)."))
    else:
        checks.append(_check("error", "Няма решение на масовия бюджет",
                             "Конструкцията расте по-бързо от подемната "
                             "сила — решение не съществува. Това НЕ е "
                             "изчерпан лимит на итерациите."))

    # 1б. Възможно ли е изобщо това тегло при този филамент
    wl_req = cfg.get("wing_loading_requested", cfg["wing_loading"])
    wl_use = cfg.get("wing_loading_used", wl_req)
    if not feasible:
        if converged:
            detail = ("При %.0f g/dm² и „%s“ конструкцията заема над 60%% "
                      "от общата маса — масовият бюджет има решение, но "
                      "то е недопустимо. Смени на LW-PLA, намали "
                      "периметрите или намали натоварването на крилото."
                      % (wl_req, cfg["filament"]["name"]))
        else:
            detail = ("При %.0f g/dm² и „%s“ печатната конструкция расте "
                      "по-бързо от подемната сила — решение не съществува "
                      "(пробвано до %.0f g/dm²). Смени на LW-PLA, намали "
                      "периметрите или намали натоварването на крилото."
                      % (wl_req, cfg["filament"]["name"], wl_use))
        checks.append(_check("error",
                             "Конструкцията не може да носи себе си",
                             detail))
    if abs(wl_use - wl_req) > 0.5:
        checks.append(_check(
            "warn", "Натоварването на крилото е променено",
            "При %.0f g/dm² конструкцията не се носи; целеви са %.0f g/dm², "
            "а реалното натоварване е %.1f g/dm²."
            % (wl_req, wl_use, wing_loading)))

    # 2. Натоварване на крилото
    lo, hi = mission["wing_loading_range"]
    if payload_g <= 0:
        checks.append(_check("warn", "Няма зададен товар",
                             "Общото тегло е 0 g — моделът е изчислен само "
                             "от конструкцията. Задай масата на оборудването."))
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

    re_lo, re_hi = cfg["airfoil"].get("re_range", (0.0, 0.0))
    if re_lo and re_cruise < re_lo * 0.8:
        checks.append(_check(
            "warn", "Re под диапазона на профила",
            "Re = %.0f, а %s работи добре от ~%.0f. Избери по-дебел профил "
            "или по-голям хорд."
            % (re_cruise, cfg["airfoil"]["name"], re_lo)))
    elif re_hi and re_cruise > re_hi * 1.2:
        checks.append(_check(
            "warn", "Re над диапазона на профила",
            "Re = %.0f, а %s е предвиден до ~%.0f."
            % (re_cruise, cfg["airfoil"]["name"], re_hi)))

    # 5. Тяга — сравнява се с тягата при ПРЕПОРЪЧАНАТА мощност (иначе
    # проверката е тавтологична: мощността се вдига точно до целта).
    tw_t = spec["thrust_to_weight_target"]
    tw_a = spec["thrust_to_weight_actual"]
    tw_rec = spec.get("thrust_to_weight_at_recommended", tw_a)
    if tw_rec < 0.9 * tw_t:
        checks.append(_check(
            "warn", "Тягата изисква повече мощност от препоръчаната",
            "При препоръчаните %.0f W/kg тягата е %.2f : 1 (цел %.2f : 1); "
            "мощността е вдигната до %.0f W (%.0f W/kg). Провери дали "
            "моторът/ESC издържат, или сложи по-голямо витло (%d\" сега)."
            % (spec["power_to_weight"], tw_rec, tw_t,
               spec["p_max_elec_w"],
               spec["p_max_elec_w"] / total_kg if total_kg > 0 else 0.0,
               spec["prop_d_in"])))
    else:
        checks.append(_check("ok", "Тяга",
                             "%.2f : 1 (цел %.2f : 1) при %d W и витло "
                             "%d инча." % (tw_a, tw_t,
                                           round(spec["p_max_elec_w"]),
                                           spec["prop_d_in"])))

    # 6. Мощност
    p2w_act = spec["p_max_elec_w"] / total_kg if total_kg > 0 else 0.0
    if p2w_act > 1.6 * spec["power_to_weight"]:
        checks.append(_check("warn", "Много висока мощност за типа",
                             "%.0f W/kg при препоръчани %.0f W/kg — тежък "
                             "мотор/батерия и къс полет."
                             % (p2w_act, spec["power_to_weight"])))
    else:
        checks.append(_check("ok", "Мощност",
                             "%.0f W/kg, макс. ток %.1f A (ESC %d A)."
                             % (p2w_act, spec["i_max_a"], spec["esc_a"])))

    # 7. Витло спрямо размаха и мощността
    prop_mm = spec["prop_d_in"] * 25.4
    if prop_mm > 0.32 * geom["span_mm"]:
        checks.append(_check("warn", "Голямо витло за размаха",
                             "%d инча (%.0f mm) при размах %.0f mm — провери "
                             "клиренса и реактивния момент."
                             % (spec["prop_d_in"], prop_mm, geom["span_mm"])))
    if spec.get("rpm_conflict"):
        reasons = []
        if spec.get("rpm_pitch_over_tip"):
            reasons.append("стъпката иска %.0f об/мин, над лимита %.0f"
                           % (spec["rpm_min"], spec["rpm_tip"]))
        if spec.get("rpm_power_over_tip"):
            reasons.append("мощността иска %.0f об/мин, над лимита %.0f"
                           % (spec["rpm_power"], spec["rpm_tip"]))
        if spec.get("rpm_power_below_pitch"):
            reasons.append("при тази мощност витлото достига %.0f об/мин, "
                           "а за крейсерската стъпка са нужни %.0f"
                           % (spec["rpm_power"], spec["rpm_min"]))
        if spec.get("rpm_capped"):
            reasons.append("оборотите са ограничени до %.0f, за да не се "
                           "надхвърли върховата скорост при пълна батерия"
                           % spec["rpm_target"])
        checks.append(_check(
            "warn", "Витлото не е съгласувано с мощността",
            "%d×%d инча: %s. Сложи витло с по-малка стъпка/диаметър или "
            "промени мощността и клетките."
            % (spec["prop_d_in"], spec["prop_pitch_in"],
               "; ".join(reasons) or "оборотите са извън разумния режим")))
    else:
        checks.append(_check("info", "Витло",
                             "%d×%d инча, ~%.0f об/мин (J ≈ %.2f), Kv ≈ %.0f."
                             % (spec["prop_d_in"], spec["prop_pitch_in"],
                                spec["rpm_target"],
                                spec.get("advance_ratio_cruise", 0.0),
                                spec["kv"])))

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

    if spec.get("esc_saturated"):
        checks.append(_check(
            "error", "ESC над стандартния размер",
            "Нужни са %.0f A (1.25×%.1f A), а най-големият стандартен ESC "
            "е %d A. Раздели задвижването, вдигни клетките или намали "
            "мощността."
            % (spec["esc_required_a"], spec["i_max_a"],
               presets.ESC_SIZES_A[-1])))

    end_act = spec["battery"]["endurance_min"]
    end_tgt = spec["battery"]["endurance_target_min"]
    if end_act < 0.8 * end_tgt:
        checks.append(_check("warn", "По-малко време от желаното",
                             "%.0f мин при цел %.0f мин — батерията е "
                             "ограничена от теглото." % (end_act, end_tgt)))
    elif end_act > 1.5 * end_tgt:
        cap_for_target = (spec["battery"]["capacity_mah"] * end_tgt / end_act
                          if end_act > 0 else spec["battery"]["capacity_mah"])
        checks.append(_check(
            "info", "По-голяма батерия от нужното",
            "%.0f мин при цел %.0f мин — за целта стигат ~%.0f mAh "
            "(~%.0f g по-малко тегло)." % (
                end_act, end_tgt, cap_for_target,
                max(0.0, spec["battery"]["mass_g"]
                    - spec["battery"]["energy_wh"] * end_tgt / end_act
                    / presets.BATTERY_SPECIFIC_ENERGY_WH_KG * 1000.0))))
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
                             "ЦТ е на %.1f%% MAC — зад неутралната точка. "
                             "Моделът ще е нестабилен; премести маса напред."
                             % cg_res["cg_pct_mac"]))
    elif sm < 0.05:
        checks.append(_check("warn", "Малък статичен запас",
                             "%.0f%% MAC — допустимо за 3D, но не за треньор."
                             % (sm * 100.0)))
    elif sm <= 0.16:
        checks.append(_check("ok", "Статичен запас",
                             "%.0f%% MAC (цел %.0f%%), ЦТ на %.1f%% MAC "
                             "(неутрална точка %.0f mm)."
                             % (sm * 100.0,
                                cg_res["static_margin_target"] * 100.0,
                                cg_res["cg_pct_mac"],
                                cg_res.get("x_np_mm", 0.0))))
    else:
        checks.append(_check("warn", "Голям статичен запас",
                             "%.0f%% MAC — носът е тежък, моделът ще иска "
                             "много тример." % (sm * 100.0)))

    if cg_res.get("battery_x_required_mm") is not None \
            and not cg_res.get("cg_achievable", True):
        checks.append(_check(
            "error", "Целевият ЦТ не е постижим",
            "Реалният ЦТ е %.0f mm (%.1f%% MAC) — статичният запас е %.0f%% "
            "вместо целевите %.0f%%. Числата в отчета са за РЕАЛНИЯ ЦТ, не "
            "за целевия."
            % (cg_res["x_cg_mm"], cg_res["cg_pct_mac"],
               cg_res["static_margin_actual"] * 100.0,
               cg_res["static_margin_target"] * 100.0)))

    shift = cg_res["battery_shift_mm"]
    x_bat = cg_res.get("battery_x_required_mm")
    x_placed = cg_res.get("battery_x_placed_mm", x_bat)
    if x_bat is None:
        checks.append(_check("warn", "Няма батерия в списъка",
                             "Добави батерия, за да може ЦТ да се балансира."))
    elif not cg_res["battery_feasible"]:
        if x_bat < 0:
            checks.append(_check(
                "error", "Моделът излиза тежък на опашка",
                "Дори батерия в самото начало на носа не стига за целта "
                "(нужни са %.0f mm пред носа). Конструкцията отзад е твърде "
                "тежка — намали масата на опашката (LW-PLA, по-малко "
                "периметри) или премести сервата напред." % abs(x_bat)))
        else:
            checks.append(_check(
                "error", "Батерията не може да балансира модела",
                "Тя трябва да е на %.0f mm от носа — извън фюзелажа "
                "(дължина %.0f mm). Преместена е на %.0f mm; ЦТ е %.1f%% MAC."
                % (x_bat, fus["length_mm"], x_placed,
                   cg_res["cg_pct_mac"])))
    elif abs(shift) <= 25:
        checks.append(_check("ok", "Баланс с батерията",
                             "Батерията на ~%.0f mm от носа е на добро място."
                             % x_placed))
    elif abs(shift) <= 60:
        checks.append(_check("warn", "Ще трябва разместване",
                             "Постави батерията на %.0f mm от носа "
                             "(по подразбиране %.0f mm)."
                             % (x_placed, cg_res["battery_x_default_mm"])))
    else:
        checks.append(_check("warn", "Голямо разместване на батерията",
                             "Постави батерията на %.0f mm от носа "
                             "(по подразбиране %.0f mm, отместване %.0f mm)."
                             % (x_placed, cg_res["battery_x_default_mm"],
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
    elif st.get("carbon_for_stiffness"):
        checks.append(_check(
            "warn", "Нужен е карбон за коравина",
            "Якостта стига (%.1f mm² от %.1f mm²), но само печатаният капс "
            "се огъва %.0f mm при лимит %.0f mm. С включения карбон "
            "%.0f×%.1f mm × %d деформацията е %.1f mm."
            % (st["cap_area_req_mm2"], st["cap_area_print_mm2"],
               st["deflection_print_mm"], st["deflection_limit_mm"],
               st["carbon"]["width_mm"], st["carbon"]["thickness_mm"],
               st["carbon"]["count"], st["deflection_carbon_mm"])))
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
    for problem in printcost.fit_problems(geom, tail, fus, cfg):
        checks.append(_check("error", "Печат: частта не се побира", problem))
    if cfg.get("infill", 0) > 40:
        checks.append(_check(
            "warn", "Висок infill",
            "Моделът за печат е калибриран за тънкостенни крила (0–25% "
            "infill). При %d%% масата/времето може да са подценени."
            % round(cfg["infill"])))
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
            if tail.get("tail_fit_limited"):
                checks.append(_check(
                    "ok", "Хоризонтална опашка",
                    "S_h = %.0f cm² (%.0f%% от крилото), V_h = %.2f, рамо "
                    "%.0f mm (конфиг. %.0f — ограничено от фюзелажа)."
                    % (tail["s_h_dm2"] * 100.0, s_h_ratio, cfg["vh"],
                       tail["l_h_mm"], tail.get("l_h_configured_mm",
                                                tail["l_h_mm"]))))
            else:
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
        if tail.get("tail_fit_limited"):
            checks.append(_check(
                "info", "Опашката е ограничена от фюзелажа",
                "Конфигурираното рамо %.0f mm не се побира; използвано е "
                "%.0f mm. S_h/S_v са увеличени до %.1f/%.1f dm², за да "
                "запазят V_h/V_v. Ако това не е желано, удължи фюзелажа или "
                "намали tail_arm_ratio."
                % (tail.get("l_h_configured_mm", tail["l_h_mm"]),
                   tail["l_h_mm"], tail["s_h_dm2"], tail["s_v_dm2"])))
    else:
        checks.append(_check("info", "Крило без опашка",
                             "Elevoni управляват наклон и тангаж; "
                             "статичният запас трябва да е 3–7%% MAC."))

    return checks









