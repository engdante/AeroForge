"""Регресионни тестове за мостовете (root gap) на опашните повърхности."""

import math
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import assembly, geometry3d  # noqa: E402
from test_config import base  # noqa: E402

FAST = {"points": 10, "stations": 3, "fuselage_ring": 14,
        "fuselage_stations": 3, "tail_stations": 3}


def part_names(model):
    return [part["name"] for part in model["parts"]]


class TestTailBridges(unittest.TestCase):
    def test_v_tail_has_root_bridge(self):
        """V-опашката има мост от панелите към тялото."""
        names = part_names(geometry3d.build_model(base(tail={"type": "v_tail"})))
        self.assertIn("Връзки корен опашка (V)", names)

    def test_t_tail_no_stabilizer_root_bridge(self):
        """T-опашката лежи на кила: без мост към тялото, но с мост за кила."""
        names = part_names(geometry3d.build_model(base(tail={"type": "t_tail"})))
        self.assertNotIn("Връзки корен опашка", names)
        self.assertIn("Връзка корен кил", names)

    def test_conventional_has_both_bridges(self):
        """Класическата опашка има мост за стабилизатора и за кила."""
        names = part_names(geometry3d.build_model(base()))
        self.assertIn("Връзки корен опашка", names)
        self.assertIn("Връзка корен кил", names)

    def test_v_tail_export_starts_away_from_fuselage(self):
        """V-панелът в експорта тръгва от кожата + луфта, не от центъра."""
        res = base(tail={"type": "v_tail"})
        fus = res["geometry"]["fuselage"]
        z_center = fus["height_mm"] / 2.0
        gamma = math.radians(float(res["layout"].get("v_tail_deg", 35.0)))
        bodies = assembly.loft_bodies(res, None, FAST, tail_root_gap_mm=10.0)
        by_name = {body["name"]: body for body in bodies}
        for key, sign in (("Stabilizer_V_R", 1.0),
                          ("Stabilizer_V_L", -1.0)):
            self.assertIn(key, by_name)
            section = by_name[key]["sections"][0]
            x, y, z = section["origin"]
            skin = assembly.skin_offset(
                fus, x, (0.0, sign * math.cos(gamma), math.sin(gamma)))
            radial = math.hypot(y, z - z_center)
            self.assertAlmostEqual(radial, skin + 10.0, places=2)
            self.assertAlmostEqual(radial, section["station_mm"], places=2)

    def test_t_tail_stabilizer_sits_on_fin_tip(self):
        """Стабилизаторът на T-опашката е на върха на кила, не над него."""
        res = base(tail={"type": "t_tail"})
        model = geometry3d.build_model(res)
        parts = {part["name"]: part for part in model["parts"]}
        fin_top = max(parts["Кил"]["points"][2::3])
        stab_bottom = min(parts["Стабилизатор"]["points"][2::3])
        self.assertLess(abs(stab_bottom - fin_top), 30.0)
        self.assertLessEqual(stab_bottom, fin_top)


def _tris(points):
    tri_list = []
    for i in range(0, len(points), 9):
        tri_list.append(tuple(
            (points[i + 3 * k], points[i + 1 + 3 * k], points[i + 2 + 3 * k])
            for k in range(3)))
    return tri_list


def _boundary_edges(tri_list):
    edges = {}
    for a, b, c in tri_list:
        for p, q in ((a, b), (b, c), (c, a)):
            key = (p, q) if p < q else (q, p)
            edges[key] = edges.get(key, 0) + 1
    return sum(1 for count in edges.values() if count == 1)


class TestBridgeOrientation(unittest.TestCase):
    """
    Регресионен тест: мостовете са затворени тела с навън сочещи нормали.
    Огледалната страна изисква обърната намотка — без нея отрицателният
    обем анулира положителния и тялото става неупотребимо в CAD.
    """

    BRIDGES = ("Връзки корен крило", "Връзки корен опашка",
               "Връзки корен опашка (V)", "Връзка корен кил")

    def _check(self, tail, expected):
        model = geometry3d.build_model(base(tail=tail), quality="high")
        names = part_names(model)
        for name in expected:
            self.assertIn(name, names)
        for part in model["parts"]:
            if part["name"] not in self.BRIDGES:
                continue
            tris = _tris(part["points"])
            self.assertEqual(_boundary_edges(tris), 0, part["name"])
            self.assertGreater(geometry3d._signed_volume(tris), 0.0,
                               part["name"])

    def test_bridges_are_closed_outward_for_every_tail(self):
        self._check({"type": "conventional"},
                    ("Връзки корен крило", "Връзки корен опашка",
                     "Връзка корен кил"))
        self._check({"type": "t_tail"},
                    ("Връзки корен крило", "Връзка корен кил"))
        self._check({"type": "v_tail"},
                    ("Връзки корен крило", "Връзки корен опашка (V)"))


if __name__ == "__main__":
    unittest.main()
