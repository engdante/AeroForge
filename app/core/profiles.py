"""
profiles.py — профили на изпълнение (Бюджет / Стандарт / Хай-енд) и BOM.

Профилът е предварителен избор: попълва филамент, конструктивни материали,
клас електроника и легло. Всичко остава ръчно променяемо — профилът не
участва във физиката, само в избора на материали и в цената.

Цените са ОРИЕНТИРОВЪЧНИ в EUR и трябва да се редактират по местния пазар.
"""

PROFILES = {
    "budget": {
        "label": "Бюджет",
        # ASA: солиден филамент (може и PETG). Печата се с 1 периметър и
        # нисък запълнеж — при 2 периметра масата надхвърля бюджета.
        "filament": "asa",
        "perimeters": 1,
        "infill": 5,
        "spar_material": "aluminium",
        "joiner_material": "aluminium",
        "electronics": "budget",
        "bed": [220.0, 220.0, 250.0],
    },
    "standard": {
        "label": "Стандарт",
        "filament": "asa",
        "perimeters": 1,
        "infill": 5,
        "spar_material": "carbon",
        "joiner_material": "carbon",
        "electronics": "standard",
        "bed": [220.0, 220.0, 250.0],
    },
    "highend": {
        "label": "Хай-енд",
        "filament": "lw_pla",
        "spar_material": "carbon",
        "joiner_material": "carbon",
        "electronics": "premium",
        "bed": [256.0, 256.0, 256.0],
    },
}

# Готови размери на леглото (x, y, z) mm
BED_PRESETS = {
    "220×220×250": [220.0, 220.0, 250.0],
    "180×180×180": [180.0, 180.0, 180.0],
    "256×256×256": [256.0, 256.0, 256.0],
}

# Електроника по клас: EUR на бройка; батерията — EUR на Ah
ELECTRONICS_EUR = {
    "budget": {"motor": 12.0, "esc": 8.0, "servo": 4.0, "receiver": 15.0,
               "battery_per_ah": 10.0, "hardware": 5.0},
    "standard": {"motor": 25.0, "esc": 18.0, "servo": 9.0, "receiver": 30.0,
                 "battery_per_ah": 14.0, "hardware": 8.0},
    "premium": {"motor": 60.0, "esc": 40.0, "servo": 20.0, "receiver": 60.0,
                "battery_per_ah": 18.0, "hardware": 12.0},
}


def apply(inputs, profile_key):
    """Връща копие на входа с попълнени стойности от профила."""
    import copy
    if profile_key not in PROFILES:
        raise KeyError("Непознат профил: %s" % profile_key)
    prof = PROFILES[profile_key]
    out = copy.deepcopy(inputs)
    out.setdefault("propulsion", {})
    out.setdefault("structure", {})
    out.setdefault("print", {})
    out.setdefault("bom", {})
    out["print"]["filament"] = prof["filament"]
    if "perimeters" in prof:
        out["print"]["perimeters"] = prof["perimeters"]
    if "infill" in prof:
        out["print"]["infill"] = prof["infill"]
    out["print"]["bed"] = list(prof["bed"])
    out["structure"]["spar_material"] = prof["spar_material"]
    out["structure"]["joiner_material"] = prof["joiner_material"]
    out["bom"]["electronics"] = prof["electronics"]
    out["bom"]["profile"] = profile_key
    return out


# Припокривания от catalog.json (виж catalog.py); празно = вградените стойности.
OVERRIDES = {}


def set_overrides(by_class):
    """Заменя припокриванията на цените по клас електроника."""
    OVERRIDES.clear()
    for cls, values in (by_class or {}).items():
        if cls in ELECTRONICS_EUR:
            OVERRIDES[cls] = dict(values)


def electronics_table(electronics_class):
    """Ефективните цени за клас (вградени + припокрития)."""
    table = dict(ELECTRONICS_EUR[electronics_class])
    table.update(OVERRIDES.get(electronics_class, {}))
    return table


def electronics_cost(electronics_class, motor_count, esc_count, servo_count,
                     battery_ah, has_tail):
    """Ориентировъчна цена на електрониката и крепежа (EUR)."""
    e = electronics_table(electronics_class)
    lines = [
        ("Мотор", motor_count, e["motor"]),
        ("Регулатор (ESC)", esc_count, e["esc"]),
        ("Серво", servo_count, e["servo"]),
        ("Приемник", 1, e["receiver"]),
        ("Батерия (%.2f Ah)" % battery_ah, 1, e["battery_per_ah"] * battery_ah),
        ("Крепеж, шарнири, лепило", 1, e["hardware"]),
    ]
    return [{"name": n, "qty": q, "unit_eur": u, "total_eur": q * u}
            for (n, q, u) in lines]
