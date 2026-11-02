"""
fuselage.py — параметрична геометрия на фюзелажа.

Един източник на истина за формата на тялото. Използва се от:
  * design.py     — размерите влизат в опашката, ЦТ и проверките;
  * cg.py         — реален обхват, в който батерията се събира;
  * printcost.py  — мокро съпротивление (площ) за масата на печата;
  * geometry3d.py — 3D прегледът;
  * бъдещия printgeom.py (STL) — станциите и контурът на сечението.

Формата се описва с 4 числа (nose_ratio, cabin_ratio, tail_taper,
height_ratio) и едно сечение (суперелипса), а НЕ с таблица от станции.
Всички функции са чисти, в mm, без зависимости от UI.
"""

import math

from . import weight

# |y/a|^exp + |z/b|^exp = 1 → exp = 2 е елипса, по-голямо е „по-правоъгълно“
SHAPES = {
    "ellipse": {"label": "Елипса", "exp": 2.0},
    "round": {"label": "Кръгло (h = w)", "exp": 2.0},
    "boxy": {"label": "Правоъгълно", "exp": 3.4},
    "teardrop": {"label": "Капковидно", "exp": 1.4},
}

TAIL_BOOMS = {
    "printed": "Печатана опашна част",
    "carbon_tube": "Карбонова тръба (boom)",
}

# Стойности по подразбиране — възпроизвеждат формата от v0.2.
DEFAULT = {
    "length_mm": None,
    "length_ratio": None,
    "width_mm": None,
    "height_mm": None,
    "shape": "ellipse",
    "nose_ratio": 0.14,
    "cabin_ratio": 0.42,
    "tail_taper": 0.38,
    "height_ratio": 1.25,
    "tail_boom": "printed",
    "frames": 0,
}

NOSE_BASE = 0.30      # радиус в самото начало на носа
NOSE_TIP = 0.05       # радиус при t = 0 (затворен нос)
TAIL_EXP = 1.25       # степен на стесняването към опашката
BAY_CLEARANCE_MM = 4.0   # минимална хлабина около батерията (общо)
SAMPLE_POINTS = 32


def shape_exp(shape):
    """Показател на суперелипсата за избраното сечение."""
    key = str(shape or "ellipse").lower()
    return SHAPES.get(key, SHAPES["ellipse"])["exp"]


def list_shapes():
    """Каталог на сеченията за UI."""
    return [{"key": key, "label": value["label"], "exp": value["exp"]}
            for key, value in SHAPES.items()]


def list_booms():
    """Каталог на изпълнението на опашната част за UI."""
    return [{"key": key, "label": label}
            for key, label in TAIL_BOOMS.items()]


def radius_factor(t, nose_ratio=0.14, cabin_ratio=0.42, tail_taper=0.38):
    """
    Относителен радиус на тялото по дължината (0 = нос, 1 = опашка).

    Три участъка: заоблен нос (NOSE_BASE → 1), постоянна част
    (nose_ratio → cabin_ratio) и конус към tail_taper.
    """
    nose = max(0.02, float(nose_ratio))
    cabin = min(0.90, max(nose + 0.02, float(cabin_ratio)))
    taper = max(0.05, min(1.0, float(tail_taper)))
    t = float(t)

    if t <= 0.0:
        return NOSE_TIP
    if t < nose:
        u = t / nose
        return NOSE_BASE + (1.0 - NOSE_BASE) * math.sin(u * math.pi / 2.0)
    if t < cabin:
        return 1.0
    u = (t - cabin) / max(1e-6, 1.0 - cabin)
    return 1.0 - (1.0 - taper) * (u ** TAIL_EXP)


def section(fus, t):
    """Ширина и височина на сечението при t (mm)."""
    rf = radius_factor(t, fus["nose_ratio"], fus["cabin_ratio"],
                       fus["tail_taper"])
    return (float(fus["width_mm"]) * rf, float(fus["height_mm"]) * rf)


