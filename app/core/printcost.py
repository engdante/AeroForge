"""
printcost.py — оценка на маса, време и цена за 3D печат.

Моделът работи с площ на повърхността и дебелина на стената (MVP без меш).
Масата, филаментът и времето се извеждат от ЕДНО количество материал
(обем × printed_density/density), за да не си противоречат.
Точността е ±15–20% спрямо слайсер — достатъчна за избор на филамент и
за планиране на печата.
"""

import math

FILAMENT_DIAMETER_MM = 1.75
FILAMENT_AREA_MM2 = math.pi * (FILAMENT_DIAMETER_MM / 2.0) ** 2  # 2.405 mm²
LAYER_OVERHEAD_S = 1.5      # загуби на слой (travel, retract, ускорения)
SKIN_EXTRA_FACTOR = 2.05    # площ на обшивката спрямо площта в план
DEFAULT_BED = [220.0, 220.0, 250.0]


def extrusion_width(nozzle=0.4):
    """Ширина на екструзията за дюза (практика: 1.125 × дюза)."""
    return float(nozzle) * 1.125


def wall_thickness(perimeters, nozzle=0.4):
    """Дебелина на стената при N периметъра."""
    return max(1, int(perimeters)) * extrusion_width(nozzle)


def internal_factor(perimeters, infill_pct):
    """
    Обем на вътрешната структура (ребра, спарове, frames) като част от
    обема на обшивката. Емпирично: 1 периметър (vase mode) е почти
    само обшивка; 2–3 периметъра + infill добавят вътрешни елементи.
    """
    perimeters = max(1, int(perimeters))
    base = 0.08 + 0.11 * (perimeters - 1)
    return min(0.60, base + 0.004 * max(0.0, float(infill_pct)))


def effective_flow(filament, nozzle=0.4):
    """Обемен дебит [mm³/s] с корекция за диаметъра на дюзата."""
    return float(filament["max_flow"]) * (float(nozzle) / 0.4) ** 1.5


def filament_length_m(volume_mm3, density_ratio=1.0):
    """
    Дължина на филамента за даден обем на детайла [m].

    density_ratio = printed_density / density — колко от обема на детайла е
    реално материал (за LW-PLA ≈ 0.45/1.24 = 0.36, за плътен PLA = 1.0).
    Така масата на детайла и дължината на филамента винаги описват едно и
    също количество материал.
    """
    return (volume_mm3 * max(0.0, float(density_ratio))
            / FILAMENT_AREA_MM2 / 1000.0)


def _make_part(name, area_mm2, height_mm, pieces, cfg, filament):
    """
    Изчислява обем, маса, време и цена за част с дадена повърхност.

    height_mm е размерът по Z на една част (за брой слоеве).
    """
    nozzle = float(cfg.get("nozzle", 0.4))
    perimeters = int(cfg.get("perimeters", 2))
    layer_h = max(0.08, float(cfg.get("layer_height", 0.2)))
    wall = wall_thickness(perimeters, nozzle)

    skin_vol = area_mm2 * wall
    volume = skin_vol * (1.0 + internal_factor(perimeters, cfg.get("infill", 15)))

    # Колко от обема е материал: плътните филаменти ≈ 1.0, разпенващите —
    # printed_density/density. Ползва се и за масата, и за филамента, и за
    # времето, за да не си противоречат трите оценки.
    density = max(0.01, float(filament.get("density", 1.24)))
    printed_density = float(filament["printed_density"])
    density_ratio = printed_density / density
    extruded = volume * density_ratio
    mass_g = volume * printed_density / 1000.0
    fil_m = filament_length_m(volume, density_ratio)
    layers = max(1.0, height_mm / layer_h)
    time_h = ((extruded / effective_flow(filament, nozzle)
               + layers * int(pieces) * LAYER_OVERHEAD_S) / 3600.0)
    cost = mass_g / 1000.0 * float(filament["price_per_kg"])

    return {
        "name": name,
        "area_cm2": area_mm2 / 100.0,
        "volume_cm3": volume / 1000.0,
        "pieces": int(pieces),
        "mass_g": mass_g,
        "filament_m": fil_m,
        "filament_g": mass_g,
        "time_h": time_h,
        "cost": cost,
        "wall_mm": wall,
        "layers": layers,
    }


def ellipse_perimeter(a, b):
    """Периметър на елипса (апроксимация на Рамануджан)."""
    a = max(0.001, a)
    b = max(0.001, b)
    return math.pi * (3.0 * (a + b) - math.sqrt((3.0 * a + b) * (a + 3.0 * b)))


