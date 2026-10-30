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

OUTLINE_POINTS = 8      # точки по горна/долна повърхност на сечението
WING_STATIONS = 6       # сечения по полуразмаха
FUSELAGE_STATIONS = 12
FUSELAGE_RING = 10


def _outline(key):
    """
    Затворен контур на профила: горна повърхност LE→TE, после долна TE→LE.

    За профили без собствени координати се ползва приблизителният контур
    от airfoils (схематичен, но с правилната дебелина/камера).
    """
    coords = airfoils.coordinates_for(key, OUTLINE_POINTS + 1)
    if not coords:
        coords = airfoils.coordinates_for(airfoils.DEFAULT_AIRFOIL,
                                          OUTLINE_POINTS + 1)
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
             stations=WING_STATIONS, washout_deg=0.0):
    """
    Повърхност тип „крило“: лофт по размаха с трапецовиден хорд.

    origin      — точка на кореновия водещ ръб (x, y, z)
    span_axis   — посока на размаха (единичен вектор)
    thick_axis  — посока на дебелината (нормала на повърхността)
    """
    tris = []
    sides = (-1, 1) if two_sided else (1,)
    tan_dih = math.tan(math.radians(dihedral_deg))
    tan_sweep = math.tan(math.radians(sweep_deg))
    wash = math.radians(washout_deg)

    for side in sides:
        prev = None
        for i in range(stations + 1):
            f = i / stations
            s = side * f * half_span
            chord = c_root + (c_tip - c_root) * f
            rise = abs(s) * tan_dih
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
                # коренова "капачка" само при едностранна повърхност
                if not two_sided:
                    tris += _cap(section, reverse=(side < 0))
            prev = section
        if prev is not None:
            tris += _cap(prev, reverse=(side < 0))
    return tris


def _radius_factor(t):
    """Относителен радиус на фюзелажа по дължина (0 = нос, 1 = опашка)."""
    if t <= 0.0:
        return 0.05
    if t < 0.14:
        return 0.30 + 0.70 * math.sin((t / 0.14) * math.pi / 2.0)
    if t < 0.42:
        return 1.0
    u = (t - 0.42) / 0.58
    return 1.0 - 0.62 * (u ** 1.25)


def _fuselage(length, width, height, stations=FUSELAGE_STATIONS,
              ring=FUSELAGE_RING):
    """Фюзелаж: елиптични сечения по дължината + заоблен нос."""
    tris = []
    z_center = height * 0.5
    sections = []
    for i in range(stations + 1):
        t = 0.06 + 0.94 * i / stations
        rf = _radius_factor(t)
        x = t * length
        section = []
        for k in range(ring):
            ang = 2.0 * math.pi * k / ring
            section.append((
                x,
                (width * 0.5) * rf * math.cos(ang),
                z_center + (height * 0.5) * rf * math.sin(ang),
            ))
        sections.append(section)

    apex = (0.0, 0.0, z_center)
    first = sections[0]
    for i in range(len(first)):
        j = (i + 1) % len(first)
        tris.append((apex, first[i], first[j]))

    for i in range(len(sections) - 1):
        tris += _bridge(sections[i], sections[i + 1])
    tris += _cap(sections[-1])
    return tris


def _cylinder(x0, x1, radius, z_center, segments=10):
    """Къс цилиндър (мотор/спинер) по оста X."""
    ring0, ring1 = [], []
    for k in range(segments):
        ang = 2.0 * math.pi * k / segments
        y = radius * math.cos(ang)
        z = z_center + radius * math.sin(ang)
        ring0.append((x0, y, z))
        ring1.append((x1, y, z))
    tris = _bridge(ring0, ring1)
    tris += _cap(ring0, reverse=True)
    tris += _cap(ring1)
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


