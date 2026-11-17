"""Витло за 3D печат от APC геометрия: разбор, маса, натоварване, STL."""

import os
import tempfile
import unittest

import _env  # noqa: F401

from core import propeller as P  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "apc")


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="latin-1") as fh:
        return fh.read()


class TestParse(unittest.TestCase):
    def test_10x6_header_and_stations(self):
        g = P.parse_geometry(_load("10x6-PERF.PE0"))
        self.assertAlmostEqual(g["radius_in"], 5.0)
        self.assertAlmostEqual(g["hub_radius_in"], 0.5)
        self.assertEqual(g["blades"], 2)
        self.assertGreater(len(g["stations"]), 40)
        self.assertTrue(all(s["r_in"] >= 0.5 for s in g["stations"]))

    def test_8x6_has_its_own_radius(self):
        g = P.parse_geometry(_load("8x6-PERF.PE0"))
        self.assertAlmostEqual(g["radius_in"], 4.0)

    def test_rejects_non_apc_text(self):
        with self.assertRaises(P.PropellerError):
            P.parse_geometry("hello world")


class TestPrintEstimate(unittest.TestCase):
    def setUp(self):
        self.g = P.parse_geometry(_load("10x6-PERF.PE0"))

    def test_volume_below_file_total_and_above_half(self):
        # Файлът дава общия обем с хъба; ние моделираме само перките.
        ours = P.blade_volume_mm3(self.g) * self.g["blades"] / 1000.0
        file_total = self.g["file_volume_in3"] * 16.387
        self.assertLess(ours, file_total)
        self.assertGreater(ours, 0.5 * file_total)

    def test_mass_scales_with_infill(self):
        full = P.estimate_print(self.g, "pla", 1.0)["mass_g"]
        half = P.estimate_print(self.g, "pla", 0.5)["mass_g"]
        self.assertAlmostEqual(half / full, 0.5, places=6)

    def test_petg_is_heavier_and_dearer_than_pla(self):
        pla = P.estimate_print(self.g, "pla")
        petg = P.estimate_print(self.g, "petg")
        self.assertGreater(petg["mass_g"], pla["mass_g"])
        self.assertGreater(petg["cost_eur"], pla["cost_eur"])

    def test_unknown_material_raises(self):
        with self.assertRaises(P.PropellerError):
            P.estimate_print(self.g, "unobtainium")


class TestLoad(unittest.TestCase):
    def setUp(self):
        self.g = P.parse_geometry(_load("10x6-PERF.PE0"))

    def test_tip_speed_formula(self):
        # 10 in диаметър, 8000 rpm → ~106 m/s
        tip = 2 * 3.141592653589793 * (5 * 0.0254) * 8000 / 60
        levels = {c["title"]: c["level"]
                  for c in P.check_flight_load(self.g, 8000, "pla")}
        self.assertAlmostEqual(tip, 106.4, delta=0.2)
        # Консервативният праг (90 m/s) предупреждава при 10" на 8000 rpm
        self.assertEqual(levels["Обиколна скорост на върха"], "warn")

    def test_low_rpm_tip_speed_is_ok(self):
        levels = {c["title"]: c["level"]
                  for c in P.check_flight_load(self.g, 5000, "pla")}
        self.assertEqual(levels["Обиколна скорост на върха"], "ok")

    def test_very_high_rpm_is_error(self):
        levels = {c["title"]: c["level"]
                  for c in P.check_flight_load(self.g, 30000, "pla")}
        self.assertEqual(levels["Обиколна скорост на върха"], "error")

    def test_stress_scales_with_rpm_squared(self):
        s1 = P.root_stress_mpa(self.g, 4000, "pla")
        s2 = P.root_stress_mpa(self.g, 8000, "pla")
        self.assertAlmostEqual(s2 / s1, 4.0, places=6)

    def test_flight_warning_is_always_present(self):
        titles = [c["title"] for c in P.check_flight_load(self.g, 6000)]
        self.assertIn("Не е проверено за полет", titles)

    def test_nonpositive_rpm_raises(self):
        with self.assertRaises(P.PropellerError):
            P.check_flight_load(self.g, 0)


class TestBedAndStl(unittest.TestCase):
    def setUp(self):
        self.g = P.parse_geometry(_load("8x6-PERF.PE0"))

    def test_fits_220_bed_and_not_small_bed(self):
        self.assertTrue(P.fits_bed(self.g, (220, 220, 250))["fits"])
        self.assertFalse(P.fits_bed(self.g, (80, 80, 80))["fits"])

    def test_stl_is_valid_binary_with_expected_count(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.stl")
            n = P.write_stl(path, self.g)
            size = os.path.getsize(path)
        self.assertEqual(size, 84 + 50 * n)
        self.assertEqual(n, len(P.blade_triangles(self.g)) * self.g["blades"])

    def test_summary_bundles_everything(self):
        out = P.summarize(_load("10x4-PERF.PE0"), 7000, "pla",
                          1.0, (220, 220, 250))
        self.assertEqual(out["blades"], 2)
        self.assertIn("estimate", out)
        self.assertTrue(out["bed"]["fits"])
        self.assertGreaterEqual(len(out["checks"]), 3)


if __name__ == "__main__":
    unittest.main()
