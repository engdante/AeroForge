"""
solidcraft_export.py — гладък B-rep модел чрез SolidCraft (loft по сечения).

AeroForge не строи NURBS сам: геометрията се дава като **скици** (гладки
затворени профили на точната равнина), а SolidCraft прави повърхностите.
Експортът пише в папката на дизайна:

    sections/<тяло>/<секция>.svg   затворени профили (за ръчен loft/друг CAD)
    sections/manifest.csv          равнината на всяка секция
    solidcraft_model.json          команден скрипт за SolidCraft (loft + join)
    steps/profiles.json            същите профили без loft (за aircraft.sc)
    aircraft.step                  гладкият solid (ако solidcraft-cli работи)
    aircraft.sc                    дизайнът: само профилите, без loft

`aircraft.sc` завършва с профилите на тялото, крилата и опашката — Loft и
Join в него няма, свързването го прави потребителят. Гладкият solid за
STEP се строи в работния дизайн на стъпките (`steps/loft.sc`).

Скриптът може да се пусне и на ръка:

    solidcraft-cli run solidcraft_model.json --out aircraft.step

Форматът на скрипта е същият като на SolidCraft (`{"commands": [...]}`);
всяка секция е `sketch.create` → `sketch.spline.fit_point` → `sketch.line`
(за стената на задния ръб) → `sketch.finish`, накрая `solid.loft` (или
`solid.revolve` за спинер/каулинг) и `file.export`.
"""

import json
import math
import os
import shutil
import subprocess
import sys
import time

from . import assembly
from . import export_3mf
from . import export_dxf
from . import export_step

# Колко плътни да са сеченията на гладкия модел (независимо от мрежата).
# Cubic spline през 16 точки е гладка; повече точки не добавят нищо видимо,
# а вдигат броя на B-spline пачовете — а boolean-ът (join-ът с тялото) става
# драматично по-бавен и при много пачове SolidCraft блокира. Затова CAD
# моделът е умишлено по-лек от мрежата за печат.
DEFAULT_DETAIL = {
    "points": 16,             # точки на профила (крило/опашка)
    "stations": 5,            # сечения по размаха (на половин крило)
    "fuselage_ring": 20,      # точки на контура на тялото
    "fuselage_stations": 5,   # сечения по дължината
    "tail_stations": 5,
}

# Maximum geometric error when reducing each airfoil surface's fit points for
# SolidCraft sketches. This is only for the editable CAD loft; printed meshes
# and exported SVG control profiles retain their full-resolution geometry.
CAD_SPLINE_TOLERANCE_MM = 0.5

MANIFEST_HEADER = [
    "body", "section", "kind", "svg",
    "origin_x", "origin_y", "origin_z",
    "x_dir_x", "x_dir_y", "x_dir_z",
    "y_dir_x", "y_dir_y", "y_dir_z",
    "station_mm",
]

CLI_PATHS = (
    r"C:\Program Files\SolidCraft\solidcraft-cli.exe",
    r"C:\Program Files (x86)\SolidCraft\solidcraft-cli.exe",
    "/Applications/SolidCraft.app/Contents/MacOS/solidcraft-cli",
    "/usr/local/bin/solidcraft-cli",
    "/usr/bin/solidcraft-cli",
)


def find_cli():
    """
    Път до `solidcraft-cli` или None.

    Търси в SOLIDCRAFT_CLI, „Допълнения“ (tools/extras.json, tools/solidcraft),
    PATH и стандартните места за инсталация.
    """
    for key in ("SOLIDCRAFT_CLI", "SOLIDCRAFT_CLI_PATH"):
        value = os.environ.get(key)
        if value and os.path.isfile(value):
            return value
    try:   # зададен в „Допълнения“ или изтеглен portable (tools/solidcraft)
        from . import extras
        value = extras.configured_cli()
    except Exception:  # noqa: BLE001 — допълненията не бива да спират търсенето
        value = None
    if value:
        return value
    for name in ("solidcraft-cli", "solidcraft-cli.exe"):
        found = shutil.which(name)
        if found:
            return found
    for path in CLI_PATHS:
        if os.path.isfile(path):
            return path
    return None


