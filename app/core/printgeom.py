"""
printgeom.py — геометрия за печат: затворени обеми (mm) за STL.

За разлика от geometry3d.py (визуализация на пропорциите с една повърхност
без дебелина), тук обшивката е РЕАЛНА: външна и вътшна повърхност на
разстояние една стена, затворени в корена и върха, плюс спарови капси.

Координати (mm), ориентация за печат:
    X — по хордата (0 = водещ ръб)
    Y — по дебелината (повърхността на леглото е Y = 0)
    Z — по размаха (0 = корена)
Фюзелажът се печата по дължината си:
    X — ширина, Y — височина, Z — по дължината (0 = носа)

Модулът е чист Python (math), без numpy и без CSG. Всичко е лофт по
сечения, затова един и същ код се ползва за крило, опашка и тяло.
"""

import datetime
import json
import math
import os

from . import aero
from . import airfoils
from . import fairing as fairing_mod
from . import fuselage as fus_mod
from .quality import quality_spec
from . import stl as stl_mod

OUTLINE_POINTS = 18      # точки на повърхност на профила
WING_STATIONS = 6        # сечения по размаха
TAIL_STATIONS = 4
TE_TRIM = 0.02           # колко от задната част на профила се отрязва
MIN_EDGE_MM = 0.6        # минимална дебелина на задната част


class Mesh:
    """
    Прост индексен меш: върхове + триъгълници.

    Пази индексите, за да могат съседните сечения да делят върхове и
    всеки ръб да се използва точно два пъти (затворен, манифолден обем).
    """

    __slots__ = ("vertices", "faces")

    def __init__(self):
        self.vertices = []
        self.faces = []

    def vertex(self, point):
        """Добавя връх и връща индекса му."""
        self.vertices.append((float(point[0]), float(point[1]),
                              float(point[2])))
        return len(self.vertices) - 1

    def ring(self, points):
        """Добавя затворен контур и връща списък с индекси."""
        return [self.vertex(p) for p in points]

    def face(self, a, b, c):
        """Триъгълник по индекси (без изродени)."""
        if a == b or b == c or a == c:
            return
        self.faces.append((a, b, c))

    def merge(self, other):
        """Добавя друг меш, като измества индексите."""
        base = len(self.vertices)
        self.vertices.extend(other.vertices)
        for a, b, c in other.faces:
            self.faces.append((a + base, b + base, c + base))

    def triangles(self):
        """Брой триъгълници."""
        return len(self.faces)

    def bbox(self):
        """Габарит (min_x, min_y, min_z, max_x, max_y, max_z)."""
        if not self.vertices:
            return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        xs = [p[0] for p in self.vertices]
        ys = [p[1] for p in self.vertices]
        zs = [p[2] for p in self.vertices]
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    def size(self):
        """Размери (dx, dy, dz)."""
        x0, y0, z0, x1, y1, z1 = self.bbox()
        return (x1 - x0, y1 - y0, z1 - z0)

    def volume(self):
        """Ориентиран обем [mm³] (сума на тетраедри от началото)."""
        total = 0.0
        verts = self.vertices
        for a, b, c in self.faces:
            ax, ay, az = verts[a]
            bx, by, bz = verts[b]
            cx, cy, cz = verts[c]
            total += (ax * (by * cz - bz * cy)
                      - ay * (bx * cz - bz * cx)
                      + az * (bx * cy - by * cx))
        return total / 6.0

    def flip(self):
        """Обръща ориентацията на всички триъгълници."""
        self.faces = [(a, c, b) for a, b, c in self.faces]

    def orient_outward(self):
        """Прави нормалите навън (положителен обем)."""
        if self.volume() < 0:
            self.flip()
        return self

    def move(self, dx=0.0, dy=0.0, dz=0.0):
        """Отмества целия меш."""
        self.vertices = [(x + dx, y + dy, z + dz)
                         for (x, y, z) in self.vertices]
        return self

    def to_bed(self):
        """Слага частта върху леглото: min X/Y = 0, min Z = 0."""
        x0, y0, z0, _, _, _ = self.bbox()
        return self.move(-x0, -y0, -z0)

    def is_manifold(self):
        """
        Всеки ръб трябва да се използва точно два пъти (затворен обем).

        Връща (bool, брой лоши ръбове).
        """
        edges = {}
        for a, b, c in self.faces:
            for i, j in ((a, b), (b, c), (c, a)):
                key = (i, j) if i < j else (j, i)
                edges[key] = edges.get(key, 0) + 1
        bad = sum(1 for count in edges.values() if count != 2)
        return bad == 0, bad


