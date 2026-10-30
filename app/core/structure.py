"""
structure.py — якостна проверка на крилото и избор на спар.

Модел: конзола, натоварена с елиптично разпределение на подемната сила.
    M_root = (n·W/2)·(4/(3π))·(b/2) = 0.1061·n·W·b
Използва се итеративно с коефициент на сигурност 1.5 (сертификационна
практика за леки конструкции).
"""

import math

from . import airfoils
from . import presets

G = 9.80665
ELLIPTIC_CENTROID = 4.0 / (3.0 * math.pi)          # 0.4244
ROOT_MOMENT_COEFF = ELLIPTIC_CENTROID / 4.0        # 0.1061
DEFLECTION_SHAPE_FACTOR = 0.64                     # елиптично vs върхов товар
CARBON_ALLOW_MPA = 600.0      # pultruded карбон, с вграден запас
CARBON_E_MPA = 90000.0
DEFLECTION_LIMIT_RATIO = 0.08  # % от полуразмаха


def root_bending_moment(mass_kg, span_m, n_limit):
    """Коренов огъващ момент за конзолно крило [N·m]."""
    return ROOT_MOMENT_COEFF * float(n_limit) * mass_kg * G * span_m


def spar_height_mm(c_root_mm, thickness_ratio, factor=0.85):
    """
    Работна височина на спаровите капси.

    Капсите лежат близо до горната/долната повърхност, затова се взема
    ~85% от максималната дебелина на профила.
    """
    return factor * thickness_ratio * c_root_mm


def allowable_print_stress_mpa(filament, safety_factor=1.5):
    """Допустимо напрежение за печатан елемент (опън по слоеве)."""
    return (filament["tensile_mpa"] * filament["layer_factor"]
            / max(1.0, safety_factor))


def pick_carbon_strip(area_needed_mm2):
    """
    Избира карбонова лента (ширина, дебелина) и брой слоеве на капса.

    връща dict с избрания профил и броя ленти.
    """
    best = None
    for width, thick in presets.CARBON_STRIPS_MM:
        area = width * thick
        count = int(math.ceil(area_needed_mm2 / area))
        cand = {
            "width_mm": width,
            "thickness_mm": thick,
            "area_mm2": area,
            "count": count,
            "total_area_mm2": area * count,
        }
        # Предпочитаме минимален брой ленти, после минимална площ
        key = (count, area * count)
        if best is None or key < best[0]:
            best = (key, cand)
    return best[1]


def analyse(mass_kg, geom, filament, mission, airfoil_key,
            n_limit=None, safety_factor=1.5, perimeters=2, nozzle=0.4,
            cap_thickness_mm=None):
    """
    Пълна якостна проверка на крилото.

    връща: моменти, необходима площ на капсите, вариант (печат/карбон),
    деформация на върха и препоръки.
    """
    n = float(n_limit if n_limit else mission.get("n_limit", 4.0))
    n = presets.clamp(n, 1.5, 15.0)
    sf = max(1.0, float(safety_factor))

    m_root = root_bending_moment(mass_kg, geom["span_m"], n)
    m_ult = m_root * sf

    t_ratio = airfoils.thickness_of(airfoil_key)
    h_mm = spar_height_mm(geom["c_root_mm"], t_ratio)

    sigma_print = allowable_print_stress_mpa(filament, sf)
    cap_area_req = (m_ult * 1000.0) / (h_mm * sigma_print) if h_mm > 0 else 0.0

    # Какво може да се отпечата: ширина на капса × дебелина на стената
    cap_width_max = min(0.35 * geom["c_root_mm"], 30.0)
    wall_mm = perimeters * nozzle * 1.125
    if cap_thickness_mm:
        wall_mm = max(wall_mm, float(cap_thickness_mm))
    cap_area_print = cap_width_max * wall_mm
    print_ok = cap_area_req <= cap_area_print

    carbon = pick_carbon_strip(cap_area_req)
    carbon_area = carbon["total_area_mm2"]

    # Деформация на върха
    semispan_mm = geom["span_mm"] / 2.0
    p_half = n * mass_kg * G / 2.0

    def tip_deflection(area_mm2, e_mpa):
        if area_mm2 <= 0 or h_mm <= 0:
            return 0.0
        inertia = 2.0 * area_mm2 * (h_mm / 2.0) ** 2 * 1.15
        return (DEFLECTION_SHAPE_FACTOR * p_half * semispan_mm ** 3
                / (3.0 * e_mpa * inertia))

    e_print = filament["e_mpa"] * 0.8
    defl_print = tip_deflection(min(cap_area_req, cap_area_print), e_print)
    defl_carbon = tip_deflection(carbon_area, CARBON_E_MPA)

    defl_limit = DEFLECTION_LIMIT_RATIO * semispan_mm

    # Съединителна тръба за сглобяемо крило
    tube_od_target = presets.clamp(0.55 * h_mm, 4.0, 16.0)
    tube = min(presets.CARBON_TUBES_MM,
               key=lambda t: abs(t[0] - tube_od_target))
    joiner_len = int(round(1.1 * geom["c_root_mm"] / 10.0) * 10)

    solution = "печатан спар" if print_ok else "печатан + карбонова лента"
    return {
        "n_limit": n,
        "safety_factor": sf,
        "m_root_nm": m_root,
        "m_ult_nm": m_ult,
        "thickness_ratio": t_ratio,
        "spar_height_mm": h_mm,
        "sigma_allow_mpa": sigma_print,
        "cap_area_req_mm2": cap_area_req,
        "cap_area_print_mm2": cap_area_print,
        "cap_width_mm": cap_width_max,
        "wall_mm": wall_mm,
        "print_ok": print_ok,
        "solution": solution,
        "carbon": carbon,
        "carbon_required": not print_ok,
        "carbon_strength_mpa": CARBON_ALLOW_MPA,
        "deflection_print_mm": defl_print,
        "deflection_carbon_mm": defl_carbon,
        "deflection_limit_mm": defl_limit,
        "deflection_ok": (defl_carbon if not print_ok else defl_print) <= defl_limit,
        "joiner_tube": {
            "od_mm": tube[0],
            "id_mm": tube[1],
            "length_mm": joiner_len,
            "count": 2,
        },
        "min_wall_mm": 1.05 * nozzle,
        "wall_ok": wall_mm >= 1.05 * nozzle,
    }
