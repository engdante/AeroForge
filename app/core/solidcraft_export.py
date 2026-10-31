"""
solidcraft_export.py — гладък B-rep модел чрез SolidCraft (loft по сечения).

AeroForge не строи NURBS сам: геометрията се дава като **скици** (гладки
затворени профили на точната равнина), а SolidCraft прави повърхностите.
Експортът пише в папката на дизайна:

    sections/<тяло>/<секция>.svg   затворени профили (за ръчен loft/друг CAD)
    sections/manifest.csv          равнината на всяка секция
    solidcraft_model.json          команден скрипт за SolidCraft
    aircraft.step                  гладкият solid (ако solidcraft-cli работи)
    aircraft.sc                    дизайнът с история (скици + loft)

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

    Търси в SOLIDCRAFT_CLI, PATH и стандартните места за инсталация.
    """
    for key in ("SOLIDCRAFT_CLI", "SOLIDCRAFT_CLI_PATH"):
        value = os.environ.get(key)
        if value and os.path.isfile(value):
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


def _profile_path(section):
    """Път на профил: LE → горна → TE_top → TE_bot → долна → LE."""
    upper, lower = airfoil_curves(section)
    if not upper:
        return _closed_path(section["points2d"])
    head = "M %s %s" % (_fmt(upper[0][0]), _fmt(upper[0][1]))
    parts = [head] + _cubic_segments(upper)
    if lower:
        parts.append("L %s %s" % (_fmt(lower[0][0]), _fmt(lower[0][1])))
        parts += _cubic_segments(lower)
    return " ".join(parts + ["Z"])


def svg_text(points, path_d):
    """Самостоятелен SVG с един затворен профил (в mm, реални координати)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    pad = max(1.0, 0.04 * max(x1 - x0, y1 - y0))
    width = max(0.01, (x1 - x0) + 2 * pad)
    height = max(0.01, (y1 - y0) + 2 * pad)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="%.3fmm" height="%.3fmm" '
        'viewBox="%.4f %.4f %.4f %.4f">\n'
        '<g transform="scale(1,-1)">\n'
        '<path d="%s" fill="none" stroke="#000000" stroke-width="0.2"/>\n'
        '</g>\n</svg>\n'
        % (width, height, x0 - pad, -(y1 + pad), width, height, path_d))


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
                                 _profile_path(section)))
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


def build_commands(bodies, out_step=None, combine=True):
    """
    Командите за SolidCraft: скица на всяка секция → loft/revolve → combine.

    Всяко тяло носи `into` (името на тялото, в което се влива); всички
    тела се създават отделно, а накрая **един** `solid.combine` обединява
    цялата група с тялото. Скиците са именувани „<тяло> <секция>“, loft-овете
    — „<тяло> loft“, за да се четат в дървото на дизайна.

    `combine=False` оставя телата отделни (за 3MF/STEP без boolean).
    """
    commands = []
    for body in body_order(bodies):
        name = body["name"]
        if body["kind"] == "revolve":
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
        for section in body["sections"]:
            sketch = "%s %s" % (name, section["name"])
            labels.append(sketch)
            commands.append({"command": "sketch.create", "params": {
                "plane": _plane(section), "frame": "world", "name": sketch}})
            upper, lower = airfoil_curves(section)
            if not lower:
                commands.append({
                    "command": "sketch.spline.fit_point",
                    "params": {"points": _points2d(section["points2d"]),
                               "periodic": True}})
            else:
                commands.append({
                    "command": "sketch.spline.fit_point",
                    "params": {"points": _points2d(upper)}})
                commands.append({
                    "command": "sketch.spline.fit_point",
                    "params": {"points": _points2d(lower)}})
                commands.append({
                    "command": "sketch.line",
                    "params": {"points": _points2d([upper[-1], lower[0]])}})
            commands.append({"command": "sketch.finish", "params": {}})
        params = {"sections": [{"sketch": label} for label in labels],
                  "body_name": name, "name": "%s loft" % name}
        commands.append({"command": "solid.loft", "params": params})

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


def build_script(bodies, out_step=None, combine=True):
    """Целият команден скрипт за SolidCraft."""
    return {"commands": build_commands(bodies, out_step, combine=combine)}


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
        "  aircraft.sc            дизайнът на AeroForge (скици + loft + join)",
        "  preview.png            как изглежда моделът (iso изглед)",
        "  reference.step/.3mf    габарити: батерия, мотор, ESC, приемник, серво, ЦГ",
        "  sections/              по един SVG профил на всяка секция + manifest.csv",
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
    lines += [
        "",
        "Ред на импорт:",
        "  1. aircraft.step или aircraft.3mf — частите на самолета",
        "  2. reference.step/.3mf — обемите за ориентир (скрий ги след позициониране)",
        "",
        "КАК Е ПОСТРОЕН (както би го направил човек):",
        "  всяка секция е скица на своята равнина, профилът е spline през",
        "  точките, а телата се създават с Loft → Join в тялото:",
        "",
    ]
    for row in (joins or []):
        lines.append("    %-14s → %-10s застъпване %s mm"
                     % (row.get("body", "?"), row.get("into", "?"),
                        _fmt(row.get("embed_mm") or 0)))
    if not joins:
        lines.append("    (без обединяване: телата са самостоятелни)")
    if split:
        lines += [
            "",
            "  Крилото и стабилизаторът са по две половини (разрез в y = 0):",
            "  коренът на всяка е вътре в тялото и се влива в него с един",
            "  чист join. Цяла повърхност, която минава през тялото, дава",
            "  пресечна крива от две дъги и SolidCraft не я смята.",
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
        "  Отвори aircraft.sc в SolidCraft. В дървото има:",
        "    <тяло> loft   — loft-ът (2…50 сечения)",
        "    <тяло> S01…   — скиците, по една на секция",
        "  Цъкни скица (напр. Wing_R S01), хвани точка от spline-а и я премести:",
        "  loft-ът и обединеното тяло се преизграждат. Нови сечения се добавят",
        "  с Loft → Sections. sections/manifest.csv дава за всяка скица",
        "  равнината (origin / x_dir / y_dir) и станцията в mm.",
        "",
        "Ако aircraft.step липсва, скриптът не е изпълнен. Пусни го с:",
        "",
        "  solidcraft-cli run solidcraft_model.json --out aircraft.step --save aircraft.sc",
        "",
        "Тела в модела:",
    ]
    for body in bodies:
        if body["kind"] == "revolve":
            lines.append("  %-14s revolve → join" % body["name"])
        else:
            lines.append("  %-14s loft, %d сечения → join"
                         % (body["name"], len(body.get("sections") or [])))
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
                               "Winglet_R", "Winglet_L")
             if name in names]
    if wings:
        steps.append({"id": "wing", "kind": "group",
                      "label": "Крила (ляво + дясно)",
                      "bodies": wings, "est_s": 70.0})
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


