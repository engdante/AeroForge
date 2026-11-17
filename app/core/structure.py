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
from . import structmat

G = 9.80665
ELLIPTIC_CENTROID = 4.0 / (3.0 * math.pi)          # 0.4244
ROOT_MOMENT_COEFF = ELLIPTIC_CENTROID / 4.0        # 0.1061
# δ_tip за елиптично натоварване спрямо δ на върхов точков товар
# (P·L³/3EI при константно EI): ∫q(s)·(s²L/2 − s³/6)ds / (P·L³/3) = 0.29
DEFLECTION_SHAPE_FACTOR = 0.29
CARBON_ALLOW_MPA = 600.0      # pultruded карбон, с вграден запас
CARBON_E_MPA = 90000.0
DEFLECTION_LIMIT_RATIO = 0.08  # % от полуразмаха
# Натиск и локално изкълчване (оценка, да се провери с тестови отпечатъци):
# печатан капс при натиск е ~70% от опъна по слоеве. Капсът е подпрян по
# двата си надлъжни ръба от обшивката/стената (k = 4), затова се третира
# като плоча, а не като свободна колона.
COMPRESSION_FACTOR_PRINT = 0.7
PLATE_BUCKLING_K = 4.0
POISSON = 0.3
# Удебеляване на печатания капс: само капсът, не всички стени. Горна граница
# (ориентировъчна) — над нея капсът се смята за непечатаем.
CAP_MAX_THICKNESS_MM = 1.4
CAP_THICKEN_STEP_MM = 0.05


def root_bending_moment(mass_kg, span_m, n_limit, load_factor=1.0):
    """
    Коренов огъващ момент за конзолно крило [N·m].

    load_factor идва от разпределението на подемната сила (виж
    aero.span_analysis): 1.0 = елиптично, >1 при уинглет или силно
    свиване.  Така уинглетът реално товари спа̀ра, вместо да е безплатен.
    """
    return (ROOT_MOMENT_COEFF * float(load_factor) * float(n_limit)
            * mass_kg * G * span_m)


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


def plate_buckling_stress_mpa(width_mm, thick_mm, e_mpa, k=PLATE_BUCKLING_K):
    """
    Критично напрежение на локално изкълчване на подпрян капс:
    σ_cr = k·π²·E / (12·(1 − ν²)) · (t / b)².
    """
    if width_mm <= 0 or thick_mm <= 0:
        return 0.0
    return (k * math.pi ** 2 * e_mpa / (12.0 * (1.0 - POISSON ** 2))
            * (thick_mm / width_mm) ** 2)


def thicken_cap(wall_mm, width_mm, h_mm, m_ult, sigma_mat, sigma_compat,
                filament):
    """
    Дебелина на печатания капс, при която натискът минава и σ_cr стига.

    Натоварването на капса е min(m_ult, капацитетът му) / h — при по-дебел
    капс то расте, а напрежението пада като 1/t, докато σ_cr расте като t².
    Връща (дебелина_mm, удебелен_ли, ок_ли).
    """
    if width_mm <= 0 or h_mm <= 0:
        return wall_mm, False, False
    allow = COMPRESSION_FACTOR_PRINT * sigma_mat
    e_buckle = filament["e_mpa"] * 0.8

    def passes(t):
        area = width_mm * t
        load = min(m_ult, area * h_mm * sigma_compat / 1000.0) * 1000.0 / h_mm
        comp = load / area
        return (comp <= allow
                and comp <= plate_buckling_stress_mpa(width_mm, t, e_buckle))

    t = wall_mm
    while not passes(t):
        if t >= CAP_MAX_THICKNESS_MM - 1e-9:
            return wall_mm, False, False
        t = round(t + CAP_THICKEN_STEP_MM, 3)
    return t, t > wall_mm + 1e-9, True


