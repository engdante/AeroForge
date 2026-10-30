"""
settings.py — потребителски настройки (settings.json).

Пазят се до приложението (или до EXE-то) и съдържат:
  * пълния каталог на филаментите (плътности, цени, якост, дебит…);
  * базови стойности за печат, задвижване и начален дизайн.

Ако settings.json липсва или е повреден, се използват вградените стойности —
приложението никога не бива да спира заради настройки.
"""

import json
import os
import sys

from . import materials

VERSION = 1


def base_dir():
    """Папка на проекта (dev) или на EXE-то (frozen)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    here = os.path.dirname(os.path.abspath(__file__))       # app/core
    return os.path.dirname(os.path.dirname(here))           # проект


SETTINGS_PATH = os.path.join(base_dir(), "settings.json")

DEFAULT_PRINT = {
    "filament": materials.DEFAULT_FILAMENT,
    "nozzle": 0.4,
    "perimeters": None,      # None = авто (1 за LW, 2 за плътните)
    "infill": None,
    "layer_height": 0.2,
    "bed": [220.0, 220.0, 250.0],
}

DEFAULT_PROPULSION = {
    "cells": 3,
    "endurance_min": 8.0,
}

DEFAULT_DESIGN = {
    "mission": "trainer",
    "payload_total_g": 600.0,
}

# Шрифтове за интерфейса (ключ → CSS font-family стек)
FONTS = [
    {"key": "segoe", "label": "Segoe UI (по подразбиране)",
     "css": '"Segoe UI", Tahoma, sans-serif'},
    {"key": "system", "label": "Системен шрифт",
     "css": 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'},
    {"key": "arial", "label": "Arial / Helvetica",
     "css": 'Arial, Helvetica, sans-serif'},
    {"key": "verdana", "label": "Verdana (широк, четим)",
     "css": 'Verdana, Geneva, sans-serif'},
    {"key": "tahoma", "label": "Tahoma", "css": 'Tahoma, Geneva, sans-serif'},
    {"key": "trebuchet", "label": "Trebuchet MS",
     "css": '"Trebuchet MS", "Segoe UI", sans-serif'},
    {"key": "georgia", "label": "Georgia (серифен)",
     "css": 'Georgia, "Times New Roman", serif'},
    {"key": "consolas", "label": "Consolas (равноширок)",
     "css": 'Consolas, "Courier New", monospace'},
]

DEFAULT_UI = {
    "font": "segoe",
    "size": 13,      # базов размер в px (11–20)
}

UI_SIZE_MIN = 11
UI_SIZE_MAX = 20


def fonts():
    """Списък с шрифтове за UI."""
    return [dict(f) for f in FONTS]


_STATE = {
    "custom": False,
    "defaults": {},
    "error": "",
}


def _num(value, default=None):
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _merge_defaults(raw):
    """Обезпечава структурата на defaults (без да чупи при лош вход)."""
    raw = raw if isinstance(raw, dict) else {}
    prt = raw.get("print") if isinstance(raw.get("print"), dict) else {}
    prop = raw.get("propulsion")
    prop = prop if isinstance(prop, dict) else {}
    des = raw.get("design") if isinstance(raw.get("design"), dict) else {}

    bed = prt.get("bed") or DEFAULT_PRINT["bed"]
    try:
        bed = [max(60.0, float(b)) for b in list(bed)[:3]]
    except (TypeError, ValueError):
        bed = list(DEFAULT_PRINT["bed"])
    while len(bed) < 3:
        bed.append(DEFAULT_PRINT["bed"][len(bed)])

    filament = prt.get("filament") or DEFAULT_PRINT["filament"]
    if filament not in materials.FILAMENTS:
        filament = materials.DEFAULT_FILAMENT
    if filament not in materials.FILAMENTS:
        filament = next(iter(materials.FILAMENTS))

    ui = raw.get("ui") if isinstance(raw.get("ui"), dict) else {}
    font_keys = [f["key"] for f in FONTS]
    font = str(ui.get("font") or DEFAULT_UI["font"])
    if font not in font_keys:
        font = DEFAULT_UI["font"]
    size = _num(ui.get("size"), DEFAULT_UI["size"])
    try:
        size = int(round(float(size)))
    except (TypeError, ValueError):
        size = DEFAULT_UI["size"]
    size = int(max(UI_SIZE_MIN, min(UI_SIZE_MAX, size)))

    return {
        "print": {
            "filament": filament,
            "nozzle": _num(prt.get("nozzle"), DEFAULT_PRINT["nozzle"]),
            "perimeters": _num(prt.get("perimeters"), None),
            "infill": _num(prt.get("infill"), None),
            "layer_height": _num(prt.get("layer_height"),
                                 DEFAULT_PRINT["layer_height"]),
            "bed": bed,
        },
        "propulsion": {
            "cells": int(_num(prop.get("cells"),
                              DEFAULT_PROPULSION["cells"]) or 3),
            "endurance_min": _num(prop.get("endurance_min"),
                                  DEFAULT_PROPULSION["endurance_min"]),
        },
        "design": {
            "mission": str(des.get("mission") or DEFAULT_DESIGN["mission"]),
            "payload_total_g": _num(des.get("payload_total_g"),
                                    DEFAULT_DESIGN["payload_total_g"]),
        },
        "ui": {
            "font": font,
            "size": size,
        },
    }


def get_ui():
    """Шрифт, размер и готов CSS стек за интерфейса."""
    ui = dict(get_defaults()["ui"])
    ui["css"] = get_font_css(ui["font"])
    return ui


def get_font_css(key):
    """CSS font-family за ключ на шрифт (fallback към подразбирания)."""
    for font in FONTS:
        if font["key"] == key:
            return font["css"]
    return FONTS[0]["css"]


def get_defaults():
    """Копие на базовите стойности (винаги пълни)."""
    if not _STATE["defaults"]:
        _STATE["defaults"] = _merge_defaults({})
    return json.loads(json.dumps(_STATE["defaults"]))


def is_custom():
    """True, ако има записан settings.json."""
    return bool(_STATE["custom"])


def get_error():
    """Последна грешка при зареждане (за диагностика в UI)."""
    return _STATE["error"]


def load():
    """Зарежда settings.json (ако има) и прилага каталога на филаментите."""
    _STATE["error"] = ""
    _STATE["custom"] = False
    materials.reset_catalog()
    _STATE["defaults"] = _merge_defaults({})

    if not os.path.exists(SETTINGS_PATH):
        return False
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # noqa: BLE001 — лошият файл не бива да чупи старта
        _STATE["error"] = "Не мога да прочета settings.json: %s" % exc
        return False
    if not isinstance(data, dict):
        _STATE["error"] = "settings.json не е обект"
        return False

    filaments = data.get("filaments")
    if isinstance(filaments, dict) and filaments:
        if not materials.apply_catalog(filaments):
            _STATE["error"] = "Каталогът на филаментите е невалиден"
    _STATE["defaults"] = _merge_defaults(data.get("defaults"))
    _STATE["custom"] = True
    return True


def get_settings():
    """Пълен пакет за UI: каталог + базови стойности + път до файла."""
    return {
        "version": VERSION,
        "custom": is_custom(),
        "error": get_error(),
        "path": SETTINGS_PATH,
        "filaments": materials.list_filaments(),
        "defaults": get_defaults(),
        "builtin_filament_keys": list(materials.BUILTIN_FILAMENTS.keys()),
        "fonts": fonts(),
        "size_range": [UI_SIZE_MIN, UI_SIZE_MAX],
    }


def save(payload):
    """
    Записва настройките. Очаква {"filaments": {...}, "defaults": {...}}.

    връща {"ok": bool, "error": str, "path": str}
    """
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Очаквах обект с настройки"}

    filaments = payload.get("filaments")
    if isinstance(filaments, list):
        # UI може да праща списък — преобразуваме към dict по key
        filaments = {
            str(f.get("key") or f.get("name")): f
            for f in filaments if isinstance(f, dict)
        }
    if not isinstance(filaments, dict) or not filaments:
        return {"ok": False, "error": "Липсва каталог на филаментите"}

    cleaned = {}
    for key, spec in filaments.items():
        if not isinstance(spec, dict):
            continue
        safe_key = str(key).strip().lower().replace(" ", "_")[:40]
        if not safe_key:
            continue
        cleaned[safe_key] = materials.normalize_spec(safe_key, spec)
    if not cleaned:
        return {"ok": False, "error": "Каталогът е празен"}

    data = {
        "version": VERSION,
        "filaments": cleaned,
        "defaults": _merge_defaults(payload.get("defaults")),
    }
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        return {"ok": False, "error": "Не мога да запиша файла: %s" % exc}

    materials.apply_catalog(cleaned)
    _STATE["defaults"] = data["defaults"]
    _STATE["custom"] = True
    _STATE["error"] = ""
    return {"ok": True, "path": SETTINGS_PATH}


def reset():
    """Изтрива settings.json и връща вградените стойности."""
    try:
        if os.path.exists(SETTINGS_PATH):
            os.remove(SETTINGS_PATH)
    except OSError as exc:
        return {"ok": False, "error": "Не мога да изтрия файла: %s" % exc}
    load()
    return {"ok": True, "path": SETTINGS_PATH}


# прилагаме настройките при първо зареждане на модула
load()


