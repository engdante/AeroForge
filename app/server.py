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

from core import aero
from core import airfoils
from core import design as design_mod
from core import fuselage
from core import geometry3d
from core import layout
from core import materials
from core import export_job
from core import presets
from core import printgeom
from core import profiles
from core import catalog as catalog_mod
from core import controls
from core import extras
from core import motor
from core import propeller as propeller_mod
from core import report
from core import settings as app_settings
from core import solidcraft_export
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
        "tip_styles": aero.list_tip_styles(),
        "quality_levels": geometry3d.quality_levels(),
        "categories": categories,
        "defaults": design_mod.default_inputs(),
        "battery_capacities": presets.BATTERY_CAPACITIES_MAH,
        "prop_sizes": sorted(presets.PROP_MASS_G.keys()),
        "motor_classes": [dict(c, mount=list(c["mount"]))
                          for c in motor.MOTOR_CLASSES],
        "fuselage": {
            "shapes": fuselage.list_shapes(),
            "booms": fuselage.list_booms(),
            "defaults": dict(fuselage.DEFAULT),
        },
        "layout": {
            "propulsion": layout.list_propulsion(),
            "wing_positions": layout.list_wing_positions(),
            "tail_types": layout.list_tail_types(),
            "tail_planforms": [{"key": key, "label": value["label"],
                                "description": value["description"]}
                               for key, value in aero.TAIL_PLANFORMS.items()],
            "tail_tip_styles": [{"key": key, "label": value["label"]}
                                for key, value in aero.TAIL_TIP_STYLES.items()],
            "wing_offset_limit": layout.WING_OFFSET_LIMIT,
        },
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
    payload = app_settings.get_settings()
    # нивата за качество на 3D модела идват от geometry3d (един източник)
    payload["quality_levels"] = geometry3d.quality_levels()
    return payload


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
def profile_costs(inputs):
    """
    Сравнение на профилите (Бюджет / Стандарт / Хай-енд) за текущия дизайн.
    Смята се на заявка (не при всяко редактиране), защото са три пълни изчисления.
    """
    if inputs is not None and not isinstance(inputs, dict):
        return {"ok": False, "error": "очаквах обект (dict)"}
    rows = []
    for key, prof in profiles.PROFILES.items():
        try:
            res = design_mod.compute(profiles.apply(inputs or {}, key))
        except Exception as exc:  # noqa: BLE001
            rows.append({"key": key, "label": prof["label"], "ok": False,
                         "error": "%s: %s" % (type(exc).__name__, exc)})
            continue
        if not res.get("ok"):
            rows.append({"key": key, "label": prof["label"], "ok": False,
                         "error": res.get("error", "грешка в изчислението")})
            continue
        bom = res["bom"]
        rows.append({
            "key": key,
            "label": prof["label"],
            "ok": True,
            "total_eur": bom["total_eur"],
            "print_eur": bom["print_eur"],
            "structure_eur": bom["structure_eur"],
            "electronics_eur": bom["electronics_eur"],
            "ready": bool(res["stability"].get("ready_to_fly")),
        })
    return {"ok": True, "rows": rows}


def _compute(inputs):
    """Пълно изчисление (общо за UI, отчетите и експорта)."""
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
def compute_design(inputs):
    """
    Пълно изчисление за UI. Добавя `structure_view` — схемата „спар и
    джойнер“ (кореново сечение), смятана от същата геометрия като експорта.
    Отчетите и експортът ползват _compute и не я съдържат.
    """
    res = _compute(inputs)
    if res.get("ok"):
        try:
            res["servos"] = controls.servo_sizing(res)
        except Exception:  # noqa: BLE001 — оразмеряването е само подсказка
            res["servos"] = None
        try:
            res["motor_view"] = motor.summary(res)
        except Exception:  # noqa: BLE001 — размерът на мотора е само подсказка
            res["motor_view"] = None
        try:
            res["structure_view"] = printgeom.spar_section(res)
        except Exception:  # noqa: BLE001 — схемата не бива да спира изчислението
            import traceback
            traceback.print_exc()
            res["structure_view"] = None
    return res


