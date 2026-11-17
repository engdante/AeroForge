"""
Елерони (елевони): размери в изчислението, 3D прегледът (с вътрешните
части спар/джойнер) и резачите за гладкия модел в SolidCraft.
"""

import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import assembly, controls, design, geometry3d  # noqa: E402
from core import solidcraft_export as sc  # noqa: E402

TRAINER = {"name": "Ailerons", "mission": "trainer",
           "payload": {"mode": "simple", "total_g": 600}}


def compute(**wing):
    case = dict(TRAINER)
    if wing:
        case["wing"] = wing
    return design.compute(case)


class TestControlsCore(unittest.TestCase):
    def test_defaults_follow_mission(self):
        ail = compute()["geometry"]["ailerons"]
        self.assertTrue(ail["enabled"])
        self.assertEqual(ail["kind"], "aileron")
        self.assertAlmostEqual(ail["chord_frac"], 0.18)   # aileron_ratio
        self.assertAlmostEqual(ail["start_frac"], controls.DEFAULT_SPAN[0])
        self.assertAlmostEqual(ail["end_frac"], controls.DEFAULT_SPAN[1])
        self.assertGreater(ail["area_dm2"], 0.0)
        self.assertTrue(0.03 < ail["area_ratio"] < 0.20)

    def test_flying_wing_has_elevons_further_inboard(self):
        res = design.compute(dict(TRAINER, mission="flying_wing"))
        ail = res["geometry"]["ailerons"]
        self.assertEqual(ail["kind"], "elevon")
        self.assertAlmostEqual(ail["start_frac"], controls.ELEVON_SPAN[0])

    def test_percent_input_and_zero_disables(self):
        ail = compute(ailerons={"chord_frac": 30, "start_frac": 50,
                                "end_frac": 90})["geometry"]["ailerons"]
        self.assertAlmostEqual(ail["chord_frac"], 0.30)
        self.assertAlmostEqual(ail["start_frac"], 0.50)
        self.assertAlmostEqual(ail["end_frac"], 0.90)
        off = compute(ailerons={"chord_frac": 0})["geometry"]["ailerons"]
        self.assertFalse(off["enabled"])
        self.assertEqual(off["area_dm2"], 0.0)

    def test_values_are_clamped(self):
        ail = compute(ailerons={"chord_frac": 0.9, "start_frac": 0.6,
                                "end_frac": 0.61})["geometry"]["ailerons"]
        self.assertLessEqual(ail["chord_frac"], controls.CHORD_FRAC_RANGE[1])
        self.assertGreaterEqual(ail["end_frac"] - ail["start_frac"],
                                controls.MIN_SPAN_FRAC - 1e-9)

    def test_rounded_tip_stops_before_rounding(self):
        ail = compute(tip_style="rounded", tip_frac=0.2)["geometry"]["ailerons"]
        self.assertLessEqual(ail["end_frac"], 0.8)


class TestPreviewModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = compute()
        cls.model = geometry3d.build_model(cls.res, quality="normal")
        cls.parts = {p["name"]: p for p in cls.model["parts"]}

    def bbox(self, part, axis):
        values = part["points"][axis::3]
        return min(values), max(values)

    def test_aileron_part_behind_hinge_and_in_span_range(self):
        ail = self.parts.get("Елерони")
        self.assertIsNotNone(ail)
        self.assertEqual(ail["layer"], "skin")
        g = self.res["geometry"]
        y_lo, y_hi = self.bbox(ail, 1)
        self.assertAlmostEqual(y_hi, g["ailerons"]["y_end_mm"],
                               delta=0.05 * g["span_mm"])
        x_lo, _ = self.bbox(ail, 0)
        # пантата е зад 70 % от най-късата хорда
        self.assertGreater(x_lo, g["wing_le_mm"] + 0.7 * g["c_tip_mm"])

    def test_internal_parts_are_inside_the_wing_span(self):
        g = self.res["geometry"]
        for name in ("Спар (печатани капси)", "Джойнер"):
            part = self.parts.get(name)
            self.assertIsNotNone(part, name)
            self.assertEqual(part["layer"], "internal")
            y_lo, y_hi = self.bbox(part, 1)
            self.assertLessEqual(y_hi, g["span_mm"] / 2.0 + 1.0)
            self.assertGreaterEqual(y_lo, -g["span_mm"] / 2.0 - 1.0)
        joiner = self.parts["Джойнер"]
        y_lo, y_hi = self.bbox(joiner, 1)
        length = self.res["structure"]["joiner_tube"]["length_mm"]
        self.assertAlmostEqual(y_hi - y_lo, length, delta=2.0)

    def test_no_aileron_part_when_disabled(self):
        res = compute(ailerons={"chord_frac": 0})
        names = [p["name"] for p in geometry3d.build_model(res)["parts"]]
        self.assertNotIn("Елерони", names)
        self.assertIn("Крило", names)

    def test_clip_outline_splits_profile_at_hinge(self):
        outline = geometry3d._outline("naca2412", 24)
        front = geometry3d._clip_outline(outline, -1.0, 0.8)
        rear = geometry3d._clip_outline(outline, 0.8, 2.0)
        self.assertAlmostEqual(max(p[0] for p in front), 0.8, places=6)
        self.assertAlmostEqual(min(p[0] for p in rear), 0.8, places=6)
        self.assertGreaterEqual(len(rear), 3)