# --------------------------------------------------------------------------
# Лофт: повърхности и капачки между два контура с еднаква дължина
# --------------------------------------------------------------------------
def bridge(mesh, ring_a, ring_b):
    """
    Свързва два затворени контура (индекси) с лента от триъгълници.

    Контурите трябва да са с еднаква дължина и еднаква посока.
    """
    n = len(ring_a)
    if n != len(ring_b) or n < 3:
        return
    for i in range(n):
        j = (i + 1) % n
        a0, a1 = ring_a[i], ring_a[j]
        b0, b1 = ring_b[i], ring_b[j]
        mesh.face(a0, a1, b1)
        mesh.face(a0, b1, b0)


def cap_fan(mesh, ring, center, reverse=False):
    """Затваря контур с ветрило от центроида (за плътни краища)."""
    c = mesh.vertex(center)
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        if reverse:
            mesh.face(c, ring[j], ring[i])
        else:
            mesh.face(c, ring[i], ring[j])


def cap_annulus(mesh, outer, inner, reverse=False):
    """Затваря пръстен между външен и вътрешен контур."""
    n = len(outer)
    if n != len(inner) or n < 3:
        return
    for i in range(n):
        j = (i + 1) % n
        o0, o1 = outer[i], outer[j]
        i0, i1 = inner[i], inner[j]
        if reverse:
            mesh.face(o0, i1, o1)
            mesh.face(o0, i0, i1)
        else:
            mesh.face(o0, o1, i1)
            mesh.face(o0, i1, i0)


# --------------------------------------------------------------------------
# Профил и 2D геометрия
# --------------------------------------------------------------------------
def _signed_area(points):
    """Ориентирана площ на полигон (формула на шнура)."""
    acc = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        acc += x0 * y1 - x1 * y0
    return acc / 2.0


def ccw(points):
    """Връща полигона обратно на часовниковата стрелка."""
    return points if _signed_area(points) > 0 else list(reversed(points))


def airfoil_outline(key, points=OUTLINE_POINTS, te_trim=TE_TRIM,
                    min_edge_mm=None, chord_mm=1.0, le_trim=0.0):
    """
    Затворен контур на профила: горна повърхност LE→TE, долна TE→LE.

    Задната част се отрязва до вертикална стена с минимална дебелина —
    иначе при изместване с една стена профилът се самопресича при
    затворения заден ръб. Връща списък (x, y) в единична хорда, CCW.

    `le_trim` (дял от хордата) отрязва и водещия ръб до малка стена.
    Ползва се само за CAD: там ножът на водещия ръб прави пресечната
    крива с тялото нестабилна (SolidCraft отказва join-а). Мрежата за
    печат/преглед остава с остър ръб (по подразбиране 0).
    """
    coords = airfoils.coordinates_for(key, points + 1)
    if not coords:
        coords = airfoils.coordinates_for(airfoils.DEFAULT_AIRFOIL,
                                          points + 1)
    upper = [(float(x), float(y)) for x, y in coords["upper"]]
    lower = [(float(x), float(y)) for x, y in coords["lower"]]

    x_cut = max(0.80, 1.0 - te_trim)
    top = [p for p in upper if p[0] <= x_cut]
    bot = [p for p in lower if p[0] <= x_cut]
    if not top or not bot:
        return []
    # малко удължаване до x_cut, за да е равна задната стена
    top.append((x_cut, _interp_y(upper, x_cut)))
    bot.append((x_cut, _interp_y(lower, x_cut)))

    if le_trim and le_trim > 0:
        # отрязан водещ ръб: малка вертикална стена вместо нож
        x_le = min(0.25, max(0.0, float(le_trim)))
        top_next = [p for p in top if p[0] > x_le]
        bot_next = [p for p in bot if p[0] > x_le]
        if top_next and bot_next:
            top = [(x_le, _interp_y(upper, x_le))] + top_next
            bot = [(x_le, _interp_y(lower, x_le))] + bot_next

    half = max(top[-1][1] - bot[-1][1], 0.0) / 2.0
    if min_edge_mm and chord_mm > 0:
        half = max(half, (min_edge_mm / 2.0) / chord_mm)
    y_mid = (top[-1][1] + bot[-1][1]) / 2.0
    top[-1] = (top[-1][0], y_mid + half)
    bot[-1] = (bot[-1][0], y_mid - half)

    outline = top + list(reversed(bot[1:]))
    return ccw(outline)


