"""
Тестове за backend слоя (server.py) — същите функции, които вика браузърът.

Изисква инсталиран `eel`; ако липсва, тестовете се пропускат.
"""

import importlib.util
import os
import shutil
import sys
import unittest

APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
import _env  # noqa: F401  (sys.path + изолирани настройки)

HAS_EEL = importlib.util.find_spec("eel") is not None

server = None
if HAS_EEL:
    import server  # noqa: E402  (инициализира и eel.init)


@unittest.skipUnless(HAS_EEL, "eel не е инсталиран")
class TestPresetsPayload(unittest.TestCase):
    def test_get_presets_shape(self):
        p = server.get_presets()
        for key in ("version", "missions", "filaments", "airfoils",
                    "categories", "defaults", "paths"):
            self.assertIn(key, p)
        self.assertGreaterEqual(len(p["missions"]), 6)
        self.assertGreaterEqual(len(p["filaments"]), 8)
        for mission in p["missions"]:
            self.assertIn("key", mission)
            self.assertIn("wing_loading", mission)
        # defaults трябва да е сериализируемо (както го праща Eel)
        import json
        json.dumps(p, ensure_ascii=False)

    def test_airfoil_shape(self):
        shape = server.airfoil_shape("naca2412")
        self.assertTrue(shape["ok"])
        self.assertFalse(shape["approximate"])
        self.assertEqual(len(shape["upper"]), 81)
        self.assertEqual(len(shape["lower"]), 81)
        # всички координати в рамките на хордата
        for x, y in shape["upper"]:
            self.assertGreaterEqual(x, -0.01)
            self.assertLessEqual(x, 1.01)

    def test_airfoil_shape_by_naca_code(self):
        shape = server.airfoil_shape("4412")
        self.assertTrue(shape["ok"])
        self.assertFalse(shape["approximate"])

    def test_airfoil_shape_approximate_for_catalog_profiles(self):
        for key in ("clarky", "s1223", "mh32", "e205", "mh45"):
            shape = server.airfoil_shape(key)
            self.assertTrue(shape["ok"], key)
            self.assertTrue(shape["approximate"], key)
            self.assertGreater(len(shape["upper"]), 20)
            ys = [p[1] for p in shape["upper"] + shape["lower"]]
            self.assertLess(max(ys) - min(ys), 0.4)

    def test_airfoil_shape_invalid(self):
        self.assertFalse(server.airfoil_shape("xyz")["ok"])
        self.assertFalse(server.airfoil_shape(None)["ok"])

    def test_get_settings_has_catalog_and_defaults(self):
        data = server.get_settings()
        self.assertIn("filaments", data)
        self.assertIn("defaults", data)
        self.assertIn("path", data)
        keys = [f["key"] for f in data["filaments"]]
        self.assertIn("lw_pla", keys)
        for filament in data["filaments"]:
            for field in ("printed_density", "price_per_kg", "tensile_mpa",
                          "e_mpa", "layer_factor", "max_flow", "expansion"):
                self.assertIn(field, filament)

    def test_settings_have_fonts_and_ui(self):
        data = server.get_settings()
        self.assertIn("fonts", data)
        self.assertIn("size_range", data)
        self.assertIn("ui", data["defaults"])
        self.assertIn("font", data["defaults"]["ui"])
        self.assertIn("size", data["defaults"]["ui"])
        self.assertGreaterEqual(len(data["fonts"]), 5)
        self.assertEqual(len(data["size_range"]), 2)

    def test_presets_include_ui_with_css(self):
        data = server.get_presets()
        self.assertIn("ui", data)
        self.assertIn("css", data["ui"])
        self.assertIsInstance(data["ui"]["size"], int)
        self.assertIn("sans-serif", data["ui"]["css"])

    def test_get_model3d(self):
        model = server.get_model3d({
            "mission": "trainer",
            "payload": {"mode": "simple", "total_g": 600},
            "print": {"filament": "lw_pla", "perimeters": 1, "infill": 0},
        })
        self.assertTrue(model["ok"], model.get("error"))
        self.assertGreaterEqual(len(model["parts"]), 4)
        self.assertGreater(model["triangles"], 400)
        self.assertIn("span_mm", model["size"])
        # всяка част е плоска последователност от триъгълници
        for part in model["parts"]:
            self.assertEqual(len(part["points"]) % 9, 0)


@unittest.skipUnless(HAS_EEL, "eel не е инсталиран")
class TestComputeAndExport(unittest.TestCase):
    def test_compute_design(self):
        res = server.compute_design({
            "name": "Backend тест",
            "mission": "trainer",
            "payload": {"mode": "simple", "total_g": 600},
        })
        self.assertTrue(res["ok"], res.get("error"))
        self.assertIn("geometry", res)

    def test_compute_design_bad_input_returns_error(self):
        res = server.compute_design("това не е dict")
        self.assertFalse(res["ok"])
        self.assertIn("error", res)

    def test_export_report_writes_into_exports(self):
        res = server.export_report({
            "name": "Backend Export",
            "payload": {"mode": "simple", "total_g": 500},
        })
        self.assertTrue(res["ok"], res.get("error"))
        folder = res["paths"]["folder"]
        try:
            self.assertTrue(os.path.isdir(folder))
            self.assertTrue(folder.startswith(server.EXPORT_DIR))
            for name in ("report.html", "report.md", "BOM.csv",
                         "design.json"):
                self.assertTrue(os.path.exists(os.path.join(folder, name)))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


@unittest.skipUnless(HAS_EEL, "eel не е инсталиран")
class TestDesignStorage(unittest.TestCase):
    NAME = "AeroForge Backend Test"

    def tearDown(self):
        server.delete_design(self.NAME)

    def test_save_load_list_delete(self):
        inputs = {
            "name": self.NAME,
            "mission": "glider",
            "payload": {"mode": "simple", "total_g": 450},
            "print": {"filament": "lw_pla"},
        }
        saved = server.save_design(self.NAME, inputs)
        self.assertTrue(saved["ok"], saved.get("error"))
        self.assertTrue(os.path.exists(saved["path"]))

        listed = server.list_designs()
        names = [d["file"] for d in listed]
        self.assertIn(saved["file"], names)

        loaded = server.load_design(saved["file"])
        self.assertTrue(loaded["ok"], loaded.get("error"))
        self.assertEqual(loaded["inputs"]["mission"], "glider")
        self.assertEqual(loaded["inputs"]["payload"]["total_g"], 450)

        # зареденото трябва да се преизчисли без грешка
        res = server.compute_design(loaded["inputs"])
        self.assertTrue(res["ok"], res.get("error"))

        deleted = server.delete_design(self.NAME)
        self.assertTrue(deleted["ok"])
        self.assertFalse(server.load_design(saved["file"])["ok"])

    def test_missing_design(self):
        self.assertFalse(server.load_design("няма такъв дизайн")["ok"])

    def test_paths_endpoint(self):
        paths = server.get_paths()
        self.assertIn("designs", paths)
        self.assertIn("exports", paths)
        self.assertTrue(os.path.isdir(paths["designs"]))
        self.assertTrue(os.path.isdir(paths["exports"]))


if __name__ == "__main__":
    unittest.main()
