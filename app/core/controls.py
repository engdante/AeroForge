"""
controls.py — кормилни повърхности на крилото (елерони / елевони).

Един източник за размерите на елероните: изчислението (geometry.ailerons),
3D прегледът (geometry3d) и гладкият CAD модел в SolidCraft (assembly)
четат едни и същи дялове, за да показват и строят едно и също.

Елеронът е задната част на крилото зад линията на пантата:

    хорда на елерона = chord_frac × местната хорда
    по размаха — от start_frac до end_frac от полуразмаха (|y| / (b/2))

При крило без опашка повърхностите са елевони (елерон + кормило за
височина) и по подразбиране започват по-навътре.
"""

import math

from . import aero

DEFAULT_CHORD_FRAC = 0.22      # ако мисията не дава aileron_ratio
CHORD_FRAC_RANGE = (0.10, 0.40)
DEFAULT_SPAN = (0.45, 0.92)    # елерони при самолет с опашка
ELEVON_SPAN = (0.25, 0.92)     # елевони при крило без опашка
MIN_SPAN_FRAC = 0.10           # най-късият елерон (дял от полуразмаха)
HINGE_GAP_MM = 1.0             # процеп между крилото и елерона по пантата
END_GAP_MM = 1.5               # процеп в двата края по размаха
TIP_CLEARANCE_FRAC = 0.02      # елеронът спира преди заобления връх


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def normalize_input(raw):
    """
    Входът от UI → {"chord_frac", "start_frac", "end_frac"} (None = авто).

    UI подава проценти (22 → 0.22); стойности над 1 се приемат за проценти.
    `chord_frac = 0` изключва елероните.
    """
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key in ("chord_frac", "start_frac", "end_frac"):
        value = _num(raw.get(key))
        if value is not None and value > 1.0:
            value = value / 100.0
        out[key] = value
    return out


def resolve(raw, mission, tip_style="square", tip_frac=0.0):
    """
    Окончателните дялове на елероните за дизайна.

    връща {"enabled", "kind", "chord_frac", "start_frac", "end_frac",
           "auto": {...}}
    """
    inp = normalize_input(raw)
    mission = mission or {}
    has_tail = bool(mission.get("has_tail", True))
    auto_chord = float(mission.get("aileron_ratio") or DEFAULT_CHORD_FRAC)
    span0, span1 = DEFAULT_SPAN if has_tail else ELEVON_SPAN
    # при заоблен/извит връх елеронът свършва преди закръглението
    style = aero.tip_style_of(tip_style)
    if style in ("rounded", "upturned", "winglet") and tip_frac:
        span1 = min(span1, 1.0 - float(tip_frac) - TIP_CLEARANCE_FRAC)
    auto = {"chord_frac": auto_chord, "start_frac": span0, "end_frac": span1}

    chord = inp["chord_frac"] if inp["chord_frac"] is not None else auto_chord
    if chord is not None and chord <= 0.0:
        return {"enabled": False, "kind": "aileron" if has_tail else "elevon",
                "chord_frac": 0.0, "start_frac": span0, "end_frac": span1,
                "auto": auto}
    chord = min(CHORD_FRAC_RANGE[1], max(CHORD_FRAC_RANGE[0], chord))
    start = inp["start_frac"] if inp["start_frac"] is not None else span0
    end = inp["end_frac"] if inp["end_frac"] is not None else span1
    start = min(0.90, max(0.05, start))
    end = min(0.98, max(0.15, end))
    if end - start < MIN_SPAN_FRAC:
        end = min(0.98, start + MIN_SPAN_FRAC)
        start = end - MIN_SPAN_FRAC
    return {"enabled": True, "kind": "aileron" if has_tail else "elevon",
            "chord_frac": chord, "start_frac": start, "end_frac": end,
            "auto": auto}


# Типични серва (каталожни стойности при 4.8 V). Размерите са на тялото:
# L — дължина (по нея са ушите), W — дебелина, H — височина (без вала).
SERVO_CLASSES = (
    {"key": "micro9", "label": "9 g микро (SG90 / ES08MA)", "mass_g": 9.0,
     "size_mm": (23.0, 12.2, 22.5), "tabs_mm": 32.2, "torque_kgcm": 1.6},
    {"key": "micro13", "label": "13 g микро, метални зъбни колела (MG90S)",
     "mass_g": 13.4, "size_mm": (22.8, 12.2, 28.5), "tabs_mm": 32.5,
     "torque_kgcm": 1.8},
    {"key": "mini17", "label": "17 g мини (ES3054 / MG92B)", "mass_g": 17.0,
     "size_mm": (28.0, 13.0, 30.0), "tabs_mm": 38.0, "torque_kgcm": 3.0},
    {"key": "std40", "label": "40 g стандартно (MG996R)", "mass_g": 40.0,
     "size_mm": (40.7, 19.7, 42.9), "tabs_mm": 54.0, "torque_kgcm": 9.4},
)
SERVO_SAFETY = 2.5             # запас по момент
SERVO_THROW_DEG = 45.0         # ход на рамото на сервото
SURFACE_THROW_DEG = {"aileron": 25.0, "elevon": 25.0, "elevator": 30.0,
                     "rudder": 30.0, "ruddervator": 30.0}
