"""
Интеграционни тестове: цялостен дизайн през design.compute().

Тук се проверява дали резултатите попадат в реалистични диапазони за
RC модел — това е „тестът за здрав разум“ на целия модел.
"""

import math
import os
import sys
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import design, report  # noqa: E402


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
        self.assertTrue(s["battery_feasible"])
        self.assertTrue(s["ready_to_fly"])

    def test_static_margin_uses_neutral_point(self):
        """NP е зад AC на крилото (принос на опашката), а ЦТ е зад 25% MAC."""
        s = self.res["stability"]
        self.assertGreater(s["x_np_mm"], s["x_ac_mm"])
        self.assertGreater(s["cg_pct_mac"], 25.0)
        self.assertLess(s["cg_pct_mac"], 45.0)
        # SM е спрямо NP, не спрямо AC
        self.assertAlmostEqual(s["static_margin_actual"],
                               (s["x_np_mm"] - s["x_cg_mm"]) / s["mac_mm"],
                               places=9)

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

    def test_no_tail_neutral_point_is_the_ac(self):
        res = design.compute({
            "mission": "flying_wing",
            "payload": {"mode": "simple", "total_g": 450},
            "wing": {"airfoil": "mh45"},
        })
        s = res["stability"]
        self.assertAlmostEqual(s["x_np_mm"], s["x_ac_mm"], places=9)

    def test_reflexed_airfoil_has_no_profile_warning(self):
        res = design.compute({
            "mission": "flying_wing",
            "payload": {"mode": "simple", "total_g": 450},
            "wing": {"airfoil": "mh45"},
        })
        titles = [c["title"] for c in res["checks"]]
        self.assertNotIn("Профил за крило без опашка", titles)


class TestInfeasibleBalance(unittest.TestCase):
    """Тежък товар на опашката → батерията не може да балансира."""

    @classmethod
    def setUpClass(cls):
        cls.res = design.compute({
            "mission": "trainer",
            "payload": {
                "mode": "components",
                "components": [
                    {"name": "Батерия", "category": "battery", "qty": 1,
                     "unit_mass_g": 120},
                    {"name": "Товар на опашката", "category": "other",
                     "qty": 1, "unit_mass_g": 600, "x_mm": 900},
                ],
            },
        })

    def test_battery_out_of_range(self):
        s = self.res["stability"]
        self.assertFalse(s["battery_feasible"])
        self.assertLess(s["battery_x_required_mm"], 0.0)
        # батерията е сложена на границата на обхвата, не на невъзможното място
        self.assertGreaterEqual(s["battery_x_placed_mm"], 0.0)
        self.assertLessEqual(s["battery_x_placed_mm"],
                             0.72 * self.res["geometry"]["fuselage"]["length_mm"])

    def test_cg_is_not_reported_as_target(self):
        """ЦТ НЕ трябва да съвпада с целевия, когато балансът е невъзможен."""
        s = self.res["stability"]
        self.assertGreater(abs(s["x_cg_mm"] - s["x_target_mm"]), 1.0)
        self.assertFalse(s["ready_to_fly"])
        self.assertFalse(s["cg_achievable"])

    def test_error_check_explains_it(self):
        titles = [c["title"] for c in self.res["checks"] if c["level"] == "error"]
        self.assertTrue(any("опашка" in t or "не е постижим" in t
                            for t in titles), titles)


class TestThrustCheckIsNotTautological(unittest.TestCase):
    def test_low_power_to_weight_triggers_warning(self):
        res = design.compute(trainer_inputs(
            propulsion={"power_to_weight": 10, "thrust_to_weight": 1.6}))
        titles = [c["title"] for c in res["checks"]]
        self.assertIn("Тягата изисква повече мощност от препоръчаната", titles)
        # мощността наистина е вдигната, за да се постигне целта
        self.assertGreater(res["propulsion"]["p_max_elec_w"],
                           res["propulsion"]["p_elec_recommended_w"])

    def test_enough_power_keeps_ok(self):
        res = design.compute(trainer_inputs(
            propulsion={"power_to_weight": 400, "thrust_to_weight": 0.5}))
        titles = [c["title"] for c in res["checks"]]
        self.assertNotIn("Тягата изисква повече мощност от препоръчаната",
                         titles)


