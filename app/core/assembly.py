"""
assembly.py — цялостен модел на самолета за CAD (OML).

За разлика от printgeom.py (кухи черупки, ориентация за печат), тук
геометрията е ПЛЪТНА и е в самолетна координатна система:

    X — назад от носа (станции)
    Y — надясно по размаха
    Z — нагоре; Z = 0 е долната точка на фюзелажа (земята)

Така моделът се импортира в CAD (3MF/STEP), където потребителят добавя
отвори за серва, джобове за управлението, капаци и т.н. Вътрешности не се
моделират — дават се само референтни тела (батерия, серва, мотор, ЦТ),
за да е ясно къде какво стои.

Модулът е чист Python и ползва примитивите от printgeom.py.
"""

import math

from . import aero
from . import airfoils
from . import fairing as fairing_mod
from . import fuselage as fus_mod
from .quality import quality_spec
from . import layout as layout_mod
from . import printgeom
from . import propulsion

# По-груба дискретизация от печатната: STEP/3MF да останат малки, а
# повърхността — достатъчно гладка за ориентир в CAD.
CAD_POINTS = 20
CAD_STATIONS = 10
CAD_FUSELAGE_RING = 16
CAD_FUSELAGE_STATIONS = 14
WASHOUT_DEG = printgeom.WASHOUT_DEG

DATUM = {
    "origin": "върхът на носа, на централната линия",
    "x": "назад по фюзелажа (станции), mm",
    "y": "надясно по размаха, mm",
    "z": "нагоре; Z = 0 е коремът (равнината XY е земята)",
    "units": "mm",
}

REF_SERVO_SMALL = (23.0, 12.0, 23.0)    # 9 g серва
REF_SERVO_LARGE = (30.0, 13.0, 30.0)    # 17 g+ серва

# CAD: застъпване между телата, за да може SolidCraft да ги обедини (join).
# Две тела, които само се допират (лице в лице), дават нестабилен boolean —
# SolidCraft ги отказва с „the join could not be computed reliably“.
JOIN_EMBED_MM = 3.0        # уинглет / T-опашка / спинер: застъпване в мм

# Коренът на крилото минава през тялото: горната повърхност е отвън, средната
# линия — вътре. Ако равнината на крилото е плътно под короната (високо
# крило), пресечната крива минава по ножа на водещия ръб и обединението се
# проваля. Затова коренът слиза/сяда с ROOT_SINK_FRAC от височината на тялото,
# а до ROOT_BLEND_FRAC от полуразмаха отместването затихва до 0 — външното
# крило остава точно на проектното място.
ROOT_SINK_FRAC = 0.15      # 15% от височината на тялото
ROOT_SINK_BAND = 0.25      # крилото е „близо до стената“ в тази чест от височината
ROOT_BLEND_FRAC = 0.30     # до 30% от полуразмаха слягането изчезва
ROOT_FAIRING_CHORD_RATIO = 1.25   # +25% chord at the wing root
ROOT_FAIRING_THICK_RATIO = 1.40   # +40% thickness at the wing root
ROOT_FAIRING_FADE_FRAC = 0.28     # fades to profile by 28% of half span


def _unit_outline(airfoil_key, points=CAD_POINTS, chord_mm=200.0):
    """Контур на профила в единична хорда (с отрязан заден ръб)."""
    return printgeom.airfoil_outline(
        airfoil_key, points, min_edge_mm=printgeom.MIN_EDGE_MM,
        chord_mm=chord_mm)


def _rotated(u, v, chord, twist_deg):
    """Точка от профила в mm, завъртяна около водещия ръб (равнина XZ)."""
    rot = math.radians(twist_deg)
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    x = chord * u
    z = chord * v
    return (x * cos_r - z * sin_r, x * sin_r + z * cos_r)


def _section_split(unit):
    """
    Индексът на задната стена в контура на профила.

    `airfoil_outline` връща LE → горна повърхност → TE_top → TE_bot →
    долна повърхност. Двете TE точки имат еднакъв x (= x_cut), затова
    двойката с максимален x е стената на задния ръб.
    """
    if not unit:
        return None
    max_x = max(p[0] for p in unit)
    for i in range(len(unit) - 1):
        if (abs(unit[i][0] - max_x) <= 1e-9
                and abs(unit[i + 1][0] - max_x) <= 1e-9):
            return i
    return None


def surface_rings(chord_root_mm, chord_tip_mm, span_mm, airfoil_key,
                  origin, span_axis, thick_axis, dihedral_deg=0.0,
                  twist_deg=0.0, stations=CAD_STATIONS, symmetric=False,
                  points=CAD_POINTS, chord_fn=None, upturn_deg=0.0,
                  upturn_frac=0.0, spacing="linear", sink_mm=0.0,
                  sink_blend=ROOT_BLEND_FRAC, start_mm=0.0):
    """
    Сеченията на повърхност (крило, стабилизатор, кил).

    Един източник за мрежата (`surface_solid`) и за гладкия loft в
    SolidCraft. Всяко сечение носи и равнината на скицата:
    `origin` (3D), `x_dir` (по хордата) и `y_dir` (по дебелината), а
    `points2d` са координатите в тази равнина.

    връща [{"name", "points3d", "points2d", "origin", "x_dir", "y_dir",
            "station_mm", "split"}]

    `spacing="sine"` сгъстява сеченията към върха (без да променя хордата).
    Така SolidCraft прави една гладка повърхност вместо много пачове —
    ползва се само за гладкия loft, не за мрежата.

    `sink_mm` сваля корена по световно Z (отрицателно = надолу) и затихва
    до 0 на `sink_blend` от размаха. Ползва се само за CAD модела: така
    коренът влиза достатъчно дълбоко в тялото и SolidCraft може да ги
    обедини (виж `wing_root_sink`).

    `start_mm` отмества началото на половин повърхност по размаха (върхът
    остава на `span_mm`). С `-JOIN_EMBED_MM` коренът на всяка половина
    влиза няколко mm отвъд оста, така че двете половини се **застъпват**,
    вместо да се допират с лица по оста (виж `half_rings`).
    """
    chord_root_mm = max(1.0, float(chord_root_mm))
    chord_tip_mm = max(0.5, float(chord_tip_mm))
    span_mm = max(1.0, float(span_mm))
    start_mm = float(start_mm or 0.0)
    if abs(start_mm) >= span_mm:
        start_mm = 0.0
    stations = max(2, int(stations))
    unit = _unit_outline(airfoil_key, points, chord_root_mm)
    if len(unit) < 6:
        return []
    split = _section_split(unit)

    tan_dih = math.tan(math.radians(dihedral_deg))
    tan_up = math.tan(math.radians(upturn_deg)) if upturn_deg else 0.0
    half = span_mm / 2.0
    out = []
    for i in range(stations + 1):
        u = i / stations
        if symmetric:
            side = 1.0 if u >= 0.5 else -1.0
            q = abs(2.0 * u - 1.0)
        else:
            side = 1.0
            q = u
        # при заоблен връх станциите се сгъстяват към върха
        if chord_fn is not None or spacing == "sine":
            f = math.sin(0.5 * math.pi * q)
        else:
            f = q
        if symmetric:
            s = side * f * half
        elif start_mm:
            # коренът започва `start_mm` по-навътре, върхът остава на място
            s = start_mm + f * (span_mm - start_mm)
        else:
            s = f * span_mm
        chord = (chord_fn(f) if chord_fn is not None
                 else chord_root_mm + (chord_tip_mm - chord_root_mm) * f)
        twist = twist_deg * f
        rise = abs(s) * tan_dih if symmetric else s * tan_dih
        if tan_up and upturn_frac > 0 and f > 1.0 - upturn_frac:
            bend = (f - (1.0 - upturn_frac)) / upturn_frac
            rise += bend * bend * half * upturn_frac * tan_up
        base = (origin[0] + span_axis[0] * s + thick_axis[0] * rise,
                origin[1] + span_axis[1] * s + thick_axis[1] * rise,
                origin[2] + span_axis[2] * s + thick_axis[2] * rise)
        if sink_mm:
            # затихващо слягане на корена (само CAD): 1 при корена, 0 на
            # sink_blend от размаха
            w = max(0.0, 1.0 - f / max(1e-9, float(sink_blend)))
            base = (base[0], base[1], base[2] + sink_mm * w * w)
        pts3d, pts2d = [], []
        for (u, v) in unit:
            lx, lz = _rotated(u, v, chord, twist)
            pts2d.append((lx, lz))
            pts3d.append((base[0] + lx,
                          base[1] + thick_axis[1] * lz,
                          base[2] + thick_axis[2] * lz))
        out.append({
            "name": "S%02d" % (i + 1),
            "points3d": pts3d,
            "points2d": pts2d,
            "origin": base,
            "x_dir": (1.0, 0.0, 0.0),
            "y_dir": (float(thick_axis[0]), float(thick_axis[1]),
                      float(thick_axis[2])),
            "station_mm": float(s),
            "split": split,
        })
    return out


