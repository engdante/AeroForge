"""
presets.py — пресети по тип модел и справочни таблици.

Стойностите са от практиката на RC моделизма (обхвати, в които моделите
летят добре). Всяка може да се пренастрои от потребителя в UI.
"""

import math

# --------------------------------------------------------------------------
# Типове мисии
# --------------------------------------------------------------------------
MISSIONS = {
    "trainer": {
        "label": "Треньор",
        "description": "Стабилен, бавен, прощаващ грешки — за учене.",
        "wing_loading": 32.0,        # g/dm²
        "wing_loading_range": (24.0, 45.0),
        "power_to_weight": 120.0,    # W/kg
        "thrust_to_weight": 0.60,
        "aspect_ratio": 7.0,
        "aspect_ratio_range": (5.5, 9.0),
        "taper": 0.75,
        "dihedral_deg": 3.0,
        "n_limit": 4.0,
        "cd0": 0.032,
        "oswald": 0.75,
        "fuselage_ratio": 0.75,      # L = k·b
        "tail_arm_ratio": 0.62,      # l_h = k·L
        "vh": 0.55,
        "vv": 0.035,
        "static_margin": 0.12,
        "has_tail": True,
        "aileron_ratio": 0.18,
        "elevator_ratio": 0.35,
        "rudder_ratio": 0.35,
        "cruise_factor": 1.75,       # V_cruise = k·V_stall
        "hand_launch": True,
    },
    "sport": {
        "label": "Спорт",
        "description": "Бърз, пъргав, с добро aerobatic поведение.",
        "wing_loading": 55.0,
        "wing_loading_range": (45.0, 75.0),
        "power_to_weight": 250.0,
        "thrust_to_weight": 0.85,
        "aspect_ratio": 6.0,
        "aspect_ratio_range": (5.0, 7.5),
        "taper": 0.55,
        "dihedral_deg": 2.0,
        "n_limit": 6.0,
        "cd0": 0.028,
        "oswald": 0.78,
        "fuselage_ratio": 0.76,
        "tail_arm_ratio": 0.62,
        "vh": 0.50,
        "vv": 0.035,
        "static_margin": 0.09,
        "has_tail": True,
        "aileron_ratio": 0.20,
        "elevator_ratio": 0.32,
        "rudder_ratio": 0.38,
        "cruise_factor": 1.9,
        "hand_launch": False,
    },
    "3d": {
        "label": "3D / акробатика",
        "description": "Огромни кормила, тяга > тегло, много ниска инерция.",
        "wing_loading": 45.0,
        "wing_loading_range": (35.0, 60.0),
        "power_to_weight": 400.0,
        "thrust_to_weight": 1.60,
        "aspect_ratio": 5.5,
        "aspect_ratio_range": (4.5, 6.5),
        "taper": 0.50,
        "dihedral_deg": 1.0,
        "n_limit": 8.0,
        "cd0": 0.035,
        "oswald": 0.70,
        "fuselage_ratio": 0.80,
        "tail_arm_ratio": 0.58,
        "vh": 0.45,
        "vv": 0.040,
        "static_margin": 0.07,
        "has_tail": True,
        "aileron_ratio": 0.28,
        "elevator_ratio": 0.45,
        "rudder_ratio": 0.45,
        "cruise_factor": 1.6,
        "hand_launch": False,
    },
    "glider": {
        "label": "Планер",
        "description": "Ниско натоварване на крилото, голям размах, дълъг полет.",
        "wing_loading": 22.0,
        "wing_loading_range": (14.0, 32.0),
        "power_to_weight": 90.0,
        "thrust_to_weight": 0.35,
        "aspect_ratio": 9.0,
        "aspect_ratio_range": (7.0, 12.0),
        "taper": 0.60,
        "dihedral_deg": 3.5,
        "n_limit": 5.0,
        "cd0": 0.022,
        "oswald": 0.85,
        "fuselage_ratio": 0.85,
        "tail_arm_ratio": 0.70,
        "vh": 0.65,
        "vv": 0.045,
        "static_margin": 0.10,
        "has_tail": True,
        "aileron_ratio": 0.18,
        "elevator_ratio": 0.35,
        "rudder_ratio": 0.35,
        "cruise_factor": 1.45,
        "hand_launch": True,
    },
    "flying_wing": {
        "label": "Крило (без опашка)",
        "description": "Flying wing / делта — само крило, elevon управление.",
        "wing_loading": 38.0,
        "wing_loading_range": (28.0, 55.0),
        "power_to_weight": 250.0,
        "thrust_to_weight": 0.80,
        "aspect_ratio": 5.0,
        "aspect_ratio_range": (4.0, 6.5),
        "taper": 0.45,
        "dihedral_deg": 2.0,
        "n_limit": 5.0,
        "cd0": 0.032,
        "oswald": 0.72,
        "fuselage_ratio": 0.42,
        "tail_arm_ratio": 0.55,
        "vh": 0.0,
        "vv": 0.0,
        "static_margin": 0.05,
        "has_tail": False,
        "aileron_ratio": 0.25,
        "elevator_ratio": 0.0,
        "rudder_ratio": 0.0,
        "cruise_factor": 1.8,
        "hand_launch": True,
    },
    "cargo": {
        "label": "Товарен / дълъг полет",
        "description": "Носи товар: камери, багаж, доставки.",
        "wing_loading": 60.0,
        "wing_loading_range": (45.0, 90.0),
        "power_to_weight": 110.0,
        "thrust_to_weight": 0.50,
        "aspect_ratio": 6.5,
        "aspect_ratio_range": (5.5, 8.5),
        "taper": 0.80,
        "dihedral_deg": 3.0,
        "n_limit": 3.5,
        "cd0": 0.040,
        "oswald": 0.78,
        "fuselage_ratio": 0.80,
        "tail_arm_ratio": 0.65,
        "vh": 0.60,
        "vv": 0.040,
        "static_margin": 0.12,
        "has_tail": True,
        "aileron_ratio": 0.20,
        "elevator_ratio": 0.35,
        "rudder_ratio": 0.35,
        "cruise_factor": 1.7,
        "hand_launch": False,
    },
}

