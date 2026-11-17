"""
Детайлният модел за SolidCraft (aircraft_detailed.sc): крило и опашка —
цели тела с централен профил, слети с кухото тяло; елерони с шарнирна
панта; серва, избрани по шарнирния момент.

Тестовете проверяват генерирания скрипт (без SolidCraft). Реалното
построяване се пуска с AEROFORGE_SOLIDCRAFT_SLOW=1 (около 1.5 min).
"""

import math
import os
import tempfile
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import controls, design, detailed_model as dm  # noqa: E402
from core import solidcraft_export as sc  # noqa: E402

TRAINER = {"name": "Detailed", "mission": "trainer",
           "payload": {"mode": "simple", "total_g": 600}}


def compute(**extra):
    case = dict(TRAINER)
    case.update(extra)
    return design.compute(case)


def names(script, command=None):
    return [c["params"].get("name") for c in script["commands"]
            if command is None or c["command"] == command]


class TestCenterSection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = compute()
        cls.frame = dm.wing_frame(cls.res)

    def test_wing_is_one_body_through_the_centre(self):
        stations = self.frame.stations()
        self.assertIn(0.0, stations)
        self.assertAlmostEqual(min(stations), -self.frame.semi, places=6)
        self.assertAlmostEqual(max(stations), self.frame.semi, places=6)
        # симетрично спрямо оста
        self.assertEqual(sorted(-s for s in stations), sorted(stations))

    def test_centre_profile_is_longer_and_thicker(self):
        f = self.frame
        g = self.res["geometry"]
        u = 0.3
        t_centre = 2 * f.half_thickness(u, 0.0)
        t_root = (f.surface(u, 1) - f.surface(u, -1)) * f.chord(0.0)
        self.assertAlmostEqual(t_centre / t_root, f.k_thick, places=6)
        self.assertGreater(f.k_chord, 1.0)
        self.assertLessEqual(f.k_thick * f.thickness_ratio(),
                             dm.CENTER_TC_MAX + 1e-9)
        # хордата в оста: TE − LE на централното сечение
        le = f.point(0.0, f.mid(0.0), 0.0)[0]
        te = f.point(1.0, f.mid(1.0), 0.0)[0]
        self.assertAlmostEqual((te - le) / g["c_root_mm"], f.k_chord, delta=0.02)

    def test_blend_ends_outside_the_fuselage_and_is_smooth(self):
        f = self.frame
        half_w = self.res["geometry"]["fuselage"]["width_mm"] / 2.0
        self.assertGreater(f.blend, half_w)
        self.assertEqual(f.weight(f.blend), 0.0)
        self.assertEqual(f.weight(0.0), 1.0)
        # без чупка: производната е 0 в двата края
        eps = 1e-3
        self.assertAlmostEqual(f.weight(eps), 1.0, places=5)
        self.assertAlmostEqual(f.weight(f.blend - eps), 0.0, places=5)

    def test_tail_surfaces_get_centre_profiles(self):
        tails = dict(dm.tail_frames(self.res))
        self.assertIn("Stabilizer", tails)
        self.assertIn("Fin", tails)
        self.assertTrue(tails["Stabilizer"].symmetric)
        self.assertIn(0.0, tails["Stabilizer"].stations())
        for frame in tails.values():
            self.assertGreater(frame.blend, 0.0)
            self.assertGreater(frame.k_chord, 1.0)

    def test_stabilizer_lift_variant(self):
        base = dict(dm.tail_frames(self.res))["Stabilizer"].origin[2]
        lifted = dict(dm.tail_frames(self.res, stab_lift_mm=3.0))["Stabilizer"]
        self.assertAlmostEqual(lifted.origin[2] - base, 3.0, places=6)


class TestDetailedScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = compute()
        cls.script = dm.build_script(cls.res, None, sc.DEFAULT_DETAIL,
                                     out_step="x/aircraft_detailed.step")
        cls.labels = names(cls.script)

    def test_airframe_is_joined_part_by_part(self):
        for tool in ("Cowl", "Wing", "Stabilizer", "Fin"):
            self.assertIn("Join %s" % tool, self.labels)
        self.assertNotIn("Wing_R", self.script["bodies"])
        self.assertNotIn("Wing", self.script["bodies"])

    def test_only_servos_inside_the_fuselage(self):
        refs = [n for n in self.script["bodies"] if n.startswith("REF_")]
        self.assertTrue(refs)
        for name in refs:
            # мотор и витло са в носа (пред преградата), не в кухината
            self.assertTrue(name.startswith(("REF_Servo", "REF_Motor_",
                                             "REF_Prop_")), name)
        for name in ("REF_Servo_Elevator", "REF_Servo_Rudder",
                     "REF_Servo_Aileron_R", "REF_Servo_Aileron_L"):
            self.assertIn(name, refs)

    def test_hollow_fuselage_cavity_and_hatch(self):
        self.assertIn("Fuselage cavity", self.labels)
        self.assertIn("Hatch from fuselage", self.labels)
        # кухината е преди сливането, капакът — след него
        self.assertLess(self.labels.index("Fuselage cavity"),
                        self.labels.index("Join Wing"))
        self.assertGreater(self.labels.index("Hatch opening"),
                           self.labels.index("Join Wing"))
        removes = [c for c in self.script["commands"]
                   if c["command"] == "solid.remove"]
        self.assertEqual(removes[-1]["params"]["bodies"], ["Fuselage_Fill"])

    def test_through_centre_features_after_the_join(self):
        join = self.labels.index("Join Wing")
        for label in ("Spar slot Top", "Spar slot Bot", "Tube channel",
                      "Cable junction", "Cable channel R", "Cable channel L",
                      "Cable exit"):
            self.assertGreater(self.labels.index(label), join, label)

    def test_aileron_hinge_parts_for_both_sides(self):
        ail = self.res["geometry"]["ailerons"]
        count = max(2, int(round(ail["span_mm"] / dm.KNUCKLE_PITCH_MM)))
        for side in ("R", "L"):
            self.assertIn("Aileron_%s from wing" % side, self.labels)
            self.assertIn("Wing %s hinge cove" % side, self.labels)
            self.assertIn("Aileron_%s pin hole" % side, self.labels)
            self.assertIn("Aileron_%s horn" % side, self.labels)
            self.assertIn("Wing %s servo bay" % side, self.labels)
            knuckles = [n for n in self.labels
                        if n and n.startswith("Wing %s knuckle" % side)]
            self.assertEqual(len(knuckles), count)
            # елеронът се взима от крилото преди процепа и преди сливането
            take = self.labels.index("Aileron_%s from wing" % side)
            self.assertLess(take, self.labels.index("Wing %s slot" % side))
            self.assertLess(take, self.labels.index("Join Wing"))

    def test_primitives_have_positive_size(self):
        for c in self.script["commands"]:
            p = c["params"]
            if c["command"] == "solid.box":
                for key in ("length", "width", "height"):
                    self.assertGreater(p[key], 0, p["name"])
            elif c["command"] == "solid.cylinder":
                self.assertGreater(p["height"], 0, p["name"])
                self.assertGreater(p["diameter"], 0, p["name"])

    def test_export_is_last(self):
        last = self.script["commands"][-1]
        self.assertEqual(last["command"], "file.export")
        self.assertTrue(last["params"]["path"].endswith("aircraft_detailed.step"))

    def test_hinge_fits_the_wing(self):
        g = self.res["geometry"]
        frame = dm.wing_frame(self.res)
        u = 1.0 - g["ailerons"]["chord_frac"]
        r, t_half = dm._hinge_radius(frame, u, g["ailerons"]["y_start_mm"],
                                     g["ailerons"]["y_end_mm"])
        self.assertGreaterEqual(t_half - r - dm.HINGE_GAP_MM,
                                dm.HINGE_LIP_MM - 1e-9)
        self.assertGreater(r, dm.PIN_D_MM / 2.0 + 0.8)

    def test_tube_keeps_wall_to_the_surface(self):
        tube = dm.tube_layout(self.res, dm.wing_frame(self.res))
        self.assertGreater(tube["wall_margin_mm"], 1.2)


class TestCavity(unittest.TestCase):
    def test_inner_sections_are_smaller_by_the_wall(self):
        from core import assembly
        res = compute()
        outer = assembly.fuselage_rings(res, rings=24, stations=16)
        inner = dm.inner_sections(outer, 1.2)
        self.assertGreater(len(inner), 8)
        by_name = {s["name"]: s for s in outer}
        for section in inner:
            o = by_name[section["name"]]
            ow = max(p[0] for p in o["points2d"]) - min(p[0] for p in o["points2d"])
            iw = (max(p[0] for p in section["points2d"])
                  - min(p[0] for p in section["points2d"]))
            self.assertAlmostEqual(ow - iw, 2.4, places=6)
        cut = dm.inner_sections(outer, 1.2, x_max=500.0)
        self.assertTrue(all(s["station_mm"] <= 500.0 for s in cut))

    def test_no_aileron_ops_without_ailerons(self):
        res = compute(wing={"ailerons": {"chord_frac": 0}})
        labels = names(dm.build_script(res, None, sc.DEFAULT_DETAIL))
        self.assertFalse(any(n and n.startswith("Aileron") for n in labels))
        self.assertIn("Fuselage cavity", labels)


