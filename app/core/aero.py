"""
aero.py — аеродинамика: геометрия на крилото, скорости, поляра, L/D.

Всички функции са в SI (m, kg, s, N, W), освен ако името не казва друго.
"""

import math

from . import airfoils

G = 9.80665          # m/s²
RHO = 1.225          # kg/m³, морско ниво, 15 °C
NU = 1.5e-5          # m²/s, кинематичен вискозитет
CL_ALPHA_2D = 5.9    # 1/rad, наклон на подемната сила за 2D профил (~2π·0.94)

# Геометрия на опашните повърхности — използва се и за проверка дали
# опашката физически се побира във фюзелажа.
TAIL_AR_H = 4.5
TAIL_TAPER_H = 0.6
TAIL_AR_V = 1.4
TAIL_TAPER_V = 0.55
TAIL_FIT_MARGIN_RATIO = 0.02   # 2% от дължината на фюзелажа


# --------------------------------------------------------------------------
# Геометрия
# --------------------------------------------------------------------------
def wing_loading_g_dm2(mass_g, area_m2):
    """Натоварване на крилото в g/dm²."""
    if area_m2 <= 0:
        return 0.0
    return mass_g / (area_m2 * 100.0)


def area_from_wing_loading(mass_g, wing_loading):
    """Площ на крилото [m²] по зададено натоварване [g/dm²]."""
    if wing_loading <= 0:
        raise ValueError("Натоварването на крилото трябва да е > 0")
    return mass_g / (wing_loading * 100.0)


def wing_geometry(area_m2, aspect_ratio, taper):
    """
    Геометрия на крило с трапецовидна форма.

    Връща размах, коренов/върхов хорд, MAC и среден хорд.
    """
    aspect_ratio = max(2.0, float(aspect_ratio))
    taper = min(1.0, max(0.2, float(taper)))
    span = math.sqrt(aspect_ratio * area_m2)
    c_root = 2.0 * area_m2 / (span * (1.0 + taper))
    c_tip = taper * c_root
    mac = (2.0 / 3.0) * c_root * (1.0 + taper + taper ** 2) / (1.0 + taper)
    return {
        "area_m2": area_m2,
        "area_dm2": area_m2 * 100.0,
        "span_m": span,
        "span_mm": span * 1000.0,
        "aspect_ratio": aspect_ratio,
        "taper": taper,
        "c_root_m": c_root,
        "c_root_mm": c_root * 1000.0,
        "c_tip_m": c_tip,
        "c_tip_mm": c_tip * 1000.0,
        "c_mean_m": area_m2 / span,
        "mac_m": mac,
        "mac_mm": mac * 1000.0,
    }


def tail_chord_m(area_m2, ar=TAIL_AR_H, taper=TAIL_TAPER_H):
    """Среден (коренов) хорд на опашна повърхност с дадена площ [m]."""
    if area_m2 <= 0 or ar <= 0:
        return 0.0
    taper = min(1.0, max(0.2, float(taper)))
    span = math.sqrt(ar * area_m2)
    if span <= 0:
        return 0.0
    return 2.0 * area_m2 / (span * (1.0 + taper))


def _max_tail_arm_for_fit(d_m, chord_coeff_m):
    """
    Най-голямото рамо l, за което опашката се побира:

        l + chord_coeff/√l ≤ d,   d = L − margin − x_wing_AC

    chord_coeff идва от c_tail(l) = coeff/√l (площта расте при по-късо
    рамо).  Решава се x² + a/x = d с x = √l; връща None, ако дори
    минималният хорд не се побира.
    """
    if d_m <= 0:
        return None
    a = max(0.0, float(chord_coeff_m))
    if a <= 0:
        return d_m
    x_min = (a / 2.0) ** (1.0 / 3.0)      # минимум на x² + a/x
    if x_min * x_min + a / x_min > d_m:
        return None
    # l ≤ d, следователно x = √l ≤ √d.  (hi = d би дал l = d².)
    lo, hi = x_min, math.sqrt(d_m)
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if mid * mid + a / mid > d_m:
            hi = mid
        else:
            lo = mid
    return lo * lo


