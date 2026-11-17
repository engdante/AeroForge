"""Фаза 2: каталог на конструктивните материали, джойнер по якост, сравнение."""

import unittest

import _env  # noqa: F401

from core import design, structmat  # noqa: E402


class TestCatalogueFormulas(unittest.TestCase):
    def test_aluminium_10x8_matches_plan_values(self):
        # MASTER_PLAN §1.2: алуминий ø10/8 ≈ 76 g/m, EI ≈ 20 N·m², ~11.6 N·m
        self.assertAlmostEqual(
            structmat.tube_mass_g_per_m(10, 8, 2.70), 76.3, delta=0.2)
        self.assertAlmostEqual(
            structmat.tube_ei_nm2(10, 8, 69000), 20.0, delta=0.1)
        allowable = (structmat.tube_section_modulus_mm3(10, 8)
                     * 200.0 / 1000.0)
        self.assertAlmostEqual(allowable, 11.6, delta=0.1)

    def test_carbon_10x8_matches_plan_values(self):
        self.assertAlmostEqual(
            structmat.tube_mass_g_per_m(10, 8, 1.55), 43.8, delta=0.5)
        self.assertAlmostEqual(
            structmat.tube_ei_nm2(10, 8, 90000), 26.2, delta=0.2)

    def test_unknown_material_raises(self):
        with self.assertRaises(KeyError):
            structmat.get("bamboo")


class TestSelectTube(unittest.TestCase):
    def test_picks_lightest_tube_that_holds_the_moment(self):
        sel = structmat.select_tube("aluminium", 6.4)
        self.assertIsNotNone(sel)
        self.assertLessEqual(sel["stress_mpa"], sel["allow_mpa"])
        # по-лек от следващия по-голям профил с ОД 12
        self.assertLess(sel["mass_g_per_m"], 93.5)

    def test_returns_none_when_nothing_fits(self):
        self.assertIsNone(structmat.select_tube("aluminium", 500.0))


class TestDesignIntegration(unittest.TestCase):
    def _run(self, **structure):
        inp = {"name": "t", "mission": "trainer",
               "payload": {"mode": "simple", "total_g": 600}}
        if structure:
            inp["structure"] = structure
        return design.compute(inp)

    def test_default_is_carbon(self):
        res = self._run()
        self.assertEqual(res["structure"]["joiner_tube"]["material"],
                         "carbon")
        self.assertEqual(res["structure"]["spar_material"], "carbon")

    def test_aluminium_joiner_is_chosen_by_strength(self):
        res = self._run(joiner_material="aluminium")
        j = res["structure"]["joiner_tube"]
        self.assertEqual(j["material"], "aluminium")
        self.assertLessEqual(j["stress_mpa"], j["allow_mpa"])
        titles = [c["title"] for c in res["checks"]]
        self.assertTrue(any("Джойнер (Алуминий" in t for t in titles))

    def test_invalid_material_falls_back_to_carbon(self):
        res = self._run(spar_material="unobtainium")
        self.assertEqual(res["structure"]["spar_material"], "carbon")

    def test_comparison_has_all_combinations(self):
        res = self._run()
        rows = res["material_comparison"]
        self.assertEqual(len(rows), 3 * 4)
        for r in rows:
            self.assertGreaterEqual(r["mass_g"], 0.0)
            self.assertGreaterEqual(r["cost_eur"], 0.0)

    def test_structure_mass_is_included_in_total(self):
        # Джойнерът от стомана е по-тежък от въглеродния: общата маса расте.
        a = self._run()
        b = self._run(joiner_material="steel")
        self.assertGreater(b["weights"]["total_g"], a["weights"]["total_g"])

    def test_total_includes_structure_mass(self):
        # Общата маса покрива рамата: по-голямата част от бюджета са
        # печатаните части + конструкцията (спар и джойнер).
        res = self._run()
        self.assertGreaterEqual(res["weights"]["airframe_g"],
                                res["bom"]["structure_g"])

if __name__ == "__main__":
    unittest.main()