def surface_solid(chord_root_mm, chord_tip_mm, span_mm, airfoil_key,
                  origin, span_axis, thick_axis, dihedral_deg=0.0,
                  twist_deg=0.0, stations=CAD_STATIONS, symmetric=False,
                  points=CAD_POINTS, chord_fn=None, upturn_deg=0.0,
                  upturn_frac=0.0, sink_mm=0.0, sink_blend=ROOT_BLEND_FRAC,
                  spacing="linear"):
    """
    Плътна повърхност (крило, стабилизатор, кил) като един затворен обем.

    origin      — коренът на водещия ръб (x, y, z)
    span_axis   — посока на размаха (единичен вектор)
    thick_axis  — посока на дебелината (перпендикулярна)
    symmetric   — True: размахът е от -span/2 до +span/2 (цяло крило)
    """
    sections = surface_rings(
        chord_root_mm, chord_tip_mm, span_mm, airfoil_key, origin,
        span_axis, thick_axis, dihedral_deg, twist_deg, stations,
        symmetric, points, chord_fn, upturn_deg, upturn_frac,
        sink_mm=sink_mm, sink_blend=sink_blend, spacing=spacing)
    if not sections:
        return printgeom.Mesh()
    rings = [section["points3d"] for section in sections]

    mesh = printgeom.Mesh()
    idx = [mesh.ring(ring) for ring in rings]
    for i in range(len(idx) - 1):
        printgeom.bridge(mesh, idx[i], idx[i + 1])

    first, last = rings[0], rings[-1]
    printgeom.cap_fan(mesh, idx[0], _centroid(first), reverse=True)
    printgeom.cap_fan(mesh, idx[-1], _centroid(last))
    return mesh.orient_outward()


def _centroid(points):
    n = float(len(points))
    return (sum(p[0] for p in points) / n,
            sum(p[1] for p in points) / n,
            sum(p[2] for p in points) / n)


def fuselage_rings(res, rings=None, stations=None, quality=None,
                   t_start=0.0):
    """
    Сеченията на тялото по дължината (един източник за mesh и за loft).

    `t_start` е къде започва първото сечение по дължината (0…1):
    мрежата почва от 0.02 и затваря носа с конус към върха, а гладкият
    loft ползва аналитичното сечение при 0 (3 mm — практически връх).

    връща [{"name", "points3d", "points2d", "origin", "x_dir", "y_dir",
            "station_mm", "split": None}]
    """
    q = quality_spec(quality)
    rings = int(rings or q["cad_ring"])
    stations = int(stations or q["cad_stations"])
    fus = (res.get("geometry") or {}).get("fuselage") or {}
    length = float(fus.get("length_mm") or 0.0)
    height = float(fus.get("height_mm") or 0.0)
    if length <= 0 or height <= 0:
        return []
    z_center = height / 2.0
    start = min(max(0.0, float(t_start)), 0.9)
    out = []
    for i in range(stations + 1):
        u = i / stations
        t = start + (1.0 - start) * u
        pts2d = fus_mod.outline(fus, t, rings)
        x = t * length
        section = {
            "name": "F%02d" % (i + 1),
            "points3d": [(x, y, v + z_center) for (y, v) in pts2d],
            "points2d": [(y, v) for (y, v) in pts2d],
            "origin": (x, 0.0, z_center),
            "x_dir": (0.0, 1.0, 0.0),
            "y_dir": (0.0, 0.0, 1.0),
            "station_mm": x,
            "split": None,
        }
        if abs(float(fus.get("exp") or 2.0) - 2.0) <= 1e-9:
            # Точно елипса: CAD скицата може да е `sketch.ellipse` вместо
            # spline през 16+ точки. Контурът остава в points2d за SVG.
            half_w = max(abs(float(p[0])) for p in pts2d)
            half_h = max(abs(float(p[1])) for p in pts2d)
            if half_w > 0.0 and half_h > 0.0:
                section["primitive"] = {
                    "type": "ellipse",
                    "center": (0.0, 0.0),
                    "major": (half_w, 0.0),
                    "minor_radius": half_h,
                }
        out.append(section)
    return out


def fuselage_section(fus, x_mm, rings=48):
    """
    Полуширина и полувисочина (спрямо оста) на обшивката при станция x.

    Използва се за луфта на крилото/опашката: тялото се стеснява към
    опашката, затова максималната ширина/височина дава прекалено голям
    луфт там.
    """
    fus = fus or {}
    length = float(fus.get("length_mm") or 0.0)
    half_w = float(fus.get("width_mm") or 0.0) / 2.0
    half_h = float(fus.get("height_mm") or 0.0) / 2.0
    if length <= 0 or half_w <= 0 or half_h <= 0:
        return half_w, half_h
    t = min(max(0.0, float(x_mm) / length), 1.0)
    pts = fus_mod.outline(fus, t, max(24, int(rings)))
    if not pts:
        return half_w, half_h
    return (max(abs(float(p[0])) for p in pts),
            max(abs(float(p[1])) for p in pts))


def skin_offset(fus, x_mm, axis):
    """
    Разстояние от оста на тялото до обшивката по посока `axis` (y, z).

    За посока (0, 1, 0) това е локалната полуширина, за (0, 0, 1) —
    локалната полувисочина, а за наклонена ос (V-опашка) — пресечната
    точка на лъча със суперелипсата. Така "луфт" винаги се мери от
    обшивката, а не от максималния габарит на тялото.
    """
    fus = fus or {}
    a, b = fuselage_section(fus, x_mm)
    cy = abs(float(axis[1]))
    cz = abs(float(axis[2]))
    norm = math.hypot(cy, cz)
    if a <= 0.0 or b <= 0.0 or norm <= 1e-9:
        return 0.0
    cy, cz = cy / norm, cz / norm
    n = max(0.5, float(fus.get("exp") or 2.0))
    denom = (cy / a) ** n + (cz / b) ** n
    if denom <= 0.0:
        return 0.0
    return 1.0 / (denom ** (1.0 / n))


