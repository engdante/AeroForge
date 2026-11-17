"""
export_job.py — стъпков експорт към SolidCraft с прогрес за UI.

Защо е стъпков: `solidcraft-cli run` печата резултата само накрая, а
Eel (gevent) не може да обслужи втори RPC, докато един блокира в
`subprocess.run`. Затова всяка стъпка е отделен кратък пуск, а JS ги
извиква една по една и рисува прогрес бар, чеклист и ETA.

Стъпки (виж `solidcraft_export.group_steps`):

    prep     — сечения (SVG + manifest) + 3MF от мрежата + референции
    profiles — само профилите (скици) в aircraft.sc, без loft
    group    — по една група тела в работния дизайн (loft + combine)
    finish   — STEP + 3MF от solid-а, `eval` проверка, PNG превю, README

Задачата живее в паметта (`JOBS`) и е независима от UI: същата машина
ползва и синхронният `solidcraft_export.export()`.
"""

import datetime
import json
import os
import threading
import time
import uuid

from . import assembly
from . import design as design_mod
from . import export_dxf
from . import solidcraft_export as sc

JOBS = {}
_LOCK = threading.Lock()

# Таймаут на една стъпка: един бавен join не бива да блокира експорта.
# Стабилизаторът е най-скъпата стъпка (тънък профил + дълъг корен), затова
# границата е широка; всичко над нея се маркира „пропуснато“.
STEP_TIMEOUT_S = 150
# Крилата имат собствен, по-широк лимит: една стъпка влива **двете**
# полукрила с един combine (виж `solidcraft_export.group_steps`).
WING_TIMEOUT_FACTOR = 1.6
WING_TIMEOUT_S = int(STEP_TIMEOUT_S * WING_TIMEOUT_FACTOR)
# Моделът е асиметричен, ако |min Y| и |max Y| се разминават с повече от
# това (липсва полукрило след таймаут на join-а).
ASYMMETRY_MM = 2.0
ASYMMETRY_SPAN_FRAC = 0.01


def _now():
    return time.time()


def _posix(path):
    return str(path).replace("\\", "/")


def _log(job, text):
    """Добавя ред в лога на задачата (последните 60 реда)."""
    job["log"].append({"t": round(_now() - job["t0"], 1), "text": text})
    if len(job["log"]) > 60:
        del job["log"][:-60]


def _get(job_id):
    with _LOCK:
        return JOBS.get(job_id)


def _timing_text(timing):
    """„3.2 s · boolean 2.8 s“ — за реда в чеклиста."""
    timing = timing or {}
    total = float(timing.get("total_ms") or 0.0) / 1000.0
    boolean = float(timing.get("boolean_ms") or 0.0) / 1000.0
    if total <= 0:
        return None
    if boolean > 0.05:
        return "%.1f s · boolean %.1f s" % (total, boolean)
    return "%.1f s" % total


def _error_text(out):
    """Четимо съобщение от неуспешна стъпка (join refusal идва дълго)."""
    errors = out.get("errors") or []
    if errors:
        text = "; ".join(message for _idx, _cmd, message in errors)
        return text[:300]
    return (out.get("error") or "неуспешна стъпка")[:300]


def _wing_attempts(sink_mm, height):
    """
    Опитите за стъпката с крилата — от най-евтиния към най-сигурния.

    1. както е проектирано;
    2. с по-голямо слягане в тялото (или принудително, ако е 0) — по-дълбок
       корен дава по-стабилна пресечна крива;
    3. крилата остават **отделни тела** (без join) — винаги пълен модел,
       дори когато boolean-ът не минава.
    """
    attempts = [{}]
    sink = float(sink_mm or 0.0)
    if sink:
        attempts.append({"sink_mm": sink * 1.6})
    elif height > 0:
        attempts.append({"sink_mm": -assembly.ROOT_SINK_FRAC * height})
    attempts.append({"unjoin": True})
    return attempts


def _attempts(step, sink_mm, height):
    """Стъпаловидните опити за една група тела (виж `_do_group`)."""
    if str(step.get("id") or "").startswith("wing"):
        return _wing_attempts(sink_mm, height)
    attempts = [{}]
    if step.get("id") == "tail" and height > 0:
        attempts.append({"tail_lift_mm": 0.25 * height})
        attempts.append({"tail_lift_mm": 0.10 * height})
    return attempts


def _step_timeout(job, step):
    """Таймаут на стъпка: крилата получават 1.6× (двете полукрила наведнъж)."""
    base = float(job.get("timeout") or STEP_TIMEOUT_S)
    if str(step.get("id") or "").startswith("wing"):
        return base * WING_TIMEOUT_FACTOR
    return base


