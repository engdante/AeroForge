"""
Тестове за печатаемата геометрия (printgeom.py).

Проверява се това, което чупи слайсера: затворен обем (всеки ръб 2 пъти),
положителен обем, разумна дебелина на стената, габарити и план за печат.
"""

import json
import math
import os
import shutil
import tempfile
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import design, printgeom, report  # noqa: E402

BED = [220.0, 220.0, 250.0]


def result(**overrides):
    inputs = {"mission": "trainer",
              "payload": {"mode": "simple", "total_g": 600},
              "print": {"filament": "lw_pla", "perimeters": 1, "infill": 0,
                        "nozzle": 0.4, "bed": BED}}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(inputs.get(key), dict):
            inputs[key] = dict(inputs[key], **value)
        else:
            inputs[key] = value
    return design.compute(inputs)


class TestMeshBasics(unittest.TestCase):
    def test_box_volume(self):
        box = [[(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)],
               [(0, 0, 100), (10, 0, 100), (10, 10, 100), (0, 10, 100)]]
        mesh = printgeom.prism(box)
        self.assertAlmostEqual(mesh.volume(), 10000.0, delta=1e-6)
        self.assertTrue(mesh.is_manifold()[0])
        # 4 страни × 2 + 2 капачки с ветрило × 4 триъгълника
        self.assertEqual(mesh.triangles(), 16)

    def test_shell_matches_cylinder_volume(self):
        def circle(r, z, n=32):
            return [(r * math.cos(2 * math.pi * i / n),
                     r * math.sin(2 * math.pi * i / n), z)
                    for i in range(n)]

        mesh = printgeom.loft_shell([circle(10, 0), circle(10, 100)],
                                    [circle(9, 0), circle(9, 100)])
        expected = math.pi * (10 ** 2 - 9 ** 2) * 100
        self.assertAlmostEqual(mesh.volume(), expected, delta=0.03 * expected)
        self.assertTrue(mesh.is_manifold()[0])

    def test_to_bed_moves_to_origin(self):
        mesh = printgeom.loft_shell(
            [[(5, 5, -5), (15, 5, -5), (15, 15, -5), (5, 15, -5)],
             [(5, 5, 5), (15, 5, 5), (15, 15, 5), (5, 15, 5)]],
            [[(6, 6, -5), (14, 6, -5), (14, 14, -5), (6, 14, -5)],
             [(6, 6, 5), (14, 6, 5), (14, 14, 5), (6, 14, 5)]])
        mesh.to_bed()
        x0, y0, z0, _, _, _ = mesh.bbox()
        self.assertAlmostEqual(x0, 0.0, places=9)
        self.assertAlmostEqual(y0, 0.0, places=9)
        self.assertAlmostEqual(z0, 0.0, places=9)


class TestAirfoilOutline(unittest.TestCase):
    def test_outline_is_closed_and_ccw(self):
        pts = printgeom.airfoil_outline("naca2412", 16, min_edge_mm=0.6,
                                        chord_mm=200.0)
        self.assertGreater(len(pts), 10)
        self.assertGreater(printgeom._signed_area(pts), 0.0)
        self.assertGreater(min(p[0] for p in pts), -1e-9)
        self.assertLessEqual(max(p[0] for p in pts), 1.0 + 1e-9)

    def test_trailing_edge_has_minimum_thickness(self):
        chord = 200.0
        pts = printgeom.airfoil_outline("naca0009", 16, min_edge_mm=0.8,
                                        chord_mm=chord)
        x_max = max(p[0] for p in pts)
        near = [p[1] for p in pts if abs(p[0] - x_max) < 1e-6]
        self.assertGreaterEqual(max(near) - min(near), 0.8 / chord - 1e-9)

    def test_offset_stays_inside(self):
        unit = printgeom.airfoil_outline("naca2412", 16, min_edge_mm=0.6,
                                         chord_mm=200.0)
        pts = [(x * 200.0, y * 200.0) for (x, y) in unit]
        inner = printgeom.offset_inward(pts, 0.5)
        self.assertLess(abs(printgeom._signed_area(inner)),
                        abs(printgeom._signed_area(pts)))
        self.assertEqual(len(inner), len(pts))


