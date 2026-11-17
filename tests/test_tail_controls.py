"""
Кормилата на опашката: височина (две половини), посока, руддерватори при
V-опашка — в изчислението, оразмеряването на сервата, 3D прегледа и
детайлния модел за SolidCraft.
"""

import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import controls, design, detailed_model as dm, geometry3d  # noqa: E402
from core import solidcraft_export as sc  # noqa: E402

BASE = {"name": "Tail", "mission": "trainer",
        "payload": {"mode": "simple", "total_g": 600}}


def compute(mission="trainer", tail_type="conventional", ctrl=None):
    case = dict(BASE, mission=mission)
    case["tail"] = {"type": tail_type}
    if ctrl is not None:
        case["tail"]["controls"] = ctrl
    return design.compute(case)


def labels(script):
    return [c["params"].get("name") for c in script["commands"]]


class TestTailControlsCore(unittest.TestCase):
    def test_defaults_follow_mission(self):
        tc = compute()["geometry"]["tail_controls"]
        self.assertTrue(tc["elevator"]["enabled"])
        self.assertTrue(tc["rudder"]["enabled"])
        self.assertAlmostEqual(tc["elevator"]["chord_frac"], 0.35)  # trainer
        self.assertAlmostEqual(tc["rudder"]["chord_frac"], 0.35)
        self.assertEqual(tc["elevator"]["kind"], "elevator")

    def test_percent_input_zero_disables_and_clamps(self):
        tc = compute(ctrl={"elevator_frac": 40, "rudder_frac": 0})["geometry"]["tail_controls"]
        self.assertAlmostEqual(tc["elevator"]["chord_frac"], 0.40)
        self.assertFalse(tc["rudder"]["enabled"])
        tc = compute(ctrl={"elevator_frac": 90})["geometry"]["tail_controls"]
        self.assertLessEqual(tc["elevator"]["chord_frac"], controls.TAIL_CHORD_RANGE[1])

    def test_v_tail_has_ruddervators_only(self):
        tc = compute(tail_type="v_tail")["geometry"]["tail_controls"]
        self.assertEqual(tc["elevator"]["kind"], "ruddervator")
        self.assertTrue(tc["elevator"]["enabled"])
        self.assertFalse(tc["rudder"]["enabled"])

    def test_flying_wing_has_none(self):
        tc = compute(mission="flying_wing")["geometry"]["tail_controls"]
        self.assertFalse(tc["elevator"]["enabled"])
        self.assertFalse(tc["rudder"]["enabled"])

    def test_servo_sizing_uses_the_tail_controls(self):
        keys = {s["key"]: s for s in controls.servo_sizing(compute())["surfaces"]}
        self.assertIn("elevator", keys)
        self.assertIn("rudder", keys)
        v = {s["key"]: s for s in controls.servo_sizing(compute(tail_type="v_tail"))["surfaces"]}
        self.assertEqual(v["ruddervator"]["count"], 2)
        self.assertNotIn("rudder", v)
        bigger = controls.servo_sizing(compute(ctrl={"elevator_frac": 50}))
        base = controls.servo_sizing(compute())
        el_big = [s for s in bigger["surfaces"] if s["key"] == "elevator"][0]
        el_base = [s for s in base["surfaces"] if s["key"] == "elevator"][0]
        self.assertGreater(el_big["torque_kgcm"], el_base["torque_kgcm"])


class TestTailControlsPreview(unittest.TestCase):
    def parts(self, **kw):
        model = geometry3d.build_model(compute(**kw), quality="normal")
        return {p["name"]: p for p in model["parts"]}

    def test_conventional_and_t_tail(self):
        for tail_type in ("conventional", "t_tail"):
            parts = self.parts(tail_type=tail_type)
            self.assertIn("Кормило за височина", parts, tail_type)
            self.assertIn("Кормило за посока", parts, tail_type)
            # рудерът е над стабилизатора (класическа) / под него (T)
            rud_z = parts["Кормило за посока"]["points"][2::3]
            el_z = parts["Кормило за височина"]["points"][2::3]
            if tail_type == "conventional":
                self.assertGreater(min(rud_z), max(el_z) - 1.0)
            else:
                self.assertLess(max(rud_z), min(el_z) + 1.0)

    def test_elevator_halves_are_mirrored(self):
        ys = self.parts()["Кормило за височина"]["points"][1::3]
        self.assertAlmostEqual(min(ys), -max(ys), places=1)

    def test_v_tail_ruddervators(self):
        parts = self.parts(tail_type="v_tail")
        self.assertIn("Руддерватор (дясно)", parts)
        self.assertIn("Руддерватор (ляво)", parts)

    def test_disabled_controls_are_not_drawn(self):
        parts = self.parts(ctrl={"elevator_frac": 0, "rudder_frac": 0})
        self.assertNotIn("Кормило за височина", parts)
        self.assertNotIn("Кормило за посока", parts)


