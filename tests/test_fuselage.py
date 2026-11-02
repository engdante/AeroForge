"""
Тестове за параметричната геометрия на фюзелажа (fuselage.py).

Проверява се, че формата е непрекъсната, че площта/обемът са разумни,
че обхватът за батерията е вътре в тялото и че стойностите по подразбиране
възпроизвеждат формата от v0.2.
"""

import math
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import fuselage, weight  # noqa: E402


def make(length=1000.0, width=60.0, height=75.0, **params):
    return fuselage.resolve(1250.0, 0.8, 110.0,
                            dict({"length_mm": length, "width_mm": width,
                                  "height_mm": height}, **params),
                            default_ratio=0.75)


class TestRadiusFactor(unittest.TestCase):
    def test_default_shape_matches_v02(self):
        """Формата по подразбиране е същата като твърдо закодираната."""
        self.assertAlmostEqual(fuselage.radius_factor(0.0), 0.05, places=9)
        self.assertAlmostEqual(fuselage.radius_factor(0.14), 1.0, places=9)
        self.assertAlmostEqual(fuselage.radius_factor(0.40), 1.0, places=9)
        expected = 1.0 - 0.62 * (((0.71 - 0.42) / 0.58) ** 1.25)
        self.assertAlmostEqual(fuselage.radius_factor(0.71), expected,
                               places=9)
        self.assertAlmostEqual(fuselage.radius_factor(1.0), 0.38, places=9)

    def test_nose_grows(self):
        values = [fuselage.radius_factor(t) for t in
                  (0.0, 0.02, 0.05, 0.10, 0.13)]
        for a, b in zip(values, values[1:]):
            self.assertLess(a, b)

    def test_tail_taper_controls_end(self):
        self.assertAlmostEqual(
            fuselage.radius_factor(1.0, tail_taper=0.25), 0.25, places=9)
        self.assertAlmostEqual(
            fuselage.radius_factor(1.0, tail_taper=0.9), 0.9, places=9)

    def test_radius_is_bounded(self):
        for i in range(101):
            value = fuselage.radius_factor(i / 100.0)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)


class TestSections(unittest.TestCase):
    def test_outline_is_centered(self):
        fus = make()
        pts = fuselage.outline(fus, 0.3, 24)
        self.assertEqual(len(pts), 24)
        ys = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        self.assertAlmostEqual(sum(ys) / len(ys), 0.0, places=6)
        self.assertAlmostEqual(sum(zs) / len(zs), 0.0, places=6)

    def test_section_scales_with_radius(self):
        fus = make()
        w_full, h_full = fuselage.section(fus, 0.3)
        w_tail, h_tail = fuselage.section(fus, 1.0)
        self.assertAlmostEqual(w_full, 60.0, places=6)
        self.assertAlmostEqual(h_full, 75.0, places=6)
        self.assertAlmostEqual(w_tail, 60.0 * 0.38, delta=0.1)
        self.assertAlmostEqual(h_tail, 75.0 * 0.38, delta=0.1)

    def test_perimeter_matches_ramanujan_for_ellipse(self):
        fus = make(width=50.0, height=70.0)
        per = fuselage.perimeter(fus, 0.3, 128)
        a, b = 25.0, 35.0
        ram = math.pi * (3.0 * (a + b)
                         - math.sqrt((3.0 * a + b) * (a + 3.0 * b)))
        self.assertAlmostEqual(per, ram, delta=0.01 * ram)

    def test_boxy_section_is_bigger(self):
        ellipse = make(shape="ellipse")
        boxy = make(shape="boxy")
        self.assertGreater(fuselage.perimeter(boxy, 0.3, 64),
                           fuselage.perimeter(ellipse, 0.3, 64))
        self.assertGreater(fuselage.section_area(boxy, 0.3, 64),
                           fuselage.section_area(ellipse, 0.3, 64))


class TestBodyMetrics(unittest.TestCase):
    def test_wetted_area_is_smaller_than_constant_section(self):
        """Стесняването към опашката намалява площта (v0.2 я надценяваше)."""
        fus = make()
        full = fuselage.perimeter(fus, 0.3) * fus["length_mm"]
        self.assertLess(fus["wetted_area_mm2"], 0.95 * full)
        self.assertGreater(fus["wetted_area_mm2"], 0.5 * full)

    def test_area_grows_with_size(self):
        small = make(width=50.0, height=60.0)
        big = make(width=80.0, height=95.0)
        self.assertGreater(big["wetted_area_mm2"], small["wetted_area_mm2"])

    def test_volume_grows(self):
        small = make(width=50.0, height=60.0)
        big = make(width=80.0, height=95.0)
        self.assertGreater(small["volume_cm3"], 0.0)
        self.assertGreater(big["volume_cm3"], small["volume_cm3"])

    def test_slenderness(self):
        fus = make(length=1000.0, width=60.0, height=75.0)
        self.assertAlmostEqual(fus["slenderness"],
                               1000.0 / math.sqrt(60.0 * 75.0), places=6)