def _interp_y(points, x):
    """Линейна интерполация по x върху монотонен по x списък."""
    if not points:
        return 0.0
    prev = points[0]
    for cur in points:
        if cur[0] >= x:
            if cur[0] <= prev[0] + 1e-12:
                return cur[1]
            t = (x - prev[0]) / (cur[0] - prev[0])
            return prev[1] + t * (cur[1] - prev[1])
        prev = cur
    return points[-1][1]


def offset_inward(points, distance, miter_limit=3.0):
    """
    Измества затворен CCW полигон навътре с `distance` (стена).

    Нормалите се сумират по ъглополовящата, а дължината на митрата се
    ограничава — иначе при остър връх точката „излита“.
    """
    n = len(points)
    if n < 3 or distance <= 0:
        return list(points)
    normals = []
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            normals.append((0.0, 0.0))
        else:
            # за CCW полигон вътрешността е отляво на реброто
            normals.append((-dy / length, dx / length))

    out = []
    for i in range(n):
        nx1, ny1 = normals[i - 1]
        nx2, ny2 = normals[i]
        bx, by = nx1 + nx2, ny1 + ny2
        length = math.hypot(bx, by)
        if length <= 1e-9:
            out.append(points[i])
            continue
        bx, by = bx / length, by / length
        cos_half = max(0.2, bx * nx1 + by * ny1)
        miter = min(distance / cos_half, miter_limit * distance)
        out.append((points[i][0] + bx * miter,
                    points[i][1] + by * miter))
    return out


# --------------------------------------------------------------------------
# Лофт на затворена черупка (външна + вътрешна повърхност + две капачки)
# --------------------------------------------------------------------------
def loft_shell(outer_sections, inner_sections):
    """
    Затворена черупка от две поредици сечения с еднаква дължина.

    Всяко сечение е списък от (x, y, z) точки, подредени в еднаква посока.
    Връща Mesh с външна повърхност, вътрешна (обратна) и пръстени в двата
    края. Ориентацията се оправя от orient_outward().
    """
    mesh = Mesh()
    outer_rings = [mesh.ring(points) for points in outer_sections]
    inner_rings = [mesh.ring(points) for points in inner_sections]

    for i in range(len(outer_rings) - 1):
        bridge(mesh, outer_rings[i], outer_rings[i + 1])
        # вътрешната повърхност е с обърната посока
        bridge(mesh, inner_rings[i + 1], inner_rings[i])

    cap_annulus(mesh, outer_rings[0], inner_rings[0], reverse=True)
    cap_annulus(mesh, outer_rings[-1], inner_rings[-1])
    return mesh.orient_outward()


def _centroid(points):
    n = float(len(points))
    return (sum(p[0] for p in points) / n,
            sum(p[1] for p in points) / n,
            sum(p[2] for p in points) / n)


def prism(sections):
    """
    Плътен призматичен елемент (спарен капс) по поредица от 4-точкови
    сечения. Затворен обем, който се добавя към обшивката като отделна
    черупка — така слайсерът обединява телата без CSG.
    """
    mesh = Mesh()
    rings = [mesh.ring(points) for points in sections]
    for i in range(len(rings) - 1):
        bridge(mesh, rings[i], rings[i + 1])
    cap_fan(mesh, rings[0], _centroid(sections[0]), reverse=True)
    cap_fan(mesh, rings[-1], _centroid(sections[-1]))
    return mesh.orient_outward()


# --------------------------------------------------------------------------
# Профилни повърхности (крило и опашка)
# --------------------------------------------------------------------------
WASHOUT_DEG = 1.5      # положително = усукване надолу към върха (washout)


def _profile_lines(key, points=OUTLINE_POINTS):
    """Горна и долна линия на профила в единична хорда."""
    coords = airfoils.coordinates_for(key, points + 1)
    if not coords:
        coords = airfoils.coordinates_for(airfoils.DEFAULT_AIRFOIL,
                                          points + 1)
    upper = [(float(x), float(y)) for x, y in coords["upper"]]
    lower = [(float(x), float(y)) for x, y in coords["lower"]]
    return upper, lower