class TestWing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.g = cls.res["geometry"]
        cls.st = cls.res["structure"]
        cls.halph = printgeom.lifting_surface(
            cls.g["c_root_mm"], cls.g["c_tip_mm"], cls.g["span_mm"] / 2.0,
            cls.g["airfoil"]["key"], cls.st["wall_mm"],
            cls.g["dihedral_deg"], printgeom.WASHOUT_DEG,
            printgeom.WING_STATIONS, False)

    def test_closed_shell(self):
        ok, bad = self.halph.is_manifold()
        self.assertTrue(ok, "лоши ръбове: %d" % bad)
        self.assertGreater(self.halph.volume(), 0.0)

    def test_span_matches_design(self):
        size = self.halph.size()
        self.assertAlmostEqual(size[2], self.g["span_mm"] / 2.0, delta=1.0)

    def test_wall_thickness_doubles_volume(self):
        twice = printgeom.lifting_surface(
            self.g["c_root_mm"], self.g["c_tip_mm"], self.g["span_mm"] / 2.0,
            self.g["airfoil"]["key"], 2.0 * self.st["wall_mm"],
            self.g["dihedral_deg"], printgeom.WASHOUT_DEG, 4, False)
        ratio = twice.volume() / self.halph.volume()
        self.assertGreater(ratio, 1.7)
        self.assertLess(ratio, 2.3)

    def test_mirrored_half_has_same_volume(self):
        mirror = printgeom.lifting_surface(
            self.g["c_root_mm"], self.g["c_tip_mm"], self.g["span_mm"] / 2.0,
            self.g["airfoil"]["key"], self.st["wall_mm"],
            self.g["dihedral_deg"], printgeom.WASHOUT_DEG,
            printgeom.WING_STATIONS, True)
        self.assertAlmostEqual(mirror.volume(), self.halph.volume(),
                               delta=1e-6 * max(1.0, self.halph.volume()))
        self.assertTrue(mirror.is_manifold()[0])

    def test_caps_are_closed_and_add_material(self):
        caps = printgeom.spar_caps(
            self.res, self.g["c_root_mm"], self.g["c_tip_mm"],
            self.g["span_mm"] / 2.0, self.g["airfoil"]["key"],
            self.st["wall_mm"], self.g["dihedral_deg"],
            printgeom.WASHOUT_DEG, printgeom.WING_STATIONS, False)
        self.assertGreater(caps.volume(), 0.0)
        self.assertTrue(caps.is_manifold()[0])

    def test_carbon_splits_the_cap(self):
        plain = printgeom.spar_caps({"structure": {
            "cap_width_mm": 30.0, "wall_mm": 0.45}}, 200.0, 150.0, 300.0,
            "naca2412", 0.45)
        split = printgeom.spar_caps({"structure": {
            "cap_width_mm": 30.0, "wall_mm": 0.45, "carbon_required": True,
            "carbon": {"width_mm": 9.0, "count": 1}}},
            200.0, 150.0, 300.0, "naca2412", 0.45)
        self.assertGreater(split.triangles(), plain.triangles())
        self.assertGreater(plain.volume(), split.volume())


class TestWingTip(unittest.TestCase):
    def _parts(self, **wing):
        res = result(wing=wing)
        return res, printgeom.build_parts(res)

    def test_rounded_tip_shell_is_closed(self):
        res, rounded = self._parts(tip_style="rounded")
        wing = [p for p in rounded if p["file"] == "wing_right.stl"][0]
        self.assertTrue(wing["mesh"].is_manifold()[0])
        self.assertGreater(wing["mesh"].volume(), 0.0)
        # площта се запазва, затова обемът на черупката е от същия порядък
        _, plain = self._parts()
        base = [p for p in plain if p["file"] == "wing_right.stl"][0]
        ratio = wing["mesh"].volume() / base["mesh"].volume()
        self.assertGreater(ratio, 0.85)
        self.assertLess(ratio, 1.15)

    def test_rounded_tip_respects_the_minimum_chord(self):
        res, _ = self._parts(tip_style="rounded")
        c_root = res["geometry"]["c_root_mm"]
        self.assertGreaterEqual(res["geometry"]["c_tip_mm"], 0.07 * c_root)
        self.assertGreaterEqual(res["geometry"]["c_tip_mm"], 14.0)

    def test_winglet_is_printed_as_a_separate_part(self):
        _, parts = self._parts(tip_style="winglet",
                               winglet={"enabled": True, "height_mm": 45})
        files = [p["file"] for p in parts]
        self.assertIn("winglet_right.stl", files)
        self.assertIn("winglet_left.stl", files)
        for part in parts:
            if part["file"].startswith("winglet"):
                self.assertTrue(part["mesh"].is_manifold()[0], part["name"])
                self.assertGreater(part["mesh"].volume(), 1.0)

    def test_spinner_is_printed_as_a_part(self):
        _, parts = self._parts()
        files = [p["file"] for p in parts]
        self.assertIn("spinner.stl", files)
        spin = [p for p in parts if p["file"] == "spinner.stl"][0]
        self.assertTrue(spin["mesh"].is_manifold()[0], spin["name"])
        self.assertGreater(spin["mesh"].volume(), 1000.0)

    def test_pusher_has_no_spinner(self):
        res = result(layout={"propulsion": "pusher"})
        files = [p["file"] for p in printgeom.build_parts(res)]
        self.assertNotIn("spinner.stl", files)

    def test_plan_for_print_includes_the_winglet(self):
        res, parts = self._parts(tip_style="winglet",
                                 winglet={"enabled": True, "height_mm": 40})
        plan = printgeom.plan_parts(parts, BED, res["filament"])
        self.assertTrue(any("Уинглет" in row["name"]
                            for row in plan["parts"]))


