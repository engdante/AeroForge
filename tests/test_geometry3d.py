"""
Тестове за опростения 3D модел (geometry3d).

Проверява се, че геометрията е валидна (крайни числа, правилен размах,
симетрия) и че частите отговарят на типа модел.
"""

import json
import math
import os
import sys
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import design, geometry3d  # noqa: E402


def trainer_result(**overrides):
    inputs = {
        "mission": "trainer",
        "payload": {"mode": "simple", "total_g": 600},
        "print": {"filament": "lw_pla", "perimeters": 1, "infill": 0},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(inputs.get(key), dict):
            inputs[key].update(value)
        else:
            inputs[key] = value
    return design.compute(inputs)


class TestModelStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = trainer_result()
        cls.model = geometry3d.build_model(cls.res)

    def test_model_ok(self):
        self.assertTrue(self.model["ok"])
        self.assertEqual(self.model["units"], "mm")

    def test_parts_present(self):
        names = [p["name"] for p in self.model["parts"]]
        self.assertIn("Крило", names)
        self.assertIn("Фюзелаж", names)
        self.assertIn("Стабилизатор", names)
        self.assertIn("Кил", names)
        self.assertIn("Мотор", names)

    def test_triangle_count_reasonable(self):
        self.assertGreater(self.model["triangles"], 400)
        # бюджетът идва от нивото за качество (по подразбиране „високо“)
        self.assertLess(self.model["triangles"],
                        geometry3d.QUALITY_LEVELS["high"]["max_tris"])

    def test_points_are_complete_triangles(self):
        for part in self.model["parts"]:
            points = part["points"]
            self.assertEqual(len(points) % 9, 0, part["name"])
            self.assertEqual(len(points) // 9, part["triangles"])
            for value in points:
                self.assertTrue(math.isfinite(value), part["name"])

    def test_span_matches_design(self):
        ys = []
        for part in self.model["parts"]:
            ys.extend(part["points"][1::3])
        span = max(ys) - min(ys)
        self.assertAlmostEqual(span, self.res["geometry"]["span_mm"],
                               delta=1.0)
        self.assertAlmostEqual(self.model["size"]["span_mm"],
                               self.res["geometry"]["span_mm"], delta=1.5)

    def test_wing_is_symmetric(self):
        wing = [p for p in self.model["parts"] if p["name"] == "Крило"][0]
        ys = wing["points"][1::3]
        self.assertAlmostEqual(max(ys), -min(ys), delta=1.5)

    def test_model_is_json_serializable(self):
        text = json.dumps(self.model)
        self.assertGreater(len(text), 1000)
        self.assertLess(len(text), 2_000_000)

    def test_no_absurd_coordinates(self):
        for part in self.model["parts"]:
            points = part["points"]
            for i in range(0, len(points), 3):
                self.assertLess(abs(points[i]), 10000.0)
                self.assertLess(abs(points[i + 1]), 10000.0)
                self.assertLess(abs(points[i + 2]), 10000.0)


class TestWingTipGeometry(unittest.TestCase):
    @staticmethod
    def _tip_extent(res):
        """Ширина на последното сечение по хордата (в близост до върха)."""
        model = geometry3d.build_model(res)
        wing = [p for p in model["parts"] if p["name"] == "Крило"][0]
        xs = wing["points"][0::3]
        ys = wing["points"][1::3]
        y_max = max(ys)
        near = [x for x, y in zip(xs, ys) if y > y_max - 0.5]
        return max(near) - min(near)

    def test_rounded_tip_has_a_small_tip_chord(self):
        square = trainer_result()
        rounded = trainer_result(wing={"tip_style": "rounded"})
        self.assertLess(self._tip_extent(rounded),
                        0.75 * self._tip_extent(square))

    def test_winglet_is_a_separate_part(self):
        model = geometry3d.build_model(
            trainer_result(wing={"tip_style": "winglet",
                                 "winglet": {"enabled": True,
                                             "height_mm": 50}}))
        names = [p["name"] for p in model["parts"]]
        self.assertIn("Уинглет (дясно)", names)
        self.assertIn("Уинглет (ляво)", names)

    def test_upturned_tip_rises(self):
        def wing_top(res):
            model = geometry3d.build_model(res)
            wing = [p for p in model["parts"] if p["name"] == "Крило"][0]
            return max(wing["points"][2::3])

        flat = wing_top(trainer_result())
        bent = wing_top(trainer_result(wing={"tip_style": "upturned"}))
        self.assertGreater(bent, flat + 5.0)

    def test_winglet_keeps_the_triangle_budget(self):
        model = geometry3d.build_model(
            trainer_result(wing={"tip_style": "winglet",
                                 "winglet": {"enabled": True,
                                             "height_mm": 50}}))
        self.assertLessEqual(model["triangles"],
                             geometry3d.QUALITY_LEVELS["high"]["max_tris"])


class TestQualityLevels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = trainer_result()

    def test_levels_give_more_triangles(self):
        counts = {}
        for key in ("low", "normal", "high"):
            model = geometry3d.build_model(self.res, quality=key)
            counts[key] = model["triangles"]
            self.assertEqual(model["quality"], key)
        self.assertLess(counts["low"], counts["normal"])
        self.assertLess(counts["normal"], counts["high"])

    def test_budget_degrades_density_not_parts(self):
        model = geometry3d.build_model(self.res, max_triangles=3000)
        names = [p["name"] for p in model["parts"]]
        self.assertIn("Крило", names)
        self.assertIn("Фюзелаж", names)
        self.assertLessEqual(model["triangles"], 3000)

    def test_every_part_is_watertight_and_outward(self):
        model = geometry3d.build_model(self.res, quality="high")
        for part in model["parts"]:
            pts = part["points"]
            edges = {}
            volume = 0.0
            for i in range(0, len(pts), 9):
                tri = [(pts[i + 3 * k], pts[i + 1 + 3 * k], pts[i + 2 + 3 * k])
                       for k in range(3)]
                a, b, c = tri
                volume += (a[0] * (b[1] * c[2] - b[2] * c[1])
                           - a[1] * (b[0] * c[2] - b[2] * c[0])
                           + a[2] * (b[0] * c[1] - b[1] * c[0]))
                for p, q in ((a, b), (b, c), (c, a)):
                    key = (p, q) if p < q else (q, p)
                    edges[key] = edges.get(key, 0) + 1
            boundary = sum(1 for v in edges.values() if v == 1)
            self.assertEqual(boundary, 0, part["name"])
            self.assertGreater(volume, 0.0, part["name"])

    def test_spinner_sits_in_front_of_the_nose(self):
        model = geometry3d.build_model(self.res)
        motor = [p for p in model["parts"] if p["name"] == "Мотор"][0]
        xs = motor["points"][0::3]
        self.assertLess(min(xs), 0.0)

    def test_unknown_quality_falls_back(self):
        self.assertEqual(geometry3d.quality_of("hyper"), "high")
        self.assertEqual(geometry3d.quality_of("ultra"), "ultra")


class TestModelVariants(unittest.TestCase):
    def test_flying_wing_has_no_tail_parts(self):
        res = trainer_result(mission="flying_wing",
                             wing={"airfoil": "mh45"})
        model = geometry3d.build_model(res)
        names = [p["name"] for p in model["parts"]]
        self.assertIn("Крило", names)
        self.assertNotIn("Стабилизатор", names)
        self.assertNotIn("Кил", names)

    def test_glider_has_tail(self):
        model = geometry3d.build_model(trainer_result(mission="glider"))
        names = [p["name"] for p in model["parts"]]
        self.assertIn("Стабилизатор", names)
        self.assertIn("Кил", names)

    def test_bigger_plane_is_bigger(self):
        small = geometry3d.build_model(trainer_result(
            payload={"mode": "simple", "total_g": 400}))
        big = geometry3d.build_model(trainer_result(
            payload={"mode": "simple", "total_g": 900}))
        self.assertGreater(big["size"]["span_mm"], small["size"]["span_mm"])
        self.assertGreater(big["size"]["length_mm"],
                           small["size"]["length_mm"])

    def test_catalog_airfoil_also_works(self):
        for key in ("clarky", "s1223", "mh32"):
            model = geometry3d.build_model(trainer_result(
                wing={"airfoil": key}))
            self.assertTrue(model["ok"], key)
            self.assertGreater(model["triangles"], 400)

    def test_triangle_budget_is_respected(self):
        model = geometry3d.build_model(trainer_result(), max_triangles=200)
        self.assertLessEqual(model["triangles"], 200)

    def test_invalid_input(self):
        self.assertFalse(geometry3d.build_model(None)["ok"])
        self.assertFalse(geometry3d.build_model({"ok": False})["ok"])


if __name__ == "__main__":
    unittest.main()