def fit_problems(geom, tail, fuselage, cfg):
    """
    Проверява дали частите физически влизат в леглото.

    Връща списък от текстови проблеми; празен списък = всичко се побира.
    Това е отделно от оценката за маса/време, за да не се показва валиден
    печат за детайл, който не може да се сложи на леглото.
    """
    bed = cfg.get("bed") or DEFAULT_BED
    bed_xy = min(float(bed[0]), float(bed[1]))
    bed_z = max(1.0, float(bed[2]))
    problems = []

    c_root = float(geom.get("c_root_mm", 0.0))
    c_tip = float(geom.get("c_tip_mm", 0.0))
    if c_root > bed_xy + 1e-6:
        problems.append("Кореновият хорд %.0f mm е по-голям от леглото "
                        "%.0f×%.0f mm — завърти крилото или го раздели по "
                        "хорда." % (c_root, bed[0], bed[1]))
    if c_tip > bed_xy + 1e-6:
        problems.append("Върховият хорд %.0f mm е по-голям от леглото "
                        "%.0f mm." % (c_tip, bed_xy))

    semispan = float(geom.get("span_mm", 0.0)) / 2.0
    if semispan > 0:
        half_pieces = max(1, int(math.ceil(semispan / bed_z)))
        seg = semispan / half_pieces
        if seg > bed_z + 1e-6:
            problems.append("Сегментът на крилото %.0f mm е по-висок от "
                            "Z=%.0f mm." % (seg, bed_z))

    w = float(fuselage.get("width_mm", 0.0))
    h = float(fuselage.get("height_mm", 0.0))
    if w > bed_xy + 1e-6 or h > bed_xy + 1e-6:
        problems.append("Сечението на фюзелажа %.0f×%.0f mm не влиза в "
                        "леглото %.0f×%.0f mm." % (w, h, bed[0], bed[1]))

    c_h = float(tail.get("c_h_mm", 0.0) or 0.0)
    c_v = float(tail.get("c_v_mm", 0.0) or 0.0)
    if max(c_h, c_v) > bed_xy + 1e-6:
        problems.append("Хордът на опашката %.0f mm е по-голям от леглото "
                        "%.0f mm." % (max(c_h, c_v), bed_xy))
    tail_height = semispan * 0.35
    if tail_height > bed_z + 1e-6:
        problems.append("Височината на опашковата част %.0f mm е над Z=%.0f "
                        "mm — раздели я на повече части." % (tail_height,
                                                             bed_z))
    return problems


def estimate_airframe(geom, tail, fuselage, cfg, filament):
    """
    Оценява всички печатани части на самолета.

    geom      — от aero.wing_geometry (m, mm)
    tail      — от aero.tail_areas (m²)
    fuselage  — dict(width_mm, height_mm, length_mm)
    cfg       — параметри на печата (nozzle, perimeters, infill, layer_height, bed)
    """
    bed = cfg.get("bed") or DEFAULT_BED
    # Крилото се печата с размах по Z; хордата трябва да влезе в XY.
    bed_xy = min(float(bed[0]), float(bed[1]))
    bed_z = max(1.0, float(bed[2]))
    semispan = geom["span_mm"] / 2.0
    wing_pieces = max(1, int(math.ceil(semispan / bed_z))) * 2
    wing_seg_len = semispan / max(1, wing_pieces // 2)

    wing_area = geom["area_m2"] * 1e6 * SKIN_EXTRA_FACTOR
    tail_area = (tail.get("s_h_m2", 0.0) + tail.get("s_v_m2", 0.0)) * 1e6 \
        * SKIN_EXTRA_FACTOR

    w = float(fuselage["width_mm"])
    h = float(fuselage["height_mm"])
    L = float(fuselage["length_mm"])
    fus_area = ellipse_perimeter(w / 2.0, h / 2.0) * L
    fus_pieces = max(1, int(math.ceil(L / float(bed[2]))))

    parts = []
    parts.append(_make_part("Крило (2 половини)", wing_area, wing_seg_len,
                            wing_pieces, cfg, filament))
    if tail_area > 1.0:
        parts.append(_make_part("Опашка (стабилизатор + кил)", tail_area,
                                semispan * 0.35, 2, cfg, filament))
    parts.append(_make_part("Фюзелаж", fus_area, L / fus_pieces,
                            fus_pieces, cfg, filament))
    return parts


def summarize(parts):
    """Обобщение на списък части."""
    total_mass = sum(p["mass_g"] for p in parts)
    return {
        "parts": parts,
        "total_mass_g": total_mass,
        "filament_m": sum(p["filament_m"] for p in parts),
        "filament_g": sum(p.get("filament_g", p["mass_g"]) for p in parts),
        "time_h": sum(p["time_h"] for p in parts),
        "cost": sum(p["cost"] for p in parts),
        "pieces": sum(p["pieces"] for p in parts),
        "biggest_piece_time_h": max([p["time_h"] / max(1, p["pieces"])
                                     for p in parts] or [0.0]),
    }