def _section_polygon(unit_outline, chord, twist_deg, x_shift):
    """Контур на сечението в mm, завъртян около водещия ръб."""
    rot = math.radians(twist_deg)
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    out = []
    for u, v in unit_outline:
        x = chord * u
        y = chord * v
        out.append((x * cos_r - y * sin_r + x_shift,
                    x * sin_r + y * cos_r))
    return out


def spinner_mesh(params, segments=24, cowl=True):
    """
    Спинер (конус) + каулинг като затворен обем за печат/CAD.

    Параметрите идват от fairing.spinner_params; геометрията е същата
    като в 3D прегледа, за да няма разминаване между изгледа и модела.
    cowl=False оставя само конуса — така спинерите се печатат (каулингът
    е част от OML модела, не от печатната част).
    """
    if not params:
        return Mesh()
    if not cowl:
        return spinner_cone(params, segments)
    return spinner_cowl(params, segments)


def spinner_cone(params, segments=24):
    """Само конусът на спинера — затворен обем (връх + основа)."""
    mesh = Mesh()
    if not params:
        return mesh
    seg = max(8, int(segments))
    z = float(params["z_center"])
    r_spin = max(1.0, float(params["radius"]))
    x_tip = float(params["x_tip"])
    x_base = float(params["x_base"])
    base = [(x_base, r_spin * math.cos(2.0 * math.pi * k / seg),
             z + r_spin * math.sin(2.0 * math.pi * k / seg))
            for k in range(seg)]
    idx = mesh.ring(base)
    tip = mesh.vertex((x_tip, 0.0, z))
    for k in range(seg):
        mesh.face(tip, idx[(k + 1) % seg], idx[k])
    cap_fan(mesh, idx, (x_base, 0.0, z))
    return mesh.orient_outward()


def spinner_cowl(params, segments=24):
    """
    Каулингът: пресечен конус от спинера към кожата на тялото.

    Отделно тяло, защото е отделен затворен обем — така всеки обект в
    3MF/STEP е валиден solid (една обвивка).
    """
    mesh = Mesh()
    if not params:
        return mesh
    seg = max(8, int(segments))
    z = float(params["z_center"])
    r_spin = max(1.0, float(params["radius"]))
    x_c0 = float(params["x_cowl0"])
    x_c1 = float(params["x_cowl1"])
    r_c1 = max(0.5, float(params["r_cowl1"]))
    ring0, ring1 = [], []
    for k in range(seg):
        ang = 2.0 * math.pi * k / seg
        ring0.append((x_c0, r_spin * math.cos(ang), z + r_spin * math.sin(ang)))
        ring1.append((x_c1, r_c1 * math.cos(ang), z + r_c1 * math.sin(ang)))
    i0 = mesh.ring(ring0)
    i1 = mesh.ring(ring1)
    bridge(mesh, i0, i1)
    cap_fan(mesh, i0, (x_c0, 0.0, z), reverse=True)
    cap_fan(mesh, i1, (x_c1, 0.0, z))
    return mesh.orient_outward()


def lifting_surface(chord_root_mm, chord_tip_mm, span_mm, airfoil_key,
                    wall_mm, dihedral_deg=0.0, twist_deg=0.0,
                    stations=WING_STATIONS, mirrored=False,
                    te_min_mm=MIN_EDGE_MM, chord_fn=None,
                    upturn_deg=0.0, upturn_frac=0.0, points=None):
    """
    Полу- или цяла повърхност (крило/опашка) като затворена черупка.

    span_mm е дължината по размаха (за полукрило — полуразмах).
    mirrored=True обръща посоката на размаха (за другата половина).
    chord_fn(f) замества линейния хорд (заоблен/извит връх) и сгъстява
    станциите към върха, където хордът се променя най-бързо.
    """
    chord_root_mm = max(1.0, float(chord_root_mm))
    chord_tip_mm = max(0.5, float(chord_tip_mm))
    span_mm = max(1.0, float(span_mm))
    wall = max(0.2, float(wall_mm))
    stations = max(2, int(stations))

    unit = airfoil_outline(airfoil_key, int(points or OUTLINE_POINTS),
                           min_edge_mm=te_min_mm, chord_mm=chord_root_mm)
    if len(unit) < 6:
        return Mesh()

    tan_dih = math.tan(math.radians(dihedral_deg))
    tan_up = math.tan(math.radians(upturn_deg)) if upturn_deg else 0.0
    outer, inner = [], []
    for i in range(stations + 1):
        u = i / stations
        f = math.sin(0.5 * math.pi * u) if chord_fn is not None else u
        chord = (chord_fn(f) if chord_fn is not None
                 else chord_root_mm + (chord_tip_mm - chord_root_mm) * f)
        z = f * span_mm * (-1.0 if mirrored else 1.0)
        x_shift = abs(z) * tan_dih
        # извит нагоре връх: издигане по дебелината (Y в ориентация за печат)
        y_rise = 0.0
        if tan_up and upturn_frac > 0 and f > 1.0 - upturn_frac:
            bend = (f - (1.0 - upturn_frac)) / upturn_frac
            y_rise = bend * bend * span_mm * upturn_frac * tan_up
        twist = twist_deg * f
        poly = ccw(_section_polygon(unit, chord, twist, x_shift))
        outer.append([(x, y + y_rise, z) for (x, y) in poly])
        inset = ccw(offset_inward(poly, wall))
        inner.append([(x, y + y_rise, z) for (x, y) in inset])

    return loft_shell(outer, inner)


