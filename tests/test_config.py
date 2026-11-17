"""
Интеграционни тестове за конфигурацията: тяло, двигатели, опашка.

Проверява се, че изборът на потребителя стига до изчисленията (ЦТ,
маса, печат, 3D) и че стари входни данни продължават да работят.
"""

import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import design, geometry3d, weight  # noqa: E402


def base(**overrides):
    inputs = {"mission": "trainer",
              "payload": {"mode": "simple", "total_g": 600},
              "print": {"filament": "lw_pla", "perimeters": 1, "infill": 0}}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(inputs.get(key), dict):
            inputs[key] = dict(inputs[key], **value)
        else:
            inputs[key] = value
    return design.compute(inputs)


class TestDefaultsAreBackwardsCompatible(unittest.TestCase):
    def test_empty_input_still_computes(self):
        res = design.compute({})
        self.assertTrue(res["ok"], res.get("error"))

    def test_default_layout_is_tractor(self):
        res = base()
        self.assertEqual(res["layout"]["propulsion"], "tractor")
        self.assertEqual(res["layout"]["tail_type"], "conventional")
        self.assertEqual(res["layout"]["motor_count"], 1)

    def test_fuselage_block_present(self):
        fus = base()["geometry"]["fuselage"]
        for key in ("length_mm", "width_mm", "height_mm", "shape",
                    "wetted_area_mm2", "volume_cm3", "battery_bay_mm",
                    "slenderness", "auto"):
            self.assertIn(key, fus)

    def test_old_saved_inputs_without_new_blocks(self):
        res = design.compute({
            "name": "стар дизайн", "mission": "sport",
            "payload": {"mode": "simple", "total_g": 500},
            "wing": {"airfoil": "clarky"}, "tail": {"vh": 0.5},
            "fusion": {"ignored": True},
        })
        self.assertTrue(res["ok"])
        self.assertIn("fuselage", res["inputs"])
        self.assertIn("layout", res["inputs"])

    def test_wing_and_tail_root_gap_default_to_ten_and_are_clamped(self):
        default = base()
        self.assertEqual(default["inputs"]["layout"]["wing_root_gap_mm"], 10.0)
        self.assertEqual(default["inputs"]["layout"]["tail_root_gap_mm"], 10.0)
        self.assertEqual(default["layout"]["wing_root_gap_mm"], 10.0)
        self.assertEqual(default["layout"]["tail_root_gap_mm"], 10.0)
        self.assertEqual(base(layout={"wing_root_gap_mm": 22})
                         ["inputs"]["layout"]["wing_root_gap_mm"], 22.0)
        self.assertEqual(base(layout={"wing_root_gap_mm": 90})
                         ["inputs"]["layout"]["wing_root_gap_mm"], 40.0)
        self.assertEqual(base(layout={"wing_root_gap_mm": -5})
                         ["inputs"]["layout"]["wing_root_gap_mm"], 0.0)
        self.assertEqual(base(layout={"tail_root_gap_mm": 22})
                         ["inputs"]["layout"]["tail_root_gap_mm"], 22.0)
        self.assertEqual(base(layout={"tail_root_gap_mm": 90})
                         ["inputs"]["layout"]["tail_root_gap_mm"], 40.0)
        self.assertEqual(base(layout={"tail_root_gap_mm": -5})
                         ["inputs"]["layout"]["tail_root_gap_mm"], 0.0)
        # Backwards compatibility: стария ключ root_gap_mm се прилага за двете
        legacy = base(layout={"root_gap_mm": 15})
        self.assertEqual(legacy["inputs"]["layout"]["wing_root_gap_mm"], 15.0)
        self.assertEqual(legacy["inputs"]["layout"]["tail_root_gap_mm"], 15.0)