class TestFuselage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.mesh = printgeom.fuselage_mesh(cls.res)
        cls.fus = cls.res["geometry"]["fuselage"]

    def test_is_closed(self):
        ok, bad = self.mesh.is_manifold()
        self.assertTrue(ok, "лоши ръбове: %d" % bad)
        self.assertGreater(self.mesh.volume(), 0.0)

    def test_dimensions_match_design(self):
        size = self.mesh.size()
        # филета няма — габаритът е точно номиналният
        self.assertAlmostEqual(size[0], self.fus["width_mm"], delta=0.6)
        self.assertAlmostEqual(size[1], self.fus["height_mm"], delta=0.6)
        self.assertAlmostEqual(size[2], self.fus["length_mm"], delta=0.6)

    def test_volume_follows_wall_and_area(self):
        wall = self.res["structure"]["wall_mm"]
        expected = self.fus["wetted_area_mm2"] * wall / 1000.0
        self.assertGreater(self.mesh.volume() / 1000.0, 0.5 * expected)
        self.assertLess(self.mesh.volume() / 1000.0, 1.4 * expected)

    def test_thicker_wall_more_material(self):
        thick = printgeom.fuselage_mesh(self.res, wall_mm=1.2)
        self.assertGreater(thick.volume(), self.mesh.volume())
        self.assertTrue(thick.is_manifold()[0])


class TestPartsAndPlan(unittest.TestCase):
    def test_parts_are_closed_and_on_bed(self):
        parts = printgeom.build_parts(result())
        self.assertGreaterEqual(len(parts), 4)
        for part in parts:
            mesh = part["mesh"]
            self.assertTrue(mesh.is_manifold()[0], part["name"])
            x0, y0, z0, _, _, _ = mesh.bbox()
            self.assertAlmostEqual(x0, 0.0, places=6, msg=part["name"])
            self.assertAlmostEqual(y0, 0.0, places=6, msg=part["name"])
            self.assertAlmostEqual(z0, 0.0, places=6, msg=part["name"])

    def test_flying_wing_has_no_tail_parts(self):
        parts = printgeom.build_parts(result(
            mission="flying_wing", wing={"airfoil": "mh45"}))
        names = [p["name"] for p in parts]
        self.assertNotIn("Стабилизатор", names)
        self.assertNotIn("Кил", names)
        self.assertTrue(any("Крило" in n for n in names))

    def test_plan_reports_segments(self):
        res = result()
        parts = printgeom.build_parts(res)
        plan = printgeom.plan_parts(parts, BED, res["filament"])
        self.assertFalse(plan["all_fit"])
        wing = [p for p in plan["parts"] if p["file"] == "wing_right.stl"][0]
        self.assertGreaterEqual(wing["segments"]["z"], 2)
        self.assertTrue(wing["manifold"])
        self.assertGreater(wing["mass_g"], 1.0)

    def test_plan_mass_uses_printed_density(self):
        parts = printgeom.build_parts(result())
        plan = printgeom.plan_parts(parts, BED, {"printed_density": 0.45})
        self.assertAlmostEqual(plan["total_mass_g"],
                               plan["total_volume_cm3"] * 0.45, delta=0.2)

    def test_export_writes_files_and_plan(self):
        folder = tempfile.mkdtemp(prefix="aeroforge_geom_")
        try:
            res = result()
            out = printgeom.export(res, folder, BED, res["filament"],
                                   slugify=report.slugify)
            self.assertTrue(out["ok"], out.get("error"))
            self.assertTrue(os.path.isdir(out["folder"]))
            for item in out["files"]:
                self.assertTrue(os.path.exists(item["path"]), item["file"])
                self.assertGreater(item["bytes"], 84)
            with open(out["plan_path"], encoding="utf-8") as f:
                plan = json.load(f)
            self.assertEqual(plan["units"], "mm")
            self.assertGreater(len(plan["parts"]), 3)
            self.assertTrue(plan["notes"])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_mass_matches_print_estimate(self):
        """Геометрията и емпиричната оценка за печат дават еднаква маса."""
        res = result()
        parts = printgeom.build_parts(res)
        volume = sum(p["mesh"].volume() for p in parts) / 1000.0
        mass = volume * res["filament"]["printed_density"]
        estimate = res["print"]["total_mass_g"]
        self.assertLess(abs(mass / estimate - 1.0), 0.20,
                        "STL %.1f g срещу оценка %.1f g" % (mass, estimate))

    def test_invalid_design_is_rejected(self):
        self.assertEqual(printgeom.build_parts(None), [])
        self.assertFalse(printgeom.export({"ok": False}, ".", BED)["ok"])


if __name__ == "__main__":
    unittest.main()

