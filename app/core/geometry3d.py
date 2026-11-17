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
from . import assembly
from . import airfoils
from . import fairing as fairing_mod
from . import fuselage as fus_mod
from . import layout as layout_mod
from . import motor as motor_mod
from . import printgeom

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


def _clip_outline(outline, u_min, u_max):
    """
    Частта от затворения контур на профила с u_min ≤ x ≤ u_max
    (Sutherland–Hodgman по двете вертикални прави). Ползва се за крилото
    пред пантата и за елерона зад нея; срезът е права стена.
    """
    def clip(points, keep, cross):
        out = []
        n = len(points)
        for i in range(n):
            cur, nxt = points[i], points[(i + 1) % n]
            cur_in, nxt_in = keep(cur), keep(nxt)
            if cur_in:
                out.append(cur)
            if cur_in != nxt_in:
                out.append(cross(cur, nxt))
        return out

    def at_x(x0):
        def cross(a, b):
            t = (x0 - a[0]) / ((b[0] - a[0]) or 1e-12)
            return (x0, a[1] + t * (b[1] - a[1]))
        return cross

    pts = list(outline)
    if u_min > -1e-9:
        pts = clip(pts, lambda p: p[0] >= u_min, at_x(u_min))
    if u_max < 1.0 + 1e-9 and pts:
        pts = clip(pts, lambda p: p[0] <= u_max, at_x(u_max))
    # без повторени съседни точки (дават изродени триъгълници)
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
            out.append(p)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-9 \
            and abs(out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    return out


def _surface(outline, half_span, c_root, c_tip, origin, span_axis,
             thick_axis, two_sided=True, dihedral_deg=0.0, sweep_deg=0.0,
             stations=WING_STATIONS, washout_deg=0.0, chord_fn=None,
             upturn_deg=0.0, upturn_frac=0.0, root_gap_mm=0.0,
             f_range=None):
    """
    Повърхност тип „крило“: лофт по размаха с трапецовиден хорд.

    origin      — точка на кореновия водещ ръб (x, y, z)
    span_axis   — посока на размаха (единичен вектор)
    thick_axis  — посока на дебелината (нормала на повърхността)

    chord_fn    — функция f → хорд [mm] за нетрапецовидна планформа
                  (заоблен връх); при нея станциите се сгъстяват към върха
    upturn_deg  — ъгъл на извиване на върха нагоре („извит връх“)
    f_range     — (f0, f1): само участък от размаха (за крилото около
                  елерона); всяко парче е затворено в двата края
    """
    tris = []
    sides = (-1, 1) if two_sided else (1,)
    root_gap = min(max(0.0, float(root_gap_mm)), half_span)
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
            if f_range is None:
                f = math.sin(0.5 * math.pi * u) if chord_fn is not None else u
            else:
                f0, f1 = f_range
                g = (math.sin(0.5 * math.pi * u)
                     if chord_fn is not None and f1 >= 1.0 else u)
                f = f0 + (f1 - f0) * g
            s = side * (root_gap + f * (half_span - root_gap))
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


def _tube(p0, p1, radius, segments=16):
    """Затворен цилиндър от p0 до p1 (произволна ос) — за джойнера."""
    ax = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    length = math.sqrt(ax[0] ** 2 + ax[1] ** 2 + ax[2] ** 2)
    if length <= 1e-9 or radius <= 0:
        return []
    a = (ax[0] / length, ax[1] / length, ax[2] / length)
    # два перпендикуляра на оста
    ref = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 0.0, 1.0)
    e1 = (a[1] * ref[2] - a[2] * ref[1], a[2] * ref[0] - a[0] * ref[2],
          a[0] * ref[1] - a[1] * ref[0])
    n1 = math.sqrt(sum(c * c for c in e1)) or 1.0
    e1 = tuple(c / n1 for c in e1)
    e2 = (a[1] * e1[2] - a[2] * e1[1], a[2] * e1[0] - a[0] * e1[2],
          a[0] * e1[1] - a[1] * e1[0])
    rings = []
    for base in (p0, p1):
        ring = []
        for i in range(segments):
            t = 2.0 * math.pi * i / segments
            c, s = math.cos(t) * radius, math.sin(t) * radius
            ring.append((base[0] + e1[0] * c + e2[0] * s,
                         base[1] + e1[1] * c + e2[1] * s,
                         base[2] + e1[2] * c + e2[2] * s))
        rings.append(ring)
    return (_bridge(rings[0], rings[1]) + _cap(rings[0], reverse=True)
            + _cap(rings[1]))


