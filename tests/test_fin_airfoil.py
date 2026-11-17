"""
Регресия: килът (вертикалната опашка) трябва да е със СИМЕТРИЧЕН профил.

Профилът, избран за опашката, е за хоризонталните повърхности (те работят
като крило). Преди килът получаваше същия профил — с камбер беше
несиметричен спрямо равнината на самолета.
"""

import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import airfoils, assembly, design, geometry3d  # noqa: E402

CASE = {"name": "Fin", "mission": "trainer",
        "payload": {"mode": "simple", "total_g": 600}}


def compute(tail_airfoil, tail_type="conventional"):
    case = dict(CASE)
    case["tail"] = {"airfoil": tail_airfoil, "type": tail_type}
    return design.compute(case)


class TestFinAirfoil(unittest.TestCase):
    def test_every_catalog_profile_maps_to_a_symmetric_fin(self):
        for key in airfoils.AIRFOILS:
            fin = airfoils.fin_airfoil(key)
            self.assertTrue(airfoils.is_symmetric(fin), (key, fin))
            if airfoils.is_symmetric(key):
                self.assertEqual(fin, key)

    def test_closest_thickness_is_used(self):
        # Clark Y е ~11.7 % → NACA 0012; MH 32 е ~8.7 % → NACA 0009
        self.assertEqual(airfoils.fin_airfoil("clarky"), "naca0012")
        self.assertEqual(airfoils.fin_airfoil("mh32"), "naca0009")
        self.assertEqual(airfoils.fin_airfoil("непознат"), airfoils.DEFAULT_TAIL_AIRFOIL)

    def test_result_and_cad_use_the_symmetric_fin(self):
        res = compute("clarky")
        g = res["geometry"]
        self.assertEqual(g["tail_airfoil"], "clarky")
        self.assertEqual(g["fin_airfoil"], "naca0012")
        keys = {name: spec["airfoil_key"]
                for name, _f, spec in assembly.tail_specs(res)}
        self.assertEqual(keys["Fin"], "naca0012")
        self.assertEqual(keys["Stabilizer"], "clarky")

    def test_preview_fin_is_mirror_symmetric(self):
        for tail_type in ("conventional", "t_tail"):
            res = compute("clarky", tail_type)
            model = geometry3d.build_model(res, quality="normal")
            fin = [p for p in model["parts"] if p["name"] == "Кил"][0]
            ys = fin["points"][1::3]
            self.assertAlmostEqual(min(ys), -max(ys), places=1, msg=tail_type)
            # и всяка точка има огледална двойка
            pts = {(round(x, 1), round(y, 1), round(z, 1))
                   for x, y, z in zip(fin["points"][0::3], ys,
                                      fin["points"][2::3])}
            missing = [p for p in pts if (p[0], -p[1], p[2]) not in pts]
            self.assertEqual(missing, [], tail_type)

    def test_v_tail_keeps_the_chosen_profile(self):
        res = compute("clarky", "v_tail")
        keys = {name: spec["airfoil_key"]
                for name, _f, spec in assembly.tail_specs(res)}
        self.assertTrue(keys)
        self.assertTrue(all(k == "clarky" for k in keys.values()), keys)


if __name__ == "__main__":
    unittest.main()
