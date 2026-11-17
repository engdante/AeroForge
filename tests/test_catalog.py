"""Редактируем каталог на цени (catalog.py): проверка, запис, припокриване."""

import os
import tempfile
import unittest

import _env  # noqa: F401

from core import catalog, design, profiles, structmat  # noqa: E402


def _base():
    return {"name": "c", "mission": "trainer",
            "payload": {"mode": "simple", "total_g": 600}}


class TestCatalogOverrides(unittest.TestCase):
    def tearDown(self):
        catalog.apply({"electronics": {}, "materials": {}})

    def test_override_changes_electronics_cost(self):
        before = profiles.electronics_cost("standard", 1, 1, 2, 1.0, True)
        catalog.apply({"electronics": {"standard": {"motor": 99.0}},
                       "materials": {}})
        after = profiles.electronics_cost("standard", 1, 1, 2, 1.0, True)
        motor_before = [x for x in before if x["name"] == "Мотор"][0]
        motor_after = [x for x in after if x["name"] == "Мотор"][0]
        self.assertAlmostEqual(motor_after["unit_eur"], 99.0)
        self.assertNotAlmostEqual(motor_before["unit_eur"], 99.0)

    def test_material_price_override_reaches_bom(self):
        base = design.compute(_base())["bom"]["structure_eur"]
        catalog.apply({"electronics": {}, "materials": {"carbon": 2000.0}})
        dear = design.compute(_base())["bom"]["structure_eur"]
        self.assertGreaterEqual(dear, base)
        self.assertAlmostEqual(structmat.get("carbon")["price_eur_kg"], 2000.0)

    def test_reset_restores_builtin_prices(self):
        catalog.apply({"electronics": {}, "materials": {"steel": 50.0}})
        catalog.apply({"electronics": {}, "materials": {}})
        self.assertEqual(structmat.get("steel")["price_eur_kg"],
                         structmat.MATERIALS["steel"]["price_eur_kg"])


class TestCatalogFile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, catalog.CATALOG_NAME)

    def tearDown(self):
        catalog.reset(self.path)

    def test_save_then_read_roundtrip(self):
        catalog.save(self.path, {"electronics": {"budget": {"esc": "9.5"}},
                                 "materials": {"aluminium": 13}})
        data = catalog.read(self.path)
        self.assertAlmostEqual(data["electronics"]["budget"]["esc"], 9.5)
        self.assertAlmostEqual(
            data["materials"]["aluminium"]["price_eur_kg"], 13.0)

    def test_material_properties_roundtrip_and_apply(self):
        from core import structmat
        catalog.save(self.path, {"materials": {
            "aluminium": {"density": 2.8, "e_mpa": 70000,
                          "allow_mpa": 240, "price_eur_kg": 9}}})
        mat = structmat.get("aluminium")
        self.assertAlmostEqual(mat["density"], 2.8)
        self.assertAlmostEqual(mat["e_mpa"], 70000.0)
        self.assertAlmostEqual(mat["allow_mpa"], 240.0)
        self.assertAlmostEqual(mat["price_eur_kg"], 9.0)
        catalog.reset(self.path)
        self.assertAlmostEqual(structmat.get("aluminium")["density"], 2.70)

    def test_rejects_implausible_material_properties(self):
        for bad in ({"density": 0}, {"e_mpa": -5}, {"allow_mpa": 1e9},
                    {"laser": 1}):
            with self.assertRaises(ValueError):
                catalog.validate({"materials": {"carbon": bad}})

    def test_rejects_unknown_keys_and_negative_values(self):
        for bad in ({"electronics": {"gold": {"esc": 1}}},
                    {"electronics": {"budget": {"laser": 1}}},
                    {"electronics": {"budget": {"esc": -3}}},
                    {"materials": {"bamboo": 5}},
                    {"materials": {"steel": "много"}}):
            with self.assertRaises(ValueError):
                catalog.validate(bad)

    def test_broken_file_falls_back_to_builtin(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        self.assertEqual(catalog.read(self.path),
                         {"electronics": {}, "materials": {}})

    def test_effective_lists_defaults_and_values(self):
        eff = catalog.effective()
        self.assertIn("standard", eff["electronics"])
        self.assertIn("carbon", eff["materials"])
        self.assertIn("defaults", eff)


if __name__ == "__main__":
    unittest.main()
