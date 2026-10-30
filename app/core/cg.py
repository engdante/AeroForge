"""
cg.py — център на тежестта (ЦТ), статичен запас и баланс с батерията.

ЦТ се смята по моменти около носа на фюзелажа (x = 0).
Аеродинамичният център (AC) на крилото е на 25% от MAC, а неутралната
точка (NP) е зад него с приноса на хоризонталната опашка:

    x_NP = x_AC + V_h · (a_t/a) · (1 − dε/dα) · MAC

Статичният запас се мери спрямо NP (а не спрямо AC на крилото), защото
моментът на тангаж зависи от целия самолет.
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


def neutral_point_mm(wing_le_mm, mac_mm, vh=0.0, has_tail=True):
    """
    Неутрална точка [mm от носа].

    Без опашка (flying wing) NP ≈ AC на крилото; при конвенционална опашка
    NP се измества назад пропорционално на V_h.
    """
    ac_mm = wing_le_mm + 0.25 * mac_mm
    if not has_tail or not vh or vh <= 0:
        return ac_mm
    shift = vh * presets.TAIL_LIFT_RATIO * presets.DOWNWASH_FACTOR * mac_mm
    return ac_mm + shift


def analyse(components, airframe_g, fus_len_mm, wing_le_mm, mac_mm,
            static_margin=0.10, has_tail=True, vh=0.0):
    """
    Пълен анализ на ЦТ и автоматично позициониране на батерията.

    Статичният запас е положителен, когато ЦТ е ПРЕД неутралната точка
    (носещ нос = устойчив модел):

        SM = (x_NP − x_CG) / MAC

    Ако батерията не може да стигне изчисленото място (вън от фюзелажа),
    връща се РЕАЛНИЯТ ЦТ с батерия на границата на обхвата, а
    battery_feasible = False. Така „перфектен“ статичен запас никога не
    се показва за невъзможен баланс.
    """
    sm = presets.clamp(float(static_margin), 0.0, 0.30)
    air = weight.airframe_items(airframe_g, fus_len_mm, wing_le_mm, mac_mm,
                                has_tail)
    items = merge_items(components, air)
    total_g, x_cg_before = center_of_gravity(items)

    mac = max(1.0, float(mac_mm))
    ac_mm = wing_le_mm + 0.25 * mac
    np_mm = neutral_point_mm(wing_le_mm, mac, vh, has_tail)
    target_mm = np_mm - sm * mac

    battery = [i for i in items if i.get("category") == "battery"]
    battery_g = sum(i["mass_g"] for i in battery)
    battery_x_default = ((sum(i["mass_g"] * i["x_mm"] for i in battery)
                         / battery_g) if battery_g > 0 else 0.0)

    x_battery_required = None
    x_battery_placed = None
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
        # Ако изчисленото място е извън фюзелажа — слагаме батерията на
        # най-близката достижима позиция и отчитаме реалния ЦТ.
        x_battery_placed = (x_battery_required if battery_feasible
                            else presets.clamp(x_battery_required, lo, hi))
        balanced_items = []
        for i in items:
            if i.get("category") == "battery":
                i = dict(i, x_mm=x_battery_placed)
            balanced_items.append(i)
        _, x_cg = center_of_gravity(balanced_items)

    shift = ((x_battery_placed - battery_x_default)
             if x_battery_placed is not None else 0.0)

    sm_actual = (np_mm - x_cg) / mac
    sm_before = (np_mm - x_cg_before) / mac
    achievable = (battery_g > 0 and abs(x_cg - target_mm) <= 0.02 * mac)

    return {
        "x_cg_mm": x_cg,
        "x_cg_before_mm": x_cg_before,
        "x_ac_mm": ac_mm,
        "x_np_mm": np_mm,
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
        "battery_x_placed_mm": x_battery_placed,
        "battery_shift_mm": shift,
        "battery_feasible": battery_feasible,
        "cg_achievable": achievable,
        "total_mass_g": total_g,
        "items": balanced_items,
        # nose_heavy е историческо име; x_cg < x_NP означава стабилен,
        # а не непременно „носово тежък“.
        "statically_stable": x_cg < np_mm,
        "nose_heavy": x_cg < np_mm,
        # Това е само „ЦТ/батерията е ок“. Крайният ready_to_fly се
        # изчислява в design.build_result след всички проверки.
        "cg_ready": bool(battery_feasible and achievable),
        "ready_to_fly": bool(battery_feasible and achievable),
    }