def _r(value, digits=4):
    """Закръгля координата (стабилен JSON/XML, без -0)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    value = round(value, digits)
    return 0.0 if value == 0 else value


def _points2d(points):
    return [[_r(p[0]), _r(p[1])] for p in points]


def _vector(vec):
    return [_r(vec[0]), _r(vec[1]), _r(vec[2])]


def _plane(section):
    return {"origin": _vector(section["origin"]),
            "x_dir": _vector(section["x_dir"]),
            "y_dir": _vector(section["y_dir"])}


def airfoil_curves(section):
    """
    Разделя контура на профила на (горна, долна) крива.

    `airfoil_outline` дава LE → горна → TE_top → TE_bot → долна, а
    `split` е индексът на TE_top. Долната крива се връща обърната
    (TE_bot → … → LE), за да може контурът да се затвори с една линия
    по стената на задния ръб.
    """
    points = section["points2d"]
    split = section.get("split")
    if split is None or split >= len(points) - 1:
        return list(points), []
    upper = list(points[:split + 1])                 # LE → TE_top
    lower = list(points[split + 1:]) + [points[0]]   # TE_bot → … → LE
    return upper, lower


def _point_segment_distance(point, start, end):
    """Minimum 2D distance from a point to a finite line segment."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length2 = dx * dx + dy * dy
    if length2 <= 1e-18:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    t = max(0.0, min(1.0, (
        (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
    ) / length2))
    return math.hypot(point[0] - start[0] - t * dx,
                      point[1] - start[1] - t * dy)


def _simplified_curve_indices(curves, tolerance_mm):
    """Shared Douglas–Peucker indices for loft-compatible section curves."""
    if not curves or len(curves[0]) < 3:
        return list(range(len(curves[0]))) if curves else []
    count = len(curves[0])
    if any(len(curve) != count for curve in curves):
        return list(range(count))

    keep = {0, count - 1}

    def visit(curve, first, last, tolerance):
        start, end = curve[first], curve[last]
        index = None
        distance = tolerance
        for i in range(first + 1, last):
            current = _point_segment_distance(curve[i], start, end)
            if current > distance:
                index, distance = i, current
        if index is not None:
            keep.add(index)
            visit(curve, first, index, tolerance)
            visit(curve, index, last, tolerance)

    for curve in curves:
        chord = max(p[0] for p in curve) - min(p[0] for p in curve)
        if chord <= 1e-9:
            return list(range(count))
        normalized = [(p[0] / chord, p[1] / chord) for p in curve]
        visit(normalized, 0, count - 1, max(0.0, tolerance_mm) / chord)
    return sorted(keep)


def airfoil_spline(section):
    """
    Контурът на профила като ЕДИН отворен сплайн: заден ръб → едната
    повърхност → нос → другата повърхност → заден ръб; затваря се с правата
    стена на задния ръб. Носът е вътре в сплайна (гладък), а не шев между
    две криви. Връща (точки, индекс на носа) или ([], None) без стена.
    """
    upper, lower = airfoil_curves(section)
    if not lower:
        return [], None
    spline = list(lower) + list(upper[1:])     # TE₂ → … → нос → … → TE₁
    le = min(range(len(spline)), key=lambda i: (spline[i][0], abs(spline[i][1])))
    return spline, le


def simplified_airfoil_splines(sections, tolerance_mm=CAD_SPLINE_TOLERANCE_MM):
    """
    Опростените сплайни на сеченията с ОГЛЕДАЛНО избрани точки.

    Двете половини (от носа към всеки заден ръб) се опростяват поотделно, а
    после всяка запазва обединението на избраните индекси (мерени от носа).
    Профилите са с еднакви x горе и долу, затова при симетричен профил
    (кил, стабилизатор) двете страни на сплайна получават едни и същи
    станции — сплайнът е симетричен. Индексите са общи за всички сечения
    (loft-ът иска еднаква топология).
    """
    data = [airfoil_spline(section) for section in sections]
    if not data or any(le is None for _s, le in data):
        return [spline for spline, _le in data]
    les = {le for _s, le in data}
    lengths = {len(s) for s, _le in data}
    if len(les) != 1 or len(lengths) != 1:
        return [spline for spline, _le in data]
    le = les.pop()
    count = lengths.pop()
    side_a = [list(reversed(s[:le + 1])) for s, _le in data]    # нос → TE₂
    side_b = [list(s[le:]) for s, _le in data]                   # нос → TE₁
    if len(side_a[0]) == len(side_b[0]):
        keep = (set(_simplified_curve_indices(side_a, tolerance_mm))
                | set(_simplified_curve_indices(side_b, tolerance_mm)))
        keep = sorted(keep)
        out = []
        for a, b in zip(side_a, side_b):
            half_a = [a[i] for i in keep]
            half_b = [b[i] for i in keep]
            out.append(list(reversed(half_a)) + half_b[1:])
        return out
    keep = _simplified_curve_indices([s for s, _le in data], tolerance_mm)
    if count - 1 not in keep:
        keep.append(count - 1)
    return [[s[i] for i in sorted(set(keep) | {le})] for s, _le in data]


def _fmt(value):
    return ("%.4f" % _r(value)).rstrip("0").rstrip(".") or "0"


def _cubic_segments(points, closed=False):
    """Catmull-Rom → cubic Bézier сегменти (гладка крива през точките)."""
    pts = list(points)
    n = len(pts)
    if n < 2:
        return []
    if closed and n > 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
        n -= 1
    out = []
    segments = n if closed else n - 1
    for i in range(segments):
        if closed:
            p0, p1 = pts[(i - 1) % n], pts[i % n]
            p2, p3 = pts[(i + 1) % n], pts[(i + 2) % n]
        else:
            p0 = pts[max(0, i - 1)]
            p1, p2 = pts[i], pts[i + 1]
            p3 = pts[min(n - 1, i + 2)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0,
              p1[1] + (p2[1] - p0[1]) / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0,
              p2[1] - (p3[1] - p1[1]) / 6.0)
        out.append("C %s %s %s %s %s %s" % (
            _fmt(c1[0]), _fmt(c1[1]), _fmt(c2[0]), _fmt(c2[1]),
            _fmt(p2[0]), _fmt(p2[1])))
    return out


def _closed_path(points):
    """Затворен гладък SVG път през всички точки."""
    pts = list(points)
    if len(pts) < 3:
        return ""
    head = "M %s %s" % (_fmt(pts[0][0]), _fmt(pts[0][1]))
    return " ".join([head] + _cubic_segments(pts, closed=True) + ["Z"])


def _polygon_path(points):
    """Затворен път от прави отсечки (резачите на елероните)."""
    pts = list(points)
    if len(pts) < 3:
        return ""
    return " ".join(["M %s %s" % (_fmt(pts[0][0]), _fmt(pts[0][1]))]
                    + ["L %s %s" % (_fmt(p[0]), _fmt(p[1])) for p in pts[1:]]
                    + ["Z"])


def _profile_path(section):
    """Път на профил: LE → горна → TE_top → TE_bot → долна → LE."""
    if (section.get("primitive") or {}).get("type") == "polygon":
        return _polygon_path(section["points2d"])
    upper, lower = airfoil_curves(section)
    if not upper:
        return _closed_path(section["points2d"])
    head = "M %s %s" % (_fmt(upper[0][0]), _fmt(upper[0][1]))
    parts = [head] + _cubic_segments(upper)
    if lower:
        parts.append("L %s %s" % (_fmt(lower[0][0]), _fmt(lower[0][1])))
        parts += _cubic_segments(lower)
    return " ".join(parts + ["Z"])


def svg_text(points, path_d, primitive=None):
    """Самостоятелен SVG с един затворен профил (в mm, реални координати)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    pad = max(1.0, 0.04 * max(x1 - x0, y1 - y0))
    width = max(0.01, (x1 - x0) + 2 * pad)
    height = max(0.01, (y1 - y0) + 2 * pad)
    if primitive and primitive.get("type") == "ellipse":
        center = primitive["center"]
        major = primitive["major"]
        major_len = math.hypot(float(major[0]), float(major[1]))
        minor_len = float(primitive["minor_radius"])
        # `major` е краят на голямата ос: ако е по Y, осите се разменят.
        if abs(float(major[1])) > abs(float(major[0])):
            rx, ry = minor_len, major_len
        else:
            rx, ry = major_len, minor_len
        shape = ('<ellipse cx="%s" cy="%s" rx="%s" ry="%s" '
                 'fill="none" stroke="#000000" stroke-width="0.2"/>\n' % (
                     _fmt(center[0]), _fmt(center[1]), _fmt(rx), _fmt(ry)))
    else:
        shape = ('<path d="%s" fill="none" stroke="#000000" '
                 'stroke-width="0.2"/>\n' % path_d)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="%.3fmm" height="%.3fmm" '
        'viewBox="%.4f %.4f %.4f %.4f">\n'
        '<g transform="scale(1,-1)">\n'
        '%s'
        '</g>\n</svg>\n'
        % (width, height, x0 - pad, -(y1 + pad), width, height, shape))


def write_sections(folder, bodies):
    """
    Записва по един SVG на секция + редовете за `manifest.csv`.

    връща (rows, count)
    """
    rows = []
    count = 0
    for body in bodies:
        name = body["name"]
        body_dir = os.path.join(folder, name)
        os.makedirs(body_dir, exist_ok=True)
        if body["kind"] == "revolve":
            profile = body["profile"]
            with open(os.path.join(body_dir, "profile.svg"), "w",
                      encoding="utf-8") as f:
                f.write(svg_text(profile, _closed_path(profile)))
            plane = body["plane"]
            rows.append([name, "profile", "revolve",
                         "sections/%s/profile.svg" % name]
                        + _vector(plane["origin"])
                        + _vector(plane["x_dir"])
                        + _vector(plane["y_dir"]) + [""])
            count += 1
            continue
        for section in body["sections"]:
            label = section["name"]
            with open(os.path.join(body_dir, "%s.svg" % label), "w",
                      encoding="utf-8") as f:
                f.write(svg_text(section["points2d"],
                                 _profile_path(section),
                                 section.get("primitive")))
            rows.append([name, label, "loft",
                         "sections/%s/%s.svg" % (name, label)]
                        + _vector(section["origin"])
                        + _vector(section["x_dir"])
                        + _vector(section["y_dir"])
                        + [_r(section["station_mm"], 2)])
            count += 1
    return rows, count


def body_order(bodies):
    """
    Подрежда телата така, че всяко да е след тялото, в което се влива.

    SolidCraft строи един solid в историята: тялото-основа първо, после
    крило/опашка/спинер с `operation: join, targets: [основата]`.

    `after` е само зависимост по ред (без join) — ползва се, когато две
    тела влизат в едно и също тяло, но редът им е важен (каулинг преди
    спинер).
    """
    by_name = {body["name"]: body for body in bodies}
    out, seen = [], set()

    def visit(body, depth=0):
        name = body["name"]
        if name in seen or depth > 32:
            return
        for parent in (body.get("after"), body.get("into")):
            if parent and parent in by_name:
                visit(by_name[parent], depth + 1)
        seen.add(name)
        out.append(body)

    for body in bodies:
        visit(body)
    return out


def build_commands(bodies, out_step=None, combine=True, loft=True):
    """
    Командите за SolidCraft: скица на всяка секция → loft/revolve → combine.

    Всяко тяло носи `into` (името на тялото, в което се влива); всички
    тела се създават отделно, а накрая **един** `solid.combine` обединява
    цялата група с тялото. Скиците са именувани „<тяло> <секция>“, loft-овете
    — „<тяло> loft“, за да се четат в дървото на дизайна.

    `combine=False` оставя телата отделни (за 3MF/STEP без boolean).

    `loft=False` спира след скиците: скриптът дава само **профилите** на
    тялото, крилата и опашката (виж `profile_bodies`), без loft, revolve и
    combine — свързването остава за потребителя.
    """
    if not loft:
        bodies = profile_bodies(bodies)
    commands = []
    for body in body_order(bodies):
        name = body["name"]
        if body["kind"] == "revolve":
            if not loft:
                continue
            profile = body["profile"]
            commands.append({"command": "sketch.create", "params": {
                "plane": {key: _vector(value)
                          for key, value in body["plane"].items()},
                "frame": "world", "name": name}})
            commands.append({"command": "sketch.line", "params": {
                "points": _points2d(profile), "closed": True}})
            commands.append({"command": "sketch.finish", "params": {}})
            commands.append({"command": "solid.revolve", "params": {
                "sketch": name, "axis": body.get("axis", "x"),
                "body_name": name, "name": "%s revolve" % name}})
            continue

        labels = []
        sections = body["sections"]
        splines = simplified_airfoil_splines(sections)
        for section, spline in zip(sections, splines):
            sketch = "%s %s" % (name, section["name"])
            labels.append(sketch)
            commands.append({"command": "sketch.create", "params": {
                "plane": _plane(section), "frame": "world", "name": sketch}})
            primitive = section.get("primitive")
            if primitive and primitive.get("type") == "polygon":
                # резач (призма на елерона): затворен многоъгълник
                commands.append({"command": "sketch.line", "params": {
                    "points": _points2d(section["points2d"]),
                    "closed": True}})
            elif primitive and primitive.get("type") == "ellipse":
                commands.append({"command": "sketch.ellipse", "params": {
                    "center": _points2d([primitive["center"]])[0],
                    "major": _points2d([primitive["major"]])[0],
                    "minor_radius": _r(primitive["minor_radius"])}})
            elif not spline:
                commands.append({
                    "command": "sketch.spline.fit_point",
                    "params": {"points": _points2d(section["points2d"]),
                               "periodic": True}})
            else:
                # един сплайн през носа (гладък и симетричен) + стената на
                # задния ръб (виж simplified_airfoil_splines)
                commands.append({
                    "command": "sketch.spline.fit_point",
                    "params": {"points": _points2d(spline)}})
                commands.append({
                    "command": "sketch.line",
                    "params": {"points": _points2d([spline[-1], spline[0]])}})
            commands.append({"command": "sketch.finish", "params": {}})
        if not loft:
            # само профилите: свързването (loft-овете) е за потребителя
            continue
        params = {"sections": [{"sketch": label} for label in labels],
                  "body_name": name, "name": "%s loft" % name}
        commands.append({"command": "solid.loft", "params": params})
        commands.extend(_cutter_commands(body))

    if not loft:
        return commands

    # Всички тела се създават отделно, а обединяването е **една** операция
    # на тяло: `solid.combine` с всички инструменти наведнъж. Последователните
    # join-ове върху вече променяно тяло са това, което висеше в SolidCraft
    # (лявото крило върху тяло с дясно крило); един combine с двете
    # полукрила минава за секунди.
    if combine:
        targets = {}
        for body in body_order(bodies):
            into = body.get("into")
            if into:
                targets.setdefault(into, []).append(body["name"])
        for target, tools in targets.items():
            commands.append({"command": "solid.combine", "params": {
                "target": target, "tools": list(tools),
                "operation": "join"}})

    if out_step:
        commands.append({"command": "file.export", "params": {
            "path": str(out_step).replace("\\", "/"), "format": "step"}})
    return commands


def _cutter_commands(body):
    """
    Boolean-ите на резачите (елерони), веднага след loft-а им.

    `op: intersect` — тялото-резач става сечението си с `with` (крилото
    остава: `keep_tools`), т.е. от призмата остава самият елерон.
    `op: cut` — резачът се изважда от `from` (крилото) и оставя процепа.
    """
    op = body.get("op")
    name = body["name"]
    if op == "intersect" and body.get("with"):
        return [{"command": "solid.combine", "params": {
            "target": name, "tools": [body["with"]],
            "operation": "intersect", "keep_tools": True,
            "name": "%s intersect" % name}}]
    if op == "cut" and body.get("from"):
        return [{"command": "solid.combine", "params": {
            "target": body["from"], "tools": [name], "operation": "cut",
            "name": "%s cut" % name}}]
    return []


def profile_bodies(bodies):
    """
    Телата, чийто профил има смисъл да се свързва на ръка: тяло, криле, опашка.

    Каулингът и спинерът са revolve (не секции за loft), а уинглетите са
    малки профили в върха — те не влизат в списъка за ръчно свързване.
    """
    return [body for body in body_order(bodies)
            if body["kind"] == "loft"
            and not body["name"].startswith("Winglet")
            and not body.get("cutter")]


def build_script(bodies, out_step=None, combine=True, loft=True):
    """Целият команден скрипт за SolidCraft."""
    return {"commands": build_commands(bodies, out_step, combine=combine,
                                       loft=loft)}


def step_errors(text):
    """
    Грешките по стъпки от stderr на SolidCraft → [(индекс, команда, текст)].

    `run --allow-errors` записва файла и при провален join, а причината
    остава в stderr: „error: step 49 (solid.loft): the join could not …“.
    """
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("error: step "):
            continue
        rest = line[len("error: step "):]
        idx, _, tail = rest.partition(" ")
        command, _, message = tail.partition(": ")
        command = command.strip("()")
        out.append((idx, command, message.strip() or tail.strip()))
    return out


def run_cli(script_path, out_step=None, save_design=None, timeout=300,
            cli=None, allow_errors=True):
    """
    Пуска `solidcraft-cli run` върху скрипта.

    `allow_errors=True` (по подразбиране) кара SolidCraft да запише файла
    дори ако един join се провали — така експортът не гърми заради едно
    тяло, а причината се връща в `errors`.

    връща {"ok", "cli", "returncode", "stdout", "stderr", "error", "errors"}
    """
    exe = cli or find_cli()
    if not exe:
        return {"ok": False, "cli": None, "errors": [],
                "error": "solidcraft-cli не е намерен (PATH или %s)"
                         % CLI_PATHS[0]}
    args = [exe, "run", script_path]
    if out_step:
        args += ["--out", out_step]
    if save_design:
        args += ["--save", save_design]
    if allow_errors:
        args.append("--allow-errors")
    kwargs = {"capture_output": True, "text": True, "timeout": timeout,
              "encoding": "utf-8", "errors": "replace"}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(args, **kwargs)
    except subprocess.TimeoutExpired:
        return {"ok": False, "cli": exe, "errors": [],
                "error": "SolidCraft не отговори за %d s" % timeout}
    except OSError as exc:
        return {"ok": False, "cli": exe, "errors": [], "error": str(exc)}

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    errors = step_errors(stderr) + step_errors(stdout)
    ok = proc.returncode == 0
    error = None
    if not ok:
        error = stderr or stdout or ("SolidCraft върна код %d"
                                     % proc.returncode)
    elif out_step and not os.path.exists(out_step):
        ok = False
        error = "SolidCraft приключи, но не записа %s" % out_step
    return {"ok": ok, "cli": exe, "returncode": proc.returncode,
            "stdout": stdout[-4000:], "stderr": stderr[-4000:],
            "errors": errors, "error": error}


def readme_text(name, bodies, joins=None, sink_mm=0.0, split=None,
                info=None):
    """
    README в папката на експорта: какво има, как е построено, как се редактира.

    `info` носи данните за 3MF-а и позицията на крилото (виж `export_job`).
    """
    info = info or {}
    three_mf = info.get("three_mf") or {}
    lines = [
        "AeroForge — модел, построен в SolidCraft",
        "=" * 42,
        "",
        "Дизайн: %s" % name,
    ]
    if info.get("wing_offset_desc"):
        lines.append("Крило: %s" % info["wing_offset_desc"])
    lines += [
        "",
        "Какво има тук:",
        "  aircraft.step          обединеният solid — за CAD с boolean операции",
        "  aircraft.3mf           същата геометрия като мрежа — за друг CAD/слайсер",
        "  aircraft.sc            дизайнът на AeroForge: САМО профилите, без loft",
        "  preview.png            как изглежда моделът (iso изглед)",
        "  reference.step/.3mf    габарити: батерия, мотор, ESC, приемник, серво, ЦГ",
        "  sections/              по един SVG профил на всяка секция + manifest.csv",
        "  steps/                 командните скриптове + loft.sc (loft-ът и join-овете)",
        "  aircraft_detailed.sc   ДЕТАЙЛЕН модел: крило и опашка с централен профил,",
        "                         слети с кухото тяло; капак, серва, елерони с панта,",
        "                         мотор (стойка, 4×M3) и витло",
        "  aircraft_detailed.step същият детайлен модел като STEP",
        "",
        "3MF или STEP?",
        "  3MF е МРЕЖА (триъгълници): отваря се навсякъде (Fusion, FreeCAD,",
        "  SolidWorks, Blender, Prusa/Bambu), но не е B-rep solid — не можеш да",
        "  правиш boolean, отвори и джобове по него.",
        "  STEP е SOLID (B-rep с BSpline повърхности): с него работят boolean",
        "  операции, отвори за серва, джобове за управлението, капаци.",
    ]
    if three_mf.get("source") == "solidcraft":
        lines.append("  Тук aircraft.3mf е изнесен от същия solid (%s)."
                     % (three_mf.get("quality") or "standard"))
    elif three_mf.get("source") == "mesh":
        lines.append("  Тук aircraft.3mf е от мрежата на AeroForge (SolidCraft "
                     "не е изпълнен).")
    if info.get("detailed_notes"):
        lines += ["", "ДЕТАЙЛЕН МОДЕЛ (aircraft_detailed.sc)%s:"
                  % ("" if info.get("detailed_built")
                     else " — само скриптът steps/detailed.json")]
        lines += ["  " + note for note in info["detailed_notes"]]
        lines += [
            "  Тела: Fuselage (тяло + крило + опашка, слети в едно), Hatch",
            "  (капак), Aileron_R/L, Servo_Cover_R/L, Spar_Tube, Spinner,",
            "  Elevator_R/L + Rudder (или Ruddervator_R/L при V-опашка),",
            "  Pushrod_* — тягите; REF_Servo_* — сервата, REF_Motor_* и",
            "  REF_Prop_* — моторът и витлото (само ориентир, не се печатат).",
            "  Моторът се завинтва с 4×M3 през стойката и преградата.",
            "  Вътрешността на тялото е празна — моделирай я сам.",
            "  Ос на пантата: крило — филамент 1.75 mm, опашка — стоманена",
            "  тел Ø1 mm; вкарва се от върха (при T-опашка рудерът — отгоре).",
            "  Тягите на опашката минават през канали Ø3.2 в тялото.",
        ]
    lines += [
        "",
        "Ред на импорт:",
        "  1. aircraft.step или aircraft.3mf — частите на самолета",
        "  2. reference.step/.3mf — обемите за ориентир (скрий ги след позициониране)",
        "",
        "КАК Е ПОСТРОЕН (както би го направил човек):",
        "  всяка секция е скица на своята равнина, профилът е spline през",
        "  точките. aircraft.sc спира дотук: в него има само профилите на",
        "  тялото, крилата и опашката — Linked/Loft и Join ги правиш ти.",
        "  Гладкият solid (aircraft.step) е построен със същите скици в",
        "  работния дизайн steps/loft.sc (loft + join), който aircraft.sc не",
        "  съдържа.",
        "",
    ]
    lines.append("Свързване (loft + join) — как е сглобен steps/loft.sc:")
    for row in (joins or []):
        lines.append("    %-14s → %-10s застъпване %s mm"
                     % (row.get("body", "?"), row.get("into", "?"),
                        _fmt(row.get("embed_mm") or 0)))
    if not joins:
        lines.append("    (без обединяване: телата са самостоятелни)")
    if split:
        lines += [
            "",
            "  Крилото и стабилизаторът са по две половини (разрез в y = 0).",
        ]
        if joins:
            lines += [
                "  Коренът на всяка е вътре в тялото и се влива в него с един",
                "  чист join. Цяла повърхност, която минава през тялото, дава",
                "  пресечна крива от две дъги и SolidCraft не я смята.",
            ]
        else:
            lines += [
                "  Всяка половина е самостоятелно тяло с луфт към тялото —",
                "  без обединяване.",
            ]
    if sink_mm:
        lines += [
            "",
            "  Коренът на крилото е преместен с %s mm навътре в тялото и" % _fmt(sink_mm),
            "  отместването затихва до 0 към върха. Без това крилото и тялото",
            "  само се допират и SolidCraft отказва обединението",
            "  („the join could not be computed reliably“).",
        ]
    lines += [
        "",
        "РЕДАКЦИЯ НА РЪКА:",
        "  Отвори aircraft.sc в SolidCraft. В дървото има само скици:",
        "    <тяло> S01…   — по една скица на всяка секция (профилите)",
        "  Свържи ги: избери скиците на едно тяло по ред (S01, S02, …) →",
        "  Solid ▸ Loft, после Join спрямо тялото. После премести точка от",
        "  spline-а на някоя скица (напр. Wing_R S01) — твоят loft се преизгражда.",
        "  Готовият вариант (същите скици + loft + join) е steps/loft.sc.",
        "  sections/manifest.csv дава за всяка скица равнината (origin / x_dir /",
        "  y_dir) и станцията в mm — оттам са и скиците в aircraft.sc.",
        "",
        "Ако aircraft.step липсва, loft-ът не е изпълнен. Пусни го с:",
        "",
        "  solidcraft-cli run solidcraft_model.json --out aircraft.step --save steps/loft.sc",
        "",
        "Тела в модела:",
    ]
    cutters = [body for body in bodies if body.get("cutter")]
    if cutters:
        lines += [
            "  Елерони: за всяка половина призма зад линията на пантата.",
            "    Aileron_R/L       сечение с крилото (intersect) → самият елерон",
            "    Aileron_Slot_R/L  изрязва се от крилото (cut) → процеп около него",
            "  Елеронът е отделно тяло; пантата/хорнът се добавят в CAD.",
            "",
        ]
    profiles = {body["name"] for body in profile_bodies(bodies)}
    for body in bodies:
        if body.get("op") == "cut":
            lines.append("  %-14s резач → cut от %s" % (body["name"],
                                                        body.get("from")))
            continue
        if body.get("op") == "intersect":
            lines.append("  %-14s елерон (intersect с %s) · само в steps/loft.sc"
                         % (body["name"], body.get("with")))
            continue
        mark = (" · профилите в aircraft.sc"
                if body["name"] in profiles else " · само в steps/loft.sc")
        if body["kind"] == "revolve":
            lines.append("  %-14s revolve → join%s" % (body["name"], mark))
        else:
            lines.append("  %-14s %2d сечения → join%s"
                         % (body["name"], len(body.get("sections") or []), mark))
    lines += [
        "",
        "За ръчен loft в друг CAD:",
        "  sections/manifest.csv дава за всяка секция origin / x_dir / y_dir —",
        "  създай скица на тази равнина (frame: world) и вкарай SVG-то.",
        "",
    ]
    return "\n".join(lines)



def group_steps(bodies):
    """
    Стъпките на експорта — по една група тела на пуск на SolidCraft.

    Групирането е и за скорост: boolean-ът работи върху по-малки тела, а
    всяка стъпка има собствен таймаут. Така един бавен join не блокира
    целия експорт — стъпката се маркира „пропуснато“ и се продължава.

    връща [{"id", "kind": "prep|group|finish", "label", "bodies", "est_s"}]
    """
    names = [b["name"] for b in bodies]
    steps = [{"id": "prep", "kind": "prep", "label": "Сечения + 3MF (мрежа)",
              "bodies": [], "est_s": 1.5}]
    # Профилите са отделна стъпка и тя е първата, която пипа дизайна:
    # `aircraft.sc` завършва с тях (без loft), а loft-ът и join-овете се
    # пускат в работния дизайн на стъпките за STEP.
    steps.append({"id": "profiles", "kind": "profiles",
                  "label": "Профили в aircraft.sc (без loft)",
                  "bodies": [], "est_s": 6.0})
    base = [n for n in ("Fuselage", "Cowl", "Spinner") if n in names]
    if base:
        steps.append({"id": "body", "kind": "group", "label": "Тяло и нос",
                      "bodies": base, "est_s": 7.0})
    # Двете полукрила са в **една** стъпка: `build_commands` прави един
    # `solid.combine` с двата инструмента. Отделни стъпки означават второ
    # вливане във вече променено тяло (лявото крило върху тяло с дясно
    # крило) — точно пътят, който висеше и надхвърляше таймаута, а при
    # прекъсване моделът оставаше само с едно крило.
    wings = [name for name in ("Wing", "Wing_R", "Wing_L",
                               "Winglet_R", "Winglet_L",
                               "Aileron_R", "Aileron_Slot_R",
                               "Aileron_L", "Aileron_Slot_L")
             if name in names]
    if wings:
        has_ailerons = any(n.startswith("Aileron") for n in wings)
        steps.append({"id": "wing", "kind": "group",
                      "label": ("Крила + елерони (ляво + дясно)"
                                if has_ailerons else "Крила (ляво + дясно)"),
                      "bodies": wings,
                      "est_s": 70.0 + (20.0 if has_ailerons else 0.0)})
    fin = [name for name in ("Fin",) if name in names]
    if fin:
        steps.append({"id": "fin", "kind": "group", "label": "Кил",
                      "bodies": fin, "est_s": 14.0})
    tail = [name for name in ("Stabilizer_R", "Stabilizer_L",
                              "Stabilizer_V_R", "Stabilizer_V_L")
            if name in names]
    if tail:
        steps.append({"id": "tail", "kind": "group",
                      "label": "Стабилизатор (отделно тяло)",
                      "bodies": tail, "est_s": 6.0})
    used = {name for step in steps for name in step["bodies"]}
    rest = [name for name in names if name not in used]
    if rest:
        steps.append({"id": "rest", "kind": "group", "label": "Останали тела",
                      "bodies": rest, "est_s": 10.0})
    steps.append({"id": "finish", "kind": "finish",
                  "label": "STEP + 3MF + превю", "bodies": [], "est_s": 12.0})
    return steps


def profiles_script(bodies):
    """Скрипт само със скиците-профили (тяло, криле, опашка) — за aircraft.sc."""
    return build_script(profile_bodies(bodies), loft=False)


def group_script(bodies, names, out_step=None):
    """
    Скрипт само за избраните тела (в правилния ред: тялото-основа първо).

    Скриптовете на стъпките се записват в папката (`steps/`), за да може
    всяка стъпка да се пусне и на ръка.
    """
    wanted = [body for body in body_order(bodies) if body["name"] in names]
    return build_script(wanted, out_step)


def parse_timing(text):
    """
    `--timings` от stdout → {"total_ms", "boolean_ms", "commands"}.

    `boolean_ms` е делът на boolean-ите (от `--profile`): точно той показва
    защо един join е бавен.
    """
    start = (text or "").find("{")
    if start < 0:
        return {}
    try:
        data = json.loads(text[start:])
    except ValueError:
        return {}
    total = float(data.get("total_ms") or 0.0)
    boolean = 0.0
    rows = data.get("timings") or []
    for row in rows:
        profile = row.get("profile") or {}
        boolean += float(profile.get("boolean_ms") or 0.0)
    return {"total_ms": total, "boolean_ms": boolean, "commands": len(rows)}


def run_group(script_path, design_path, first=False, timeout=120, cli=None,
              save=True):
    """
    Една стъпка от експорта: `run` върху скрипта, върху вече започнат дизайн.

    `first=False` подава `--in design.sc`, т.е. командите се добавят към
    съществуващата история — така всяка стъпка е отделен кратък пуск с
    реален прогрес, вместо един дълъг, който виси.

    връща {"ok", "ms", "timing", "errors", "stderr", "returncode"}
    """
    exe = cli or find_cli()
    if not exe:
        return {"ok": False, "ms": 0, "timing": {}, "errors": [],
                "error": "solidcraft-cli не е намерен"}
    args = [exe, "run", script_path]
    if not first and design_path:
        args += ["--in", design_path]
    if save and design_path:
        args += ["--save", design_path]
    # `--timings --profile` не е само статистика: без тях SolidCraft пуска
    # „интерактивния“ път, в който същият скрипт виси и boolean-ът се
    # проваля („boolean Union: the operation failed: no result“). С тях
    # същата геометрия минава за секунди — затова са задължителни тук.
    args += ["--allow-errors", "--timings", "--profile",
             "--param-check", "off"]
    kwargs = {"capture_output": True, "text": True, "timeout": timeout,
              "encoding": "utf-8", "errors": "replace"}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    started = time.time()
    try:
        proc = subprocess.run(args, **kwargs)
    except subprocess.TimeoutExpired:
        return {"ok": False, "ms": int((time.time() - started) * 1000),
                "timing": {}, "errors": [],
                "error": "таймаут %d s" % timeout, "timed_out": True}
    except OSError as exc:
        return {"ok": False, "ms": 0, "timing": {}, "errors": [],
                "error": str(exc)}
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    errors = step_errors(stderr) + step_errors(stdout)
    return {
        "ok": proc.returncode == 0 and not errors,
        "ms": int((time.time() - started) * 1000),
        "timing": parse_timing(stdout),
        "errors": errors,
        "returncode": proc.returncode,
        "stdout": stdout[-4000:],
        "stderr": stderr[-4000:],
        "error": None if proc.returncode == 0 else (stderr or stdout)[-400:],
    }


def mesh_3mf(res, path, quality=None):
    """3MF от мрежата на AeroForge (бърз, всеки обект = затворено тяло)."""
    bodies = assembly.build_assembly(res, quality)
    if not bodies:
        return {"objects": 0, "bytes": 0, "triangles": 0, "solids": 0,
                "problems": [], "source": "mesh"}
    info = export_3mf.write_3mf(
        path, [{"name": body["name"], "mesh": body["mesh"]} for body in bodies],
        title="AeroForge")
    info["source"] = "mesh"
    return info


def reference_files(res, folder):
    """
    Референтните обеми (батерия, мотор, ESC, приемник, серво, ЦГ) като
    отделни STEP и 3MF — импортват се СЛЕД частите на самолета.
    """
    refs = assembly.reference_bodies(res)
    if not refs:
        return {}
    out = {}
    items = [{"name": ref["name"], "mesh": ref["mesh"]} for ref in refs]
    step_path = os.path.join(folder, "reference.step")
    try:
        info = export_step.write_step(step_path, items,
                                      title="AeroForge reference")
        out["reference_step"] = {"path": step_path, "solids": info.get("solids")}
    except Exception:  # noqa: BLE001 — референциите не са критични
        pass
    three_mf = os.path.join(folder, "reference.3mf")
    try:
        info = export_3mf.write_3mf(three_mf, items,
                                    title="AeroForge reference")
        info["source"] = "mesh"
        out["reference_3mf"] = dict(info, path=three_mf)
    except Exception:  # noqa: BLE001
        pass
    return out


def snapshot(step_path, png_path, cli=None, timeout=90):
    """PNG превю на готовия модел (`snapshot --view iso`) за панела."""
    exe = cli or find_cli()
    if not exe or not step_path or not os.path.exists(step_path):
        return None
    args = [exe, "snapshot", "--in", step_path, "--out", png_path,
            "--view", "iso", "--no-grid"]
    kwargs = {"capture_output": True, "text": True, "timeout": timeout,
              "encoding": "utf-8", "errors": "replace"}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(args, **kwargs)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return png_path if os.path.exists(png_path) else None


def _bbox(raw):
    """bbox от `eval` → {"min", "max"} с точно 3 числа (или None)."""
    if not isinstance(raw, dict):
        return None
    low = raw.get("min")
    high = raw.get("max")
    if not isinstance(low, (list, tuple)) or not isinstance(high, (list, tuple)):
        return None
    if len(low) < 3 or len(high) < 3:
        return None
    try:
        return {"min": [float(v) for v in low[:3]],
                "max": [float(v) for v in high[:3]]}
    except (TypeError, ValueError):
        return None


def evaluate(step_path, cli=None, timeout=180):
    """`eval` върху STEP: тела, затворени ли са, какви повърхности има."""
    exe = cli or find_cli()
    if not exe or not step_path or not os.path.exists(step_path):
        return None
    kwargs = {"capture_output": True, "text": True, "timeout": timeout,
              "encoding": "utf-8", "errors": "replace"}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run([exe, "eval", step_path], **kwargs)
    except (subprocess.TimeoutExpired, OSError):
        return None
    text = proc.stdout or ""
    start = text.find("{")
    if start < 0:
        return None
    try:
        data = json.loads(text[start:])
    except ValueError:
        return None
    return {
        "body_count": data.get("body_count"),
        "bodies": [{"name": body.get("name"), "closed": body.get("closed"),
                    "volume_mm3": body.get("volume_mm3"),
                    "bbox": _bbox(body.get("bbox")),
                    "face_types": sorted(set(body.get("face_types") or []))}
                   for body in (data.get("bodies") or [])],
    }


def export(res, base_dir, quality=None, detail=None, slugify=None,
           run=True, timeout=120, save_design=True, options=None):
    """Синхронен експорт: същите стъпки като панела, без междинен прогрес."""
    from . import export_job
    return export_job.run_all(res, base_dir, quality=quality, detail=detail,
                              slugify=slugify, run=run, timeout=timeout,
                              save_design=save_design, options=options)


