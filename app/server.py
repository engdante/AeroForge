"""
AeroForge — Eel backend.

Стартиране:  python app\\server.py     (или start.bat от корена)

Всички изчислителни функции са в core/ и се тестват отделно; тук има само
тънък слой за браузъра + файлово съхранение.
"""

import datetime
import json
import os
import sys

import eel

from core import airfoils
from core import design as design_mod
from core import geometry3d
from core import materials
from core import presets
from core import report
from core import settings as app_settings
from core import weight

# На Windows конзолата е cp1251 — иначе print с кирилица/emoji гърми
try:
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr is not None:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# --------------------------------------------------------------------------
# Пътища (работят и в dev режим, и в PyInstaller EXE)
# --------------------------------------------------------------------------
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    BASE_DIR = os.path.dirname(sys.executable)
    WEB_DIR = os.path.join(sys._MEIPASS, "web")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    WEB_DIR = os.path.join(BASE_DIR, "web")

PROJECT_DIR = BASE_DIR if FROZEN else os.path.dirname(BASE_DIR)
DESIGN_DIR = os.path.join(PROJECT_DIR, "designs")
EXPORT_DIR = os.path.join(PROJECT_DIR, "exports")

os.makedirs(DESIGN_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

eel.init(WEB_DIR)


def _safe_name(name):
    """Безопасно име на файл за дизайн."""
    return report.slugify(name)


# --------------------------------------------------------------------------
# Справочни данни за UI
# --------------------------------------------------------------------------
@eel.expose
def get_presets():
    """Всичко, което UI-ът трябва да знае при старт."""
    missions = []
    for key, m in presets.MISSIONS.items():
        missions.append({
            "key": key,
            "label": m["label"],
            "description": m["description"],
            "wing_loading": m["wing_loading"],
            "wing_loading_range": list(m["wing_loading_range"]),
            "aspect_ratio": m["aspect_ratio"],
            "taper": m["taper"],
            "dihedral_deg": m["dihedral_deg"],
            "thrust_to_weight": m["thrust_to_weight"],
            "power_to_weight": m["power_to_weight"],
            "static_margin": m["static_margin"],
            "vh": m["vh"],
            "vv": m["vv"],
            "tail_arm_ratio": m["tail_arm_ratio"],
            "has_tail": m["has_tail"],
            "n_limit": m["n_limit"],
        })
    categories = [{"key": k, "label": v}
                  for k, v in weight.CATEGORIES.items()]
    return {
        "version": design_mod.VERSION,
        "currency": presets.CURRENCY,
        "ui": app_settings.get_ui(),
        "missions": missions,
        "filaments": materials.list_filaments(),
        "airfoils": airfoils.list_airfoils(),
        "categories": categories,
        "defaults": design_mod.default_inputs(),
        "battery_capacities": presets.BATTERY_CAPACITIES_MAH,
        "prop_sizes": sorted(presets.PROP_MASS_G.keys()),
        "paths": {"designs": DESIGN_DIR, "exports": EXPORT_DIR},
        "component_presets": [
            {"name": "Мотор 2212 1400Kv", "category": "motor",
             "unit_mass_g": 55},
            {"name": "Мотор 2830 1000Kv", "category": "motor",
             "unit_mass_g": 75},
            {"name": "ESC 30A", "category": "esc", "unit_mass_g": 30},
            {"name": "ESC 40A", "category": "esc", "unit_mass_g": 45},
            {"name": "LiPo 3S 2200 mAh", "category": "battery",
             "unit_mass_g": 180},
            {"name": "LiPo 4S 1500 mAh", "category": "battery",
             "unit_mass_g": 175},
            {"name": "Серва 9 g", "category": "servo", "unit_mass_g": 9},
            {"name": "Серва 17 g", "category": "servo", "unit_mass_g": 17},
            {"name": "Приемник 6-канален", "category": "rx",
             "unit_mass_g": 10},
            {"name": "FPV камера", "category": "camera", "unit_mass_g": 25},
            {"name": "Видео предавател 5.8 GHz", "category": "vtx",
             "unit_mass_g": 15},
            {"name": "Колесник", "category": "gear", "unit_mass_g": 35},
            {"name": "Лепило и крепеж", "category": "hardware",
             "unit_mass_g": 30},
        ],
    }


@eel.expose
def airfoil_shape(key, n=81):
    """
    Координати на профил за 2D преглед в UI.

    Приема ключ от каталога ("naca2412", "clarky", …) или NACA код ("2412").
    За профили без вградени координати връща приблизителен контур с
    флаг approximate=True (схематичен, само за визуализация).
    """
    raw = str(key or "").strip()
    try:
        count = int(n)
    except (TypeError, ValueError):
        count = 81
    count = max(11, min(201, count))

    if raw.isdigit() and len(raw) == 4:
        try:
            coords = airfoils.naca_coordinates(raw, count)
        except ValueError:
            return {"ok": False, "has_coords": False,
                    "error": "невалиден NACA код"}
        return _shape_payload(coords, False, raw)

    key_low = raw.lower()
    if key_low not in airfoils.AIRFOILS:
        return {"ok": False, "has_coords": False, "error": "непознат профил"}
    coords = airfoils.coordinates_for(key_low, count)
    if not coords:
        return {"ok": False, "has_coords": False}
    return _shape_payload(coords, bool(coords.get("approximate")), key_low)


def _shape_payload(coords, approximate, key):
    return {
        "ok": True,
        "has_coords": True,
        "approximate": approximate,
        "key": key,
        "upper": [[round(x, 5), round(y, 5)] for x, y in coords["upper"]],
        "lower": [[round(x, 5), round(y, 5)] for x, y in coords["lower"]],
    }


# --------------------------------------------------------------------------
# Настройки (settings.json)
# --------------------------------------------------------------------------
@eel.expose
def get_settings():
    """Каталог на филаментите + базови стойности."""
    return app_settings.get_settings()


@eel.expose
def save_settings(payload):
    """Записва настройките и връща обновения пакет."""
    result = app_settings.save(payload)
    if result.get("ok"):
        result["settings"] = app_settings.get_settings()
    return result


@eel.expose
def reset_settings():
    """Изтрива settings.json (връща вградените стойности)."""
    result = app_settings.reset()
    result["settings"] = app_settings.get_settings()
    return result


# --------------------------------------------------------------------------
# Изчисления
# --------------------------------------------------------------------------
@eel.expose
def compute_design(inputs):
    """Пълно изчисление (връща dict за UI)."""
    if inputs is not None and not isinstance(inputs, dict):
        return {"ok": False,
                "error": "Очаквах обект с входни данни (dict), получено: %s"
                         % type(inputs).__name__}
    try:
        return design_mod.compute(inputs or {})
    except Exception as exc:  # noqa: BLE001 — грешката трябва да стигне до UI
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


@eel.expose
def export_report(inputs):
    """Изчислява и записва отчет + BOM + JSON в exports/."""
    res = compute_design(inputs)
    if not res.get("ok"):
        return res
    try:
        paths = report.export_design(res, EXPORT_DIR)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    return {"ok": True, "paths": paths}


@eel.expose
def get_model3d(inputs):
    """
    Опростен 3D модел за визуализация (не за печат).

    Връща триъгълници по части: крило, фюзелаж, стабилизатор, кил, мотор.
    """
    res = compute_design(inputs)
    if not res.get("ok"):
        return res
    try:
        return geometry3d.build_model(res)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


# --------------------------------------------------------------------------
# Дизайни (JSON файлове в designs/)
# --------------------------------------------------------------------------
@eel.expose
def save_design(name, inputs):
    """Записва входните данни (резултатът се преизчислява при зареждане)."""
    safe = _safe_name(name or (inputs or {}).get("name") or "design")
    payload = {
        "name": (inputs or {}).get("name") or name or safe,
        "saved": datetime.datetime.now().isoformat(timespec="seconds"),
        "version": design_mod.VERSION,
        "inputs": design_mod.normalize(inputs or {}),
    }
    path = os.path.join(DESIGN_DIR, safe + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {"ok": True, "path": path, "name": payload["name"],
            "file": safe}


@eel.expose
def load_design(name):
    """Зарежда дизайн по име на файл (без разширение)."""
    safe = _safe_name(name)
    path = os.path.join(DESIGN_DIR, safe + ".json")
    if not os.path.exists(path):
        return {"ok": False, "error": "Няма такъв дизайн: %s" % safe}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "Не мога да прочета файла: %s" % exc}
    return {"ok": True, "name": data.get("name", safe),
            "inputs": data.get("inputs", {}),
            "saved": data.get("saved", ""), "file": safe}


@eel.expose
def list_designs():
    """Списък със записаните дизайни (най-новите първи)."""
    out = []
    try:
        for fname in os.listdir(DESIGN_DIR):
            if not fname.lower().endswith(".json"):
                continue
            path = os.path.join(DESIGN_DIR, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                out.append({
                    "file": fname[:-5],
                    "name": data.get("name", fname[:-5]),
                    "saved": data.get("saved", ""),
                    "mission": (data.get("inputs") or {}).get("mission", ""),
                    "mtime": os.path.getmtime(path),
                })
            except Exception:  # noqa: BLE001 — повреден файл не бива да чупи UI
                continue
    except OSError:
        pass
    out.sort(key=lambda d: d["mtime"], reverse=True)
    return out


@eel.expose
def delete_design(name):
    """Изтрива дизайн."""
    safe = _safe_name(name)
    path = os.path.join(DESIGN_DIR, safe + ".json")
    if os.path.exists(path):
        os.remove(path)
        return {"ok": True}
    return {"ok": False, "error": "Няма такъв дизайн"}


@eel.expose
def get_paths():
    """Пътища за показване в UI."""
    return {"designs": DESIGN_DIR, "exports": EXPORT_DIR, "base": PROJECT_DIR}


@eel.expose
def open_folder(which="exports"):
    """Отваря папка в Explorer."""
    target = EXPORT_DIR if which == "exports" else DESIGN_DIR
    try:
        if sys.platform.startswith("win"):
            os.startfile(target)  # noqa: S606 — нарочно отваряме Explorer
        else:
            import subprocess
            subprocess.Popen(["xdg-open", target])
        return {"ok": True, "path": target}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def main():
    print("AeroForge %s" % design_mod.VERSION)
    print("Папка с дизайни: %s" % DESIGN_DIR)
    print("Папка с отчети:  %s" % EXPORT_DIR)
    port = 0
    for arg in sys.argv[1:]:
        try:
            port = int(arg)
        except ValueError:
            pass

    # AEROFORGE_NO_BROWSER=1 → само сървърът (за тестове / отдалечен достъп)
    mode = None if os.environ.get("AEROFORGE_NO_BROWSER") == "1" else "default"
    kwargs = {"size": (1400, 900), "port": port, "shutdown_delay": 1.0}
    if mode is not None:
        eel.start("index.html", mode=mode, **kwargs)
    else:
        eel.start("index.html", **kwargs)



if __name__ == "__main__":
    main()