def _unjoin(bodies, names):
    """Копие на телата без `into` за изброените имена (без join)."""
    wanted = set(names or ())
    out = []
    for body in bodies:
        if body.get("name") in wanted and body.get("into"):
            body = {key: value for key, value in body.items()
                    if key not in ("into", "embed_mm", "after")}
        out.append(body)
    return out


def max_asymmetry_mm(eval_data):
    """Разликата между общия ляв/десен обхват на всички тела (mm)."""
    min_y = None
    max_y = None
    for body in (eval_data or {}).get("bodies") or []:
        bbox = body.get("bbox") or {}
        low = bbox.get("min")
        high = bbox.get("max")
        if not low or not high:
            continue
        try:
            body_min = float(low[1])
            body_max = float(high[1])
        except (TypeError, ValueError, IndexError):
            continue
        min_y = body_min if min_y is None else min(min_y, body_min)
        max_y = body_max if max_y is None else max(max_y, body_max)
    if min_y is None or max_y is None:
        return 0.0
    return abs(abs(min_y) - abs(max_y))


def _check_symmetry(job, step):
    """
    Warning, ако моделът е асиметричен по размаха.

    Сравнява общия bbox на модела, а не отделните тела: отделните половини
    на стабилизатора са асиметрични поотделно, но симетрични заедно.
    """
    geometry = job["res"].get("geometry") or {}
    span = float(geometry.get("span_mm") or 0.0)
    asym = max_asymmetry_mm(job.get("eval"))
    limit = max(ASYMMETRY_MM, ASYMMETRY_SPAN_FRAC * span)
    if span <= 0 or asym <= limit:
        return 0.0
    message = ("моделът е асиметричен по размаха: %.1f mm разлика "
               "(липсва половина?)" % asym)
    job["warnings"].append(message)
    detail = step.get("detail") or ""
    step["detail"] = (detail + " · " + message).strip(" ·")
    _log(job, message)
    return asym


def _eta(job):
    """Оставащи секунди: оценките, калибрирани по вече миналите стъпки."""
    done = [s for s in job["steps"] if s["state"] in ("done", "skipped", "error")]
    pending = [s for s in job["steps"] if s["state"] == "pending"]
    est_done = sum(float(s.get("est_s") or 0.0) for s in done)
    real_done = sum(float(s.get("ms") or 0) / 1000.0 for s in done)
    factor = 1.0
    if est_done > 0.5 and real_done > 0:
        factor = min(4.0, max(0.4, real_done / est_done))
    return round(sum(float(s.get("est_s") or 0.0) for s in pending) * factor)


def state(job):
    """
    Състоянието на задачата като JSON за UI.

    Връща и старите ключове на експорта (`ok`, `folder`, `step`, `design`,
    `bodies`, `joins`, `files`…), за да работи и синхронният път.
    """
    if not job:
        return {"ok": False, "error": "няма такава задача"}
    if job.get("status") == "ready" and job["index"] == 0:
        job["status"] = "running"
    steps = [{"id": s["id"], "label": s["label"], "state": s["state"],
              "ms": s["ms"], "detail": s.get("detail"),
              "error": s.get("error"), "est_s": s.get("est_s")}
             for s in job["steps"]]
    done = [s for s in steps if s["state"] in ("done", "skipped", "error")]
    warnings = list(job.get("warnings") or [])
    return {
        "ok": True,
        "job": job["id"],
        "status": job.get("status"),
        "folder": job["folder"],
        "design_name": job["name"],
        "index": job["index"],
        "progress": (100.0 * len(done) / len(steps)) if steps else 0.0,
        "elapsed_s": round(_now() - job["t0"], 1),
        "eta_s": _eta(job),
        "steps": steps,
        "log": list(job["log"])[-14:],
        "step": job.get("step_path") if os.path.exists(job.get("step_path") or "")
                else None,
        "design": (job.get("design_path")
                   if os.path.exists(job.get("design_path") or "") else None),
        "three_mf": job.get("three_mf_info"),
        "preview": job.get("preview"),
        "reference": (job.get("files") or {}).get("reference_step", {}).get("path"),
        "sections": job.get("section_count") or 0,
        "bodies": [{"name": b["name"], "kind": b["kind"],
                    "sections": len(b.get("sections") or [])}
                   for b in job["bodies"]],
        "joins": [{"body": b["name"], "into": b.get("into"),
                   "embed_mm": b.get("embed_mm")}
                  for b in job["bodies"] if b.get("into")],
        "sink_mm": job.get("sink_mm"),
        "eval": job.get("eval"),
        "files": job.get("files") or {},
        "script": job.get("script_path"),
        "cli": job.get("cli"),
        "warning": "; ".join(warnings)[:600] if warnings else None,
        "error": job.get("error"),
    }