class TestStations(unittest.TestCase):
    def test_stations_cover_length(self):
        fus = make(length=1000.0)
        parts = fuselage.stations(fus, 250.0)
        self.assertEqual(len(parts), 4)
        self.assertAlmostEqual(parts[0]["x0_mm"], 0.0, places=6)
        self.assertAlmostEqual(parts[-1]["x1_mm"], 1000.0, places=6)
        for part in parts:
            self.assertLessEqual(part["x1_mm"] - part["x0_mm"], 250.0 + 1e-6)

    def test_short_body_is_one_piece(self):
        fus = make(length=200.0)
        self.assertEqual(len(fuselage.stations(fus, 250.0)), 1)


class TestBatteryBay(unittest.TestCase):
    def test_bay_is_inside_body(self):
        fus = make()
        bay = fus["battery_bay_mm"]
        self.assertIsNotNone(bay)
        self.assertGreaterEqual(bay[0], 0.0)
        self.assertLessEqual(bay[1], fus["length_mm"])

    def test_bigger_battery_has_smaller_bay(self):
        fus = make()
        small = fuselage.bay_limits(fus, [80.0, 35.0, 25.0])
        big = fuselage.bay_limits(fus, [80.0, 55.0, 40.0])
        self.assertIsNotNone(small)
        if big is not None:
            self.assertLessEqual(big[1] - big[0], small[1] - small[0] + 1e-6)

    def test_no_room_returns_none(self):
        fus = make(width=40.0, height=45.0)
        self.assertIsNone(fuselage.bay_limits(fus, [60.0, 90.0, 50.0]))


class TestResolve(unittest.TestCase):
    def test_auto_uses_mission_ratio(self):
        fus = fuselage.resolve(1200.0, 0.8, 110.0, None, default_ratio=0.75)
        self.assertAlmostEqual(fus["length_mm"], 900.0, delta=1.0)
        self.assertAlmostEqual(fus["auto"]["length_mm"], 900.0, delta=1.0)

    def test_auto_matches_weight_function(self):
        fus = fuselage.resolve(1200.0, 0.8, 110.0, None, default_ratio=0.75)
        ref = weight.fuselage_dimensions(110.0, 0.8, 900.0)
        self.assertAlmostEqual(fus["width_mm"], round(ref["width_mm"], 1))
        self.assertAlmostEqual(fus["height_mm"], round(ref["height_mm"], 1))

    def test_overrides_are_respected(self):
        fus = make(length=800.0, width=70.0, height=80.0, shape="boxy",
                   nose_ratio=0.20, cabin_ratio=0.50, tail_taper=0.30,
                   frames=4)
        self.assertAlmostEqual(fus["length_mm"], 800.0, places=1)
        self.assertAlmostEqual(fus["width_mm"], 70.0, places=1)
        self.assertAlmostEqual(fus["height_mm"], 80.0, places=1)
        self.assertEqual(fus["shape"], "boxy")
        self.assertAlmostEqual(fus["nose_ratio"], 0.20, places=6)
        self.assertEqual(fus["frames"], 4)
        self.assertTrue(fus["manual"]["length"])

    def test_values_are_clamped(self):
        fus = make(length=10.0, width=1.0, height=1.0, nose_ratio=9.0,
                   cabin_ratio=-3.0, tail_taper=9.0, frames=99)
        self.assertGreaterEqual(fus["length_mm"], 120.0)
        self.assertGreaterEqual(fus["width_mm"], 20.0)
        self.assertLessEqual(fus["nose_ratio"], 0.35)
        self.assertGreater(fus["cabin_ratio"], fus["nose_ratio"])
        self.assertLessEqual(fus["tail_taper"], 0.95)
        self.assertEqual(fus["frames"], 12)

    def test_unknown_shape_falls_back(self):
        self.assertEqual(make(shape="triangle")["shape"], "ellipse")

    def test_battery_fits_flag(self):
        """Много голяма батерия в късо тяло не се побира по дължина."""
        fus = fuselage.resolve(1250.0, 0.8, 1200.0,
                               {"length_mm": 200.0, "width_mm": 90.0,
                                "height_mm": 110.0}, default_ratio=0.75)
        self.assertFalse(fus["battery_fits"])


if __name__ == "__main__":
    unittest.main()
