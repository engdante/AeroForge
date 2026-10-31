"""
Тестове за форматите за CAD: 3MF, STEP (faceted), DXF и целият експорт.

Проверява се структурата на файловете (zip/XML, entity референции, DXF
кодове) — това е, което чупи импорта в CAD.
"""

import json
import os
import re
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import (assembly, design, export_3mf, export_dxf,  # noqa: E402
                  export_step, model_export)


def result(**overrides):
    inputs = {"mission": "trainer",
              "payload": {"mode": "simple", "total_g": 600},
              "print": {"filament": "lw_pla", "perimeters": 1, "infill": 0,
                        "bed": [220, 220, 250]}}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(inputs.get(key), dict):
            inputs[key] = dict(inputs[key], **value)
        else:
            inputs[key] = value
    return design.compute(inputs)


class Test3mf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.bodies = assembly.build_assembly(cls.res)
        cls.dir = tempfile.mkdtemp(prefix="aeroforge_3mf_")
        cls.path = os.path.join(cls.dir, "aircraft.3mf")
        cls.info = export_3mf.write_3mf(
            cls.path, [{"name": b["name"], "mesh": b["mesh"]}
                       for b in cls.bodies])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_zip_structure(self):
        with zipfile.ZipFile(self.path) as zf:
            names = set(zf.namelist())
        self.assertIn("[Content_Types].xml", names)
        self.assertIn("_rels/.rels", names)
        self.assertIn("3D/3dmodel.model", names)

    def test_model_xml_is_valid_and_has_objects(self):
        with zipfile.ZipFile(self.path) as zf:
            xml = zf.read("3D/3dmodel.model").decode("utf-8")
        root = ET.fromstring(xml)
        ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
        self.assertEqual(root.get("unit"), "millimeter")
        objects = root.findall(".//%sobject" % ns)
        self.assertEqual(len(objects), len(self.bodies))
        names = [o.get("name") for o in objects]
        self.assertIn("Wing", names)
        self.assertIn("Fuselage", names)
        for obj in objects:
            verts = obj.findall(".//%svertex" % ns)
            tris = obj.findall(".//%striangle" % ns)
            self.assertGreater(len(verts), 10)
            self.assertGreater(len(tris), 10)
            count = len(verts)
            for tri in tris:
                for key in ("v1", "v2", "v3"):
                    self.assertLess(int(tri.get(key)), count)

    def test_build_refers_to_all_objects(self):
        with zipfile.ZipFile(self.path) as zf:
            xml = zf.read("3D/3dmodel.model").decode("utf-8")
        root = ET.fromstring(xml)
        ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
        items = root.findall(".//%sbuild/%sitem" % (ns, ns))
        self.assertEqual(len(items), len(self.bodies))
        ids = {o.get("id") for o in root.findall(".//%sobject" % ns)}
        for item in items:
            self.assertIn(item.get("objectid"), ids)

    def test_empty_input_writes_nothing(self):
        path = os.path.join(self.dir, "empty.3mf")
        info = export_3mf.write_3mf(path, [])
        self.assertEqual(info["objects"], 0)
        self.assertFalse(os.path.exists(path))