def fuselage_solid(res, rings=None, stations=None, quality=None):
    """
    Тялото като един плътен обем: заоблен нос (връх в x = 0), сечения по
    дължината и плосък капак в опашката.

    Тялото е **една затворена обвивка** — без допълнителни тела, така че
    всеки обект в 3MF/STEP е валиден solid.
    Плътността идва от нивото за качество (cad_ring/cad_stations).
    """
    sections = fuselage_rings(res, rings=rings, stations=stations,
                              quality=quality, t_start=0.02)
    if not sections:
        return printgeom.Mesh()
    fus = (res.get("geometry") or {}).get("fuselage") or {}
    z_center = float(fus.get("height_mm") or 0.0) / 2.0
    rings3d = [section["points3d"] for section in sections]

    mesh = printgeom.Mesh()
    idx = [mesh.ring(ring) for ring in rings3d]
    for i in range(len(idx) - 1):
        printgeom.bridge(mesh, idx[i], idx[i + 1])

    apex = (0.0, 0.0, z_center)
    printgeom.cap_fan(mesh, idx[0], apex, reverse=True)
    printgeom.cap_fan(mesh, idx[-1], _centroid(rings3d[-1]))
    return mesh.orient_outward()



def spinner_solids(res, quality=None):
    """
    Спинер и каулинг като **две отделни тела** (при теглещо витло).

    Двата са отделни затворени обвивки, затова не могат да са един обект:
    всеки обект в 3MF/STEP трябва да е валиден solid (една обвивка).
    """
    params = fairing_mod.spinner_params(res)
    if not params:
        return []
    q = quality_spec(quality)
    segments = max(16, int(q["cad_ring"]) // 2)
    out = []
    cone = printgeom.spinner_cone(params, segments=segments)
    if cone.faces:
        out.append({"name": "Spinner", "file": "spinner.stl", "mesh": cone,
                    "kind": "body"})
    cowl = printgeom.spinner_cowl(params, segments=segments)
    if cowl.faces:
        out.append({"name": "Cowl", "file": "cowl.stl", "mesh": cowl,
                    "kind": "body"})
    return out


def tail_specs(res, quality=None, exact=False):
    """
    Опашката като спецификации: [(име, файл, параметри на повърхност)].

    Едно място за мрежата (`tail_solids`) и за гладкия loft в SolidCraft.

    `exact=False` (по подразбиране за CAD): планформата е трапец с прав
    срез — най-малко пачове, най-бърз boolean в SolidCraft. `exact=True`:
    планформата и връхчетата от дизайна (прав/трапец/елипса, прав/заоблен
    връх); площта се запазва чрез кореновата хорда.
    """
    q = quality_spec(quality)
    stations = int(q["cad_wing"])
    points = int(q["cad_points"])
    g = res.get("geometry") or {}
    tail = g.get("tail") or {}
    fus = g.get("fuselage") or {}
    if not (res.get("mission") or {}).get("has_tail", True):
        return []
    if not g or not fus:
        return []
    info = res.get("layout") or {}
    tail_type = info.get("tail_type", "conventional")
    height = float(fus.get("height_mm") or 0.0)
    length = float(fus.get("length_mm") or 0.0)
    z_center = height / 2.0
    key = g.get("tail_airfoil") or airfoils.DEFAULT_TAIL_AIRFOIL
    # килът — винаги със симетричен профил (виж airfoils.fin_airfoil)
    fin_key = g.get("fin_airfoil") or airfoils.fin_airfoil(key)
    wing_le = float(g.get("wing_le_mm") or 0.0)
    c_root = float(g.get("c_root_mm") or 0.0)
    tail_ac = float(tail.get("tail_ac_mm") or 0.0)
    b_h = float(tail.get("b_h_mm") or 0.0)
    c_h = float(tail.get("c_h_mm") or 0.0)
    b_v = float(tail.get("b_v_mm") or 0.0)
    c_v = float(tail.get("c_v_mm") or 0.0)
    out = []

    planform = aero.TAIL_PLANFORMS.get(info.get("tail_planform") or "tapered",
                                       aero.TAIL_PLANFORMS["tapered"])
    tip_style = aero.TAIL_TIP_STYLES.get(info.get("tail_tip_style")
                                        or "square",
                                        aero.TAIL_TIP_STYLES["square"])
    if exact:
        taper_h = float(planform["taper_h"])
        taper_v = float(planform["taper_v"])
        tip_frac = max(float(planform.get("tip_frac") or 0.0),
                       float(tip_style.get("tip_frac") or 0.0))
    else:
        taper_h = aero.TAIL_TAPER_H
        taper_v = aero.TAIL_TAPER_V
        tip_frac = 0.0
    # Входните хорди са изчислени за планформата на дизайна — при друга
    # планформа коренът се преизчислява, за да се запази площта.
    c_h = c_h * (1.0 + float(planform["taper_h"])) / (1.0 + taper_h)
    c_v = c_v * (1.0 + float(planform["taper_v"])) / (1.0 + taper_v)

    def chord_fn(c_root_mm, taper):
        if tip_frac <= 0:
            return None
        return (lambda f: aero.chord_at(f, c_root_mm, taper, "rounded",
                                        tip_frac, 0.10))

    def tail_x(chord):
        x = max(wing_le + c_root, tail_ac - 0.25 * chord)
        return min(x, max(0.0, length - chord))

    if tail_type == "v_tail" and (b_h > 10 or b_v > 10):
        panel = (info.get("v_tail") or {}).get("s_panel_m2") or 0.0
        gamma = math.radians(float(info.get("v_tail_deg") or 35.0))
        c_p = max(c_h, c_v)
        if panel > 0 and c_p > 0:
            b_panel = panel * 1e6 / (c_p * (1.0 + taper_v))
            for sign, name in ((1.0, "Stabilizer_V_R"),
                               (-1.0, "Stabilizer_V_L")):
                out.append((name, "tail_%s.stl"
                            % ("v_right" if sign > 0 else "v_left"), {
                                "chord_root_mm": c_p,
                                "chord_tip_mm": c_p * taper_v,
                                "span_mm": b_panel,
                                "airfoil_key": key,
                                "origin": (tail_x(c_p), 0.0, z_center),
                                "span_axis": (0.0, sign * math.cos(gamma),
                                              math.sin(gamma)),
                                "thick_axis": (0.0, -sign * math.sin(gamma),
                                               math.cos(gamma)),
                                "stations": max(4, stations // 2),
                                "points": points,
                                "chord_fn": chord_fn(c_p, taper_v),
                                "spacing": "sine" if tip_frac else "linear",
                            }))
        return out

    z_stab = z_center
    if tail_type == "t_tail" and b_v > 0:
        # стабилизаторът ляга JOIN_EMBED_MM под върха на кила: иначе двете
        # тела само се допират и join-ът е нестабилен
        z_stab = z_center + b_v - JOIN_EMBED_MM
    if b_v > 0:
        out.append(("Fin", "tail_vertical.stl", {
            "chord_root_mm": c_v,
            "chord_tip_mm": c_v * taper_v,
            "span_mm": b_v,
            "airfoil_key": fin_key,
            "origin": (tail_x(c_v), 0.0, z_center),
            "span_axis": (0.0, 0.0, 1.0),
            "thick_axis": (0.0, 1.0, 0.0),
            "stations": max(4, stations // 2),
            "points": points,
            "chord_fn": chord_fn(c_v, taper_v),
            "spacing": "sine" if tip_frac else "linear",
        }))

    if b_h > 10 and c_h > 10:
        out.append(("Stabilizer", "tail_horizontal.stl", {
            "chord_root_mm": c_h,
            "chord_tip_mm": c_h * taper_h,
            "span_mm": b_h,
            "airfoil_key": key,
            "origin": (tail_x(c_h), 0.0, z_stab),
            "span_axis": (0.0, 1.0, 0.0),
            "thick_axis": (0.0, 0.0, 1.0),
            "stations": max(4, stations // 2),
            "symmetric": True,
            "points": points,
            "chord_fn": chord_fn(c_h, taper_h),
            "spacing": "sine" if tip_frac else "linear",
        }))
    return out


def tail_solids(res, quality=None):
    """Стабилизатор (цял размах) и кил, според типа опашка."""
    out = []
    for name, filename, spec in tail_specs(res, quality):
        mesh = surface_solid(**spec)
        if mesh.faces:
            out.append({"name": name, "file": filename, "mesh": mesh})
    return out



def wing_root_sink(res):
    """
    С колко да слязат (или вдигнат) кореновите сечения на крилото — в мм.

    Крилото минава през тялото. Ако равнината му е плътно под короната
    (високо крило) или плътно над корема (ниско), пресечната крива минава
    по ножа на водещия ръб, в ивица, където двете повърхности са на под
    милиметър. Тогава SolidCraft отказва обединението:

        the join could not be computed reliably: it would change the body
        away from the tool … refined tolerance 6.5e-1 mm

    Затова коренът се мести с ROOT_SINK_FRAC от височината на тялото
    навътре (надолу, ако е близо до короната; нагоре, ако е близо до
    корема). Средното крило е далеч от стената и не се пипа.

    Работи с произволно отместване (`layout.wing_offset_mm`), а не само с
    трите класа: важно е разстоянието до стената, не името на позицията.

    връща float (мм, отрицателно = надолу); 0.0, ако не трябва нищо.
    """
    g = res.get("geometry") or {}
    fus = g.get("fuselage") or {}
    height = float(fus.get("height_mm") or 0.0)
    if height <= 0:
        return 0.0
    z0 = layout_mod.wing_z_from_result(res)
    sink = min(ROOT_SINK_FRAC * height, ROOT_SINK_BAND * height)
    band = ROOT_SINK_BAND * height
    # Границите са включително: крило точно на ROOT_SINK_BAND от короната
    # вече гали стесняващия се фюзелаж при кореновия заден ръб (реален
    # случай: 75 % височина на 60 mm тяло → boolean-ът на лявото крило
    # пада с „could not be computed reliably“). Слягането е само за CAD.
    if height - z0 <= band:
        return -sink          # близо до короната: слиза надолу
    if z0 <= band:
        return sink           # близо до корема: вдига се нагоре
    return 0.0


def wing_spec(res, quality=None, sink_mm=0.0):
    """
    Параметрите на крилото — едно място за мрежата, STL и гладкия loft.

    `sink_mm` се подава само за CAD модела (виж `wing_root_sink`); мрежата
    и 3MF остават по проектната геометрия.
    """
    q = quality_spec(quality)
    g = res.get("geometry") or {}
    fus = g.get("fuselage") or {}
    if not g or not fus:
        return None
    height = float(fus.get("height_mm") or 0.0)
    span = float(g.get("span_mm") or 0.0)
    z_root = layout_mod.wing_z_from_result(res)
    c_root = float(g.get("c_root_mm") or 0.0)
    tip_style = g.get("tip_style", "square")
    tip_frac = float(g.get("tip_frac") or 0.0)
    dense = tip_style in ("rounded", "upturned", "winglet") and tip_frac > 0
    chord_fn = None
    if dense:
        taper = float(g.get("taper") or 1.0)
        tip_min = float(g.get("tip_min_ratio") or 0.10)

        def chord_fn(f):
            return aero.chord_at(f, c_root, taper, tip_style, tip_frac, tip_min)
    upturn = (float(aero.TIP_STYLES.get(tip_style, {}).get("upturn_deg", 0.0))
              if tip_style == "upturned" else 0.0)
    return {
        "chord_root_mm": c_root,
        "chord_tip_mm": float(g.get("c_tip_mm") or 0.0),
        "span_mm": span,
        "airfoil_key": (g.get("airfoil") or {}).get("key")
                       or airfoils.DEFAULT_AIRFOIL,
        "origin": (float(g.get("wing_le_mm") or 0.0), 0.0, z_root),
        "span_axis": (0.0, 1.0, 0.0),
        "thick_axis": (0.0, 0.0, 1.0),
        "dihedral_deg": float(g.get("dihedral_deg") or 0.0),
        "twist_deg": float(g.get("washout_deg") or 0.0),
        "stations": int(q["cad_wing"]),
        "symmetric": True,
        "points": int(q["cad_points"]),
        "chord_fn": chord_fn,
        "upturn_deg": upturn,
        "upturn_frac": tip_frac if upturn else 0.0,
        "sink_mm": float(sink_mm or 0.0),
        "sink_blend": ROOT_BLEND_FRAC,
    }


def wing_solid(res, quality=None):
    """Цялото крило като един обем (без разрез в корена)."""
    spec = wing_spec(res, quality)
    return surface_solid(**spec) if spec else printgeom.Mesh()



def winglet_specs(res, quality=None):
    """
    Уинглетите като спецификации: [(име, файл, параметри на повърхност)].

    Те са самостоятелни тела, за да може 3MF/STEP да ги именува и за да
    не се получава самопресичане с черупката на крилото.
    """
    q = quality_spec(quality)
    g = res.get("geometry") or {}
    fus = g.get("fuselage") or {}
    winglet = g.get("winglet") or {}
    if not g or not fus or not winglet.get("enabled"):
        return []
    height_mm = float(winglet.get("height_mm") or 0.0)
    if height_mm <= 0:
        return []
    c_root = float(g.get("c_root_mm") or 0.0)
    taper = float(g.get("taper") or 1.0)
    chord = float(winglet.get("chord_mm") or 0.0) or 0.6 * c_root * taper
    cant = math.radians(min(90.0, max(45.0,
                                     float(winglet.get("cant_deg", 85.0)))))
    span = float(g.get("span_mm") or 0.0)
    semi = span / 2.0
    z0 = layout_mod.wing_z_from_result(res)
    z_tip = z0 + semi * math.tan(math.radians(
        float(g.get("dihedral_deg") or 0.0)))
    key = (g.get("airfoil") or {}).get("key") or airfoils.DEFAULT_AIRFOIL
    out = []
    for sign, name, filename in ((1.0, "Winglet_R", "winglet_right.stl"),
                                 (-1.0, "Winglet_L", "winglet_left.stl")):
        span_axis = (0.0, sign * math.cos(cant), math.sin(cant))
        # коренът влиза JOIN_EMBED_MM навътре по размаха: иначе уинглетът
        # само се допира до върха на крилото и join-ът е нестабилен
        origin = (float(g.get("wing_le_mm") or 0.0) - span_axis[0] * JOIN_EMBED_MM,
                  sign * semi - span_axis[1] * JOIN_EMBED_MM,
                  z_tip - span_axis[2] * JOIN_EMBED_MM)
        out.append((name, filename, {
            "chord_root_mm": chord,
            "chord_tip_mm": chord * 0.5,
            "span_mm": height_mm + JOIN_EMBED_MM,
            "airfoil_key": key,
            "origin": origin,
            "span_axis": span_axis,
            "thick_axis": (0.0, -sign * math.sin(cant), math.cos(cant)),
            "stations": max(3, int(q["cad_wing"]) // 2),
        }))
    return out


def winglet_solids(res, quality=None):
    """Уинглетите като отделни тела в CAD модела (ляв/десен)."""
    out = []
    for name, filename, spec in winglet_specs(res, quality):
        mesh = surface_solid(**spec)
        if mesh.faces:
            out.append({"name": name, "file": filename, "mesh": mesh})
    return out



def _box(x0, x1, y0, y1, z0, z1):
    """Правоъгълна кутия като затворен обем."""
    return printgeom.prism([
        [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)],
        [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
    ])


def reference_bodies(res):
    """
    Референтни тела: батерия, серва(и), мотор, ESC, приемник, ЦТ.

    Те НЕ са част от външната форма — служат само за ориентация в CAD:
    къде стои батерията, къде са сервата, къде е центърът на тежестта.
    """
    g = res.get("geometry") or {}
    fus = g.get("fuselage") or {}
    if not fus:
        return []
    height = float(fus.get("height_mm") or 0.0)
    z_mid = height / 2.0
    out = []

    box = fus.get("battery_box_mm") or []
    stab = res.get("stability") or {}
    x_bat = stab.get("battery_x_placed_mm")
    if not x_bat:
        x_bat = stab.get("battery_x_required_mm") or 0.25 * float(
            fus.get("length_mm") or 0.0)
    if len(box) == 3 and box[0] > 0:
        out.append({
            "name": "REF_Battery", "file": "ref_battery.stl",
            "mesh": _box(x_bat - box[0] / 2.0, x_bat + box[0] / 2.0,
                         -box[1] / 2.0, box[1] / 2.0,
                         z_mid - box[2] / 2.0, z_mid + box[2] / 2.0),
            "note": "кутия на батерията по реалните размери",
        })

    info = res.get("layout") or {}
    propulsion_key = info.get("propulsion", "tractor")
    length = float(fus.get("length_mm") or 0.0)
    width = float(fus.get("width_mm") or 0.0)
    motors = int(info.get("motor_count") or 1)
    motor_x = 0.04 * length if propulsion_key != "pusher" else 0.95 * length
    for i in range(max(1, motors)):
        y = 0.0 if motors == 1 else (-1.0 if i == 0 else 1.0) * 0.35 * (
            float(g.get("span_mm") or 0.0) / 2.0)
        x = motor_x if motors == 1 else (
            float(g.get("wing_le_mm") or 0.0) + 0.25 * float(
                g.get("mac_mm") or 0.0))
        out.append({
            "name": "REF_Motor%d" % (i + 1), "file": "ref_motor_%d.stl" %
            (i + 1),
            "mesh": _box(x - 15.0, x + 15.0, y - 14.0, y + 14.0,
                         z_mid - 14.0, z_mid + 14.0),
            "note": "габарит на мотор 28×28 mm",
        })

    esc_x = 0.13 * length if propulsion_key != "pusher" else 0.82 * length
    out.append({
        "name": "REF_ESC", "file": "ref_esc.stl",
        "mesh": _box(esc_x - 20.0, esc_x + 20.0, width / 4.0 - 12.5,
                     width / 4.0 + 12.5, z_mid - 5.0, z_mid + 5.0),
        "note": "ESC 40×25×10 mm",
    })
    rx_x = 0.36 * length if propulsion_key != "pusher" else 0.40 * length
    out.append({
        "name": "REF_Receiver", "file": "ref_receiver.stl",
        "mesh": _box(rx_x - 17.5, rx_x + 17.5, -width / 4.0 - 12.5,
                     -width / 4.0 + 12.5, z_mid - 6.0, z_mid + 6.0),
        "note": "приемник 35×25×12 mm",
    })

    servo_x = 0.62 * length
    mission_key = (res.get("mission") or {}).get("key") or "trainer"
    servo_count, servo_mass = propulsion.servo_plan(mission_key)
    servo_size = (REF_SERVO_LARGE if servo_mass >= 15.0
                  else REF_SERVO_SMALL)
    for side, suffix in ((-1.0, "R"), (1.0, "L")):
        y = side * width / 3.0
        out.append({
            "name": "REF_Servo_%s" % suffix,
            "file": "ref_servo_%s.stl" % suffix.lower(),
            "mesh": _box(servo_x - servo_size[0] / 2.0,
                         servo_x + servo_size[0] / 2.0,
                         y - servo_size[1] / 2.0, y + servo_size[1] / 2.0,
                         z_mid - servo_size[2] / 2.0,
                         z_mid + servo_size[2] / 2.0),
            "note": "серва %.0f g: %.0f×%.0f×%.0f mm (%d общо)"
                    % (servo_mass, servo_size[0], servo_size[1],
                       servo_size[2], servo_count),
        })

    cg = stab.get("x_cg_mm")
    if cg:
        out.append({
            "name": "REF_CG", "file": "ref_cg.stl",
            "mesh": _box(cg - 4.0, cg + 4.0, -4.0, 4.0,
                         z_mid - 4.0, z_mid + 4.0),
            "note": "център на тежестта (4 mm маркер)",
        })
    return out


def build_assembly(res, quality=None):
    """
    Целият самолет като списък от плътни тела в самолетни координати.

    връща [{"name", "file", "mesh", "kind"}] — kind е "body" за външната
    форма. Това е моделът, който отива в 3MF/STEP.
    Плътността идва от нивото за качество (cad_*).
    """
    if not res or not res.get("ok"):
        return []
    parts = []
    wing = wing_solid(res, quality)
    if wing.faces:
        parts.append({"name": "Wing", "file": "wing.stl", "mesh": wing,
                      "kind": "body"})
    fus = fuselage_solid(res, quality=quality)
    if fus.faces:
        parts.append({"name": "Fuselage", "file": "fuselage.stl",
                      "mesh": fus, "kind": "body"})
    for item in tail_solids(res, quality):
        parts.append({"name": item["name"], "file": item["file"],
                      "mesh": item["mesh"], "kind": "body"})
    for item in winglet_solids(res, quality):
        parts.append({"name": item["name"], "file": item["file"],
                      "mesh": item["mesh"], "kind": "body"})
    spin = spinner_solids(res, quality)
    for item in spin:
        parts.append(item)
    return parts


def _wing_section_ring(res, s, unit, symmetric=True):
    """Контур на крилото при позиция s по размаха (mm, 3D)."""
    g = res.get("geometry") or {}
    fus = g.get("fuselage") or {}
    height = float(fus.get("height_mm") or 0.0)
    span = float(g.get("span_mm") or 0.0)
    semi = span / 2.0
    c_root = float(g.get("c_root_mm") or 0.0)
    c_tip = float(g.get("c_tip_mm") or 0.0)
    dihedral = float(g.get("dihedral_deg") or 0.0)
    z0 = layout_mod.wing_z_from_result(res)
    x_le = float(g.get("wing_le_mm") or 0.0)
    ratio = min(1.0, abs(s) / semi) if semi > 0 else 0.0
    chord = aero.chord_at(ratio, c_root, float(g.get("taper") or 1.0),
                          g.get("tip_style", "square"),
                          g.get("tip_frac"),
                          float(g.get("tip_min_ratio") or 0.10))
    twist = float(g.get("washout_deg") or 0.0) * ratio
    rise = abs(s) * math.tan(math.radians(dihedral))
    ring = []
    for u, v in unit:
        lx, lz = _rotated(u, v, chord, twist)
        ring.append((x_le + lx, s, z0 + lz + rise))
    return ring


def nose_revolve(res):
    """
    Носът (спинер + каулинг) като **един** профил за `solid.revolve`.

    Две co-axial тела означават два boolean-а с тялото, а всеки boolean е
    място, където SolidCraft може да виси. Един профил дава един чист
    конус, който влиза в тялото с една кръгова пресечна крива.

    връща {"name": "Nose", "kind": "revolve", "axis", "plane", "profile"}
    или None (бутащо витло, без нос).
    """
    params = fairing_mod.spinner_params(res)
    if not params:
        return None
    z = float(params["z_center"])
    x_tip = float(params["x_tip"])
    x_base = float(params["x_base"])
    r_spin = max(1.0, float(params["radius"]))
    x_c1 = float(params["x_cowl1"])
    r_c1 = max(0.5, float(params["r_cowl1"]))
    if x_c1 <= x_base or r_c1 <= r_spin:
        return None
    return {
        "name": "Nose", "kind": "revolve", "axis": "x",
        "plane": {"origin": (0.0, 0.0, z), "x_dir": (1.0, 0.0, 0.0),
                  "y_dir": (0.0, 1.0, 0.0)},
        "profile": [(x_tip, 0.0), (x_base, 0.0), (x_base, r_spin),
                    (x_c1, r_c1), (x_c1, 0.0)],
        "parts": ["Spinner", "Cowl"],
    }


def spinner_revolves(res):
    """
    Спинер и каулинг като профили за `solid.revolve` (ос X през z_center).

    Профилът е в равнината XY при z = z_center; оста е скицовата X ос.
    """
    params = fairing_mod.spinner_params(res)
    if not params:
        return []
    z = float(params["z_center"])
    plane = {"origin": (0.0, 0.0, z), "x_dir": (1.0, 0.0, 0.0),
             "y_dir": (0.0, 1.0, 0.0)}
    x_tip = float(params["x_tip"])
    x_base = float(params["x_base"])
    r_spin = max(1.0, float(params["radius"]))
    out = [{
        "name": "Spinner", "kind": "revolve", "axis": "x",
        "plane": plane,
        "profile": [(x_tip, 0.0), (x_base, 0.0), (x_base, r_spin)],
    }]
    x_c0 = float(params["x_cowl0"])
    x_c1 = float(params["x_cowl1"])
    r_c1 = max(0.5, float(params["r_cowl1"]))
    out.append({
        "name": "Cowl", "kind": "revolve", "axis": "x",
        "plane": plane,
        "profile": [(x_c0, 0.0), (x_c1, 0.0), (x_c1, r_c1), (x_c0, r_spin)],
    })
    return out


def half_rings(spec, sign, points=None, stations=None, spacing="sine",
               sink_mm=None, root_overlap_mm=None, root_start_mm=None):
    """
    Сечения на една половина от симетрична повърхност (крило, стабилизатор).

    Симетричната повърхност минава през цялото тяло: излиза от двете му
    страни, пресечната крива става от две дъги и SolidCraft не се справя с
    този boolean (виси или отказва — проверено с реалния CLI). Затова CAD
    моделът строи две половини с разрез в y = 0: коренът им е вътре в
    тялото, всяко обединяване е една чиста дъга. Точно така би го направил
    и човек — едната половина, после mirror.

    `root_overlap_mm` вкарва корена на половината толкова mm **отвъд**
    оста, така че двете половини се застъпват, вместо да се допират с лица
    по оста. Допиращите се лица са нестабилен boolean; застъпването е
    същото правило, по което телата в модела ползват `JOIN_EMBED_MM`.
    `root_start_mm` задава началната станция на корена по размаха (за луфт
    към тялото). Върхът не мърда.

    `sign` = +1 дясна, -1 лява половина.
    """
    axis = spec.get("span_axis") or (0.0, 1.0, 0.0)
    half = dict(spec)
    half["symmetric"] = False
    half["span_mm"] = max(1.0, float(spec.get("span_mm") or 0.0) / 2.0)
    half["span_axis"] = (float(axis[0]) * sign, float(axis[1]) * sign,
                         float(axis[2]) * sign)
    if root_start_mm is not None:
        half["start_mm"] = float(root_start_mm)
    elif root_overlap_mm:
        half["start_mm"] = -abs(float(root_overlap_mm))
    if points is not None:
        half["points"] = int(points)
    if stations is not None:
        half["stations"] = int(stations)
    if spacing:
        half["spacing"] = spacing
    if sink_mm is not None:
        half["sink_mm"] = float(sink_mm)
    return surface_rings(**half)


def wing_root_fairing(sections, half_span_mm, fade_span_mm=None):
    """
    Root fairing for the CAD loft: chord and thickness are enlarged at the
    root and fade smoothly back to the chosen profile by `fade_span_mm` along
    the span. It does not move sections (origin stays) and does not move the
    tip - only scales each section's outline in its sketch plane about the
    quarter chord and the mid-thickness, so the quarter chord stays put.
    Used for the CAD loft only; print mesh (STL/3MF) and SVG sections are
    unchanged.

    returns a new list of sections; each scaled section carries
    `root_fairing = {"chord_scale", "thick_scale"}`.
    """
    if not sections:
        return list(sections)
    half_span_mm = max(1e-9, float(half_span_mm or 0.0))
    fade = (float(fade_span_mm) if fade_span_mm is not None
            else ROOT_FAIRING_FADE_FRAC * half_span_mm)
    fade = max(1e-9, fade)
    # Разстояние от корена: при застъпване първото сечение е с отрицателна
    # станция и трябва да получи пълния мащаб, а не намален.
    root_station = float(sections[0].get("station_mm") or 0.0)
    out = []
    for section in sections:
        station = abs(float(section.get("station_mm") or 0.0) - root_station)
        w = max(0.0, 1.0 - station / fade)
        if w <= 0.0:
            out.append(section)
            continue
        chord_scale = 1.0 + (ROOT_FAIRING_CHORD_RATIO - 1.0) * w
        thick_scale = 1.0 + (ROOT_FAIRING_THICK_RATIO - 1.0) * w
        pts2d = section.get("points2d") or []
        if not pts2d:
            out.append(section)
            continue
        xs = [p[0] for p in pts2d]
        # Мащабирай около четвърт-хордата: аеродинамичният център не мърда,
        # хордата расте напред и назад.
        cx = min(xs) + 0.25 * (max(xs) - min(xs))
        cz = 0.5 * (min(p[1] for p in pts2d) + max(p[1] for p in pts2d))
        fair2d = [(cx + (p[0] - cx) * chord_scale,
                   cz + (p[1] - cz) * thick_scale) for p in pts2d]
        origin = section.get("origin") or (0.0, 0.0, 0.0)
        x_dir = section.get("x_dir") or (1.0, 0.0, 0.0)
        y_dir = section.get("y_dir") or (0.0, 1.0, 0.0)
        fair3d = [(origin[0] + x_dir[0] * q[0] + y_dir[0] * q[1],
                   origin[1] + x_dir[1] * q[0] + y_dir[1] * q[1],
                   origin[2] + x_dir[2] * q[0] + y_dir[2] * q[1])
                  for q in fair2d]
        new = dict(section)
        new["points2d"] = fair2d
        new["points3d"] = fair3d
        new["root_fairing"] = {"chord_scale": chord_scale,
                               "thick_scale": thick_scale}
        out.append(new)
    return out


AILERON_CUTTER_STATIONS = 4      # сечения на призмата по размаха
AILERON_CUTTER_TE_MM = 15.0      # призмата излиза зад задния ръб
AILERON_CUTTER_Z_MM = 30.0       # и над/под профила (диедър, усукване)


def _faired_chord_x(x_local, chord, station, root_station, half_span_mm):
    """
    Къде отива точка от хордата след `wing_root_fairing` (мащаб около
    четвърт-хордата в корена, затихва по размаха) — за да следва
    резачът на елерона реалната CAD хорда и до корена.
    """
    fade = max(1e-9, ROOT_FAIRING_FADE_FRAC * half_span_mm)
    w = max(0.0, 1.0 - abs(station - root_station) / fade)
    scale = 1.0 + (ROOT_FAIRING_CHORD_RATIO - 1.0) * w
    cx = 0.25 * chord
    return cx + (x_local - cx) * scale


def aileron_cutters(res, spec, sign, wing_name, root_start_mm=None):
    """
    Резачите за елерона на една половина на крилото (за SolidCraft).

    Връща две тела-призми зад линията на пантата:
      * `Aileron_<R|L>` — от пантата + процепа до зад задния ръб, скъсено
        в двата края с процепа; сечението му с крилото е елеронът
        (`op: intersect`, крилото се запазва);
      * `Aileron_Slot_<R|L>` — от пантата до зад задния ръб, по цялата
        дължина на елерона; изрязва се от крилото (`op: cut`) и оставя
        процепа около елерона.

    Хордата, диедърът и станциите са като в `surface_rings` за същата
    половина, така че линията на пантата е на `1 - chord_frac` от
    местната хорда.
    """
    g = res.get("geometry") or {}
    ail = g.get("ailerons") or {}
    if not ail.get("enabled") or not spec:
        return []
    semi = float(spec.get("span_mm") or 0.0) / 2.0
    if semi <= 1.0:
        return []
    start = float(root_start_mm or 0.0)
    c_root = float(spec["chord_root_mm"])
    c_tip = float(spec["chord_tip_mm"])
    chord_fn = spec.get("chord_fn")
    tan_dih = math.tan(math.radians(float(spec.get("dihedral_deg") or 0.0)))
    origin = spec["origin"]
    cf = float(ail.get("chord_frac") or 0.2)
    gap = float(ail.get("hinge_gap_mm") or 0.0)
    end_gap = float(ail.get("end_gap_mm") or 0.0)
    y0 = float(ail.get("y_start_mm") or 0.0)
    y1 = float(ail.get("y_end_mm") or 0.0)
    if y1 - y0 <= 2.0 * end_gap + 5.0 or y0 <= start:
        return []

    def section_at(y, hinge_offset, index):
        f = (y - start) / max(1e-9, semi - start)
        chord = (chord_fn(f) if chord_fn is not None
                 else c_root + (c_tip - c_root) * f)
        hinge = _faired_chord_x((1.0 - cf) * chord, chord, y, start, semi)
        te = _faired_chord_x(chord, chord, y, start, semi)
        x0 = origin[0] + hinge + hinge_offset
        x1 = origin[0] + te + AILERON_CUTTER_TE_MM
        zc = origin[2] + y * tan_dih
        dz = 0.5 * chord + AILERON_CUTTER_Z_MM
        pts2d = [(x0, zc - dz), (x1, zc - dz), (x1, zc + dz), (x0, zc + dz)]
        yy = sign * y
        return {
            "name": "S%02d" % (index + 1),
            "points2d": pts2d,
            "points3d": [(px, yy, pz) for px, pz in pts2d],
            "origin": (0.0, yy, 0.0),
            "x_dir": (1.0, 0.0, 0.0),
            "y_dir": (0.0, 0.0, 1.0),
            "station_mm": yy,
            "split": None,
            "primitive": {"type": "polygon"},
        }

    def prism(ya, yb, hinge_offset):
        n = AILERON_CUTTER_STATIONS
        return [section_at(ya + (yb - ya) * i / n, hinge_offset, i)
                for i in range(n + 1)]

    side = "R" if sign > 0 else "L"
    name = "Aileron_%s" % side
    slot = "Aileron_Slot_%s" % side
    return [
        {"name": name, "kind": "loft", "cutter": True,
         "sections": prism(y0 + end_gap, y1 - end_gap, gap),
         "op": "intersect", "with": wing_name, "after": wing_name},
        {"name": slot, "kind": "loft", "cutter": True,
         "sections": prism(y0, y1, 0.0),
         "op": "cut", "from": wing_name, "after": name},
    ]


def shift_rings(sections, dz):
    """
    Отмества сечения по световно Z (цялото тяло, без затихване).

    Ползва се за хоризонталната опашка: тя лежи точно на линията на най-
    голямата ширина на тялото (z = височина/2), където стената е отвесна и
    пресечната крива минава по ножа на водещия ръб. Малко отместване нагоре
    изкарва ръба от тази линия и обединяването минава.
    """
    if not dz:
        return sections
    out = []
    for section in sections:
        moved = dict(section)
        moved["origin"] = (section["origin"][0], section["origin"][1],
                           section["origin"][2] + dz)
        moved["points3d"] = [(p[0], p[1], p[2] + dz)
                             for p in section["points3d"]]
        out.append(moved)
    return out


def loft_bodies(res, quality=None, detail=None, joins=True, split=True,
                sink_mm=None, exact_tail=False, nose_one_piece=False,
                tail_lift_mm=None, join_tail=False,
                wing_root_gap_mm=None, tail_root_gap_mm=None):
    """
    Телата за гладкия loft в SolidCraft: сечения + равнини на скиците.

    За разлика от `build_assembly` (триъгълна мрежа) тук всяко тяло е
    списък от гладки сечения, по които SolidCraft прави BSpline loft.
    `detail` задава плътността на сеченията (точки/станции) — гладката
    повърхност не зависи от бюджета на триъгълниците.

    `joins=True` (по подразбиране) подготвя модела за обединяване:
    коренът на крилото сяда в тялото (`wing_root_sink`), а всяко тяло
    носи `into` — името на тялото, в което се влива. Така SolidCraft
    строи един solid още в историята, вместо да чака ръчен boolean.

    `split=True` строи симетричните повърхности на две половини (крило,
    стабилизатор) — виж `half_rings`; `split=False` ги прави цели.

    `exact_tail=True` ползва планформата на опашката от дизайна (прав/
    трапец/елипса) и в CAD модела; по подразбиране там е трапец с прав
    срез, защото елипсата добавя сечения и забавя boolean-а.

    връща [{"name", "kind": "loft", "sections", "into"?, "embed_mm"?} |
           {"name", "kind": "revolve", "plane", "axis", "profile", "into"?}]
    """
    if not res or not res.get("ok"):
        return []
    d = detail or {}
    points = int(d.get("points") or 40)
    stations = int(d.get("stations") or 12)
    fus_ring = int(d.get("fuselage_ring") or 32)
    fus_stations = int(d.get("fuselage_stations") or 12)
    tail_stations = int(d.get("tail_stations") or 8)
    out = []
    sink = (wing_root_sink(res) if sink_mm is None else float(sink_mm)) \
        if joins else 0.0

    # Тялото е основата: всичко останало се влива в него, в този ред.
    sections = fuselage_rings(res, rings=fus_ring, stations=fus_stations,
                              t_start=0.0)
    if sections:
        out.append({"name": "Fuselage", "kind": "loft",
                    "sections": sections})

    wing_gap = max(0.0, min(40.0, float(
        (res.get("layout") or {}).get("wing_root_gap_mm", 10.0) or 0.0)))
    tail_gap = max(0.0, min(40.0, float(
        (res.get("layout") or {}).get("tail_root_gap_mm", 10.0) or 0.0)))
    if wing_root_gap_mm is not None:
        wing_gap = max(0.0, min(40.0, float(wing_root_gap_mm)))
    if tail_root_gap_mm is not None:
        tail_gap = max(0.0, min(40.0, float(tail_root_gap_mm)))

    if joins:
        nose = nose_revolve(res) if nose_one_piece else None
        if nose:
            nose["into"] = "Fuselage"
            out.append(nose)
        else:
            # Каулингът и спинерът влизат в тялото (след join тяхното име
            # изчезва — не може да е цел на друг join). Редът е важен:
            # каулингът първо, спинерът след него (`after`).
            for body in spinner_revolves(res):
                body["into"] = "Fuselage"
                if body["name"] == "Spinner":
                    body["after"] = "Cowl"
                out.append(body)

    spec = wing_spec(res, quality, sink_mm=sink)
    if spec:
        fuselage = (res.get("geometry") or {}).get("fuselage") or {}
        # Коренът стъпва на обшивката в станцията на крилото (+ луфт), а не
        # на максималната полуширина на тялото.
        wing_root = (skin_offset(fuselage, spec["origin"][0], (0.0, 1.0, 0.0))
                     + wing_gap) if (joins and wing_gap > 0) else 0.0
        if split or (joins and wing_gap > 0):
            # две половини: boolean-ът с цялото крило минава през тялото и
            # SolidCraft не го смята (виж `half_rings`)
            for sign, name in ((1.0, "Wing_R"), (-1.0, "Wing_L")):
                # коренът започва на кожа + луфт; двете половини са
                # отделни тела с плоска страна, без мостове
                sections = half_rings(
                    spec, sign, points, stations, "sine",
                    root_overlap_mm=0.0,
                    root_start_mm=(wing_root if wing_root > 0 else None))
                if not sections:
                    continue
                sections = wing_root_fairing(sections, spec["span_mm"] / 2.0)
                body = {"name": name, "kind": "loft", "sections": sections}
                if joins and wing_gap <= 0:
                    body["into"] = "Fuselage"
                    body["embed_mm"] = sink
                out.append(body)
                # елеронът се изрязва от своята половина (intersect + cut)
                out.extend(aileron_cutters(
                    res, spec, sign, name,
                    root_start_mm=(wing_root if wing_root > 0 else 0.0)))
        else:
            sections = surface_rings(**dict(spec, points=points,
                                            stations=stations,
                                            spacing="sine",
                                            start_mm=wing_root))
            sections = wing_root_fairing(sections, spec["span_mm"] / 2.0)
            if sections:
                body = {"name": "Wing", "kind": "loft", "sections": sections}
                if joins and wing_gap <= 0:
                    body["into"] = "Fuselage"
                    body["embed_mm"] = sink
                out.append(body)

    for name, _filename, spec in winglet_specs(res, quality):
        sections = surface_rings(**dict(spec, points=points,
                                        stations=max(3, stations // 2),
                                        spacing="sine"))
        if sections:
            body = {"name": name, "kind": "loft", "sections": sections}
            if joins:
                # уинглетът се влива в своята половина на крилото, не в
                # тялото: по-малък boolean, по-малко пачове
                side = "R" if name.endswith("_R") else "L"
                body["into"] = "Wing_%s" % side if split else "Wing"
                body["embed_mm"] = JOIN_EMBED_MM
            out.append(body)

    tail_type = (res.get("layout") or {}).get("tail_type", "conventional")
    fuselage = (res.get("geometry") or {}).get("fuselage") or {}
    fin_raise = 0.0
    for name, _filename, spec in tail_specs(res, quality,
                                            exact=exact_tail):
        if name == "Fin" and joins:
            # Коренът на кила стъпва на обшивката в неговата станция, а не
            # на максималната височина на тялото (то се стеснява към опашката).
            fin_raise = (skin_offset(fuselage, spec["origin"][0],
                                     (0.0, 0.0, 1.0)) + tail_gap)
            sections = surface_rings(**dict(
                spec, points=points, stations=tail_stations,
                spacing="sine", start_mm=fin_raise))
            if sections:
                out.append({"name": name, "kind": "loft",
                            "sections": sections})
            continue
        if spec.get("symmetric") and (split or (joins and tail_gap > 0)):
            height = float(fuselage.get("height_mm") or 0.0)
            into = None          # None = стабилизаторът остава отделно тяло
            root_start = 0.0
            root_overlap = 0.0
            shift = 0.0
            if joins and tail_type == "t_tail":
                # лежи на върха на кила: мести се заедно с кила, а не с
                # тялото; 3 mm застъпване идва от z_stab в `tail_specs`
                shift = fin_raise
                if join_tail:
                    into = "Fin"
            elif joins and (join_tail or tail_gap <= 0.0):
                # обединено: коренът влиза в тялото (изрично или защото
                # луфтът е 0)
                into = "Fuselage"
                root_overlap = JOIN_EMBED_MM
                shift = (float(tail_lift_mm) if tail_lift_mm is not None
                         else ROOT_SINK_FRAC * height)
            elif joins:
                # отделно тяло на кожа + луфт; вдига се над линията на
                # най-голямата ширина, за да не минава по ножа на водещия ръб
                root_start = (skin_offset(fuselage, spec["origin"][0],
                                          (0.0, 1.0, 0.0))
                              + tail_gap)
                shift = (float(tail_lift_mm) if tail_lift_mm is not None
                         else ROOT_SINK_FRAC * height)
            for sign, half_name in ((1.0, "%s_R" % name),
                                    (-1.0, "%s_L" % name)):
                sections = half_rings(
                    spec, sign, points, tail_stations, "sine",
                    root_overlap_mm=root_overlap,
                    root_start_mm=(root_start if root_start > 0 else None))
                if not sections:
                    continue
                sections = shift_rings(sections, shift)
                body = {"name": half_name, "kind": "loft",
                        "sections": sections}
                if into:
                    body["into"] = into
                    body["embed_mm"] = JOIN_EMBED_MM
                out.append(body)
            continue
        # V-опашка (два наклонени панела): луфтът се мери по оста на панела
        # от обшивката, а не от централната линия.
        gap = (0.0 if (joins and join_tail)
               else (tail_gap if joins else 0.0))
        start = 0.0
        if gap > 0 and name.startswith("Stabilizer_V"):
            start = (skin_offset(fuselage, spec["origin"][0],
                                 spec["span_axis"]) + gap)
        sections = surface_rings(**dict(
            spec, points=points, stations=tail_stations, spacing="sine",
            start_mm=start))
        if sections:
            body = {"name": name, "kind": "loft", "sections": sections}
            if joins and gap <= 0:
                body["into"] = "Fuselage"
            out.append(body)

    if joins:
        return out
    if not any(b["kind"] == "revolve" for b in out):
        out.extend(spinner_revolves(res))
    return out


def sections(res, wing_stations=5, fuselage_stations=9):
    """
    Сечения за CAD: крило (за гладък лофт) и тяло (за станции).

    връща {"wing": [{"name","y_mm","points"}], "fuselage": [...]}
    """
    g = res.get("geometry") or {}
    fus = g.get("fuselage") or {}
    if not g or not fus:
        return {"wing": [], "fuselage": []}
    unit = _unit_outline((g.get("airfoil") or {}).get("key")
                         or airfoils.DEFAULT_AIRFOIL)
    span = float(g.get("span_mm") or 0.0)
    semi = span / 2.0
    out = {"wing": [], "fuselage": []}
    n = max(2, int(wing_stations))
    for i in range(2 * n + 1):
        s = -semi + span * i / (2.0 * n)
        ring = _wing_section_ring(res, s, unit)
        if ring:
            out["wing"].append({"name": "W%02d" % (i + 1),
                                "y_mm": round(s, 2), "points": ring})
    length = float(fus.get("length_mm") or 0.0)
    height = float(fus.get("height_mm") or 0.0)
    m = max(2, int(fuselage_stations))
    for i in range(m + 1):
        t = 0.02 + 0.98 * i / m
        ring = [(t * length, y, v + height / 2.0)
                for (y, v) in fus_mod.outline(fus, t, 24)]
        out["fuselage"].append({"name": "F%02d" % (i + 1),
                                "x_mm": round(t * length, 1), "points": ring})
    return out
