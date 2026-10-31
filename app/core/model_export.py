"""
model_export.py — един експорт: цялостен CAD модел + сечения + печат.

Слага всичко в exports/<дизайн>/:

    model/     aircraft.3mf, aircraft.step, сечения (DXF/CSV), params.json
    reference/ reference.3mf (батерия, серва, мотор, ESC, приемник, ЦТ)
    print/     STL файловете + print_plan.json
    README.txt координатна система и какво е какво

Така потребителят отваря един файл в CAD и продължава: отвори за серва,
джобове за управлението, капаци. Ние даваме изчисленията и външната форма.
"""

import datetime
import json
import os

from . import assembly
from . import export_3mf
from . import export_dxf
from . import export_step
from . import printgeom

README = """AeroForge — модел за CAD
=========================

Координатна система (важно при импорт):
  X — назад от носа (станции), mm
  Y — надясно по размаха, mm
  Z — нагоре; Z = 0 е най-ниската точка на фюзелажа (земята)
  Оригин: върхът на носа, на централната линия
  Единици: милиметри (1:1)

model/
  aircraft.3mf   целият самолет: Wing, Fuselage, Stabilizer, Fin (плътни тела)
  aircraft.step  същите тела като solid тела (B-rep, за boolean операции)
  wing_sections.dxf / .csv      профилни сечения по размаха (за гладък loft)
  fuselage_stations.dxf / .csv  контури на тялото по станции
  params.json    всички параметри (за параметричен rebuild)

reference/
  reference.3mf  батерия, мотор(и), ESC, приемник, серва(и), маркер на ЦТ
                 Това са ГАБАРИТИ, не отвори. Ползвай ги, за да си направиш
                 джобовете/отворите в CAD.

print/
  STL файлове за печат (кухи черупки, ориентация за леглото) + print_plan.json

Какво НЕ е моделирано (прави се в CAD):
  * отвори и джобове за серва, капаци, панти, кормилни тяги;
  * вътрешни ребра/шпангоути и кухини;
  * колесник и моторна планка.

Съвет: за гладко крило не ползвай фасетирания STEP, а направи loft по
сеченията от wing_sections.dxf (или .csv) — така получаваш NURBS повърхност.
"""


def _params(res):
    """Всички параметри, нужни за rebuild на модела."""
    g = res.get("geometry") or {}
    fus = g.get("fuselage") or {}
    tail = g.get("tail") or {}
    info = res.get("layout") or {}
    return {
        "design": (res.get("inputs") or {}).get("name"),
        "version": res.get("version"),
        "datum": assembly.DATUM,
        "mission": (res.get("mission") or {}).get("key"),
        "wing": {
            "span_mm": g.get("span_mm"),
            "c_root_mm": g.get("c_root_mm"),
            "c_tip_mm": g.get("c_tip_mm"),
            "mac_mm": g.get("mac_mm"),
            "area_dm2": g.get("area_dm2"),
            "aspect_ratio": g.get("aspect_ratio"),
            "taper": g.get("taper"),
            "dihedral_deg": g.get("dihedral_deg"),
            "washout_deg": g.get("washout_deg", assembly.WASHOUT_DEG),
            "tip_style": g.get("tip_style", "square"),
            "tip_frac": g.get("tip_frac", 0.0),
            "tip_min_ratio": g.get("tip_min_ratio", 0.10),
            "winglet": g.get("winglet") or None,
            "le_x_mm": g.get("wing_le_mm"),
            "airfoil": (g.get("airfoil") or {}).get("key"),
            "airfoil_name": (g.get("airfoil") or {}).get("name"),
        },
        "fuselage": {
            "length_mm": fus.get("length_mm"),
            "width_mm": fus.get("width_mm"),
            "height_mm": fus.get("height_mm"),
            "shape": fus.get("shape"),
            "nose_ratio": fus.get("nose_ratio"),
            "cabin_ratio": fus.get("cabin_ratio"),
            "tail_taper": fus.get("tail_taper"),
            "height_ratio": fus.get("height_ratio"),
        },
        "tail": {
            "type": info.get("tail_type"),
            "s_h_dm2": tail.get("s_h_dm2"),
            "s_v_dm2": tail.get("s_v_dm2"),
            "b_h_mm": tail.get("b_h_mm"),
            "b_v_mm": tail.get("b_v_mm"),
            "c_h_mm": tail.get("c_h_mm"),
            "c_v_mm": tail.get("c_v_mm"),
            "tail_ac_mm": tail.get("tail_ac_mm"),
            "v_deg": info.get("v_tail_deg"),
        },
        "layout": {
            "propulsion": info.get("propulsion"),
            "motor_count": info.get("motor_count"),
            "wing_position": info.get("wing_position"),
        },
        "masses_g": {
            "total": (res.get("weights") or {}).get("total_g"),
            "airframe": (res.get("weights") or {}).get("airframe_g"),
            "payload": (res.get("weights") or {}).get("payload_g"),
        },
        "cg": {
            "x_cg_mm": (res.get("stability") or {}).get("x_cg_mm"),
            "static_margin_pct": (res.get("stability") or {}).get(
                "static_margin_pct"),
            "battery_x_mm": (res.get("stability") or {}).get(
                "battery_x_placed_mm"),
        },
    }


