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

# Планформа на опашката: съотношението на върха (taper) и колко от
# полуразмаха се закръгля (`tip_frac`; > 0 значи елипсовиден връх).
TAIL_PLANFORMS = {
    "straight": {
        "label": "Прав (постоянна хорда)",
        "description": "Хордата е еднаква по целия размах — най-прост за "
                       "изработка, върхът носи малко.",
        "taper_h": 1.0,
        "taper_v": 1.0,
        "tip_frac": 0.0,
    },
    "tapered": {
        "label": "Трапец (по подразбиране)",
        "description": "Линейно свиване към върха — класическата опашка.",
        "taper_h": TAIL_TAPER_H,
        "taper_v": TAIL_TAPER_V,
        "tip_frac": 0.0,
    },
    "elliptic": {
        "label": "Елипсовиден",
        "description": "Плавно закръгляне на последните 45% от полуразмаха — "
                       "по-мек връх, малко по-скъп за моделиране.",
        "taper_h": 0.45,
        "taper_v": 0.45,
        "tip_frac": 0.45,
    },
}

TAIL_TIP_STYLES = {
    "square": {"label": "Прав срез", "tip_frac": 0.0},
    "rounded": {"label": "Заоблен връх", "tip_frac": 0.12},
}
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


# --------------------------------------------------------------------------
# Планформа на крилото
# --------------------------------------------------------------------------
# Върхът на крилото.  „Прав срез“ е досегашната форма (трапец); заобленият
# върх намалява концентрацията на вихъра (по-меко загуба на подемна сила,
# по-малко шум, по-здрав ръб при печат).  Уинглетът е вертикална
# повърхност на върха, а „извит нагоре“ е евтин компромис между двете.
TIP_STYLES = {
    "square": {
        "label": "Прав срез",
        "description": "Класически трапец — най-прост за печат, остър ръб.",
        "tip_frac": 0.0,
        "upturn_deg": 0.0,
    },
    "rounded": {
        "label": "Заоблен (Hoerner)",
        "description": "Последните 10 % от полуразмаха се закръгляват по "
                       "елипса — по-мек връх и по-малко вихров шум.",
        "tip_frac": 0.10,
        "upturn_deg": 0.0,
    },
    "upturned": {
        "label": "Извит нагоре",
        "description": "Заоблен връх, който се извива нагоре — малко "
                       "еквивалентно разтежение и повече устойчивост.",
        "tip_frac": 0.06,
        "upturn_deg": 35.0,
    },
    "winglet": {
        "label": "Уинглет",
        "description": "Вертикална повърхност на върха — по-малко "
                       "индуцирано съпротивление, но по-голям коренов момент.",
        "tip_frac": 0.08,
        "upturn_deg": 0.0,
    },
}

# Минимален хорд на върха: под него черупката за печат (стена + отстъп)
# става невалидна, а ръбът е чуплив.
TIP_MIN_MM = 15.0
TIP_MIN_WALLS = 4.0
TIP_MIN_ROOT_RATIO = 0.08   # върхът не бива да е под 8 % от кореновия хорд
TIP_END_RATIO = 0.55        # хорд в самия връх спрямо номиналния (λ·c_root)


def list_tip_styles():
    """Каталог на типовете връх за UI."""
    return [{"key": key, "label": value["label"],
             "description": value["description"],
             "tip_frac": value["tip_frac"],
             "upturn_deg": value["upturn_deg"]}
            for key, value in TIP_STYLES.items()]


def tip_style_of(key):
    """Нормализира ключа на типа връх (непознат → „прав срез“)."""
    key = str(key or "").strip().lower()
    return key if key in TIP_STYLES else "square"


def default_tip_frac(style):
    """Дял от полуразмаха, който се закръглява при даден тип връх."""
    return float(TIP_STYLES[tip_style_of(style)]["tip_frac"])


def tip_min_ratio(wall_mm=1.2, c_root_mm=200.0):
    """
    Минимален хорд на върха като дял от кореновия.

    Печатната черупка има стена и вътрешен отстъп, затова върхът не бива
    да става по-тесен от ~4 дебелини на стената (и не под 12 mm).
    """
    c_root = max(1.0, float(c_root_mm))
    c_min = max(TIP_MIN_MM, TIP_MIN_ROOT_RATIO * c_root,
                TIP_MIN_WALLS * max(0.2, float(wall_mm)))
    return min(0.5, c_min / c_root)


