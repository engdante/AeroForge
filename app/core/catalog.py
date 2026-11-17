"""
catalog.py — редактируеми цени (catalog.json до приложението).

Пази се само разликата спрямо вградените стойности:
  * електроника по клас (EUR на бройка; батерията — EUR на Ah);
  * цена на конструктивните материали (EUR/kg).

Ако файлът липсва или е повреден, важат вградените стойности — приложението
не спира заради каталога.
"""

import json
import math
import os

from . import profiles
from . import structmat

CATALOG_NAME = "catalog.json"
ELECTRONICS_KEYS = ("motor", "esc", "servo", "receiver", "battery_per_ah",
                    "hardware")
PRICE_MAX_EUR = 100000.0
PRICE_KG_MAX_EUR = 1000.0


def _number(value, upper):
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError("очаквах число, получено: %r" % (value,))
    if not math.isfinite(number) or number < 0 or number > upper:
        raise ValueError("стойността трябва да е между 0 и %g" % upper)
    return number


def _ranged(value, lo, hi):
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError("очаквах число, получено: %r" % (value,))
    if not math.isfinite(number) or number < lo or number > hi:
        raise ValueError("стойността трябва да е между %g и %g" % (lo, hi))
    return number


def validate(payload):
    """Проверява и почиства входа. Връща dict със същата структура."""
    if not isinstance(payload, dict):
        raise ValueError("каталогът трябва да е обект")
    out = {"electronics": {}, "materials": {}}
    for cls, values in (payload.get("electronics") or {}).items():
        if cls not in profiles.ELECTRONICS_EUR:
            raise ValueError("непознат клас електроника: %s" % cls)
        if not isinstance(values, dict):
            raise ValueError("класът %s трябва да е обект" % cls)
        clean = {}
        for key, value in values.items():
            if key not in ELECTRONICS_KEYS:
                raise ValueError("непознат ред в електрониката: %s" % key)
            clean[key] = _number(value, PRICE_MAX_EUR)
        out["electronics"][cls] = clean
    for mat, value in (payload.get("materials") or {}).items():
        if mat not in structmat.MATERIALS:
            raise ValueError("непознат материал: %s" % mat)
        if isinstance(value, dict):
            clean = {}
            for field, raw in value.items():
                if field not in structmat.EDITABLE_FIELDS:
                    raise ValueError("непознато свойство: %s" % field)
                lo, hi = structmat.EDITABLE_FIELDS[field]
                clean[field] = _ranged(raw, lo, hi)
            if clean:
                out["materials"][mat] = clean
        else:
            # Стар формат: само цена (EUR/kg)
            out["materials"][mat] = {
                "price_eur_kg": _number(value, PRICE_KG_MAX_EUR)}
    return out


def read(path):
    """Чете catalog.json; при грешка връща празен каталог (вградените цени)."""
    if not path or not os.path.isfile(path):
        return {"electronics": {}, "materials": {}}
    try:
        with open(path, encoding="utf-8") as fh:
            return validate(json.load(fh))
    except (OSError, ValueError):
        return {"electronics": {}, "materials": {}}


def apply(data):
    """Слага припокриванията в profiles и structmat (за всички изчисления)."""
    profiles.set_overrides(data.get("electronics", {}))
    structmat.set_overrides(data.get("materials", {}))


def save(path, payload):
    """Проверява, записва catalog.json и прилага промените."""
    clean = validate(payload)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, ensure_ascii=False, indent=2)
    apply(clean)
    return clean


def reset(path):
    """Премахва припокриванията и върта вградените цени."""
    if path and os.path.isfile(path):
        os.remove(path)
    apply({"electronics": {}, "materials": {}})


def effective():
    """Текущите стойности (вградени + припокрития) за интерфейса."""
    electronics = {}
    for cls in profiles.ELECTRONICS_EUR:
        electronics[cls] = profiles.electronics_table(cls)
    props = {}
    defaults_props = {}
    for key, mat in structmat.MATERIALS.items():
        current = structmat.get(key)
        props[key] = {f: current[f] for f in structmat.EDITABLE_FIELDS}
        defaults_props[key] = {f: mat[f] for f in structmat.EDITABLE_FIELDS}
    return {"electronics": electronics, "materials": props,
            "defaults": {
                "electronics": {c: dict(v) for c, v in
                                profiles.ELECTRONICS_EUR.items()},
                "materials": defaults_props}}
