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
        for r, l in zip(right, left):
            self.assertAlmostEqual(r["station_mm"], l["station_mm"], places=6)
            self.assertAlmostEqual(r["origin"][1], -l["origin"][1], places=6)

    def test_wing_root_gap_makes_separate_wing_bodies(self):
        res = result(layout={"wing_root_gap_mm": 10.0})
        bodies = assembly.loft_bodies(res, None, FAST,
                                      wing_root_gap_mm=10.0)
        by_name = {body["name"]: body for body in bodies}
        self.assertIn("Wing_R", by_name)
        self.assertIn("Wing_L", by_name)
        self.assertNotIn("WingRootBridge_R", by_name)
        self.assertNotIn("WingRootBridge_L", by_name)
        self.assertFalse(any(b.get("root_bridge") for b in bodies))
        # крилните половини са отделни тела, не се влизат в тялото
        self.assertNotIn("into", by_name["Wing_R"])
        self.assertNotIn("into", by_name["Wing_L"])
        # коренът е на кожа/2 + луфт
        fus_width = res["geometry"]["fuselage"]["width_mm"]
        right_root = by_name["Wing_R"]["sections"][0]["origin"][1]
        left_root = by_name["Wing_L"]["sections"][0]["origin"][1]
        self.assertAlmostEqual(right_root, fus_width / 2.0 + 10.0, places=4)
        self.assertAlmostEqual(left_root, -(fus_width / 2.0 + 10.0), places=4)

    def test_tail_root_gap_makes_separate_tail_bodies(self):
        bodies = assembly.loft_bodies(
            result(layout={"tail_root_gap_mm": 10}), None, FAST,
            tail_root_gap_mm=10.0)
        by_name = {body["name"]: body for body in bodies}
        self.assertIn("Stabilizer_R", by_name)
        self.assertIn("Stabilizer_L", by_name)
        self.assertIn("Fin", by_name)
        self.assertNotIn("TailRootBridge_R", by_name)
        self.assertNotIn("TailRootBridge_L", by_name)
        self.assertNotIn("FinRootBridge", by_name)
        self.assertFalse(any(b.get("root_bridge") for b in bodies))
        # стабилизаторите са отделни тела, не се влизат в тялото
        self.assertNotIn("into", by_name["Stabilizer_R"])
        self.assertNotIn("into", by_name["Stabilizer_L"])
        # килът е отделно тяло с корен на локалната кожа + луфт (по
        # височината); тялото се стеснява към опашката, затова не е
        # максималната височина/2
        fus = result()["geometry"]["fuselage"]
        fin = by_name["Fin"]["sections"][0]
        skin = assembly.skin_offset(fus, fin["origin"][0], (0.0, 0.0, 1.0))
        self.assertAlmostEqual(fin["origin"][2],
                               fus["height_mm"] / 2.0 + skin + 10.0,
                               places=4)
        # по-близо до обшивката в тази станция, отколкото до максималния
        # връх на тялото (то се стеснява към опашката)
        self.assertLess(fin["origin"][2], fus["height_mm"] + 10.0)

    def test_root_gap_zero_joins_into_fuselage(self):
        bodies = assembly.loft_bodies(
            result(layout={"wing_root_gap_mm": 0, "tail_root_gap_mm": 0}),
            None, FAST,
            wing_root_gap_mm=0, tail_root_gap_mm=0)
        self.assertFalse(any(body.get("root_bridge") for body in bodies))
        by_name = {body["name"]: body for body in bodies}
        self.assertEqual(by_name["Wing_R"].get("into"), "Fuselage")
        self.assertEqual(by_name["Wing_L"].get("into"), "Fuselage")

    def test_halves_stay_symmetric_around_the_gap(self):
        bodies = assembly.loft_bodies(
            result(layout={"wing_root_gap_mm": 10}), None, FAST,
            wing_root_gap_mm=10.0)
        by_name = {body["name"]: body for body in bodies}
        right = by_name["Wing_R"]["sections"]
        left = by_name["Wing_L"]["sections"]
        self.assertEqual(len(right), len(left))
        for r, l in zip(right, left):
            self.assertAlmostEqual(r["station_mm"], l["station_mm"],
                                   places=6)
            self.assertAlmostEqual(r["origin"][1], -l["origin"][1], places=6)
        self.assertGreater(right[0]["origin"][1], 10.0)
        self.assertLess(left[0]["origin"][1], -10.0)
        semi = float(self.res["geometry"]["span_mm"]) / 2.0
        self.assertAlmostEqual(abs(right[-1]["origin"][1]), semi, places=3)

    def test_joining_disabled_does_not_add_root_bridges(self):
        bodies = assembly.loft_bodies(
            result(layout={"wing_root_gap_mm": 10, "tail_root_gap_mm": 10}),
            None, FAST, joins=False)
        self.assertFalse(any(body.get("root_bridge") for body in bodies))

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

    def test_elliptic_fuselage_sections_use_exact_ellipse_primitives(self):
        fuselage = self.by_name["Fuselage"]
        for section in fuselage["sections"]:
            primitive = section.get("primitive")
            self.assertEqual(primitive["type"], "ellipse")
            self.assertGreater(primitive["minor_radius"], 0)

        commands = se.build_commands([fuselage], combine=False)
        ellipses = [command for command in commands
                    if command["command"] == "sketch.ellipse"]
        splines = [command for command in commands
                   if command["command"] == "sketch.spline.fit_point"]
        self.assertEqual(len(ellipses), len(fuselage["sections"]))
        self.assertFalse(splines)

    def test_non_elliptic_fuselage_sections_keep_spline_geometry(self):
        res = result(fuselage={"shape": "boxy"})
        fuselage = next(body for body in assembly.loft_bodies(
            res, None, FAST) if body["name"] == "Fuselage")
        self.assertTrue(all("primitive" not in section
                            for section in fuselage["sections"]))
        commands = se.build_commands([fuselage], combine=False)
        self.assertTrue(any(command["command"] ==
                            "sketch.spline.fit_point"
                            for command in commands))

    def test_airfoil_fit_points_are_reduced_within_tolerance(self):
        wing = self.by_name["Wing_R"]
        original = [se.airfoil_spline(section)[0] for section in wing["sections"]]
        reduced = se.simplified_airfoil_splines(wing["sections"])

        self.assertEqual(len(original), len(reduced))
        for source, fit in zip(original, reduced):
            self.assertLess(len(fit), len(source))
            self.assertEqual(fit[0], source[0])      # стената на задния ръб
            self.assertEqual(fit[-1], source[-1])
            self.assertLessEqual(
                max(min(se._point_segment_distance(point, fit[i], fit[i + 1])
                        for i in range(len(fit) - 1))
                    for point in source),
                se.CAD_SPLINE_TOLERANCE_MM + 1e-6)

        # един сплайн на сечение (през носа) + стената на задния ръб
        commands = se.build_commands([wing], combine=False)
        splines = [command for command in commands
                   if command["command"] == "sketch.spline.fit_point"]
        self.assertEqual(len(splines), len(reduced))
        self.assertTrue(all(len(command["params"]["points"]) < 32
                            for command in splines))

    def test_symmetric_tail_profiles_stay_symmetric(self):
        """Регресия: килът/стабилизаторът (NACA 0009) излизаха несиметрични —
        носът беше шев между две криви, а точките се избираха поотделно."""
        for name, _file, spec in assembly.tail_specs(self.res):
            sections = assembly.surface_rings(**dict(spec, points=16, stations=5))
            for spline in se.simplified_airfoil_splines(sections):
                le = min(range(len(spline)), key=lambda i: spline[i][0])
                side_a = list(reversed(spline[:le + 1]))
                side_b = spline[le:]
                self.assertEqual(len(side_a), len(side_b), name)
                for p, q in zip(side_a, side_b):
                    self.assertAlmostEqual(p[0], q[0], places=6, msg=name)
                    self.assertAlmostEqual(p[1], -q[1], places=6, msg=name)

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
                    "Stabilizer_V_L", "Wing_R", "Wing_L")
        self.assertGreater(len(self.bodies), 2)
        for name, body in self.by_name.items():
            if name == "Fuselage" or body.get("cutter"):
                # резачите на елероните не се вливат: intersect/cut с крилото
                continue
            if name in separate:
                self.assertNotIn("into", body, name)
                continue
            if name == "Fin":
                self.assertNotIn("into", body, name)
                continue
            self.assertEqual(body.get("into"), "Fuselage", name)

    def test_gap_panels_remain_separate_from_fuselage(self):
        bodies = assembly.loft_bodies(
            result(layout={"wing_root_gap_mm": 10, "tail_root_gap_mm": 10}),
            None, FAST)
        panels = {b["name"]: b for b in bodies
                  if b["name"] in ("Wing_R", "Wing_L",
                                    "Stabilizer_R", "Stabilizer_L")}
        for name, body in panels.items():
            self.assertNotIn("into", body, name)
        self.assertFalse(any(b.get("root_bridge") for b in bodies))


        names = {body["name"] for body in bodies}


    def test_tail_can_be_joined_on_request(self):
        joined = assembly.loft_bodies(self.res, None, FAST, join_tail=True)
        by_name = {b["name"]: b for b in joined}
        for name in ("Stabilizer_R", "Stabilizer_L"):
            self.assertEqual(by_name[name].get("into"), "Fuselage", name)

    def test_t_tail_stabilizer_is_not_joined_into_the_fuselage(self):
        """T-опашката: стабилизаторът е на кила, не в тялото."""
        bodies = assembly.loft_bodies(
            result(tail={"type": "t_tail"}), None, FAST)
        by_name = {b["name"]: b for b in bodies}
        for name in ("Stabilizer_R", "Stabilizer_L"):
            self.assertNotIn("into", by_name[name], name)
        # и не се описва като влято във фюзелажа в стъпките
        steps = {step["id"]: step for step in se.group_steps(bodies)}
        self.assertIn("Stabilizer_R", steps["tail"]["bodies"])

    def test_t_tail_join_lands_the_stabilizer_on_the_fin(self):
        """Заявеното обединяване на T-опашка влива стабилизатора в кила."""
        bodies = assembly.loft_bodies(
            result(tail={"type": "t_tail"}), None, FAST, join_tail=True)
        by_name = {b["name"]: b for b in bodies}
        for name in ("Stabilizer_R", "Stabilizer_L"):
            self.assertEqual(by_name[name].get("into"), "Fin", name)
        # килът е преди стабилизатора в реда на изграждане
        order = [b["name"] for b in se.body_order(bodies)]
        self.assertLess(order.index("Fin"), order.index("Stabilizer_R"))

    def test_v_tail_gap_is_measured_from_the_skin(self):
        """Луфтът на V-панела е по оста на панела, от обшивката."""
        res = result(tail={"type": "v_tail"})
        fus = res["geometry"]["fuselage"]
        gamma = math.radians(float(res["layout"].get("v_tail_deg", 35.0)))
        bodies = assembly.loft_bodies(res, None, FAST, tail_root_gap_mm=6.0)
        by_name = {b["name"]: b for b in bodies}
        z_center = fus["height_mm"] / 2.0
        for name, sign in (("Stabilizer_V_R", 1.0), ("Stabilizer_V_L", -1.0)):
            section = by_name[name]["sections"][0]
            x, y, z = section["origin"]
            skin = assembly.skin_offset(
                fus, x, (0.0, sign * math.cos(gamma), math.sin(gamma)))
            radial = math.hypot(y, z - z_center)
            self.assertAlmostEqual(radial, skin + 6.0, places=2)
            self.assertGreater(radial - skin, 5.0)

    def test_zero_gap_tails_join_into_the_fuselage(self):
        """Луфт 0 = опашката е част от модела (конвенционална и V)."""
        for tail in ({"type": "conventional"}, {"type": "v_tail"}):
            res = result(tail=tail)
            bodies = assembly.loft_bodies(
                res, None, FAST, wing_root_gap_mm=0.0, tail_root_gap_mm=0.0)
            by_name = {b["name"]: b for b in bodies}
            fus = res["geometry"]["fuselage"]
            for name in ("Stabilizer_R", "Stabilizer_L",
                         "Stabilizer_V_R", "Stabilizer_V_L"):
                if name not in by_name:
                    continue
                self.assertEqual(by_name[name].get("into"), "Fuselage",
                                 "%s / %s" % (name, tail["type"]))
                if name.startswith("Stabilizer_V"):
                    # V-панелите влизат в тялото по конструкция: коренът им е
                    # в обшивката, затова не искат embed_mm
                    sign = 1.0 if name.endswith("R") else -1.0
                    gamma = math.radians(
                        float(res["layout"].get("v_tail_deg", 35.0)))
                    section = by_name[name]["sections"][0]
                    x, y, z = section["origin"]
                    skin = assembly.skin_offset(
                        fus, x, (0.0, sign * math.cos(gamma), math.sin(gamma)))
                    self.assertLess(math.hypot(y, z - fus["height_mm"] / 2.0),
                                    skin, name)
                else:
                    self.assertIn("embed_mm", by_name[name], name)

    def test_root_gap_makes_separate_tail_step(self):
        bodies = assembly.loft_bodies(
            result(layout={"tail_root_gap_mm": 10}), None, FAST,
            tail_root_gap_mm=10)
        steps = {step["id"]: step for step in se.group_steps(bodies)}
        # с положителен луфт опашката е в собственa стъпка, без мостове
        self.assertIn("Stabilizer_R", steps["tail"]["bodies"])
        self.assertIn("Stabilizer_L", steps["tail"]["bodies"])
        self.assertNotIn("TailRootBridge_R", steps["tail"]["bodies"])
        self.assertNotIn("TailRootBridge_L", steps["tail"]["bodies"])
        self.assertIn("Fin", steps["fin"]["bodies"])
        self.assertNotIn("FinRootBridge", steps["fin"]["bodies"])

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
        # луфт 0 = крилото и опашката се вливат в тялото; всички
        # обединявания отиват в един `solid.combine`
        bodies = assembly.loft_bodies(
            result(layout={"wing_root_gap_mm": 0, "tail_root_gap_mm": 0}),
            None, FAST)
        combines = [c for c in se.build_commands(bodies)
                    if c["command"] == "solid.combine"
                    and c["params"].get("operation") == "join"]
        self.assertEqual(len(combines), 1)
        params = combines[0]["params"]
        self.assertEqual(params["target"], "Fuselage")
        self.assertEqual(params["operation"], "join")
        for name in ("Wing_R", "Wing_L", "Stabilizer_R", "Stabilizer_L",
                     "Cowl", "Spinner"):
            self.assertIn(name, params["tools"])
        self.assertFalse(any(b.get("root_bridge") for b in bodies))
        # килът остава отделно тяло (не влиза в combine-а)
        self.assertNotIn("Fin", params["tools"])

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
        # застъпване има само когато крилото се влива (луфт 0)
        res = result(layout={"wing_position": "high",
                             "wing_root_gap_mm": 0, "tail_root_gap_mm": 0})
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

    def test_root_fairing_increases_chord_and_thickness_at_root(self):
        res = result(layout={"wing_position": "high"})
        spec = assembly.wing_spec(res, None)
        raw = assembly.half_rings(spec, 1, points=12, stations=6,
                                  root_overlap_mm=assembly.JOIN_EMBED_MM)
        fair = assembly.wing_root_fairing(raw, spec["span_mm"] / 2.0)
        root_raw, root_fair = raw[0], fair[0]
        raw_x = [p[0] for p in root_raw["points2d"]]
        fair_x = [p[0] for p in root_fair["points2d"]]
        raw_z = [p[1] for p in root_raw["points2d"]]
        fair_z = [p[1] for p in root_fair["points2d"]]
        self.assertGreater(max(fair_x) - min(fair_x),
                           max(raw_x) - min(raw_x))
        self.assertGreater(max(fair_z) - min(fair_z),
                           max(raw_z) - min(raw_z))
        raw_x0, raw_x1 = min(raw_x), max(raw_x)
        fair_x0, fair_x1 = min(fair_x), max(fair_x)
        raw_qc = raw_x0 + 0.25 * (raw_x1 - raw_x0)
        fair_qc = fair_x0 + 0.25 * (fair_x1 - fair_x0)
        self.assertAlmostEqual(raw_qc, fair_qc, places=6)
        self.assertAlmostEqual(root_fair["root_fairing"]["chord_scale"],
                               assembly.ROOT_FAIRING_CHORD_RATIO, places=3)

    def test_root_fairing_returns_to_design_profile_after_fade(self):
        res = result()
        spec = assembly.wing_spec(res, None)
        raw = assembly.half_rings(spec, 1, points=12, stations=6)
        fair = assembly.wing_root_fairing(
            raw, spec["span_mm"] / 2.0, fade_span_mm=60.0)
        self.assertEqual(fair[-1]["points2d"], raw[-1]["points2d"])
        self.assertEqual(fair[-1]["points3d"], raw[-1]["points3d"])
        for old, new in zip(raw, fair):
            self.assertAlmostEqual(old["origin"][1], new["origin"][1])
            self.assertAlmostEqual(old["origin"][2], new["origin"][2])


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

    @unittest.skipUnless(se.find_cli(), "няма solidcraft-cli")
    def test_elliptic_fuselage_sketch_command_runs_in_solidcraft(self):
        fuselage = next(body for body in assembly.loft_bodies(
            result(), None, FAST) if body["name"] == "Fuselage")
        script = {"commands": se.build_commands([fuselage], combine=False)}
        with tempfile.TemporaryDirectory(prefix="aeroforge_ellipse_") as folder:
            path = os.path.join(folder, "ellipse.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(script, stream)
            proc = subprocess.run(
                [se.find_cli(), "run", path, "--results", "--quiet"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertNotIn("error:", (proc.stderr + proc.stdout).lower())

    @unittest.skipUnless(se.find_cli(), "няма solidcraft-cli")
    def test_simplified_wing_loft_runs_in_solidcraft(self):
        wing = next(body for body in assembly.loft_bodies(
            result(), None, FAST) if body["name"] == "Wing_R")
        script = {"commands": se.build_commands([wing], combine=False)}
        with tempfile.TemporaryDirectory(prefix="aeroforge_wing_loft_") as folder:
            path = os.path.join(folder, "wing.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(script, stream)
            proc = subprocess.run(
                [se.find_cli(), "run", path, "--results", "--quiet"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertNotIn("error:", (proc.stderr + proc.stdout).lower())

    @unittest.skipUnless(se.find_cli(), "няма solidcraft-cli")
    def test_fillet_on_selected_edges_runs_in_solidcraft(self):
        # Small native command probe: a deliberately simple prismatic solid
        # verifies edge picks and the fillet command accepted by our CLI.
        commands = [
            {"command": "sketch.create", "params": {
                "plane": "XY", "name": "Probe profile"}},
            {"command": "sketch.line", "params": {
                "points": [[0, 0], [100, 0], [100, 30], [0, 30]],
                "closed": True}},
            {"command": "sketch.finish", "params": {}},
            {"command": "solid.extrude", "params": {
                "distance": 50, "sketch": "Probe profile",
                "body_name": "Probe body"}},
            {"command": "solid.fillet", "params": {
                "body": "Probe body", "edges": [[50, 30, 0]],
                "radius": 2, "name": "Probe fillet"}},
        ]
        with tempfile.TemporaryDirectory(prefix="aeroforge_fillet_probe_") as folder:
            path = os.path.join(folder, "fillet.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump({"commands": commands}, stream)
            proc = subprocess.run(
                [se.find_cli(), "run", path, "--results", "--quiet"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertNotIn("error:", (proc.stderr + proc.stdout).lower())

    def test_svg_contains_a_closed_path(self):
        section = assembly.loft_bodies(
            result(), None, FAST)[0]["sections"][0]
        text = se.svg_text(section["points2d"], se._profile_path(section))
        self.assertTrue(text.startswith("<?xml"))
        self.assertIn("<svg", text)
        self.assertTrue(text.rstrip().endswith("</svg>"))
        self.assertIn('d="M', text)
        self.assertIn("Z", text)

    def test_elliptic_fuselage_svg_uses_ellipse_element(self):
        fuselage = next(body for body in assembly.loft_bodies(
            result(), None, FAST) if body["name"] == "Fuselage")
        section = fuselage["sections"][1]
        text = se.svg_text(section["points2d"], se._profile_path(section),
                           section["primitive"])
        root = ET.fromstring(text)
        ellipse = root.find(".//{http://www.w3.org/2000/svg}ellipse")
        self.assertIsNotNone(ellipse)
        self.assertIsNone(root.find(".//{http://www.w3.org/2000/svg}path"))


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
        # детайлният модел има свой бавен тест (test_detailed_model)
        cls.out = se.export(result(), cls.dir, detail=FAST, timeout=45,
                            slugify=lambda _n: "demo",
                            options={"timeout": 45, "detailed": False})
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