def spar_caps(res, chord_root_mm, chord_tip_mm, span_mm, airfoil_key,
              wall_mm, dihedral_deg=0.0, twist_deg=0.0,
              stations=WING_STATIONS, mirrored=False, chord_fn=None,
              upturn_deg=0.0, upturn_frac=0.0, points=None):
    """
    Печатани спарови капси по горна и долна повърхност.

    Напречното сечение е това, с което смята structure.analyse: ширина
    cap_width_mm и дебелина wall_mm. При нужда от карбон капсът се разделя
    на две ленти с процеп за карбоновата лента.
    """
    st = res.get("structure") or {}
    cap_w = float(st.get("cap_width_mm") or 0.0)
    if cap_w <= 0:
        return Mesh()
    wall = max(0.2, float(wall_mm))
    cap_t = max(0.4, wall)
    carbon = st.get("carbon") or {}
    carbon_needed = bool(st.get("carbon_required")) and \
        int(carbon.get("count") or 0) > 0
    gap = min(0.6 * cap_w, float(carbon.get("width_mm") or 0.0) + 0.3) \
        if carbon_needed else 0.0
    strips = 2 if gap > 0.5 else 1
    strip_w = (cap_w - gap) / strips if strips == 2 else cap_w
    if strip_w <= 0.3:
        strips, strip_w, gap = 1, cap_w, 0.0

    upper, lower = _profile_lines(airfoil_key, int(points or OUTLINE_POINTS))
    x_cap = 0.30
    half = (cap_w / 2.0) / max(1.0, chord_root_mm)
    y_top = min(_interp_y(upper, x_cap - half),
                _interp_y(upper, x_cap),
                _interp_y(upper, x_cap + half))
    y_bot = max(_interp_y(lower, x_cap - half),
                _interp_y(lower, x_cap),
                _interp_y(lower, x_cap + half))

    mesh = Mesh()
    tan_up = math.tan(math.radians(upturn_deg)) if upturn_deg else 0.0
    for sign in (1.0, -1.0):
        strips_sections = [[] for _ in range(strips)]
        for i in range(stations + 1):
            u = i / stations
            f = math.sin(0.5 * math.pi * u) if chord_fn is not None else u
            chord = (chord_fn(f) if chord_fn is not None
                     else chord_root_mm + (chord_tip_mm - chord_root_mm) * f)
            z = f * span_mm * (-1.0 if mirrored else 1.0)
            x_shift = abs(z) * math.tan(math.radians(dihedral_deg))
            y_rise = 0.0
            if tan_up and upturn_frac > 0 and f > 1.0 - upturn_frac:
                bend = (f - (1.0 - upturn_frac)) / upturn_frac
                y_rise = bend * bend * span_mm * upturn_frac * tan_up
            rot = math.radians(twist_deg * f)
            cos_r, sin_r = math.cos(rot), math.sin(rot)
            base = (y_top if sign > 0 else y_bot) * chord
            # капсът е точно под кожата; при карбон — две ленти с процеп
            y_in = base - sign * wall
            y_out = y_in - sign * cap_t
            x0 = x_cap * chord - cap_w / 2.0
            if strips == 1:
                ranges = [(x0, x0 + cap_w)]
            else:
                first = (x0, x0 + strip_w)
                second = (x0 + cap_w - strip_w, x0 + cap_w)
                ranges = [first, second]
            for idx, (xa, xb) in enumerate(ranges):
                corners = ((xa, y_out), (xb, y_out),
                           (xb, y_in), (xa, y_in))
                pts = []
                for (lx, ly) in corners:
                    pts.append((lx * cos_r - ly * sin_r + x_shift,
                                lx * sin_r + ly * cos_r + y_rise, z))
                strips_sections[idx].append(pts)

        for sections in strips_sections:
            if len(sections) >= 2:
                mesh.merge(prism(sections))
    return mesh



