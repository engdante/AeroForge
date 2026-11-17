"""Регресионен тест: текущите изчисления трябва да съвпадат със златните снимки."""

import unittest

import _env  # noqa: F401
import _golden  # noqa: E402


class TestGoldenSnapshots(unittest.TestCase):
    def test_snapshots_match(self):
        for name in _golden.CASES:
            with self.subTest(case=name):
                expected = _golden.load(name)
                actual = _golden.snapshot(name)
                diffs = _golden.compare(expected, actual)
                self.assertEqual(diffs, [], "\n".join(diffs[:30]))


if __name__ == "__main__":
    unittest.main()
