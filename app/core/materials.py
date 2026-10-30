"""
materials.py — филаменти за 3D печат на RC модел.

Стойностите са типични за масова употреба (TDS на производители + практика
на моделистите). Използват се за оценка на маса, якост, време и цена —
не са сертификационни данни.

Каталогът може да се редактира от „Настройки“ в приложението; промените
се пазят в settings.json и се прилагат с apply_catalog().

Означения:
    density         g/cm³  — плътност на плътния материал
    printed_density g/cm³  — реална плътност на отпечатаното тяло
                              (за разпенващите LW филаменти е по-ниска)
    tensile_mpa     MPa    — якост на опън (по слоеве, типично)
    e_mpa           MPa    — модул на еластичност
    layer_factor    -      — ефективност на слоевата адхезия при огъване
    price_per_kg    €      — ориентировъчна цена
    max_flow        mm³/s  — практически обемен дебит при 0.4 mm дюза
    expansion       -      — коефициент на разпенване (обем на детайла /
                              обем на подадения материал). Информативен:
                              изчисленията ползват printed_density, за да
                              останат масата, филаментът и времето
                              консистентни.
"""

import math

BUILTIN_FILAMENTS = {
    "pla": {
        "key": "pla",
        "name": "PLA",
        "density": 1.24,
        "printed_density": 1.24,
        "tensile_mpa": 50.0,
        "e_mpa": 3500.0,
        "layer_factor": 0.65,
        "price_per_kg": 20.0,
        "max_flow": 11.0,
        "expansion": 1.0,
        "temp": "200–215 °C",
        "notes": "Твърд и евтин, но крехък при удар. Става за крила с 2 периметъра.",
    },
    "pla_plus": {
        "key": "pla_plus",
        "name": "PLA+ (Tough PLA)",
        "density": 1.24,
        "printed_density": 1.24,
        "tensile_mpa": 45.0,
        "e_mpa": 2800.0,
        "layer_factor": 0.72,
        "price_per_kg": 25.0,
        "max_flow": 11.0,
        "expansion": 1.0,
        "temp": "205–225 °C",
        "notes": "По-жилав от PLA — по-добър при удар и при Flite-test стил.",
    },
    "petg": {
        "key": "petg",
        "name": "PETG",
        "density": 1.27,
        "printed_density": 1.27,
        "tensile_mpa": 50.0,
        "e_mpa": 2100.0,
        "layer_factor": 0.70,
        "price_per_kg": 23.0,
        "max_flow": 12.0,
        "expansion": 1.0,
        "temp": "230–250 °C",
        "notes": "Жилав, слаба твърдост — огъва се. Добър за фюзелаж и landing gear.",
    },
    "lw_pla": {
        "key": "lw_pla",
        "name": "LW-PLA (разпенващ се)",
        "density": 1.24,
        "printed_density": 0.45,
        "tensile_mpa": 22.0,
        "e_mpa": 1200.0,
        "layer_factor": 0.60,
        "price_per_kg": 45.0,
        "max_flow": 8.0,
        "expansion": 1.55,
        "temp": "230–250 °C",
        "notes": "Стандартът за печатани самолети: ~2.7× по-лек от PLA. "
                 "Печата се с 1 периметър (vase mode), изисква ребра/спарове.",
    },
    "lw_pla_ht": {
        "key": "lw_pla_ht",
        "name": "LW-PLA-HT (термоустойчив)",
        "density": 1.24,
        "printed_density": 0.55,
        "tensile_mpa": 28.0,
        "e_mpa": 1500.0,
        "layer_factor": 0.62,
        "price_per_kg": 55.0,
        "max_flow": 8.0,
        "expansion": 1.40,
        "temp": "240–260 °C",
        "notes": "Като LW-PLA, но издържа на слънце в кола (до ~90 °C).",
    },
    "abs": {
        "key": "abs",
        "name": "ABS",
        "density": 1.04,
        "printed_density": 1.04,
        "tensile_mpa": 40.0,
        "e_mpa": 2200.0,
        "layer_factor": 0.55,
        "price_per_kg": 20.0,
        "max_flow": 12.0,
        "expansion": 1.0,
        "temp": "240–260 °C",
        "notes": "Лек, но се разслоява при по-хладна стая; изисква затворена камера.",
    },
    "asa": {
        "key": "asa",
        "name": "ASA",
        "density": 1.07,
        "printed_density": 1.07,
        "tensile_mpa": 45.0,
        "e_mpa": 2300.0,
        "layer_factor": 0.58,
        "price_per_kg": 28.0,
        "max_flow": 12.0,
        "expansion": 1.0,
        "temp": "250–270 °C",
        "notes": "UV-устойчив вариант на ABS — за модели, стоящи на слънце.",
    },
    "pa_cf": {
        "key": "pa_cf",
        "name": "PA-CF (найлон + карбон)",
        "density": 1.16,
        "printed_density": 1.10,
        "tensile_mpa": 75.0,
        "e_mpa": 5000.0,
        "layer_factor": 0.75,
        "price_per_kg": 90.0,
        "max_flow": 8.0,
        "expansion": 1.0,
        "temp": "260–290 °C",
        "notes": "Най-здравият често срещан филамент — за спарове и моторни планки.",
    },
    "tpu": {
        "key": "tpu",
        "name": "TPU 95A",
        "density": 1.21,
        "printed_density": 1.21,
        "tensile_mpa": 25.0,
        "e_mpa": 60.0,
        "layer_factor": 0.80,
        "price_per_kg": 50.0,
        "max_flow": 6.0,
        "expansion": 1.0,
        "temp": "220–240 °C",
        "notes": "За панти, колела и носови буфери — не за носещи части.",
    },
}