class TestStep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.bodies = assembly.build_assembly(cls.res)
        cls.dir = tempfile.mkdtemp(prefix="aeroforge_step_")
        cls.path = os.path.join(cls.dir, "aircraft.step")
        cls.info = export_step.write_step(
            cls.path, [{"name": b["name"], "mesh": b["mesh"]}
                       for b in cls.bodies])
        with open(cls.path, encoding="ascii", errors="replace") as f:
            cls.text = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_envelope(self):
        self.assertTrue(self.text.startswith("ISO-10303-21;"))
        self.assertIn("HEADER;", self.text)
        self.assertIn("DATA;", self.text)
        self.assertIn("ENDSEC;", self.text)
        self.assertTrue(self.text.rstrip().endswith("END-ISO-10303-21;"))

    def test_millimetre_unit(self):
        self.assertIn("SI_UNIT(.MILLI.,.METRE.)", self.text)

    def test_one_solid_per_body(self):
        # MANIFOLD_SOLID_BREP (не FACETED_BREP): Fusion внася само него като
        # solid body; с FACETED_BREP тялото става mesh body и boolean не работи
        self.assertEqual(self.text.count("MANIFOLD_SOLID_BREP"),
                         len(self.bodies))
        self.assertNotIn("FACETED_BREP", self.text)
        self.assertEqual(self.text.count("CLOSED_SHELL"), len(self.bodies))
        self.assertEqual(self.info["solids"], len(self.bodies))

    def test_products_are_named(self):
        for body in self.bodies:
            self.assertIn("PRODUCT('%s'" % body["name"], self.text)

    def test_all_entity_references_resolve(self):
        defined = set(re.findall(r"^#(\d+)=", self.text, flags=re.MULTILINE))
        used = set(re.findall(r"#(\d+)", self.text))
        self.assertTrue(defined)
        self.assertEqual(used - defined, set(), "недефинирани референции")

    def test_every_triangle_is_an_advanced_face(self):
        faces = self.text.count("ADVANCED_FACE")
        triangles = sum(b["mesh"].triangles() for b in self.bodies)
        self.assertEqual(faces, triangles)
        self.assertEqual(self.text.count("EDGE_LOOP"), triangles)
        self.assertEqual(self.text.count("PLANE("), triangles)

    def test_brep_topology_is_closed(self):
        """Всеки ръб (EDGE_CURVE) участва в точно 2 лица (B-rep валидност)."""
        used = {}
        for ref in re.findall(r"ORIENTED_EDGE\('',\*,\*,#(\d+),", self.text):
            used[ref] = used.get(ref, 0) + 1
        self.assertTrue(used)
        broken = {ref: n for ref, n in used.items() if n != 2}
        self.assertEqual(broken, {}, "ръбове, които не са споделени от 2 лица")

    def test_no_entity_references_itself(self):
        """Самопрепратка (#n → #n) прави файла невалиден за CAD."""
        for line in self.text.splitlines():
            match = re.match(r"^#(\d+)=(.*);$", line)
            if not match:
                continue
            own = match.group(1)
            refs = re.findall(r"#(\d+)", match.group(2))
            self.assertNotIn(own, refs, "entity #%s сочи към себе си" % own)

    def test_representation_has_a_placement(self):
        """ADVANCED_BREP_SHAPE_REPRESENTATION изисква AXIS2_PLACEMENT_3D."""
        placements = set(re.findall(
            r"^#(\d+)=AXIS2_PLACEMENT_3D", self.text, flags=re.MULTILINE))
        self.assertTrue(placements)
        found = re.findall(
            r"^#\d+=ADVANCED_BREP_SHAPE_REPRESENTATION\('([^']*)',"
            r"\((#[0-9]+),(#[0-9]+)\)", self.text, flags=re.MULTILINE)
        self.assertEqual(len(found), len(self.bodies))
        for _name, placement, brep in found:
            self.assertIn(placement.lstrip("#"), placements)
            self.assertIn("#" + brep.lstrip("#"), self.text)

    def test_empty_input_writes_no_solids(self):
        path = os.path.join(self.dir, "empty.step")
        info = export_step.write_step(path, [])
        self.assertEqual(info["solids"], 0)
        with open(path, encoding="ascii") as f:
            text = f.read()
        self.assertNotIn("MANIFOLD_SOLID_BREP", text)


