"""
Тестове за експорта към SolidCraft (гладък B-rep модел чрез loft).

Проверява се това, което чупи импорта:
  * сеченията имат равнина (origin / x_dir / y_dir) и затворен профил;
  * командите са валиден скрипт за SolidCraft (скица → spline → loft);
  * файловете (SVG, manifest, скрипт) се записват;
  * ако `solidcraft-cli` е налице — истинският loft дава затворени тела
    с гладки (не само равнинни) повърхности.
"""

import json
import math
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import assembly, design, solidcraft_export as se  # noqa: E402

# Малко сечения: тестът пуска истински SolidCraft и трябва да е бърз.
FAST = {"points": 12, "stations": 3, "fuselage_ring": 12,
        "fuselage_stations": 3, "tail_stations": 3}


def result(**overrides):
    inputs = {"mission": "trainer",
              "payload": {"mode": "simple", "total_g": 600},
              "print": {"filament": "lw_pla", "perimeters": 1, "infill": 0}}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(inputs.get(key), dict):
            inputs[key] = dict(inputs[key], **value)
        else:
            inputs[key] = value
    return design.compute(inputs)


class TestLoftBodies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.bodies = assembly.loft_bodies(cls.res, None, se.DEFAULT_DETAIL)
        cls.by_name = {b["name"]: b for b in cls.bodies}

    def test_all_parts_are_present(self):
        # симетричните повърхности са две половини (за да е стабилен join-ът)
        for name in ("Wing_R", "Wing_L", "Fuselage", "Spinner", "Cowl",
                     "Stabilizer_R", "Stabilizer_L", "Fin"):
            self.assertIn(name, self.by_name)

    def test_loft_sections_have_planes(self):
        for body in self.bodies:
            if body["kind"] != "loft":
                continue
            self.assertGreaterEqual(len(body["sections"]), 2, body["name"])
            for section in body["sections"]:
                self.assertEqual(len(section["origin"]), 3)
                self.assertEqual(len(section["x_dir"]), 3)
                self.assertEqual(len(section["y_dir"]), 3)
                self.assertEqual(len(section["points2d"]),
                                 len(section["points3d"]))

    def test_halves_are_symmetric(self):
        right = self.by_name["Wing_R"]["sections"]
        left = self.by_name["Wing_L"]["sections"]
        self.assertEqual(len(right), len(left))
        self.assertEqual([s["station_mm"] for s in right],
                         [s["station_mm"] for s in left])
        for r, l in zip(right, left):
            self.assertAlmostEqual(r["origin"][1], -l["origin"][1], places=6)
        # коренът влиза JOIN_EMBED_MM отвъд оста (двете половини се
        # застъпват, вместо да се допират с лица) — върхът не мърда
        self.assertAlmostEqual(right[0]["origin"][1],
                               -assembly.JOIN_EMBED_MM, places=6)
        self.assertAlmostEqual(left[0]["origin"][1],
                               assembly.JOIN_EMBED_MM, places=6)
        semi = float(self.res["geometry"]["span_mm"]) / 2.0
        self.assertAlmostEqual(right[-1]["origin"][1], semi, places=3)
        self.assertAlmostEqual(left[-1]["origin"][1], -semi, places=3)

    def test_airfoil_has_upper_and_lower_curve(self):
        wing = self.by_name["Wing_R"]
        upper, lower = se.airfoil_curves(wing["sections"][0])
        self.assertGreater(len(upper), 3)
        self.assertGreater(len(lower), 3)
        # долната крива започва от TE_bot и завършва в LE
        self.assertEqual(upper[0], lower[-1])

    def test_fuselage_sections_are_closed_rings(self):
        fus = self.by_name["Fuselage"]
        for section in fus["sections"]:
            self.assertIsNone(section["split"])
            self.assertGreater(len(section["points2d"]), 6)

    def test_spinner_and_cowl_are_revolves(self):
        # спинер + каулинг = един конус: един boolean по-малко
        self.assertEqual(self.by_name["Spinner"]["kind"], "revolve")
        self.assertEqual(self.by_name["Cowl"]["kind"], "revolve")
        for name in ("Spinner", "Cowl"):
            self.assertGreaterEqual(len(self.by_name[name]["profile"]), 3)
        # ???????? ????? ? ?????? ???? ???????? (????? ? ?????)
        self.assertEqual(self.by_name["Spinner"]["into"], "Fuselage")
        self.assertEqual(self.by_name["Spinner"]["after"], "Cowl")

    def test_nose_can_be_one_piece(self):
        bodies = assembly.loft_bodies(self.res, None, FAST,
                                      nose_one_piece=True)
        names = [b["name"] for b in bodies]
        self.assertIn("Nose", names)
        self.assertNotIn("Spinner", names)

    def test_flying_wing_has_no_tail(self):
        res = result(mission="flying_wing", wing={"airfoil": "mh45"})
        names = [b["name"] for b in assembly.loft_bodies(res, None, FAST)]
        self.assertNotIn("Stabilizer", names)
        self.assertNotIn("Fin", names)


