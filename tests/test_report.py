"""
Тестове за отчетите и експорта (Markdown, HTML, BOM, JSON).
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import design, report  # noqa: E402


class TestReports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = design.compute({
            "name": "Отчет Тест",
            "mission": "trainer",
            "payload": {"mode": "simple", "total_g": 600},
        })

    def test_markdown_contains_sections(self):
        md = report.build_report_markdown(self.res)
        self.assertIn("AeroForge", md)
        self.assertIn("Отчет Тест", md)
        for heading in ("1. Обобщение", "2. Товар и маси",
                        "3. Крило и аеродинамика", "5. Задвижване",
                        "6. Якост на крилото", "7. Печат", "8. Проверки"):
            self.assertIn(heading, md)
        self.assertIn(report.DISCLAIMER, md)

    def test_markdown_numbers_present(self):
        md = report.build_report_markdown(self.res)
        self.assertIn("%.0f g" % self.res["weights"]["total_g"], md)
        self.assertIn("%.0f mm" % self.res["geometry"]["span_mm"], md)

    def test_html_is_standalone(self):
        html = report.build_report_html(self.res)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn('charset="utf-8"', html)
        self.assertIn("<style>", html)
        self.assertNotIn("<script", html)
        self.assertIn("Отчет Тест", html)
        self.assertIn("Проверки", html)

    def test_html_escapes_user_input(self):
        res = design.compute({
            "name": "<script>alert(1)</script>",
            "payload": {"mode": "simple", "total_g": 500},
        })
        html = report.build_report_html(res)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_bom_csv_parses(self):
        import csv
        text = report.build_bom_csv(self.res)
        rows = list(csv.reader(io.StringIO(text), delimiter=";"))
        self.assertEqual(rows[0][0], "#")
        self.assertEqual(rows[0][1], "Компонент")
        self.assertEqual(len(rows[0]), 9)

        parts_header = [i for i, r in enumerate(rows)
                        if len(r) > 1 and r[0] == "#" and
                        r[1].startswith("Печатана")]
        self.assertEqual(len(parts_header), 1)
        cut = parts_header[0]

        component_rows = [r for r in rows[1:cut] if r and r[0].isdigit()]
        self.assertGreater(len(component_rows), 0)
        for row in component_rows:
            self.assertEqual(len(row), 9)

        part_rows = [r for r in rows[cut + 1:] if r and r[0].isdigit()]
        self.assertGreater(len(part_rows), 0)
        for row in part_rows:
            self.assertEqual(len(row), 8)

        total_line = [r for r in rows[1:cut] if "ОБЩО" in r]
        self.assertEqual(len(total_line), 1)

    def test_slugify(self):
        self.assertEqual(report.slugify("Мой дизайн 1"), "Мой_дизайн_1")
        self.assertEqual(report.slugify('a/b\\c:d*e'), "a_b_c_d_e")
        self.assertEqual(report.slugify(""), "design")


class TestExport(unittest.TestCase):
    def test_export_writes_files(self):
        res = design.compute({
            "name": "Export Test",
            "payload": {"mode": "simple", "total_g": 600},
        })
        tmp = tempfile.mkdtemp(prefix="aeroforge_")
        try:
            paths = report.export_design(res, tmp)
            for name in ("report.md", "report.html", "BOM.csv",
                         "design.json"):
                self.assertIn(name, paths)
                self.assertTrue(os.path.exists(paths[name]), name)
                self.assertGreater(os.path.getsize(paths[name]), 100)

            with open(paths["design.json"], encoding="utf-8") as f:
                data = json.load(f)
            self.assertTrue(data["ok"])
            self.assertEqual(data["inputs"]["name"], "Export Test")

            with open(paths["BOM.csv"], encoding="utf-8-sig") as f:
                self.assertIn("Компонент", f.readline())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
