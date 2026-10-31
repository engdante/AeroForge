"""
geometry3d.py — опростен 3D модел на проектирания самолет.

Целта е ВИЗУАЛИЗАЦИЯ на пропорциите (как би изглеждал моделът), а не
геометрия за печат: обшивката е една повърхност без дебелина, без ребра,
канали за тръби и т.н.

Координатна система (mm):
    X — по дължината на фюзелажа (0 = нос, +X към опашката)
    Y — по размаха (±), Z — нагоре (0 = земя)
"""

import math

from . import aero
from . import airfoils
from . import fairing as fairing_mod
from . import fuselage as fus_mod
from . import layout as layout_mod

OUTLINE_POINTS = 16     # точки по горна/долу повърхност на сечението (високо)
WING_STATIONS = 6       # сечения по полуразмаха (минимум)
FUSELAGE_STATIONS = 12
FUSELAGE_RING = 10

# Нивата на качеството живеят в quality.py (един източник за прегледа,
# CAD и STL); тук се внасят за съвместимост на старите извиквания.
from .quality import (QUALITY_LEVELS, QUALITY_ORDER, DEFAULT_QUALITY,  # noqa: E402,F401
                      quality_levels, quality_of, quality_spec)



def _outline(key, points=None):
    """
    Затворен контур на профила: горна повърхност LE→TE, после долна TE→LE.

    За профили без собствени координати се ползва приблизителният контур
    от airfoils (схематичен, но с правилната дебелина/камера).
    """
    n = max(4, int(points or OUTLINE_POINTS))
    coords = airfoils.coordinates_for(key, n + 1)
    if not coords:
        coords = airfoils.coordinates_for(airfoils.DEFAULT_AIRFOIL, n + 1)
    pts = [(float(x), float(y)) for x, y in coords["upper"]]
    pts += [(float(x), float(y)) for x, y in reversed(coords["lower"][1:-1])]
    return pts


def _bridge(section_a, section_b):
    """Свързва две еднакви по дължина сечения с лента от триъгълници."""
    tris = []
    n = len(section_a)
    for i in range(n):
        j = (i + 1) % n
        p0, p1 = section_a[i], section_a[j]
        p2, p3 = section_b[j], section_b[i]
        tris.append((p0, p1, p2))
        tris.append((p0, p2, p3))
    return tris


def _cap(section, reverse=False):
    """Затваря сечение с фен от центроида (работи за изпъкнали контури)."""
    n = len(section)
    if n < 3:
        return []
    cx = sum(p[0] for p in section) / n
    cy = sum(p[1] for p in section) / n
    cz = sum(p[2] for p in section) / n
    center = (cx, cy, cz)
    tris = []
    for i in range(n):
        j = (i + 1) % n
        if reverse:
            tris.append((center, section[j], section[i]))
        else:
            tris.append((center, section[i], section[j]))
    return tris