class TestJoinTree(unittest.TestCase):
    """
    Join дървото: моделът се строи като един solid, а не шест отделни тела.

    Тялото-основа е фюзелажът; крилото, опашката, уинглетите и спинер/
    каулингът се създават направо с `operation: join`, за да не остане
    ръчен boolean (който SolidCraft отказва при допирни лица).
    """

    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.bodies = assembly.loft_bodies(cls.res, None, FAST)
        cls.by_name = {b["name"]: b for b in cls.bodies}

    def test_fuselage_is_the_base(self):
        self.assertNotIn("into", self.by_name["Fuselage"])

    def test_every_other_body_joins_into_the_fuselage(self):
        # ?????????????? ?????? ??????? ???? (boolean ????), ??????????
        # ?? ?????? ? ??????
        separate = ("Stabilizer_R", "Stabilizer_L", "Stabilizer_V_R",
                    "Stabilizer_V_L")
        self.assertGreater(len(self.bodies), 2)
        for name, body in self.by_name.items():
            if name == "Fuselage":
                continue
            if name in separate:
                self.assertNotIn("into", body, name)
                continue
            self.assertEqual(body.get("into"), "Fuselage", name)

    def test_tail_can_be_joined_on_request(self):
        joined = assembly.loft_bodies(self.res, None, FAST, join_tail=True)
        by_name = {b["name"]: b for b in joined}
        for name in ("Stabilizer_R", "Stabilizer_L"):
            self.assertEqual(by_name[name].get("into"), "Fuselage", name)

    def test_body_order_puts_the_base_first(self):
        ordered = se.body_order(self.bodies)
        self.assertEqual(ordered[0]["name"], "Fuselage")
        self.assertEqual(len(ordered), len(self.bodies))

    def test_first_loft_is_the_fuselage_without_join(self):
        lofts = [c for c in se.build_commands(self.bodies)
                 if c["command"] == "solid.loft"]
        self.assertEqual(lofts[0]["params"]["body_name"], "Fuselage")
        self.assertNotIn("operation", lofts[0]["params"])

    def test_one_combine_joins_all_tools(self):
        # ???? ???????? ?? ???? ?????? ?????? ?? join-???: ???? SolidCraft
        # ?? ???? (?????? ????? ????? ???? ? ????? ?????)
        combines = [c for c in se.build_commands(self.bodies)
                    if c["command"] == "solid.combine"]
        self.assertEqual(len(combines), 1)
        params = combines[0]["params"]
        self.assertEqual(params["target"], "Fuselage")
        self.assertEqual(params["operation"], "join")
        for name in ("Wing_R", "Wing_L", "Fin", "Cowl", "Spinner"):
            self.assertIn(name, params["tools"])
        # ?????????????? ?? ? ? combine-? ?? ????????????
        self.assertNotIn("Stabilizer_R", params["tools"])

    def test_lofts_are_created_separately(self):
        lofts = [c for c in se.build_commands(self.bodies)
                 if c["command"] in ("solid.loft", "solid.revolve")]
        self.assertTrue(lofts)
        for loft in lofts:
            self.assertNotIn("targets", loft["params"])

    def test_features_have_readable_names(self):
        # в дървото на дизайна: „Wing_R loft“, а не „Loft 4“
        names = [c["params"].get("name") for c in se.build_commands(self.bodies)
                 if c["command"] in ("solid.loft", "solid.revolve")]
        self.assertIn("Wing_R loft", names)
        self.assertIn("Fuselage loft", names)

    def test_joins_can_be_switched_off(self):
        plain = assembly.loft_bodies(self.res, None, FAST, joins=False)
        self.assertFalse(any(b.get("into") for b in plain))


