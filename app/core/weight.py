"""
weight.py — компоненти, масов бюджет и разпределение на масата.
"""

import math

CATEGORIES = {
    "motor": "Мотор",
    "esc": "ESC",
    "prop": "Витло",
    "battery": "Батерия",
    "servo": "Серва",
    "rx": "Приемник",
    "camera": "Камера",
    "vtx": "Видео предавател",
    "gear": "Колесник",
    "hardware": "Лепило/крепеж",
    "other": "Друго",
}

# Позиция по подразбиране (част от дължината на фюзелажа, от носа)
DEFAULT_X_FRACTION = {
    "prop": 0.01,
    "motor": 0.04,
    "camera": 0.07,
    "esc": 0.12,
    "battery": 0.24,
    "vtx": 0.27,
    "rx": 0.36,
    "servo": 0.62,
    "gear": 0.32,
    "hardware": 0.45,
    "other": 0.40,
}


def _num(value, default=0.0):
    """Безопасно преобразуване към число (от вход от браузъра)."""
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def normalize_component(comp, fus_len_mm=0.0, index=0):
    """
    Привежда компонент от UI към вътрешен формат.

    x_mm (позиция от носа) може да се зададе ръчно; иначе се взима
    разумна стойност по категория.
    """
    category = comp.get("category") or "other"
    if category not in CATEGORIES:
        category = "other"
    qty = max(1.0, _num(comp.get("qty"), 1.0))
    unit = max(0.0, _num(comp.get("unit_mass_g"), 0.0))
    x_raw = comp.get("x_mm")
    if x_raw is None or x_raw == "":
        frac = DEFAULT_X_FRACTION.get(category, 0.40)
        x_mm = frac * fus_len_mm
        auto_x = True
    else:
        x_mm = _num(x_raw, 0.0)
        auto_x = False
    return {
        "id": comp.get("id") or "c%d" % index,
        "name": comp.get("name") or CATEGORIES[category],
        "category": category,
        "category_label": CATEGORIES[category],
        "qty": qty,
        "unit_mass_g": unit,
        "mass_g": qty * unit,
        "x_mm": x_mm,
        "auto_x": auto_x,
        "estimated": bool(comp.get("estimated", False)),
        "note": comp.get("note", ""),
    }


def components_total_g(components):
    """Обща маса на списък компоненти (нормализирани или сурови)."""
    total = 0.0
    for c in components:
        if "mass_g" in c:
            total += float(c["mass_g"])
        else:
            total += float(c.get("qty", 1) or 1) * float(c.get("unit_mass_g", 0) or 0)
    return total


def provided_categories(components):
    """Кои категории потребителят вече е задал (за да не се оценяват)."""
    return set(c["category"] for c in components if not c.get("estimated"))


def airframe_items(airframe_g, fus_len_mm, wing_le_mm, mac_mm, has_tail=True):
    """
    Разпределя масата на конструкцията по секции (за ЦТ и за графиката).

    Печатаната конструкция не е равномерна: крилото е около своя център,
    фюзелажът е по-тежък в носовата част (оборудване, моторна планка),
    а опашната част е лека тръба. Тегловни дялове: крило 42%, носова част
    на фюзелажа 24%, задна част 16%, опашка 18%.
    """
    if not has_tail:
        return [
            {"name": "Крило (конструкция)", "category": "airframe",
             "mass_g": 0.85 * airframe_g,
             "x_mm": wing_le_mm + 0.45 * mac_mm},
            {"name": "Гърбица/фюзелаж (конструкция)", "category": "airframe",
             "mass_g": 0.15 * airframe_g, "x_mm": 0.30 * fus_len_mm},
        ]
    return [
        {"name": "Крило (конструкция)", "category": "airframe",
         "mass_g": 0.42 * airframe_g,
         "x_mm": wing_le_mm + 0.45 * mac_mm},
        {"name": "Фюзелаж — носова част", "category": "airframe",
         "mass_g": 0.24 * airframe_g, "x_mm": 0.28 * fus_len_mm},
        {"name": "Фюзелаж — задна част", "category": "airframe",
         "mass_g": 0.16 * airframe_g, "x_mm": 0.72 * fus_len_mm},
        {"name": "Опашка (конструкция)", "category": "airframe",
         "mass_g": 0.18 * airframe_g, "x_mm": 0.92 * fus_len_mm},
    ]


def breakdown(components, airframe_g):
    """Разбивка по категории за графиката и отчета."""
    groups = {}
    for c in components:
        key = c["category_label"] if c.get("category_label") else c["category"]
        groups[key] = groups.get(key, 0.0) + c["mass_g"]
    groups["Конструкция (печат)"] = groups.get("Конструкция (печат)", 0.0) \
        + airframe_g
    total = sum(groups.values())
    out = []
    for name, mass in sorted(groups.items(), key=lambda kv: -kv[1]):
        out.append({
            "name": name,
            "mass_g": mass,
            "pct": (100.0 * mass / total) if total > 0 else 0.0,
        })
    return out


def fuselage_dimensions(battery_volume_cm3, mass_kg, fus_len_mm):
    """
    Оразмерява фюзелажа така, че батерията да влезе в носа.

    Батерия: пропорции 3 : 1.4 : 1 (дължина : ширина : височина).
    Минимални размери — от масата на модела (по-голям модел → по-широк
    фюзелаж за достъп и здравина).
    """
    vol_mm3 = max(2000.0, float(battery_volume_cm3) * 1000.0)
    k = (vol_mm3 / 4.2) ** (1.0 / 3.0)      # 3k · 1.4k · k = 4.2k³
    bat_l, bat_w, bat_h = 3.0 * k, 1.4 * k, k

    min_w = 30.0 + 20.0 * math.sqrt(max(0.05, mass_kg))
    width = max(bat_w + 12.0, min_w)
    height = max(bat_h + 12.0, 1.25 * width)
    length = max(fus_len_mm, bat_l + 0.25 * fus_len_mm)

    return {
        "width_mm": width,
        "height_mm": height,
        "length_mm": length,
        "battery_box_mm": [round(bat_l, 1), round(bat_w, 1), round(bat_h, 1)],
        "battery_fits": (bat_l + 0.1 * length) <= length,
    }
