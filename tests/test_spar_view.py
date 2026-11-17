"""
Схемата „спар и джойнер“ (printgeom.spar_section) и интерфейсът без цени.
"""

import json
import os
import re
import shutil
import subprocess
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import design, printgeom  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
WEB = os.path.join(ROOT, "app", "web")

CASE = {"name": "Spar view", "mission": "trainer",
        "payload": {"mode": "simple", "total_g": 600}}


class TestSparSection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = design.compute(dict(CASE))
        cls.view = printgeom.spar_section(cls.res)

    def test_view_uses_root_chord_and_airfoil(self):
        g = self.res["geometry"]
        self.assertAlmostEqual(self.view["chord_mm"], g["c_root_mm"], places=1)
        self.assertEqual(self.view["airfoil"], g["airfoil"]["key"])
        xs = [p[0] for p in self.view["upper"]]
        self.assertAlmostEqual(min(xs), 0.0, places=1)
        self.assertAlmostEqual(max(xs), g["c_root_mm"], places=1)

    def test_caps_match_structure(self):
        st = self.res["structure"]
        cap = self.view["cap"]
        self.assertAlmostEqual(cap["width_mm"], st["cap_width_mm"], places=1)
        self.assertAlmostEqual(
            cap["x_mm"],
            printgeom.SPAR_CAP_CHORD_FRAC * self.view["chord_mm"], places=1)
        # горният капс е над долния и двата са вътре в профила
        self.assertGreater(cap["y_top_mm"], cap["y_bottom_mm"])
        # при карбон капсът е две ленти с процеп поне колкото лентата
        if self.view["carbon"]["needed"]:
            self.assertEqual(cap["strips"], 2)
            self.assertGreaterEqual(cap["gap_mm"],
                                    self.view["carbon"]["width_mm"])

    def test_joiner_matches_channel_and_tube(self):
        tube = self.res["structure"]["joiner_tube"]
        ch = printgeom.joiner_channel(self.res)
        j = self.view["joiner"]
        self.assertEqual(j["bore_mm"], ch["bore_mm"])
        self.assertEqual(j["x_mm"], ch["x_mm"])
        self.assertEqual(j["od_mm"], tube["od_mm"])
        self.assertEqual(j["id_mm"], tube["id_mm"])
        self.assertEqual(j["length_mm"], tube["length_mm"])

    def test_no_view_for_failed_result(self):
        self.assertIsNone(printgeom.spar_section({"ok": False}))
        self.assertIsNone(printgeom.spar_section(None))


class TestUiHasNoPrices(unittest.TestCase):
    """Интерфейсът показва само грамове/метри филамент, без цени."""

    def read(self, *parts):
        with open(os.path.join(WEB, *parts), encoding="utf-8-sig") as handle:
            return handle.read()

    def test_index_has_no_prices_or_profile_compare(self):
        html = self.read("index.html")
        for token in ("€", "EUR", "btnProfileCompare", "electronicsClass",
                      "bomTable"):
            self.assertNotIn(token, html)
        self.assertIn('id="sparCanvas"', html)
        self.assertIn('id="sparPlanCanvas"', html)

    def test_ui_scripts_show_no_prices(self):
        for name in ("ui.js", "settings.js"):
            text = self.read("js", name)
            self.assertNotIn("€", text, name)
            self.assertNotIn("compareProfiles", text, name)


@unittest.skipUnless(shutil.which("node"), "няма node")
class TestCheckTabs(unittest.TestCase):
    """Всяко предупреждение/грешка трябва да маркира някой таб на панела."""

    EXPECTED = {
        "Нужен е карбон за коравина": "structure",
        "Печатан спар не е достатъчен": "structure",
        "Голяма деформация на крилото": "structure",
        "Профил за крило без опашка": "wing",
        "Малък статичен запас": "tail",
        "Голямо разместване на батерията": "payload",
        "Батерията не влиза в носа": "fuselage",
        "Висок ток от батерията": "power",
        "Печат: частта не се побира": "print",
        "ESC над стандартния размер": "power",
        "Целевият ЦТ не е постижим": "tail",
        "Витлата са близо до тялото": "fuselage",
        "Къс нос за бутащо витло": "fuselage",
        "Конструкцията не може да носи себе си": "print",
        "Висок infill": "print",
    }

    def map_titles(self, titles):
        script = (
            "const fs = require('fs');"
            "global.document = {};"
            "eval(fs.readFileSync(process.argv[1], 'utf8').replace(/^\\ufeff/, '')"
            " + ';global.checkTab = checkTab;');"
            "const t = JSON.parse(fs.readFileSync(0, 'utf8'));"
            "console.log(JSON.stringify(t.map((x) => checkTab(x))));")
        proc = subprocess.run(
            ["node", "-e", script, os.path.join(WEB, "js", "ui.js")],
            input=json.dumps(titles), capture_output=True, text=True,
            encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_known_titles(self):
        titles = list(self.EXPECTED)
        self.assertEqual(self.map_titles(titles),
                         [self.EXPECTED[t] for t in titles])

    def test_every_warning_title_in_checks_has_a_tab(self):
        path = os.path.join(ROOT, "app", "core", "checks.py")
        with open(path, encoding="utf-8-sig") as handle:
            src = handle.read()
        titles = re.findall(r'_check\(\s*"(?:warn|error)",\s*"([^"]+)"', src)
        self.assertGreater(len(titles), 10)
        tabs = self.map_titles(titles)
        missing = [t for t, tab in zip(titles, tabs) if not tab]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
