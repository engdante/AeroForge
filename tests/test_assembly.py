"""
Тестове за цялостния CAD модел (assembly.py).

Проверява се координатната система (нос в 0, корем при Z=0), че крилото е
един обем по целия размах, че телата са затворени и че референциите са на
местата, които изчисленията дават.
"""

import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import assembly, design, printgeom  # noqa: E402


def result(**overrides):
    inputs = {"mission": "trainer",
              "payload": {"mode": "simple", "total_g": 600},
              "print": {"filament": "lw_pla", "perimeters": 1, "infill": 0}}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(inputs.get(key), dict):
            inputs[key] = dict(inputs[key], **value)
        else:
            inputs[key] = value
    return design.compute(inputs)


class TestBodies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.bodies = assembly.build_assembly(cls.res)
        cls.by_name = {b["name"]: b["mesh"] for b in cls.bodies}

    def test_all_bodies_present(self):
        names = [b["name"] for b in self.bodies]
        self.assertIn("Wing", names)
        self.assertIn("Fuselage", names)
        self.assertIn("Stabilizer", names)
        self.assertIn("Fin", names)

    def test_all_bodies_are_closed_solids(self):
        for body in self.bodies:
            ok, bad = body["mesh"].is_manifold()
            self.assertTrue(ok, "%s: %d лоши ръба" % (body["name"], bad))
            self.assertGreater(body["mesh"].volume(), 0.0, body["name"])

    def test_wing_is_one_body_over_full_span(self):
        wing = self.by_name["Wing"]
        size = wing.size()
        self.assertAlmostEqual(size[1], self.res["geometry"]["span_mm"],
                               delta=1.5)
        self.assertEqual(len([b for b in self.bodies
                              if b["name"].startswith("Wing")]), 1)

    def test_fuselage_matches_dimensions(self):
        fus = self.res["geometry"]["fuselage"]
        size = self.by_name["Fuselage"].size()
        # филета няма — габаритът е точно номиналният
        self.assertAlmostEqual(size[0], fus["length_mm"], delta=1.0)
        self.assertAlmostEqual(size[1], fus["width_mm"], delta=0.6)
        self.assertAlmostEqual(size[2], fus["height_mm"], delta=0.6)

    def test_datum_nose_at_zero_and_belly_at_zero(self):
        mesh = self.by_name["Fuselage"]
        fus = self.res["geometry"]["fuselage"]
        x0, y0, z0, x1, y1, z1 = mesh.bbox()
        self.assertAlmostEqual(x0, 0.0, places=6)
        self.assertAlmostEqual(z0, 0.0, places=6)
        self.assertAlmostEqual(y0, -fus["width_mm"] / 2.0, delta=0.2)

    def test_wing_sits_above_belly(self):
        wing = self.by_name["Wing"]
        z0 = wing.bbox()[2]
        height = self.res["geometry"]["fuselage"]["height_mm"]
        self.assertGreater(z0, 0.4 * height)

    def test_solid_is_not_a_thin_shell(self):
        wing = self.by_name["Wing"]
        g = self.res["geometry"]
        shell = printgeom.lifting_surface(
            g["c_root_mm"], g["c_tip_mm"], g["span_mm"] / 2.0,
            g["airfoil"]["key"], self.res["structure"]["wall_mm"],
            g["dihedral_deg"], printgeom.WASHOUT_DEG, 6, False)
        self.assertGreater(wing.volume(), 5.0 * shell.volume())

    def test_flying_wing_has_no_tail_bodies(self):
        res = result(mission="flying_wing", wing={"airfoil": "mh45"})
        names = [b["name"] for b in assembly.build_assembly(res)]
        self.assertNotIn("Stabilizer", names)
        self.assertNotIn("Fin", names)

    def test_v_tail_gives_two_panels(self):
        res = result(tail={"type": "v_tail", "v_deg": 38})
        names = [b["name"] for b in assembly.build_assembly(res)]
        self.assertIn("Stabilizer_V_R", names)
        self.assertIn("Stabilizer_V_L", names)
        self.assertNotIn("Stabilizer", names)

    def test_invalid_design(self):
        self.assertEqual(assembly.build_assembly(None), [])


