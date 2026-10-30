"""
Тестове за модела на печат (маса, филамент, време, цена).
"""

import math
import os
import sys
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import materials, printcost  # noqa: E402


class TestGeometryOfPrint(unittest.TestCase):
    def test_extrusion_width(self):
        self.assertAlmostEqual(printcost.extrusion_width(0.4), 0.45, places=6)
        self.assertAlmostEqual(printcost.extrusion_width(0.6), 0.675, places=6)

    def test_wall_thickness(self):
        self.assertAlmostEqual(printcost.wall_thickness(2, 0.4), 0.9, places=6)
        self.assertAlmostEqual(printcost.wall_thickness(1, 0.4), 0.45,
                               places=6)

    def test_internal_factor_grows(self):
        vase = printcost.internal_factor(1, 0)
        solid = printcost.internal_factor(3, 40)
        self.assertLess(vase, solid)
        self.assertGreater(vase, 0.0)
        self.assertLessEqual(solid, 0.6)

    def test_filament_length_known_value(self):
        """100 g PLA (1.24 g/cm³) ≈ 33.5 m филамент 1.75 mm."""
        length = printcost.filament_length_m(100000.0 / 1.24, 1.0)
        self.assertAlmostEqual(length, 33.5, delta=0.6)

    def test_lw_pla_consumes_more_filament(self):
        vase = printcost.filament_length_m(1000.0, 1.0)
        foaming = printcost.filament_length_m(1000.0, 1.55)
        self.assertAlmostEqual(foaming / vase, 1.55, places=6)


class TestPart(unittest.TestCase):
    def setUp(self):
        self.cfg = {"nozzle": 0.4, "perimeters": 1, "infill": 0,
                    "layer_height": 0.2, "bed": [220, 220, 250]}
        self.lw = materials.get("lw_pla")
        self.pla = materials.get("pla")

    def test_cube_like_part_mass(self):
        """
        20×20×20 mm куб: площ 2400 mm², стена 0.45 mm.
        Аналитичната стена е ~1971 mm³; моделът дава +8% за вътрешност,
        затова допускаме 25% разлика.
        """
        part = printcost._make_part("куб", 2400.0, 20.0, 1, self.cfg, self.pla)
        analytic_shell = 20 ** 3 - (20 - 2 * 0.45) ** 3
        self.assertAlmostEqual(part["volume_cm3"] * 1000.0, analytic_shell,
                               delta=0.25 * analytic_shell)

    def test_mass_matches_volume(self):
        part = printcost._make_part("тест", 10000.0, 50.0, 1, self.cfg, self.pla)
        expected = part["volume_cm3"] * self.pla["printed_density"]
        self.assertAlmostEqual(part["mass_g"], expected, places=6)

    def test_lw_pla_is_lighter_same_volume(self):
        a = printcost._make_part("a", 10000.0, 50.0, 1, self.cfg, self.pla)
        b = printcost._make_part("a", 10000.0, 50.0, 1, self.cfg, self.lw)
        self.assertLess(b["mass_g"], a["mass_g"])
        self.assertGreater(b["filament_m"], a["filament_m"])

    def test_time_and_cost_positive(self):
        part = printcost._make_part("тест", 50000.0, 200.0, 2, self.cfg,
                                    self.lw)
        self.assertGreater(part["time_h"], 0.0)
        self.assertGreater(part["cost"], 0.0)
        self.assertEqual(part["pieces"], 2)


class TestAirframeEstimate(unittest.TestCase):
    def test_estimate_returns_parts(self):
        from core import aero
        geom = aero.wing_geometry(0.24, 7.0, 0.75)
        tail = aero.tail_areas(0.24, geom["span_m"], geom["mac_m"], 0.9, 0.62,
                               0.55, 0.035)
        fus = {"width_mm": 50.0, "height_mm": 62.0, "length_mm": 900.0,
               "battery_fits": True}
        cfg = {"nozzle": 0.4, "perimeters": 1, "infill": 0,
               "layer_height": 0.2, "bed": [220, 220, 250]}
        parts = printcost.estimate_airframe(geom, tail, fus, cfg,
                                            materials.get("lw_pla"))
        self.assertGreaterEqual(len(parts), 3)
        names = " ".join(p["name"] for p in parts)
        self.assertIn("Крило", names)
        self.assertIn("Фюзелаж", names)
        for part in parts:
            self.assertGreater(part["mass_g"], 0.0)
            self.assertGreaterEqual(part["pieces"], 1)

    def test_smaller_bed_more_pieces(self):
        from core import aero
        geom = aero.wing_geometry(0.44, 7.0, 0.75)
        tail = {"s_h_m2": 0.0, "s_v_m2": 0.0}
        fus = {"width_mm": 50.0, "height_mm": 62.0, "length_mm": 900.0}
        big = printcost.estimate_airframe(
            geom, tail, fus,
            {"nozzle": 0.4, "perimeters": 1, "infill": 0,
             "layer_height": 0.2, "bed": [400, 400, 400]},
            materials.get("lw_pla"))
        small = printcost.estimate_airframe(
            geom, tail, fus,
            {"nozzle": 0.4, "perimeters": 1, "infill": 0,
             "layer_height": 0.2, "bed": [180, 180, 180]},
            materials.get("lw_pla"))
        self.assertGreater(sum(p["pieces"] for p in small),
                           sum(p["pieces"] for p in big))

    def test_summarize(self):
        parts = [
            {"name": "a", "mass_g": 10.0, "filament_m": 3.0, "time_h": 1.0,
             "cost": 1.0, "pieces": 1, "volume_cm3": 8.0},
            {"name": "b", "mass_g": 5.0, "filament_m": 1.5, "time_h": 0.5,
             "cost": 0.5, "pieces": 2, "volume_cm3": 4.0},
        ]
        total = printcost.summarize(parts)
        self.assertAlmostEqual(total["total_mass_g"], 15.0)
        self.assertAlmostEqual(total["time_h"], 1.5)
        self.assertEqual(total["pieces"], 3)


if __name__ == "__main__":
    unittest.main()
