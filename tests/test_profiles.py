"""Фаза 3: профили, цени (EUR) и BOM."""

import copy
import unittest

import _env  # noqa: F401

from core import design, profiles  # noqa: E402


def base_inputs(mission="trainer", payload=600):
    return {"name": "p", "mission": mission,
            "payload": {"mode": "simple", "total_g": payload}}


class TestProfiles(unittest.TestCase):
    def test_apply_sets_materials_and_leaves_original_untouched(self):
        original = base_inputs()
        snapshot = copy.deepcopy(original)
        out = profiles.apply(original, "budget")
        self.assertEqual(original, snapshot)
        self.assertEqual(out["structure"]["spar_material"], "aluminium")
        self.assertEqual(out["print"]["filament"],
                         profiles.PROFILES["budget"]["filament"])
        self.assertEqual(out["bom"]["profile"], "budget")

    def test_unknown_profile_raises(self):
        with self.assertRaises(KeyError):
            profiles.apply(base_inputs(), "ultra")

    def test_budget_is_cheaper_than_highend(self):
        totals = {}
        for key in ("budget", "highend"):
            res = design.compute(profiles.apply(base_inputs(), key))
            totals[key] = res["bom"]["total_eur"]
        self.assertLess(totals["budget"], totals["highend"])


class TestProfilesAreFlyable(unittest.TestCase):
    def test_every_profile_is_ready_for_600g_trainer(self):
        for key in profiles.PROFILES:
            res = design.compute(profiles.apply(base_inputs(), key))
            self.assertTrue(res["stability"]["ready_to_fly"],
                            (key, res["stability"]["blocking_checks"]))


class TestDefaultFilaments(unittest.TestCase):
    def test_budget_and_standard_use_asa_with_one_perimeter(self):
        for key in ("budget", "standard"):
            prof = profiles.PROFILES[key]
            self.assertEqual(prof["filament"], "asa")
            self.assertEqual(prof["perimeters"], 1)

    def test_highend_keeps_lw_pla(self):
        self.assertEqual(profiles.PROFILES["highend"]["filament"], "lw_pla")

    def test_apply_copies_perimeters_and_infill(self):
        out = profiles.apply({}, "budget")
        self.assertEqual(out["print"]["perimeters"], 1)
        self.assertEqual(out["print"]["infill"], 5)


class TestBom(unittest.TestCase):
    def test_total_is_sum_of_parts(self):
        bom = design.compute(base_inputs())["bom"]
        self.assertAlmostEqual(
            bom["total_eur"],
            bom["print_eur"] + bom["structure_eur"] + bom["electronics_eur"],
            places=6)
        self.assertAlmostEqual(
            bom["electronics_eur"],
            sum(x["total_eur"] for x in bom["electronics_lines"]), places=6)

    def test_electronics_class_is_validated(self):
        inp = base_inputs()
        inp["bom"] = {"electronics": "gold-plated"}
        res = design.compute(inp)
        self.assertEqual(res["bom"]["electronics_class"], "standard")

    def test_battery_line_scales_with_capacity(self):
        lines = profiles.electronics_cost("budget", 1, 1, 4, 2.0, True)
        bat = [x for x in lines if x["name"].startswith("Батерия")][0]
        self.assertAlmostEqual(bat["total_eur"], 20.0)


class TestBedPresets(unittest.TestCase):
    def test_smaller_bed_needs_at_least_as_many_pieces(self):
        from core import printcost
        geom = design.compute(base_inputs("3d", 600))["geometry"]
        tail = {"c_h_mm": 0, "c_v_mm": 0}
        small = printcost.split_plan(geom, tail, {"bed": [180.0] * 3})
        big = printcost.split_plan(geom, tail, {"bed": [256.0] * 3})
        self.assertGreaterEqual(small["wing_chord_pieces"],
                                big["wing_chord_pieces"])
        self.assertGreaterEqual(small["wing_span_pieces"],
                                big["wing_span_pieces"])

if __name__ == "__main__":
    unittest.main()