class TestRootSink(unittest.TestCase):
    """
    Коренът на крилото сяда в тялото, за да е стабилен join-ът.

    Без отместване крилото и тялото се срещат в ивица под милиметър и
    SolidCraft отказва обединението (проверено с реалния CLI).
    """

    def test_high_wing_sinks_down(self):
        res = result(layout={"wing_position": "high"})
        self.assertLess(assembly.wing_root_sink(res), 0.0)

    def test_low_wing_moves_up(self):
        res = result(layout={"wing_position": "low"})
        self.assertGreater(assembly.wing_root_sink(res), 0.0)

    def test_sink_is_bounded_by_the_fuselage_height(self):
        for pos in ("high", "mid", "low"):
            res = result(layout={"wing_position": pos})
            height = float(res["geometry"]["fuselage"]["height_mm"])
            self.assertLessEqual(abs(assembly.wing_root_sink(res)),
                                 assembly.ROOT_SINK_BAND * height, pos)

    def test_wing_at_the_band_edge_sinks(self):
        # точно на ROOT_SINK_BAND от короната: кореновият заден ръб гали
        # стесняващия се фюзелаж, затова слягането е задължително
        res = {"geometry": {"fuselage": {"height_mm": 60.0}},
               "layout": {"wing_z_mm": 45.0}}
        self.assertAlmostEqual(assembly.wing_root_sink(res),
                               -assembly.ROOT_SINK_FRAC * 60.0)

    def test_cad_wing_root_is_lower_but_the_tip_does_not_move(self):
        res = result(layout={"wing_position": "high"})
        spec = assembly.wing_spec(res, None)
        plain = assembly.surface_rings(**dict(spec, stations=8,
                                              spacing="sine"))
        sunk = assembly.surface_rings(**dict(spec, stations=8,
                                             spacing="sine",
                                             sink_mm=-10.0))
        root_plain = min(plain, key=lambda s: abs(s["station_mm"]))
        root_sunk = min(sunk, key=lambda s: abs(s["station_mm"]))
        self.assertAlmostEqual(
            root_plain["origin"][2] - root_sunk["origin"][2], 10.0, delta=0.2)
        tip_plain = max(plain, key=lambda s: abs(s["station_mm"]))
        tip_sunk = max(sunk, key=lambda s: abs(s["station_mm"]))
        self.assertAlmostEqual(tip_plain["origin"][2], tip_sunk["origin"][2],
                               delta=0.1)

    def test_cad_wing_in_the_model_is_sunk(self):
        res = result(layout={"wing_position": "high"})
        sink = assembly.wing_root_sink(res)
        sunk = [b for b in assembly.loft_bodies(res, None, se.DEFAULT_DETAIL)
                if b["name"] == "Wing_R"][0]
        plain = [b for b in assembly.loft_bodies(res, None, se.DEFAULT_DETAIL,
                                                 joins=False)
                 if b["name"] == "Wing_R"][0]
        self.assertAlmostEqual(sunk["embed_mm"], sink, delta=0.01)
        z_sunk = min(p[2] for s in sunk["sections"] for p in s["points3d"])
        z_plain = min(p[2] for s in plain["sections"] for p in s["points3d"])
        self.assertLess(z_sunk, z_plain - 5.0)


class TestScript(unittest.TestCase):
    def test_script_is_a_solidcraft_script(self):
        bodies = assembly.loft_bodies(result(), None, FAST)
        script = se.build_script(bodies, "C:/tmp/aircraft.step")
        self.assertEqual(list(script), ["commands"])
        commands = [c["command"] for c in script["commands"]]
        self.assertEqual(commands[0], "sketch.create")
        self.assertIn("solid.loft", commands)
        self.assertIn("solid.revolve", commands)
        self.assertEqual(commands[-1], "file.export")
        export = script["commands"][-1]["params"]
        self.assertEqual(export["format"], "step")
        self.assertTrue(export["path"].endswith("aircraft.step"))

    def test_every_sketch_is_finished_and_named(self):
        bodies = assembly.loft_bodies(result(), None, FAST)
        commands = se.build_commands(bodies)
        created = [c["params"]["name"] for c in commands
                   if c["command"] == "sketch.create"]
        finished = [c for c in commands if c["command"] == "sketch.finish"]
        self.assertEqual(len(created), len(finished))
        self.assertEqual(len(created), len(set(created)))
        for loft in [c for c in commands if c["command"] == "solid.loft"]:
            for section in loft["params"]["sections"]:
                self.assertIn(section["sketch"], created)

    def test_svg_contains_a_closed_path(self):
        section = assembly.loft_bodies(
            result(), None, FAST)[0]["sections"][0]
        text = se.svg_text(section["points2d"], se._profile_path(section))
        self.assertTrue(text.startswith("<?xml"))
        self.assertIn("<svg", text)
        self.assertTrue(text.rstrip().endswith("</svg>"))
        self.assertIn('d="M', text)
        self.assertIn("Z", text)