def start(res, base_dir, quality=None, detail=None, slugify=None, options=None):
    """
    Създава задача за експорт: тела, стъпки, папка. Не пипа SolidCraft.

    `options`: {"run": bool, "split": bool, "exact_tail": bool,
                "quality_3mf": "standard|fine|finest", "timeout": s,
                "save_design": bool,
                "detailed": bool — детайлният модел aircraft_detailed.sc
                (по подразбиране True)}
    """
    if not res or not res.get("ok"):
        return {"ok": False, "error": "няма изчислен дизайн"}
    options = dict(options or {})
    detail = dict(detail or sc.DEFAULT_DETAIL)
    name = (res.get("inputs") or {}).get("name") or "design"
    slug = slugify(name) if slugify else "design"
    folder = os.path.join(base_dir, slug)
    sections_dir = os.path.join(folder, "sections")
    steps_dir = os.path.join(folder, "steps")
    os.makedirs(sections_dir, exist_ok=True)
    os.makedirs(steps_dir, exist_ok=True)

    split = bool(options.get("split", True))
    exact_tail = bool(options.get("exact_tail", False))
    join_tail = bool(options.get("join_tail", False))
    layout = res.get("layout") or {}
    wing_root_gap = max(0.0, min(40.0, float(
        layout.get("wing_root_gap_mm", layout.get("root_gap_mm", 10.0)) or 0.0)))
    tail_root_gap = max(0.0, min(40.0, float(
        layout.get("tail_root_gap_mm", layout.get("root_gap_mm", 10.0)) or 0.0)))
    sink = assembly.wing_root_sink(res)
    bodies = assembly.loft_bodies(res, quality, detail, split=split,
                                  sink_mm=sink, exact_tail=exact_tail,
                                  nose_one_piece=bool(
                                      options.get("nose_one_piece", False)),
                                  join_tail=join_tail,
                                  wing_root_gap_mm=wing_root_gap,
                                  tail_root_gap_mm=tail_root_gap)
    if not bodies:
        return {"ok": False, "error": "няма геометрия за гладък модел"}

    cli = sc.find_cli() if options.get("run", True) else None
    steps = sc.group_steps(bodies)
    if options.get("detailed", True):
        # детайлният модел е отделен дизайн (aircraft_detailed.sc): стъпка
        # преди финала, за да влезе в README/манифеста; неуспехът ѝ не
        # засяга основния модел
        steps.insert(len(steps) - 1, {
            "id": "detailed", "kind": "detailed",
            "label": "Детайлен модел (aircraft_detailed.sc)",
            "bodies": [], "est_s": 90.0})
    for step in steps:
        step.update({"state": "pending", "ms": None, "error": None,
                     "detail": None})

    job = {
        "id": uuid.uuid4().hex[:10],
        "res": res,
        "name": name,
        "folder": folder,
        "sections_dir": sections_dir,
        "steps_dir": steps_dir,
        "detail": detail,
        "quality": quality,
        "options": options,
        "bodies": bodies,
        "steps": steps,
        "index": 0,
        "status": "ready",
        "t0": _now(),
        "log": [],
        "warnings": [],
        "files": {},
        "cli": cli,
        "signal_cli": bool(options.get("run", True)),
        "split": split,
        "sink_mm": sink,
        "wing_root_gap_mm": wing_root_gap,
        "tail_root_gap_mm": tail_root_gap,
        "timeout": float(options.get("timeout") or STEP_TIMEOUT_S),
        "save_design": bool(options.get("save_design", True)),
        "quality_3mf": options.get("quality_3mf") or "fine",
        "design_ok": False,
        "section_count": 0,
        "three_mf_info": None,
        "preview": None,
        "eval": None,
        "error": None,
        "script_path": os.path.join(folder, "solidcraft_model.json"),
        "design_path": os.path.join(folder, "aircraft.sc"),
        # работен дизайн на стъпките: същите скици + loft + join → STEP
        "loft_design_path": os.path.join(steps_dir, "loft.sc"),
        "step_path": os.path.join(folder, "aircraft.step"),
        "three_mf": os.path.join(folder, "aircraft.3mf"),
        "preview_path": os.path.join(folder, "preview.png"),
        "detailed_design_path": os.path.join(folder, "aircraft_detailed.sc"),
        "detailed_step_path": os.path.join(folder, "aircraft_detailed.step"),
        "detailed_preview_path": os.path.join(folder, "preview_detailed.png"),
        "readme_path": os.path.join(folder, "README.txt"),
        "manifest_path": os.path.join(folder, "model_manifest.json"),
        "sections_manifest": os.path.join(sections_dir, "manifest.csv"),
    }
    with _LOCK:
        JOBS[job["id"]] = job
    _log(job, "%d тела, %d стъпки, папка %s"
         % (len(bodies), len(steps), os.path.basename(folder)))
    if job["signal_cli"] and not cli:
        _log(job, "solidcraft-cli не е намерен — ще има само мрежа и сечения")
    return state(job)



