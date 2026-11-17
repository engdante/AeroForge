"""
design.py — оркестратор: от входните данни до пълен дизайн.

compute() е чиста функция (dict -> dict) и се използва както от Eel
backend-а, така и от тестовете.
"""

import copy
import math

from . import aero
from . import controls
from . import airfoils
from . import cg
from . import fuselage
from . import layout
from . import materials
from . import presets
from . import printcost
from . import profiles
from . import structmat
from . import propulsion
from . import settings as app_settings
from . import structure
from . import weight
from .checks import _check, build_checks

VERSION = "0.7.2"

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
            "tip_style": None,
            "tip_frac": None,
            "washout_deg": None,
            "winglet": {
                "enabled": False,
                "height_mm": None,
                "cant_deg": 85.0,
                "toe_deg": 0.0,
                "chord_mm": None,
            },
            "airfoil": airfoils.DEFAULT_AIRFOIL,
            # елерони: дялове (None = авто по мисията; хорда 0 = без елерони)
            "ailerons": {"chord_frac": None, "start_frac": None,
                         "end_frac": None},
            # None = автоматично (крилото се поставя, за да падне батерията в обхвата)
            "wing_le_ratio": None,
        },
        "tail": {
            "type": "conventional",
            "vh": None,
            "vv": None,
            "static_margin": None,
            "tail_arm_ratio": None,
            "airfoil": airfoils.DEFAULT_TAIL_AIRFOIL,
            "planform": "tapered",
            "tip_style": "square",
            "v_deg": None,
            # кормила: хорда като дял (None = авто по мисията, 0 = без)
            "controls": {"elevator_frac": None, "rudder_frac": None},
        },
        "fuselage": {
            "length_mm": None,
            "length_ratio": None,
            "width_mm": None,
            "height_mm": None,
            "shape": "ellipse",
            "nose_ratio": None,
            "cabin_ratio": None,
            "tail_taper": None,
            "height_ratio": None,
            "tail_boom": "printed",
            "frames": 0,
        },
        "layout": {
            "propulsion": "tractor",
            "wing_position": "high",
            # отместване на крилото от средното положение, mm (+ нагоре);
            # None = ползва се класът wing_position (стари дизайни)
            "wing_offset_mm": None,
            # Разстояние от обшивката на фюзелажа до корените на крило/опашка.
            "wing_root_gap_mm": 10.0,
            "tail_root_gap_mm": 10.0,
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
            "spar_material": "carbon",
            "joiner_material": "carbon",
        },
        "bom": {
            "electronics": "standard",
            "profile": None,
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


def _winglet_config(raw, tip_style=None):
    """
    Уинглет: височина, наклон (cant), ъгъл и хорд.

    Уинглетът съществува САМО при тип връх „уинглет“ — иначе число в полето
    за височина не бива да създава уинглет (типът връх е източникът на
    истина).  Изключен уинглет = нулева височина, за да не се влачи
    „половин“ конфигурация из геометрията и аеродинамиката.
    """
    raw = raw or {}
    if not isinstance(raw, dict):
        raw = {}
    height = _num(raw.get("height_mm"), 0.0) or 0.0
    if tip_style is not None and aero.tip_style_of(tip_style) != "winglet":
        height = 0.0
    if not raw.get("enabled") or height <= 0:
        return {"enabled": False, "height_mm": 0.0, "cant_deg": 85.0,
                "toe_deg": 0.0, "chord_mm": 0.0}
    return {
        "enabled": True,
        "height_mm": presets.clamp(height, 5.0, 400.0),
        "cant_deg": presets.clamp(_num(raw.get("cant_deg"), 85.0), 45.0, 90.0),
        "toe_deg": presets.clamp(_num(raw.get("toe_deg"), 0.0), -5.0, 5.0),
        "chord_mm": max(0.0, _num(raw.get("chord_mm"), 0.0) or 0.0),
    }


def wing_aero(cfg, geom, mission):
    """
    Аеродинамика на планформата за конкретната геометрия.

    Мисийният `oswald` е калибриран за номиналната планформа (прав връх,
    мисийно свиване), затова геометрията дава ДОБАВКА спрямо него:

        e = e_мисия + (e_геометрия − e_номинал)

    Така съществуващите дизайни не се променят, а заоблен връх, уинглет,
    усукване или по-добро свиване реално вдигат качеството.  Връща
    (данни от анализа, използван Oswald).
    """
    winglet = cfg.get("winglet")
    design = aero.span_analysis(geom, cfg["washout_deg"], cfg["dihedral_deg"],
                                0.0, winglet)
    nominal_geom = aero.wing_geometry(geom["area_m2"],
                                      mission["aspect_ratio"],
                                      mission["taper"],
                                      mission.get("tip_style", "square"))
    nominal = aero.span_analysis(nominal_geom,
                                 mission.get("washout_deg", 0.0),
                                 mission["dihedral_deg"], 0.0, None)
    e_used = presets.clamp(mission["oswald"] + (design["e"] - nominal["e"]),
                           0.45, 1.25)
    return design, e_used, nominal["e"]


SPAR_MATERIALS = ("carbon", "aluminium", "wood")
JOINER_MATERIALS = ("carbon", "aluminium", "fibreglass", "steel")


def _choice(value, default, options):
    """Стойността, ако е от допустимите; иначе подразбиращата се."""
    return value if value in options else default


def structure_option(st, geom, spar, joiner, span_mm=None):
    """
    Маса и цена на конструктивните елементи за даден избор спар/джойнер.

    Спарът е армировката на целия размах (ленти по капсите); джойнерите са
    два профила с дължина 1.1 × хорда. Масата се добавя към рамата в
    evaluate (чрез _structure_extra_g) и се показва в BOM и в сравнението.
    """
    span = float(span_mm if span_mm is not None else geom["span_mm"])
    spar_mat = structmat.get(spar)
    joiner_mat = structmat.get(joiner)

    spar_g = 0.0
    if st["carbon_required"]:
        area = st["carbon"]["total_area_mm2"]
        spar_g = area * span * spar_mat["density"] / 1000.0

    tube = st["joiner_tube"]
    joiner_ok = bool(tube.get("od_mm"))
    joiner_g = 0.0
    if joiner_ok:
        per_m = structmat.tube_mass_g_per_m(tube["od_mm"], tube["id_mm"],
                                            joiner_mat["density"])
        joiner_g = per_m * (tube["length_mm"] / 1000.0) * tube["count"]

    cost = (spar_g / 1000.0 * spar_mat["price_eur_kg"]
            + joiner_g / 1000.0 * joiner_mat["price_eur_kg"])
    ok = (joiner_ok and st["adhesive_ok"] and st["deflection_ok"]
          and st.get("compression_ok", True)
          and (st["print_ok"] or st["carbon_required"]))
    return {
        "spar": spar,
        "joiner": joiner,
        "ok": bool(ok),
        "spar_g": spar_g,
        "joiner_g": joiner_g,
        "mass_g": spar_g + joiner_g,
        "cost_eur": cost,
        "adhesive_ok": st["adhesive_ok"],
        "deflection_ok": st["deflection_ok"],
        "joiner_ok": joiner_ok,
    }


def _structure_extra_g(total_g, geom, fil, mission, cfg, spar_mat, joiner_mat):
    """
    Допълнителната маса на конструкцията (g) при дадена обща маса:
    удебеляването на печатания капс + армировката (спар) + джойнерите.
    """
    st = structure.analyse(
        total_g / 1000.0, geom, fil, mission, cfg["airfoil_key"],
        n_limit=cfg["n_limit"], safety_factor=cfg["safety_factor"],
        perimeters=cfg["perimeters"], nozzle=cfg["nozzle"],
        spar_material=spar_mat, joiner_material=joiner_mat)
    row = structure_option(st, geom, spar_mat, joiner_mat)
    return st["cap_extra_g"] + row["mass_g"]


def material_comparison(mass_kg, geom, fil, mission, cfg):
    """Таблица: всяка комбинация спар × джойнер (3 × 4 = 12 реда)."""
    rows = []
    for spar in SPAR_MATERIALS:
        for joiner in JOINER_MATERIALS:
            st = structure.analyse(
                mass_kg, geom, fil, mission, cfg["airfoil_key"],
                n_limit=cfg["n_limit"], safety_factor=cfg["safety_factor"],
                perimeters=cfg["perimeters"], nozzle=cfg["nozzle"],
                spar_material=spar, joiner_material=joiner)
            rows.append(structure_option(st, geom, spar, joiner))
    return rows


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
    bomc = merged.get("bom") or {}
    fus = merged.get("fuselage") or {}
    lay = merged.get("layout") or {}
    # Обратна съвместимост: стари дизайни с един общ root_gap_mm
    # се прилагат за и крилото и опашката.
    _legacy_gap = _num(lay.get("root_gap_mm"), None)
    _wing_gap = (_legacy_gap if _legacy_gap is not None
                 else _num(lay.get("wing_root_gap_mm"), 10.0))
    _tail_gap = (_legacy_gap if _legacy_gap is not None
                 else _num(lay.get("tail_root_gap_mm"), 10.0))

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
            "tip_style": (str(wing.get("tip_style")).lower()
                          if str(wing.get("tip_style") or "").lower()
                          in aero.TIP_STYLES else None),
            "tip_frac": _num(wing.get("tip_frac")),
            "washout_deg": _num(wing.get("washout_deg")),
            "winglet": _winglet_config(wing.get("winglet"),
                                       wing.get("tip_style")),
            "airfoil": wing.get("airfoil") or base["wing"]["airfoil"],
            "ailerons": controls.normalize_input(wing.get("ailerons")),
            "wing_le_ratio": _num(wing.get("wing_le_ratio"), None),
        },
        "tail": {
            "type": tail.get("type") or "conventional",
            "vh": _num(tail.get("vh")),
            "vv": _num(tail.get("vv")),
            "static_margin": _num(tail.get("static_margin")),
            "tail_arm_ratio": _num(tail.get("tail_arm_ratio")),
            "airfoil": tail.get("airfoil") or base["tail"]["airfoil"],
            "v_deg": _num(tail.get("v_deg")),
            "controls": controls.normalize_tail_input(tail.get("controls")),
        },
        "fuselage": {
            "length_mm": _num(fus.get("length_mm")),
            "length_ratio": _num(fus.get("length_ratio")),
            "width_mm": _num(fus.get("width_mm")),
            "height_mm": _num(fus.get("height_mm")),
            "shape": (str(fus.get("shape") or "ellipse").lower()
                      if str(fus.get("shape") or "ellipse").lower()
                      in fuselage.SHAPES else "ellipse"),
            "nose_ratio": _num(fus.get("nose_ratio")),
            "cabin_ratio": _num(fus.get("cabin_ratio")),
            "tail_taper": _num(fus.get("tail_taper")),
            "height_ratio": _num(fus.get("height_ratio")),
            "tail_boom": (str(fus.get("tail_boom") or "printed").lower()
                          if str(fus.get("tail_boom") or "printed").lower()
                          in fuselage.TAIL_BOOMS else "printed"),
            "frames": min(12.0, max(0.0, _num(fus.get("frames"), 0.0))),
        },
        "layout": {
            "propulsion": (str(lay.get("propulsion") or "tractor").lower()
                           if str(lay.get("propulsion") or "tractor").lower()
                           in layout.PROPULSION_LAYOUTS else "tractor"),
            "wing_position": (
                str(lay.get("wing_position") or "high").lower()
                if str(lay.get("wing_position") or "high").lower()
                in layout.WING_POSITIONS else "high"),
            # отместване на крилото от средното положение, mm (+ нагоре);
            # None = ползва се класът wing_position (стари дизайни)
            "wing_offset_mm": _num(lay.get("wing_offset_mm")),
            "wing_root_gap_mm": max(0.0, min(40.0, _wing_gap)),
            "tail_root_gap_mm": max(0.0, min(40.0, _tail_gap)),
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
            "spar_material": _choice(stc.get("spar_material"), "carbon",
                                     SPAR_MATERIALS),
            "joiner_material": _choice(stc.get("joiner_material"), "carbon",
                                       JOINER_MATERIALS),
        },
        "bom": {
            "electronics": _choice(bomc.get("electronics"), "standard",
                                   tuple(profiles.ELECTRONICS_EUR)),
            "profile": bomc.get("profile") or None,
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
    # Типът връх е източник на истина и за уинглета (виж _winglet_config).
    tip_style = aero.tip_style_of(inp["wing"].get("tip_style")
                                  or mission.get("tip_style"))
    return {
        "mission": mission,
        "mission_key": inp["mission"],
        "filament": filament,
        "airfoil": airfoils.get(airfoil_key),
        "airfoil_key": airfoil_key,
        "cd0_airfoil": aero.cd0_for_airfoil(mission["cd0"],
                                            airfoils.get(airfoil_key)),
        "cd0_used": aero.cd0_for_airfoil(mission["cd0"],
                                         airfoils.get(airfoil_key)),
        "cd0_winglet": 0.0,
        # Oswald се калибрира по планформата в compute(); тук е базата по
        # мисия, за да е валиден и при директно извикване на evaluate().
        "oswald": mission["oswald"],
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
        "tip_style": tip_style,
        "tip_frac": presets.clamp(
            (inp["wing"].get("tip_frac")
             if inp["wing"].get("tip_frac") is not None
             else aero.default_tip_frac(tip_style)),
            0.0, 0.35),
        "washout_deg": presets.clamp(
            (inp["wing"].get("washout_deg")
             if inp["wing"].get("washout_deg") is not None
             else mission.get("washout_deg", presets.DEFAULT_WASHOUT_DEG)),
            0.0, 4.0),
        "winglet": _winglet_config(inp["wing"].get("winglet"), tip_style),
        "ailerons": controls.resolve(
            inp["wing"].get("ailerons"), mission, tip_style,
            (inp["wing"].get("tip_frac")
             if inp["wing"].get("tip_frac") is not None
             else aero.default_tip_frac(tip_style))),
        "wing_le_auto": inp["wing"]["wing_le_ratio"] is None,
        "wing_le_ratio": presets.clamp(
            0.30 if inp["wing"]["wing_le_ratio"] is None
            else inp["wing"]["wing_le_ratio"], 0.10, 0.60),
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
        "tail_type": (inp["tail"].get("type")
                      if inp["tail"].get("type") in layout.TAIL_TYPES
                      else "conventional"),
        "tail_controls_input": inp["tail"].get("controls"),
        "tail_planform": (inp["tail"].get("planform")
                          if inp["tail"].get("planform") in aero.TAIL_PLANFORMS
                          else "tapered"),
        "tail_tip_style": (inp["tail"].get("tip_style")
                           if inp["tail"].get("tip_style")
                           in aero.TAIL_TIP_STYLES else "square"),
        "v_tail_deg": presets.clamp(
            inp["tail"].get("v_deg") if inp["tail"].get("v_deg") is not None
            else 35.0, 15.0, 55.0),
        "fuselage": inp["fuselage"],
        "layout": inp["layout"],
        "propulsion_layout": inp["layout"]["propulsion"],
        "wing_position": inp["layout"]["wing_position"],
        "wing_offset_mm": inp["layout"].get("wing_offset_mm"),
        "wing_root_gap_mm": inp["layout"]["wing_root_gap_mm"],
        "tail_root_gap_mm": inp["layout"]["tail_root_gap_mm"],
        "motor_count": layout.motor_count(inp["layout"]["propulsion"]),
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


def _wing_offset_desc(place):
    """Текст за UI/отчета: „+28 mm (92 % от височината на тялото)“."""
    offset = float(place.get("offset_mm") or 0.0)
    percent = float(place.get("percent") or 50.0)
    if abs(offset) < 0.05:
        return "средно положение (50 % от височината)"
    return "%+.0f mm от средното (%.0f %% от височината)" % (offset, percent)


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


def compute_core(inputs):
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
        # Капацитетът идва от желаното време (U4), освен ако е зададен ръчно.
        capacity = cfg["capacity_mah"] or None
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
        geom = aero.wing_geometry(area, cfg["aspect_ratio"], cfg["taper"],
                                  cfg["tip_style"], cfg["tip_frac"])
        # Минималният хорд на върха зависи от стената за печат, а тя — от
        # дюзата и периметрите.  Затова планформата се преизчислява веднъж
        # с реалния минимум (иначе закръглянето стига до невалидна черупка).
        wall = printcost.wall_thickness(cfg["perimeters"], cfg["nozzle"])
        tip_min = aero.tip_min_ratio(wall, geom["c_root_mm"])
        if abs(tip_min - geom["tip_min_ratio"]) > 1e-4:
            geom = aero.wing_geometry(area, cfg["aspect_ratio"], cfg["taper"],
                                      cfg["tip_style"], cfg["tip_frac"], tip_min)
        geom["winglet_area_m2"] = 0.0
        if cfg["winglet"]["enabled"]:
            wl = aero.winglet_effect(cfg["winglet"]["height_mm"],
                                     cfg["winglet"]["chord_mm"],
                                     cfg["winglet"]["cant_deg"],
                                     0.5, geom["span_mm"],
                                     geom["c_root_mm"] * geom["taper"])
            geom["winglet_area_m2"] = wl["area_total_m2"]
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
                            if battery_mass_provided_g > 0 else None),
            motor_count=cfg["motor_count"], oswald=cfg["oswald"])
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
        # Тялото: размерите и формата идват от fuselage.py (авто или ръчно).
        fus = fuselage.resolve(geom["span_mm"], total_g / 1000.0,
                               spec["battery"]["volume_cm3"],
                               cfg["fuselage"], mission["fuselage_ratio"])
        wing_le_m = cfg["wing_le_ratio"] * fus["length_mm"] / 1000.0
        tail = aero.tail_areas(area, geom["span_m"], geom["mac_m"],
                               fus["length_mm"] / 1000.0,
                               cfg["tail_arm_ratio"], cfg["vh"], cfg["vv"],
                               wing_le_m=wing_le_m,
                               taper_h=aero.TAIL_PLANFORMS[
                                   cfg["tail_planform"]]["taper_h"],
                               taper_v=aero.TAIL_PLANFORMS[
                                   cfg["tail_planform"]]["taper_v"])
        parts = printcost.estimate_airframe(geom, tail, fus, print_cfg, fil)
        # Армировката, джойнерите и удебеляването на капса са част от рамата
        airframe = (sum(p["mass_g"] for p in parts)
                    + _structure_extra_g(
                        total_g, geom, fil, mission, cfg,
                        inp["structure"]["spar_material"],
                        inp["structure"]["joiner_material"]))
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

    # Аеродинамика на планформата: Oswald по геометрията спрямо номиналната
    # за мисията.  Ако геометрията се различава, масовият бюджет се решава
    # отново с новия Oswald — иначе мощността и отчетът биха си противоречили.
    wing, e_used, e_nominal = wing_aero(cfg, state["geom"], mission)
    cd0_winglet = aero.winglet_cd0_delta(wing.get("winglet") or {},
                                         state["geom"]["area_m2"],
                                         cfg["airfoil"]["cd_min"])
    changed = (abs(e_used - cfg["oswald"]) > 0.005
               or abs(cd0_winglet - cfg["cd0_winglet"]) > 1e-6)
    cfg["oswald"] = e_used
    cfg["cd0_winglet"] = cd0_winglet
    cfg["cd0_used"] = cfg["cd0_airfoil"] + cd0_winglet
    if changed:
        total_g, state, feasible, evals, converged = solve(wl_used)
        iterations += evals
        wing, e_used, e_nominal = wing_aero(cfg, state["geom"], mission)
        cd0_winglet = aero.winglet_cd0_delta(wing.get("winglet") or {},
                                             state["geom"]["area_m2"],
                                             cfg["airfoil"]["cd_min"])
        cfg["cd0_winglet"] = cd0_winglet
        cfg["cd0_used"] = cfg["cd0_airfoil"] + cd0_winglet
    cfg["oswald"] = e_used
    cfg["oswald_nominal"] = e_nominal
    cfg["wing_aero"] = wing

    result = build_result(inp, cfg, state, user_components, mode, iterations,
                          converged, print_cfg, feasible)

    # Автоматично крило: ако търсенето намира по-добра позиция (батерията
    # пада в обхвата), прилагаме я и преизчисляваме веднъж с фиксирана стойност.
    if cfg.get("wing_le_auto") and result.get("ok"):
        geo = result["geometry"]
        rec_mm = geo.get("wing_le_recommended_mm")
        fus_mm = geo["fuselage"]["length_mm"]
        if rec_mm and abs(rec_mm - geo["wing_le_mm"]) > 5.0:
            fixed = copy.deepcopy(inputs)
            fixed.setdefault("wing", {})["wing_le_ratio"] = rec_mm / fus_mm
            result = _compute_fixed(fixed)
    return result


