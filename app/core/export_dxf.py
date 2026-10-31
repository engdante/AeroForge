"""
export_dxf.py — DXF R12 (AC1009) с 3D полилинии, без зависимости.

Използва се за сеченията на крилото и тялото: в CAD по тях се прави
гладък loft (NURBS), който е по-добър от фасетирания STEP.

DXF е двойки „код на група / стойност“, всяка на нов ред. Пишем само
HEADER (версия, единици), TABLES (слоеве) и ENTITIES.
"""

import os


def _pairs(*pairs):
    """Сглобява двойки код/стойност във вид за писане."""
    out = []
    for code, value in pairs:
        out.append(str(code))
        out.append(str(value))
    return out


def _polyline(layer, points, closed=False):
    rows = _pairs((0, "POLYLINE"), (8, layer), (66, 1),
                  (70, 9 if closed else 8))
    for (x, y, z) in points:
        rows += _pairs((0, "VERTEX"), (8, layer),
                       (10, "%.4f" % float(x)),
                       (20, "%.4f" % float(y)),
                       (30, "%.4f" % float(z)),
                       (70, 32))
    rows += _pairs((0, "SEQEND"), (8, layer))
    return rows


def dxf_text(polylines, scale_mm=True):
    """
    Текст на DXF файл. polylines = [{"layer", "points", "closed"}].
    """
    layers = []
    for item in polylines:
        name = str(item.get("layer") or "0")
        if name not in layers:
            layers.append(name)

    rows = []
    rows += _pairs((0, "SECTION"), (2, "HEADER"),
                   (9, "$ACADVER"), (1, "AC1009"),
                   (9, "$INSUNITS"), (70, 4 if scale_mm else 0),
                   (0, "ENDSEC"))
    rows += _pairs((0, "SECTION"), (2, "TABLES"),
                   (0, "TABLE"), (2, "LAYER"), (70, len(layers)))
    for name in layers:
        rows += _pairs((0, "LAYER"), (2, name), (70, 0), (62, 7),
                       (6, "CONTINUOUS"))
    rows += _pairs((0, "ENDTAB"), (0, "ENDSEC"))

    rows += _pairs((0, "SECTION"), (2, "ENTITIES"))
    for item in polylines:
        points = item.get("points") or []
        if len(points) < 2:
            continue
        rows += _polyline(str(item.get("layer") or "0"), points,
                          bool(item.get("closed")))
    rows += _pairs((0, "ENDSEC"), (0, "EOF"))
    return "\n".join(rows) + "\n"


def write_dxf(path, polylines, scale_mm=True):
    """Записва DXF. Връща {"polylines", "points", "bytes"}."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    text = dxf_text(polylines, scale_mm)
    with open(path, "w", encoding="ascii", errors="replace") as f:
        f.write(text)
    written = [p for p in polylines if len(p.get("points") or []) >= 2]
    return {"polylines": len(written),
            "points": sum(len(p["points"]) for p in written),
            "bytes": os.path.getsize(path)}


def write_csv(path, rows, header):
    """Прост CSV с „;“ за координатите на сеченията."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(";".join(header) + "\r\n")
        for row in rows:
            f.write(";".join(str(v) for v in row) + "\r\n")
    return {"rows": len(rows), "bytes": os.path.getsize(path)}
