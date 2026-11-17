"""Натиск и локално изкълчване на печатания капс (structure.py)."""

import math
import unittest

import _env  # noqa: F401

from core import structure  # noqa: E402


class TestPlateBuckling(unittest.TestCase):
    def test_formula_matches_hand_calculation(self):
        # k=4, E=2800 MPa, t=0.45 mm, b=30 mm, ν=0.3
        expected = (4 * math.pi ** 2 * 2800 / (12 * (1 - 0.09))
                    * (0.45 / 30) ** 2)
        self.assertAlmostEqual(
            structure.plate_buckling_stress_mpa(30, 0.45, 2800), expected,
            places=9)

    def test_thicker_cap_buckles_at_higher_stress(self):
        thin = structure.plate_buckling_stress_mpa(30, 0.45, 2800)
        thick = structure.plate_buckling_stress_mpa(30, 0.9, 2800)
        # σ_cr ~ (t/b)² → удвояване на t учетворява σ_cr
        self.assertAlmostEqual(thick / thin, 4.0, places=6)

    def test_zero_geometry_returns_zero(self):
        self.assertEqual(structure.plate_buckling_stress_mpa(0, 1, 2800), 0.0)


class TestStructureKeys(unittest.TestCase):
    def test_analyse_reports_compression_and_buckling(self):
        from core import design
        res = design.compute({"name": "t", "mission": "trainer",
                              "payload": {"mode": "simple",
                                          "total_g": 600}})
        st = res["structure"]
        for key in ("cap_load_n", "cap_compression_mpa",
                    "buckling_stress_mpa", "compression_ok",
                    "buckling_ok"):
            self.assertIn(key, st)
        self.assertGreater(st["buckling_stress_mpa"], 0.0)


if __name__ == "__main__":
    unittest.main()


class TestCapThickening(unittest.TestCase):
    def test_cap_thickens_until_buckling_passes(self):
        from core import design
        res = design.compute({"name": "t", "mission": "trainer",
                              "payload": {"mode": "simple", "total_g": 600},
                              "print": {"filament": "lw_pla"}})
        st = res["structure"]
        self.assertTrue(st["cap_thickened"])
        self.assertTrue(st["buckling_ok"])
        self.assertTrue(st["compression_ok"])
        self.assertGreater(st["wall_mm"], 0.45)
        self.assertLessEqual(st["wall_mm"], structure.CAP_MAX_THICKNESS_MM)

    def test_thickened_cap_adds_mass(self):
        from core import design
        res = design.compute({"name": "t", "mission": "trainer",
                              "payload": {"mode": "simple", "total_g": 600},
                              "print": {"filament": "lw_pla"}})
        self.assertGreater(res["structure"]["cap_extra_g"], 0.0)

    def test_no_thickening_when_cap_already_passes(self):
        fil = {"e_mpa": 2800.0, "printed_density": 1.0}
        wall, changed, ok = structure.thicken_cap(
            1.0, 30.0, 40.0, 0.001, 5.0, 2.0, fil)
        self.assertEqual(wall, 1.0)
        self.assertFalse(changed)
        self.assertTrue(ok)