def pick_carbon_strip(area_needed_mm2, max_width_mm=None, strips=None):
    """
    Избира карбонова лента (ширина, дебелина) и брой слоеве на капса.

    max_width_mm ограничава ширината до наличната ширина на капса.
    връща dict с избрания профил и броя ленти.
    """
    strips = strips or presets.CARBON_STRIPS_MM
    candidates = [(w, t) for (w, t) in strips
                  if not max_width_mm or w <= max_width_mm]
    if not candidates:
        candidates = list(strips)
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


def _reinforcement(material_key):
    """E, допустимо и ленти за спара; карбонът връща старите константи."""
    if material_key == "carbon":
        return {"e": CARBON_E_MPA, "allow": CARBON_ALLOW_MPA,
                "strips": presets.CARBON_STRIPS_MM}
    mat = structmat.get(material_key)
    return {"e": mat["e_mpa"], "allow": mat["allow_mpa"],
            "strips": structmat.STRIPS_MM.get(material_key,
                                              presets.CARBON_STRIPS_MM)}


def analyse(mass_kg, geom, filament, mission, airfoil_key,
            n_limit=None, safety_factor=1.5, perimeters=2, nozzle=0.4,
            cap_thickness_mm=None, spar_material="carbon",
            joiner_material="carbon"):
    """
    Пълна якостна проверка на крилото.

    връща: моменти, необходима площ на капсите, вариант (печат/карбон),
    деформация на върха и препоръки.
    """
    n = float(n_limit if n_limit else mission.get("n_limit", 4.0))
    n = presets.clamp(n, 1.5, 15.0)
    sf = max(1.0, float(safety_factor))
    # Армировка на спара: карбон (по подразбиране, както досега) или
    # алуминиева/дървена лента — със своите E, допустимо и ленти.
    reinf = _reinforcement(spar_material)

    m_root = root_bending_moment(mass_kg, geom["span_m"], n,
                                 geom.get("bending_factor", 1.0))
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

    # Карбонът поема само недостига, но двата материала работят при
    # еднаква деформация. Карбонът е много по-твърд, затова при
    # достигане на неговото допустимо напрежение печатаният капс е
    # натоварен само до E_print/E_carbon от своето. Това е по-консервативно
    # от простото сумиране на две допустими напрежения.
    sigma_print_compat = (min(sigma_mat,
                              reinf["allow"] * (filament["e_mpa"] * 0.8)
                              / reinf["e"])
                          if reinf["e"] > 0 else 0.0)

    # Капсът се удебелява само ако натискът или изкълчването не минават.
    wall_before_mm = wall_mm
    wall_mm, cap_thickened, cap_buckle_ok = thicken_cap(
        wall_mm, cap_width_max, h_mm, m_ult, sigma_mat, sigma_print_compat,
        filament)
    cap_extra_g = (max(0.0, wall_mm - wall_before_mm) * cap_width_max
                   * geom["span_mm"] * 0.5 * float(filament["printed_density"])
                   / 1000.0)
    cap_area_print = cap_width_max * wall_mm
    print_ok = cap_area_req <= cap_area_print

    # Карбонът поема само недостига, но двата материала работят при
    # еднаква деформация. Карбонът е много по-твърд, затова при
    # достигане на неговото допустимо напрежение печатаният капс е
    # натоварен само до E_print/E_carbon от своето. Това е по-консервативно
    # от простото сумиране на две допустими напрежения.
    e_print = filament["e_mpa"] * 0.8
    m_print_capacity = cap_area_print * h_mm * sigma_mat / 1000.0
    m_print_compat = cap_area_print * h_mm * sigma_print_compat / 1000.0
    m_missing = max(0.0, m_ult - m_print_compat)
    carbon_area_req = ((m_missing * 1000.0) / (h_mm * reinf["allow"])
                       if h_mm > 0 else 0.0)
    carbon = pick_carbon_strip(carbon_area_req, cap_width_max,
                               strips=reinf["strips"])
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
                                 carbon_area, reinf["e"])
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

    # Натиск и локално изкълчване на печатания капс (горният пояс е на
    # натиск). Натоварването е частта, която капсът носи сам.
    cap_load_n = (min(m_ult, m_print_compat) * 1000.0 / h_mm
                  if h_mm > 0 else 0.0)
    cap_area_mm2 = cap_width_max * wall_mm
    comp_stress = cap_load_n / cap_area_mm2 if cap_area_mm2 > 0 else 0.0
    compression_allow = COMPRESSION_FACTOR_PRINT * sigma_mat
    compression_ok = comp_stress <= compression_allow
    e_print_buckle = filament["e_mpa"] * 0.8
    sigma_cr = plate_buckling_stress_mpa(cap_width_max, wall_mm,
                                         e_print_buckle)
    buckling_ok = comp_stress <= sigma_cr

    # Съединителна тръба за сглобяемо крило
    tube_od_target = presets.clamp(0.55 * h_mm, 4.0, 16.0)
    tube = min(presets.CARBON_TUBES_MM,
               key=lambda t: abs(t[0] - tube_od_target))
    joiner_len = int(round(1.1 * geom["c_root_mm"] / 10.0) * 10)
    joiner = {
        "material": "carbon",
        "od_mm": tube[0],
        "id_mm": tube[1],
        "length_mm": joiner_len,
        "count": 2,
    }
    if joiner_material != "carbon":
        # Джойнер по якост: огъващият момент при корена, без геометричното правило
        sel = structmat.select_tube(joiner_material, m_ult)
        joiner.update({
            "material": joiner_material,
            "od_mm": sel["od_mm"] if sel else None,
            "id_mm": sel["id_mm"] if sel else None,
            "stress_mpa": sel["stress_mpa"] if sel else None,
            "allow_mpa": sel["allow_mpa"] if sel else None,
            "mass_g_per_m": sel["mass_g_per_m"] if sel else None,
            "ok": sel is not None,
        })
    # Лепилна връзка: срязващото усилие на корена през двата джойнера
    shear_n = n * mass_kg * G / 2.0
    bonded_mm2 = (2.0 * math.pi * (joiner["od_mm"] or 0.0)
                  * (joiner_len / 2.0)) if joiner["od_mm"] else 0.0
    adhesive_mpa = structmat.bonded_shear_mpa(shear_n, bonded_mm2)
    adhesive_ok = adhesive_mpa <= structmat.ADHESIVE_SHEAR_ALLOW_MPA

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
        "cap_thickened": bool(cap_thickened),
        "cap_extra_g": cap_extra_g,
        "cap_thicken_ok": bool(cap_buckle_ok),
        "print_ok": print_ok,
        "print_capacity_nm": m_print_capacity,
        "print_capacity_compat_nm": m_print_compat,
        "sigma_print_at_carbon_mpa": sigma_print_compat,
        "solution": solution,
        "carbon": carbon,
        "carbon_area_req_mm2": carbon_area_req,
        "carbon_required": carbon_required,
        "carbon_for_stiffness": bool(stiffness_required),
        "carbon_strength_mpa": reinf["allow"],
        "spar_material": spar_material,
        "deflection_print_mm": defl_print,
        "deflection_carbon_mm": defl_carbon,
        "deflection_limit_mm": defl_limit,
        "deflection_ok": (defl_carbon if carbon_required
                          else defl_print) <= defl_limit,
        "joiner_tube": joiner,
        "adhesive_shear_mpa": adhesive_mpa,
        "adhesive_ok": adhesive_ok,
        "cap_load_n": cap_load_n,
        "cap_compression_mpa": comp_stress,
        "compression_allow_mpa": compression_allow,
        "compression_ok": bool(compression_ok),
        "buckling_stress_mpa": sigma_cr,
        "buckling_ok": bool(buckling_ok),
        "min_wall_mm": 1.05 * nozzle,
        "wall_ok": wall_mm >= 1.05 * nozzle,
    }