def build_model(res, max_triangles=6000):
    """
    Строи опростен 3D модел от резултата на design.compute().

    връща {"ok", "units", "size", "parts": [{name, color, points}], ...}
    „points“ е плосък списък x,y,z за всеки връх на всеки триъгълник.
    """
    if not res or not res.get("ok"):
        return {"ok": False, "error": "няма изчислен дизайн"}

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

    wingspan_ratio = span / max(1.0, length)
    # за много дълги фюзелажи (планер) крилото е по-ниско спрямо тялото
    z_wing = height * (0.92 if wingspan_ratio < 1.6 else 0.75)

    parts = []
    outline = _outline(airfoil_key)

    parts.append({
        "name": "Крило",
        "color": "#4db3e6",
        "tris": _surface(
            outline, span / 2.0, c_root, c_tip,
            (wing_le, 0.0, z_wing), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
            True, dihedral, 0.0, WING_STATIONS, -1.5),
    })

    parts.append({
        "name": "Фюзелаж",
        "color": "#cfd8e3",
        "tris": _fuselage(length, width, height),
    })

    tail = g["tail"]
    s_h_mm2 = float(tail.get("s_h_dm2") or 0.0) * 10000.0
    s_v_mm2 = float(tail.get("s_v_dm2") or 0.0) * 10000.0
    tail_outline = _outline(g.get("tail_airfoil")
                            or airfoils.DEFAULT_TAIL_AIRFOIL)
    tail_ac = float(tail.get("tail_ac_mm") or 0.0)
    if tail_ac <= 0.0:
        tail_ac = (wing_le + 0.25 * float(g["mac_mm"])
                   + float(tail.get("l_h_mm") or 0.0))

    if s_h_mm2 > 100.0:
        taper_h = aero.TAIL_TAPER_H
        c_h = float(tail.get("c_h_mm") or 0.0)
        if c_h <= 0:
            c_h = aero.tail_chord_m(s_h_mm2 / 1e6, aero.TAIL_AR_H,
                                    taper_h) * 1000.0
        b_h = 2.0 * s_h_mm2 / (c_h * (1.0 + taper_h)) if c_h > 0 else 0.0
        # AC на опашката е на 25% от хордата; използва се същото рамо,
        # с което е смятан статичният запас.
        x_h = max(wing_le + c_root, tail_ac - 0.25 * c_h)
        x_h = min(x_h, max(0.0, length - c_h))
        parts.append({
            "name": "Стабилизатор",
            "color": "#9fb0c6",
            "tris": _surface(
                tail_outline, b_h / 2.0, c_h, c_h * taper_h,
                (x_h, 0.0, height * 0.55), (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0), True, 0.0, 0.0, 4, 0.0),
        })

    if s_v_mm2 > 100.0:
        taper_v = aero.TAIL_TAPER_V
        c_v = float(tail.get("c_v_mm") or 0.0)
        if c_v <= 0:
            c_v = aero.tail_chord_m(s_v_mm2 / 1e6, aero.TAIL_AR_V,
                                    taper_v) * 1000.0
        b_v = 2.0 * s_v_mm2 / (c_v * (1.0 + taper_v)) if c_v > 0 else 0.0
        x_v = max(wing_le + c_root, tail_ac - 0.25 * c_v)
        x_v = min(x_v, max(0.0, length - c_v))
        parts.append({
            "name": "Кил",
            "color": "#8fa2ba",
            "tris": _surface(
                tail_outline, b_v, c_v, c_v * taper_v,
                (x_v, 0.0, height * 0.55), (0.0, 0.0, 1.0),
                (0.0, 1.0, 0.0), False, 0.0, 0.0, 4, 0.0),
        })

    parts.append({
        "name": "Мотор",
        "color": "#f0b24a",
        "tris": _cylinder(-0.02 * length, 0.035 * length,
                          min(width, height) * 0.22, height * 0.5, 10),
    })

    out_parts = []
    total = 0
    for part in parts:
        points = _pack(part["tris"])
        count = len(points) // 9
        if count == 0:
            continue
        if total + count > max_triangles:
            continue
        total += count
        out_parts.append({
            "name": part["name"],
            "color": part["color"],
            "triangles": count,
            "points": points,
        })

    # реален габарит на модела (за показване и за рамкиране в UI)
    xs, ys, zs = [], [], []
    for part in out_parts:
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
        size = {"length_mm": length, "span_mm": span, "height_mm": height}

    return {
        "ok": True,
        "units": "mm",
        "triangles": total,
        "parts": out_parts,
        "size": size,
        "info": {
            "airfoil": g["airfoil"]["name"],
            "aspect_ratio": round(float(g["aspect_ratio"]), 2),
            "has_tail": bool(res["mission"]["has_tail"]),
        },
    }