def _do_prep(job, step):
    """Стъпка 1: SVG сечения, manifest, пълният скрипт, 3MF от мрежата."""
    bodies = job["bodies"]
    rows, count = sc.write_sections(job["sections_dir"], bodies)
    export_dxf.write_csv(job["sections_manifest"], rows, sc.MANIFEST_HEADER)
    job["section_count"] = count
    job["files"]["sections_manifest"] = {"path": job["sections_manifest"],
                                         "sections": count}
    with open(job["script_path"], "w", encoding="utf-8") as f:
        json.dump(sc.build_script(bodies, job["step_path"]), f,
                  ensure_ascii=False, indent=1)
    job["files"]["solidcraft_script"] = {
        "path": job["script_path"],
        "bytes": os.path.getsize(job["script_path"])}
    info = sc.mesh_3mf(job["res"], job["three_mf"], job["quality"])
    job["three_mf_info"] = dict(info, path=job["three_mf"], quality="mesh")
    job["files"]["aircraft_3mf"] = dict(info, path=job["three_mf"])
    job["files"].update(sc.reference_files(job["res"], job["folder"]))
    step["state"] = "done"
    step["detail"] = "%d сечения · 3MF: %d обекта" % (
        count, info.get("objects") or 0)
    _log(job, "сечения: %d · 3MF (мрежа): %d обекта"
         % (count, info.get("objects") or 0))


def _do_profiles(job, step):
    """
    Стъпката след prep: `aircraft.sc` = само профилите (скици), без loft.

    Свързването (loft + join) не е тук — то е в работния дизайн на
    стъпките (`steps/loft.sc`), от който идва `aircraft.step`.
    """
    script_path = os.path.join(job["steps_dir"], "profiles.json")
    script = sc.profiles_script(job["bodies"])
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=1)
    sketches = sum(1 for command in script["commands"]
                   if command["command"] == "sketch.create")
    bodies = sc.profile_bodies(job["bodies"])
    step["detail"] = "%d тела · %d скици" % (len(bodies), sketches)
    job["files"]["profiles_script"] = {
        "path": script_path, "bytes": os.path.getsize(script_path)}
    if not job["cli"]:
        step["state"] = "skipped"
        step["detail"] = (step["detail"] or "") + " · няма solidcraft-cli"
        return
    if not job["save_design"]:
        step["state"] = "skipped"
        step["detail"] = (step["detail"] or "") + " · дизайнът не се записва"
        return
    out = sc.run_group(script_path, job["design_path"], first=True,
                       timeout=_step_timeout(job, step), cli=job["cli"],
                       save=True)
    step["ms"] = out.get("ms")
    if out.get("ok") and os.path.exists(job["design_path"]):
        step["state"] = "done"
        step["detail"] = _timing_text(out.get("timing")) or step["detail"]
        _log(job, "профилите са в aircraft.sc: %d скици за %.1f s"
             % (sketches, (out.get("ms") or 0) / 1000.0))
        return
    message = _error_text(out)
    step["state"] = "error"
    step["error"] = message
    job["warnings"].append("%s: %s" % (step["label"], message))
    _log(job, "профилите не са записани: %s" % message[:120])


