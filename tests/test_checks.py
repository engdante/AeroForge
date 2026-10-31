"""Проверки за модула с инженерни проверки и съвместимия design API."""

import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import checks, design  # noqa: E402


class TestChecksModule(unittest.TestCase):
    def test_design_keeps_checks_api_compatible(self):
        self.assertIs(design.build_checks, checks.build_checks)
        self.assertIs(design._check, checks._check)

    def test_check_has_stable_result_shape(self):
        self.assertEqual(
            checks._check("warn", "Пример", "Обяснение"),
            {"level": "warn", "title": "Пример", "detail": "Обяснение"},
        )


if __name__ == "__main__":
    unittest.main()