@eel.expose
def export_report(inputs):
    """Изчислява и записва отчет + BOM + JSON в exports/."""
    res = _compute(inputs)
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
    res = _compute(inputs)
    if not res.get("ok"):
        return res
    try:
        quality = app_settings.get_ui().get("quality")
        return geometry3d.build_model(res, quality=quality)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


@eel.expose
def export_plan(inputs, options=None):
    """
    Подготвя експорта (без SolidCraft): папка, сечения, 3MF от мрежата.

    Връща задача (`job`) и списък стъпки с оценка, за да може панелът да
    покаже какво предстои още преди първото чакане.
    """
    res = _compute(inputs)
    if not res.get("ok"):
        return res
    try:
        opts = dict(options or {})
        opts.setdefault("run", True)
        return export_job.start(
            res, EXPORT_DIR,
            quality=app_settings.get_ui().get("quality"),
            slugify=report.slugify, options=opts)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


@eel.expose
def export_step(job, index=None):
    """Изпълнява една стъпка от експорта и връща новото състояние."""
    try:
        return export_job.run_step(job, index)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


@eel.expose
def export_cancel(job):
    """Отказва експорта (текущата стъпка се довършва, следващите — не)."""
    return export_job.cancel(job)


@eel.expose
def export_state(job):
    """Състоянието на задачата (за възстановяване на панела)."""
    return export_job.current(job)


@eel.expose
def export_preview(job):
    """
    PNG превю на готовия модел като data URL (за панела на експорта).

    Браузърът не може да отвори `file://` от страницата на Eel, затова
    картинката се връща като base64 — само за файл в папката на експорта.
    """
    import base64
    item = export_job.current(job)
    path = item.get("preview")
    if not path or not os.path.exists(path):
        return None
    root = os.path.abspath(EXPORT_DIR)
    if not _inside(path, root):
        return None
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None
    return "data:image/png;base64," + data


@eel.expose
def export_solidcraft(inputs, options=None):
    """
    Синхронен експорт (същите стъпки, без междинен прогрес).

    Ползва се от скриптове и тестове; UI-ят вика `export_plan` +
    `export_step`, за да показва прогрес.
    """
    res = _compute(inputs)
    if not res.get("ok"):
        return res
    try:
        opts = dict(options or {})
        return solidcraft_export.export(
            res, EXPORT_DIR,
            quality=app_settings.get_ui().get("quality"),
            slugify=report.slugify, options=opts)
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


def _inside(path, root):
    """True само ако `path` е самата `root` или е вътре в нея (не префикс на името)."""
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:  # различни дялове на Windows
        return False


@eel.expose
def open_export(path):
    """
    Отваря конкретна папка от exports/ (за „намери файловете“).

    Приема се само път вътре в EXPORT_DIR — не произволен от браузъра.
    """
    base = os.path.abspath(EXPORT_DIR)
    target = os.path.abspath(str(path or ""))
    if not _inside(target, base):
        return {"ok": False, "error": "пътят е извън папката с отчети"}
    if not os.path.isdir(target):
        return {"ok": False, "error": "няма такава папка: %s" % target}
    try:
        if sys.platform.startswith("win"):
            os.startfile(target)  # noqa: S606
        else:
            import subprocess
            subprocess.Popen(["xdg-open", target])
        return {"ok": True, "path": target}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------
# Витла за 3D печат (APC геометрия от папка PE0-FILES_WEB)
# --------------------------------------------------------------------------
PROP_DIR = os.path.join(PROJECT_DIR, "PE0-FILES_WEB")
PROP_EXPORT_DIR = os.path.join(EXPORT_DIR, "propellers")


def _prop_path(name):
    """Път към APC файл — само директно в PROP_DIR, без подпапки."""
    base = os.path.basename(str(name or ""))
    if not base.upper().endswith(".PE0"):
        raise ValueError("не е APC геометрия")
    path = os.path.abspath(os.path.join(PROP_DIR, base))
    if not _inside(path, PROP_DIR) or not os.path.isfile(path):
        raise ValueError("няма такъв файл: %s" % base)
    return path


