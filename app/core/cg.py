"""
cg.py — център на тежестта (ЦТ), статичен запас и баланс с батерията.

ЦТ се смята по моменти около носа на фюзелажа (x = 0).
Аеродинамичният център (AC) се приема на 25% от MAC.
"""

from . import presets
from . import weight


def merge_items(components, airframe_items):
    """Обединява компонентите с разпределената маса на конструкцията."""
    items = []
    for c in components:
        items.append({
            "name": c["name"],
            "category": c.get("category", ""),
            "category_label": c.get("category_label", ""),
            "mass_g": c["mass_g"],
            "x_mm": c["x_mm"],
            "estimated": c.get("estimated", False),
        })
    for a in airframe_items:
        items.append({
            "name": a["name"],
            "category": "airframe",
            "category_label": "Конструкция",
            "mass_g": a["mass_g"],
            "x_mm": a["x_mm"],
            "estimated": False,
        })
    return items


def center_of_gravity(items):
    """Връща (обща маса [g], x_CG [mm от носа])."""
    total = sum(i["mass_g"] for i in items)
    if total <= 0:
        return 0.0, 0.0
    moment = sum(i["mass_g"] * i["x_mm"] for i in items)
    return total, moment / total


def analyse(components, airframe_g, fus_len_mm, wing_le_mm, mac_mm,
            static_margin=0.10, has_tail=True):
    """
    Пълен анализ на ЦТ и автоматично позициониране на батерията.

    Статичният запас е положителен, когато ЦТ е ПРЕД аеродинамичния център
    (носещ нос = устойчив модел):

        SM = (x_AC − x_CG) / MAC

    връща позицията на ЦТ преди и след балансиране, нужното място на
    батерията и списък по елементи.
    """
    sm = presets.clamp(float(static_margin), 0.0, 0.30)
    air = weight.airframe_items(airframe_g, fus_len_mm, wing_le_mm, mac_mm,
                                has_tail)
    items = merge_items(components, air)
    total_g, x_cg_before = center_of_gravity(items)

    mac = max(1.0, float(mac_mm))
    ac_mm = wing_le_mm + 0.25 * mac
    target_mm = ac_mm - sm * mac

    battery = [i for i in items if i.get("category") == "battery"]
    battery_g = sum(i["mass_g"] for i in battery)
    battery_x_default = ((sum(i["mass_g"] * i["x_mm"] for i in battery)
                         / battery_g) if battery_g > 0 else 0.0)

    x_battery_required = None
    battery_feasible = True
    balanced_items = items
    x_cg = x_cg_before

    if battery_g > 0:
        rest = [i for i in items if i.get("category") != "battery"]
        rest_moment = sum(i["mass_g"] * i["x_mm"] for i in rest)
        x_battery_required = (target_mm * total_g - rest_moment) / battery_g
        lo = 0.02 * fus_len_mm
        hi = 0.72 * fus_len_mm
        battery_feasible = lo <= x_battery_required <= hi
        # Балансиран вариант: всички батерии на изчисленото място
        balanced_items = []
        for i in items:
            if i.get("category") == "battery":
                i = dict(i, x_mm=x_battery_required)
            balanced_items.append(i)
        _, x_cg = center_of_gravity(balanced_items)

    shift = ((x_battery_required - battery_x_default)
             if x_battery_required is not None else 0.0)

    sm_actual = (ac_mm - x_cg) / mac
    sm_before = (ac_mm - x_cg_before) / mac

    return {
        "x_cg_mm": x_cg,
        "x_cg_before_mm": x_cg_before,
        "x_ac_mm": ac_mm,
        "x_target_mm": target_mm,
        "wing_le_mm": wing_le_mm,
        "mac_mm": mac,
        "cg_pct_mac": (x_cg - wing_le_mm) / mac * 100.0,
        "cg_pct_mac_before": (x_cg_before - wing_le_mm) / mac * 100.0,
        "static_margin_target": sm,
        "static_margin_actual": sm_actual,
        "static_margin_pct": sm_actual * 100.0,
        "static_margin_before_pct": sm_before * 100.0,
        "battery_mass_g": battery_g,
        "battery_x_default_mm": battery_x_default,
        "battery_x_required_mm": x_battery_required,
        "battery_shift_mm": shift,
        "battery_feasible": battery_feasible,
        "total_mass_g": total_g,
        "items": balanced_items,
        "nose_heavy": x_cg < ac_mm,
        "ready_to_fly": abs(x_cg - target_mm) <= 0.02 * mac,
    }