def _wing_strip(rect_fn, half_span, c_root, c_tip, origin, dihedral_deg,
                washout_deg, f_end, root_gap_mm=0.0, chord_fn=None,
                stations=6):
    """
    Вътрешна лента по размаха на крилото (капс на спара, карбон).

    `rect_fn(chord)` дава затворен контур [(x, z)] в mm в равнината на
    сечението (x от водещия ръб, z нагоре). Станциите и преобразуването
    са същите като на `_surface`, за да лежи лентата точно в крилото.
    """
    tris = []
    root_gap = min(max(0.0, float(root_gap_mm)), half_span)
    tan_dih = math.tan(math.radians(dihedral_deg))
    wash = math.radians(washout_deg)
    for side in (-1, 1):
        prev = None
        for i in range(stations + 1):
            f = f_end * i / stations
            s = side * (root_gap + f * (half_span - root_gap))
            chord = (chord_fn(f) if chord_fn is not None
                     else c_root + (c_tip - c_root) * f)
            twist = wash * f
            rise = abs(s) * tan_dih
            section = []
            for cx, cz in rect_fn(chord):
                rx = cx * math.cos(twist) - cz * math.sin(twist)
                rz = cx * math.sin(twist) + cz * math.cos(twist)
                section.append((origin[0] + rx, origin[1] + s,
                                origin[2] + rz + rise))
            if prev is None:
                tris += _cap(section, reverse=(side > 0))
            else:
                tris += _bridge(prev, section)
            prev = section
        tris += _cap(prev, reverse=(side < 0))
    return tris


def _signed_volume(tris):
    """Ориентиран обем на затворена мрежа (за проверка на намотката)."""
    total = 0.0
    if not tris:
        return 0.0
    # Use a nearby origin to avoid catastrophic cancellation for small parts
    # located far along X (notably root-gap connector lofts).
    origin = tris[0][0]
    for (a, b, c) in tris:
        ax, ay, az = (a[i] - origin[i] for i in range(3))
        bx, by, bz = (b[i] - origin[i] for i in range(3))
        cx, cy, cz = (c[i] - origin[i] for i in range(3))
        total += (ax * (by * cz - bz * cy)
                  - ay * (bx * cz - bz * cx)
                  + az * (bx * cy - by * cx))
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


MOTOR_COLOR = "#9aa4b1"
PROP_COLOR = "#5b6675"


def _motor_parts(res, segments=16):
    """Камбана + вал + стойка на мотора и двулопатно витло (за всеки мотор)."""
    lay = motor_mod.layout(res)
    if not lay:
        return []
    cls, prop = lay["motor"], lay["prop"]
    out = []
    many = len(lay["units"]) > 1
    for i, unit in enumerate(lay["units"]):
        y, z = unit["y"], unit["z"]

        def axis(x):
            return (x, y, z)

        motor = _orient(_tube(axis(unit["x_can0"]), axis(unit["x_can1"]),
                              0.5 * cls["can_d"], segments))
        motor += _orient(_tube(axis(unit["x_can0"]), axis(unit["x_shaft_end"]),
                               0.5 * cls["shaft_d"], 8))
        if unit.get("x_mount") is not None and                 abs(unit["x_mount"] - unit["x_can1"]) > 0.5:
            motor += _orient(_tube(axis(unit["x_can1"]), axis(unit["x_mount"]),
                                   0.5 * cls["mount"][1] + 3.0, segments))
        suffix = " (%d)" % (i + 1) if many and i else ""
        out.append({"name": "Мотор" + suffix, "color": MOTOR_COLOR,
                    # теглещият е в каулинга — вижда се в „Вътрешност“
                    "layer": "internal" if lay["propulsion"] == "tractor"
                    else "solid", "tris": motor})

        blades = _orient(_tube(axis(unit["x_prop"] - 0.5 * prop["hub_t_mm"]),
                               axis(unit["x_prop"] + 0.5 * prop["hub_t_mm"]),
                               0.5 * prop["hub_d_mm"], segments))
        sections = motor_mod.blade_sections(prop)
        for blade in (0, 1):
            rings = [[motor_mod.blade_point(unit, blade, r, a, b) for a, b in pts]
                     for r, pts in sections]
            shell = []
            for ra, rb in zip(rings, rings[1:]):
                shell += _bridge(ra, rb)
            shell += _cap(rings[0], reverse=True) + _cap(rings[-1])
            blades += _orient(shell)
        out.append({"name": "Витло" + suffix, "color": PROP_COLOR,
                    "tris": blades})
    return out