def _raw_outline(fus, t, count):
    """Контур по равни ъгли (суперелипса)."""
    w, h = section(fus, t)
    a = max(0.0, w / 2.0)
    b = max(0.0, h / 2.0)
    n = max(0.5, float(fus.get("exp", 2.0)))
    power = 2.0 / n
    pts = []
    count = max(8, int(count))
    for i in range(count):
        ang = 2.0 * math.pi * i / count
        c, s = math.cos(ang), math.sin(ang)
        y = a * math.copysign(abs(c) ** power, c)
        z = b * math.copysign(abs(s) ** power, s)
        pts.append((y, z))
    return pts


def outline(fus, t, points=SAMPLE_POINTS):
    """
    Затворен контур на сечението: [(y, z), ...] около центъра му.

    Суперелипса: y = a·sgn(cos)·|cos|^(2/n), z = b·sgn(sin)·|sin|^(2/n).
    При n = 2 това е точно елипса.

    Точките са по равни ъгли: за суперелипса това е и близо до оптималното
    по кривина (проверено — разпределение по дъга/кривина не намалява
    грешката), затова качеството се управлява само с брой точки.
    """
    return _raw_outline(fus, t, points)


def perimeter(fus, t, points=SAMPLE_POINTS):
    """Периметър на сечението при t (mm)."""
    pts = outline(fus, t, points)
    total = 0.0
    for i in range(len(pts)):
        y0, z0 = pts[i]
        y1, z1 = pts[(i + 1) % len(pts)]
        total += math.hypot(y1 - y0, z1 - z0)
    return total


def section_area(fus, t, points=SAMPLE_POINTS):
    """Площ на сечението при t (mm²) по формулата на шнура."""
    pts = outline(fus, t, points)
    acc = 0.0
    for i in range(len(pts)):
        y0, z0 = pts[i]
        y1, z1 = pts[(i + 1) % len(pts)]
        acc += y0 * z1 - y1 * z0
    return abs(acc) / 2.0


def _integrate(fus, fn, samples=24):
    """Интегрира функция на t по дължината (трапеци, равномерна мрежа)."""
    length = float(fus["length_mm"])
    if length <= 0:
        return 0.0
    n = max(4, int(samples))
    total = 0.0
    prev = fn(0.0)
    for i in range(1, n + 1):
        t = i / n
        cur = fn(t)
        total += 0.5 * (prev + cur) * (length / n)
        prev = cur
    return total


def wetted_area_mm2(fus):
    """Площ на обшивката (за маса на печата) [mm²]."""
    return _integrate(fus, lambda t: perimeter(fus, t))


def volume_cm3(fus):
    """Вътрешен обем на тялото [cm³]."""
    return _integrate(fus, lambda t: section_area(fus, t)) / 1000.0


def slenderness(fus):
    """Стройност L/√(w·h) — под 4 е „танк“, над 12 е трудно за печат."""
    w = max(1e-6, float(fus["width_mm"]))
    h = max(1e-6, float(fus["height_mm"]))
    return float(fus["length_mm"]) / math.sqrt(w * h)


def stations(fus, bed_z):
    """
    Станции за сегментиране по леглото (тялото се печата по Z).

    връща [{"i", "x0_mm", "x1_mm", "t0", "t1"}], всички части ≤ bed_z.
    """
    length = max(1.0, float(fus["length_mm"]))
    bed = max(1.0, float(bed_z))
    pieces = max(1, int(math.ceil(length / bed)))
    step = length / pieces
    out = []
    for i in range(pieces):
        x0 = i * step
        x1 = min(length, (i + 1) * step)
        out.append({
            "i": i + 1,
            "x0_mm": round(x0, 1),
            "x1_mm": round(x1, 1),
            "t0": round(x0 / length, 4),
            "t1": round(x1 / length, 4),
        })
    return out