class TestBbox(unittest.TestCase):
    """bbox от `eval` — нужен е за проверката за симетрия."""

    def test_bbox_is_three_numbers(self):
        self.assertEqual(se._bbox({"min": [1, 2, 3], "max": [4, 5, 6]}),
                         {"min": [1.0, 2.0, 3.0], "max": [4.0, 5.0, 6.0]})

    def test_bbox_without_three_axes_is_none(self):
        for raw in (None, {}, {"min": [1, 2], "max": [3, 4]},
                    {"min": ["а", 2, 3], "max": [1, 2, 3]}):
            self.assertIsNone(se._bbox(raw), raw)


class TestFilesWithoutCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="aeroforge_sc_")
        cls.out = se.export(result(), os.path.join(cls.dir, "out"),
                            detail=FAST, slugify=lambda _n: "demo",
                            run=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_export_writes_script_and_sections(self):
        self.assertTrue(self.out["ok"], self.out.get("error"))
        self.assertGreater(self.out["sections"], 5)
        self.assertTrue(os.path.exists(self.out["script"]))
        with open(self.out["script"], encoding="utf-8") as f:
            script = json.load(f)
        self.assertIn("commands", script)

    def test_svg_files_are_valid_xml(self):
        folder = os.path.join(self.out["folder"], "sections")
        svgs = []
        for root, _dirs, files in os.walk(folder):
            svgs += [os.path.join(root, n) for n in files
                     if n.endswith(".svg")]
        self.assertGreaterEqual(len(svgs), 5)
        for path in svgs:
            with open(path, encoding="utf-8") as f:
                ET.fromstring(f.read())

    def test_manifest_has_a_plane_per_section(self):
        path = os.path.join(self.out["folder"], "sections", "manifest.csv")
        with open(path, encoding="utf-8-sig") as f:
            rows = [line for line in f.read().splitlines() if line.strip()]
        self.assertEqual(rows[0].split(";")[0], "body")
        self.assertEqual(len(rows) - 1, self.out["sections"])
        for row in rows[1:]:
            self.assertGreaterEqual(len(row.split(";")),
                                    len(se.MANIFEST_HEADER))

    def test_no_step_without_cli(self):
        self.assertIsNone(self.out["step"])

    def test_reference_bodies_are_a_separate_step(self):
        path = os.path.join(self.out["folder"], "reference.step")
        self.assertTrue(os.path.exists(path), path)
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(200000)
        self.assertIn("MANIFOLD_SOLID_BREP", text)
        self.assertIn("REF_Battery", text)


@unittest.skipUnless(se.find_cli(), "няма solidcraft-cli")
class TestSolidcraftRun(unittest.TestCase):
    """Истински SolidCraft: моделът се записва, обединен в едно тяло."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="aeroforge_sc_run_")
        cls.out = se.export(result(), cls.dir, detail=FAST, timeout=45,
                            slugify=lambda _n: "demo",
                            options={"timeout": 45})
        cls.eval = None
        if cls.out.get("step"):
            proc = subprocess.run(
                [se.find_cli(), "eval", cls.out["step"]],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300)
            text = proc.stdout
            start = text.find("{")
            cls.eval = json.loads(text[start:]) if start >= 0 else None

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_step_and_design_are_written(self):
        self.assertTrue(self.out["ok"], self.out.get("error"))
        self.assertTrue(os.path.exists(self.out["step"]))
        self.assertGreater(os.path.getsize(self.out["step"]), 1000)
        # дизайнът с историята (скици + loft + join) — за редакция на ръка
        self.assertTrue(os.path.exists(self.out["design"]))

    def test_bodies_are_closed_solids(self):
        self.assertIsNotNone(self.eval, "SolidCraft не върна JSON")
        for body in self.eval["bodies"]:
            self.assertTrue(body["closed"], body["name"])
            self.assertGreater(body["volume_mm3"], 0.0, body["name"])

    def test_surfaces_are_smooth_not_only_planar(self):
        types = set()
        for body in self.eval["bodies"]:
            types.update(body["face_types"])
        self.assertTrue(types - {"plane"},
                        "моделът е само равнинни лица: %s" % types)

    def test_model_has_closed_bodies(self):
        # ??? ??????? ????? ???? ?? ?????? (FAST) ???? ?? ??????????????
        # ???? ?? ?? ?????????? ? ??????? ? ????? ???????? ???? ?? ? solid.
        self.assertGreaterEqual(self.eval["body_count"], 1)
        for body in self.eval["bodies"]:
            self.assertTrue(body["closed"], body["name"])

if __name__ == "__main__":
    unittest.main()

