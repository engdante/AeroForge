"""
Тестове за „solid“ обектите в 3MF (meshcheck + export_3mf).

3MF не поддържа B-rep — „solid“ там значи мрежа с манифолдни ръбове,
еднаква ориентация, външни нормали и една обвивка (χ = 2).  Тези тестове
проверяват точно това, за всяко тяло в модела и в записания файл.
"""

import os
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import assembly, design, export_3mf, meshcheck, printgeom  # noqa: E402

NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def result(**overrides):
    inputs = {"mission": "trainer",
              "payload": {"mode": "simple", "total_g": 600}}
    inputs.update(overrides)
    return design.compute(inputs)


class TestSolidReport(unittest.TestCase):
    def test_cube_is_a_solid(self):
        mesh = printgeom.Mesh()
        corners = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
                   (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10)]
        idx = [mesh.vertex(p) for p in corners]
        for face in ((0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
                     (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
                     (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)):
            mesh.face(*(idx[i] for i in face))
        report = meshcheck.solid_report(mesh)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["shells"], 1)
        self.assertEqual(report["euler"], 2)
        self.assertAlmostEqual(report["volume"], 1000.0, places=6)

    def test_open_mesh_is_reported(self):
        mesh = printgeom.lifting_surface(120.0, 80.0, 200.0, "naca2412", 0.45)
        mesh.faces = mesh.faces[:-40]           # отваряме обвивката
        report = meshcheck.solid_report(mesh)
        self.assertFalse(report["ok"])
        self.assertGreater(report["boundary_edges"], 0)

    def test_two_shells_are_detected_and_split(self):
        a = printgeom.lifting_surface(100.0, 80.0, 100.0, "naca2412", 0.45)
        b = printgeom.lifting_surface(100.0, 80.0, 100.0, "naca0012", 0.45)
        merged = printgeom.Mesh()
        merged.merge(a)
        merged.merge(b)
        report = meshcheck.solid_report(merged)
        self.assertEqual(report["shells"], 2)
        self.assertFalse(report["ok"])          # един обект = едно тяло
        pieces = meshcheck.split_shells(merged, ["Part"])
        self.assertEqual(len(pieces), 2)
        for _name, piece in pieces:
            self.assertTrue(meshcheck.solid_report(piece)["ok"])


class TestAircraftSolids(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.bodies = assembly.build_assembly(cls.res, "high")

    def test_every_body_is_one_closed_solid(self):
        self.assertTrue(self.bodies)
        for body in self.bodies:
            report = meshcheck.solid_report(body["mesh"])
            self.assertTrue(report["ok"],
                            "%s: %s" % (body["name"], report["problems"]))
            self.assertEqual(report["shells"], 1, body["name"])
            self.assertEqual(report["euler"], 2, body["name"])  # плътно тяло
            self.assertGreater(report["volume"], 0.0, body["name"])

    def test_spinner_and_cowl_are_separate_bodies(self):
        names = [b["name"] for b in self.bodies]
        self.assertIn("Spinner", names)
        self.assertIn("Cowl", names)

    def test_print_fuselage_is_one_solid(self):
        fus = [p for p in printgeom.build_parts(self.res, "normal")
               if p["file"] == "fuselage.stl"][0]
        report = meshcheck.solid_report(fus["mesh"])
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["shells"], 1)
        # печатаното тяло е **куха черупка** → род 1 (χ = 0), не плътна топка
        self.assertEqual(report["genus"], 1)


class TestThreeMfSolids(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.folder = tempfile.mkdtemp()
        cls.path = os.path.join(cls.folder, "aircraft.3mf")
        cls.items = [{"name": b["name"], "mesh": b["mesh"]}
                     for b in assembly.build_assembly(cls.res, "high")]
        cls.out = export_3mf.write_3mf(cls.path, cls.items)

    def test_all_objects_are_solids(self):
        self.assertGreaterEqual(self.out["solids"], 5)
        self.assertEqual(self.out["problems"], [])
        self.assertEqual(self.out["objects"], self.out["solids"])

    def test_file_has_one_mesh_per_object(self):
        with zipfile.ZipFile(self.path) as zf:
            xml = zf.read("3D/3dmodel.model").decode("utf-8")
        root = ET.fromstring(xml)
        objects = root.findall("%sobjects/%sobject" % (NS, NS))
        if not objects:
            objects = root.findall(".//%sobject" % NS)
        self.assertGreaterEqual(len(objects), 1)
        for obj in objects:
            self.assertEqual(obj.get("type"), "model")
            meshes = obj.findall("%smesh" % NS)
            self.assertEqual(len(meshes), 1, obj.get("name"))

    def test_names_contain_the_parts(self):
        names = [item["name"] for item in self.items]
        self.assertEqual(names[0], "Wing")
        self.assertIn("Fuselage", names)
        self.assertIn("Spinner", names)
        self.assertIn("Cowl", names)


if __name__ == "__main__":
    unittest.main()
