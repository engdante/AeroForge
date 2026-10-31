"""
Тестове за компоновката (layout.py): позиции на компонентите, брой
мотори, височина на крилото и геометрия на V-опашка.
"""

import math
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import layout, weight  # noqa: E402


class TestPropulsionLayouts(unittest.TestCase):
    def test_catalog_is_complete(self):
        keys = [item["key"] for item in layout.list_propulsion()]
        self.assertEqual(keys, ["tractor", "pusher", "twin"])

    def test_motor_counts(self):
        self.assertEqual(layout.motor_count("tractor"), 1)
        self.assertEqual(layout.motor_count("pusher"), 1)
        self.assertEqual(layout.motor_count("twin"), 2)
        self.assertEqual(layout.motor_count("непознато"), 1)

    def test_tractor_keeps_default_positions(self):
        pos = layout.positions("tractor", 1000.0, 300.0, 200.0)
        for category, frac in weight.DEFAULT_X_FRACTION.items():
            self.assertAlmostEqual(pos[category], frac * 1000.0, places=6)

    def test_pusher_moves_motor_to_tail(self):
        pos = layout.positions("pusher", 1000.0, 300.0, 200.0)
        self.assertGreater(pos["motor"], 0.90 * 1000.0)
        self.assertGreater(pos["prop"], pos["motor"])
        self.assertLess(pos["battery"], 0.30 * 1000.0)

    def test_twin_motors_are_on_the_wing(self):
        pos = layout.positions("twin", 1000.0, 300.0, 200.0)
        self.assertAlmostEqual(pos["motor"], 300.0 + 50.0, places=6)
        self.assertAlmostEqual(pos["prop"], pos["motor"], places=6)

    def test_positions_are_positive(self):
        for key in ("tractor", "pusher", "twin"):
            pos = layout.positions(key, 1000.0, 300.0, 200.0)
            for category, value in pos.items():
                self.assertGreaterEqual(value, 0.0, category)


class TestWingPositions(unittest.TestCase):
    def test_factor_order(self):
        self.assertGreater(layout.wing_z_factor("high"),
                           layout.wing_z_factor("mid"))
        self.assertGreater(layout.wing_z_factor("mid"),
                           layout.wing_z_factor("low"))

    def test_unknown_falls_back_to_high(self):
        self.assertEqual(layout.wing_z_factor("няма"),
                         layout.wing_z_factor("high"))


class TestVTail(unittest.TestCase):
    def test_projected_areas_meet_requirements(self):
        panel = layout.v_tail_panel(0.06, 0.03, 35.0)
        self.assertGreaterEqual(panel["s_h_eff_m2"], 0.06 - 1e-9)
        self.assertGreaterEqual(panel["s_v_eff_m2"], 0.03 - 1e-9)
        self.assertGreaterEqual(panel["s_panel_m2"], 0.06)

    def test_gamma_45_halves_projection(self):
        panel = layout.v_tail_panel(0.1, 0.1, 45.0)
        self.assertAlmostEqual(panel["s_panel_m2"], 0.1 / math.cos(
            math.radians(45.0)), places=6)

    def test_angle_is_clamped(self):
        self.assertLessEqual(layout.v_tail_panel(0.05, 0.02, 99.0)["gamma_deg"],
                             60.0)
        self.assertGreaterEqual(
            layout.v_tail_panel(0.05, 0.02, 1.0)["gamma_deg"], 10.0)

    def test_zero_areas(self):
        panel = layout.v_tail_panel(0.0, 0.0, 35.0)
        self.assertEqual(panel["s_panel_m2"], 0.0)

    def test_reports_governing_projection(self):
        tall = layout.v_tail_panel(0.02, 0.10, 35.0)
        self.assertEqual(tall["limited_by"], "вертикална")


if __name__ == "__main__":
    unittest.main()
