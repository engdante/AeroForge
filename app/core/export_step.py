"""
export_step.py — STEP (ISO 10303-21, AP214) с **истински solid тела**.

Пишем MANIFOLD_SOLID_BREP: затворена обвивка (CLOSED_SHELL) от ADVANCED_FACE
с планарни повърхности (PLANE) и споделени ръбове (EDGE_CURVE/ORIENTED_EDGE).
Това е валиден CAD solid — Fusion/SolidWorks/FreeCAD го внасят като **solid
body**, с който работят boolean операции (за разлика от FACETED_BREP, който
Fusion внася като mesh body: „a boolean needs a solid body“).

Повърхностите са равнинни (фасетирани), защото няма OpenCASCADE („само eel,
офлайн, един EXE“).  За гладка повърхност даваме сеченията (DXF) за loft.

Структура на файла:
    ISO-10303-21; HEADER; ... ENDSEC;
    DATA; <контекст> <за всяка част: PRODUCT → ...
           → ADVANCED_BREP_SHAPE_REPRESENTATION → MANIFOLD_SOLID_BREP> ENDSEC;
    END-ISO-10303-21;
"""

import datetime
import math
import os

APPLICATION_CONTEXT = "automotive design"
SCHEMA = "AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }"


class _Ids:
    """Брояч на entity номерата (#1, #2, ...)."""

    def __init__(self):
        self.value = 0

    def next(self):
        self.value += 1
        return "#%d" % self.value


def _num(value):
    return ("%.4f" % float(value)).rstrip("0").rstrip(".") or "0"


def _point(ids, lines, point):
    ref = ids.next()
    lines.append("%s=CARTESIAN_POINT('',(%s,%s,%s));"
                 % (ref, _num(point[0]), _num(point[1]), _num(point[2])))
    return ref


def _direction(ids, lines, vec):
    ref = ids.next()
    lines.append("%s=DIRECTION('',(%s,%s,%s));"
                 % (ref, _num(vec[0]), _num(vec[1]), _num(vec[2])))
    return ref


def _unit(vec):
    length = math.sqrt(vec[0] ** 2 + vec[1] ** 2 + vec[2] ** 2)
    if length <= 1e-12:
        return None
    return (vec[0] / length, vec[1] / length, vec[2] / length)


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0])


def _perp(normal):
    """Вектор, перпендикулярен на normal (за ref_direction)."""
    helper = (0.0, 0.0, 1.0) if abs(normal[2]) < 0.9 else (1.0, 0.0, 0.0)
    out = _unit(_cross(normal, helper))
    return out or (1.0, 0.0, 0.0)


def _solid(ids, lines, name, mesh, stats=None):
    """
    Едно тяло като **истински B-rep solid**: MANIFOLD_SOLID_BREP → CLOSED_SHELL
    от ADVANCED_FACE с планарни повърхности и споделени ръбове.

    Защо не FACETED_BREP: Fusion/SolidWorks внасят FACETED_BREP като
    **mesh body** („a boolean needs a solid body“), а MANIFOLD_SOLID_BREP с
    ADVANCED_FACE се внася като solid body и с него работят boolean операции.
    Топологията е валидна, ако мрежата е манифолдна (всеки ръб се ползва от
    точно 2 лица с противоположна посока) — това се проверява преди запис.
    """
    # 1. Върхове
    vertex_points = []
    for point in mesh.vertices:
        ref = ids.next()
        lines.append("%s=VERTEX_POINT('',%s);" % (ref, _point(ids, lines, point)))
        vertex_points.append(ref)

    # 2. Ръбове: всеки неориентиран ръб се среща веднъж в топологията
    edge_refs = {}
    for (a, b, c) in mesh.faces:
        for (u, v) in ((a, b), (b, c), (c, a)):
            key = (u, v) if u < v else (v, u)
            if key in edge_refs:
                continue
            p0 = mesh.vertices[key[0]]
            p1 = mesh.vertices[key[1]]
            direction = _unit((p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]))
            if direction is None:                      # изроден ръб
                edge_refs[key] = None
                continue
            length = math.dist(p0, p1)
            vector = ids.next()
            lines.append("%s=VECTOR('',%s,%s);"
                         % (vector, _direction(ids, lines, direction),
                            _num(length)))
            line = ids.next()
            lines.append("%s=LINE('',%s,%s);"
                         % (line, _point(ids, lines, p0), vector))
            curve = ids.next()
            lines.append("%s=EDGE_CURVE('',%s,%s,%s,.T.);"
                         % (curve, vertex_points[key[0]],
                            vertex_points[key[1]], line))
            edge_refs[key] = curve

    # 3. Лица (по един ADVANCED_FACE на триъгълник)
    face_refs = []
    skipped = 0
    for (a, b, c) in mesh.faces:
        pa, pb, pc = mesh.vertices[a], mesh.vertices[b], mesh.vertices[c]
        normal = _unit(_cross((pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]),
                              (pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2])))
        if normal is None:                              # нулева площ
            skipped += 1
            continue
        placement = ids.next()
        lines.append("%s=AXIS2_PLACEMENT_3D('',%s,%s,%s);"
                     % (placement, _point(ids, lines, pa),
                        _direction(ids, lines, normal),
                        _direction(ids, lines, _perp(normal))))
        plane = ids.next()
        lines.append("%s=PLANE('',%s);" % (plane, placement))

        oriented = []
        broken = False
        for (u, v) in ((a, b), (b, c), (c, a)):
            key = (u, v) if u < v else (v, u)
            curve = edge_refs.get(key)
            if not curve:
                broken = True
                break
            ref = ids.next()
            lines.append("%s=ORIENTED_EDGE('',*,*,%s,%s);"
                         % (ref, curve, ".T." if (u, v) == key else ".F."))
            oriented.append(ref)
        if broken:
            skipped += 1
            continue
        loop = ids.next()
        lines.append("%s=EDGE_LOOP('',(%s));" % (loop, ",".join(oriented)))
        bound = ids.next()
        lines.append("%s=FACE_OUTER_BOUND('',%s,.T.);" % (bound, loop))
        face = ids.next()
        lines.append("%s=ADVANCED_FACE('',(%s),%s,.T.);" % (face, bound, plane))
        face_refs.append(face)

    if not face_refs:
        return None
    shell = ids.next()
    lines.append("%s=CLOSED_SHELL('',(%s));" % (shell, ",".join(face_refs)))
    brep = ids.next()
    lines.append("%s=MANIFOLD_SOLID_BREP('%s',%s);" % (brep, name, shell))
    if stats is not None:
        stats["skipped_faces"] = stats.get("skipped_faces", 0) + skipped
    return brep


