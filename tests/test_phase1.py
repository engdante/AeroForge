"""
Фаза 1 (MASTER_PLAN): автоматично крило, капацитет по желаното време,
C-граница и разрези за печат.
"""

import unittest

import _env  # noqa: F401

from core import design  # noqa: E402

MISSIONS = ["trainer", "sport", "3d", "glider", "flying_wing", "cargo"]
PAYLOADS = [200, 600, 1000]


def run(mission, payload, **extra):
    inp = {"name": "t", "mission": mission,
           "payload": {"mode": "simple", "total_g": payload}}
    inp.update(extra)
    return design.compute(inp)


class TestAutoWing(unittest.TestCase):
    def test_empty_wing_position_is_auto_and_balances(self):
        res = run("flying_wing", 200)
        self.assertTrue(res["ok"])
        self.assertTrue(res["stability"]["ready_to_fly"],
                        res["stability"]["blocking_checks"])
        geo = res["geometry"]
        self.assertAlmostEqual(geo["wing_le_mm"],
                               geo["wing_le_recommended_mm"], delta=5.0)

    def test_explicit_wing_position_is_kept(self):
        res = run("trainer", 600, wing={"wing_le_ratio": 0.30})
        fus = res["geometry"]["fuselage"]["length_mm"]
        self.assertAlmostEqual(res["geometry"]["wing_le_mm"], 0.30 * fus,
                               delta=0.5)


class TestBatteryFromEndurance(unittest.TestCase):
    def test_endurance_never_below_target(self):
        for m in MISSIONS:
            for p in PAYLOADS:
                with self.subTest(mission=m, payload=p):
                    b = run(m, p)["propulsion"]["battery"]
                    self.assertGreaterEqual(
                        b["endurance_min"],
                        b["endurance_target_min"] - 1e-6)

    def test_c_rate_stays_below_limit(self):
        for m in MISSIONS:
            for p in PAYLOADS:
                with self.subTest(mission=m, payload=p):
                    b = run(m, p)["propulsion"]["battery"]
                    self.assertLessEqual(b["c_rating_needed"], 35.0 + 1e-6)

    def test_manual_capacity_is_respected(self):
        res = run("trainer", 600, propulsion={"capacity_mah": 2200})
        self.assertAlmostEqual(res["propulsion"]["battery"]["capacity_mah"],
                               2200.0)


class TestReadyGrid(unittest.TestCase):
    def test_ready_for_all_mission_payload_pairs(self):
        bad = []
        for m in MISSIONS:
            for p in PAYLOADS:
                res = run(m, p)
                if not res["stability"]["ready_to_fly"]:
                    bad.append((m, p, res["stability"]["blocking_checks"]))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
