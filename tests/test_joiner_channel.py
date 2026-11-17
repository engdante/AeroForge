"""
Канали за съединителната тръба (джойнера): геометрия, стенна граница,
негативни цилиндри за слайсера и план за печат.
"""

import copy
import math
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import design, printgeom  # noqa: E402

CASE = {"name": "Channel trainer", "mission": "trainer",
        "payload": {"mode": "simple", "total_g": 600}}


class TestJoinerChannel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = design.compute(dict(CASE))
        cls.tube = cls.res["structure"]["joiner_tube"]

    def test_channel_matches_tube(self):
        ch = printgeom.joiner_channel(self.res)
        self.assertIsNotNone(ch)
        self.assertAlmostEqual(ch["od_mm"], self.tube["od_mm"], places=6)
        self.assertAlmostEqual(
            ch["bore_mm"], self.tube["od_mm"] + printgeom.CHANNEL_CLEARANCE_MM,
            places=6)
        # дълбочината е половината от джойнера (дела на лепилната връзка)
        self.assertAlmostEqual(ch["depth_mm"], self.tube["length_mm"] / 2.0,
                               places=6)

    def test_wall_margin_and_flag_agree(self):
        ch = printgeom.joiner_channel(self.res)
        self.assertEqual(ch["ok"],
                         ch["wall_margin_mm"] >= printgeom.CHANNEL_MIN_WALL_MM)
        self.assertTrue(ch["ok"], ch)

    def test_no_tube_no_channel(self):
        res = copy.deepcopy(self.res)
        res["structure"]["joiner_tube"]["od_mm"] = None
        self.assertIsNone(printgeom.joiner_channel(res))

    def test_too_big_tube_fails_wall_check(self):
        res = copy.deepcopy(self.res)
        res["structure"]["joiner_tube"]["od_mm"] = 60.0
        ch = printgeom.joiner_channel(res)
        self.assertLess(ch["wall_margin_mm"], 0.0)
        self.assertFalse(ch["ok"])

    def test_cutter_is_closed_and_has_right_depth(self):
        ch = printgeom.joiner_channel(self.res)
        cut = printgeom.joiner_cutter(ch)
        manifold, _ = cut.is_manifold()
        self.assertTrue(manifold)
        size = cut.size()
        self.assertAlmostEqual(size[2], ch["depth_mm"] + 1.0, places=6)
        self.assertLessEqual(size[0], ch["bore_mm"] + 1e-6)
        # обемът е близо до 24-ъгълна призма с радиус bore/2
        r = ch["bore_mm"] / 2.0
        n = printgeom.CUTTER_SEGMENTS
        poly = 0.5 * n * r * r * math.sin(2 * math.pi / n)
        self.assertAlmostEqual(cut.volume(), poly * (ch["depth_mm"] + 1.0),
                               delta=0.02 * poly * (ch["depth_mm"] + 1.0))

    def test_cutters_do_not_change_printable_parts(self):
        plain = printgeom.build_parts(self.res)
        cutters = []
        with_cut = printgeom.build_parts(self.res, cutters=cutters)
        self.assertEqual([p["file"] for p in plain],
                         [p["file"] for p in with_cut])
        self.assertEqual(len(cutters), 2)
        self.assertTrue(all(c["file"].startswith("channel_") for c in cutters))

    def test_export_writes_cutters_and_plan_entry(self):
        import os
        import tempfile
        base = tempfile.mkdtemp()
        out = printgeom.export(self.res, base, [220, 220, 250],
                               slugify=lambda s: "chan")
        self.assertTrue(out["ok"])
        roles = [f.get("role") for f in out["files"]]
        self.assertEqual(roles.count("channel_cutter"), 2)
        for f in out["files"]:
            self.assertTrue(os.path.exists(f["path"]))
        self.assertIsNotNone(out["plan"]["joiner_channel"])
        # печатният план не брои негативните обеми
        self.assertFalse(any(p["name"].startswith("Канал")
                             for p in out["plan"]["parts"]))


if __name__ == "__main__":
    unittest.main()
