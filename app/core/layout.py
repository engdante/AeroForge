"""
layout.py — компоновка: къде са двигателите, крилото и опашката.

Модулът превежда избора на потребителя (тягач/бутач/два мотора) в
конкретни позиции на компонентите по дължината (за ЦТ), в коефициент за
височината на крилото (за 3D) и в геометрия на V-опашка.

Чисти функции, без зависимости от UI.
"""

import math

from . import weight

# Разположение на задвижването. Стойностите са части от дължината на
# фюзелажа (от носа); при „два мотора“ моторът и витлото са на крилото,
# затова позицията им се смята отделно.
PROPULSION_LAYOUTS = {
    "tractor": {
        "label": "Тягач — мотор отпред",
        "description": "Класическо разположение: теглещо витло, поток по крилото.",
        "motor_count": 1,
        "x": {},                      # базовите дялове от weight
    },
    "pusher": {
        "label": "Бутач — мотор отзад",
        "description": "Бутащо витло: чист поток към крилото, но тежък нос за баланс.",
        "motor_count": 1,
        "x": {
            "prop": 0.99,
            "motor": 0.95,
            "esc": 0.82,
            "battery": 0.22,
            "camera": 0.09,
            "vtx": 0.30,
            "rx": 0.40,
            "servo": 0.66,
            "gear": 0.35,
            "hardware": 0.48,
            "other": 0.42,
        },
    },
    "twin": {
        "label": "Два мотора на крилото",
        "description": "Два еднакви мотора на крилото (по 50% от мощността).",
        "motor_count": 2,
        "x": {
            "esc": 0.14,
            "battery": 0.25,
            "camera": 0.08,
            "vtx": 0.28,
            "rx": 0.38,
            "servo": 0.62,
            "gear": 0.33,
            "hardware": 0.46,
            "other": 0.40,
        },
    },
}

WING_POSITIONS = {
    "high": {"label": "Високо крило", "z": 0.92},
    "mid": {"label": "Средно крило", "z": 0.50},
    "low": {"label": "Ниско крило", "z": 0.18},
}

# Колко от височината на тялото може да се мести крилото от средното
# положение (0.44 = до 94% за короната, -0.44 = до 6% над корема).
WING_OFFSET_LIMIT = 0.44
# Граница за класа „високо/ниско“ — използва се само за отчетите и съветите.
WING_CLASS_BAND = 0.20


def wing_class(ratio):
    """Клас за отчетите (високо/средно/ниско) от отместването (дял от височината)."""
    if ratio >= WING_CLASS_BAND:
        return "high"
    if ratio <= -WING_CLASS_BAND:
        return "low"
    return "mid"


def wing_placement(offset_mm=None, wing_position="high", height_mm=0.0):
    """
    Къде е крилото: отместване в mm от средното положение или стар клас.

    `offset_mm` има приоритет пред `wing_position` (високо/средно/ниско от
    старите дизайни). Отместването се ограничава до ±WING_OFFSET_LIMIT от
    височината на тялото, за да не излезе крилото извън него.

    връща {"z_mm", "offset_mm", "ratio", "class", "percent", "clamped"}
    """
    height = max(0.0, float(height_mm or 0.0))
    limit = WING_OFFSET_LIMIT * height
    clamped = False
    if offset_mm is not None and height > 0:
        value = float(offset_mm)
        if abs(value) > limit:
            value = limit if value > 0 else -limit
            clamped = True
        ratio = value / height
    else:
        key = str(wing_position or "high").lower()
        ratio = float(WING_POSITIONS.get(key, WING_POSITIONS["high"])["z"]) - 0.5
        value = ratio * height
    z = (0.5 + ratio) * height
    return {
        "z_mm": z,
        "offset_mm": value,
        "ratio": ratio,
        "class": wing_class(ratio),
        "percent": 100.0 * (0.5 + ratio),
        "clamped": clamped,
    }


def wing_z_from_result(res):
    """Z на корена на крилото (mm) за изчисления резултат."""
    res = res or {}
    lay = res.get("layout") or {}
    height = float(((res.get("geometry") or {}).get("fuselage") or {})
                   .get("height_mm") or 0.0)
    if lay.get("wing_z_mm") is not None:
        return float(lay["wing_z_mm"])
    return height * wing_z_factor(lay.get("wing_position", "high"))