def _surface(outline, half_span, c_root, c_tip, origin, span_axis,
             thick_axis, two_sided=True, dihedral_deg=0.0, sweep_deg=0.0,
             stations=WING_STATIONS, washout_deg=0.0, chord_fn=None,
             upturn_deg=0.0, upturn_frac=0.0):
    """
    Повърхност тип „крило“: лофт по размаха с трапецовиден хорд.

    origin      — точка на кореновия водещ ръб (x, y, z)
    span_axis   — посока на размаха (единичен вектор)
    thick_axis  — посока на дебелината (нормала на повърхността)

    chord_fn    — функция f → хорд [mm] за нетрапецовидна планформа
                  (заоблен връх); при нея станциите се сгъстяват към върха
    upturn_deg  — ъгъл на извиване на върха нагоре („извит връх“)
    """
    tris = []
    sides = (-1, 1) if two_sided else (1,)
    tan_dih = math.tan(math.radians(dihedral_deg))
    tan_sweep = math.tan(math.radians(sweep_deg))
    wash = math.radians(washout_deg)
    tan_upturn = math.tan(math.radians(upturn_deg)) if upturn_deg else 0.0

    for side in sides:
        prev = None
        for i in range(stations + 1):
            u = i / stations
            # при заоблен връх станциите се сгъстяват там, където хордът
            # се променя най-бързо
            f = math.sin(0.5 * math.pi * u) if chord_fn is not None else u
            s = side * f * half_span
            chord = (chord_fn(f) if chord_fn is not None
                     else c_root + (c_tip - c_root) * f)
            rise = abs(s) * tan_dih
            if tan_upturn and upturn_frac > 0 and f > 1.0 - upturn_frac:
                bend = (f - (1.0 - upturn_frac)) / upturn_frac
                rise += bend * bend * half_span * upturn_frac * tan_upturn
            lead = abs(s) * tan_sweep
            twist = wash * f
            section = []
            for ox, oy in outline:
                # хорда по X с отчитане на усукването около водещия ръб
                cx = ox * chord
                cz = oy * chord
                rx = cx * math.cos(twist) - cz * math.sin(twist)
                rz = cx * math.sin(twist) + cz * math.cos(twist)
                depth_offset = rz + rise
                point = (
                    origin[0] + lead + rx,
                    origin[1] + span_axis[1] * s + thick_axis[1] * depth_offset,
                    origin[2] + span_axis[2] * s + thick_axis[2] * depth_offset,
                )
                section.append(point)
            if prev is not None:
                tris += _bridge(prev, section)
            else:
                # коренова капачка: коренът е затворен (обемът е валиден),
                # макар и скрит в тялото
                tris += _cap(section, reverse=(side > 0))
            prev = section
        if prev is not None:
            tris += _cap(prev, reverse=(side < 0))
    return tris


def _radius_factor(t, fus=None):
    """
    Относителен радиус на фюзелажа по дължина (0 = нос, 1 = опашка).

    Формата идва от fuselage.py, за да е еднаква с масата за печат и с
    бъдещия STL. Без `fus` се ползва формата по подразбиране.
    """
    if fus:
        return fus_mod.radius_factor(t, fus.get("nose_ratio", 0.14),
                                     fus.get("cabin_ratio", 0.42),
                                     fus.get("tail_taper", 0.38))
    return fus_mod.radius_factor(t)


def _fuselage(length, width, height, fus=None, stations=FUSELAGE_STATIONS,
              ring=FUSELAGE_RING):
    """
    Фюзелаж: сечения по дължината + заоблен нос.

    Контурът идва от fuselage.outline (суперелипса + нос/кабина/опашка),
    за да съвпада с CAD/STL модела, а станциите се сгъстяват към носа и
    опашката, където радиусът се променя най-бързо.
    """
    tris = []
    z_center = height * 0.5
    sections = []
    for i in range(stations + 1):
        u = i / stations
        # косинус + равномерно: гъсто към нос/опашка, но без „чупка“ в средата
        t = 0.02 + 0.98 * (0.45 * u
                           + 0.55 * 0.5 * (1.0 - math.cos(math.pi * u)))
        x = t * length
        if fus:
            pts = fus_mod.outline(fus, t, ring)
        else:
            rf = _radius_factor(t)
            pts = [(0.5 * width * rf * math.cos(2.0 * math.pi * k / ring),
                    0.5 * height * rf * math.sin(2.0 * math.pi * k / ring))
                   for k in range(ring)]
        sections.append([(x, y, z_center + z) for (y, z) in pts])

    apex = (0.0, 0.0, z_center)
    first = sections[0]
    for i in range(len(first)):
        j = (i + 1) % len(first)
        tris.append((apex, first[i], first[j]))

    for i in range(len(sections) - 1):
        tris += _bridge(sections[i], sections[i + 1])
    tris += _cap(sections[-1])
    return tris


