"""
Тестове за аеродинамиката — формулите се проверяват с ръчни изчисления.
"""

import math
import os
import sys
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import aero  # noqa: E402


class TestWingGeometry(unittest.TestCase):
    def test_span_from_area_and_ar(self):
        g = aero.wing_geometry(0.24, 7.0, 0.75)
        self.assertAlmostEqual(g["span_m"], math.sqrt(7.0 * 0.24), places=6)
        self.assertAlmostEqual(g["area_dm2"], 24.0, places=6)

    def test_root_and_tip_chord(self):
        g = aero.wing_geometry(0.30, 7.0, 0.75)
        # c_root = 2S / (b·(1+λ))
        expected = 2 * 0.30 / (g["span_m"] * 1.75)
        self.assertAlmostEqual(g["c_root_m"], expected, places=9)
        self.assertAlmostEqual(g["c_tip_m"], 0.75 * expected, places=9)

    def test_mean_aerodynamic_chord(self):
        g = aero.wing_geometry(0.30, 7.0, 1.0)
        # при λ=1 MAC = c_root
        self.assertAlmostEqual(g["mac_m"], g["c_root_m"], places=9)
        g2 = aero.wing_geometry(0.30, 7.0, 0.4)
        self.assertGreater(g2["mac_m"], g2["c_tip_m"])
        self.assertLess(g2["mac_m"], g2["c_root_m"])

    def test_wing_loading_roundtrip(self):
        self.assertAlmostEqual(aero.wing_loading_g_dm2(1200, 0.30), 40.0,
                               places=6)
        area = aero.area_from_wing_loading(1200, 40.0)
        self.assertAlmostEqual(area, 0.30, places=9)


class TestSpeeds(unittest.TestCase):
    def test_stall_speed_hand_calc(self):
        """m=1.2 kg, S=0.30 m², CL=1.4 → 6.76 m/s."""
        v = aero.stall_speed(1.2, 0.30, 1.4)
        self.assertAlmostEqual(v, 6.763, delta=0.02)

    def test_stall_analysis_reduces_cl(self):
        res = aero.stall_analysis(1.2, 0.15, 0.15, 1.4)
        self.assertLessEqual(res["cl_max"], 1.4)
        self.assertGreater(res["cl_max"], 1.4 * 0.85)
        self.assertGreater(res["v_stall_ms"], 0.0)

    def test_reynolds(self):
        re = aero.reynolds(10.0, 0.2)
        self.assertAlmostEqual(re, 10.0 * 0.2 / 1.5e-5, places=1)
        self.assertEqual(aero.reynolds(10.0, 0.0), 0.0)

    def test_fuselage_length(self):
        self.assertAlmostEqual(aero.fuselage_length(1.2, 0.75), 0.9, places=9)


class TestPolar(unittest.TestCase):
    def test_cd0_at_zero_lift(self):
        self.assertAlmostEqual(aero.drag_polar(0.0, 7.0, 0.75, 0.032), 0.032,
                               places=9)

    def test_induced_drag_grows_with_cl(self):
        low = aero.drag_polar(0.2, 7.0, 0.75, 0.032)
        high = aero.drag_polar(1.0, 7.0, 0.75, 0.032)
        self.assertGreater(high, low)

    def test_best_ld_matches_theory(self):
        ar, e, cd0 = 7.0, 0.75, 0.032
        ld, cl = aero.best_ld(ar, e, cd0)
        k = math.pi * ar * e
        self.assertAlmostEqual(cl, math.sqrt(cd0 * k), places=9)
        # L/D_max = √(π·AR·e/CD0) / 2
        self.assertAlmostEqual(ld, math.sqrt(k / cd0) / 2.0, places=9)
        # L/D при оптималния CL трябва да съвпада
        self.assertAlmostEqual(cl / aero.drag_polar(cl, ar, e, cd0), ld,
                               places=6)
        # разумна стойност за RC модел
        self.assertGreater(ld, 5.0)
        self.assertLess(ld, 40.0)

    def test_lift_slope_between_2d_and_finite(self):
        slope = aero.lift_slope(7.0)
        self.assertLess(slope, aero.CL_ALPHA_2D)
        self.assertGreater(slope, 3.0)

    def test_level_flight_power_positive(self):
        res = aero.level_flight(1.2, 0.30, 7.0, 0.75, 0.032, 11.0, 0.55)
        self.assertGreater(res["p_shaft_w"], 0.0)
        self.assertGreater(res["drag_n"], 0.0)
        self.assertGreater(res["cl"], 0.0)

    def test_speed_sweep_lengths(self):
        sweep = aero.speed_sweep(1.2, 0.30, 7.0, 0.75, 0.032, 6.0, 20.0, 12,
                                 0.55, 200.0, 1.4)
        self.assertEqual(len(sweep["v"]), 12)
        self.assertEqual(len(sweep["p_req"]), 12)
        # при ниска скорост CL > CL_max → стойността е None
        self.assertIsNone(sweep["ld"][0])
        self.assertEqual(sweep["p_avail"][0], 200.0)


class TestTail(unittest.TestCase):
    def test_tail_volumes(self):
        res = aero.tail_areas(0.30, 1.2, 0.20, 0.9, 0.6, 0.5, 0.04)
        # S_h = V_h·S·MAC / l_h
        self.assertAlmostEqual(res["s_h_m2"], 0.5 * 0.30 * 0.20 / (0.6 * 0.9),
                               places=9)
        # S_v = V_v·S·b / l_v   (l_v = 0.92·L)
        self.assertAlmostEqual(res["s_v_m2"],
                               0.04 * 0.30 * 1.2 / (0.92 * 0.9), places=9)

    def test_flying_wing_has_no_tail(self):
        res = aero.tail_areas(0.30, 1.2, 0.20, 0.9, 0.6, 0.0, 0.0)
        self.assertEqual(res["s_h_m2"], 0.0)
        self.assertEqual(res["s_v_m2"], 0.0)


if __name__ == "__main__":
    unittest.main()
