"""
motor.py — мотор и витло като геометрия (3D преглед и детайлен модел).

Изчислението (propulsion) дава мощност, kV и витло D×P; тук от тях идват
физическите размери:

  * мотор — стандартен безчетков outrunner (2204 … 5055): най-малкият,
    който носи мощността с резерв и върти витлото (по-голямо витло иска
    по-голям статор — въртящ момент);
  * витло — две лопати с реалния диаметър; ъгълът на всяка станция е от
    стъпката (β = atan(P / 2πr)), хордата — типична за APC/електрически;
  * разположение — теглещо: витлото в спинера, моторът зад него, стойка
    до преградата; бутащо: зад края на тялото; два мотора: пред предния
    ръб на крилото на 35 % от полуразмаха.

Координати (mm): X назад от носа, Y надясно, Z нагоре (Z = 0 коремът).
"""

import math

INCH_MM = 25.4

# key, въртящ момент (N·m, ≈ 9.55/kV · I_max — почти не зависи от kV),
# диаметър и дължина на „камбаната“, вал, монтажни отвори (две диагонали
# на кръста, mm), маса, макс. мощност
MOTOR_CLASSES = (
    {"key": "2204", "q_max_nm": 0.045, "can_d": 27.5, "can_l": 18.0, "shaft_d": 3.0,
     "mount": (16.0, 19.0), "mass_g": 26.0, "p_max_w": 120.0},
    {"key": "2208", "q_max_nm": 0.1, "can_d": 27.5, "can_l": 22.0, "shaft_d": 3.0,
     "mount": (16.0, 19.0), "mass_g": 42.0, "p_max_w": 170.0},
    {"key": "2212", "q_max_nm": 0.19, "can_d": 27.5, "can_l": 26.0, "shaft_d": 3.17,
     "mount": (16.0, 19.0), "mass_g": 55.0, "p_max_w": 230.0},
    {"key": "2216", "q_max_nm": 0.27, "can_d": 27.5, "can_l": 30.0, "shaft_d": 3.17,
     "mount": (16.0, 19.0), "mass_g": 70.0, "p_max_w": 300.0},
    {"key": "2826", "q_max_nm": 0.34, "can_d": 35.0, "can_l": 30.0, "shaft_d": 5.0,
     "mount": (19.0, 25.0), "mass_g": 100.0, "p_max_w": 420.0},
    {"key": "3536", "q_max_nm": 0.45, "can_d": 35.0, "can_l": 36.0, "shaft_d": 5.0,
     "mount": (19.0, 25.0), "mass_g": 125.0, "p_max_w": 550.0},
    {"key": "4250", "q_max_nm": 1.1, "can_d": 42.0, "can_l": 50.0, "shaft_d": 6.0,
     "mount": (25.0, 30.0), "mass_g": 210.0, "p_max_w": 900.0},
    {"key": "5055", "q_max_nm": 1.8, "can_d": 50.0, "can_l": 55.0, "shaft_d": 6.0,
     "mount": (30.0, 38.0), "mass_g": 330.0, "p_max_w": 1400.0},
)
POWER_HEADROOM = 1.25     # моторът носи 125 % от входната мощност
TORQUE_HEADROOM = 1.10    # ... и 110 % от момента на витлото
BAY_CLEAR_MM = 1.5        # луфт около въртящата се камбана
COWL_WALL_MM = 1.2        # стена на каулинга около мотора
SPINNER_GAP_MM = 2.0      # между гърба на спинера и камбаната
MOUNT_T_MM = 3.0          # кръстата стойка на мотора
SHAFT_OUT_MM = 14.0       # вал пред камбаната (адаптер на витлото)
FIREWALL_FRAC = 0.06      # преградата по подразбиране (дял от дължината)

