"""
propeller.py — витло за 3D печат от APC геометрия (*.PE0 / *-PERF.PE0).

Какво прави:
  * чете APC геометрията (радиус, хъб, брой перки, таблица по станции);
  * оценява обем, маса и разход за печат;
  * проверява натоварването на печатаното витло: центробежно напрежение
    в корена и обиколна скорост на върха;
  * пише STL на перката (без хъб; хъбът се проектира отделно).

Важно: всички прагове и якости в този файл са ОРИЕНТИРОВЪЧНИ, а не
валидирани. Печатано витло не е проверено за полет. Преди полет
витлото се тества на стенд и се претегля.

Единици: APC файловете са в инчове; вътрешно се работи в mm, kg, s, Pa.
"""

import math
import re
import struct

MM_PER_IN = 25.4

# Ориентировъчни стойности за печатан материал. Якостта при печат
# (по слоеве) е по-ниска от обемната и силно зависи от настройките.
PRINT_MATERIALS = {
    "pla": {"label": "PLA", "density_g_cm3": 1.24, "allow_mpa": 12.0,
            "price_eur_kg": 20.0},
    "petg": {"label": "PETG", "density_g_cm3": 1.27, "allow_mpa": 9.0,
             "price_eur_kg": 22.0},
}

# Прагове (консервативни: печатаното витло е с ниска умора и вибрира).
# Обиколна скорост ~106 m/s е типична за 10" при 8000 rpm — предупреждава.
TIP_SPEED_WARN_MS = 90.0
TIP_SPEED_ERROR_MS = 120.0
STRESS_WARN_RATIO = 0.4    # σ / allow > 0.4 → предупреждение (SF < 2.5)
STRESS_ERROR_RATIO = 0.67  # σ / allow > 0.67 → грешка (SF < 1.5)

_STATION_COLUMNS = 14
_NUM = r"[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?"


class PropellerError(ValueError):
    """Файлът не е APC геометрия или е празен."""


def _header_value(text, key):
    match = re.search(key + r"\s*[:=]?\s*(" + _NUM + r")", text)
    return float(match.group(1)) if match else None


def parse_geometry(text):
    """
    Разбира APC геометрията. Връща dict:
      radius_in, hub_radius_in, blades, stations (списък от dict),
      file_mass_kg, file_volume_in3 (ако са в файла).
    Станциите са само тези с r >= hub_radius.
    """
    if not text or "STATION" not in text:
        raise PropellerError("Липсва таблица STATION — не е APC геометрия.")

    radius = _header_value(text, "RADIUS")
    hub = _header_value(text, "HUBRAD")
    blades = _header_value(text, "BLADES")
    if not radius or hub is None or not blades:
        raise PropellerError("Липсват RADIUS / HUBRAD / BLADES в заглавието.")

    stations = []
    in_table = False
    for line in text.splitlines():
        if "STATION" in line:
            in_table = True
            continue
        if not in_table:
            continue
        parts = line.split()
        if len(parts) != _STATION_COLUMNS:
            if stations and "-----" in line:
                break
            continue
        try:
            values = [float(p) for p in parts]
        except ValueError:
            continue
        (r, chord, pitch_q, pitch_le, pitch_pr, sweep, rake, t_ratio,
         twist, max_thick, area, zhigh, cgy, cgz) = values
        if r + 1e-9 < hub:
            continue
        stations.append({
            "r_in": r, "chord_in": chord, "pitch_in": pitch_q,
            "twist_deg": twist, "thickness_ratio": t_ratio,
            "area_in2": area, "max_thick_in": max_thick,
        })

    if len(stations) < 3:
        raise PropellerError("Твърде малко станции в таблицата.")

    return {
        "radius_in": radius,
        "hub_radius_in": hub,
        "blades": int(round(blades)),
        "stations": stations,
        "file_mass_kg": _header_value(text, r"TOTAL WEIGHT \(Kg\)"),
        "file_volume_in3": _header_value(text, r"TOTAL VOLUME \(IN\*\*3\)"),
    }


def _integrate(xs, ys):
    total = 0.0
    for i in range(1, len(xs)):
        total += 0.5 * (ys[i] + ys[i - 1]) * (xs[i] - xs[i - 1])
    return total


def blade_volume_mm3(geom):
    """Обем на една перка (mm³) от интеграла на напречното сечение."""
    st = geom["stations"]
    rs = [s["r_in"] * MM_PER_IN for s in st]
    areas = [s["area_in2"] * MM_PER_IN ** 2 for s in st]
    return _integrate(rs, areas)


