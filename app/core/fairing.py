"""
fairing.py — нос на модела: параметри на спинер + каулинг.

Модулът НЕ строи мрежи — само дава параметри, за да може geometry3d
(преглед), assembly (STEP/3MF) и printgeom (STL) да ги построят със
своите примитиви и да останат еднакви.  Така няма кръгова зависимост
между генераторите.

Бележка: „филетата“ (плавни преходи между крилото/опашката и тялото) бяха
махнати — преходът ще се прави по друг начин.
"""

import math

from . import fuselage as fus_mod
from . import motor as motor_mod


def _num(value, default=0.0):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    return out if math.isfinite(out) else float(default)


def spinner_params(res):
    """
    Спинер + каулинг за конкретен дизайн (само при теглещо витло).

    връща {"x_tip", "x_base", "radius", "x_cowl0", "x_cowl1", "r_cowl1",
    "z_center"} в mm или None, ако носът е гол (бутащо витло, без тяло).
    """
    g = res.get("geometry") or {}
    fus = g.get("fuselage") or {}
    layout = res.get("layout") or {}
    if not fus:
        return None
    length = _num(fus.get("length_mm"))
    propulsion = str(layout.get("propulsion") or "tractor").lower()
    if propulsion != "tractor" or length <= 1.0:
        return None
    width = _num(fus.get("width_mm"))
    height = _num(fus.get("height_mm"))
    motor_r = min(width, height) * 0.22
    if motor_r <= 1.0:
        return None
    # спинерът и каулингът побират камбаната на избрания мотор (motor.py)
    radius = max(2.0, motor_r * 1.05, motor_mod.bay_radius(res))

    def half_width(t):
        return 0.5 * width * fus_mod.radius_factor(
            t, _num(fus.get("nose_ratio"), 0.14),
            _num(fus.get("cabin_ratio"), 0.42),
            _num(fus.get("tail_taper"), 0.38))

    # каулингът свършва там, където тялото е поне колкото него
    t_c1 = 0.05
    while half_width(t_c1) < radius and t_c1 < 0.12:
        t_c1 += 0.005
    return {
        "x_tip": -0.045 * length,
        "x_base": 0.012 * length,
        "radius": radius,
        # каулингът свързва спинера с кожата на тялото
        "x_cowl0": 0.008 * length,
        "x_cowl1": t_c1 * length,
        "r_cowl1": max(half_width(t_c1), radius),
        "z_center": 0.5 * height,
    }