class TestTailControlsDetailed(unittest.TestCase):
    def test_conventional_script(self):
        script = dm.build_script(compute(), None, sc.DEFAULT_DETAIL)
        names = labels(script)
        for side in ("R", "L"):
            self.assertIn("Elevator_%s from Stabilizer" % side, names)
            self.assertIn("Stabilizer %s hinge cove" % side, names)
            self.assertIn("Elevator_%s horn" % side, names)
            self.assertIn("Pushrod channel Elevator_%s" % side, names)
            # кормилото се взима преди сливането на стабилизатора с тялото
            self.assertLess(names.index("Elevator_%s from Stabilizer" % side),
                            names.index("Join Stabilizer"))
        self.assertIn("Rudder from Fin", names)
        self.assertIn("Fin hinge cove", names)
        self.assertIn("Pushrod channel Rudder", names)
        self.assertLess(names.index("Rudder from Fin"), names.index("Join Fin"))
        for body in ("Elevator_R", "Elevator_L", "Rudder", "Pushrod_Rudder",
                     "Pushrod_Elevator_R", "REF_Servo_Elevator", "REF_Servo_Rudder"):
            self.assertIn(body, script["bodies"])
        # тягите тръгват след сливането (каналът минава през тялото)
        self.assertGreater(names.index("Pushrod channel Rudder"),
                           names.index("Join Fin"))

    def test_tail_pins_are_thinner(self):
        script = dm.build_script(compute(), None, sc.DEFAULT_DETAIL)
        pins = {c["params"]["name"]: c["params"]["diameter"]
                for c in script["commands"]
                if c["command"] == "solid.cylinder"
                and c["params"]["name"].endswith("_PinHole")}
        self.assertEqual(pins["Rudder_PinHole"], dm.TAIL_PIN_D_MM)
        self.assertEqual(pins["Elevator_R_PinHole"], dm.TAIL_PIN_D_MM)
        self.assertEqual(pins["Aileron_R_PinHole"], dm.PIN_D_MM)

    def test_v_tail_script(self):
        script = dm.build_script(compute(tail_type="v_tail"), None, sc.DEFAULT_DETAIL)
        names = labels(script)
        for side in ("R", "L"):
            self.assertIn("Ruddervator_%s from Stabilizer_V_%s" % (side, side), names)
            self.assertIn("REF_Servo_Ruddervator_%s" % side, script["bodies"])
            self.assertIn("Pushrod_Ruddervator_%s" % side, script["bodies"])
        self.assertFalse(any(n and n.startswith("Rudder ") for n in names))

    def test_flying_wing_has_no_tail_controls(self):
        script = dm.build_script(compute(mission="flying_wing"), None,
                                 sc.DEFAULT_DETAIL)
        self.assertFalse(any(b.startswith(("Elevator", "Rudder", "Pushrod_E"))
                             for b in script["bodies"]))


class TestControlFallbacks(unittest.TestCase):
    def test_labels_map_to_controls(self):
        self.assertEqual(dm.control_of_label("Stabilizer L hinge cove"), "Elevator_L")
        self.assertEqual(dm.control_of_label("Fin knuckle 1"), "Rudder")
        self.assertEqual(dm.control_of_label("Wing R slot"), "Aileron_R")
        self.assertEqual(dm.control_of_label("Elevator_R pin hole"), "Elevator_R")
        self.assertEqual(dm.control_of_label("Stabilizer_V_R pin hole"),
                         "Ruddervator_R")
        self.assertIsNone(dm.control_of_label("Join Fin"))

    def test_failed_hinge_op_becomes_a_control_feature(self):
        script = dm.build_script(compute(), None, sc.DEFAULT_DETAIL)
        names = labels(script)
        i = names.index("Stabilizer L hinge cove")
        errors = [(str(i + 1), "solid.combine", "check refuses")]
        self.assertEqual(dm.failed_feature(errors, script["commands"]),
                         "Control Elevator_L")

    def test_control_variants_are_symmetric_and_end(self):
        v = dm.next_variants({}, "Control Elevator_L", 0)
        self.assertEqual(v["ctrl"], {"Elevator_R": 1, "Elevator_L": 1})
        v = dm.next_variants(v, "Control Elevator_L", 2)
        self.assertEqual(v["ctrl"]["Elevator_R"], 3)
        self.assertIsNone(dm.next_variants(v, "Control Elevator_L", 3))
        t = dm.next_variants({}, "Join Stabilizer_V_R", 0)
        self.assertEqual(t["thick"], {"Stabilizer_V_R": 1.0, "Stabilizer_V_L": 1.0})

    def test_levels_change_the_hinge(self):
        base = labels(dm.build_script(compute(), None, sc.DEFAULT_DETAIL))
        no_pin = labels(dm.build_script(compute(), None, sc.DEFAULT_DETAIL,
                                        variants={"ctrl": {"Rudder": 2}}))
        skip = dm.build_script(compute(), None, sc.DEFAULT_DETAIL,
                               variants={"ctrl": {"Rudder": 3}})
        self.assertIn("Fin knuckle 1", base)
        self.assertNotIn("Fin knuckle 1", no_pin)
        self.assertNotIn("Rudder_PinHole", no_pin)
        self.assertIn("Rudder from Fin", no_pin)
        self.assertNotIn("Rudder", skip["bodies"])
        self.assertNotIn("Pushrod_Rudder", skip["bodies"])


if __name__ == "__main__":
    unittest.main()