class TestInfeasibleCases(unittest.TestCase):
    def test_heavy_filament_increases_wing_loading(self):
        """PLA с 2 периметъра не може да носи себе си при 32 g/dm²."""
        res = design.compute(trainer_inputs(
            print={"filament": "pla", "perimeters": 2, "infill": 15}))
        self.assertTrue(res["ok"])
        used = res["resolved"]["wing_loading"]
        requested = res["resolved"]["wing_loading_requested"]
        self.assertGreater(used, requested)
        # вдигането е ограничено (не 4.5×, както преди)
        self.assertLessEqual(used, requested * 1.25 + 1e-6)
        titles = [c["title"] for c in res["checks"]]
        self.assertIn("Натоварването на крилото е променено", titles)

    def test_infeasible_design_does_not_explode(self):
        """Без решение масата не бива да расте до абсурд (преди 2.9–8 kg)."""
        res = design.compute(trainer_inputs(
            print={"filament": "pla", "perimeters": 2, "infill": 15}))
        self.assertFalse(res["resolved"]["feasible"])
        self.assertLess(res["weights"]["airframe_pct"], 100.0)
        self.assertLess(res["weights"]["total_g"], 5000.0)
        titles = [c["title"] for c in res["checks"]]
        self.assertIn("Конструкцията не може да носи себе си", titles)

    def test_zero_payload_still_computes(self):
        res = design.compute({
            "payload": {"mode": "simple", "total_g": 0},
        })
        self.assertTrue(res["ok"])


class TestSimpleModeIsolation(unittest.TestCase):
    def test_leftover_components_are_ignored(self):
        clean = design.compute(trainer_inputs())
        left = design.compute(trainer_inputs(payload={
            "mode": "simple", "total_g": 600,
            "components": [{"name": "Motor", "category": "motor",
                            "qty": 1, "unit_mass_g": 100}],
        }))
        self.assertAlmostEqual(clean["weights"]["total_g"],
                               left["weights"]["total_g"], places=6)
        self.assertAlmostEqual(clean["weights"]["payload_g"],
                               left["weights"]["payload_g"], places=6)
        self.assertAlmostEqual(clean["geometry"]["wing_loading_g_dm2"],
                               left["geometry"]["wing_loading_g_dm2"],
                               places=6)


class TestReadyToFlyAggregation(unittest.TestCase):
    def test_ready_is_false_for_infeasible_design(self):
        res = design.compute({
            "mission": "trainer",
            "payload": {"mode": "simple", "total_g": 100},
            "print": {"filament": "lw_pla", "perimeters": 2, "infill": 10},
            "wing": {"wing_loading": 20},
        })
        self.assertFalse(res["resolved"]["feasible"])
        self.assertFalse(res["stability"]["ready_to_fly"])
        self.assertTrue(res["stability"]["blocking_checks"])


class TestInfeasibleBudgetReporting(unittest.TestCase):
    def test_no_root_has_gap_and_correct_message(self):
        res = design.compute(trainer_inputs(
            print={"filament": "pla", "perimeters": 2, "infill": 15}))
        w = res["weights"]
        self.assertFalse(res["resolved"]["feasible"])
        self.assertFalse(w["converged"])
        self.assertFalse(w["budget_closed"])
        self.assertGreater(w["budget_gap_g"], 1.0)
        titles = [c["title"] for c in res["checks"]]
        self.assertIn("Няма решение на масовия бюджет", titles)
        self.assertIn("Масовият бюджет не се затваря", titles)


class TestAirfoilCdMin(unittest.TestCase):
    def test_cd_min_changes_drag_and_ld(self):
        low = design.compute(trainer_inputs(
            wing={"airfoil": "naca0009"}))
        high = design.compute(trainer_inputs(
            wing={"airfoil": "s1223"}))
        self.assertLess(low["aero"]["cd0"], high["aero"]["cd0"])
        self.assertGreater(low["aero"]["ld_max"], high["aero"]["ld_max"])