def chord_fraction(x, taper, tip_style="square", tip_frac=None,
                   tip_min_ratio_value=0.10):
    """
    Относителен хорд c(x)/c_root по полуразмаха.

    x = 2·|y|/b ∈ [0, 1] (0 = корен, 1 = връх).  За „прав срез“ е точно
    линейната трапецовидна зависимост.  Останалите типове закръгляват
    последните `tip_frac` от полуразмаха по елипса — това е заоблен
    планформен ъгъл, а не „игла“: върхът запазва ~55 % от номиналния си
    хорд (иначе черупката за печат изтънява до невалидна).
    """
    x = min(1.0, max(0.0, float(x)))
    taper = min(1.0, max(0.2, float(taper)))
    style = tip_style_of(tip_style)
    if tip_frac is None:
        tip_frac = default_tip_frac(style)
    tip_frac = min(0.45, max(0.0, float(tip_frac)))
    linear = 1.0 - (1.0 - taper) * x
    if style == "square" or tip_frac <= 1e-6:
        return linear

    x_round = 1.0 - tip_frac
    if x <= x_round:
        return linear
    c_round = 1.0 - (1.0 - taper) * x_round
    # хорд в самия връх: заоблен ъгъл, но не под минимума за печат
    c_end = max(taper * TIP_END_RATIO, float(tip_min_ratio_value))
    c_end = min(c_round, c_end)
    u = (x - x_round) / tip_frac
    return c_end + (c_round - c_end) * math.sqrt(max(0.0, 1.0 - u * u))


def chord_at(x, c_root_mm, taper, tip_style="square", tip_frac=None,
             tip_min_ratio_value=0.10):
    """Хорд [mm] на дадена позиция по полуразмаха (x = 2|y|/b)."""
    return float(c_root_mm) * chord_fraction(
        x, taper, tip_style, tip_frac, tip_min_ratio_value)


def _simpson(func, a=0.0, b=1.0, samples=40):
    """Интеграл по Симпсън (точен за полиноми до 3-та степен)."""
    n = max(2, int(samples))
    if n % 2:
        n += 1
    h = (b - a) / n
    total = func(a) + func(b)
    for i in range(1, n):
        total += (4.0 if i % 2 else 2.0) * func(a + i * h)
    return total * h / 3.0


def planform(taper, tip_style="square", tip_frac=None, tip_min_ratio_value=0.10,
             samples=40):
    """
    Интегрални характеристики на планформата.

    k_form = ∫c(x)/c_root dx — с него площта се запазва при заоблен връх:
        S = b·c_root·k_form  →  c_root = S/(b·k_form)
    mac_ratio = MAC/c_root = ∫c_n² dx / ∫c_n dx (за трапец дава точно
    аналитичната формула ⅔(1+λ+λ²)/(1+λ)).
    """
    taper = min(1.0, max(0.2, float(taper)))
    style = tip_style_of(tip_style)
    frac = default_tip_frac(style) if tip_frac is None else float(tip_frac)
    frac = min(0.45, max(0.0, frac))

    def c_n(x):
        return chord_fraction(x, taper, style, frac, tip_min_ratio_value)

    k_form = _simpson(c_n, 0.0, 1.0, samples)
    k_mac = _simpson(lambda x: c_n(x) ** 2, 0.0, 1.0, samples)
    return {
        "tip_style": style,
        "tip_frac": frac,
        "tip_min_ratio": float(tip_min_ratio_value),
        "k_form": k_form,
        "mac_ratio": k_mac / max(1e-9, k_form),
        "c_tip_ratio": c_n(1.0),
    }