def compute(inputs):
    """Публичният вход: пълен дизайн с автоматично крило, когато е зададено „авто“."""
    return compute_core(inputs)


def _compute_fixed(inputs):
    """compute_core с фиксирано крило (без втори автоматичен проход)."""
    return compute_core(inputs)







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
    # Къде е крилото: отместване в mm от средното положение има приоритет
    # пред класа високо/средно/ниско (последният остава за старите дизайни).
    wing_place = layout.wing_placement(cfg.get("wing_offset_mm"),
                                       cfg.get("wing_position", "high"),
                                       float(fus.get("height_mm") or 0.0))
    cfg["wing_position"] = wing_place["class"]
    # Реалният коренов момент спрямо елиптичния (от разпределението на
    # подемната сила) — уинглетът и силното свиване го увеличават.
    geom["bending_factor"] = cfg.get("wing_aero", {}).get("m_root_factor", 1.0)

    if mode == "simple":
        # В simple режим списъкът с компоненти е скрит в UI, но може да
        # е останал от предишен режим. Той НЕ бива да се добавя към
        # shadow-разпределението — иначе масата се брои двойно и геометрията
        # (оразмерена само по total_g) престава да отговаря на масата.
        base_components = _shadow_components(inp["payload"]["total_g"])
    else:
        base_components = list(inp["payload"]["components"]) + state["est"]
    wing_le_mm = cfg["wing_le_ratio"] * fus_len_mm
    # Позициите на компонентите зависят от разположението на двигателите
    # (тягач / бутач / два мотора) — идват от layout.py.
    positions = layout.positions(cfg["propulsion_layout"], fus_len_mm,
                                 wing_le_mm, geom["mac_mm"])
    components = [weight.normalize_component(c, fus_len_mm, i, positions)
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

    bay = fus.get("battery_bay_mm") or (None, None)
    cg_res = cg.analyse(components, airframe_g, fus_len_mm, wing_le_mm,
                        geom["mac_mm"], cfg["static_margin"], cfg["has_tail"],
                        cfg["vh"], battery_lo_mm=bay[0], battery_hi_mm=bay[1],
                        tail_boom=fus.get("tail_boom", "printed"))

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
        # Търсим позиция на крилото, при която батерията попада в реалния
        # обхват по сечение (bay), а не в произволно 6–45% от дължината.
        lo_x, hi_x = 0.06 * fus_len_mm, 0.45 * fus_len_mm
        if bay[0] is not None and bay[1] is not None:
            lo_x, hi_x = bay[0], bay[1]
        for i in range(15):
            ratio = 0.10 + 0.025 * i
            wl_mm = ratio * fus_len_mm
            trial = cg.analyse(components, airframe_g, fus_len_mm, wl_mm,
                               geom["mac_mm"], cfg["static_margin"],
                               cfg["has_tail"], cfg["vh"],
                               battery_lo_mm=bay[0], battery_hi_mm=bay[1],
                               tail_boom=fus.get("tail_boom", "printed"))
            xb = trial.get("battery_x_required_mm")
            if xb is None or not trial.get("cg_achievable"):
                continue
            if lo_x <= xb <= hi_x:
                score = abs(xb - 0.20 * fus_len_mm)
                if best is None or score < best[0]:
                    best = (score, wl_mm)
        if best is not None:
            wing_le_recommended = best[1]

    spar_mat = inp["structure"]["spar_material"]
    joiner_mat = inp["structure"]["joiner_material"]
    st = structure.analyse(
        total_g / 1000.0, geom, fil, mission, cfg["airfoil_key"],
        n_limit=cfg["n_limit"], safety_factor=cfg["safety_factor"],
        perimeters=cfg["perimeters"], nozzle=cfg["nozzle"],
        spar_material=spar_mat, joiner_material=joiner_mat)
    struct_row = structure_option(st, geom, spar_mat, joiner_mat)
    comparison = material_comparison(total_g / 1000.0, geom, fil, mission,
                                     cfg)

    # V-опашка: панелът, който дава същите хоризонтална и вертикална
    # проекция като изчислените S_h и S_v.
    v_tail = None
    if cfg["has_tail"] and cfg["tail_type"] == "v_tail":
        v_tail = layout.v_tail_panel(tail["s_h_m2"], tail["s_v_m2"],
                                     cfg["v_tail_deg"])

    # Размах на опашните повърхности (нужен за 3D и за 2D изгледа)
    tail_b_h_mm = (2.0 * tail["s_h_m2"] * 1e6
                   / (tail["c_h_mm"] * (1.0 + aero.TAIL_TAPER_H))
                   if tail.get("c_h_mm") else 0.0)
    tail_b_v_mm = (2.0 * tail["s_v_m2"] * 1e6
                   / (tail["c_v_mm"] * (1.0 + aero.TAIL_TAPER_V))
                   if tail.get("c_v_mm") else 0.0)

    ld_max, cl_opt = aero.best_ld(geom["aspect_ratio"], cfg["oswald"],
                                  cfg["cd0_used"])
    # Скоростта при максимално качество (за реален деградиент/скорост на
    # снижаване), а не крейсерската — иначе сензорът е +20–30% погрешен.
    v_best_ld = aero.speed_for_cl(total_g / 1000.0, geom["area_m2"], cl_opt)
    re_cruise = aero.reynolds(state["v_cruise"], geom["mac_m"])
    wing_loading = aero.wing_loading_g_dm2(total_g, geom["area_m2"])
    summary = printcost.summarize(parts)

    # BOM: печат + конструкция (спар/джойнер) + електроника (EUR, ориентировъчно)
    elec_class = inp["bom"]["electronics"]
    battery_ah = float(spec["battery"]["capacity_mah"]) / 1000.0
    elec_lines = profiles.electronics_cost(
        elec_class, cfg["motor_count"], cfg["motor_count"],
        4 if cfg["has_tail"] else 2, battery_ah, cfg["has_tail"])
    elec_eur = sum(x["total_eur"] for x in elec_lines)
    bom = {
        "currency": "EUR",
        "electronics_class": elec_class,
        "print_eur": summary["cost"],
        "structure_eur": struct_row["cost_eur"],
        "structure_g": struct_row["mass_g"],
        "printed_cap_extra_g": st["cap_extra_g"],
        "electronics_eur": elec_eur,
        "electronics_lines": elec_lines,
        "total_eur": summary["cost"] + struct_row["cost_eur"] + elec_eur,
        "note": "ориентировъчни цени — редактируеми",
    }

    curves = aero.speed_sweep(
        total_g / 1000.0, geom["area_m2"], geom["aspect_ratio"],
        cfg["oswald"], cfg["cd0_used"],
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
        "layout": {
            "propulsion": cfg["propulsion_layout"],
            "propulsion_label": layout.PROPULSION_LAYOUTS[
                cfg["propulsion_layout"]]["label"],
            "motor_count": cfg["motor_count"],
            "wing_position": cfg["wing_position"],
            "wing_position_label": layout.WING_POSITIONS[
                cfg["wing_position"]]["label"],
            "wing_offset_mm": wing_place["offset_mm"],
            "wing_offset_ratio": wing_place["ratio"],
            "wing_offset_percent": wing_place["percent"],
            "wing_offset_clamped": wing_place["clamped"],
            "wing_offset_desc": _wing_offset_desc(wing_place),
            "wing_z_mm": wing_place["z_mm"],
            "wing_root_gap_mm": cfg["wing_root_gap_mm"],
            "tail_root_gap_mm": cfg["tail_root_gap_mm"],
            "tail_type": cfg["tail_type"],
            "tail_type_label": layout.TAIL_TYPES[cfg["tail_type"]]["label"],
            "tail_planform": cfg["tail_planform"],
            "tail_planform_label": aero.TAIL_PLANFORMS[
                cfg["tail_planform"]]["label"],
            "tail_tip_style": cfg["tail_tip_style"],
            "tail_tip_style_label": aero.TAIL_TIP_STYLES[
                cfg["tail_tip_style"]]["label"],
            "v_tail_deg": cfg["v_tail_deg"],
            "v_tail": v_tail,
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
            "tip_style": geom.get("tip_style", "square"),
            "tip_frac": geom.get("tip_frac", 0.0),
            "tip_min_ratio": geom.get("tip_min_ratio", 0.10),
            "washout_deg": cfg["washout_deg"],
            "winglet": dict(cfg["winglet"],
                            chord_mm=((cfg.get("wing_aero", {}).get("winglet")
                                       or {}).get("chord_mm")
                                      or cfg["winglet"]["chord_mm"]),
                            area_dm2=(cfg.get("wing_aero", {}).get("winglet")
                                      or {}).get("area_dm2", 0.0) * 2.0),
            "ailerons": controls.geometry(cfg["ailerons"], geom),
            "bending_factor": geom.get("bending_factor", 1.0),
            "wing_loading_g_dm2": wing_loading,
            "dihedral_deg": cfg["dihedral_deg"],
            "wing_le_mm": wing_le_mm,
            "wing_le_recommended_mm": wing_le_recommended,
            "fuselage": fus,
            "tail": {
                "type": cfg["tail_type"],
                "v_tail": v_tail,
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
                "b_h_mm": tail_b_h_mm,
                "b_v_mm": tail_b_v_mm,
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
            "tail_controls": controls.resolve_tail(
                cfg.get("tail_controls_input"),
                cfg["mission"], cfg["tail_type"]),
            "tail_airfoil": cfg["tail_airfoil"],
            # килът винаги е със симетричен профил (виж airfoils.fin_airfoil)
            "fin_airfoil": airfoils.fin_airfoil(cfg["tail_airfoil"]),
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
            "cd0_winglet": cfg.get("cd0_winglet", 0.0),
            "cd_min_airfoil": cfg["airfoil"]["cd_min"],
            "oswald": cfg["oswald"],
            "oswald_mission": mission["oswald"],
            "oswald_nominal": cfg.get("oswald_nominal", mission["oswald"]),
            "e_planar": cfg.get("wing_aero", {}).get("e_planar"),
            "cl_tip_ratio": cfg.get("wing_aero", {}).get("cl_tip_ratio"),
            "winglet_delta_span": cfg.get("wing_aero", {}).get(
                "delta_span_ratio", 0.0),
            "lift_slope_per_rad": aero.lift_slope(geom["aspect_ratio"],
                                                  cfg["oswald"]),
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
        "material_comparison": comparison,
        "bom": bom,
        "curves": curves,
    }