def _pack(tris):
    """Превръща триъгълниците в плосък списък числа (1 знак)."""
    out = []
    for tri in tris:
        for point in tri:
            out.append(round(point[0], 1))
            out.append(round(point[1], 1))
            out.append(round(point[2], 1))
    return out


AILERON_MIN_F = 0.02          # елеронът не стига до самия корен/връх
# по-светли от реалните, за да се отличават от обшивката в „Вътрешност“
TUBE_COLORS = {"carbon": "#9fb0c6", "aluminium": "#dfe6ee",
               "fibreglass": "#d9cf9a", "steel": "#8d98a5"}
SPAR_CAP_COLOR = "#f0a64a"
CARBON_STRIP_COLOR = "#2a2f36"


def _aileron_layout(ail, half_span, wing_root, c_root, c_tip):
    """
    Елеронът в параметрите на `_surface` (f по размаха, u по хордата).

    `_surface` мери f от корена на половината (след луфта към тялото), а
    geometry.ailerons — от оста; тук се превръща едното в другото.
    """
    if not ail or not ail.get("enabled"):
        return None
    denom = half_span - wing_root
    if denom <= 1.0:
        return None
    fa = (float(ail.get("y_start_mm") or 0.0) - wing_root) / denom
    fb = (float(ail.get("y_end_mm") or 0.0) - wing_root) / denom
    fa = max(AILERON_MIN_F, fa)
    fb = min(1.0 - AILERON_MIN_F, fb)
    if fb - fa < 0.05:
        return None
    mean_chord = max(1.0, 0.5 * (c_root + c_tip))
    end_gap_f = float(ail.get("end_gap_mm") or 0.0) / denom
    if fb - fa - 2.0 * end_gap_f < 0.03:
        end_gap_f = 0.0
    return {
        "kind": ail.get("kind", "aileron"),
        "f_start": fa,
        "f_end": fb,
        "hinge_u": 1.0 - float(ail.get("chord_frac") or 0.2),
        "gap_u": float(ail.get("hinge_gap_mm") or 0.0) / mean_chord,
        "end_gap_f": end_gap_f,
    }


CONTROL_COLOR = "#6f86a3"     # кормилата на опашката (по-тъмни от нея)


def _control_layout(ctrl, s0, s1, half_span, root, c_root, c_tip):
    """
    Кормило в параметрите на `_surface`: s0/s1 са абсолютни станции по
    размаха (от оста / от корена на кила), `root` — откъдето започва
    повърхността. None, ако няма кормило или е твърде късо.
    """
    if not ctrl or not ctrl.get("enabled"):
        return None
    denom = half_span - root
    if denom <= 1.0:
        return None
    fa = max(0.0, (s0 - root) / denom)
    fb = min(1.0, (s1 - root) / denom)
    if fb - fa < 0.08:
        return None
    mean_chord = max(1.0, 0.5 * (c_root + c_tip))
    end_gap_f = float(ctrl.get("end_gap_mm") or 0.0) / denom
    if fb - fa - 2.0 * end_gap_f < 0.05:
        end_gap_f = 0.0
    return {
        "f_start": fa, "f_end": fb,
        "hinge_u": 1.0 - float(ctrl.get("chord_frac") or 0.3),
        "gap_u": float(ctrl.get("hinge_gap_mm") or 0.0) / mean_chord,
        "end_gap_f": end_gap_f,
    }


