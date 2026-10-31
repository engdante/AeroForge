"""
export_3mf.py — запис на 3MF (3D Manufacturing Format) без зависимости.

3MF е zip с XML: един файл, много именувани тела, цвят и единица (mm).
Така целият самолет се отваря с една операция в CAD/слайсер и всяка част
може да се избира отделно.

Спецификация: Core 1.0 (2015/02). Пишем само нужното: resources + build.

Обектите са **solid**: 3MF не поддържа B-rep (NURBS), затова „solid“ в
3MF значи мрежа с манифолдни ръбове, еднаква ориентация и външни нормали
(Core 1.4, Chapter 4.1).  Преди запис всяко тяло се проверява с
`meshcheck.solid_report`; ако съдържа няколко обвивки, се разделя на
отделни обекти, за да е валидно всяко от тях.
"""

import os
import zipfile
from xml.sax.saxutils import escape

from . import meshcheck

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>
"""

RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""

MODEL_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
DEFAULT_COLORS = {
    "Wing": "#4DB3E6",
    "Fuselage": "#CFD8E3",
    "Stabilizer": "#9FB0C6",
    "Fin": "#8FA2BA",
    "Stabilizer_V_R": "#9FB0C6",
    "Stabilizer_V_L": "#8FA2BA",
}


def _color(name):
    base = DEFAULT_COLORS.get(name.split("_")[0], "#B0B8C4")
    return base + "FF"


def _vertices_xml(mesh):
    return "".join('<vertex x="%.4f" y="%.4f" z="%.4f"/>' % p
                   for p in mesh.vertices)


def _triangles_xml(mesh):
    return "".join('<triangle v1="%d" v2="%d" v3="%d"/>' % f
                   for f in mesh.faces)


def solidify(items):
    """
    Подготвя телата за 3MF: всяко става **един** затворен solid.

    Ако обект съдържа няколко обвивки, се разделя на отделни обекти
    (най-голямата запазва името, другите получават наставка „_2“, „_3“).
    връща (items, reports) — reports е по един доклад на краен обект.
    """
    out, reports = [], []
    for item in items:
        mesh = item.get("mesh")
        if not mesh or not mesh.faces:
            continue
        pieces = meshcheck.split_shells(mesh, [item["name"]])
        for name, piece in pieces:
            report = meshcheck.solid_report(piece)
            out.append({"name": name, "mesh": piece, "report": report})
            reports.append({"name": name, "ok": report["ok"],
                            "problems": report["problems"]})
    return out, reports


def model_xml(items, title="AeroForge"):
    """XML на 3D модела (resources + build) за списък от тела."""
    blocks = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model unit="millimeter" xml:lang="en-US" xmlns="%s">' % MODEL_NS,
        '<metadata name="Title">%s</metadata>' % escape(title),
        '<metadata name="Application">AeroForge</metadata>',
        '<metadata name="AeroForge:SolidObjects">true</metadata>',
        "<resources>",
        '<basematerials id="1">',
    ]
    for index, item in enumerate(items):
        blocks.append('<base name="%s" displaycolor="%s"/>'
                      % (escape(item["name"]), _color(item["name"])))
    blocks.append("</basematerials>")

    for index, item in enumerate(items):
        mesh = item["mesh"]
        blocks.append(
            '<object id="%d" type="model" name="%s" pid="1" pindex="%d">'
            % (index + 2, escape(item["name"]), index))
        blocks.append("<mesh>")
        blocks.append("<vertices>%s</vertices>" % _vertices_xml(mesh))
        blocks.append("<triangles>%s</triangles>" % _triangles_xml(mesh))
        blocks.append("</mesh>")
        blocks.append("</object>")
    blocks.append("</resources>")
    blocks.append("<build>")
    for index in range(len(items)):
        blocks.append('<item objectid="%d"/>' % (index + 2))
    blocks.append("</build>")
    blocks.append("</model>")
    return "".join(blocks)


def write_3mf(path, items, title="AeroForge"):
    """
    Записва 3MF. items = [{"name", "mesh"}].

    Връща {"objects", "bytes", "triangles", "solids", "problems"}.
    """
    items = [i for i in items if i.get("mesh") and i["mesh"].faces]
    if not items:
        return {"objects": 0, "bytes": 0, "triangles": 0, "solids": 0,
                "problems": []}
    items, reports = solidify(items)
    if not items:
        return {"objects": 0, "bytes": 0, "triangles": 0, "solids": 0,
                "problems": []}
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", RELS)
        zf.writestr("3D/3dmodel.model", model_xml(items, title))
    return {
        "objects": len(items),
        "bytes": os.path.getsize(path),
        "triangles": sum(item["mesh"].triangles() for item in items),
        "solids": sum(1 for r in reports if r["ok"]),
        "problems": [r for r in reports if not r["ok"]],
    }