def _cylinder(x0, x1, radius, z_center, segments=10, y_center=0.0):
    """Къс цилиндър (мотор/спинер) по оста X."""
    ring0, ring1 = [], []
    for k in range(segments):
        ang = 2.0 * math.pi * k / segments
        y = y_center + radius * math.cos(ang)
        z = z_center + radius * math.sin(ang)
        ring0.append((x0, y, z))
        ring1.append((x1, y, z))
    tris = _bridge(ring0, ring1)
    tris += _cap(ring0, reverse=True)
    tris += _cap(ring1)
    return tris


def _signed_volume(tris):
    """Ориентиран обем на затворена мрежа (за проверка на намотката)."""
    total = 0.0
    for (a, b, c) in tris:
        total += (a[0] * (b[1] * c[2] - b[2] * c[1])
                  - a[1] * (b[0] * c[2] - b[2] * c[0])
                  + a[2] * (b[0] * c[1] - b[1] * c[0]))
    return total / 6.0


def _orient(tris):
    """
    Обръща намотката, ако нормалите сочат навътре.

    Нужно е за backface culling в прегледа и за валиден STL/STEP: всички
    части трябва да имат еднаква посока на нормалите.
    """
    if _signed_volume(tris) < 0.0:
        return [(a, c, b) for (a, b, c) in tris]
    return tris


def _cone(x_tip, x_base, radius, z_center, segments=12):
    """Конус (спинер) по оста X: връх при x_tip, основа при x_base."""
    ring = []
    for k in range(segments):
        ang = 2.0 * math.pi * k / segments
        ring.append((x_base, radius * math.cos(ang),
                     z_center + radius * math.sin(ang)))
    apex = (x_tip, 0.0, z_center)
    tris = []
    for k in range(segments):
        j = (k + 1) % segments
        tris.append((apex, ring[j], ring[k]))
    tris += _cap(ring, reverse=False)
    return tris


def _spininner(params, segments=12):
    """
    Спинер + каулинг вместо гол цилиндър на мотора.

    Спинерът е конус пред носа, а каулингът (къс пресечен конус) свързва
    спинера с кожата на тялото — така носът няма „стърчащ цилиндър“ и
    преходът е плавен.  Параметрите идват от fairing.spinner_params.
    """
    z_center = params["z_center"]
    r_spin = params["radius"]
    tris = _cone(params["x_tip"], params["x_base"], r_spin, z_center, segments)

    ring0, ring1 = [], []
    for k in range(segments):
        ang = 2.0 * math.pi * k / segments
        ring0.append((params["x_cowl0"], r_spin * math.cos(ang),
                      z_center + r_spin * math.sin(ang)))
        ring1.append((params["x_cowl1"], params["r_cowl1"] * math.cos(ang),
                      z_center + params["r_cowl1"] * math.sin(ang)))
    tris += _bridge(ring0, ring1)
    tris += _cap(ring0, reverse=True)
    tris += _cap(ring1, reverse=False)
    return tris


def _pack(tris):
    """Превръща триъгълниците в плосък списък числа (1 знак)."""
    out = []
    for tri in tris:
        for point in tri:
            out.append(round(point[0], 1))
            out.append(round(point[1], 1))
            out.append(round(point[2], 1))
    return out