def _surface_split(outline, layout, stations, **kw):
    """
    Повърхност, разделена на неподвижна част и кормило зад пантата.

    `kw` са аргументите на `_surface` (без контур, станции и f_range).
    Връща (неподвижни триъгълници, триъгълници на кормилото).
    """
    if layout is None:
        return _surface(outline, stations=stations, **kw), []
    fa, fb = layout["f_start"], layout["f_end"]
    front = _clip_outline(outline, -1.0, layout["hinge_u"])
    rear = _clip_outline(outline, layout["hinge_u"] + layout["gap_u"], 2.0)
    fixed = []
    if fa > 0.005:
        fixed += _surface(outline, stations=max(2, int(round(stations * fa)) + 1),
                          f_range=(0.0, fa), **kw)
    fixed += _surface(front, stations=max(2, int(round(stations * (fb - fa))) + 1),
                      f_range=(fa, fb), **kw)
    if fb < 0.995:
        fixed += _surface(outline,
                          stations=max(2, int(round(stations * (1.0 - fb))) + 1),
                          f_range=(fb, 1.0), **kw)
    moving = []
    eg = layout["end_gap_f"]
    if len(rear) >= 3 and fb - fa - 2 * eg > 0.02:
        moving = _surface(rear, stations=max(2, int(round(stations * (fb - fa))) + 1),
                          f_range=(fa + eg, fb - eg), **kw)
    return fixed, moving