def _do_group(job, step):
    """Стъпка 2..n: една група тела през SolidCraft (loft + combine)."""
    if not job["cli"]:
        step["state"] = "skipped"
        step["detail"] = "няма solidcraft-cli"
        return
    if job.get("design_broken"):
        step["state"] = "skipped"
        step["detail"] = "тялото не е построено — моделът ще е от отделни тела"
        return
    script_path = os.path.join(job["steps_dir"], "%s.json" % step["id"])
    # Крилото и стабилизаторът са най-чувствителните стъпки: когато
    # повърхността минава близо до стената на тялото (високо/ниско крило,
    # тънка опашка на линията на най-голямата ширина), boolean-ът може да
    # „виси“. Затова при неуспех се пробва с по-голямо застъпване/повдигане.
    height = float(((job["res"].get("geometry") or {}).get("fuselage") or {})
                   .get("height_mm") or 0.0)
    attempts = _attempts(step, job.get("sink_mm"), height)
    last = {}
    for attempt, overrides in enumerate(attempts):
        bodies = job["bodies"]
        if overrides:
            layout = job["res"].get("layout") or {}
            wing_root_gap = max(0.0, min(40.0, float(
                layout.get("wing_root_gap_mm", layout.get("root_gap_mm", 10.0)) or 0.0)))
            tail_root_gap = max(0.0, min(40.0, float(
                layout.get("tail_root_gap_mm", layout.get("root_gap_mm", 10.0)) or 0.0)))
            bodies = assembly.loft_bodies(
                job["res"], job["quality"], job["detail"],
                split=job.get("split", True),
                sink_mm=overrides.get("sink_mm", job.get("sink_mm")),
                exact_tail=job.get("options", {}).get("exact_tail", False),
                nose_one_piece=job.get("options", {}).get("nose_one_piece",
                                                          False),
                join_tail=job.get("options", {}).get("join_tail", False),
                tail_lift_mm=overrides.get("tail_lift_mm"),
                wing_root_gap_mm=wing_root_gap,
                tail_root_gap_mm=tail_root_gap)
            if overrides.get("unjoin"):
                # последен опит: крилата остават отделни тела, за да има
                # пълен (макар и необединен) модел вместо половин крило
                bodies = _unjoin(bodies, step["bodies"])
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(sc.group_script(bodies, step["bodies"]), f,
                      ensure_ascii=False, indent=1)
        first = not job.get("design_ok")
        out = sc.run_group(script_path, job["loft_design_path"], first=first,
                           timeout=_step_timeout(job, step), cli=job["cli"],
                           save=job["save_design"])
        last = out
        step["ms"] = out.get("ms") or step.get("ms")
        step["detail"] = _timing_text(out.get("timing")) or step.get("detail")
        if out.get("ok"):
            if overrides:
                job["bodies"] = bodies
                if "sink_mm" in overrides:
                    job["sink_mm"] = overrides["sink_mm"]
                step["detail"] = (step["detail"] or "") + \
                    " · опит %d" % (attempt + 1)
                _log(job, "%s: мина от опит %d (%s)"
                     % (step["label"], attempt + 1, overrides))
            job["design_ok"] = os.path.exists(job["loft_design_path"])
            step["state"] = "done"
            _log(job, "%s: готово за %.1f s"
                 % (step["label"], (out.get("ms") or 0) / 1000.0))
            return
        if attempt + 1 < len(attempts):
            _log(job, "%s: опит %d неуспешен (%s) — пробвам с по-голямо "
                      "застъпване" % (step["label"], attempt + 1,
                                      _error_text(out)[:80]))
    out = last
    message = _error_text(out)
    step["error"] = message
    job["warnings"].append("%s: %s" % (step["label"], message))
    step["state"] = "skipped" if out.get("timed_out") else "error"
    # Ако основата (тялото) не е построена, следващите групи няма в какво
    # да се вливат. Махаме частичния дизайн и отиваме на отделни тела —
    # експортът пак дава валиден файл.
    if step["id"] == "body" or not job.get("design_ok"):
        job["design_broken"] = True
        job["design_ok"] = False
        path = job.get("loft_design_path")
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        _log(job, "%s: неуспешно — продължавам с отделни тела" % step["label"])
    else:
        _log(job, "%s: %s" % (step["label"], message))