DEFAULT_MISSION = "trainer"

# --------------------------------------------------------------------------
# Справочни таблици
# --------------------------------------------------------------------------
# Маса на електрическо витло, грамове, по диаметър в инчове
PROP_MASS_G = {
    5: 4, 6: 5, 7: 7, 8: 9, 9: 12, 10: 16, 11: 20, 12: 24, 13: 29,
    14: 35, 15: 42, 16: 48, 17: 55, 18: 62, 19: 70, 20: 80, 22: 95,
}

# Стандартни капацитети LiPo, mAh
BATTERY_CAPACITIES_MAH = [
    300, 450, 650, 850, 1000, 1300, 1500, 1800, 2200, 2600, 3300,
    4000, 4500, 5000, 5200, 6200, 8000, 10000, 13000, 16000, 22000,
]

# Стандартни размери на ESC, A
ESC_SIZES_A = [6, 10, 15, 20, 25, 30, 40, 50, 60, 70, 80, 100, 120, 150]

# Карбонови ленти (ширина × дебелина), mm
CARBON_STRIPS_MM = [
    (3.0, 0.5), (5.0, 0.5), (3.0, 1.0), (5.0, 1.0), (8.0, 0.5),
    (8.0, 1.0), (10.0, 1.0), (10.0, 1.5), (12.0, 1.5), (15.0, 1.5),
]

# Карбонови тръби (външен × вътрешен диаметър), mm
CARBON_TUBES_MM = [
    (4.0, 3.0), (5.0, 4.0), (6.0, 4.0), (6.0, 5.0), (8.0, 6.0),
    (10.0, 8.0), (12.0, 10.0), (14.0, 12.0), (16.0, 14.0),
]

# Типична специфична енергия на LiPo пакет (с кутията и кабелите), Wh/kg
BATTERY_SPECIFIC_ENERGY_WH_KG = 160.0
# Обемна енергийна плътност на LiPo пакет, Wh/cm³
BATTERY_ENERGY_DENSITY_WH_CM3 = 0.36

# Ориентировъчни цени на карбоновите усилвания (€)
CARBON_STRIP_PRICE_PER_MM2 = 0.026   # за mm² напречно сечение
CARBON_TUBE_PRICE_PER_MM = 0.46      # за mm дължина

# Валута за всички цени в приложението
CURRENCY = "€"


def interp(table, x):
    """Линейна интерполация в речник {x: y} с числови ключове."""
    keys = sorted(table)
    if not keys:
        return 0.0
    if x <= keys[0]:
        return float(table[keys[0]])
    if x >= keys[-1]:
        return float(table[keys[-1]])
    for i in range(len(keys) - 1):
        x0, x1 = keys[i], keys[i + 1]
        if x0 <= x <= x1:
            y0, y1 = table[x0], table[x1]
            t = (x - x0) / (x1 - x0)
            return float(y0 + (y1 - y0) * t)
    return float(table[keys[-1]])


def pick_at_least(values, target):
    """Първата стойност от подреден списък, която е >= target."""
    ordered = sorted(values)
    for v in ordered:
        if v >= target:
            return v
    return ordered[-1]


def clamp(value, low, high):
    """Ограничава стойност в интервал."""
    return max(low, min(high, value))


def mission(key):
    """Връща копие на пресета за мисия (fallback към DEFAULT_MISSION)."""
    return dict(MISSIONS.get(key, MISSIONS[DEFAULT_MISSION]))

