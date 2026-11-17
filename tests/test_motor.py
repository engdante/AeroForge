"""
Мотор и витло: избор на мотора (мощност + въртящ момент), витлото по
реалния D×P, разположението (теглещо/бутащо/два мотора), 3D прегледът и
детайлният модел за SolidCraft (отделение, стойка, отвори, REF тела).
"""

import math
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import design, detailed_model as dm, fairing, geometry3d  # noqa: E402
from core import motor  # noqa: E402
from core import solidcraft_export as sc  # noqa: E402

BASE = {"name": "Motor", "payload": {"mode": "simple", "total_g": 600}}


def compute(mission="trainer", propulsion=None):
    case = dict(BASE, mission=mission)
    if propulsion:
        case["layout"] = {"propulsion": propulsion}
    return design.compute(case)


def labels(script):
    return [c["params"].get("name") for c in script["commands"]]


class TestMotorSelection(unittest.TestCase):
    def test_class_covers_power_and_torque(self):
        for mission in ("trainer", "sport", "3d", "glider", "flying_wing"):
            res = compute(mission)
            cls = motor.select(res)
            p = res["propulsion"]
            self.assertGreaterEqual(cls["p_max_w"],
                                    motor.POWER_HEADROOM * p["p_motor_elec_w"],
                                    mission)
            self.assertGreaterEqual(cls["q_max_nm"],
                                    motor.TORQUE_HEADROOM * motor.torque_nm(res),
                                    mission)

    def test_smallest_class_that_fits(self):
        res = compute("trainer")
        cls = motor.select(res)
        keys = [c["key"] for c in motor.MOTOR_CLASSES]
        for smaller in motor.MOTOR_CLASSES[:keys.index(cls["key"])]:
            fits = (smaller["p_max_w"] >= motor.POWER_HEADROOM
                    * res["propulsion"]["p_motor_elec_w"]
                    and smaller["q_max_nm"] >= motor.TORQUE_HEADROOM
                    * motor.torque_nm(res))
            self.assertFalse(fits, smaller["key"])

    def test_twin_motors_share_the_power(self):
        single = motor.select(compute("sport"))
        twin = motor.select(compute("sport", "twin"))
        self.assertLessEqual(twin["p_max_w"], single["p_max_w"])

    def test_prop_matches_the_calculation(self):
        res = compute("trainer")
        prop = motor.prop_geometry(res)
        self.assertAlmostEqual(prop["d_mm"],
                               res["propulsion"]["prop_d_in"] * 25.4, places=3)

    def test_blade_angle_follows_pitch(self):
        prop = motor.prop_geometry(compute("trainer"))
        for r, pts in motor.blade_sections(prop)[1:]:
            # ъгълът на сечението (LE → TE) е β = atan(P / 2πr)
            le = max(pts, key=lambda p: p[0] * 1 + 0 * p[1])
            te = min(pts, key=lambda p: p[0])
            beta = math.degrees(math.atan2(le[1] - te[1], le[0] - te[0]))
            expect = math.degrees(math.atan2(prop["pitch_mm"], 2 * math.pi * r))
            self.assertAlmostEqual(beta, expect, delta=6.0)


class TestMotorLayout(unittest.TestCase):
    def test_tractor_motor_behind_spinner_and_in_front_of_firewall(self):
        res = compute("trainer")
        lay = motor.layout(res)
        spin = fairing.spinner_params(res)
        unit = lay["units"][0]
        self.assertGreater(unit["x_can0"], spin["x_base"])
        self.assertLess(unit["x_prop"], spin["x_base"])
        self.assertGreater(unit["x_prop"], spin["x_tip"])
        self.assertLessEqual(unit["x_mount"], lay["x_firewall"])

    def test_spinner_and_cowl_fit_the_motor(self):
        for mission in ("trainer", "3d", "glider"):
            res = compute(mission)
            spin = fairing.spinner_params(res)
            self.assertGreaterEqual(spin["radius"] + 1e-6, motor.bay_radius(res),
                                    mission)
            self.assertGreaterEqual(spin["r_cowl1"] + 1e-6, spin["radius"])

    def test_pusher_and_twin(self):
        res = compute("trainer", "pusher")
        lay = motor.layout(res)
        length = res["geometry"]["fuselage"]["length_mm"]
        self.assertGreater(lay["units"][0]["x_prop"], length)
        twin = motor.layout(compute("trainer", "twin"))
        self.assertEqual(len(twin["units"]), 2)
        ys = sorted(u["y"] for u in twin["units"])
        self.assertAlmostEqual(ys[0], -ys[1])
        self.assertTrue(all(u["x_prop"] < u["x_can0"] for u in twin["units"]))