def _read_prop(name):
    path = _prop_path(name)
    with open(path, encoding="latin-1") as fh:
        return path, fh.read()


@eel.expose
def list_propellers():
    """Списък с APC витла от PE0-FILES_WEB."""
    if not os.path.isdir(PROP_DIR):
        return {"ok": False, "error": "липсва папка PE0-FILES_WEB", "items": []}
    items = []
    for fname in sorted(os.listdir(PROP_DIR)):
        if fname.upper().endswith(".PE0"):
            label = fname[:-4]
            if label.upper().endswith("-PERF"):
                label = label[:-5]
            items.append({"name": fname, "label": label})
    return {"ok": True, "items": items}


@eel.expose
def propeller_summary(name, rpm, material="pla", infill=1.0, bed=None):
    """Маса, цена, проверки за натоварване и побиране на леглото."""
    try:
        _, text = _read_prop(name)
        bed_mm = tuple(float(v) for v in bed) if bed else None
        out = propeller_mod.summarize(text, float(rpm), str(material),
                                      float(infill), bed_mm)
        return {"ok": True, "summary": out}
    except (ValueError, propeller_mod.PropellerError) as exc:
        return {"ok": False, "error": str(exc)}


@eel.expose
def export_propeller_stl(name):
    """Записва STL на перката в exports/propellers/ (mm)."""
    try:
        path, text = _read_prop(name)
        geom = propeller_mod.parse_geometry(text)
        os.makedirs(PROP_EXPORT_DIR, exist_ok=True)
        stem = os.path.splitext(os.path.basename(path))[0]
        target = os.path.join(PROP_EXPORT_DIR, stem + ".stl")
        count = propeller_mod.write_stl(target, geom)
        return {"ok": True, "path": target, "triangles": count}
    except (ValueError, propeller_mod.PropellerError) as exc:
        return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------
# Каталог на цени (catalog.json до приложението)
# --------------------------------------------------------------------------
CATALOG_PATH = os.path.join(PROJECT_DIR, catalog_mod.CATALOG_NAME)
catalog_mod.apply(catalog_mod.read(CATALOG_PATH))


@eel.expose
def get_catalog():
    return {"ok": True, **catalog_mod.effective()}


@eel.expose
def save_catalog(payload):
    try:
        catalog_mod.save(CATALOG_PATH, payload)
        return {"ok": True, **catalog_mod.effective()}
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------
# Допълнения: APC витла и SolidCraft (изтегляне/път) — виж core/extras.py
# --------------------------------------------------------------------------
@eel.expose
def extras_status():
    try:
        return {"ok": True, **extras.status(PROP_DIR)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@eel.expose
def extras_install_apc():
    started = extras.install_apc(PROP_DIR)
    return {"ok": True, "started": started, "progress": extras.progress()}


@eel.expose
def extras_solidcraft_latest():
    """Последната версия на SolidCraft в GitHub за тази платформа."""
    try:
        return {"ok": True, **extras.latest_solidcraft()}
    except Exception as exc:  # noqa: BLE001 — мрежата може да липсва
        return {"ok": False, "error": str(exc)}


@eel.expose
def extras_install_solidcraft(url=None):
    """Без адрес — последната версия от GitHub (SHA-256); с адрес — архивът."""
    try:
        started = extras.install_solidcraft(url or None)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "started": started, "progress": extras.progress()}


@eel.expose
def extras_set_cli(path):
    try:
        return {"ok": True, "cli": extras.set_cli_path(path)}
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


@eel.expose
def extras_progress():
    return {"ok": True, "progress": extras.progress()}


@eel.expose
def reset_catalog():
    try:
        catalog_mod.reset(CATALOG_PATH)
        return {"ok": True, **catalog_mod.effective()}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def main():
    print("AeroForge %s" % design_mod.VERSION)
    print("Папка с дизайни: %s" % DESIGN_DIR)
    print("Папка с отчети:  %s" % EXPORT_DIR)
    cli = solidcraft_export.find_cli()
    print("SolidCraft CLI:  %s" % (
        cli or "не е намерен — експортът ще записва само скрипта и SVG-ите"))
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