def _product(ids, lines, name, brep_ref, context_ref, placement_ref):
    product = ids.next()
    lines.append("%s=PRODUCT('%s','%s','',(#2));" % (product, name, name))
    formation = ids.next()
    lines.append("%s=PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE"
                 "('','',%s,.NOT_KNOWN.);" % (formation, product))
    definition = ids.next()
    lines.append("%s=PRODUCT_DEFINITION('design','',%s,#3);"
                 % (definition, formation))
    shape = ids.next()
    lines.append("%s=PRODUCT_DEFINITION_SHAPE('','',%s);"
                 % (shape, definition))
    representation = ids.next()
    lines.append("%s=ADVANCED_BREP_SHAPE_REPRESENTATION('%s',(%s,%s),%s);"
                 % (representation, name, placement_ref, brep_ref,
                    context_ref))
    link = ids.next()
    lines.append("%s=SHAPE_DEFINITION_REPRESENTATION(%s,%s);"
                 % (link, shape, representation))


def step_text(items, title="AeroForge"):
    """
    Връща текста на STEP файла. items = [{"name", "mesh"}].
    """
    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    lines = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('%s faceted solid'),'2;1');" % title,
        "FILE_NAME('%s','%s',('AeroForge'),(''),'AeroForge','AeroForge','');"
        % (title.replace("'", ""), stamp),
        "FILE_SCHEMA(('%s'));" % SCHEMA,
        "ENDSEC;",
        "DATA;",
        "#1=APPLICATION_CONTEXT('%s');" % APPLICATION_CONTEXT,
        "#2=PRODUCT_CONTEXT('',#1,'mechanical');",
        "#3=PRODUCT_DEFINITION_CONTEXT('part definition',#1,'design');",
        "#4=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));",
        "#5=(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.));",
        "#6=(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT());",
        "#7=UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.01),#4,'','');",
        "#8=(GEOMETRIC_REPRESENTATION_CONTEXT(3)"
        "GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#7))"
        "GLOBAL_UNIT_ASSIGNED_CONTEXT((#4,#5,#6))"
        "REPRESENTATION_CONTEXT('',''));",
    ]
    ids = _Ids()
    ids.value = 8
    # глобална ориентация за всяко ADVANCED_BREP_SHAPE_REPRESENTATION
    lines.append("#9=CARTESIAN_POINT('',(0.,0.,0.));")
    lines.append("#10=DIRECTION('',(0.,0.,1.));")
    lines.append("#11=DIRECTION('',(1.,0.,0.));")
    ids.value = 11
    placement = ids.next()
    lines.append("%s=AXIS2_PLACEMENT_3D('',#9,#10,#11);" % placement)
    stats = {"skipped_faces": 0}
    solids = 0
    for item in items:
        mesh = item.get("mesh")
        if not mesh or not mesh.faces:
            continue
        name = str(item.get("name") or "Part").replace("'", "")
        brep = _solid(ids, lines, name, mesh, stats)
        if not brep:
            continue
        _product(ids, lines, name, brep, "#8", placement)
        solids += 1
    lines.append("ENDSEC;")
    lines.append("END-ISO-10303-21;")
    return "\n".join(lines) + "\n", solids, stats


def write_step(path, items, title="AeroForge"):
    """Записва STEP файл. Връща {"solids", "triangles", "bytes"}."""
    items = [i for i in items if i.get("mesh") and i["mesh"].faces]
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    text, solids, stats = step_text(items, title)
    with open(path, "w", encoding="ascii", errors="replace") as f:
        f.write(text)
    return {"solids": solids,
            "triangles": sum(i["mesh"].triangles() for i in items),
            "skipped_faces": stats.get("skipped_faces", 0),
            "bytes": os.path.getsize(path)}