class TestDxf(unittest.TestCase):
    def test_writes_polylines_with_layers(self):
        folder = tempfile.mkdtemp(prefix="aeroforge_dxf_")
        path = os.path.join(folder, "sections.dxf")
        try:
            info = export_dxf.write_dxf(path, [
                {"layer": "WING", "closed": True,
                 "points": [(0, 0, 0), (10, 0, 0), (10, 5, 1)]},
                {"layer": "FUSELAGE", "closed": True,
                 "points": [(0, 0, 0), (0, 20, 0), (0, 20, 30)]},
            ])
            self.assertEqual(info["polylines"], 2)
            with open(path, encoding="ascii") as f:
                text = f.read()
            self.assertIn("AC1009", text)
            self.assertIn("$INSUNITS", text)
            self.assertIn("WING", text)
            self.assertIn("FUSELAGE", text)
            self.assertEqual(text.count("POLYLINE"), 2)
            self.assertEqual(text.count("VERTEX"), 6)
            self.assertIn("SEQEND", text)
            self.assertTrue(text.rstrip().endswith("EOF"))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_short_polylines_are_skipped(self):
        folder = tempfile.mkdtemp(prefix="aeroforge_dxf_")
        try:
            path = os.path.join(folder, "short.dxf")
            info = export_dxf.write_dxf(path, [
                {"layer": "X", "points": [(0, 0, 0)]}])
            self.assertEqual(info["polylines"], 0)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_csv_writer(self):
        folder = tempfile.mkdtemp(prefix="aeroforge_csv_")
        try:
            path = os.path.join(folder, "s.csv")
            info = export_dxf.write_csv(path, [["W01", 0, 1.5]],
                                        ["section", "y", "x"])
            self.assertEqual(info["rows"], 1)
            with open(path, encoding="utf-8-sig") as f:
                text = f.read()
            self.assertIn("section;y;x", text)
            self.assertIn("W01;0;1.5", text)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class TestModelExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.dir = tempfile.mkdtemp(prefix="aeroforge_model_")
        cls.out = model_export.export_model(
            cls.res, cls.dir, [220, 220, 250], cls.res["filament"],
            slugify=lambda _name: "demo")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_ok(self):
        self.assertTrue(self.out["ok"], self.out.get("error"))

    def test_expected_files_exist(self):
        model_dir = os.path.join(self.out["folder"], "model")
        for name in ("aircraft.3mf", "aircraft.step", "wing_sections.dxf",
                     "fuselage_stations.dxf", "wing_sections.csv",
                     "fuselage_stations.csv", "params.json"):
            path = os.path.join(model_dir, name)
            self.assertTrue(os.path.exists(path), name)
            self.assertGreater(os.path.getsize(path), 100, name)

    def test_reference_folder(self):
        path = os.path.join(self.out["folder"], "reference", "reference.3mf")
        self.assertTrue(os.path.exists(path))

    def test_print_folder_has_stl_and_plan(self):
        folder = os.path.join(self.out["folder"], "print")
        self.assertTrue(os.path.isdir(folder))
        files = os.listdir(folder)
        self.assertTrue(any(f.endswith(".stl") for f in files), files)
        self.assertIn("print_plan.json", files)

    def test_readme_and_manifest(self):
        self.assertTrue(os.path.exists(
            os.path.join(self.out["folder"], "README.txt")))
        with open(self.out["manifest_path"], encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["units"], "mm")
        self.assertIn("origin", manifest["datum"])
        self.assertGreaterEqual(len(manifest["bodies"]), 3)
        self.assertIn("aircraft_step", manifest["files"])

    def test_params_contain_geometry(self):
        path = os.path.join(self.out["folder"], "model", "params.json")
        with open(path, encoding="utf-8") as f:
            params = json.load(f)
        g = self.res["geometry"]
        self.assertAlmostEqual(params["wing"]["span_mm"], g["span_mm"],
                               places=3)
        self.assertAlmostEqual(params["fuselage"]["length_mm"],
                               g["fuselage"]["length_mm"], places=3)
        self.assertEqual(params["datum"]["units"], "mm")

    def test_invalid_design_is_rejected(self):
        self.assertFalse(model_export.export_model({}, ".", [200, 200, 200])["ok"])


if __name__ == "__main__":
    unittest.main()