def tail_areas(area_m2, span_m, mac_m, fuselage_len_m, tail_arm_ratio, vh, vv,
               wing_le_m=None):
    """
    Площи на опашните повърхности по обемни коефициенти.

        V_h = S_h·l_h / (S·MAC)  ->  S_h = V_h·S·MAC / l_h
        V_v = S_v·l_v / (S·b)    ->  S_v = V_v·S·b / l_v

    Рамото l се мери от аеродинамичния център на крилото до
    аеродинамичния център на опашката. Ако е зададена позицията на крилото
    (wing_le_m), проверява се дали опашката физически се побира във
    фюзелажа. Когато не се побира, рамото се скъсява до максимално
    възможното, а площта се увеличава така, че V_h/V_v да останат същите.
    Така статичният запас не се получава „оптимистичен“.
    """
    l_cfg = max(0.0, tail_arm_ratio) * fuselage_len_m
    l_h = l_cfg
    l_v = l_cfg
    fit_limited = False
    tail_ac_m = 0.0

    if wing_le_m is not None and l_cfg > 0 and (vh > 0 or vv > 0):
        wing_ac = float(wing_le_m) + 0.25 * mac_m
        d = (fuselage_len_m
             - TAIL_FIT_MARGIN_RATIO * fuselage_len_m - wing_ac)
        k_h = max(0.0, vh) * area_m2 * mac_m
        k_v = max(0.0, vv) * area_m2 * span_m
        ch_coeff = (2.0 / ((1.0 + TAIL_TAPER_H) * math.sqrt(TAIL_AR_H))
                    if TAIL_AR_H > 0 else 0.0)
        cv_coeff = (2.0 / ((1.0 + TAIL_TAPER_V) * math.sqrt(TAIL_AR_V))
                    if TAIL_AR_V > 0 else 0.0)
        # 0.75·c_tail(l) = C/√l; за двете повърхности се взема по-голямото C.
        c_fit = max(0.75 * ch_coeff * math.sqrt(k_h) if k_h > 0 else 0.0,
                    0.75 * cv_coeff * math.sqrt(k_v) if k_v > 0 else 0.0)
        l_max = _max_tail_arm_for_fit(d, c_fit)
        if l_max is None:
            l_max = max(0.05 * fuselage_len_m, 1e-9)
            fit_limited = True
        if l_max < l_cfg - 1e-9:
            l_h = l_v = max(0.05 * fuselage_len_m, l_max)
            fit_limited = True
        tail_ac_m = wing_ac + l_h

    s_h = (vh * area_m2 * mac_m / l_h) if (l_h > 0 and vh > 0) else 0.0
    s_v = (vv * area_m2 * span_m / l_v) if (l_v > 0 and vv > 0) else 0.0
    c_h = tail_chord_m(s_h, TAIL_AR_H, TAIL_TAPER_H)
    c_v = tail_chord_m(s_v, TAIL_AR_V, TAIL_TAPER_V)
    return {
        "s_h_m2": s_h,
        "s_h_dm2": s_h * 100.0,
        "s_v_m2": s_v,
        "s_v_dm2": s_v * 100.0,
        "l_h_m": l_h,
        "l_h_mm": l_h * 1000.0,
        "l_v_m": l_v,
        "l_v_mm": l_v * 1000.0,
        "l_h_configured_mm": l_cfg * 1000.0,
        "l_eff_mm": l_h * 1000.0,
        "tail_fit_limited": fit_limited,
        "tail_ac_mm": tail_ac_m * 1000.0,
        "c_h_mm": c_h * 1000.0,
        "c_v_mm": c_v * 1000.0,
    }


def fuselage_length(span_m, ratio=0.75):
    """Дължина на фюзелажа по правилото L = k·b."""
    return span_m * ratio


def cd0_for_airfoil(base_cd0, airfoil):
    """
    Коригира общия CD0 по избрания профил.

    `mission["cd0"]` е общото паразитно съпротивление, калибрирано за
    референтния профил NACA 2412. Смяната на профила променя само
    профилната част: CD0 = base − CD_min(ref) + CD_min(selected).
    Така NACA 0009 намалява съпротивлението, а S1223 го увеличава.
    """
    ref_cd = airfoils.get("naca2412").get("cd_min", 0.010)
    cd_min = airfoil.get("cd_min", ref_cd)
    return max(0.005, float(base_cd0) - ref_cd + float(cd_min))


# --------------------------------------------------------------------------
# Скорости и Re
# --------------------------------------------------------------------------
def reynolds(v_ms, chord_m):
    """Число на Рейнолдс по хорда."""
    if chord_m <= 0:
        return 0.0
    return v_ms * chord_m / NU


def stall_speed(mass_kg, area_m2, cl_max):
    """Скорост на загуба на подемна сила [m/s]."""
    if area_m2 <= 0 or cl_max <= 0:
        return 0.0
    return math.sqrt(2.0 * mass_kg * G / (RHO * area_m2 * cl_max))