class TestSolidCraftCutters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = compute()
        cls.bodies = assembly.loft_bodies(cls.res, None, sc.DEFAULT_DETAIL)
        cls.by_name = {b["name"]: b for b in cls.bodies}

    def test_each_half_gets_aileron_and_slot(self):
        for side in ("R", "L"):
            ail = self.by_name["Aileron_%s" % side]
            slot = self.by_name["Aileron_Slot_%s" % side]
            self.assertEqual(ail["op"], "intersect")
            self.assertEqual(ail["with"], "Wing_%s" % side)
            self.assertEqual(slot["op"], "cut")
            self.assertEqual(slot["from"], "Wing_%s" % side)

    def test_aileron_is_inside_slot_with_gaps(self):
        g = self.res["geometry"]["ailerons"]
        ail = self.by_name["Aileron_R"]["sections"]
        slot = self.by_name["Aileron_Slot_R"]["sections"]
        self.assertAlmostEqual(slot[0]["station_mm"], g["y_start_mm"], places=3)
        self.assertAlmostEqual(ail[0]["station_mm"],
                               g["y_start_mm"] + g["end_gap_mm"], places=3)
        # пантата на елерона е с процепа зад тази на прореза (станциите се
        # различават с крайния процеп, а хордата се стеснява → ±0.2 mm)
        self.assertAlmostEqual(ail[0]["points2d"][0][0] - slot[0]["points2d"][0][0],
                               g["hinge_gap_mm"], delta=0.2)
        left = self.by_name["Aileron_L"]["sections"]
        self.assertAlmostEqual(left[0]["station_mm"], -ail[0]["station_mm"])

    def test_commands_intersect_then_cut_before_join(self):
        commands = sc.build_commands(self.bodies)
        combines = [(c["params"]["target"], c["params"]["operation"],
                     c["params"].get("keep_tools"))
                    for c in commands if c["command"] == "solid.combine"]
        self.assertIn(("Aileron_R", "intersect", True), combines)
        self.assertIn(("Wing_R", "cut", None), combines)
        self.assertLess(combines.index(("Aileron_R", "intersect", True)),
                        combines.index(("Wing_R", "cut", None)))
        # резачите са правоъгълни скици (затворена линия), не spline
        lines = [c for c in commands if c["command"] == "sketch.line"
                 and c["params"].get("closed")]
        self.assertGreaterEqual(len(lines), 4 * (assembly.AILERON_CUTTER_STATIONS + 1))

    def test_cutters_stay_out_of_profiles_and_in_wing_step(self):
        names = [b["name"] for b in sc.profile_bodies(self.bodies)]
        self.assertFalse(any(n.startswith("Aileron") for n in names))
        wing_step = [s for s in sc.group_steps(self.bodies) if s["id"] == "wing"][0]
        for name in ("Aileron_R", "Aileron_Slot_R", "Aileron_L", "Aileron_Slot_L"):
            self.assertIn(name, wing_step["bodies"])

    def test_no_cutters_without_ailerons(self):
        res = compute(ailerons={"chord_frac": 0})
        bodies = assembly.loft_bodies(res, None, sc.DEFAULT_DETAIL)
        self.assertFalse(any(b.get("cutter") for b in bodies))


if __name__ == "__main__":
    unittest.main()
