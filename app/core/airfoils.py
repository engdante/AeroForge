"""
airfoils.py — профили на крилото.

Съдържа:
  * генератор на NACA 4-цифрени профили (реални координати по формулите
    на NACA Report 824);
  * каталог с аеродинамични данни (CL_max, CD_min, допустим Re диапазон),
    използвани за оразмеряване и за проверки.

Каталогът пази само данни за профилите, за които нямаме вградени
координати — така не се показват „измислени“ контури.
"""

import math

# --------------------------------------------------------------------------
# Каталог
# --------------------------------------------------------------------------
# cl_max   — максимален коефициент на подемна сила при Re ~150k
# cl0      — CL при нулев ъгъл на атака
# cd_min   — минимално съпротивление
# re_range — диапазон, в който профилът работи добре
# kind     — cambered / symmetric / reflexed (за крило без опашка)
AIRFOILS = {
    "naca2412": {
        "key": "naca2412",
        "name": "NACA 2412",
        "code": "2412",
        "kind": "cambered",
        "cl_max": 1.40,
        "cl0": 0.25,
        "cd_min": 0.010,
        "alpha_stall": 14.0,
        "re_range": (60000, 600000),
        "use": "Треньор, общо предназначение",
        "has_coords": True,
    },
    "naca4412": {
        "key": "naca4412",
        "name": "NACA 4412",
        "code": "4412",
        "kind": "cambered",
        "cl_max": 1.55,
        "cl0": 0.40,
        "cd_min": 0.011,
        "alpha_stall": 13.0,
        "re_range": (60000, 500000),
        "use": "Бавни и товарни модели, голяма подемна сила",
        "has_coords": True,
    },
    "naca2415": {
        "key": "naca2415",
        "name": "NACA 2415",
        "code": "2415",
        "kind": "cambered",
        "cl_max": 1.50,
        "cl0": 0.28,
        "cd_min": 0.012,
        "alpha_stall": 12.5,
        "re_range": (50000, 400000),
        "use": "Треньор с по-голяма носеща способност и по-здрав спар",
        "has_coords": True,
    },
    "naca0012": {
        "key": "naca0012",
        "name": "NACA 0012",
        "code": "0012",
        "kind": "symmetric",
        "cl_max": 1.05,
        "cl0": 0.0,
        "cd_min": 0.008,
        "alpha_stall": 12.0,
        "re_range": (50000, 600000),
        "use": "Симетричен: 3D/акробатика, стабилизатори",
        "has_coords": True,
    },
    "naca0009": {
        "key": "naca0009",
        "name": "NACA 0009",
        "code": "0009",
        "kind": "symmetric",
        "cl_max": 0.85,
        "cl0": 0.0,
        "cd_min": 0.007,
        "alpha_stall": 10.0,
        "re_range": (40000, 400000),
        "use": "Опашни повърхности (стабилизатор, кил)",
        "has_coords": True,
    },
    "clarky": {
        "key": "clarky",
        "name": "Clark Y",
        "code": None,
        "kind": "cambered",
        "cl_max": 1.50,
        "cl0": 0.45,
        "cd_min": 0.012,
        "alpha_stall": 14.0,
        "re_range": (50000, 400000),
        "use": "Класика за треньори; плоска долна повърхност — лесен за печат",
        "geometry": {"thickness": 0.117, "camber": 0.034,
                     "camber_pos": 0.35, "reflex": 0.0},
        "has_coords": False,
    },
    "s1223": {
        "key": "s1223",
        "name": "Selig S1223",
        "code": None,
        "kind": "cambered",
        "cl_max": 2.00,
        "cl0": 0.90,
        "cd_min": 0.018,
        "alpha_stall": 11.0,
        "re_range": (80000, 300000),
        "use": "Максимална подемна сила при ниска скорост (FPV, бавни крила)",
        "geometry": {"thickness": 0.085, "camber": 0.075,
                     "camber_pos": 0.45, "reflex": 0.0},
        "has_coords": False,
    },
    "mh32": {
        "key": "mh32",
        "name": "MH 32",
        "code": None,
        "kind": "cambered",
        "cl_max": 1.25,
        "cl0": 0.35,
        "cd_min": 0.007,
        "alpha_stall": 11.0,
        "re_range": (100000, 500000),
        "use": "Спорт/планер — ниско съпротивление",
        "geometry": {"thickness": 0.100, "camber": 0.024,
                     "camber_pos": 0.42, "reflex": 0.0},
        "has_coords": False,
    },
    "e205": {
        "key": "e205",
        "name": "Eppler E205",
        "code": None,
        "kind": "cambered",
        "cl_max": 1.30,
        "cl0": 0.38,
        "cd_min": 0.008,
        "alpha_stall": 12.0,
        "re_range": (70000, 400000),
        "use": "Планер, добро L/D",
        "geometry": {"thickness": 0.108, "camber": 0.036,
                     "camber_pos": 0.40, "reflex": 0.0},
        "has_coords": False,
    },
    "mh45": {
        "key": "mh45",
        "name": "MH 45 (reflex)",
        "code": None,
        "kind": "reflexed",
        "cl_max": 1.05,
        "cl0": 0.15,
        "cd_min": 0.008,
        "alpha_stall": 10.0,
        "re_range": (100000, 400000),
        "use": "Крило без опашка (flying wing) — самонастройващ се момент",
        "geometry": {"thickness": 0.095, "camber": 0.025,
                     "camber_pos": 0.35, "reflex": 0.55},
        "has_coords": False,
    },
}