class TestBatteryMass(unittest.TestCase):
    def test_component_mass_is_used(self):
        res = design.compute({
            "mission": "trainer",
            "payload": {"mode": "components", "components": [
                {"name": "Battery", "category": "battery", "qty": 1,
                 "unit_mass_g": 180, "x_mm": 180},
                {"name": "Motor", "category": "motor", "qty": 1,
                 "unit_mass_g": 55},
            ]},
            "propulsion": {"cells": 3, "capacity_mah": 2200},
        })
        bat = res["propulsion"]["battery"]
        self.assertAlmostEqual(bat["mass_g"], 180.0, places=6)
        self.assertEqual(bat["mass_source"], "зададена от компонента")


class TestInputValidation(unittest.TestCase):
    def test_non_finite_payload_falls_back(self):
        for value in ("inf", "nan", "-inf"):
            res = design.compute({
                "payload": {"mode": "simple", "total_g": value}})
            self.assertTrue(res["ok"])
            self.assertTrue(math.isfinite(res["weights"]["total_g"]))

    def test_huge_payload_is_capped(self):
        res = design.compute({
            "payload": {"mode": "simple", "total_g": 1e12}})
        self.assertLessEqual(res["inputs"]["payload"]["total_g"],
                             design.MAX_PAYLOAD_G + 1e-6)


class TestEstimatedFlag(unittest.TestCase):
    def test_flag_survives_input_normalization(self):
        res = design.compute({
            "mission": "trainer",
            "payload": {"mode": "components", "components": [
                {"name": "Motor (est)", "category": "motor", "qty": 1,
                 "unit_mass_g": 50, "estimated": True},
                {"name": "Battery", "category": "battery", "qty": 1,
                 "unit_mass_g": 150},
            ]},
        })
        motor = [c for c in res["weights"]["components"]
                 if c["name"] == "Motor (est)"][0]
        self.assertTrue(motor["estimated"])
        inp = [c for c in res["inputs"]["payload"]["components"]
               if c["name"] == "Motor (est)"][0]
        self.assertTrue(inp["estimated"])


class TestBomBatteryPosition(unittest.TestCase):
    def test_bom_uses_balanced_position(self):
        res = design.compute({
            "mission": "trainer",
            "payload": {"mode": "components", "components": [
                {"name": "Battery", "category": "battery", "qty": 1,
                 "unit_mass_g": 180, "x_mm": 120},
                {"name": "Motor", "category": "motor", "qty": 1,
                 "unit_mass_g": 55},
            ]},
        })
        bat = [c for c in res["weights"]["components"]
               if c["category"] == "battery"][0]
        self.assertAlmostEqual(bat["x_mm"], 120.0, places=6)
        self.assertIn("x_placed_mm", bat)
        self.assertAlmostEqual(bat["x_placed_mm"],
                               res["stability"]["battery_x_placed_mm"])
        row = [line for line in report.build_bom_csv(res).splitlines()
               if "Battery" in line][0]
        self.assertIn("%.0f" % bat["x_placed_mm"], row)


class TestTailFit(unittest.TestCase):
    def test_tail_fits_fuselage_and_preserves_volume(self):
        res = design.compute(trainer_inputs())
        g = res["geometry"]
        t = g["tail"]
        self.assertTrue(t["tail_fit_limited"])
        self.assertLessEqual(t["l_h_mm"],
                             t["l_h_configured_mm"] + 1e-6)
        c_tail = max(t["c_h_mm"], t["c_v_mm"])
        self.assertLessEqual(t["tail_ac_mm"] + 0.75 * c_tail,
                             g["fuselage"]["length_mm"] + 1e-6)
        s_h = t["s_h_dm2"] / 100.0
        vh_actual = (s_h * (t["l_h_mm"] / 1000.0)
                     / (g["area_m2"] * g["mac_mm"] / 1000.0))
        self.assertAlmostEqual(vh_actual, t["vh"], delta=0.01)


if __name__ == "__main__":
    unittest.main()