TAIL_TYPES = {
    "conventional": {
        "label": "Класическа опашка",
        "description": "Стабилизатор на фюзелажа, кил отгоре.",
    },
    "t_tail": {
        "label": "T-опашка",
        "description": "Стабилизаторът е на върха на кила — извън обдухването от витлото.",
    },
    "v_tail": {
        "label": "V-опашка",
        "description": "Две наклонени повърхности вместо стабилизатор и кил.",
    },
}

TAIL_X_RATIO = 0.92   # позиция на опашката по подразбиране (част от L)


def list_propulsion():
    """Каталог на разположенията на двигателите за UI."""
    return [{"key": key, "label": value["label"],
             "description": value["description"],
             "motor_count": value["motor_count"]}
            for key, value in PROPULSION_LAYOUTS.items()]


def list_wing_positions():
    """Каталог на позициите на крилото за UI (бързи бутони за отместване)."""
    return [{"key": key, "label": value["label"], "z": value["z"],
             "offset_ratio": value["z"] - 0.5}
            for key, value in WING_POSITIONS.items()]


def list_tail_types():
    """Каталог на типовете опашка за UI."""
    return [{"key": key, "label": value["label"],
             "description": value["description"]}
            for key, value in TAIL_TYPES.items()]


def motor_count(propulsion="tractor"):
    """Брой мотори за избраното разположение."""
    key = str(propulsion or "tractor").lower()
    return int(PROPULSION_LAYOUTS.get(key, PROPULSION_LAYOUTS["tractor"])
               ["motor_count"])


def wing_z_factor(wing_position="high"):
    """Колко високо е крилото спрямо височината на тялото (0..1)."""
    key = str(wing_position or "high").lower()
    return float(WING_POSITIONS.get(key, WING_POSITIONS["high"])["z"])


def positions(propulsion, fus_len_mm, wing_le_mm, mac_mm):
    """
    Позиции на компонентите по дължината (mm от носа).

    Връща dict категория → mm. Липсващите категории остават с дяловете
    по подразбиране от weight.DEFAULT_X_FRACTION.
    """
    key = str(propulsion or "tractor").lower()
    conf = PROPULSION_LAYOUTS.get(key, PROPULSION_LAYOUTS["tractor"])
    fractions = dict(weight.DEFAULT_X_FRACTION)
    fractions.update(conf["x"])
    if key == "twin":
        # моторът и витлото са на крилото, на 25% от хордата
        on_wing = wing_le_mm + 0.25 * max(1.0, float(mac_mm))
        if fus_len_mm > 0:
            frac = on_wing / fus_len_mm
        else:
            frac = 0.30
        fractions["motor"] = frac
        fractions["prop"] = frac
    out = {}
    for category, frac in fractions.items():
        out[category] = float(frac) * max(0.0, float(fus_len_mm))
    return out


def v_tail_panel(s_h_m2, s_v_m2, gamma_deg=35.0):
    """
    Панел за V-опашка: колко площ е нужна, за да даде същите проекции.

    Хоризонталната проекция е S·cosΓ, вертикалната — S·sinΓ. Двете
    изисквания рядко се удовлетворяват от една и съща площ, затова се
    взима по-голямата (по-консервативно) и се връщат реалните проекции.
    """
    gamma = math.radians(max(10.0, min(60.0, float(gamma_deg))))
    gamma_out = round(math.degrees(gamma), 1)
    cos_g = max(1e-3, math.cos(gamma))
    sin_g = max(1e-3, math.sin(gamma))
    s_h = max(0.0, float(s_h_m2))
    s_v = max(0.0, float(s_v_m2))
    if s_h <= 0 and s_v <= 0:
        return {"s_panel_m2": 0.0, "s_h_eff_m2": 0.0, "s_v_eff_m2": 0.0,
                "gamma_deg": gamma_out, "limited_by": ""}
    need_h = s_h / cos_g if s_h > 0 else 0.0
    need_v = s_v / sin_g if s_v > 0 else 0.0
    panel = max(need_h, need_v)
    return {
        "s_panel_m2": panel,
        "s_h_eff_m2": panel * cos_g,
        "s_v_eff_m2": panel * sin_g,
        "gamma_deg": gamma_out,
        "limited_by": "хоризонтална" if need_h >= need_v else "вертикална",
    }
