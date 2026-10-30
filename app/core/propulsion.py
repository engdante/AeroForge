"""
propulsion.py — оразмеряване на задвижването (мотор, витло, ESC, батерия).

Моделът е класическа momentum-theory оценка за статична тяга плюс поляра
за мощността в крейсер. Коефициентите са практически, не са CFD.
"""

import math

from . import aero
from . import presets

G = 9.80665
RHO = 1.225

ETA_MOTOR = 0.80        # КПД на безчетков мотор под товар
ETA_ESC = 0.95          # КПД на регулатора
ETA_PROP = 0.55         # КПД на витлото в крейсер
FIGURE_OF_MERIT = 0.65  # качество на витлото при статична тяга
TIP_SPEED_MAX = 0.60 * 343.0   # m/s — граница по шум/ефективност
LIPO_CELL_V = 3.70
DOD = 0.80              # използваем заряд на батерията
MOTOR_W_PER_G = 4.0     # W входна мощност на грам мотор
ESC_W_PER_G = 12.0      # W на грам ESC


# --------------------------------------------------------------------------
# Витло и тяга
# --------------------------------------------------------------------------
def choose_prop_diameter_in(span_m, max_in=20):
    """Диаметър на витлото: ~25% от размаха, закръглен до цял инч."""
    d_in = 0.25 * span_m / 0.0254
    return int(presets.clamp(round(d_in), 6, max_in))


def disc_area_m2(d_m):
    """Площ на метателния диск на витлото."""
    return math.pi * (d_m / 2.0) ** 2


def static_thrust_n(p_shaft_w, d_m, fm=FIGURE_OF_MERIT):
    """
    Статична тяга по momentum theory: T = (2ρA)^(1/3)·(FM·P)^(2/3).
    """
    p_shaft_w = max(0.0, p_shaft_w)
    a = disc_area_m2(d_m)
    if a <= 0:
        return 0.0
    return (2.0 * RHO * a) ** (1.0 / 3.0) * (fm * p_shaft_w) ** (2.0 / 3.0)


def power_for_thrust_w(thrust_n, d_m, fm=FIGURE_OF_MERIT):
    """Мощност на вала, нужна за дадена статична тяга (обратна на горната)."""
    a = disc_area_m2(d_m)
    if a <= 0 or thrust_n <= 0:
        return 0.0
    return thrust_n ** 1.5 / (fm * math.sqrt(2.0 * RHO * a))


def rpm_limits(d_m, v_cruise_ms, pitch_m):
    """(лимит по върхова скорост, минимални обороти за крейсер)."""
    if d_m <= 0:
        return 0.0, 0.0
    rpm_tip = (TIP_SPEED_MAX / (math.pi * d_m)) * 60.0
    rpm_pitch = (60.0 * 1.5 * v_cruise_ms / pitch_m) if pitch_m > 0 else 0.0
    return rpm_tip, rpm_pitch