def _structure_parts(res, half_span, c_root, c_tip, wing_le, z_wing,
                     dihedral, washout, wing_root, chord_fn, tip_style,
                     tip_frac, q):
    """
    Спаровите капси, лентата (карбон) и джойнерът като части на прегледа.

    Размерите идват от printgeom.spar_section — същите като в схемата
    „Конструкция“ и в печатната геометрия.
    """
    view = printgeom.spar_section(res)
    if not view or c_root <= 0:
        return []
    parts = []
    cap = view["cap"]
    wall = float(view.get("wall_mm") or 0.45)
    cap_t = float(cap["thickness_mm"])
    x_frac = float(cap["x_mm"]) / c_root
    top_frac = float(cap["y_top_mm"]) / c_root
    bot_frac = float(cap["y_bottom_mm"]) / c_root
    cap_w = float(cap["width_mm"])
    strip_w = float(cap["strip_width_mm"])
    dense = tip_style in ("rounded", "upturned", "winglet") and tip_frac > 0
    f_end = min(0.97, 1.0 - tip_frac - 0.03) if dense else 0.97
    n = max(3, int(q["wing"]))

    def ranges(chord):
        x0 = x_frac * chord - cap_w / 2.0
        if cap["strips"] == 2:
            return [(x0, x0 + strip_w), (x0 + cap_w - strip_w, x0 + cap_w)]
        return [(x0, x0 + cap_w)]

    def rect(xa, xb, ya, yb):
        return [(xa, ya), (xb, ya), (xb, yb), (xa, yb)]

    def strip(rect_fn):
        return _wing_strip(rect_fn, half_span, c_root, c_tip,
                           (wing_le, 0.0, z_wing), dihedral, washout, f_end,
                           wing_root, chord_fn, n)

    cap_tris = []
    for idx in range(int(cap["strips"])):
        # горен капс: под обшивката надолу; долен: над обшивката нагоре
        cap_tris += strip(lambda c, i=idx: rect(
            ranges(c)[i][0], ranges(c)[i][1],
            top_frac * c - wall - cap_t, top_frac * c - wall))
        cap_tris += strip(lambda c, i=idx: rect(
            ranges(c)[i][0], ranges(c)[i][1],
            bot_frac * c + wall, bot_frac * c + wall + cap_t))
    parts.append({"name": "Спар (печатани капси)", "color": SPAR_CAP_COLOR,
                  "layer": "internal", "tris": cap_tris})

    carbon = view.get("carbon") or {}
    if carbon.get("needed") and carbon.get("width_mm"):
        cw = float(carbon["width_mm"])
        ct = float(carbon.get("thickness_mm") or 0.5) * int(carbon.get("count") or 1)
        tris = strip(lambda c: rect(x_frac * c - cw / 2.0, x_frac * c + cw / 2.0,
                                    top_frac * c - wall - ct, top_frac * c - wall))
        tris += strip(lambda c: rect(x_frac * c - cw / 2.0, x_frac * c + cw / 2.0,
                                     bot_frac * c + wall, bot_frac * c + wall + ct))
        parts.append({"name": "Лента на спара", "color": CARBON_STRIP_COLOR,
                      "layer": "internal", "tris": tris})

    j = view.get("joiner")
    if j and j.get("length_mm") and j.get("od_mm"):
        half_len = float(j["length_mm"]) / 2.0
        x = wing_le + float(j["x_mm"])
        z = z_wing + float(j["y_mm"])
        rise = half_len * math.tan(math.radians(dihedral))
        segments = max(12, int(q["ring"]))
        tris = []
        # по една половина във всяко полукрило — следва диедъра
        for sign in (1.0, -1.0):
            tris += _tube((x, 0.0, z), (x, sign * half_len, z + rise),
                          float(j["od_mm"]) / 2.0, segments)
        parts.append({"name": "Джойнер",
                      "color": TUBE_COLORS.get(j.get("material"), "#9fb0c6"),
                      "layer": "internal", "tris": tris})
    return parts


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
    layout_info = res.get("layout") or {}
    # Отделни луфтове за крило и опашка (обратна съвместимост с root_gap_mm)
    wing_root_gap = max(0.0, min(40.0, float(
        layout_info.get("wing_root_gap_mm",
                          layout_info.get("root_gap_mm", 10.0)) or 0.0)))
    tail_root_gap = max(0.0, min(40.0, float(
        layout_info.get("tail_root_gap_mm",
                          layout_info.get("root_gap_mm", 10.0)) or 0.0)))

    parts = []
    outline = _outline(airfoil_key, q["outline"])

    # Локална полуширина на обшивката в станцията на крилото (не максималната):
    # така превюто и CAD експортът мерят луфта от едно и също място.
    wing_skin = assembly.skin_offset(fus, wing_le, (0.0, 1.0, 0.0))
    wing_root = wing_skin + wing_root_gap if wing_root_gap > 0 else 0.0

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

    half_span = span / 2.0

    def wing_piece(piece_outline, f_range=None, n=stations):
        return _surface(
            piece_outline, half_span, c_root, c_tip,
            (wing_le, 0.0, z_wing), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
            True, dihedral, 0.0, n, washout, chord_fn,
            upturn, tip_frac if upturn else 0.0,
            root_gap_mm=wing_root, f_range=f_range)

    ail = _aileron_layout(g.get("ailerons") or {}, half_span, wing_root,
                          c_root, c_tip)
    if ail is None:
        parts.append({"name": "Крило", "color": "#4db3e6", "layer": "skin",
                      "tris": wing_piece(outline)})
    else:
        # крилото е на три парчета: до елерона, над елерона (само пред
        # пантата) и след него; елеронът е отделна част зад пантата
        fa, fb = ail["f_start"], ail["f_end"]
        front = _clip_outline(outline, -1.0, ail["hinge_u"])
        rear = _clip_outline(outline, ail["hinge_u"] + ail["gap_u"], 2.0)
        n_in = max(2, int(round(stations * fa)) + 1)
        n_mid = max(2, int(round(stations * (fb - fa))) + 1)
        n_out = max(2, int(round(stations * (1.0 - fb))) + 1)
        tris = (wing_piece(outline, (0.0, fa), n_in)
                + wing_piece(front, (fa, fb), n_mid)
                + wing_piece(outline, (fb, 1.0), n_out))
        parts.append({"name": "Крило", "color": "#4db3e6", "layer": "skin",
                      "tris": tris})
        if len(rear) >= 3:
            parts.append({
                "name": "Елерони" if ail["kind"] == "aileron" else "Елевони",
                "color": "#1f7fb8", "layer": "skin",
                "tris": wing_piece(rear, (fa + ail["end_gap_f"],
                                          fb - ail["end_gap_f"]), n_mid)})

    # Спар и джойнер — вътрешни части (виждат се в режим „Вътрешност“)
    parts += _structure_parts(res, half_span, c_root, c_tip, wing_le,
                              z_wing, dihedral, washout, wing_root,
                              chord_fn, tip_style, tip_frac, q)

    if wing_root_gap > 0.0:
        bridge_tris = []
        for sign in (1.0, -1.0):
            rings = []
            for distance in (wing_skin - 3.0, wing_skin + wing_root_gap + 3.0):
                ring = []
                y = sign * distance
                for u, v in outline:
                    ring.append((wing_le + u * c_root,
                                 y,
                                 z_wing + v * c_root))
                # огледалната страна изисква обърната намотка, за да сочат
                # нормалите навън (иначе обемът ѝ е отрицателен)
                if sign < 0.0:
                    ring.reverse()
                rings.append(ring)
            bridge_tris.extend(_bridge(rings[0], rings[1]))
            bridge_tris.extend(_cap(rings[0], reverse=True))
            bridge_tris.extend(_cap(rings[1]))
        parts.append({"name": "Връзки корен крило", "color": "#e0a85c",
                      "layer": "skin", "tris": bridge_tris})

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
    tail_key = g.get("tail_airfoil") or airfoils.DEFAULT_TAIL_AIRFOIL
    tail_outline = _outline(tail_key, q["outline"])
    # килът — със симетричен профил, независимо от профила на опашката
    fin_outline = _outline(g.get("fin_airfoil")
                           or airfoils.fin_airfoil(tail_key), q["outline"])
    tail_ac = float(tail.get("tail_ac_mm") or 0.0)
    if tail_ac <= 0.0:
        tail_ac = (wing_le + 0.25 * float(g["mac_mm"])
                   + float(tail.get("l_h_mm") or 0.0))

    tail_type = layout_info.get("tail_type", "conventional")
    tail_ctrl = g.get("tail_controls") or {}
    fin_key = g.get("fin_airfoil") or airfoils.fin_airfoil(tail_key)
    stab_top = stab_bottom = -1e9
    tail_gap = tail_root_gap
    z_center = height / 2.0
    z_tail = height * 0.55

    # Спинер + каулинг на носа (при теглещо витло)
    spinner = fairing_mod.spinner_params(res)

    parts.append({
        "name": "Фюзелаж",
        "color": "#cfd8e3",
        "layer": "skin",
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
            # Коренът на панела стъпва на обшивката по оста на панела и
            # после се отмества с луфта — същото като в CAD експорта.
            v_skin = assembly.skin_offset(fus, x_v, (0.0, cos_g, sin_g))
            root_off = v_skin + tail_gap
            el_ctrl = tail_ctrl.get("elevator") or {}
            v_layout = _control_layout(
                el_ctrl, el_ctrl.get("root_clear_mm", 2.0),
                b_panel * (1.0 - el_ctrl.get("tip_margin_frac", 0.03)),
                b_panel, 0.0, c_p, c_p * taper_v)
            for name, sign in (("Стабилизатор (V)", 1.0),
                               ("Кил (V)", -1.0)):
                fixed, moving = _surface_split(
                    tail_outline, v_layout, max(q["tail"], 8),
                    half_span=b_panel, c_root=c_p, c_tip=c_p * taper_v,
                    origin=(x_v, sign * root_off * cos_g,
                            z_center + root_off * sin_g),
                    span_axis=(0.0, sign * cos_g, sin_g),
                    thick_axis=(0.0, -sign * sin_g, cos_g), two_sided=False)
                parts.append({
                    "name": name,
                    "color": "#9fb0c6" if sign > 0 else "#8fa2ba",
                    "tris": fixed,
                })
                if moving:
                    parts.append({"name": "Руддерватор %s" % ("(дясно)" if sign > 0
                                                             else "(ляво)"),
                                  "color": CONTROL_COLOR, "tris": moving})
            if tail_gap > 0.0:
                # Мост от обшивката на фюзелажа до корена на панелите.
                # Следи ъгъла на панела (gamma) и се вгражда 3 mm
                # в обшивката, за да няма видима пукнатина.
                bridge_tris = []
                for sign in (1.0, -1.0):
                    rings = []
                    for dist in (v_skin - 3.0, root_off + 3.0):
                        ring = []
                        # профилът е в равнината на корена на панела:
                        # хордът е по x, дебелината по осите на панела
                        for u, v in tail_outline:
                            ring.append((x_v + u * c_p,
                                         sign * (dist * cos_g
                                                - v * c_p * sin_g),
                                         z_center + dist * sin_g
                                         + v * c_p * cos_g))
                        if sign < 0.0:
                            ring.reverse()
                        rings.append(ring)
                    bridge_tris.extend(_bridge(rings[0], rings[1]))
                    bridge_tris.extend(_cap(rings[0], reverse=True))
                    bridge_tris.extend(_cap(rings[1]))
                parts.append({"name": "Връзки корен опашка (V)",
                              "color": "#d2b18c", "tris": bridge_tris})
    else:
        # Коренът на кила стъпва на обшивката в неговата станция (тялото
        # се стеснява към опашката), а при луфт — на луфта над нея.
        if s_v_mm2 > 100.0:
            x_v0 = max(wing_le + c_root, tail_ac - 0.25 * c_v)
            x_v0 = min(x_v0, max(0.0, length - c_v))
            fin_skin = assembly.skin_offset(fus, x_v0, (0.0, 0.0, 1.0))
        else:
            x_v0, fin_skin = 0.0, 0.0
        z_fin = (z_center + fin_skin + tail_gap
                 if tail_gap > 0.0 else z_tail)

        if s_h_mm2 > 100.0:
            # AC на опашката е на 25% от хордата; използва се същото рамо,
            # с което е смятан статичният запас.
            x_h = max(wing_le + c_root, tail_ac - 0.25 * c_h)
            x_h = min(x_h, max(0.0, length - c_h))
            conventional = tail_type != "t_tail"
            # T-опашка: стабилизаторът ляга на върха на кила (3 mm
            # застъпване), а не виси над него.
            z_h = (z_fin + b_v - assembly.JOIN_EMBED_MM
                   if not conventional else z_tail)
            skin_h = (assembly.skin_offset(fus, x_h, (0.0, 1.0, 0.0))
                      if conventional else 0.0)
            root_h = skin_h + tail_gap if (tail_gap > 0 and conventional) else 0.0
            el_ctrl = tail_ctrl.get("elevator") or {}
            clear = float(el_ctrl.get("root_clear_mm", 2.0))
            if conventional:
                # елеваторът започва извън тялото (при пантата)
                x_hinge = x_h + (1.0 - float(el_ctrl.get("chord_frac") or 0.3)) * c_h
                e0 = max(root_h, assembly.skin_offset(fus, x_hinge,
                                                      (0.0, 1.0, 0.0))) + clear
            else:
                # T-опашка: от кила (полудебелината на върха му) навън
                e0 = 0.5 * airfoils.thickness_of(fin_key) * c_v * taper_v + clear
            h_layout = _control_layout(
                el_ctrl, e0,
                b_h / 2.0 * (1.0 - el_ctrl.get("tip_margin_frac", 0.03)),
                b_h / 2.0, root_h, c_h, c_h * taper_h)
            fixed, moving = _surface_split(
                tail_outline, h_layout, max(q["tail"], 8),
                half_span=b_h / 2.0, c_root=c_h, c_tip=c_h * taper_h,
                origin=(x_h, 0.0, z_h), span_axis=(0.0, 1.0, 0.0),
                thick_axis=(0.0, 0.0, 1.0), two_sided=True,
                root_gap_mm=root_h)
            parts.append({"name": "Стабилизатор", "color": "#9fb0c6",
                          "tris": fixed})
            if moving:
                parts.append({"name": "Кормило за височина",
                              "color": CONTROL_COLOR, "tris": moving})
            stab_top = z_h + 0.5 * airfoils.thickness_of(tail_key) * c_h
            stab_bottom = z_h - 0.5 * airfoils.thickness_of(tail_key) * c_h
            if root_h > 0.0:
                bridge_tris = []
                for sign in (1.0, -1.0):
                    rings = []
                    for distance in (skin_h - 3.0, root_h + 3.0):
                        ring = []
                        for u, v in tail_outline:
                            ring.append((x_h + u * c_h,
                                             sign * distance,
                                         z_h + v * c_h))
                        if sign < 0.0:
                            ring.reverse()
                        rings.append(ring)
                    bridge_tris.extend(_bridge(rings[0], rings[1]))
                    bridge_tris.extend(_cap(rings[0], reverse=True))
                    bridge_tris.extend(_cap(rings[1]))
                parts.append({"name": "Връзки корен опашка",
                              "color": "#d2b18c", "tris": bridge_tris})

        if s_v_mm2 > 100.0:
            ru_ctrl = tail_ctrl.get("rudder") or {}
            clear = float(ru_ctrl.get("root_clear_mm", 2.0))
            r0, r1 = clear, b_v * (1.0 - ru_ctrl.get("tip_margin_frac", 0.03))
            if s_h_mm2 > 100.0 and tail_type == "t_tail":
                # рудерът свършва под стабилизатора на върха на кила
                r1 = min(r1, stab_bottom - z_fin - clear)
            elif s_h_mm2 > 100.0:
                # рудерът започва над стабилизатора (елеваторът да се движи)
                r0 = max(r0, stab_top - z_fin + clear)
            r_layout = _control_layout(ru_ctrl, r0, r1, b_v, 0.0, c_v,
                                       c_v * taper_v)
            fixed, moving = _surface_split(
                fin_outline, r_layout, max(q["tail"], 8),
                half_span=b_v, c_root=c_v, c_tip=c_v * taper_v,
                origin=(x_v0, 0.0, z_fin), span_axis=(0.0, 0.0, 1.0),
                thick_axis=(0.0, 1.0, 0.0), two_sided=False)
            parts.append({"name": "Кил", "color": "#8fa2ba", "tris": fixed})
            if moving:
                parts.append({"name": "Кормило за посока",
                              "color": CONTROL_COLOR, "tris": moving})
            if tail_gap > 0.0:
                bridge_tris = []
                rings = []
                for z_station in (z_center + fin_skin - 3.0,
                                  z_fin + 3.0):
                    ring = [(x_v0 + u * c_v, v * c_v, z_station)
                            for u, v in fin_outline]
                    rings.append(ring)
                bridge_tris.extend(_bridge(rings[0], rings[1]))
                bridge_tris.extend(_cap(rings[0], reverse=True))
                bridge_tris.extend(_cap(rings[1]))
                parts.append({"name": "Връзка корен кил",
                              "color": "#c2a47f", "tris": bridge_tris})

    # Мотор(и) и витло(а): размерите идват от motor.py (клас по мощност и
    # въртящ момент, витлото — реалният D×P от изчислението)
    if spinner:
        parts.append({"name": "Спинер", "color": "#f0b24a", "layer": "skin",
                      "tris": _spininner(spinner, max(16, q["ring"]))})
    parts += _motor_parts(res, max(12, q["ring"] // 2))

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
            # skin = обшивка (полупрозрачна в режим „Вътрешност“),
            # internal = спар/джойнер, solid = всичко останало
            "layer": part.get("layer", "solid"),
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
            "tail_airfoil": airfoils.get(
                g.get("tail_airfoil") or airfoils.DEFAULT_TAIL_AIRFOIL)["name"],
            "fin_airfoil": airfoils.get(
                g.get("fin_airfoil") or airfoils.fin_airfoil(
                    g.get("tail_airfoil") or airfoils.DEFAULT_TAIL_AIRFOIL))["name"],
            "aspect_ratio": round(float(g["aspect_ratio"]), 2),
            "has_tail": bool(res["mission"]["has_tail"]),
        },
    }