def _do_finish(job, step):
    """Последна стъпка: STEP + 3MF от solid-а, eval, превю, README/manifest."""
    cli = job["cli"]
    if not cli:
        step["state"] = "skipped"
        step["detail"] = "няма solidcraft-cli — само мрежа"
        _write_outputs(job, source="mesh")
        return
    commands = [
        {"command": "file.export", "params": {"path": _posix(job["step_path"]),
                                              "format": "step"}},
        {"command": "file.export", "params": {"path": _posix(job["three_mf"]),
                                              "format": "3mf",
                                              "quality": job["quality_3mf"]}},
    ]
    script_path = os.path.join(job["steps_dir"], "finish.json")
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump({"commands": commands}, f, ensure_ascii=False, indent=1)
    if os.path.exists(job["loft_design_path"]):
        out = sc.run_group(script_path, job["loft_design_path"], first=False,
                           timeout=max(job["timeout"], 180), cli=cli,
                           save=False)
    else:
        # нищо не е построено: пълен скрипт без joins, за да има файл
        layout = job["res"].get("layout") or {}
        plain_wing_gap = max(0.0, min(40.0, float(
            layout.get("wing_root_gap_mm", layout.get("root_gap_mm", 10.0)) or 0.0)))
        plain_tail_gap = max(0.0, min(40.0, float(
            layout.get("tail_root_gap_mm", layout.get("root_gap_mm", 10.0)) or 0.0)))
        plain = assembly.loft_bodies(job["res"], job["quality"], job["detail"],
                                     joins=False,
                                     wing_root_gap_mm=plain_wing_gap,
                                     tail_root_gap_mm=plain_tail_gap)
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(sc.build_script(plain, job["step_path"]), f,
                      ensure_ascii=False, indent=1)
        out = sc.run_group(script_path, None, first=True,
                           timeout=max(job["timeout"], 240), cli=cli,
                           save=False)
        job["warnings"].append("SolidCraft не построи нищо — моделът е с "
                              "отделни тела")
    step["ms"] = out.get("ms") or step.get("ms")
    step["detail"] = _timing_text(out.get("timing")) or step.get("detail")
    has_step = os.path.exists(job["step_path"])
    has_3mf = os.path.exists(job["three_mf"])
    source = "solidcraft" if has_3mf and out.get("ok") else "mesh"
    if has_step:
        job["eval"] = sc.evaluate(job["step_path"], cli=cli)
        bodies = (job.get("eval") or {}).get("body_count") or 0
        if bodies:
            bad = [b for b in (job["eval"] or {}).get("bodies", [])
                   if not b.get("closed")]
            if bad:
                job["warnings"].append("%d тела не са затворени"
                                       % len(bad))
        _check_symmetry(job, step)
        job["preview"] = sc.snapshot(job["step_path"], job["preview_path"],
                                     cli=cli)
        if not out.get("ok") and out.get("errors"):
            step["state"] = "error"
            step["error"] = _error_text(out)
            job["warnings"].append(step["error"])
        else:
            step["state"] = "done"
        # manifest/README се пишат след всички проверки, за да не остане
        # стъпката „running“ в готовия файл и warning-ите да влязат в него
        _write_outputs(job, source=source)
        _log(job, "STEP: %.1f MB, тела: %s%s"
             % (os.path.getsize(job["step_path"]) / 1e6, bodies,
                " · 3MF: %.1f MB" % (os.path.getsize(job["three_mf"]) / 1e6)
                if has_3mf else ""))
        return
    step["state"] = "error"
    step["error"] = _error_text(out)
    job["warnings"].append(step["error"])
    _write_outputs(job, source=source)
    _log(job, "STEP не е записан: %s" % step["error"])



DETAILED_TIMEOUT_S = 420.0
DETAILED_MAX_RETRIES = 14      # резервни опити (сливане, отвор, кормила)


def _do_detailed(job, step):
    """
    Детайлният модел: кухо тяло с капак, крило със седло/джойнер/щифт/винт,
    гнезда за серво, елерони с шарнирна панта — отделен `aircraft_detailed.sc`
    (+ `.step`). Скриптът е в `steps/detailed.json` и може да се пусне на ръка.
    """
    from . import detailed_model
    script = detailed_model.build_script(job["res"], job["quality"],
                                         job["detail"],
                                         out_step=job["detailed_step_path"])
    job["detailed_notes"] = list(script["notes"])
    script_path = os.path.join(job["steps_dir"], "detailed.json")
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump({"commands": script["commands"]}, f, ensure_ascii=False,
                  indent=1)
    job["files"]["detailed_script"] = {"path": script_path,
                                       "bytes": os.path.getsize(script_path)}
    step["detail"] = "%d команди" % len(script["commands"])
    if not script["commands"]:
        step["state"] = "skipped"
        step["detail"] = "; ".join(script["notes"]) or "няма геометрия"
        return
    if not job["cli"]:
        step["state"] = "skipped"
        step["detail"] += " · няма solidcraft-cli (скриптът е записан)"
        return
    def run(current):
        for path in (job["detailed_step_path"], job["detailed_design_path"]):
            if os.path.exists(path):
                os.remove(path)
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump({"commands": current["commands"]}, f,
                      ensure_ascii=False, indent=1)
        return sc.run_group(script_path, job["detailed_design_path"],
                            first=True,
                            timeout=max(_step_timeout(job, step),
                                        DETAILED_TIMEOUT_S),
                            cli=job["cli"], save=True)

    out = run(script)
    total_ms = out.get("ms") or 0
    # SolidCraft понякога отказва сливането на повърхност с тялото („Bad
    # CurveCusp“ — почти допирателна пресечна крива): резервните варианти
    # за точно тази повърхност (detailed_model.FALLBACKS), накрая — отделно тяло
    variants, attempts = {}, {}
    for _retry in range(DETAILED_MAX_RETRIES):
        feature = None if out.get("ok") else detailed_model.failed_feature(
            out.get("errors"), script["commands"])
        if not feature:
            break
        new = detailed_model.next_variants(variants, feature,
                                           attempts.get(feature, 0))
        if new is None:
            break
        attempts[feature] = attempts.get(feature, 0) + 1
        variants = new
        _log(job, "„%s“ е отказано от SolidCraft — повтарям (%s)"
             % (feature, variants))
        script = detailed_model.build_script(
            job["res"], job["quality"], job["detail"],
            out_step=job["detailed_step_path"], variants=variants)
        job["detailed_notes"] = list(script["notes"])
        out = run(script)
        total_ms += out.get("ms") or 0
    out["ms"] = total_ms
    step["ms"] = out.get("ms")
    if out.get("ok") and os.path.exists(job["detailed_step_path"]):
        ev = sc.evaluate(job["detailed_step_path"], cli=job["cli"]) or {}
        job["detailed_eval"] = ev
        sc.snapshot(job["detailed_step_path"], job["detailed_preview_path"],
                    cli=job["cli"])
        step["state"] = "done"
        step["detail"] = "%s тела · %s" % (
            ev.get("body_count") or "?",
            _timing_text(out.get("timing")) or "%.0f s" % ((out.get("ms") or 0) / 1000.0))
        _log(job, "детайлният модел е готов: %s тела" % ev.get("body_count"))
        return
    message = _error_text(out) if out.get("errors") or out.get("error") \
        else "SolidCraft не записа aircraft_detailed.step"
    step["state"] = "error"
    step["error"] = message
    job["warnings"].append("%s: %s" % (step["label"], message))
    _log(job, "детайлният модел не е построен: %s" % message[:160])


