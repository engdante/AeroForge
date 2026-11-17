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

from core import assembly, design, geometry3d  # noqa: E402


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

    def test_tail_airfoil_selection_changes_3d_tail_geometry(self):
        def tail_parts(airfoil):
            result = trainer_result(tail={"airfoil": airfoil})
            model = geometry3d.build_model(result, quality="low")
            return {part["name"]: part["points"] for part in model["parts"]
                    if part["name"] in ("Стабилизатор", "Кил")}

        default_tail = tail_parts("naca0009")
        selected_tail = tail_parts("naca0012")
        self.assertEqual(set(selected_tail), set(default_tail))
        for name, points in default_tail.items():
            with self.subTest(part=name):
                self.assertNotEqual(points, selected_tail[name])

        selected_model = geometry3d.build_model(
            trainer_result(tail={"airfoil": "naca0012"}), quality="low")
        self.assertEqual(selected_model["info"]["tail_airfoil"], "NACA 0012")

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

    def test_root_gap_adds_visible_bridge_parts(self):
        model = geometry3d.build_model(
            trainer_result(layout={"root_gap_mm": 10.0}))
        names = [part["name"] for part in model["parts"]]
        self.assertIn("Крило", names)
        self.assertIn("Фюзелаж", names)
        self.assertIn("Връзки корен крило", names)
        self.assertIn("Връзки корен опашка", names)
        self.assertIn("Връзка корен кил", names)

    def test_root_gap_moves_displayed_panels_and_keeps_them_symmetric(self):
        res = trainer_result(layout={"wing_root_gap_mm": 10.0})
        model = geometry3d.build_model(res)
        wing = next(part for part in model["parts"] if part["name"] == "Крило")
        ys = wing["points"][1::3]
        half_gap = (res["geometry"]["fuselage"]["width_mm"] / 2.0 +
                    res["layout"]["wing_root_gap_mm"])
        self.assertAlmostEqual(min(ys), -res["geometry"]["span_mm"] / 2.0,
                               places=1)
        self.assertAlmostEqual(max(ys), res["geometry"]["span_mm"] / 2.0,
                               places=1)
        self.assertGreaterEqual(min(value for value in ys if value > 0),
                                half_gap)
        self.assertLessEqual(max(value for value in ys if value < 0),
                             -half_gap)

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
        spinner = [p for p in model["parts"] if p["name"] == "Спинер"][0]
        xs = spinner["points"][0::3]
        self.assertLess(min(xs), 0.0)

    def test_unknown_quality_falls_back(self):
        self.assertEqual(geometry3d.quality_of("hyper"), "high")
        self.assertEqual(geometry3d.quality_of("ultra"), "ultra")