class TestFuselageControl(unittest.TestCase):
    def test_length_override_changes_tail_and_mass(self):
        short = base(fuselage={"length_mm": 700})
        long_ = base(fuselage={"length_mm": 1100})
        self.assertLess(short["geometry"]["fuselage"]["length_mm"],
                        long_["geometry"]["fuselage"]["length_mm"])
        self.assertLess(short["geometry"]["tail"]["l_h_mm"],
                        long_["geometry"]["tail"]["l_h_mm"])
        self.assertGreater(short["geometry"]["tail"]["s_h_dm2"],
                           long_["geometry"]["tail"]["s_h_dm2"])

    def test_width_override_respected(self):
        res = base(fuselage={"width_mm": 90})
        self.assertAlmostEqual(res["geometry"]["fuselage"]["width_mm"], 90.0,
                               places=1)

    def test_height_ratio(self):
        wide = base(fuselage={"height_ratio": 1.6})
        narrow = base(fuselage={"height_ratio": 1.0})
        self.assertGreater(wide["geometry"]["fuselage"]["height_mm"],
                           narrow["geometry"]["fuselage"]["height_mm"])

    def test_shape_changes_wetted_area_and_mass(self):
        ellipse = base(fuselage={"shape": "ellipse"})
        boxy = base(fuselage={"shape": "boxy"})
        self.assertGreater(boxy["geometry"]["fuselage"]["wetted_area_mm2"],
                           ellipse["geometry"]["fuselage"]["wetted_area_mm2"])
        self.assertGreater(boxy["weights"]["airframe_g"],
                           ellipse["weights"]["airframe_g"])

    def test_frames_add_material(self):
        none = base(fuselage={"frames": 0})
        many = base(fuselage={"frames": 8})
        self.assertGreater(many["weights"]["airframe_g"],
                           none["weights"]["airframe_g"])

    def test_boom_moves_mass_forward(self):
        printed = base(fuselage={"tail_boom": "printed"})
        boom = base(fuselage={"tail_boom": "carbon_tube"})
        # По-леката опашка мести ЦТ напред, затова батерията трябва да е
        # по-назад, за да стигне същия целеви запас.
        self.assertLess(boom["stability"]["x_cg_before_mm"],
                        printed["stability"]["x_cg_before_mm"])
        self.assertGreater(boom["stability"]["battery_x_required_mm"],
                           printed["stability"]["battery_x_required_mm"])

    def test_manual_flag(self):
        self.assertTrue(base(fuselage={"length_mm": 900})["geometry"]
                        ["fuselage"]["manual"]["length"])
        self.assertFalse(base()["geometry"]["fuselage"]["manual"]["length"])


class TestMotorPlacement(unittest.TestCase):
    def test_pusher_moves_cg_back(self):
        # При фиксирано крило (иначе автоматичното крило балансира и двете)
        tractor = base(wing={"wing_le_ratio": 0.3})
        pusher = base(layout={"propulsion": "pusher"},
                      wing={"wing_le_ratio": 0.3})
        self.assertGreater(pusher["stability"]["cg_pct_mac"],
                           tractor["stability"]["cg_pct_mac"])

    def test_pusher_reports_note_and_auto_wing_balances_it(self):
        # Крилото е на автоматично позициониране: при бутащо витло то се
        # премества напред и моделът става балансиран. Бележката остава.
        res = base(layout={"propulsion": "pusher"})
        titles = [c["title"] for c in res["checks"]]
        self.assertIn("Бутащо витло", titles)
        self.assertTrue(res["stability"]["ready_to_fly"])
        self.assertAlmostEqual(res["geometry"]["wing_le_mm"],
                               res["geometry"]["wing_le_recommended_mm"])

    def test_twin_uses_two_motors(self):
        res = design.compute({
            "mission": "trainer",
            "payload": {"mode": "components", "components": [
                {"name": "Батерия", "category": "battery", "qty": 1,
                 "unit_mass_g": 180},
            ]},
            "layout": {"propulsion": "twin"},
        })
        motors = [c for c in res["weights"]["components"]
                  if c["category"] == "motor"]
        self.assertTrue(motors)
        self.assertEqual(motors[0]["qty"], 2)
        self.assertEqual(res["layout"]["motor_count"], 2)

    def test_twin_motor_position_is_on_wing(self):
        res = design.compute({
            "mission": "trainer",
            "payload": {"mode": "components", "components": [
                {"name": "Батерия", "category": "battery", "qty": 1,
                 "unit_mass_g": 180},
            ]},
            "layout": {"propulsion": "twin"},
        })
        motor = [c for c in res["weights"]["components"]
                 if c["category"] == "motor"][0]
        g = res["geometry"]
        self.assertAlmostEqual(motor["x_mm"],
                               g["wing_le_mm"] + 0.25 * g["mac_mm"],
                               delta=1.0)

    def test_unknown_layout_falls_back_to_tractor(self):
        res = base(layout={"propulsion": "rocket"})
        self.assertEqual(res["layout"]["propulsion"], "tractor")