# лопата: (r/R, хорда/R, дебелина/хорда) — типично електрическо витло
# първата станция (r/R = 0) е в главината — виж blade_sections
BLADE_STATIONS = ((0.0, 0.09, 0.30), (0.30, 0.19, 0.11), (0.50, 0.18, 0.09),
                  (0.70, 0.15, 0.08), (0.88, 0.11, 0.07), (1.00, 0.05, 0.07))


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def select(res):
    """Класът на мотора за дизайна (dict от MOTOR_CLASSES + "reason") или None."""
    p = (res or {}).get("propulsion") or {}
    power = _num(p.get("p_motor_elec_w") or p.get("p_max_elec_w"))
    if power <= 0 or _num(p.get("prop_d_in")) <= 0:
        return None
    torque = torque_nm(res)
    for cls in MOTOR_CLASSES:
        if cls["p_max_w"] >= POWER_HEADROOM * power                 and cls["q_max_nm"] >= TORQUE_HEADROOM * torque:
            out = dict(cls)
            out["reason"] = "%.0f W, %.2f N·m на витлото" % (power, torque)
            return out
    out = dict(MOTOR_CLASSES[-1])
    out["reason"] = ("най-големият в таблицата (%.0f W, %.2f N·m)"
                     % (power, torque))
    return out


def torque_nm(res):
    """Момент на витлото при пълна мощност: Q = P_вал / ω."""
    p = (res or {}).get("propulsion") or {}
    shaft = _num(p.get("p_max_shaft_w"))
    motors = max(1, int(_num(p.get("motor_count"), 1)))
    rpm = _num(p.get("rpm_target")) or _num(p.get("rpm_power"))
    if shaft <= 0 or rpm <= 0:
        return 0.0
    return shaft / motors / (rpm * 2.0 * math.pi / 60.0)


def bay_radius(res):
    """Радиус на носа, нужен за мотора (камбана + луфт + стена), mm."""
    cls = select(res)
    if not cls:
        return 0.0
    return 0.5 * cls["can_d"] + BAY_CLEAR_MM + COWL_WALL_MM


def prop_geometry(res):
    """Витлото: диаметър, стъпка, главина (mm)."""
    p = (res or {}).get("propulsion") or {}
    d_mm = _num(p.get("prop_d_in")) * INCH_MM
    pitch_mm = _num(p.get("prop_pitch_in")) * INCH_MM
    if d_mm <= 0:
        return None
    return {"d_mm": d_mm, "r_mm": 0.5 * d_mm, "pitch_mm": pitch_mm,
            "hub_d_mm": max(14.0, 0.055 * d_mm),
            "hub_t_mm": max(7.0, 0.035 * d_mm),
            "d_in": _num(p.get("prop_d_in")), "pitch_in": _num(p.get("prop_pitch_in"))}


def blade_sections(prop, points=8):
    """
    Сечения на една лопата в нейната равнина: [(r, [(a, b), …])], където
    a е по посоката на въртене (тангенциално), b — по оста на мотора
    (напред = +b, срещу полета). Сечението е лещовидно, завъртяно на
    ъгъла на стъпката β = atan(P / 2πr).
    """
    out = []
    radius = prop["r_mm"]
    hub_r = 0.5 * prop["hub_d_mm"]
    for frac, c_frac, t_frac in BLADE_STATIONS:
        r = frac * radius if frac > 0 else 0.6 * hub_r
        chord = max(3.0, c_frac * radius)
        thick = max(0.8, t_frac * chord)
        beta = math.atan2(prop["pitch_mm"], 2.0 * math.pi * r) if r > 0 else 0.0
        cb, sb = math.cos(beta), math.sin(beta)
        pts = []
        for k in range(points):
            ang = 2.0 * math.pi * k / points
            u = 0.5 * math.cos(ang)              # −½…½ по хордата
            v = 0.5 * thick * math.sin(ang) * (1.0 - 0.3 * abs(2 * u))
            a = u * chord
            pts.append((a * cb - v * sb, a * sb + v * cb))
        out.append((r, pts))
    return out