DIVE_FACTOR = 1.25             # проектна скорост = 1.25 × V_max (пикиране)


def _v_max(res):
    """Максимална хоризонтална скорост: налична мощност ≥ нужна."""
    c = res.get("curves") or {}
    best = None
    for v, avail, need in zip(c.get("v") or [], c.get("p_avail") or [],
                              c.get("p_req") or []):
        if avail is not None and need is not None and avail >= need:
            best = v if best is None else max(best, v)
    if best is None:
        best = 2.0 * float((res.get("aero") or {}).get("v_cruise_ms") or 10.0)
    return float(best)


def hinge_torque_kgcm(chord_mm, length_mm, v_ms, surface_deg,
                      servo_deg=SERVO_THROW_DEG):
    """
    Нужен момент на сервото (kg·cm) — стандартната формула за RC модели:

        T[oz·in] = 8.5e-6 · C² · V² · L · sin(S1) · tan(S1) / tan(S2)

    C, L — хорда и дължина на кормилото в cm, V — скорост в mph,
    S1 — ход на кормилото, S2 — ход на рамото на сервото.
    """
    c_cm = chord_mm / 10.0
    l_cm = length_mm / 10.0
    mph = v_ms * 2.23694
    s1 = math.radians(surface_deg)
    s2 = math.radians(servo_deg)
    oz_in = (8.5e-6 * c_cm * c_cm * mph * mph * l_cm * math.sin(s1)
             * math.tan(s1) / math.tan(s2))
    return oz_in * 0.0720077


def pick_servo(torque_kgcm, safety=SERVO_SAFETY):
    """Най-малкото серво от каталога с поне `safety` × нужния момент."""
    for servo in SERVO_CLASSES:
        if servo["torque_kgcm"] >= safety * torque_kgcm:
            return servo
    return SERVO_CLASSES[-1]


def servo_sizing(res):
    """
    Сервата по повърхности: нужен момент, избрано серво и запас.

    Едно серво на елерон (по едно в крилото); едно за височина (двете
    половини на стабилизатора с обща тяга) и едно за посока.
    """
    from . import presets
    g = res.get("geometry") or {}
    mission = presets.mission((res.get("mission") or {}).get("key") or "trainer")
    v = DIVE_FACTOR * _v_max(res)
    out = {"v_design_ms": v, "safety": SERVO_SAFETY, "surfaces": []}

    def add(key, label, count, chord, length):
        if chord <= 0 or length <= 0:
            return
        torque = hinge_torque_kgcm(chord, length, v, SURFACE_THROW_DEG[key])
        servo = pick_servo(torque)
        out["surfaces"].append({
            "key": key, "label": label, "count": count,
            "chord_mm": chord, "length_mm": length,
            "torque_kgcm": torque, "servo": dict(servo),
            "margin": servo["torque_kgcm"] / torque if torque > 0 else None,
        })

    ail = g.get("ailerons") or {}
    if ail.get("enabled"):
        kind = ail.get("kind", "aileron")
        add(kind, "Елевон" if kind == "elevon" else "Елерон", 2,
            0.5 * (ail["chord_inboard_mm"] + ail["chord_outboard_mm"]),
            ail["span_mm"])
    tail = g.get("tail") or {}
    tc = g.get("tail_controls") or {}
    if mission.get("has_tail", True):
        taper_h, taper_v = 0.6, 0.55
        c_h = float(tail.get("c_h_mm") or 0.0) * (1.0 + taper_h) / 2.0
        c_v = float(tail.get("c_v_mm") or 0.0) * (1.0 + taper_v) / 2.0
        el = tc.get("elevator") or {}
        ru = tc.get("rudder") or {}
        el_frac = (el.get("chord_frac") if el else
                   float(mission.get("elevator_ratio") or 0.0))
        ru_frac = (ru.get("chord_frac") if ru else
                   float(mission.get("rudder_ratio") or 0.0))
        if el.get("kind") == "ruddervator":
            # V-опашка: по едно серво на панел (височина + посока)
            vt = tail.get("v_tail") or {}
            c_p = max(float(tail.get("c_h_mm") or 0.0),
                      float(tail.get("c_v_mm") or 0.0)) * (1.0 + taper_v) / 2.0
            b_p = float(vt.get("b_panel_mm") or tail.get("b_h_mm") or 0.0)
            add("ruddervator", "Руддерватор", 2, (el_frac or 0.0) * c_p, b_p)
        else:
            add("elevator", "Кормило за височина", 1, (el_frac or 0.0) * c_h,
                float(tail.get("b_h_mm") or 0.0))
            add("rudder", "Кормило за посока", 1, (ru_frac or 0.0) * c_v,
                float(tail.get("b_v_mm") or 0.0))
    return out