# --------------------------------------------------------------------------
# Фюзелаж
# --------------------------------------------------------------------------
FUSELAGE_RING = 24


def fuselage_mesh(res, wall_mm=None, rings=None, quality=None):
    """
    Тялото като затворена черупка по станции, в ориентация за печат:
    X = ширина, Y = височина, Z = по дължината (0 = носа).

    Вътрешната повърхност е мащабирана версия на външната (не отместване):
    така контурът винаги остава валиден и с еднакъв брой точки, което е
    нужно за пръстените в двата края.

    Плътността идва от нивото за качество: rings и стъпка по оста (mm).
    """
    q = quality_spec(quality)
    rings = int(rings or q["stl_ring"])
    fus = (res.get("geometry") or {}).get("fuselage") or {}
    if not fus:
        return Mesh()
    wall = max(0.2, float(wall_mm if wall_mm is not None else
                          ((res.get("structure") or {}).get("wall_mm")
                           or 0.45)))
    length = float(fus.get("length_mm") or 0.0)
    if length <= 0:
        return Mesh()

    step = max(4.0, float(q["stl_step_mm"]))
    stations = int(max(12, min(120, length / step)))
    outer, inner = [], []
    for i in range(stations + 1):
        t = i / stations
        poly = fus_mod.outline(fus, t, rings)
        w, h = fus_mod.section(fus, t)
        if w <= 1e-6 or h <= 1e-6:
            continue
        f = min(1.0 - 2.0 * wall / w, 1.0 - 2.0 * wall / h)
        f = max(0.20, min(0.99, f))
        z = t * length
        outer.append([(y, v, z) for (y, v) in poly])
        inner.append([(y * f, v * f, z) for (y, v) in poly])

    if len(outer) < 3:
        return Mesh()
    return loft_shell(outer, inner).to_bed()


