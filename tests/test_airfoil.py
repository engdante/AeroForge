"""
Тестове за геометрията на профилите (NACA 4-цифрен генератор).
"""

import math
import os
import sys
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import airfoils  # noqa: E402


class TestNacaParsing(unittest.TestCase):
    def test_parse_2412(self):
        m, p, t = airfoils.parse_naca("2412")
        self.assertAlmostEqual(m, 0.02, places=6)
        self.assertAlmostEqual(p, 0.40, places=6)
        self.assertAlmostEqual(t, 0.12, places=6)

    def test_parse_symmetric(self):
        m, p, t = airfoils.parse_naca("0012")
        self.assertAlmostEqual(m, 0.0)
        self.assertAlmostEqual(t, 0.12)

    def test_invalid_code(self):
        with self.assertRaises(ValueError):
            airfoils.parse_naca("abc")


class TestNacaShape(unittest.TestCase):
    def test_thickness_2412(self):
        """NACA 2412 трябва да е ~12% дебел, максимумът около 30% от хордата."""
        thickness, x_at = airfoils.measured_thickness("2412")
        self.assertAlmostEqual(thickness, 0.12, delta=0.005)
        self.assertGreater(x_at, 0.25)
        self.assertLess(x_at, 0.35)

    def test_thickness_0012(self):
        thickness, x_at = airfoils.measured_thickness("0012")
        self.assertAlmostEqual(thickness, 0.12, delta=0.004)
        self.assertGreater(x_at, 0.25)
        self.assertLess(x_at, 0.35)

    def test_camber_2412(self):
        """Максималната камера е 2% на 40% от хордата."""
        yc, _ = airfoils.naca_camber(0.40, 0.02, 0.40)
        self.assertAlmostEqual(yc, 0.02, delta=1e-6)
        # в краищата камерата е нула
        self.assertAlmostEqual(airfoils.naca_camber(0.0, 0.02, 0.4)[0], 0.0)
        self.assertAlmostEqual(airfoils.naca_camber(1.0, 0.02, 0.4)[0], 0.0)

    def test_symmetric_has_zero_camber(self):
        for x in (0.1, 0.3, 0.5, 0.8):
            self.assertAlmostEqual(airfoils.naca_camber(x, 0.0, 0.0)[0], 0.0)

    def test_closed_trailing_edge(self):
        coords = airfoils.naca_coordinates("4412", 81)
        upper_te = coords["upper"][-1]
        lower_te = coords["lower"][-1]
        self.assertAlmostEqual(upper_te[0], 1.0, places=6)
        self.assertAlmostEqual(upper_te[1], lower_te[1], places=6)

    def test_loop_is_closed(self):
        loop = airfoils.naca_coordinates("2412", 61)["loop"]
        self.assertEqual(len(loop), 2 * 61 - 2)
        first, last = loop[0], loop[-1]
        # контурът започва и завършва при водещия ръб (в рамките на стъпката)
        self.assertLess(abs(first[0] - last[0]), 0.01)
        self.assertLess(abs(first[1] - last[1]), 0.01)
        self.assertAlmostEqual(max(p[0] for p in loop), 1.0, places=6)

    def test_upper_above_lower(self):
        coords = airfoils.naca_coordinates("2412", 61)
        for (xu, yu), (xl, yl) in zip(coords["upper"], coords["lower"]):
            self.assertGreater(yu + 1e-9, yl, "горната повърхност е под долната")

    def test_all_catalog_naca_generate(self):
        for key, af in airfoils.AIRFOILS.items():
            if not af["has_coords"]:
                continue
            coords = airfoils.naca_coordinates(af["code"], 31)
            self.assertEqual(len(coords["upper"]), 31, key)


class TestCatalog(unittest.TestCase):
    def test_clmax_re_correction(self):
        self.assertAlmostEqual(airfoils.clmax_at_re(1.4, 300000), 1.4)
        self.assertAlmostEqual(airfoils.clmax_at_re(1.4, 50000), 1.4 * 0.88)
        mid = airfoils.clmax_at_re(1.4, 125000)
        self.assertGreater(mid, 1.4 * 0.88)
        self.assertLess(mid, 1.4)

    def test_unknown_key_falls_back(self):
        af = airfoils.get("nope")
        self.assertEqual(af["key"], airfoils.DEFAULT_AIRFOIL)

    def test_thickness_of_tail_airfoil(self):
        self.assertAlmostEqual(airfoils.thickness_of("naca0009"), 0.09,
                               places=6)
        self.assertGreater(airfoils.thickness_of("clarky"), 0.10)

    def test_reflexed_detection(self):
        self.assertTrue(airfoils.is_reflexed("mh45"))
        self.assertFalse(airfoils.is_reflexed("naca2412"))


if __name__ == "__main__":
    unittest.main()