class TestTailTypes(unittest.TestCase):
    def test_v_tail_panel_is_reported(self):
        res = base(tail={"type": "v_tail", "v_deg": 40})
        panel = res["layout"]["v_tail"]
        self.assertIsNotNone(panel)
        self.assertGreaterEqual(panel["s_panel_m2"],
                               res["geometry"]["tail"]["s_h_dm2"] / 100.0
                               - 1e-9)
        self.assertAlmostEqual(res["layout"]["v_tail_deg"], 40.0, places=6)

    def test_v_tail_keeps_required_areas(self):
        res = base(tail={"type": "v_tail"})
        tail = res["geometry"]["tail"]
        panel = res["layout"]["v_tail"]
        self.assertGreaterEqual(panel["s_h_eff_m2"],
                               tail["s_h_dm2"] / 100.0 - 1e-9)
        self.assertGreaterEqual(panel["s_v_eff_m2"],
                               tail["s_v_dm2"] / 100.0 - 1e-9)

    def test_t_tail_has_no_effect_on_stability(self):
        conv = base()
        ttail = base(tail={"type": "t_tail"})
        self.assertAlmostEqual(conv["stability"]["x_np_mm"],
                               ttail["stability"]["x_np_mm"], places=6)

    def test_tail_type_reaches_3d(self):
        conv = geometry3d.build_model(base())
        vtail = geometry3d.build_model(base(tail={"type": "v_tail"}))
        conv_names = [p["name"] for p in conv["parts"]]
        v_names = [p["name"] for p in vtail["parts"]]
        self.assertIn("Стабилизатор", conv_names)
        self.assertIn("Стабилизатор (V)", v_names)
        self.assertNotIn("Стабилизатор", v_names)

    def test_t_tail_is_higher(self):
        conv = geometry3d.build_model(base())
        ttail = geometry3d.build_model(base(tail={"type": "t_tail"}))
        self.assertGreater(ttail["size"]["height_mm"],
                           conv["size"]["height_mm"])


class TestLayoutIn3D(unittest.TestCase):
    def test_pusher_motor_is_at_the_tail(self):
        res = base(layout={"propulsion": "pusher"})
        model = geometry3d.build_model(res)
        motor = [p for p in model["parts"] if p["name"] == "Мотор"][0]
        xs = motor["points"][0::3]
        self.assertGreater(min(xs),
                           0.9 * res["geometry"]["fuselage"]["length_mm"])

    def test_twin_has_two_motors(self):
        model = geometry3d.build_model(base(layout={"propulsion": "twin"}))
        names = [p["name"] for p in model["parts"]]
        self.assertIn("Мотор", names)
        self.assertIn("Мотор (2)", names)

    def test_wing_position_changes_height(self):
        high = geometry3d.build_model(base(layout={"wing_position": "high"}))
        low = geometry3d.build_model(base(layout={"wing_position": "low"}))
        z_high = [p for p in high["parts"] if p["name"] == "Крило"][0]
        z_low = [p for p in low["parts"] if p["name"] == "Крило"][0]
        avg_high = sum(z_high["points"][2::3]) / (len(z_high["points"]) / 3)
        avg_low = sum(z_low["points"][2::3]) / (len(z_low["points"]) / 3)
        self.assertGreater(avg_high, avg_low + 20.0)


class TestAirframeShares(unittest.TestCase):
    def test_shares_sum_to_one(self):
        items = weight.airframe_items(100.0, 900.0, 300.0, 180.0)
        self.assertAlmostEqual(sum(i["mass_g"] for i in items), 100.0,
                               places=6)

    def test_boom_makes_tail_lighter(self):
        printed = weight.airframe_items(100.0, 900.0, 300.0, 180.0)
        boom = weight.airframe_items(100.0, 900.0, 300.0, 180.0,
                                     tail_boom="carbon_tube")
        self.assertLess(boom[-1]["mass_g"], printed[-1]["mass_g"])

    def test_flying_wing_has_two_items(self):
        items = weight.airframe_items(100.0, 500.0, 200.0, 150.0,
                                      has_tail=False)
        self.assertEqual(len(items), 2)


if __name__ == "__main__":
    unittest.main()
