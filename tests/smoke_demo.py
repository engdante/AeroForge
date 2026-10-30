r"""
Бърза проверка „на ръка“: изчислява няколко примерни дизайна и печата
обобщение. Използва се при разработка и за валидация на формулите.

    python tests\smoke_demo.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "app"))

# На Windows конзолата е cp1251 — принуждаваме UTF-8, за да не гърми на „²“
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core import design  # noqa: E402


CASES = [
    ("Треньор, само тегло (LW-PLA)", {
        "name": "Trainer 600",
        "mission": "trainer",
        "payload": {"mode": "simple", "total_g": 600},
        "print": {"filament": "lw_pla", "perimeters": 1, "infill": 0},
    }),
    ("Същият, но PLA 2 периметъра", {
        "name": "Trainer PLA",
        "mission": "trainer",
        "payload": {"mode": "simple", "total_g": 600},
        "print": {"filament": "pla", "perimeters": 2, "infill": 15},
    }),
    ("Същият, PLA 1 периметър", {
        "name": "Trainer PLA 1P",
        "mission": "trainer",
        "payload": {"mode": "simple", "total_g": 600},
        "print": {"filament": "pla", "perimeters": 1, "infill": 0},
    }),
    ("FPV крило без опашка", {
        "name": "Wing 800",
        "mission": "flying_wing",
        "payload": {"mode": "simple", "total_g": 450},
        "wing": {"airfoil": "mh45"},
        "print": {"filament": "lw_pla", "perimeters": 1, "infill": 0},
    }),
    ("Списък компоненти", {
        "name": "Trainer BOM",
        "mission": "trainer",
        "payload": {
            "mode": "components",
            "components": [
                {"name": "Мотор 2212 1400Kv", "category": "motor",
                 "qty": 1, "unit_mass_g": 55},
                {"name": "ESC 30A", "category": "esc", "qty": 1,
                 "unit_mass_g": 30},
                {"name": "LiPo 3S 2200", "category": "battery", "qty": 1,
                 "unit_mass_g": 180},
                {"name": "Серва 9g", "category": "servo", "qty": 4,
                 "unit_mass_g": 9},
                {"name": "Приемник", "category": "rx", "qty": 1,
                 "unit_mass_g": 8},
                {"name": "Камера", "category": "camera", "qty": 1,
                 "unit_mass_g": 25},
            ],
        },
        "propulsion": {"cells": 3, "endurance_min": 10},
    }),
]


def summary_line(res):
    g = res["geometry"]
    a = res["aero"]
    w = res["weights"]
    s = res["stability"]
    p = res["propulsion"]
    pr = res["print"]
    return (
        "  маса %.0f g | размах %.0f mm | площ %.1f dm² | W/S %.1f g/dm²\n"
        "  V_stall %.1f m/s | Re %.0f | T/W %.2f | време %.0f мин\n"
        "  печат %.0f g (%.0f%%) | ЦТ %.0f%% MAC | SM %.0f%% | "
        "спар %.0f mm²\n"
        "  печат: %.1f h, %.0f g филамент, %.0f €, %d части"
        % (
            w["total_g"], g["span_mm"], g["area_dm2"],
            g["wing_loading_g_dm2"],
            a["v_stall_ms"], a["re_cruise"],
            p["thrust_to_weight_actual"], p["battery"]["endurance_min"],
            w["airframe_g"], w["airframe_pct"],
            s["cg_pct_mac"], s["static_margin_pct"],
            res["structure"]["cap_area_req_mm2"],
            pr["time_h"], pr["total_mass_g"], pr["cost"], pr["pieces"],
        )
    )


def main():
    from core import settings as app_settings
    defaults = app_settings.get_defaults()
    print("AeroForge — примерни дизайни")
    if app_settings.is_custom():
        print("Настройки: ПОТРЕБИТЕЛСКИ (settings.json) — филамент по "
              "подразбиране: %s" % defaults["print"]["filament"])
    else:
        print("Настройки: вградени (няма settings.json)")
    print()

    for title, inputs in CASES:
        res = design.compute(inputs)
        levels = {}
        for c in res["checks"]:
            levels[c["level"]] = levels.get(c["level"], 0) + 1
        print("=" * 72)
        print(title)
        print(summary_line(res))
        print("  итерации %d, конвергенция: %s"
              % (res["weights"]["iterations"],
                 "да" if res["weights"]["converged"] else "НЕ"))
        print("  проверки: %s" % ", ".join(
            "%s=%d" % (k, levels[k]) for k in sorted(levels)))
        for c in res["checks"]:
            if c["level"] in ("error", "warn"):
                print("   [%s] %s — %s" % (c["level"], c["title"], c["detail"]))
    print("=" * 72)


if __name__ == "__main__":
    main()
