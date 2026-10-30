"""
Тестове за задвижването: баланс мощност ↔ обороти ↔ ток ↔ ESC.

Това е най-важната проверка след промяната: Kv/оборотите вече не се
задават от процент от върховия лимит, а от мощността, която витлото
реално поглъща.
"""

import math
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import design, propulsion  # noqa: E402


def trainer_inputs(**overrides):
    inputs = {
        "mission": "trainer",
        "payload": {"mode": "simple", "total_g": 600},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(inputs.get(key), dict):
            inputs[key].update(value)
        else:
            inputs[key] = value
    return inputs


class TestPropHelpers(unittest.TestCase):
    def test_power_roundtrip(self):
        for rpm in (3000.0, 6000.0, 9500.0):
            p = propulsion.prop_power_w(rpm, 0.330)
            self.assertAlmostEqual(
                propulsion.prop_rpm_for_power(p, 0.330), rpm, delta=1e-6)

    def test_zero_inputs_are_safe(self):
        self.assertEqual(propulsion.prop_power_w(0.0, 0.3), 0.0)
        self.assertEqual(propulsion.prop_power_w(5000.0, 0.0), 0.0)
        self.assertEqual(propulsion.prop_rpm_for_power(0.0, 0.3), 0.0)
        self.assertEqual(propulsion.prop_rpm_for_power(50.0, 0.0), 0.0)


class TestSizedSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = design.compute(trainer_inputs())
        cls.p = cls.res["propulsion"]

    def test_power_and_rpm_are_consistent(self):
        p = self.p
        absorbed = propulsion.prop_power_w(p["rpm_target"], p["prop_d_m"])
        if p.get("rpm_capped"):
            self.assertLessEqual(absorbed, p["p_max_shaft_w"] * 1.02)
        else:
            self.assertAlmostEqual(absorbed, p["p_max_shaft_w"],
                                   delta=0.02 * p["p_max_shaft_w"])

    def test_target_rpm_is_below_tip_limit(self):
        self.assertLessEqual(self.p["rpm_target"], self.p["rpm_tip"] + 1e-6)
        # при пълна батерия без товар също не бива да надхвърля лимита
        self.assertLessEqual(self.p["rpm_full_noload"],
                             self.p["rpm_tip"] + 1e-6)

    def test_kv_matches_loaded_rpm(self):
        expected = self.p["kv"] * self.p["voltage_v"] * 0.75
        self.assertAlmostEqual(expected, self.p["rpm_target"], delta=1.0)

    def test_current_matches_electrical_power(self):
        self.assertAlmostEqual(
            self.p["i_max_a"] * self.p["voltage_v"],
            self.p["p_max_elec_w"], places=6)

    def test_esc_has_margin_when_not_saturated(self):
        if not self.p.get("esc_saturated"):
            self.assertGreaterEqual(
                self.p["esc_a"], 1.25 * self.p["i_max_a"] - 1e-9)

    def test_advance_ratio_is_sane(self):
        self.assertGreater(self.p["advance_ratio_cruise"], 0.15)
        self.assertLess(self.p["advance_ratio_cruise"], 0.90)

    def test_base_prop_has_no_conflict(self):
        self.assertFalse(self.p["rpm_conflict"])


class TestEscSaturation(unittest.TestCase):
    def test_over_150a_is_flagged(self):
        res = design.compute({
            "mission": "3d",
            "payload": {"mode": "simple", "total_g": 3000},
            "propulsion": {"cells": 3, "power_to_weight": 600,
                           "thrust_to_weight": 1.0},
        })
        p = res["propulsion"]
        self.assertGreater(p["esc_required_a"], 150.0)
        self.assertTrue(p["esc_saturated"])
        titles = [c["title"] for c in res["checks"]]
        self.assertIn("ESC над стандартния размер", titles)


class TestPropDiameterValidation(unittest.TestCase):
    def test_too_small_is_clamped(self):
        res = design.compute(trainer_inputs(
            propulsion={"prop_d_in": 0.5}))
        self.assertGreaterEqual(res["propulsion"]["prop_d_in"], 5)

    def test_too_large_is_clamped(self):
        res = design.compute(trainer_inputs(
            propulsion={"prop_d_in": 100}))
        self.assertLessEqual(res["propulsion"]["prop_d_in"], 24)


if __name__ == "__main__":
    unittest.main()
