"""
Тестове за якостта на крилото (коренов момент, спар, карбон).
"""

import os
import sys
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import aero, materials, presets, structure  # noqa: E402


class TestRootMoment(unittest.TestCase):
    def test_hand_calculation(self):
        """m=1.2 kg, b=1.2 m, n=4 → M = 0.106·4·W·b ≈ 6.0 N·m."""
        moment = structure.root_bending_moment(1.2, 1.2, 4.0)
        self.assertAlmostEqual(moment, 5.99, delta=0.15)

    def test_moment_scales_linearly(self):
        m1 = structure.root_bending_moment(1.0, 1.0, 4.0)
        m2 = structure.root_bending_moment(2.0, 1.0, 4.0)
        m3 = structure.root_bending_moment(1.0, 1.0, 8.0)
        self.assertAlmostEqual(m2 / m1, 2.0, places=6)
        self.assertAlmostEqual(m3 / m1, 2.0, places=6)


class TestSpar(unittest.TestCase):
    def test_spar_height_uses_thickness(self):
        # 12% профил, хорда 200 mm, 85% от дебелината
        self.assertAlmostEqual(structure.spar_height_mm(200.0, 0.12), 20.4,
                               places=6)

    def test_allowable_stress_pla(self):
        pla = materials.get("pla")
        sigma = structure.allowable_print_stress_mpa(pla, 1.5)
        self.assertAlmostEqual(sigma, 50.0 * 0.65 / 1.5, places=6)

    def test_allowable_stress_drops_with_safety_factor(self):
        pla = materials.get("pla")
        self.assertAlmostEqual(
            structure.allowable_print_stress_mpa(pla, 3.0),
            structure.allowable_print_stress_mpa(pla, 1.5) / 2.0, places=6)


class TestCarbonSelection(unittest.TestCase):
    def test_picks_enough_area(self):
        carbon = structure.pick_carbon_strip(12.0)
        self.assertGreaterEqual(carbon["total_area_mm2"], 12.0)

    def test_thicker_need_less_strips(self):
        small = structure.pick_carbon_strip(3.0)
        big = structure.pick_carbon_strip(60.0)
        self.assertLess(small["count"], big["count"])

    def test_known_strip_size(self):
        carbon = structure.pick_carbon_strip(1.4)
        self.assertEqual(carbon["count"], 1)
        self.assertGreaterEqual(carbon["area_mm2"], 1.4)


class TestAnalyse(unittest.TestCase):
    def setUp(self):
        self.geom = aero.wing_geometry(0.24, 7.0, 0.75)
        self.mission = presets.mission("trainer")
        self.pla = materials.get("pla")
        self.lw = materials.get("lw_pla")

    def test_outputs_positive(self):
        st = structure.analyse(0.773, self.geom, self.lw, self.mission,
                               "naca2412")
        self.assertGreater(st["m_root_nm"], 0.0)
        self.assertGreater(st["cap_area_req_mm2"], 0.0)
        self.assertGreater(st["spar_height_mm"], 0.0)
        self.assertGreaterEqual(st["n_limit"], 1.5)

    def test_light_foaming_filament_needs_carbon_more_often(self):
        st_pla = structure.analyse(0.773, self.geom, self.pla, self.mission,
                                   "naca2412")
        st_lw = structure.analyse(0.773, self.geom, self.lw, self.mission,
                                  "naca2412")
        # LW-PLA е по-слаб → по-голяма нужна площ на капсите
        self.assertGreater(st_lw["cap_area_req_mm2"],
                           st_pla["cap_area_req_mm2"])

    def test_wall_rule(self):
        st = structure.analyse(0.773, self.geom, self.lw, self.mission,
                               "naca2412", perimeters=1, nozzle=0.4)
        # един периметър при 0.4 дюза = 0.45 mm — допустимо за vase mode
        self.assertGreaterEqual(st["wall_mm"], st["min_wall_mm"])
        self.assertTrue(st["wall_ok"])

    def test_deflection_limit_positive(self):
        st = structure.analyse(0.773, self.geom, self.lw, self.mission,
                               "naca2412")
        self.assertGreater(st["deflection_limit_mm"], 0.0)
        self.assertGreater(st["deflection_carbon_mm"], 0.0)

    def test_joiner_tube_from_standard_list(self):
        st = structure.analyse(0.773, self.geom, self.lw, self.mission,
                               "naca2412")
        sizes = [(t[0], t[1]) for t in presets.CARBON_TUBES_MM]
        self.assertIn((st["joiner_tube"]["od_mm"], st["joiner_tube"]["id_mm"]),
                      sizes)


if __name__ == "__main__":
    unittest.main()