# --------------------------------------------------------------------------
# Опашка
# --------------------------------------------------------------------------
def tail_meshes(res, wall_mm=None, quality=None):
    """
    Стабилизатор и кил като затворени черупки.

    Опашката е симетрична: стабилизаторът се строи като две полу-повърхности
    (лява и дясна), а килът — като една повърхност от корена към върха.
    """
    q = quality_spec(quality)
    tail_points = int(q["stl_points"])
    tail_stations = max(4, int(q["stl_wing"]) // 2 + 2)
    from . import aero

    g = res.get("geometry") or {}
    tail = g.get("tail") or {}
    if not res.get("mission", {}).get("has_tail", True):
        return []
    wall = max(0.2, float(wall_mm if wall_mm is not None else
                          ((res.get("structure") or {}).get("wall_mm")
                           or 0.45)))
    key = g.get("tail_airfoil") or airfoils.DEFAULT_TAIL_AIRFOIL
    out = []

    b_h = float(tail.get("b_h_mm") or 0.0)
    c_h = float(tail.get("c_h_mm") or 0.0)
    if b_h > 10.0 and c_h > 10.0:
        mesh = Mesh()
        for mirrored in (False, True):
            mesh.merge(lifting_surface(
                c_h, c_h * aero.TAIL_TAPER_H, b_h / 2.0, key, wall,
                0.0, 0.0, tail_stations, mirrored, points=tail_points))
        out.append({"name": "Стабилизатор", "file": "tail_horizontal.stl",
                    "mesh": mesh.to_bed()})

    b_v = float(tail.get("b_v_mm") or 0.0)
    c_v = float(tail.get("c_v_mm") or 0.0)
    if b_v > 10.0 and c_v > 10.0:
        mesh = lifting_surface(c_v, c_v * aero.TAIL_TAPER_V, b_v, key, wall,
                               0.0, 0.0, tail_stations, False,
                               points=tail_points)
        out.append({"name": "Кил", "file": "tail_vertical.stl",
                    "mesh": mesh.to_bed()})
    return out



# --------------------------------------------------------------------------
# Сглобяване на частите, план за печат и експорт
# --------------------------------------------------------------------------
def build_parts(res, quality=None):
    """
    Всички печатаеми части като затворени обеми.

    връща [{"name", "file", "mesh", "note"}] — геометрията е в mm и в
    ориентация за печат (частта лежи на леглото).
    Плътността идва от нивото за качество (stl_*).
    """
    if not res or not res.get("ok"):
        return []
    q = quality_spec(quality)
    g = res.get("geometry") or {}
    st = res.get("structure") or {}
    wall = float(st.get("wall_mm") or 0.45)
    parts = []

    semispan = float(g.get("span_mm") or 0.0) / 2.0
    c_root = float(g.get("c_root_mm") or 0.0)
    c_tip = float(g.get("c_tip_mm") or 0.0)
    dihedral = float(g.get("dihedral_deg") or 0.0)
    key = (g.get("airfoil") or {}).get("key") or airfoils.DEFAULT_AIRFOIL
    tip_style = g.get("tip_style", "square")
    tip_frac = float(g.get("tip_frac") or 0.0)
    tip_min = float(g.get("tip_min_ratio") or 0.10)
    taper = float(g.get("taper") or 1.0)
    washout = float(g.get("washout_deg") or 0.0)
    winglet = g.get("winglet") or {}
    dense = tip_style in ("rounded", "upturned", "winglet") and tip_frac > 0
    chord_fn = ((lambda f: aero.chord_at(f, c_root, taper, tip_style,
                                         tip_frac, tip_min))
                if dense else None)
    upturn = (float(aero.TIP_STYLES.get(tip_style, {}).get("upturn_deg", 0.0))
              if tip_style == "upturned" else 0.0)
    upturn_frac = tip_frac if upturn else 0.0
    # при закръгляне станциите се сгъстяват към върха (виж закръглянето)
    stations = max(int(q["stl_wing"]), 16) if dense else int(q["stl_wing"])
    wing_points = int(q["stl_points"])

    if semispan > 10.0 and c_root > 10.0:
        for name, mirrored, filename in (
                ("Крило — дясна половина", False, "wing_right.stl"),
                ("Крило — лява половина", True, "wing_left.stl")):
            mesh = lifting_surface(c_root, c_tip, semispan, key, wall,
                                   dihedral, washout, stations,
                                   mirrored, chord_fn=chord_fn,
                                   upturn_deg=upturn,
                                   upturn_frac=upturn_frac,
                                   points=wing_points)
            mesh.merge(spar_caps(res, c_root, c_tip, semispan, key, wall,
                                 dihedral, washout, stations,
                                 mirrored, chord_fn=chord_fn,
                                 upturn_deg=upturn,
                                 upturn_frac=upturn_frac,
                                 points=wing_points))
            parts.append({"name": name, "file": filename,
                          "mesh": mesh.to_bed()})

    # Уинглет: отделна част за печат (лепи се на върха), за да не се
    # обръща черупката на 90° и да остане крилото печатаемо.
    wl_h = float(winglet.get("height_mm") or 0.0)
    if winglet.get("enabled") and wl_h > 5.0 and c_root > 10.0:
        wl_chord = float(winglet.get("chord_mm") or 0.0)
        if wl_chord <= 0:
            wl_chord = 0.6 * c_root * taper
        for name, mirrored, filename in (
                ("Уинглет — дясно", False, "winglet_right.stl"),
                ("Уинглет — ляво", True, "winglet_left.stl")):
            mesh = lifting_surface(wl_chord, 0.5 * wl_chord, wl_h, key, wall,
                                   0.0, 0.0, 6, mirrored,
                                   points=max(12, wing_points // 2))
            if mesh.faces:
                parts.append({"name": name, "file": filename,
                              "mesh": mesh.to_bed()})

    fus = fuselage_mesh(res, wall, quality=quality)
    if fus.faces:
        parts.append({"name": "Фюзелаж", "file": "fuselage.stl",
                      "mesh": fus})

    # Спинер + каулинг (само при теглещо витло) — същата геометрия като
    # в прегледа, за да няма разминаване.
    spin = fairing_mod.spinner_params(res)
    if spin:
        mesh = spinner_mesh(spin, segments=max(16, int(q["stl_ring"])),
                            cowl=False)
        if mesh.faces:
            parts.append({"name": "Спинер", "file": "spinner.stl",
                          "mesh": mesh.to_bed()})

    parts.extend(tail_meshes(res, wall, quality=quality))
    return parts


def _segments_for(size, bed):
    """Колко части по всяка ос, за да влезе в леглото."""
    out = {}
    for axis, dim, limit in (("x", size[0], bed[0]), ("y", size[1], bed[1]),
                             ("z", size[2], bed[2])):
        out[axis] = max(1, int(math.ceil(dim / max(1.0, float(limit)))))
    return out


def plan_parts(parts, bed, filament=None):
    """План за печат: габарити, побиране в леглото, обем и маса."""
    bed = [float(v) for v in (bed or [220.0, 220.0, 250.0])[:3]]
    while len(bed) < 3:
        bed.append(250.0)
    density = float((filament or {}).get("printed_density") or 0.0)
    rows = []
    all_fit = True
    for part in parts:
        mesh = part["mesh"]
        size = mesh.size()
        volume = max(0.0, mesh.volume()) / 1000.0     # cm³
        fits = (size[0] <= bed[0] + 1e-6 and size[1] <= bed[1] + 1e-6
                and size[2] <= bed[2] + 1e-6)
        all_fit = all_fit and fits
        rows.append({
            "name": part["name"],
            "file": part["file"],
            "size_mm": [round(v, 1) for v in size],
            "triangles": mesh.triangles(),
            "volume_cm3": round(volume, 2),
            "mass_g": round(volume * density, 1) if density else None,
            "fits_bed": bool(fits),
            "segments": _segments_for(size, bed),
            "manifold": mesh.is_manifold()[0],
        })
    return {
        "units": "mm",
        "bed_mm": [round(v, 1) for v in bed],
        "parts": rows,
        "all_fit": bool(all_fit),
        "total_volume_cm3": round(sum(r["volume_cm3"] for r in rows), 2),
        "total_mass_g": (round(sum(r["mass_g"] or 0.0 for r in rows), 1)
                         if density else None),
        "total_triangles": sum(r["triangles"] for r in rows),
    }


def notes_for(plan):
    """Кратки бележки към плана (какво още не се моделира)."""
    notes = []
    if not plan.get("all_fit", True):
        big = [p["name"] for p in plan.get("parts", [])
               if not p["fits_bed"]]
        notes.append("Не се побират в леглото: %s. Разделянето по станции "
                     "(сегменти с гнезда) е следващата стъпка."
                     % ", ".join(big))
    notes.append("Корените са затворени с пръстен. Гнездото за "
                 "съединителната тръба и шпангоутите се добавят при "
                 "сегментирането.")
    notes.append("Спаровите капси са отделни тела в същия STL — слайсерът "
                 "ги обединява с обшивката.")
    return notes


def export(res, base_dir, bed, filament=None, slugify=None, subdir="stl",
           quality=None):
    """
    Записва STL файловете и print_plan.json в <base>/<дизайн>/<subdir>/.

    Връща {"ok", "folder", "files", "plan"}.
    """
    if not res or not res.get("ok"):
        return {"ok": False, "error": "няма изчислен дизайн"}
    parts = build_parts(res, quality=quality)
    if not parts:
        return {"ok": False, "error": "няма части за експорт"}

    name = (res.get("inputs") or {}).get("name") or "design"
    slug = slugify(name) if slugify else "design"
    folder = os.path.join(base_dir, slug)
    if subdir:
        folder = os.path.join(folder, subdir)
    os.makedirs(folder, exist_ok=True)

    plan = plan_parts(parts, bed, filament)
    files = []
    for part in parts:
        path = os.path.join(folder, part["file"])
        info = stl_mod.write_stl(path, part["mesh"].vertices,
                                 part["mesh"].faces, part["name"])
        files.append({"file": part["file"], "path": path,
                      "triangles": info["triangles"],
                      "bytes": info["bytes"]})

    plan["generated"] = datetime.datetime.now().isoformat(timespec="seconds")
    plan["files"] = files
    plan["notes"] = notes_for(plan)
    plan_path = os.path.join(folder, "print_plan.json")
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return {"ok": True, "folder": folder, "plan": plan, "files": files,
            "plan_path": plan_path}