def export_model(res, base_dir, bed, filament=None, slugify=None,
                 quality=None):
    """Пише model/, reference/, print/ и README.txt. Връща manifest."""
    if not res or not res.get("ok"):
        return {"ok": False, "error": "няма изчислен дизайн"}
    bodies = assembly.build_assembly(res, quality)
    if not bodies:
        return {"ok": False, "error": "няма геометрия за експорт"}
    refs = assembly.reference_bodies(res)
    sections = assembly.sections(res)

    name = (res.get("inputs") or {}).get("name") or "design"
    slug = slugify(name) if slugify else "design"
    folder = os.path.join(base_dir, slug)
    model_dir = os.path.join(folder, "model")
    ref_dir = os.path.join(folder, "reference")
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(ref_dir, exist_ok=True)

    files = {}

    def record(key, path, info):
        files[key] = {"path": path, "bytes": os.path.getsize(path)}
        files[key].update(info or {})

    path_3mf = os.path.join(model_dir, "aircraft.3mf")
    record("aircraft_3mf", path_3mf, export_3mf.write_3mf(
        path_3mf, [{"name": b["name"], "mesh": b["mesh"]} for b in bodies],
        title="AeroForge"))

    step_items = [{"name": b["name"], "mesh": b["mesh"]} for b in bodies]
    step_items += [{"name": r["name"], "mesh": r["mesh"]} for r in refs]
    path_step = os.path.join(model_dir, "aircraft.step")
    record("aircraft_step", path_step, export_step.write_step(
        path_step, step_items, title="AeroForge"))

    if refs:
        path_ref = os.path.join(ref_dir, "reference.3mf")
        record("reference_3mf", path_ref, export_3mf.write_3mf(
            path_ref, [{"name": r["name"], "mesh": r["mesh"]} for r in refs],
            title="AeroForge reference"))

    path_wing_dxf = os.path.join(model_dir, "wing_sections.dxf")
    record("wing_sections_dxf", path_wing_dxf, export_dxf.write_dxf(
        path_wing_dxf,
        [{"layer": "WING", "points": s["points"], "closed": True}
         for s in sections["wing"]]))

    path_fus_dxf = os.path.join(model_dir, "fuselage_stations.dxf")
    record("fuselage_stations_dxf", path_fus_dxf, export_dxf.write_dxf(
        path_fus_dxf,
        [{"layer": "FUSELAGE", "points": s["points"], "closed": True}
         for s in sections["fuselage"]]))

    wing_rows = []
    for sec in sections["wing"]:
        for (x, y, z) in sec["points"]:
            wing_rows.append([sec["name"], "%.1f" % sec["y_mm"],
                              "%.3f" % x, "%.3f" % y, "%.3f" % z])
    path_wing_csv = os.path.join(model_dir, "wing_sections.csv")
    record("wing_sections_csv", path_wing_csv, export_dxf.write_csv(
        path_wing_csv, wing_rows,
        ["section", "y_station_mm", "x_mm", "y_mm", "z_mm"]))

    fus_rows = []
    for sec in sections["fuselage"]:
        for (x, y, z) in sec["points"]:
            fus_rows.append([sec["name"], "%.1f" % sec["x_mm"],
                             "%.3f" % x, "%.3f" % y, "%.3f" % z])
    path_fus_csv = os.path.join(model_dir, "fuselage_stations.csv")
    record("fuselage_stations_csv", path_fus_csv, export_dxf.write_csv(
        path_fus_csv, fus_rows,
        ["station", "x_station_mm", "x_mm", "y_mm", "z_mm"]))

    params_path = os.path.join(model_dir, "params.json")
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump(_params(res), f, ensure_ascii=False, indent=2)
    record("params_json", params_path, {})

    readme_path = os.path.join(folder, "README.txt")
    with open(readme_path, "w", encoding="utf-8-sig") as f:
        f.write(README)
    record("readme", readme_path, {})

    print_out = printgeom.export(res, folder, bed, filament,
                                 slugify=lambda _name: "print", subdir="",
                                 quality=quality)
    if print_out.get("ok"):
        files["print"] = {
            "path": print_out["folder"],
            "files": len(print_out.get("files") or []),
            "plan": print_out.get("plan_path"),
        }

    manifest = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "design": name,
        "units": "mm",
        "datum": assembly.DATUM,
        "bodies": [{"name": b["name"],
                    "triangles": b["mesh"].triangles(),
                    "size_mm": [round(v, 1) for v in b["mesh"].size()],
                    "volume_cm3": round(b["mesh"].volume() / 1000.0, 2)}
                   for b in bodies],
        "reference": [{"name": r["name"], "note": r.get("note", "")}
                      for r in refs],
        "sections": {"wing": len(sections["wing"]),
                     "fuselage": len(sections["fuselage"])},
        "files": files,
    }
    manifest_path = os.path.join(folder, "model_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return {"ok": True, "folder": folder, "manifest": manifest,
            "manifest_path": manifest_path, "files": files}