def wing_geometry(area_m2, aspect_ratio, taper, tip_style="square",
                  tip_frac=None, tip_min_ratio_value=0.10):
    """
    Геометрия на крилото: размах, коренов/върхов хорд, MAC и среден хорд.

    Площта S се запазва при всяка планформа (заоблен/извит връх/уинглет),
    затова натоварването на крилото и статичният запас не се променят от
    формата на върха.
    """
    area_m2 = max(1e-6, float(area_m2))
    aspect_ratio = max(2.0, float(aspect_ratio))
    taper = min(1.0, max(0.2, float(taper)))
    pf = planform(taper, tip_style, tip_frac, tip_min_ratio_value)
    span = math.sqrt(aspect_ratio * area_m2)
    c_root = area_m2 / (span * max(1e-9, pf["k_form"]))
    c_tip = c_root * pf["c_tip_ratio"]
    mac = c_root * pf["mac_ratio"]
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
        "tip_style": pf["tip_style"],
        "tip_frac": pf["tip_frac"],
        "tip_min_ratio": pf["tip_min_ratio"],
        "k_form": pf["k_form"],
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
               wing_le_m=None, taper_h=None, taper_v=None):
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
    taper_h = TAIL_TAPER_H if taper_h is None else float(taper_h)
    taper_v = TAIL_TAPER_V if taper_v is None else float(taper_v)
    fit_limited = False
    tail_ac_m = 0.0

    if wing_le_m is not None and l_cfg > 0 and (vh > 0 or vv > 0):
        wing_ac = float(wing_le_m) + 0.25 * mac_m
        d = (fuselage_len_m
             - TAIL_FIT_MARGIN_RATIO * fuselage_len_m - wing_ac)
        k_h = max(0.0, vh) * area_m2 * mac_m
        k_v = max(0.0, vv) * area_m2 * span_m
        ch_coeff = (2.0 / ((1.0 + taper_h) * math.sqrt(TAIL_AR_H))
                    if TAIL_AR_H > 0 else 0.0)
        cv_coeff = (2.0 / ((1.0 + taper_v) * math.sqrt(TAIL_AR_V))
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
    c_h = tail_chord_m(s_h, TAIL_AR_H, taper_h)
    c_v = tail_chord_m(s_v, TAIL_AR_V, taper_v)
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


# --------------------------------------------------------------------------
# Разпределение на подемната сила (Prandtl–Glauert)
# --------------------------------------------------------------------------
# Класическата теория на носещата линия по Фурие: точно и устойчиво решение
# за произволна планформа (вкл. заоблен връх) и усукване.  Диаедърът влиза
# с класическата загуба на ефективен размах (cos²Γ), уинглетът — като
# еквивалентно удължение на размаха (не-планарна оценка).  Моделът е
# невискозен — вискозните загуби идват от полярата на профила.
LIFT_SLOPE_2D = 5.9        # 1/rad, наклон на подемната сила за 2D профил
LL_STATIONS = 20           # брой фурие-членове/станции в Prandtl–Glauert
LL_ALPHA_REF = math.radians(2.0)   # референтен ъгъл за линеаризацията
ELLIPTIC_MOMENT = 0.1061   # M_root = 0.1061·n·W·b (елиптичен товар)
WINGLET_SPAN_K = 0.45      # еквивалентно удължение на размаха от уинглет
CL_REFERENCE = 0.5         # CL, при който се сравнява ефективността (e)


def _section_chord(geom, x):
    """Хорд [m] при относителна позиция по полуразмаха x = 2|y|/b."""
    return max(1e-4, chord_at(
        x, float(geom["c_root_m"]) * 1000.0, geom.get("taper", 1.0),
        geom.get("tip_style", "square"), geom.get("tip_frac"),
        geom.get("tip_min_ratio", 0.10)) / 1000.0)


def _solve(matrix, rhs):
    """Гаус с избор на водещ елемент; None при изродена матрица."""
    n = len(rhs)
    if n == 0 or any(len(row) != n for row in matrix):
        return None
    a = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
        lead = a[col][col]
        for row in range(col + 1, n):
            factor = a[row][col] / lead
            if factor:
                for k in range(col, n + 1):
                    a[row][k] -= factor * a[col][k]
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        total = a[row][n] - sum(a[row][k] * x[k] for k in range(row + 1, n))
        x[row] = total / a[row][row]
    return x


def _glauert(geom, washout_rad, alpha_ref_rad, stations=20):
    """
    Prandtl–Glauert решение по Фурие за планарно крило.

    Γ(θ) = 2bV·Σ A_n·sin(nθ),  y = −(b/2)·cos θ
    Σ A_n·sin(nθ)·[1 + n·μ/sinθ] = μ·(α(θ) − α0),   μ = a0·c/(4b)

    Устойчиво е (без 1/Δy сингулярността на дискретната вихрена решетка)
    и дава точно разпределение за произволна планформа — вкл. заоблен
    връх — както и усукване (washout) през α(θ).
    """
    span = float(geom["span_m"])
    n_st = max(8, int(stations))
    thetas = [math.pi * (i + 1) / (n_st + 1) for i in range(n_st)]
    matrix, rhs = [], []
    for theta in thetas:
        x = abs(math.cos(theta))
        chord = _section_chord(geom, x)
        mu = LIFT_SLOPE_2D * chord / (4.0 * span)
        matrix.append([math.sin(n * theta) * (1.0 + n * mu / math.sin(theta))
                       for n in range(1, n_st + 1)])
        rhs.append(mu * (alpha_ref_rad - washout_rad * x))
    return _solve(matrix, rhs), thetas


def _local_cl(theta, coeffs, geom):
    """Локален cl при ъгъл θ (в единици 0.5ρV² = 1)."""
    chord = _section_chord(geom, abs(math.cos(theta)))
    series = sum(a * math.sin((n + 1) * theta)
                 for n, a in enumerate(coeffs))
    return 4.0 * float(geom["span_m"]) * series / chord


def winglet_effect(height_mm, chord_mm=None, cant_deg=85.0, taper=0.5,
                   span_mm=0.0, c_ref_mm=0.0):
    """
    Уинглет: площ, омокрена площ и еквивалентно разширение на размаха.

    Еквивалентният размах е класическата не-планарна оценка: вертикална
    повърхност с височина h в края действа като удължение на размаха с
    K·h (K ≈ 0.45 за оптимално натоварен уинглет).  Наклонът (cant) влиза
    със sin, защото хоризонтален „уинглет“ не носи полза.

    c_ref_mm е референтният хорд (номиналният върхов хорд преди
    закръглянето) — от него идва хордът на уинглета, ако не е зададен.
    """
    height = max(0.0, float(height_mm or 0.0))
    if chord_mm is None or float(chord_mm) <= 0:
        chord = 0.6 * max(0.0, float(c_ref_mm))
    else:
        chord = float(chord_mm)
    taper = min(1.0, max(0.2, float(taper)))
    cant = math.radians(min(90.0, max(45.0, float(cant_deg))))
    span = max(1.0, float(span_mm))
    area_side = 1e-6 * height * chord * (1.0 + taper) / 2.0
    delta_ratio = 2.0 * WINGLET_SPAN_K * math.sin(cant) * (height / span)
    return {
        "enabled": height > 1e-6,
        "height_mm": height,
        "chord_mm": chord,
        "taper": taper,
        "cant_deg": math.degrees(cant),
        "area_m2": area_side,
        "area_dm2": area_side * 100.0,
        "area_total_m2": 2.0 * area_side,
        "delta_span_ratio": max(0.0, delta_ratio),
        "wetted_m2": 2.2 * 2.0 * area_side if area_side > 0 else 0.0,
    }


def winglet_cd0_delta(winglet, area_ref_m2, cd_min=0.008):
    """
    Добавка към CD0 от уинглета (триене + смущения).

    Площта е плановата (една страна), омокрената е ~2.2× (двете
    повърхности + ръбове), а cd_min на профила е мярка за 2·cf.
    """
    if not winglet or not winglet.get("enabled") or area_ref_m2 <= 0:
        return 0.0
    wetted = winglet.get("wetted_m2") or 0.0
    return max(0.0, wetted * max(0.006, float(cd_min)) * 1.15 / area_ref_m2)


_PLANFORM_CACHE = {}


def _planform_solution(ar, taper, tip_style, tip_frac, tip_min_ratio_value,
                       washout_deg, stations=LL_STATIONS):
    """
    Решение на Prandtl–Glauert в безразмерен мащаб (размах = 1).

    e, разпределението на cl и кореновият момент са инвариантни на мащаба,
    затова резултатът се кешира по формата на планформата — едно изчисление
    за целия дизайн, независимо колко итерации прави масовият бюджет.
    """
    key = (round(float(ar), 3), round(float(taper), 3), str(tip_style),
           round(float(tip_frac or 0.0), 3), round(float(tip_min_ratio_value), 3),
           round(float(washout_deg), 2), int(stations))
    cached = _PLANFORM_CACHE.get(key)
    if cached is not None:
        return cached

    geom = wing_geometry(1.0 / max(1.0, float(ar)), ar, taper, tip_style,
                         tip_frac, tip_min_ratio_value)
    washout_rad = math.radians(max(-6.0, min(6.0, float(washout_deg))))
    coeffs_ref, thetas = _glauert(geom, washout_rad, LL_ALPHA_REF, stations)
    coeffs_zero, _ = _glauert(geom, washout_rad, 0.0, stations)
    if not coeffs_ref or not coeffs_zero:
        return None

    # e зависи от CL (усукването променя формата на товара), затова се
    # сравнява при умерен CL, а не при произволен ъгъл на атака.
    slope = (coeffs_ref[0] - coeffs_zero[0]) / LL_ALPHA_REF
    if abs(slope) < 1e-9:
        return None
    alpha_star = (CL_REFERENCE / (math.pi * ar) - coeffs_zero[0]) / slope
    ratio = alpha_star / LL_ALPHA_REF
    coeffs = [c0 + (c - c0) * ratio
              for c, c0 in zip(coeffs_ref, coeffs_zero)]

    a1 = coeffs[0]
    total = sum((i + 1) * a * a for i, a in enumerate(coeffs))
    if total <= 1e-12 or a1 <= 0:
        return None

    cl_local = []
    for theta in thetas:
        if math.sin(theta) <= 1e-6:
            continue
        local = _local_cl(theta, coeffs, geom)
        cl_local.append((round(abs(math.cos(theta)), 4),
                         round(local / CL_REFERENCE, 4)))
    tip = [r for x, r in cl_local if x >= 0.85]

    def moment_integrand(theta):
        y = -0.5 * math.cos(theta)
        dy = 0.5 * math.sin(theta)
        chord = _section_chord(geom, abs(math.cos(theta)))
        return y * chord * _local_cl(theta, coeffs, geom) * dy

    moment = _simpson(moment_integrand, 0.5 * math.pi, math.pi, 40)
    lift = CL_REFERENCE * geom["area_m2"]

    result = {
        "e_planar": (a1 * a1) / total,
        "cl_alpha": math.pi * ar * slope,
        "cl_local": cl_local,
        "cl_tip_ratio": max(tip) if tip else 0.0,
        "m_root_factor": (moment / (lift * ELLIPTIC_MOMENT * geom["span_m"])
                          if lift > 1e-9 else 1.0),
        "stations": len(thetas),
    }
    # кешът е малък и ограничен — UI слайдерите не бива да го пълнят
    if len(_PLANFORM_CACHE) > 256:
        _PLANFORM_CACHE.clear()
    _PLANFORM_CACHE[key] = result
    return result


def span_analysis(geom, washout_deg=0.0, dihedral_deg=0.0, sweep_deg=0.0,
                  winglet=None, stations=LL_STATIONS):
    """
    Анализ на носещата система: Oswald e, разпределение на cl, коренов
    момент и наклон на подемната сила.

    Планформата се решава с Prandtl–Glauert (виж _planform_solution),
    диаедърът влиза с класическата загуба на ефективен размах (cos²Γ), а
    уинглетът — като еквивалентно удължение на размаха (winglet_effect).
    Моделът е невискозен.

    връща {"e", "e_planar", "cdi_factor", "cl_alpha", "cl_local",
           "cl_tip_ratio", "m_root_factor", "delta_span_ratio"}
    """
    span = float(geom.get("span_m") or 0.0)
    area = float(geom.get("area_m2") or 0.0)
    ar = max(1.0, float(geom.get("aspect_ratio") or 7.0))
    fallback = {"e": 0.75, "e_planar": 0.75,
                "cdi_factor": 1.0 / (math.pi * ar * 0.75),
                "cl_alpha": LIFT_SLOPE_2D, "cl_local": [],
                "cl_tip_ratio": 0.0, "m_root_factor": 1.0,
                "delta_span_ratio": 0.0, "stations": 0}
    if span <= 0 or area <= 0:
        return fallback

    base = _planform_solution(ar, geom.get("taper", 1.0),
                              geom.get("tip_style", "square"),
                              geom.get("tip_frac"),
                              geom.get("tip_min_ratio", 0.10),
                              washout_deg, stations)
    if not base:
        return fallback

    dihedral_rad = math.radians(max(-15.0, min(25.0, float(dihedral_deg))))
    sweep_rad = math.radians(max(-25.0, min(45.0, float(sweep_deg))))

    delta_span = 0.0
    winglet_info = None
    if winglet and winglet.get("enabled"):
        winglet_info = winglet_effect(winglet.get("height_mm"),
                                      winglet.get("chord_mm"),
                                      winglet.get("cant_deg", 85.0),
                                      winglet.get("taper", 0.5),
                                      span * 1000.0,
                                      float(geom.get("c_root_mm") or 0.0)
                                      * float(geom.get("taper") or 1.0))
        delta_span = winglet_info["delta_span_ratio"]

    e = (base["e_planar"] * math.cos(dihedral_rad) ** 2
         * math.cos(sweep_rad) ** 2 * (1.0 + delta_span) ** 2)
    e = min(1.35, max(0.4, e))

    return {
        "e": e,
        "e_planar": base["e_planar"],
        "cdi_factor": 1.0 / (math.pi * ar * e) if e > 0 else 0.0,
        "cl_alpha": base["cl_alpha"],
        "cl_local": base["cl_local"],
        "cl_tip_ratio": base["cl_tip_ratio"],
        "m_root_factor": min(1.6, max(0.8, base["m_root_factor"])),
        "delta_span_ratio": delta_span,
        "winglet": winglet_info,
        "stations": base["stations"],
    }


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