DEFAULT_AIRFOIL = "naca2412"
DEFAULT_TAIL_AIRFOIL = "naca0009"

# Корекция на CL_max за ниски числа на Рейнолдс (емпирична)
RE_REF = 200000.0
RE_MIN = 50000.0
CLMAX_PENALTY_AT_RE_MIN = 0.88


# --------------------------------------------------------------------------
# NACA 4-цифрен генератор (NACA Report 824)
# --------------------------------------------------------------------------
def parse_naca(code):
    """'2412' -> (m=0.02, p=0.4, t=0.12)."""
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    if len(digits) != 4:
        raise ValueError("NACA кодът трябва да е 4 цифри, получено: %r" % (code,))
    m = int(digits[0]) / 100.0
    p = int(digits[1]) / 10.0
    t = int(digits[2:4]) / 100.0
    if m > 0 and p <= 0.0:
        p = 0.4
    return m, p, t


def naca_thickness(x, t, closed_te=True):
    """Полудебелина на NACA 4-цифрен профил."""
    a4 = -0.1036 if closed_te else -0.1015
    x = max(0.0, min(1.0, x))
    return 5.0 * t * (
        0.2969 * math.sqrt(x)
        - 0.1260 * x
        - 0.3516 * x ** 2
        + 0.2843 * x ** 3
        + a4 * x ** 4
    )


def naca_camber(x, m, p):
    """Средна линия на NACA 4-цифрен профил -> (yc, dyc/dx)."""
    if m <= 0.0 or p <= 0.0 or p >= 1.0:
        return 0.0, 0.0
    x = max(0.0, min(1.0, x))
    if x < p:
        yc = m / (p * p) * (2.0 * p * x - x * x)
        dy = 2.0 * m / (p * p) * (p - x)
    else:
        yc = m / ((1.0 - p) ** 2) * ((1.0 - 2.0 * p) + 2.0 * p * x - x * x)
        dy = 2.0 * m / ((1.0 - p) ** 2) * (p - x)
    return yc, dy


def naca_coordinates(code, n=61, closed_te=True):
    """
    Координати на NACA 4-цифрен профил (хорда = 1.0).

    Връща dict с upper (LE->TE), lower (LE->TE) и loop — затворен контур
    по посока на часовниковата стрелка, подходящ за лофт/триангулация.
    """
    m, p, t = parse_naca(code)
    n = max(11, int(n))
    xs = [0.5 * (1.0 - math.cos(math.pi * i / (n - 1))) for i in range(n)]
    upper, lower = [], []
    for x in xs:
        yt = naca_thickness(x, t, closed_te)
        yc, dy = naca_camber(x, m, p)
        theta = math.atan(dy)
        upper.append((x - yt * math.sin(theta), yc + yt * math.cos(theta)))
        lower.append((x + yt * math.sin(theta), yc - yt * math.cos(theta)))
    loop = upper + list(reversed(lower[1:-1]))
    return {"upper": upper, "lower": lower, "loop": loop}


def measured_thickness(code, n=201):
    """
    Измерена максимална дебелина (вертикална) и позицията ѝ по хордата.

    Връща (thickness_ratio, x_at_max) — използва се за проверки в тестовете
    и за геометричните изчисления (височина на спар).
    """
    _, _, t = parse_naca(code)
    n = max(21, int(n))
    best_d, best_x = 0.0, 0.3
    for i in range(n):
        x = 0.5 * (1.0 - math.cos(math.pi * i / (n - 1)))
        d = 2.0 * naca_thickness(x, t)
        if d > best_d:
            best_d, best_x = d, x
    return best_d, best_x