def estimate_print(geom, material="pla", infill=1.0):
    """
    Маса и цена за печат на всички перки (без хъб).
    infill: 1.0 = плътно (горна граница за здравина); по-ниско = по-леко,
    но по-слабо. Маската е груба — реалната маса зависи от слайсера.
    """
    if material not in PRINT_MATERIALS:
        raise PropellerError("Непознат материал: %s" % material)
    mat = PRINT_MATERIALS[material]
    infill = min(max(float(infill), 0.1), 1.0)

    vol_mm3 = blade_volume_mm3(geom) * geom["blades"]
    vol_cm3 = vol_mm3 / 1000.0
    mass_g = vol_cm3 * mat["density_g_cm3"] * infill
    cost = mass_g / 1000.0 * mat["price_eur_kg"]
    return {
        "material": material,
        "volume_cm3": vol_cm3,
        "mass_g": mass_g,
        "cost_eur": cost,
        "infill": infill,
    }


def root_stress_mpa(geom, rpm, material="pla"):
    """
    Центробежно напрежение в корена на перката (MPa).
    σ(r0) = ρ ω² ∫_{r0}^{R} A(s)·s ds / A(r0)  — за една перка.
    """
    mat = PRINT_MATERIALS[material]
    omega = rpm * 2.0 * math.pi / 60.0
    rho = mat["density_g_cm3"] * 1000.0  # kg/m³
    st = geom["stations"]
    rs = [s["r_in"] * MM_PER_IN / 1000.0 for s in st]     # m
    areas = [s["area_in2"] * (MM_PER_IN / 1000.0) ** 2 for s in st]  # m²
    if areas[0] <= 0:
        raise PropellerError("Нулево сечение в корена.")
    moment = _integrate(rs, [a * r for a, r in zip(areas, rs)])
    sigma_pa = rho * omega ** 2 * moment / areas[0]
    return sigma_pa / 1e6


def check_flight_load(geom, rpm, material="pla"):
    """
    Проверки за натоварване на печатаното витло. Връща списък от
    dict(level, title, detail). Всички прагове са ориентировъчни.
    """
    if rpm is None or rpm <= 0:
        raise PropellerError("Оборотите трябва да са положителни.")
    if material not in PRINT_MATERIALS:
        raise PropellerError("Непознат материал: %s" % material)
    mat = PRINT_MATERIALS[material]
    checks = []

    radius_m = geom["radius_in"] * MM_PER_IN / 1000.0
    tip = 2.0 * math.pi * radius_m * rpm / 60.0
    tip_detail = "%.0f m/s при %d rpm (диаметър %.1f in)" % (
        tip, rpm, 2 * geom["radius_in"])
    if tip >= TIP_SPEED_ERROR_MS:
        level = "error"
    elif tip >= TIP_SPEED_WARN_MS:
        level = "warn"
    else:
        level = "ok"
    checks.append({"level": level, "title": "Обиколна скорост на върха",
                   "detail": tip_detail})

    sigma = root_stress_mpa(geom, rpm, material)
    ratio = sigma / mat["allow_mpa"]
    if ratio >= STRESS_ERROR_RATIO:
        level = "error"
    elif ratio >= STRESS_WARN_RATIO:
        level = "warn"
    else:
        level = "ok"
    checks.append({
        "level": level,
        "title": "Центробежно напрежение в корена (%s)" % mat["label"],
        "detail": "%.1f MPa срещу ориентировъчна якост %.0f MPa "
                  "(съотношение %.2f)" % (sigma, mat["allow_mpa"], ratio),
    })

    checks.append({
        "level": "warn",
        "title": "Не е проверено за полет",
        "detail": "Печатано витло трябва да се тества на стенд и да се "
                  "претегли преди полет. Разрушено витло е опасно.",
    })
    return checks


def fits_bed(geom, bed_mm):
    """
    Перката, отпечатана плоска (една перка), по дължина и хорда.
    bed_mm: (x, y, z) в mm. Връща dict с размерите и fits.
    """
    st = geom["stations"]
    length_mm = (geom["radius_in"] - geom["hub_radius_in"]) * MM_PER_IN
    chord_mm = max(s["chord_in"] for s in st) * MM_PER_IN
    thick_mm = max(s["max_thick_in"] for s in st) * MM_PER_IN
    fits = (length_mm <= bed_mm[0] and chord_mm <= bed_mm[1]
            and thick_mm <= bed_mm[2])
    return {"length_mm": length_mm, "chord_mm": chord_mm,
            "thick_mm": thick_mm, "fits": fits}