def _write_outputs(job, source="mesh"):
    """README + model_manifest.json (файлове, стъпки, времена, проверка)."""
    files = job["files"]
    if os.path.exists(job["step_path"]):
        files["aircraft_step"] = {"path": job["step_path"],
                                  "bytes": os.path.getsize(job["step_path"])}
    if os.path.exists(job["design_path"]):
        files["aircraft_design"] = {
            "path": job["design_path"],
            "bytes": os.path.getsize(job["design_path"]),
            "contents": "profiles"}
    if os.path.exists(job["loft_design_path"]):
        files["loft_design"] = {
            "path": job["loft_design_path"],
            "bytes": os.path.getsize(job["loft_design_path"]),
            "contents": "loft+join"}
    if os.path.exists(job["three_mf"]):
        info = job.get("three_mf_info") or {}
        if source == "solidcraft":
            files["aircraft_3mf"] = {"path": job["three_mf"],
                                     "bytes": os.path.getsize(job["three_mf"]),
                                     "source": "solidcraft",
                                     "quality": job["quality_3mf"]}
            job["three_mf_info"] = dict(files["aircraft_3mf"])
        else:
            files["aircraft_3mf"] = dict(info, path=job["three_mf"],
                                         source="mesh")
    if job.get("preview"):
        files["preview"] = {"path": job["preview"],
                            "bytes": os.path.getsize(job["preview"])}
    for key, path, extra in (
            ("detailed_design", job.get("detailed_design_path"),
             {"contents": "detailed"}),
            ("detailed_step", job.get("detailed_step_path"), {}),
            ("detailed_preview", job.get("detailed_preview_path"), {})):
        if path and os.path.exists(path):
            files[key] = dict(extra, path=path, bytes=os.path.getsize(path))
    info = {
        "detailed_notes": job.get("detailed_notes"),
        "detailed_built": bool(job.get("detailed_step_path")
                               and os.path.exists(job["detailed_step_path"])),
        "three_mf": job.get("three_mf_info") or {},
        "wing_offset_desc": (job["res"].get("layout") or {}).get(
            "wing_offset_desc"),
    }
    with open(job["readme_path"], "w", encoding="utf-8-sig") as f:
        f.write(sc.readme_text(job["name"], job["bodies"],
                               [{"body": b["name"], "into": b.get("into"),
                                 "embed_mm": b.get("embed_mm")}
                                for b in job["bodies"] if b.get("into")],
                               job["sink_mm"], job["split"], info))
    files["readme"] = {"path": job["readme_path"]}
    layer = (job["res"].get("layout") or {})
    manifest = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "design": job["name"],
        "version": design_mod.VERSION,
        "units": "mm",
        "wing": {
            "offset_mm": layer.get("wing_offset_mm"),
            "percent": layer.get("wing_offset_percent"),
            "z_mm": layer.get("wing_z_mm"),
            "class": layer.get("wing_position"),
            "description": layer.get("wing_offset_desc"),
            "root_sink_mm": job["sink_mm"],
            "root_gap_mm": max(0.0, min(40.0, float(
                layer.get("wing_root_gap_mm",
                          layer.get("root_gap_mm", 10.0)) or 0.0))),
        },
        "tail": {
            "type": layer.get("tail_type"),
            "planform": layer.get("tail_planform"),
            "tip_style": layer.get("tail_tip_style"),
            "root_gap_mm": max(0.0, min(40.0, float(
                layer.get("tail_root_gap_mm",
                          layer.get("root_gap_mm", 10.0)) or 0.0))),
        },
        "bodies": [{"name": b["name"], "kind": b["kind"],
                    "sections": len(b.get("sections") or []),
                    "into": b.get("into"),
                    "embed_mm": b.get("embed_mm")} for b in job["bodies"]],
        "steps": [{"id": s["id"], "label": s["label"], "state": s["state"],
                   "ms": s["ms"], "detail": s.get("detail"),
                   "error": s.get("error")} for s in job["steps"]],
        "eval": job.get("eval"),
        "detailed": {"notes": job.get("detailed_notes") or [],
                     "eval": job.get("detailed_eval")},
        "warnings": job.get("warnings") or [],
        "files": files,
    }
    with open(job["manifest_path"], "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    files["manifest"] = {"path": job["manifest_path"]}
    # SolidCraft пази резервно копие при --save; не е нужно в папката
    for design in (job["design_path"], job["loft_design_path"],
                   job.get("detailed_design_path") or ""):
        backup = design + ".bak"
        if os.path.exists(backup):
            try:
                os.remove(backup)
            except OSError:
                pass



def run_step(job_id, index=None):
    """
    Изпълнява една стъпка от задачата и връща новото състояние.

    UI вика това в цикъл: така прогресът е реален (всяка стъпка е отделен
    пуск), а евентуален таймаут не блокира целия експорт наведнъж.
    """
    job = _get(job_id)
    if not job:
        return {"ok": False, "error": "няма такава задача"}
    if job.get("status") == "cancelled":
        return state(job)
    idx = job["index"] if index is None else int(index)
    if idx >= len(job["steps"]):
        job["status"] = "done"
        return state(job)
    step = job["steps"][idx]
    if step["state"] in ("done", "skipped", "error"):
        job["index"] = max(job["index"], idx + 1)
        return state(job)
    step["state"] = "running"
    job["status"] = "running"
    started = _now()
    try:
        if step["kind"] == "prep":
            _do_prep(job, step)
        elif step["kind"] == "profiles":
            _do_profiles(job, step)
        elif step["kind"] == "group":
            _do_group(job, step)
        elif step["kind"] == "detailed":
            _do_detailed(job, step)
        else:
            _do_finish(job, step)
    except Exception as exc:  # noqa: BLE001 — експортът не бива да гърми
        step["state"] = "error"
        step["error"] = "%s: %s" % (type(exc).__name__, exc)
        job["warnings"].append("%s: %s" % (step["label"], step["error"]))
        _log(job, "грешка в „%s“: %s" % (step["label"], step["error"]))
    step["ms"] = int((_now() - started) * 1000) if step.get("ms") is None \
        else step["ms"]
    job["index"] = max(job["index"], idx + 1)
    if job["index"] >= len(job["steps"]):
        job["status"] = "done"
        job["finished"] = _now()
        _log(job, "готово за %.1f s" % (_now() - job["t0"]))
    return state(job)


def cancel(job_id):
    """
    Отказва задачата. Текущата стъпка довършва (CLI не може да се прекъсне
    от друг RPC), но следващите не се изпълняват.
    """
    job = _get(job_id)
    if not job:
        return {"ok": False, "error": "няма такава задача"}
    if job.get("status") not in ("done", "error"):
        job["status"] = "cancelled"
        _log(job, "отказано от потребителя")
    return state(job)


def current(job_id):
    """Състоянието на задачата (за възстановяване на панела)."""
    return state(_get(job_id))


def run_all(res, base_dir, quality=None, detail=None, slugify=None,
            run=True, timeout=STEP_TIMEOUT_S, save_design=True,
            options=None):
    """
    Синхронен експорт — същите стъпки, но без междинен прогрес.

    Ползва се от `solidcraft_export.export()` (тестове, скриптове), за да
    има само един път за построяване на модела.
    """
    opts = dict(options or {})
    opts.setdefault("run", run)
    opts.setdefault("timeout", timeout)
    opts.setdefault("save_design", save_design)
    started = start(res, base_dir, quality=quality, detail=detail,
                    slugify=slugify, options=opts)
    if not started.get("ok"):
        return started
    job_id = started["job"]
    total = len(JOBS[job_id]["steps"])
    for index in range(total):
        current_state = run_step(job_id, index)
        if current_state.get("status") == "cancelled":
            break
    return state(JOBS[job_id])

