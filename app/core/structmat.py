"""
structmat.py — каталог на конструктивните материали (спар, джойнер, опашна греда).

Стойностите са инженерни оценки за оразмеряване, не сертификационни данни.
Цените са ориентировъчни (EUR/kg) и са редактируеми — зависят от пазара.

Масата на профил: g/m = A[mm²] · ρ[g/cm³]  (1 mm² · 1 g/cm³ = 1 mg/mm = 1 g/m).
"""

import math

# E и допустимо напрежение [MPa], плътност [g/cm³], ориентировъчна цена [EUR/kg]
MATERIALS = {
    "carbon": {
        "name": "Карбон (pultruded)",
        "e_mpa": 90000.0, "allow_mpa": 600.0,
        "density": 1.55, "price_eur_kg": 200.0,
    },
    "aluminium": {
        "name": "Алуминий 6061-T6",
        "e_mpa": 69000.0, "allow_mpa": 200.0,
        "density": 2.70, "price_eur_kg": 12.0,
    },
    "fibreglass": {
        "name": "Фибростъкло (pultruded)",
        "e_mpa": 40000.0, "allow_mpa": 250.0,
        "density": 1.90, "price_eur_kg": 25.0,
    },
    "wood": {
        "name": "Дърво (бук)",
        "e_mpa": 14000.0, "allow_mpa": 50.0,
        "density": 0.72, "price_eur_kg": 15.0,
    },
    "steel": {
        "name": "Стоманена тел",
        "e_mpa": 200000.0, "allow_mpa": 500.0,
        "density": 7.85, "price_eur_kg": 5.0,
    },
}

# Тръби (ОД, вътрешен Ø) [mm] — алуминий, стена 1 mm
ALU_TUBES_MM = [
    (6.0, 4.0), (8.0, 6.0), (10.0, 8.0), (12.0, 10.0),
    (14.0, 12.0), (16.0, 14.0), (20.0, 18.0),
]

# Ленти (ширина, дебелина) [mm] за спар
STRIPS_MM = {
    "aluminium": [(10.0, 1.0), (12.0, 1.0), (15.0, 1.0), (20.0, 1.0)],
    "wood": [(10.0, 3.0), (15.0, 3.0), (20.0, 4.0), (25.0, 5.0)],
}

ADHESIVE_SHEAR_ALLOW_MPA = 8.0   # епоксид, консервативно (ориентировъчно)


# Припокривания на цената (EUR/kg) от catalog.json; виж catalog.py.
# Редактируеми свойства и допустими граници (за catalog.json).
EDITABLE_FIELDS = {
    "price_eur_kg": (0.0, 1000.0),
    "density": (0.1, 12.0),       # g/cm³
    "e_mpa": (1.0, 400000.0),     # модул на еластичност, MPa
    "allow_mpa": (1.0, 5000.0),   # допустимо напрежение на опън, MPa
}
OVERRIDES = {}


def set_overrides(values):
    """Припокрития по материал и свойство; неизвестните полета се пропускат."""
    OVERRIDES.clear()
    for key, fields in (values or {}).items():
        if key not in MATERIALS:
            continue
        if not isinstance(fields, dict):
            # Стар формат: число = цена (EUR/kg)
            fields = {"price_eur_kg": fields}
        clean = {f: float(v) for f, v in fields.items()
                 if f in EDITABLE_FIELDS}
        if clean:
            OVERRIDES[key] = clean


def set_price_overrides(prices):
    """Съвместимост: само цени (EUR/kg)."""
    set_overrides({k: {"price_eur_kg": v} for k, v in (prices or {}).items()})


def get(key):
    if key not in MATERIALS:
        raise KeyError("Непознат конструктивен материал: %s" % key)
    mat = dict(MATERIALS[key])
    mat.update(OVERRIDES.get(key, {}))
    return mat


def tube_area_mm2(od, idia):
    return math.pi / 4.0 * (od ** 2 - idia ** 2)


def tube_mass_g_per_m(od, idia, density):
    return tube_area_mm2(od, idia) * density


def tube_ei_nm2(od, idia, e_mpa):
    """Коравина E·I [N·m²]; E в MPa = N/mm², I в mm⁴ → N·mm² → /1e6."""
    i_mm4 = math.pi / 64.0 * (od ** 4 - idia ** 4)
    return e_mpa * i_mm4 / 1e6


def tube_section_modulus_mm3(od, idia):
    return math.pi * (od ** 4 - idia ** 4) / (32.0 * od)


def tube_bending_stress_mpa(moment_nm, od, idia):
    z = tube_section_modulus_mm3(od, idia)
    return (moment_nm * 1000.0) / z if z > 0 else float("inf")


def select_tube(material_key, moment_nm, catalog=None):
    """
    Най-лекият профил, чието огъващо напрежение е под допустимото.

    Връща dict с ОД, Ø, маса, напрежение и запас; None ако нищо не стига.
    """
    mat = get(material_key)
    if catalog is None:
        catalog = ALU_TUBES_MM
    best = None
    for od, idia in catalog:
        stress = tube_bending_stress_mpa(moment_nm, od, idia)
        if stress > mat["allow_mpa"]:
            continue
        mass = tube_mass_g_per_m(od, idia, mat["density"])
        cand = {"od_mm": od, "id_mm": idia, "stress_mpa": stress,
                "allow_mpa": mat["allow_mpa"],
                "mass_g_per_m": mass,
                "ei_nm2": tube_ei_nm2(od, idia, mat["e_mpa"])}
        if best is None or mass < best["mass_g_per_m"]:
            best = cand
    return best


def bonded_shear_mpa(shear_n, bonded_area_mm2):
    return shear_n / bonded_area_mm2 if bonded_area_mm2 > 0 else float("inf")