def _thickness_fraction(x, t_ratio):
    """Симетрично NACA-подобно разпределение на дебелината (относит. към хордата)."""
    x = min(max(x, 0.0), 1.0)
    yt = 5.0 * t_ratio * (0.2969 * math.sqrt(x) - 0.1260 * x
                          - 0.3516 * x * x + 0.2843 * x ** 3
                          - 0.1015 * x ** 4)
    return max(yt, 0.0)


def _section_ring(st, n_pts=12):
    """Точки на напречното сечение (mm) по станция — в локалната му равнина."""
    r = st["r_in"] * MM_PER_IN
    c = st["chord_in"] * MM_PER_IN
    # helix angle: tan β = стъпка / (2π r), всичко в инчове
    beta = math.atan2(st["pitch_in"], 2 * math.pi * st["r_in"])
    # Хордата лежи в равнината на въртене, наклонена с β; нормалата е
    # перпендикулярна на нея и на радиалната ос (X).
    c_dir = (0.0, math.cos(beta), -math.sin(beta))
    n_dir = (0.0, math.sin(beta), math.cos(beta))
    xs = [0.5 - 0.5 * math.cos(math.pi * k / (n_pts - 1)) for k in range(n_pts)]
    upper, lower = [], []
    for x in xs:
        u = (x - 0.5) * c
        yt = _thickness_fraction(x, st["thickness_ratio"]) * c
        upper.append((r, u * c_dir[1] + yt * n_dir[1],
                      u * c_dir[2] + yt * n_dir[2]))
        lower.append((r, u * c_dir[1] - yt * n_dir[1],
                      u * c_dir[2] - yt * n_dir[2]))
    # затворен контур: горна повърхност от LE към TE, после долна обратно
    ring = upper + list(reversed(lower[1:-1]))
    return ring


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _normal(p1, p2, p3):
    n = _cross(_sub(p2, p1), _sub(p3, p1))
    length = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) or 1.0
    return (n[0] / length, n[1] / length, n[2] / length)


def blade_triangles(geom, n_pts=12):
    """Триъгълници на една перка (mm). Без хъб; корен и връх са затворени."""
    st = geom["stations"]
    rings = [_section_ring(s, n_pts) for s in st]
    tris = []
    for i in range(len(rings) - 1):
        a, b = rings[i], rings[i + 1]
        m = len(a)
        for k in range(m):
            k2 = (k + 1) % m
            tris.append((a[k], a[k2], b[k2]))
            tris.append((a[k], b[k2], b[k]))
    # капаци в корена и на върха (вентилатор от центроида)
    for ring, flip in ((rings[0], True), (rings[-1], False)):
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        cz = sum(p[2] for p in ring) / len(ring)
        center = (cx, cy, cz)
        for k in range(len(ring)):
            k2 = (k + 1) % len(ring)
            tri = (center, ring[k], ring[k2]) if not flip else \
                (center, ring[k2], ring[k])
            tris.append(tri)
    return tris


def write_stl(path, geom, blades=None, n_pts=12):
    """Двоичен STL на всички перки (повторени около оста Z)."""
    base = blade_triangles(geom, n_pts)
    count = blades or geom["blades"]
    all_tris = []
    for b in range(count):
        ang = 2.0 * math.pi * b / count
        ca, sa = math.cos(ang), math.sin(ang)
        for tri in base:
            rot = [(p[0] * ca - p[1] * sa, p[0] * sa + p[1] * ca, p[2])
                   for p in tri]
            all_tris.append(rot)
    with open(path, "wb") as fh:
        fh.write(b"AeroForge propeller".ljust(80, b" "))
        fh.write(struct.pack("<I", len(all_tris)))
        for tri in all_tris:
            n = _normal(*tri)
            fh.write(struct.pack("<3f", *n))
            for p in tri:
                fh.write(struct.pack("<3f", *p))
            fh.write(struct.pack("<H", 0))
    return len(all_tris)


def summarize(text, rpm, material="pla", infill=1.0, bed_mm=None):
    """Пълна сводка за UI: геометрия, печат, натоварване, легло."""
    geom = parse_geometry(text)
    out = {
        "diameter_in": 2 * geom["radius_in"],
        "blades": geom["blades"],
        "estimate": estimate_print(geom, material, infill),
        "checks": check_flight_load(geom, rpm, material),
        "file_mass_kg": geom["file_mass_kg"],
    }
    if bed_mm:
        out["bed"] = fits_bed(geom, bed_mm)
    return out