def layout(res):
    """
    Разположение на мотора(ите) и витлото(ата).

    връща {"motor", "prop", "propulsion", "x_firewall", "units": [
      {"y", "z", "dir", "x_prop", "x_can0", "x_can1", "x_mount",
       "x_shaft"}]} или None.

    `dir` = −1 — витлото е напред (теглещо), +1 — назад (бутащо).
    x_can0 е челото на камбаната към витлото, x_can1 — гърбът ѝ.
    """
    from . import fairing  # кръгов импорт: fairing ползва bay_radius
    cls = select(res)
    prop = prop_geometry(res)
    g = (res or {}).get("geometry") or {}
    fus = g.get("fuselage") or {}
    info = (res or {}).get("layout") or {}
    if not cls or not prop or not fus:
        return None
    length = _num(fus.get("length_mm"))
    height = _num(fus.get("height_mm"))
    propulsion = str(info.get("propulsion") or "tractor").lower()
    units = []
    x_fw = FIREWALL_FRAC * length
    if propulsion == "pusher":
        x0 = length + 1.0                         # стойката е на края на тялото
        units.append({"y": 0.0, "z": 0.5 * height, "dir": 1.0,
                      "x_mount": length, "x_can1": x0, "x_can0": x0 + cls["can_l"],
                      "x_prop": x0 + cls["can_l"] + 4.0 + 0.5 * prop["hub_t_mm"]})
        x_fw = None
    elif propulsion == "twin":
        semi = 0.5 * _num(g.get("span_mm"))
        wing_le = _num(g.get("wing_le_mm"))
        z_wing = _num(info.get("wing_z_mm"), 0.5 * height)
        dih = math.tan(math.radians(_num(g.get("dihedral_deg"))))
        y = 0.35 * semi
        x1 = wing_le - 4.0                        # гондола пред предния ръб
        for sign in (1.0, -1.0):
            units.append({"y": sign * y, "z": z_wing + y * dih, "dir": -1.0,
                          "x_mount": wing_le, "x_can1": x1,
                          "x_can0": x1 - cls["can_l"],
                          "x_prop": x1 - cls["can_l"] - 4.0 - 0.5 * prop["hub_t_mm"]})
        x_fw = None
    else:
        spin = fairing.spinner_params(res)
        if not spin:
            return None
        x_base = _num(spin["x_base"])
        x0 = x_base + SPINNER_GAP_MM
        x1 = x0 + cls["can_l"]
        x_fw = max(x_fw, x1 + MOUNT_T_MM, _num(spin["x_cowl1"]))
        units.append({"y": 0.0, "z": _num(spin["z_center"]), "dir": -1.0,
                      "x_can0": x0, "x_can1": x1, "x_mount": x1 + MOUNT_T_MM,
                      # витлото е в процепите на спинера, пред гърба му
                      "x_prop": x_base - 1.0 - 0.5 * prop["hub_t_mm"]})
    for unit in units:
        # валът стига от камбаната през главината на витлото
        unit["x_shaft_end"] = unit["x_prop"] + unit["dir"] * (
            0.5 * prop["hub_t_mm"] + 4.0)
    return {"motor": cls, "prop": prop, "propulsion": propulsion,
            "x_firewall": x_fw, "units": units}


def prop_frame(unit, blade):
    """
    Базис на лопата `blade` (0 или 1) за мотор `unit`:
    (център, e_s — по лопатата, e_t — по въртенето, e_x — оста напред).
    Лопатите са вертикални (спряно витло), втората е завъртяна на 180°.
    """
    sign = 1.0 if blade == 0 else -1.0
    centre = (unit["x_prop"], unit["y"], unit["z"])
    e_s = (0.0, 0.0, sign)
    e_t = (0.0, sign, 0.0)
    e_x = (-unit["dir"], 0.0, 0.0)          # „напред“ = срещу полета на витлото
    return centre, e_s, e_t, e_x


def blade_point(unit, blade, r, a, b):
    centre, e_s, e_t, e_x = prop_frame(unit, blade)
    return tuple(centre[i] + r * e_s[i] + a * e_t[i] + b * e_x[i]
                 for i in range(3))


def summary(res):
    """Кратко описание за UI/README (или None)."""
    lay = layout(res)
    if not lay:
        return None
    m, p = lay["motor"], lay["prop"]
    unit = lay["units"][0]
    clearance = unit["z"] - p["r_mm"]
    return {
        "motor": m["key"], "can_d_mm": m["can_d"], "can_l_mm": m["can_l"],
        "shaft_d_mm": m["shaft_d"], "mount_mm": list(m["mount"]),
        "mass_g": m["mass_g"], "p_max_w": m["p_max_w"], "reason": m["reason"],
        "prop": "%g×%g″" % (p["d_in"], p["pitch_in"]),
        "prop_d_mm": round(p["d_mm"], 1),
        "count": len(lay["units"]),
        # колко стърчи витлото под корема (Z = 0); > 0 → нужен колесник,
        # ръчно хвърляне или сгъваемо витло
        "below_belly_mm": round(max(0.0, -clearance), 1),
        "x_firewall_mm": (round(lay["x_firewall"], 1)
                          if lay["x_firewall"] is not None else None),
    }
