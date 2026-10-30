"""
Тестове за потребителските настройки (settings.json).

Използва се временен файл — реалните настройки на потребителя не се пипат.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import design, materials, settings  # noqa: E402


class SettingsTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aeroforge_cfg_")
        self._orig_path = settings.SETTINGS_PATH
        settings.SETTINGS_PATH = os.path.join(self.tmp, "settings.json")
        settings.load()

    def tearDown(self):
        settings.SETTINGS_PATH = self._orig_path
        settings.load()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def current_catalog(self):
        return {key: materials.get(key) for key in list(materials.FILAMENTS)}


class TestDefaults(SettingsTestBase):
    def test_defaults_structure(self):
        d = settings.get_defaults()
        self.assertEqual(d["print"]["filament"], materials.DEFAULT_FILAMENT)
        self.assertIn("bed", d["print"])
        self.assertEqual(len(d["print"]["bed"]), 3)
        self.assertIn("cells", d["propulsion"])
        self.assertIn("mission", d["design"])
        self.assertGreater(d["design"]["payload_total_g"], 0)

    def test_ui_defaults(self):
        ui = settings.get_ui()
        self.assertEqual(ui["font"], settings.DEFAULT_UI["font"])
        self.assertEqual(ui["size"], settings.DEFAULT_UI["size"])
        self.assertIn("css", ui)
        self.assertIn("Segoe UI", ui["css"])

    def test_fonts_catalog(self):
        fonts = settings.fonts()
        self.assertGreaterEqual(len(fonts), 5)
        for font in fonts:
            self.assertIn("key", font)
            self.assertIn("label", font)
            self.assertIn("css", font)
        css = settings.get_font_css("consolas")
        self.assertIn("monospace", css)
        # непознат ключ → подразбираният шрифт
        self.assertEqual(settings.get_font_css("няма"), settings.FONTS[0]["css"])

    def test_defaults_are_copy(self):
        d = settings.get_defaults()
        d["print"]["filament"] = "нещо"
        self.assertNotEqual(settings.get_defaults()["print"]["filament"], "нещо")

    def test_not_custom_initially(self):
        self.assertFalse(settings.is_custom())
        self.assertFalse(os.path.exists(settings.SETTINGS_PATH))


class TestSaveAndApply(SettingsTestBase):
    def test_save_writes_file_and_applies_catalog(self):
        catalog = self.current_catalog()
        catalog["pla"]["price_per_kg"] = 33.0
        catalog["pla"]["printed_density"] = 1.30
        result = settings.save({"filaments": catalog})
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(os.path.exists(settings.SETTINGS_PATH))
        self.assertTrue(settings.is_custom())

        pla = materials.get("pla")
        self.assertAlmostEqual(pla["price_per_kg"], 33.0)
        self.assertAlmostEqual(pla["printed_density"], 1.30)

        with open(settings.SETTINGS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        self.assertIn("filaments", raw)
        self.assertAlmostEqual(raw["filaments"]["pla"]["price_per_kg"], 33.0)

    def test_garbage_numbers_are_sanitized(self):
        catalog = self.current_catalog()
        catalog["pla"]["price_per_kg"] = "колко"
        catalog["pla"]["printed_density"] = None
        result = settings.save({"filaments": catalog})
        self.assertTrue(result["ok"], result.get("error"))
        pla = materials.get("pla")
        self.assertEqual(pla["price_per_kg"], 25.0)      # fallback
        self.assertEqual(pla["printed_density"], 1.24)   # fallback

    def test_values_are_clamped_to_sane_limits(self):
        catalog = self.current_catalog()
        catalog["pla"]["printed_density"] = 0.0        # невъзможно лек
        catalog["pla"]["price_per_kg"] = 5000.0        # абсурдна цена
        catalog["pla"]["tensile_mpa"] = -10.0
        catalog["pla"]["expansion"] = 99.0
        result = settings.save({"filaments": catalog})
        self.assertTrue(result["ok"], result.get("error"))
        pla = materials.get("pla")
        self.assertGreaterEqual(pla["printed_density"], 0.1)
        self.assertLessEqual(pla["price_per_kg"], 1000.0)
        self.assertGreaterEqual(pla["tensile_mpa"], 1.0)
        self.assertLessEqual(pla["expansion"], 3.0)
        # дизайнът пак се изчислява
        res = design.compute({"payload": {"mode": "simple", "total_g": 600}})
        self.assertTrue(res["ok"])

    def test_empty_payload_rejected(self):
        self.assertFalse(settings.save({"filaments": {}})["ok"])
        self.assertFalse(settings.save("боклук")["ok"])

    def test_symbolic_keys_are_normalized(self):
        result = settings.save({"filaments": {
            "Моят ФИЛАМЕНТ": {"name": "Моят", "printed_density": 1.0,
                              "price_per_kg": 10},
        }})
        self.assertTrue(result["ok"], result.get("error"))
        self.assertIn("моят_филамент", materials.FILAMENTS)

    def test_catalog_change_affects_design_mass(self):
        before = design.compute({
            "mission": "trainer",
            "payload": {"mode": "simple", "total_g": 600},
        })["weights"]["airframe_g"]

        catalog = self.current_catalog()
        catalog["lw_pla"]["printed_density"] = 0.95   # почти плътен
        self.assertTrue(settings.save({"filaments": catalog})["ok"])

        after = design.compute({
            "mission": "trainer",
            "payload": {"mode": "simple", "total_g": 600},
        })["weights"]["airframe_g"]

        self.assertGreater(after, before * 1.3)

    def test_saved_defaults_used_for_new_design(self):
        result = settings.save({
            "filaments": self.current_catalog(),
            "defaults": {
                "print": {"filament": "pla", "nozzle": 0.6,
                          "perimeters": 2, "infill": 12,
                          "layer_height": 0.3, "bed": [300, 300, 400]},
                "propulsion": {"cells": 4, "endurance_min": 12},
                "design": {"mission": "sport", "payload_total_g": 800},
            },
        })
        self.assertTrue(result["ok"], result.get("error"))

        defaults = design.default_inputs()
        self.assertEqual(defaults["print"]["filament"], "pla")
        self.assertAlmostEqual(defaults["print"]["nozzle"], 0.6)
        self.assertEqual(defaults["print"]["perimeters"], 2)
        self.assertEqual(defaults["print"]["bed"], [300.0, 300.0, 400.0])
        self.assertEqual(defaults["propulsion"]["cells"], 4)
        self.assertEqual(defaults["mission"], "sport")
        self.assertAlmostEqual(defaults["payload"]["total_g"], 800.0)

    def test_unknown_default_filament_falls_back(self):
        result = settings.save({
            "filaments": self.current_catalog(),
            "defaults": {"print": {"filament": "няма_такъв"}},
        })
        self.assertTrue(result["ok"])
        self.assertIn(design.default_inputs()["print"]["filament"],
                      materials.FILAMENTS)

    def test_ui_settings_are_saved_and_applied(self):
        result = settings.save({
            "filaments": self.current_catalog(),
            "defaults": {"ui": {"font": "consolas", "size": 16}},
        })
        self.assertTrue(result["ok"], result.get("error"))
        ui = settings.get_ui()
        self.assertEqual(ui["font"], "consolas")
        self.assertEqual(ui["size"], 16)
        self.assertIn("monospace", ui["css"])
        # записва се и в самия файл
        with open(settings.SETTINGS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        self.assertEqual(raw["defaults"]["ui"]["size"], 16)

    def test_ui_size_is_clamped(self):
        for entered, expected in ((5, 11), (99, 20), (0, 11)):
            settings.save({
                "filaments": self.current_catalog(),
                "defaults": {"ui": {"size": entered}},
            })
            self.assertEqual(settings.get_ui()["size"], expected, entered)

    def test_unknown_font_falls_back_to_default(self):
        result = settings.save({
            "filaments": self.current_catalog(),
            "defaults": {"ui": {"font": "няма_такъв", "size": 14}},
        })
        self.assertTrue(result["ok"])
        self.assertEqual(settings.get_ui()["font"], settings.DEFAULT_UI["font"])



class TestReset(SettingsTestBase):
    def test_reset_removes_file_and_restores_builtin(self):
        catalog = self.current_catalog()
        catalog["pla"]["price_per_kg"] = 99.0
        settings.save({"filaments": catalog})
        self.assertAlmostEqual(materials.get("pla")["price_per_kg"], 99.0)

        result = settings.reset()
        self.assertTrue(result["ok"], result.get("error"))
        self.assertFalse(os.path.exists(settings.SETTINGS_PATH))
        self.assertFalse(settings.is_custom())
        self.assertAlmostEqual(
            materials.get("pla")["price_per_kg"],
            materials.BUILTIN_FILAMENTS["pla"]["price_per_kg"])


class TestBrokenFile(SettingsTestBase):
    def test_invalid_json_does_not_break(self):
        with open(settings.SETTINGS_PATH, "w", encoding="utf-8") as f:
            f.write("{ това не е json")
        self.assertFalse(settings.load())
        self.assertTrue(settings.get_error())
        # изчисленията работят с вградените стойности
        res = design.compute({"payload": {"mode": "simple", "total_g": 500}})
        self.assertTrue(res["ok"], res.get("error"))
        self.assertAlmostEqual(materials.get("pla")["price_per_kg"], 20.0)

    def test_partial_file_keeps_defaults(self):
        with open(settings.SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({"version": 1}, f)
        self.assertTrue(settings.load())
        defaults = settings.get_defaults()
        self.assertIn("print", defaults)
        self.assertIn("propulsion", defaults)
        res = design.compute({"payload": {"mode": "simple", "total_g": 500}})
        self.assertTrue(res["ok"])


if __name__ == "__main__":
    unittest.main()

