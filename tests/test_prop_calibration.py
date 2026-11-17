"""Калибровка на витлото (propulsion.py) спрямо APC PER3 данните."""

import json
import os
import statistics
import unittest

import _env  # noqa: F401

from core import propulsion  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "apc", "static_calibration.json")


def _load():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["props"]


def _fit(points):
    xs = [p["pitch_in"] / p["diameter_in"] for p in points]
    ys = [p["cp_static"] for p in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    b = (sum((x - mx) * (y - my) for x, y in zip(xs, ys))
         / sum((x - mx) ** 2 for x in xs))
    a = my - b * mx
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    return a, b, 1.0 - ss_res / ss_tot


class TestAprCalibration(unittest.TestCase):
    def setUp(self):
        self.points = _load()

    def test_fit_is_reasonable(self):
        _, _, r2 = _fit(self.points)
        self.assertGreater(r2, 0.8)

    def test_model_cp_matches_fit_at_model_pitch(self):
        # size_system ползва P = 0.6·D
        a, b, _ = _fit(self.points)
        self.assertAlmostEqual(propulsion.PROP_CP0, a + 0.6 * b, delta=0.002)

    def test_model_fom_matches_median(self):
        med = statistics.median(p["fom_static"] for p in self.points)
        self.assertAlmostEqual(propulsion.FIGURE_OF_MERIT, med, delta=0.01)

    def test_old_constant_was_underestimating_cp(self):
        # Старата стойност 0.030 е под всички средни точки при P/D ≈ 0.6
        self.assertGreater(statistics.median(
            p["cp_static"] for p in self.points), 0.030)


if __name__ == "__main__":
    unittest.main()