# --------------------------------------------------------------------------
# Помощни функции за приложението
# --------------------------------------------------------------------------
def get(key):
    """Данни за профил по ключ (fallback към DEFAULT_AIRFOIL)."""
    if key in AIRFOILS:
        return dict(AIRFOILS[key])
    return dict(AIRFOILS[DEFAULT_AIRFOIL])


def list_airfoils():
    """Списък за UI."""
    out = []
    for key, af in AIRFOILS.items():
        out.append({
            "key": key,
            "name": af["name"],
            "kind": af["kind"],
            "cl_max": af["cl_max"],
            "cd_min": af["cd_min"],
            "re_range": list(af["re_range"]),
            "use": af["use"],
            "has_coords": af["has_coords"],
        })
    return out


def clmax_at_re(cl_max, re):
    """
    CL_max, коригиран за числото на Рейнолдс.

    Под 200 000 Re подемната сила пада; при 50 000 достигаме ~88% от
    каталожната стойност (емпирична корекция, не CFD).
    """
    if re is None:
        return cl_max
    try:
        re = float(re)
    except (TypeError, ValueError):
        return cl_max
    if re >= RE_REF:
        return cl_max
    if re <= RE_MIN:
        return cl_max * CLMAX_PENALTY_AT_RE_MIN
    span = (re - RE_MIN) / (RE_REF - RE_MIN)
    factor = CLMAX_PENALTY_AT_RE_MIN + (1.0 - CLMAX_PENALTY_AT_RE_MIN) * span
    return cl_max * factor


def is_reflexed(key):
    """True, ако профилът е подходящ за крило без опашка."""
    return get(key).get("kind") == "reflexed"


def is_symmetric(key):
    return get(key).get("kind") == "symmetric"


def thickness_of(key, default=0.12):
    """
    Относителна дебелина на профила (t/c).

    За NACA се взема от кода; за каталожните — от полето geometry.
    """
    af = get(key)
    if af.get("code"):
        try:
            return parse_naca(af["code"])[2]
        except ValueError:
            return default
    geo = af.get("geometry") or {}
    return float(geo.get("thickness", default))


def approximate_coordinates(key, n=61):
    """
    Приблизителен контур за профили без вградени координати.

    Използва дебелината и камерата от каталога по формулите на NACA.
    Контурът е СХЕМАТИЧЕН (не е точната геометрия на профила) — служи
    само за визуализация; изчисленията ползват CL_max/CD_min от каталога.
    """
    af = get(key)
    if af.get("code"):
        coords = naca_coordinates(af["code"], n)
        coords["approximate"] = False
        return coords

    geo = af.get("geometry") or {}
    t = float(geo.get("thickness", 0.11))
    m = float(geo.get("camber", 0.03))
    p = float(geo.get("camber_pos", 0.4))
    reflex = float(geo.get("reflex", 0.0))
    p = min(0.9, max(0.05, p))

    n = max(11, int(n))
    xs = [0.5 * (1.0 - math.cos(math.pi * i / (n - 1))) for i in range(n)]
    upper, lower = [], []
    for x in xs:
        yt = naca_thickness(x, t)
        if m <= 0:
            yc, dy = 0.0, 0.0
        elif x < p:
            yc = m / (p * p) * (2.0 * p * x - x * x)
            dy = 2.0 * m / (p * p) * (p - x)
        else:
            yc = m / ((1.0 - p) ** 2) * ((1.0 - 2.0 * p) + 2.0 * p * x - x * x)
            dy = 2.0 * m / ((1.0 - p) ** 2) * (p - x)
        if reflex:
            # прибираме задния ръб надолу → самонастройващ се момент
            yc -= reflex * m * x * x
            dy -= 2.0 * reflex * m * x
        theta = math.atan(dy)
        upper.append((x - yt * math.sin(theta), yc + yt * math.cos(theta)))
        lower.append((x + yt * math.sin(theta), yc - yt * math.cos(theta)))
    return {
        "upper": upper,
        "lower": lower,
        "loop": upper + list(reversed(lower[1:-1])),
        "approximate": True,
    }


def coordinates_for(key, n=81):
    """
    Координати за визуализация по ключ на профил.

    Връща None, ако профилът не е известен.
    """
    if key not in AIRFOILS:
        return None
    return approximate_coordinates(key, n)