class TestFallbacks(unittest.TestCase):
    def test_failed_feature_and_variant_sequence(self):
        res = compute()
        commands = dm.build_script(res, None, sc.DEFAULT_DETAIL)["commands"]
        index = [i for i, c in enumerate(commands)
                 if c["params"].get("name") == "Join Stabilizer"][0]
        errors = [(str(index + 1), "solid.combine", "Bad CurveCusp")]
        self.assertEqual(dm.failed_feature(errors, commands), "Join Stabilizer")
        self.assertEqual(dm.failed_join(errors, commands), "Stabilizer")
        self.assertIsNone(dm.failed_feature([("1", "solid.loft", "x")], commands))

        v, seen = {}, []
        for attempt in range(10):
            v = dm.next_variants(v, "Join Stabilizer", attempt)
            if v is None:
                break
            seen.append(v)
        self.assertEqual(seen[0]["stab_lift_mm"], 3.0)
        self.assertEqual(seen[-1]["separate"], ["Stabilizer"])

    def test_variants_change_the_script(self):
        res = compute()
        script = dm.build_script(res, None, sc.DEFAULT_DETAIL,
                                 variants={"separate": ["Fin"],
                                           "thick": {"Wing": 1.0},
                                           "cable_exit": {"skip": True}})
        labels = names(script)
        self.assertNotIn("Join Fin", labels)
        self.assertIn("Fin", script["bodies"])
        self.assertNotIn("Cable exit", labels)

    def test_cable_exit_fallbacks_end_with_skip(self):
        v = {}
        for attempt in range(3):
            v = dm.next_variants(v, "Cable exit", attempt)
        self.assertTrue(v["cable_exit"]["skip"])
        self.assertIsNone(dm.next_variants(v, "Cable exit", 3))


class TestServoSizing(unittest.TestCase):
    def test_formula_matches_hand_calculation(self):
        # C = 4 cm, L = 30 cm, V = 50 mph, 25° / 45°
        v = 50.0 / 2.23694
        expected = (8.5e-6 * 16 * 2500 * 30 * math.sin(math.radians(25))
                    * math.tan(math.radians(25))) * 0.0720077
        self.assertAlmostEqual(controls.hinge_torque_kgcm(40, 300, v, 25),
                               expected, places=6)

    def test_trainer_uses_9g_servos_with_margin(self):
        sizing = controls.servo_sizing(compute())
        keys = {s["key"] for s in sizing["surfaces"]}
        self.assertEqual(keys, {"aileron", "elevator", "rudder"})
        for s in sizing["surfaces"]:
            self.assertEqual(s["servo"]["key"], "micro9")
            self.assertGreaterEqual(s["margin"], controls.SERVO_SAFETY)

    def test_bigger_load_picks_bigger_servo(self):
        self.assertEqual(controls.pick_servo(0.1)["key"], "micro9")
        self.assertEqual(controls.pick_servo(0.7)["key"], "micro13")
        self.assertEqual(controls.pick_servo(1.0)["key"], "mini17")
        self.assertEqual(controls.pick_servo(50.0)["key"], "std40")

    def test_flying_wing_has_only_elevons(self):
        sizing = controls.servo_sizing(compute(mission="flying_wing"))
        self.assertEqual([s["key"] for s in sizing["surfaces"]], ["elevon"])


class TestExportStep(unittest.TestCase):
    def test_detailed_step_runs_before_finish(self):
        from core import export_job
        res = compute()
        folder = tempfile.mkdtemp()
        job = export_job.start(res, folder, options={"run": False})
        ids = [s["id"] for s in job["steps"]]
        self.assertIn("detailed", ids)
        self.assertEqual(ids.index("detailed"), len(ids) - 2)
        off = export_job.start(res, folder, options={"run": False,
                                                     "detailed": False})
        self.assertNotIn("detailed", [s["id"] for s in off["steps"]])


@unittest.skipUnless(os.environ.get("AEROFORGE_SOLIDCRAFT_SLOW") == "1"
                     and sc.find_cli(), "бавен тест с реален SolidCraft")
class TestDetailedBuild(unittest.TestCase):
    def test_builds_closed_bodies(self):
        res = compute()
        folder = tempfile.mkdtemp()
        out = sc.export(res, folder, timeout=240)
        step = [s for s in out["steps"] if s["id"] == "detailed"][0]
        self.assertEqual(step["state"], "done", step.get("error"))
