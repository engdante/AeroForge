"""
structure.py — якостна проверка на крилото и избор на спар.

Модел: конзола, натоварена с елиптично разпределение на подемната сила.
    M_root = (n·W/2)·(4/(3π))·(b/2) = 0.1061·n·W·b
Граничният момент е M_ult = M_root · SF (SF = 1.5, практика за леки
конструкции). Коефициентът на сигурност се прилага САМО веднъж — върху
натоварването; допустимото напрежение е материална характеристика.
"""

import math

from . import airfoils
from . import presets

G = 9.80665
ELLIPTIC_CENTROID = 4.0 / (3.0 * math.pi)          # 0.4244
ROOT_MOMENT_COEFF = ELLIPTIC_CENTROID / 4.0        # 0.1061
# δ_tip за елиптично натоварване спрямо δ на върхов точков товар
# (P·L³/3EI при константно EI): ∫q(s)·(s²L/2 − s³/6)ds / (P·L³/3) = 0.29
DEFLECTION_SHAPE_FACTOR = 0.29
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
    """
    Допустимо напрежение за печатан елемент (опън по слоеве).

    В analyse() се вика с safety_factor=1.0, защото коефициентът на
    сигурност вече е приложен към граничния момент (M_ult = M_root·SF).
    Така SF участва точно веднъж.
    """
    return (filament["tensile_mpa"] * filament["layer_factor"]
            / max(1.0, safety_factor))


def pick_carbon_strip(area_needed_mm2, max_width_mm=None):
    """
    Избира карбонова лента (ширина, дебелина) и брой слоеве на капса.

    max_width_mm ограничава ширината до наличната ширина на капса.
    връща dict с избрания профил и броя ленти.
    """
    candidates = [(w, t) for (w, t) in presets.CARBON_STRIPS_MM
                  if not max_width_mm or w <= max_width_mm]
    if not candidates:
        candidates = list(presets.CARBON_STRIPS_MM)
    best = None
    for width, thick in candidates:
        area = width * thick
        count = max(1, int(math.ceil(area_needed_mm2 / area)))
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

    sigma_mat = allowable_print_stress_mpa(filament, 1.0)
    cap_area_req = (m_ult * 1000.0) / (h_mm * sigma_mat) if h_mm > 0 else 0.0

    # Какво може да се отпечата: ширина на капса × дебелина на стената
    cap_width_max = min(0.35 * geom["c_root_mm"], 30.0)
    wall_mm = perimeters * nozzle * 1.125
    if cap_thickness_mm:
        wall_mm = max(wall_mm, float(cap_thickness_mm))
    cap_area_print = cap_width_max * wall_mm
    print_ok = cap_area_req <= cap_area_print

    # Карбонът поема само недостига, но двата материала работят при
    # еднаква деформация. Карбонът е много по-твърд, затова при
    # достигане на неговото допустимо напрежение печатаният капс е
    # натоварен само до E_print/E_carbon от своето. Това е по-консервативно
    # от простото сумиране на две допустими напрежения.
    e_print = filament["e_mpa"] * 0.8
    sigma_print_compat = (min(sigma_mat,
                              CARBON_ALLOW_MPA * e_print / CARBON_E_MPA)
                          if CARBON_E_MPA > 0 else 0.0)
    m_print_capacity = cap_area_print * h_mm * sigma_mat / 1000.0
    m_print_compat = cap_area_print * h_mm * sigma_print_compat / 1000.0
    m_missing = max(0.0, m_ult - m_print_compat)
    carbon_area_req = ((m_missing * 1000.0) / (h_mm * CARBON_ALLOW_MPA)
                       if h_mm > 0 else 0.0)
    carbon = pick_carbon_strip(carbon_area_req, cap_width_max)
    carbon_area = carbon["total_area_mm2"]

    # Деформация на върха. EI се смята от ДВАТА материала, които реално
    # носят огъването: печатаният капс + (ако има) карбоновата лента.
    semispan_mm = geom["span_mm"] / 2.0
    p_half = n * mass_kg * G / 2.0

    def tip_deflection(area_mm2, e_mpa, extra_area_mm2=0.0, extra_e_mpa=0.0):
        if h_mm <= 0:
            return 0.0
        ei = (2.0 * 1.15 * (h_mm / 2.0) ** 2
              * (area_mm2 * e_mpa + extra_area_mm2 * extra_e_mpa))
        if ei <= 0:
            return 0.0
        return (DEFLECTION_SHAPE_FACTOR * p_half * semispan_mm ** 3
                / (3.0 * ei))

    e_print = filament["e_mpa"] * 0.8
    defl_print = tip_deflection(min(cap_area_req, cap_area_print), e_print)
    defl_carbon = tip_deflection(cap_area_print, e_print,
                                 carbon_area, CARBON_E_MPA)
    defl_limit = DEFLECTION_LIMIT_RATIO * semispan_mm

    # Карбон може да е нужен и само за коравина, когато якостта стига.
    stiffness_required = print_ok and defl_print > defl_limit
    carbon_required = (not print_ok) or stiffness_required
    if not carbon_required:
        carbon["count"] = 0

    if not carbon_required:
        solution = "печатан спар"
    elif print_ok:
        solution = "печатан спар + карбон (за коравина)"
    else:
        solution = "печатан + карбонова лента"

    # Съединителна тръба за сглобяемо крило
    tube_od_target = presets.clamp(0.55 * h_mm, 4.0, 16.0)
    tube = min(presets.CARBON_TUBES_MM,
               key=lambda t: abs(t[0] - tube_od_target))
    joiner_len = int(round(1.1 * geom["c_root_mm"] / 10.0) * 10)

    return {
        "n_limit": n,
        "safety_factor": sf,
        "m_root_nm": m_root,
        "m_ult_nm": m_ult,
        "thickness_ratio": t_ratio,
        "spar_height_mm": h_mm,
        "sigma_allow_mpa": sigma_mat,
        "cap_area_req_mm2": cap_area_req,
        "cap_area_print_mm2": cap_area_print,
        "cap_width_mm": cap_width_max,
        "wall_mm": wall_mm,
        "print_ok": print_ok,
        "print_capacity_nm": m_print_capacity,
        "print_capacity_compat_nm": m_print_compat,
        "sigma_print_at_carbon_mpa": sigma_print_compat,
        "solution": solution,
        "carbon": carbon,
        "carbon_area_req_mm2": carbon_area_req,
        "carbon_required": carbon_required,
        "carbon_for_stiffness": bool(stiffness_required),
        "carbon_strength_mpa": CARBON_ALLOW_MPA,
        "deflection_print_mm": defl_print,
        "deflection_carbon_mm": defl_carbon,
        "deflection_limit_mm": defl_limit,
        "deflection_ok": (defl_carbon if carbon_required
                          else defl_print) <= defl_limit,
        "joiner_tube": {
            "od_mm": tube[0],
            "id_mm": tube[1],
            "length_mm": joiner_len,
            "count": 2,
        },
        "min_wall_mm": 1.05 * nozzle,
        "wall_ok": wall_mm >= 1.05 * nozzle,
    }