class TestMotorPreview(unittest.TestCase):
    def parts(self, **kw):
        model = geometry3d.build_model(compute(**kw), quality="normal")
        return {p["name"]: p for p in model["parts"]}

    def test_tractor_parts(self):
        res = compute("trainer")
        parts = self.parts()
        for name in ("Спинер", "Мотор", "Витло"):
            self.assertIn(name, parts)
        self.assertEqual(parts["Мотор"]["layer"], "internal")
        zs = parts["Витло"]["points"][2::3]
        prop = motor.prop_geometry(res)
        self.assertAlmostEqual(max(zs) - min(zs), prop["d_mm"], delta=2.0)

    def test_twin_has_two_props(self):
        parts = self.parts(propulsion="twin")
        for name in ("Мотор", "Мотор (2)", "Витло", "Витло (2)"):
            self.assertIn(name, parts)


class TestMotorDetailed(unittest.TestCase):
    def test_tractor_nose(self):
        script = dm.build_script(compute(), None, sc.DEFAULT_DETAIL)
        names = labels(script)
        for label in ("Motor bay", "Motor mount join", "Motor bore",
                      "Motor bolt holes", "Prop 1 blades join"):
            self.assertIn(label, names)
        self.assertGreater(names.index("Motor bay"), names.index("Join Cowl"))
        for body in ("REF_Motor_1", "REF_Prop_1"):
            self.assertIn(body, script["bodies"])
        bolts = [c for c in script["commands"]
                 if c["params"].get("name", "").startswith("Motor_Bolt_")]
        self.assertEqual(len(bolts), 4)

    def test_twin_has_refs_only(self):
        script = dm.build_script(compute("trainer", "twin"), None,
                                 sc.DEFAULT_DETAIL)
        names = labels(script)
        self.assertNotIn("Motor bay", names)
        for body in ("REF_Motor_1", "REF_Motor_2", "REF_Prop_1", "REF_Prop_2"):
            self.assertIn(body, script["bodies"])

    def test_fallbacks(self):
        script = dm.build_script(compute(), None, sc.DEFAULT_DETAIL)
        names = labels(script)
        i = names.index("Motor mount join")
        self.assertEqual(dm.failed_feature([(str(i + 1), "solid.combine", "x")],
                                           script["commands"]), "Motor")
        v = dm.next_variants({}, "Motor", 0)
        self.assertEqual(v["motor"], {"mount": False})
        v = dm.next_variants(v, "Motor", 1)
        self.assertFalse(v["motor"]["bay"])
        self.assertIsNone(dm.next_variants(v, "Motor", 2))
        v = dm.next_variants({}, "Prop", 1)
        self.assertTrue(v["prop"]["skip"])
        no_mount = labels(dm.build_script(compute(), None, sc.DEFAULT_DETAIL,
                                          variants={"motor": {"mount": False}}))
        self.assertNotIn("Motor mount join", no_mount)
        self.assertIn("Motor bolt holes", no_mount)
        loose = dm.build_script(compute(), None, sc.DEFAULT_DETAIL,
                                variants={"prop": {"join": False}})
        self.assertIn("REF_Prop_1_Blade_1", loose["bodies"])


if __name__ == "__main__":
    unittest.main()