# --------------------------------------------------------------------------
# Основно оразмеряване
# --------------------------------------------------------------------------
def size_system(mass_kg, geom, v_stall_ms, v_cruise_ms, mission,
                cells=3, capacity_mah=None, endurance_min=8.0,
                thrust_to_weight=None, power_to_weight=None,
                prop_d_in=None, cd0=None):
    """
    Пълно оразмеряване на задвижването.

    връща dict с мощности, тяга, витло, Kv, ток, ESC, батерия и време.
    """
    cells = int(presets.clamp(int(cells or 3), 1, 14))
    voltage = cells * LIPO_CELL_V

    tw = float(thrust_to_weight if thrust_to_weight else
               mission.get("thrust_to_weight", 0.6))
    p2w = float(power_to_weight if power_to_weight else
                mission.get("power_to_weight", 150.0))

    p_max_elec = p2w * mass_kg
    p_shaft_avail = p_max_elec * ETA_MOTOR * ETA_ESC

    d_in = int(prop_d_in) if prop_d_in else choose_prop_diameter_in(
        geom["span_m"])
    d_m = d_in * 0.0254
    pitch_in = max(2.0, round(0.6 * d_in))
    pitch_m = pitch_in * 0.0254

    thrust_req = tw * mass_kg * G
    p_for_thrust = power_for_thrust_w(thrust_req, d_m)
    p_max_elec_needed = p_for_thrust / (ETA_MOTOR * ETA_ESC)

    # Ако наличната мощност не стига за желаната тяга — вдигаме мощността
    p_max_elec = max(p_max_elec, p_max_elec_needed)
    p_shaft_avail = p_max_elec * ETA_MOTOR * ETA_ESC
    thrust_avail = static_thrust_n(p_shaft_avail, d_m)

    rpm_tip, rpm_pitch = rpm_limits(d_m, v_cruise_ms, pitch_m)
    rpm_target = presets.clamp(0.80 * rpm_tip, max(rpm_pitch, 0.0), rpm_tip)
    kv = rpm_target / (voltage * 0.75) if voltage > 0 else 0.0

    i_max = p_max_elec / voltage if voltage > 0 else 0.0
    esc_a = presets.pick_at_least(presets.ESC_SIZES_A, 1.25 * i_max)

    # Крейсер: мощност от полярата
    cd0_used = cd0 if cd0 is not None else mission.get("cd0", 0.032)
    cruise = aero.level_flight(
        mass_kg, geom["area_m2"], geom["aspect_ratio"],
        mission.get("oswald", 0.75), cd0_used, v_cruise_ms, ETA_PROP)
    p_elec_cruise = cruise["p_shaft_w"] / (ETA_MOTOR * ETA_ESC)

    energy_needed_wh = p_elec_cruise * endurance_min / 60.0 / DOD
    cap_auto_ah = energy_needed_wh / voltage if voltage > 0 else 0.0

    if capacity_mah:
        cap_ah = float(capacity_mah) / 1000.0
        capacity_source = "зададен от потребителя"
    else:
        cap_mah = presets.pick_at_least(
            presets.BATTERY_CAPACITIES_MAH, cap_auto_ah * 1000.0)
        cap_ah = cap_mah / 1000.0
        capacity_source = "изчислен от желаното време"

    capacity_mah_used = cap_ah * 1000.0
    energy_wh = cap_ah * voltage
    usable_wh = energy_wh * DOD
    endurance_actual = (usable_wh / p_elec_cruise * 60.0
                        if p_elec_cruise > 0 else 0.0)
    c_needed = i_max / cap_ah if cap_ah > 0 else 0.0
    battery_mass_g = energy_wh / presets.BATTERY_SPECIFIC_ENERGY_WH_KG * 1000.0
    battery_volume_cm3 = energy_wh / presets.BATTERY_ENERGY_DENSITY_WH_CM3

    return {
        "cells": cells,
        "voltage_v": voltage,
        "power_to_weight": p2w,
        "p_max_elec_w": p_max_elec,
        "p_max_shaft_w": p_shaft_avail,
        "thrust_to_weight_target": tw,
        "thrust_req_n": thrust_req,
        "thrust_avail_n": thrust_avail,
        "thrust_avail_kg": thrust_avail / G,
        "thrust_to_weight_actual": thrust_avail / (mass_kg * G),
        "prop_d_in": d_in,
        "prop_pitch_in": pitch_in,
        "prop_d_m": d_m,
        "rpm_tip": rpm_tip,
        "rpm_min": rpm_pitch,
        "rpm_target": rpm_target,
        "kv": kv,
        "i_max_a": i_max,
        "esc_a": esc_a,
        "cruise": {
            "v_ms": v_cruise_ms,
            "cl": cruise["cl"],
            "cd": cruise["cd"],
            "drag_n": cruise["drag_n"],
            "p_shaft_w": cruise["p_shaft_w"],
            "p_elec_w": p_elec_cruise,
        },
        "battery": {
            "cells": cells,
            "capacity_mah": capacity_mah_used,
            "capacity_source": capacity_source,
            "voltage_v": voltage,
            "energy_wh": energy_wh,
            "usable_wh": usable_wh,
            "c_rating_needed": c_needed,
            "mass_g": battery_mass_g,
            "volume_cm3": battery_volume_cm3,
            "endurance_min": endurance_actual,
            "endurance_target_min": endurance_min,
        },
        "v_stall_ms": v_stall_ms,
    }


# --------------------------------------------------------------------------
# Оценки на масите на липсващите компоненти
# --------------------------------------------------------------------------
def servo_plan(mission_key):
    """Брой и единична маса на сервомашините по тип модел."""
    m = presets.mission(mission_key)
    if not m.get("has_tail", True):
        return 2, 12.0          # два elevon серва
    mass = {"trainer": 9.0, "sport": 12.0, "3d": 20.0,
            "glider": 9.0, "cargo": 20.0}.get(mission_key, 12.0)
    count = 4 if mission_key in ("trainer", "glider", "cargo") else 3
    return count, mass


def estimate_component_masses(spec, mission_key, provided_categories):
    """
    Оценява масите на компонентите, които потребителят не е задал.

    връща списък от компоненти с estimated=True (за BOM и за отчет).
    """
    provided = set(provided_categories or [])
    out = []

    def add(cid, name, category, unit_mass_g, note=""):
        if category in provided:
            return
        out.append({
            "id": cid,
            "name": name,
            "category": category,
            "qty": 1,
            "unit_mass_g": round(float(unit_mass_g), 1),
            "mass_g": round(float(unit_mass_g), 1),
            "estimated": True,
            "note": note,
        })

    p_max = spec["p_max_elec_w"]
    add("motor_est", "Мотор (оценка по мощност)", "motor",
        p_max / MOTOR_W_PER_G, "%d W входна мощност" % round(p_max))
    add("esc_est", "ESC (оценка)", "esc",
        p_max / ESC_W_PER_G, "%d A" % spec["esc_a"])
    add("prop_est", "Витло %d×%d" % (spec["prop_d_in"], spec["prop_pitch_in"]),
        "prop", presets.interp(presets.PROP_MASS_G, spec["prop_d_in"]))
    add("battery_est", "Батерия %dS %d mAh" % (
        spec["battery"]["cells"], round(spec["battery"]["capacity_mah"])),
        "battery", spec["battery"]["mass_g"])

    if "servo" not in provided:
        count, servo_mass = servo_plan(mission_key)
        out.append({
            "id": "servo_est",
            "name": "Серва",
            "category": "servo",
            "qty": count,
            "unit_mass_g": servo_mass,
            "mass_g": count * servo_mass,
            "estimated": True,
            "note": "елерони/елеватор/кормило",
        })

    add("rx_est", "Приемник + антена", "rx", 10.0)
    add("hw_est", "Лепило, крепеж, кабели", "hardware",
        max(15.0, 0.05 * p_max))
    return out