DEFAULT_FILAMENT = "lw_pla"

# Активен каталог — заменя се от потребителските настройки (settings.json).
FILAMENTS = {}

_REQUIRED_FIELDS = {
    "density": 1.24,
    "printed_density": 1.24,
    "tensile_mpa": 40.0,
    "e_mpa": 2000.0,
    "layer_factor": 0.6,
    "price_per_kg": 25.0,
    "max_flow": 10.0,
    "expansion": 1.0,
}

# Реалистични граници — предпазват модела от случаен/сгрешен вход
_LIMITS = {
    "density": (0.30, 3.00),
    "printed_density": (0.10, 3.00),
    "tensile_mpa": (1.0, 300.0),
    "e_mpa": (10.0, 50000.0),
    "layer_factor": (0.10, 1.00),
    "price_per_kg": (0.0, 1000.0),
    "max_flow": (0.5, 60.0),
    "expansion": (0.5, 3.0),
}


def _as_float(value, default):
    if value is None or value == "":
        return float(default)
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return number


def normalize_spec(key, spec):
    """
    Привежда един филамент към очаквания формат.

    Използва се и при зареждане на потребителски настройки, за да не може
    повреден settings.json да счупи изчисленията.
    """
    spec = dict(spec or {})
    out = {
        "key": str(spec.get("key") or key),
        "name": str(spec.get("name") or key),
        "temp": str(spec.get("temp") or ""),
        "notes": str(spec.get("notes") or ""),
    }
    for field, default in _REQUIRED_FIELDS.items():
        value = _as_float(spec.get(field), default)
        low, high = _LIMITS[field]
        out[field] = min(high, max(low, value))
    return out


def apply_catalog(filaments):
    """Замества активния каталог (от settings.json). Връща True при успех."""
    if not isinstance(filaments, dict) or not filaments:
        return False
    cleaned = {}
    for key, spec in filaments.items():
        if not isinstance(spec, dict):
            continue
        safe_key = str(key).strip().lower().replace(" ", "_")[:40]
        if not safe_key:
            continue
        cleaned[safe_key] = normalize_spec(safe_key, spec)
    if not cleaned:
        return False
    FILAMENTS.clear()
    FILAMENTS.update(cleaned)
    return True


def reset_catalog():
    """Връща вградения каталог."""
    FILAMENTS.clear()
    FILAMENTS.update({k: dict(v) for k, v in BUILTIN_FILAMENTS.items()})


def get(key):
    """Връща данните за филамент (с fallback към DEFAULT_FILAMENT)."""
    if key in FILAMENTS:
        return dict(FILAMENTS[key])
    if DEFAULT_FILAMENT in FILAMENTS:
        return dict(FILAMENTS[DEFAULT_FILAMENT])
    first = next(iter(FILAMENTS))
    return dict(FILAMENTS[first])


def list_filaments():
    """Списък за UI и за прозореца „Настройки“."""
    out = []
    for key, f in FILAMENTS.items():
        out.append({
            "key": key,
            "name": f["name"],
            "density": f["density"],
            "printed_density": f["printed_density"],
            "tensile_mpa": f["tensile_mpa"],
            "e_mpa": f["e_mpa"],
            "layer_factor": f["layer_factor"],
            "price_per_kg": f["price_per_kg"],
            "max_flow": f["max_flow"],
            "expansion": f["expansion"],
            "temp": f.get("temp", ""),
            "notes": f["notes"],
        })
    return out


reset_catalog()