# ------------------------------------------------------- кормила на опашката
TAIL_CHORD_RANGE = (0.15, 0.55)  # дял от хордата на повърхността
TAIL_HINGE_GAP_MM = 1.0           # процеп по пантата
TAIL_END_GAP_MM = 1.5             # процеп в краищата
TAIL_TIP_MARGIN_FRAC = 0.03       # кормилото спира малко преди върха
TAIL_ROOT_CLEAR_MM = 2.0          # от тялото / от другото кормило


def normalize_tail_input(raw):
    """UI → {"elevator_frac", "rudder_frac"} (проценти или дял; None = авто)."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key in ("elevator_frac", "rudder_frac"):
        value = _num(raw.get(key))
        if value is not None and value > 1.0:
            value = value / 100.0
        out[key] = value
    return out


def resolve_tail(raw, mission, tail_type="conventional"):
    """
    Кормилата на опашката: височина (елеватор) и посока (рудер).

    Хордата по подразбиране е `elevator_ratio` / `rudder_ratio` от мисията;
    0 изключва кормилото. При V-опашка двата панела носят руддерватори
    (височина + посока) с хордата на елеватора; при крило без опашка
    кормила няма (управлението е с елевоните).
    """
    mission = mission or {}
    inp = normalize_tail_input(raw)
    has_tail = bool(mission.get("has_tail", True))
    v_tail = tail_type == "v_tail"

    def one(key, auto):
        value = inp[key] if inp[key] is not None else auto
        enabled = has_tail and value is not None and value > 0.0
        if enabled:
            value = min(TAIL_CHORD_RANGE[1], max(TAIL_CHORD_RANGE[0], value))
        return {"enabled": bool(enabled), "chord_frac": value if enabled else 0.0,
                "auto_frac": auto}

    elevator = one("elevator_frac", float(mission.get("elevator_ratio") or 0.0))
    elevator["kind"] = "ruddervator" if v_tail else "elevator"
    rudder = one("rudder_frac", float(mission.get("rudder_ratio") or 0.0))
    if v_tail:
        rudder["enabled"] = False       # посоката е в руддерваторите
        rudder["chord_frac"] = 0.0
    rudder["kind"] = "rudder"
    common = {"hinge_gap_mm": TAIL_HINGE_GAP_MM, "end_gap_mm": TAIL_END_GAP_MM,
              "tip_margin_frac": TAIL_TIP_MARGIN_FRAC,
              "root_clear_mm": TAIL_ROOT_CLEAR_MM}
    elevator.update(common)
    rudder.update(common)
    return {"elevator": elevator, "rudder": rudder, "tail_type": tail_type}


def geometry(cfg, geom):
    """
    Размерите на елероните за резултата (geometry.ailerons).

    `cfg` е от `resolve`, `geom` — геометрията на крилото (span_mm,
    c_root_mm, taper, tip_style, tip_frac, tip_min_ratio).
    """
    out = dict(cfg or {})
    out.pop("auto", None)
    out["auto"] = dict((cfg or {}).get("auto") or {})
    out["hinge_gap_mm"] = HINGE_GAP_MM
    out["end_gap_mm"] = END_GAP_MM
    semi = float(geom.get("span_mm") or 0.0) / 2.0
    if not out.get("enabled") or semi <= 0:
        out.update({"y_start_mm": 0.0, "y_end_mm": 0.0, "span_mm": 0.0,
                    "chord_inboard_mm": 0.0, "chord_outboard_mm": 0.0,
                    "area_dm2": 0.0, "area_ratio": 0.0})
        return out
    c_root = float(geom.get("c_root_mm") or 0.0)
    taper = float(geom.get("taper") or 1.0)
    style = geom.get("tip_style", "square")
    tip_frac = geom.get("tip_frac")
    tip_min = float(geom.get("tip_min_ratio") or 0.10)

    def chord(f):
        return aero.chord_at(f, c_root, taper, style, tip_frac, tip_min)

    f0, f1 = out["start_frac"], out["end_frac"]
    cf = out["chord_frac"]
    span_one = (f1 - f0) * semi
    # трапец по размаха: площта на един елерон × 2
    area_mm2 = 2.0 * cf * 0.5 * (chord(f0) + chord(f1)) * span_one
    wing_mm2 = float(geom.get("area_m2") or 0.0) * 1e6
    out.update({
        "y_start_mm": f0 * semi,
        "y_end_mm": f1 * semi,
        "span_mm": span_one,
        "chord_inboard_mm": cf * chord(f0),
        "chord_outboard_mm": cf * chord(f1),
        "area_dm2": area_mm2 / 1e4,
        "area_ratio": area_mm2 / wing_mm2 if wing_mm2 > 0 else 0.0,
    })
    return out