def stall_analysis(mass_kg, area_m2, mac_m, cl_max_catalog, iterations=4):
    """
    Итеративно изчислява V_stall с корекция на CL_max по Re.

    Re зависи от скоростта, а CL_max — от Re, затова се итерира до
    стабилизиране (обикновено 2–3 стъпки, |ΔV| < 0.01 m/s).
    """
    cl = cl_max_catalog
    v = stall_speed(mass_kg, area_m2, cl)
    best = {"v_stall_ms": v, "cl_max": cl, "re_stall": reynolds(v, mac_m)}
    for _ in range(max(1, int(iterations))):
        re = reynolds(v, mac_m)
        cl = airfoils.clmax_at_re(cl_max_catalog, re)
        v_new = stall_speed(mass_kg, area_m2, cl)
        best = {"v_stall_ms": v_new, "cl_max": cl,
                "re_stall": reynolds(v_new, mac_m)}
        if abs(v_new - v) < 1e-3:
            break
        v = v_new
    return {
        "v_stall_ms": best["v_stall_ms"],
        "cl_max_catalog": cl_max_catalog,
        "cl_max": best["cl_max"],
        "re_stall": best["re_stall"],
    }


# --------------------------------------------------------------------------
# Поляра и мощност
# --------------------------------------------------------------------------
def lift_slope(ar, oswald=0.75):
    """
    Наклон на подемната сила за крило с краен размах [1/rad].

    Класическата формула a = a0/(1 + a0/(π·AR)) не включва Oswald —
    той е за индуцираното съпротивление. Параметърът се пази за
    съвместимост на извикванията.
    """
    ar = max(1.0, float(ar))
    return CL_ALPHA_2D / (1.0 + CL_ALPHA_2D / (math.pi * ar))


def drag_polar(cl, ar, oswald, cd0):
    """CD = CD0 + CL²/(π·AR·e)."""
    k = math.pi * max(1.0, ar) * max(0.3, oswald)
    return cd0 + cl * cl / k


def best_ld(ar, oswald, cd0):
    """
    Максимално аеродинамично качество и CL за него.

    CL_opt = √(π·AR·e·CD0); при него CD = 2·CD0, следователно
    L/D_max = CL_opt / (2·CD0) = √(π·AR·e/CD0) / 2.
    """
    k = math.pi * max(1.0, ar) * max(0.3, oswald)
    if cd0 <= 0 or k <= 0:
        return 0.0, 0.0
    cl_opt = math.sqrt(cd0 * k)
    return math.sqrt(k / cd0) / 2.0, cl_opt


def speed_for_cl(mass_kg, area_m2, cl):
    """Скорост, при която даден CL носи теглото (хоризонтален полет) [m/s]."""
    if area_m2 <= 0 or cl <= 0:
        return 0.0
    return math.sqrt(2.0 * mass_kg * G / (RHO * area_m2 * cl))


def lift_coefficient(mass_kg, area_m2, v_ms):
    """Нужен CL за хоризонтален полет при дадена скорост."""
    if area_m2 <= 0 or v_ms <= 0:
        return 0.0
    return 2.0 * mass_kg * G / (RHO * v_ms * v_ms * area_m2)


def level_flight(mass_kg, area_m2, ar, oswald, cd0, v_ms, prop_eff=0.55):
    """
    Хоризонтален полет при скорост v.

    Връща CL, CD, съпротивление и мощност на вала на витлото.
    """
    cl = lift_coefficient(mass_kg, area_m2, v_ms)
    cd = drag_polar(cl, ar, oswald, cd0)
    drag = 0.5 * RHO * v_ms * v_ms * area_m2 * cd
    p_shaft = drag * v_ms / max(0.2, prop_eff)
    return {"cl": cl, "cd": cd, "drag_n": drag, "p_shaft_w": p_shaft}


def speed_sweep(mass_kg, area_m2, ar, oswald, cd0, v_min, v_max,
                n=18, prop_eff=0.55, p_shaft_available=None,
                cl_max=None):
    """
    Данни за графиките: V, CL, CD, L/D, нужна мощност.

    Стойностите над CL_max се маркират като None (невъзможен полет).
    """
    n = max(4, int(n))
    v_min = max(0.5, v_min)
    v_max = max(v_min + 0.5, v_max)
    out = {"v": [], "cl": [], "cd": [], "ld": [], "p_req": [], "p_avail": []}
    for i in range(n):
        v = v_min + (v_max - v_min) * i / (n - 1)
        cl = lift_coefficient(mass_kg, area_m2, v)
        cd = drag_polar(cl, ar, oswald, cd0)
        ld = cl / cd if cd > 0 else 0.0
        p_shaft = 0.5 * RHO * v * v * area_m2 * cd * v / max(0.2, prop_eff)
        feasible = (cl_max is None) or (cl <= cl_max)
        out["v"].append(round(v, 2))
        out["cl"].append(round(cl, 3))
        out["cd"].append(round(cd, 4))
        out["ld"].append(round(ld, 1) if feasible else None)
        out["p_req"].append(round(p_shaft, 1) if feasible else None)
        out["p_avail"].append(round(p_shaft_available, 1)
                              if p_shaft_available else None)
    return out

