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
        self.assertLess(self.model["triangles"], 6000)

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