def bay_limits(fus, battery_box_mm=None, clearance=BAY_CLEARANCE_MM,
               samples=400):
    """
    Обхват за ЦЕНТЪРА на батерията, в който тя се събира по сечение.

    Връща (x0_mm, x1_mm) или None, ако никъде няма място. Обхватът вече е
    скъсен с половин дължина на батерията, за да не стърчи от носа/опашката.
    """
    if not battery_box_mm:
        return None
    try:
        bat_l, bat_w, bat_h = [float(v) for v in battery_box_mm[:3]]
    except (TypeError, ValueError):
        return None
    length = float(fus["length_mm"])
    if length <= 0:
        return None
    need_w = bat_w + max(0.0, float(clearance))
    need_h = bat_h + max(0.0, float(clearance))

    first = None
    last = None
    n = max(50, int(samples))
    for i in range(n + 1):
        t = i / n
        w, h = section(fus, t)
        if w + 1e-6 >= need_w and h + 1e-6 >= need_h:
            x = t * length
            if first is None:
                first = x
            last = x
    if first is None or last is None:
        return None
    half = bat_l / 2.0
    x0 = first + half
    x1 = last - half
    if x1 - x0 < 1.0:
        # батерията е по-дълга от наличния участък — връщаме центъра му
        mid = 0.5 * (first + last)
        return (round(mid, 1), round(mid, 1))
    return (round(x0, 1), round(x1, 1))


def resolve(span_mm, mass_kg, battery_volume_cm3, params=None,
            default_ratio=0.75):
    """
    Пълно разрешаване на размерите и формата на тялото.

    params идват от UI (design.normalize); None = „авто“ по мисията,
    батерията и масата. Така без зададени стойности резултатът е същият
    като във v0.2.
    """
    p = dict(DEFAULT)
    for key, value in (params or {}).items():
        if value is not None:
            p[key] = value

    ratio = p["length_ratio"] if p["length_ratio"] else default_ratio
    ratio = max(0.25, min(1.6, float(ratio)))
    base_len = max(120.0, float(span_mm) * ratio)

    # Минималните размери (батерия + достъп) идват от изпитаната функция.
    auto = weight.fuselage_dimensions(battery_volume_cm3, mass_kg, base_len)
    bat_l, bat_w, bat_h = auto["battery_box_mm"]

    length = float(p["length_mm"]) if p["length_mm"] else base_len
    length = max(120.0, min(4000.0, length))

    width = float(p["width_mm"]) if p["width_mm"] else auto["width_mm"]
    width = max(20.0, min(600.0, width))

    height_ratio = p["height_ratio"] if p["height_ratio"] else 1.25
    height_ratio = max(0.75, min(1.8, float(height_ratio)))
    height = float(p["height_mm"]) if p["height_mm"] else max(
        bat_h + 12.0, height_ratio * width)
    height = max(20.0, min(600.0, height))

    nose = p["nose_ratio"] if p["nose_ratio"] is not None else 0.14
    cabin = p["cabin_ratio"] if p["cabin_ratio"] is not None else 0.42
    taper = p["tail_taper"] if p["tail_taper"] is not None else 0.38
    nose = max(0.04, min(0.35, float(nose)))
    cabin = max(nose + 0.02, min(0.90, float(cabin)))
    taper = max(0.05, min(0.95, float(taper)))

    shape = str(p["shape"] or "ellipse").lower()
    if shape not in SHAPES:
        shape = "ellipse"
    boom = str(p["tail_boom"] or "printed").lower()
    if boom not in TAIL_BOOMS:
        boom = "printed"
    frames = int(max(0, min(12, float(p["frames"] or 0))))

    fus = {
        "length_mm": round(length, 1),
        "width_mm": round(width, 1),
        "height_mm": round(height, 1),
        "shape": shape,
        "exp": shape_exp(shape),
        "nose_ratio": round(nose, 4),
        "cabin_ratio": round(cabin, 4),
        "tail_taper": round(taper, 4),
        "height_ratio": round(height_ratio, 4),
        "tail_boom": boom,
        "frames": frames,
        "battery_box_mm": [round(bat_l, 1), round(bat_w, 1), round(bat_h, 1)],
        "battery_fits": bool((bat_l + 0.1 * length) <= length),
        "auto": {
            "length_mm": round(base_len, 1),
            "width_mm": round(auto["width_mm"], 1),
            "height_mm": round(auto["height_mm"], 1),
            "length_ratio": round(ratio, 3),
        },
        "manual": {
            "length": bool(p["length_mm"]),
            "width": bool(p["width_mm"]),
            "height": bool(p["height_mm"]),
        },
    }
    fus["battery_bay_mm"] = bay_limits(fus, fus["battery_box_mm"])
    fus["wetted_area_mm2"] = wetted_area_mm2(fus)
    fus["volume_cm3"] = volume_cm3(fus)
    fus["slenderness"] = slenderness(fus)
    return fus