def _assemble(res, key):
    """
    Сглобява частите на модела при зададено ниво на качество `key`.

    Отделно от build_model, за да може бюджетът за триъгълници да се
    спазва чрез по-ниско ниво, а не чрез изхвърляне на цели части.
    """
    q = QUALITY_LEVELS[key]
    quality = key
    g = res["geometry"]
    fus = g["fuselage"]
    length = float(fus["length_mm"])
    width = float(fus["width_mm"])
    height = float(fus["height_mm"])
    span = float(g["span_mm"])
    c_root = float(g["c_root_mm"])
    c_tip = float(g["c_tip_mm"])
    wing_le = float(g["wing_le_mm"])
    dihedral = float(g["dihedral_deg"])
    airfoil_key = g["airfoil"]["key"]

    # Височината на крилото вече е отместване от средното положение
    # (layout.wing_offset_mm), а не скрит евристичен коефициент.
    z_wing = layout_mod.wing_z_from_result(res)

    parts = []
    outline = _outline(airfoil_key, q["outline"])

    tip_style = g.get("tip_style", "square")
    tip_frac = float(g.get("tip_frac") or 0.0)
    tip_min = float(g.get("tip_min_ratio") or 0.10)
    taper = float(g.get("taper") or 1.0)
    washout = float(g.get("washout_deg") or 0.0)
    dense = tip_style in ("rounded", "upturned", "winglet") and tip_frac > 0
    chord_fn = ((lambda f: aero.chord_at(f, c_root, taper, tip_style,
                                         tip_frac, tip_min))
                if dense else None)
    upturn = (float(aero.TIP_STYLES.get(tip_style, {}).get("upturn_deg", 0.0))
              if tip_style == "upturned" else 0.0)
    stations = max(q["wing"], 10) if dense else q["wing"]

    parts.append({
        "name": "Крило",
        "color": "#4db3e6",
        "tris": _surface(
            outline, span / 2.0, c_root, c_tip,
            (wing_le, 0.0, z_wing), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
            True, dihedral, 0.0, stations, washout, chord_fn,
            upturn, tip_frac if upturn else 0.0),
    })

    # Уинглет: вертикална (или наклонена) повърхност на върха.
    winglet = g.get("winglet") or {}
    if winglet.get("enabled") and float(winglet.get("height_mm") or 0.0) > 0:
        wl_chord = float(winglet.get("chord_mm") or 0.0)
        if wl_chord <= 0:
            wl_chord = 0.6 * c_root * taper
        cant = math.radians(min(90.0, max(45.0,
                                         float(winglet.get("cant_deg", 85.0)))))
        semi = span / 2.0
        z_tip = z_wing + semi * math.tan(math.radians(dihedral))
        for sign, name in ((1.0, "Уинглет (дясно)"),
                           (-1.0, "Уинглет (ляво)")):
            parts.append({
                "name": name,
                "color": "#3f9cc9",
                "tris": _surface(
                    outline, float(winglet["height_mm"]), wl_chord,
                    wl_chord * 0.5,
                    (wing_le, sign * semi, z_tip),
                    (0.0, sign * math.cos(cant), math.sin(cant)),
                    (0.0, -sign * math.sin(cant), math.cos(cant)),
                    False, 0.0, 0.0, 3, 0.0),
            })

    tail = g["tail"]
    s_h_mm2 = float(tail.get("s_h_dm2") or 0.0) * 10000.0
    s_v_mm2 = float(tail.get("s_v_dm2") or 0.0) * 10000.0
    tail_outline = _outline(g.get("tail_airfoil")
                            or airfoils.DEFAULT_TAIL_AIRFOIL, q["outline"])
    tail_ac = float(tail.get("tail_ac_mm") or 0.0)
    if tail_ac <= 0.0:
        tail_ac = (wing_le + 0.25 * float(g["mac_mm"])
                   + float(tail.get("l_h_mm") or 0.0))

    layout_info = res.get("layout") or {}
    tail_type = layout_info.get("tail_type", "conventional")
    z_tail = height * 0.55

    # Спинер + каулинг на носа (при теглещо витло)
    spinner = fairing_mod.spinner_params(res)

    parts.append({
        "name": "Фюзелаж",
        "color": "#cfd8e3",
        "tris": _fuselage(length, width, height, g.get("fuselage"),
                          q["stations"], q["ring"]),
    })

    # Хорди и размах на опашните повърхности (нужни и за T-, и за V-опашка)
    taper_h = aero.TAIL_TAPER_H
    c_h = float(tail.get("c_h_mm") or 0.0)
    if c_h <= 0 and s_h_mm2 > 0:
        c_h = aero.tail_chord_m(s_h_mm2 / 1e6, aero.TAIL_AR_H,
                                taper_h) * 1000.0
    b_h = (2.0 * s_h_mm2 / (c_h * (1.0 + taper_h))
           if c_h > 0 and s_h_mm2 > 0 else 0.0)

    taper_v = aero.TAIL_TAPER_V
    c_v = float(tail.get("c_v_mm") or 0.0)
    if c_v <= 0 and s_v_mm2 > 0:
        c_v = aero.tail_chord_m(s_v_mm2 / 1e6, aero.TAIL_AR_V,
                                taper_v) * 1000.0
    b_v = (2.0 * s_v_mm2 / (c_v * (1.0 + taper_v))
           if c_v > 0 and s_v_mm2 > 0 else 0.0)

    if tail_type == "v_tail" and (s_h_mm2 > 100.0 or s_v_mm2 > 100.0):
        # V-опашка: два панела под ъгъл; площта идва от layout.v_tail_panel
        v_info = (layout_info.get("v_tail") or {})
        panel_m2 = float(v_info.get("s_panel_m2") or 0.0)
        gamma = math.radians(float(layout_info.get("v_tail_deg", 35.0)))
        c_p = max(c_h, c_v)
        if panel_m2 > 0 and c_p > 0:
            b_panel = panel_m2 * 1e6 / (c_p * (1.0 + taper_v))
            x_v = max(wing_le + c_root, tail_ac - 0.25 * c_p)
            x_v = min(x_v, max(0.0, length - c_p))
            cos_g, sin_g = math.cos(gamma), math.sin(gamma)
            for name, sign in (("Стабилизатор (V)", 1.0),
                               ("Кил (V)", -1.0)):
                parts.append({
                    "name": name,
                    "color": "#9fb0c6" if sign > 0 else "#8fa2ba",
                    "tris": _surface(
                        tail_outline, b_panel, c_p, c_p * taper_v,
                        (x_v, 0.0, z_tail), (0.0, sign * cos_g, sin_g),
                        (0.0, -sign * sin_g, cos_g), False, 0.0, 0.0,
                        q["tail"], 0.0),
                })
    else:
        if s_h_mm2 > 100.0:
            # AC на опашката е на 25% от хордата; използва се същото рамо,
            # с което е смятан статичният запас.
            x_h = max(wing_le + c_root, tail_ac - 0.25 * c_h)
            x_h = min(x_h, max(0.0, length - c_h))
            z_h = z_tail + (b_v if tail_type == "t_tail" else 0.0)
            parts.append({
                "name": "Стабилизатор",
                "color": "#9fb0c6",
                "tris": _surface(
                    tail_outline, b_h / 2.0, c_h, c_h * taper_h,
                    (x_h, 0.0, z_h), (0.0, 1.0, 0.0),
                    (0.0, 0.0, 1.0), True, 0.0, 0.0, q["tail"], 0.0),
            })

        if s_v_mm2 > 100.0:
            x_v = max(wing_le + c_root, tail_ac - 0.25 * c_v)
            x_v = min(x_v, max(0.0, length - c_v))
            parts.append({
                "name": "Кил",
                "color": "#8fa2ba",
                "tris": _surface(
                    tail_outline, b_v, c_v, c_v * taper_v,
                    (x_v, 0.0, z_tail), (0.0, 0.0, 1.0),
                    (0.0, 1.0, 0.0), False, 0.0, 0.0, q["tail"], 0.0),
            })

    # Мотор(и): отпред (тягач), отзад (бутач) или два на крилото.
    motor_r = min(width, height) * 0.22
    segments = max(8, q["ring"] // 2)
    propulsion = layout_info.get("propulsion", "tractor")
    if propulsion == "pusher":
        parts.append({
            "name": "Мотор",
            "color": "#f0b24a",
            "tris": _cylinder(0.955 * length, 1.005 * length,
                              motor_r, height * 0.5, segments),
        })
    elif propulsion == "twin":
        x_m = wing_le + 0.25 * c_root
        y_m = 0.35 * span / 2.0
        for sign in (-1.0, 1.0):
            parts.append({
                "name": "Мотор" if sign < 0 else "Мотор (2)",
                "color": "#f0b24a",
                "tris": _cylinder(x_m - 0.03 * c_root, x_m + 0.04 * c_root,
                                  motor_r * 0.7,
                                  z_wing + 0.5 * motor_r * 0.7, segments,
                                  y_center=sign * y_m, ),
            })
    else:
        if spinner:
            parts.append({
                "name": "Мотор",
                "color": "#f0b24a",
                "tris": _spininner(spinner, segments),
            })
        else:
            parts.append({
                "name": "Мотор",
                "color": "#f0b24a",
                "tris": _cylinder(-0.02 * length, 0.035 * length,
                                  motor_r, height * 0.5, segments),
            })

    # Нормализиране: всяка част със затворен обем и еднаква посока на
    # нормалите (нужно за culling и за валиден STL/STEP).
    packed = []
    total = 0
    for part in parts:
        tris = _orient(part["tris"])
        points = _pack(tris)
        count = len(points) // 9
        if count == 0:
            continue
        total += count
        packed.append({
            "name": part["name"],
            "color": part["color"],
            "triangles": count,
            "points": points,
        })
    return packed, total


def build_model(res, max_triangles=None, quality=None):
    """
    Строи опростен 3D модел от резултата на design.compute().

    връща {"ok", "units", "size", "parts": [{name, color, points}], ...}
    „points“ е плосък списък x,y,z за всеки връх на всеки триъгълник.

    Плътността идва от `quality` (low/normal/high/ultra), а бюджетът — от
    самото ниво, освен ако не е зададен изрично.  Ако триъгълниците
    надхвърлят бюджета, плътността се понижава — моделът остава цял.
    """
    if not res or not res.get("ok"):
        return {"ok": False, "error": "няма изчислен дизайн"}

    level = quality_of(quality)
    budget = (int(max_triangles) if max_triangles
              else int(QUALITY_LEVELS[level]["max_tris"]))
    idx = QUALITY_ORDER.index(level)
    parts, total = [], 0
    used = level
    for key in reversed(QUALITY_ORDER[:idx + 1]):
        parts, total = _assemble(res, key)
        used = key
        if total <= budget or key == "low":
            break

    if total > budget:
        # дори най-ниската плътност не стига — оставяме частите по приоритет
        kept, running = [], 0
        for part in parts:
            if running + part["triangles"] <= budget:
                kept.append(part)
                running += part["triangles"]
        parts, total = kept, running

    g = res["geometry"]
    # реален габарит на модела (за показване и за рамкиране в UI)
    xs, ys, zs = [], [], []
    for part in parts:
        xs.extend(part["points"][0::3])
        ys.extend(part["points"][1::3])
        zs.extend(part["points"][2::3])
    if xs:
        size = {
            "length_mm": round(max(xs) - min(xs), 1),
            "span_mm": round(max(ys) - min(ys), 1),
            "height_mm": round(max(zs) - min(zs), 1),
        }
    else:
        size = {"length_mm": float(g.get("fuselage", {}).get("length_mm", 0.0)),
                "span_mm": float(g.get("span_mm", 0.0)),
                "height_mm": float(g.get("fuselage", {}).get("height_mm", 0.0))}

    return {
        "ok": True,
        "units": "mm",
        "triangles": total,
        "parts": parts,
        "size": size,
        "quality": used,
        "info": {
            "airfoil": g["airfoil"]["name"],
            "aspect_ratio": round(float(g["aspect_ratio"]), 2),
            "has_tail": bool(res["mission"]["has_tail"]),
        },
    }


