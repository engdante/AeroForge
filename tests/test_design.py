"""
Интеграционни тестове: цялостен дизайн през design.compute().

Тук се проверява дали резултатите попадат в реалистични диапазони за
RC модел — това е „тестът за здрав разум“ на целия модел.
"""

import os
import sys
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import design  # noqa: E402


def trainer_inputs(**overrides):
    inputs = {
        "name": "Test Trainer",
        "mission": "trainer",
        "payload": {"mode": "simple", "total_g": 600},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(inputs.get(key), dict):
            inputs[key].update(value)
        else:
            inputs[key] = value
    return inputs


class TestBasicDesign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = design.compute(trainer_inputs())

    def test_result_is_ok(self):
        self.assertTrue(self.res["ok"], self.res.get("error"))

    def test_converged(self):
        self.assertTrue(self.res["weights"]["converged"],
                        "масовият бюджет не се стабилизира")

    def test_mass_budget_sums_up(self):
        w = self.res["weights"]
        self.assertAlmostEqual(w["total_g"],
                               w["payload_g"] + w["airframe_g"], places=6)

    def test_geometry_in_realistic_range(self):
        g = self.res["geometry"]
        self.assertGreater(g["span_mm"], 900)
        self.assertLess(g["span_mm"], 1800)
        self.assertGreater(g["area_dm2"], 18)
        self.assertLess(g["area_dm2"], 45)
        self.assertGreater(g["c_root_mm"], g["c_tip_mm"])
        self.assertGreater(g["mac_mm"], g["c_tip_mm"])
        self.assertLess(g["mac_mm"], g["c_root_mm"])

    def test_wing_loading_matches_target(self):
        g = self.res["geometry"]
        target = self.res["resolved"]["wing_loading"]
        self.assertAlmostEqual(g["wing_loading_g_dm2"], target, delta=2.0)

    def test_stall_and_cruise_speeds(self):
        a = self.res["aero"]
        self.assertGreater(a["v_stall_ms"], 4.0)
        self.assertLess(a["v_stall_ms"], 10.0)
        self.assertGreater(a["v_cruise_ms"], a["v_stall_ms"])

    def test_reynolds_reported(self):
        self.assertGreater(self.res["aero"]["re_cruise"], 20000)

    def test_thrust_to_weight(self):
        tw = self.res["propulsion"]["thrust_to_weight_actual"]
        self.assertGreater(tw, 0.3)
        self.assertLess(tw, 2.5)

    def test_center_of_gravity_balanced(self):
        s = self.res["stability"]
        self.assertAlmostEqual(s["static_margin_actual"],
                               s["static_margin_target"], delta=0.01)
        self.assertNotEqual(s["battery_x_required_mm"], None)

    def test_structure_values(self):
        st = self.res["structure"]
        self.assertGreater(st["m_root_nm"], 0.0)
        self.assertGreater(st["cap_area_req_mm2"], 0.0)

    def test_print_estimate(self):
        pr = self.res["print"]
        self.assertGreater(pr["total_mass_g"], 20.0)
        self.assertAlmostEqual(pr["total_mass_g"],
                               sum(p["mass_g"] for p in pr["parts"]),
                               places=6)
        self.assertGreater(pr["time_h"], 1.0)

    def test_lw_pla_has_no_critical_errors(self):
        errors = [c for c in self.res["checks"] if c["level"] == "error"]
        self.assertEqual(errors, [], "неочаквани критични грешки: %s"
                         % [c["title"] for c in errors])

    def test_checks_have_all_fields(self):
        for c in self.res["checks"]:
            self.assertIn(c["level"], ("ok", "info", "warn", "error"))
            self.assertTrue(c["title"])
            self.assertTrue(c["detail"])

    def test_deterministic(self):
        again = design.compute(trainer_inputs())
        self.assertAlmostEqual(again["weights"]["total_g"],
                               self.res["weights"]["total_g"], places=6)


class TestMonotonicity(unittest.TestCase):
    def test_more_payload_more_wing(self):
        small = design.compute(trainer_inputs(
            payload={"mode": "simple", "total_g": 400}))
        big = design.compute(trainer_inputs(
            payload={"mode": "simple", "total_g": 900}))
        self.assertGreater(big["geometry"]["span_mm"],
                           small["geometry"]["span_mm"])
        self.assertGreater(big["weights"]["total_g"],
                           small["weights"]["total_g"])

    def test_lw_pla_lighter_than_pla(self):
        lw = design.compute(trainer_inputs())
        pla = design.compute(trainer_inputs(
            print={"filament": "pla", "perimeters": 1, "infill": 0}))
        self.assertLess(lw["weights"]["airframe_pct"],
                        pla["weights"]["airframe_pct"])


class TestComponentMode(unittest.TestCase):
    def test_components_are_used(self):
        res = design.compute({
            "name": "BOM тест",
            "mission": "sport",
            "payload": {
                "mode": "components",
                "components": [
                    {"name": "Мотор", "category": "motor", "qty": 1,
                     "unit_mass_g": 80},
                    {"name": "Батерия", "category": "battery", "qty": 1,
                     "unit_mass_g": 200},
                    {"name": "Серва", "category": "servo", "qty": 4,
                     "unit_mass_g": 12},
                    {"name": "Камера", "category": "camera", "qty": 1,
                     "unit_mass_g": 40},
                ],
            },
            "propulsion": {"cells": 4, "capacity_mah": 2200,
                           "endurance_min": 6},
        })
        self.assertTrue(res["ok"])
        names = [c["name"] for c in res["weights"]["components"]]
        self.assertIn("Мотор", names)
        self.assertIn("Камера", names)
        # липсващите категории се оценяват автоматично
        self.assertTrue(any("ESC" in n for n in names), names)

    def test_explicit_position_is_kept(self):
        res = design.compute({
            "payload": {
                "mode": "components",
                "components": [
                    {"name": "Батерия", "category": "battery", "qty": 200,
                     "unit_mass_g": 1, "x_mm": 120},
                ],
            },
        })
        battery = [c for c in res["weights"]["components"]
                   if c["category"] == "battery"][0]
        self.assertAlmostEqual(battery["x_mm"], 120.0, places=6)


class TestFlyingWing(unittest.TestCase):
    def test_no_tail(self):
        res = design.compute({
            "mission": "flying_wing",
            "payload": {"mode": "simple", "total_g": 450},
            "wing": {"airfoil": "mh45"},
        })
        self.assertTrue(res["ok"])
        self.assertFalse(res["mission"]["has_tail"])
        self.assertEqual(res["geometry"]["tail"]["s_h_dm2"], 0.0)
        self.assertEqual(res["geometry"]["tail"]["s_v_dm2"], 0.0)

    def test_reflexed_airfoil_has_no_profile_warning(self):
        res = design.compute({
            "mission": "flying_wing",
            "payload": {"mode": "simple", "total_g": 450},
            "wing": {"airfoil": "mh45"},
        })
        titles = [c["title"] for c in res["checks"]]
        self.assertNotIn("Профил за крило без опашка", titles)


class TestInfeasibleCases(unittest.TestCase):
    def test_heavy_filament_increases_wing_loading(self):
        """PLA с 2 периметъра не може да носи себе си при 32 g/dm²."""
        res = design.compute(trainer_inputs(
            print={"filament": "pla", "perimeters": 2, "infill": 15}))
        self.assertTrue(res["ok"])
        used = res["resolved"]["wing_loading"]
        requested = res["resolved"]["wing_loading_requested"]
        self.assertGreater(used, requested)
        titles = [c["title"] for c in res["checks"]]
        self.assertIn("Натоварването на крилото е променено", titles)

    def test_zero_payload_still_computes(self):
        res = design.compute({
            "payload": {"mode": "simple", "total_g": 0},
        })
        self.assertTrue(res["ok"])


if __name__ == "__main__":
    unittest.main()