class TestInterElementDistances(unittest.TestCase):
    """
    Регресионни тестове: разстоянията между елементите в 3D модела
    съвпадат с изчислените размери (размах, дължина, root gap).
    """

    @classmethod
    def setUpClass(cls):
        cls.res = trainer_result()
        cls.model = geometry3d.build_model(cls.res)
        cls.g = cls.res["geometry"]
        cls.fus = cls.g["fuselage"]
        cls.layout = cls.res["layout"]

    def _part_points(self, name):
        for part in self.model["parts"]:
            if part["name"] == name:
                return part["points"]
        return None

    def test_span_matches_design_in_model(self):
        """Общият размах на модела = span_mm от дизайна."""
        ys = []
        for part in self.model["parts"]:
            ys.extend(part["points"][1::3])
        span = max(ys) - min(ys)
        self.assertAlmostEqual(span, self.g["span_mm"], delta=1.0)

    def test_length_matches_design_in_model(self):
        """Дължината на модела = length_mm (± спинер)."""
        xs = []
        for part in self.model["parts"]:
            xs.extend(part["points"][0::3])
        model_length = max(xs) - min(xs)
        fus_length = self.fus["length_mm"]
        self.assertGreaterEqual(model_length, fus_length * 0.95)
        self.assertLessEqual(model_length, fus_length * 1.15)

    def _skin(self, x_mm, axis=(0.0, 1.0, 0.0)):
        return assembly.skin_offset(self.fus, x_mm, axis)

    def test_wing_root_gap_distance_is_correct(self):
        """Коренът на крилото е на локалната кожа + wing_root_gap от y=0."""
        wing_gap = float(self.layout.get("wing_root_gap_mm", 10.0))
        if wing_gap <= 0:
            self.skipTest("wing_root_gap е 0")
        expected_root_y = self._skin(self.g["wing_le_mm"]) + wing_gap
        wing_pts = self._part_points("Крило")
        if wing_pts is None:
            self.fail("Няма част 'Крило'")
        ys = wing_pts[1::3]
        pos = [y for y in ys if y > 0]
        neg = [y for y in ys if y < 0]
        self.assertAlmostEqual(min(pos), expected_root_y, delta=1.0)
        self.assertAlmostEqual(max(neg), -expected_root_y, delta=1.0)

    def test_wing_bridge_spans_the_gap(self):
        """Мостът запълва от локалната кожа -3 до кожа + gap + 3."""
        wing_gap = float(self.layout.get("wing_root_gap_mm", 10.0))
        if wing_gap <= 0:
            self.skipTest("wing_root_gap е 0")
        skin = self._skin(self.g["wing_le_mm"])
        bridge_pts = self._part_points("Връзки корен крило")
        if bridge_pts is None:
            self.fail("Няма част 'Връзки корен крило'")
        ys = bridge_pts[1::3]
        min_abs = min(abs(y) for y in ys)
        max_abs = max(abs(y) for y in ys)
        self.assertAlmostEqual(min_abs, skin - 3.0, delta=1.0)
        self.assertAlmostEqual(max_abs, skin + wing_gap + 3.0, delta=1.0)

    def test_tail_root_gap_distance_is_correct(self):
        """Коренът на стабилизатора е на локалната кожа + tail_gap от y=0."""
        tail_type = self.layout.get("tail_type", "conventional")
        if tail_type != "conventional":
            self.skipTest("Не е конвенционална опашка")
        tail_gap = float(self.layout.get("tail_root_gap_mm", 10.0))
        if tail_gap <= 0:
            self.skipTest("tail_root_gap е 0")
        tail = self.g["tail"]
        x_h = max(self.g["wing_le_mm"] + self.g["c_root_mm"],
                  tail["tail_ac_mm"] - 0.25 * tail["c_h_mm"])
        x_h = min(x_h, max(0.0, self.fus["length_mm"] - tail["c_h_mm"]))
        expected_root_y = self._skin(x_h) + tail_gap
        stab_pts = self._part_points("Стабилизатор")
        if stab_pts is None:
            self.fail("Няма част 'Стабилизатор'")
        ys = stab_pts[1::3]
        pos = [y for y in ys if y > 0]
        neg = [y for y in ys if y < 0]
        self.assertAlmostEqual(min(pos), expected_root_y, delta=1.5)
        self.assertAlmostEqual(max(neg), -expected_root_y, delta=1.5)

    def test_tail_bridge_spans_the_gap(self):
        """Мостът на опашката запълва пропаста от кожата до панела."""
        tail_type = self.layout.get("tail_type", "conventional")
        if tail_type != "conventional":
            self.skipTest("Не е конвенционална опашка")
        tail_gap = float(self.layout.get("tail_root_gap_mm", 10.0))
        if tail_gap <= 0:
            self.skipTest("tail_root_gap е 0")
        tail = self.g["tail"]
        x_h = max(self.g["wing_le_mm"] + self.g["c_root_mm"],
                  tail["tail_ac_mm"] - 0.25 * tail["c_h_mm"])
        x_h = min(x_h, max(0.0, self.fus["length_mm"] - tail["c_h_mm"]))
        skin = self._skin(x_h)
        bridge_pts = self._part_points("Връзки корен опашка")
        if bridge_pts is None:
            self.fail("Няма част 'Връзки корен опашка'")
        ys = bridge_pts[1::3]
        min_abs = min(abs(y) for y in ys)
        max_abs = max(abs(y) for y in ys)
        self.assertAlmostEqual(min_abs, skin - 3.0, delta=1.0)
        self.assertAlmostEqual(max_abs, skin + tail_gap + 3.0, delta=1.0)

    def test_wing_tip_reaches_full_span(self):
        """Крайчетата на крилото достигат ±span/2."""
        half_span = self.g["span_mm"] / 2.0
        wing_pts = self._part_points("Крило")
        if wing_pts is None:
            self.fail("Няма част 'Крило'")
        ys = wing_pts[1::3]
        self.assertAlmostEqual(max(ys), half_span, delta=1.0)
        self.assertAlmostEqual(min(ys), -half_span, delta=1.0)


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