class TestReferenceBodies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.refs = assembly.reference_bodies(cls.res)

    def test_expected_references(self):
        names = [r["name"] for r in self.refs]
        self.assertIn("REF_Battery", names)
        self.assertIn("REF_ESC", names)
        self.assertIn("REF_Receiver", names)
        self.assertIn("REF_Servo_L", names)
        self.assertIn("REF_Servo_R", names)
        self.assertIn("REF_CG", names)

    def test_references_are_closed_boxes(self):
        for ref in self.refs:
            self.assertTrue(ref["mesh"].is_manifold()[0], ref["name"])
            self.assertGreater(ref["mesh"].volume(), 0.0, ref["name"])

    def test_battery_volume_matches_box(self):
        bat = [r for r in self.refs if r["name"] == "REF_Battery"][0]
        box = self.res["geometry"]["fuselage"]["battery_box_mm"]
        expected = box[0] * box[1] * box[2]
        self.assertAlmostEqual(bat["mesh"].volume(), expected,
                               delta=0.01 * expected)

    def test_battery_sits_at_required_position(self):
        bat = [r for r in self.refs if r["name"] == "REF_Battery"][0]
        x0, _, _, x1, _, _ = bat["mesh"].bbox()
        center = (x0 + x1) / 2.0
        placed = self.res["stability"]["battery_x_placed_mm"]
        self.assertAlmostEqual(center, placed, delta=1.0)


class TestWingTipBodies(unittest.TestCase):
    def test_rounded_tip_section_is_shorter_at_the_span_end(self):
        res = result(wing={"tip_style": "rounded"})
        plate = result()
        rounded = assembly.sections(res)["wing"]
        square = assembly.sections(plate)["wing"]
        last_r = max(rounded, key=lambda s: s["y_mm"])
        last_s = max(square, key=lambda s: s["y_mm"])
        span_r = max(p[0] for p in last_r["points"]) - min(
            p[0] for p in last_r["points"])
        span_s = max(p[0] for p in last_s["points"]) - min(
            p[0] for p in last_s["points"])
        self.assertLess(span_r, 0.75 * span_s)

    def test_winglet_body_is_added_to_the_cad_model(self):
        res = result(wing={"tip_style": "winglet",
                           "winglet": {"enabled": True, "height_mm": 45}})
        bodies = assembly.build_assembly(res)
        names = [b["name"] for b in bodies]
        self.assertIn("Winglet_R", names)
        self.assertIn("Winglet_L", names)
        for body in bodies:
            if body["name"].startswith("Winglet"):
                self.assertTrue(body["mesh"].is_manifold()[0], body["name"])

    def test_no_winglet_body_when_disabled(self):
        res = result()
        names = [b["name"] for b in assembly.build_assembly(res)]
        self.assertNotIn("Winglet_R", names)

    def test_spinner_is_a_cad_body(self):
        res = result()
        bodies = {b["name"]: b for b in assembly.build_assembly(res)}
        self.assertIn("Spinner", bodies)
        self.assertTrue(bodies["Spinner"]["mesh"].is_manifold()[0])

    def test_no_spinner_for_a_pusher(self):
        res = result(layout={"propulsion": "pusher"})
        names = [b["name"] for b in assembly.build_assembly(res)]
        self.assertNotIn("Spinner", names)


class TestSections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.sections = assembly.sections(cls.res)

    def test_counts(self):
        self.assertGreaterEqual(len(self.sections["wing"]), 7)
        self.assertGreaterEqual(len(self.sections["fuselage"]), 6)

    def test_wing_sections_cover_span(self):
        ys = [s["y_mm"] for s in self.sections["wing"]]
        span = self.res["geometry"]["span_mm"]
        self.assertAlmostEqual(min(ys), -span / 2.0, delta=2.0)
        self.assertAlmostEqual(max(ys), span / 2.0, delta=2.0)

    def test_root_section_has_full_chord(self):
        root = [s for s in self.sections["wing"]
                if abs(s["y_mm"]) < 1e-6][0]
        xs = [p[0] for p in root["points"]]
        chord = self.res["geometry"]["c_root_mm"]
        self.assertGreater(max(xs) - min(xs), 0.9 * chord)

    def test_dihedral_raises_the_tip(self):
        by_y = {round(s["y_mm"], 1): s for s in self.sections["wing"]}
        span = self.res["geometry"]["span_mm"]
        root = by_y[0.0]
        tip = by_y[round(span / 2.0, 1)]
        z_root = sum(p[2] for p in root["points"]) / len(root["points"])
        z_tip = sum(p[2] for p in tip["points"]) / len(tip["points"])
        self.assertGreater(z_tip, z_root + 1.0)

    def test_fuselage_stations_start_after_nose(self):
        xs = [s["x_mm"] for s in self.sections["fuselage"]]
        self.assertGreater(min(xs), 0.0)
        self.assertLessEqual(max(xs),
                             self.res["geometry"]["fuselage"]["length_mm"])


if __name__ == "__main__":
    unittest.main()

