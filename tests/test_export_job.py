"""
Тестове за стъпковия експорт (`export_job`): прогрес, отказ, 3MF, папки.

Проверява се това, което потребителят вижда в панела:
  * стъпките са подредени (подготовка → тяло → крила → опашка → финал);
  * всяка стъпка връща състояние с прогрес, лог и ETA;
  * при липса на solidcraft-cli експортът пак дава 3MF и сечения;
  * отказът спира следващите стъпки;
  * файловете (STEP, 3MF, .sc, README, manifest) се записват там, където
    ги чака UI-ят.
"""

import json
import os
import shutil
import tempfile
import unittest
import zipfile

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import assembly, design, export_job  # noqa: E402
from core import solidcraft_export as se  # noqa: E402

FAST = {"points": 10, "stations": 3, "fuselage_ring": 14,
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


class TestSteps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = result()
        cls.bodies = assembly.loft_bodies(cls.res, None, FAST)
        cls.steps = se.group_steps(cls.bodies)
        cls.ids = [step["id"] for step in cls.steps]

    def test_steps_are_in_order(self):
        self.assertEqual(self.ids[0], "prep")
        self.assertEqual(self.ids[1], "body")
        self.assertIn("wing", self.ids)
        # двете полукрила НЕ са отделни стъпки: вторият join върху вече
        # променено тяло висеше и оставяше модела с едно крило
        self.assertNotIn("wing_r", self.ids)
        self.assertNotIn("wing_l", self.ids)
        self.assertEqual(self.ids[-1], "finish")

    def test_both_wings_share_one_step_and_one_combine(self):
        wing = [step for step in self.steps if step["id"] == "wing"][0]
        self.assertIn("Wing_R", wing["bodies"])
        self.assertIn("Wing_L", wing["bodies"])
        script = se.group_script(self.bodies, wing["bodies"])
        combines = [c for c in script["commands"]
                    if c["command"] == "solid.combine"]
        self.assertEqual(len(combines), 1)
        self.assertEqual(sorted(combines[0]["params"]["tools"]),
                         ["Wing_L", "Wing_R"])

    def test_every_body_is_in_exactly_one_group(self):
        names = [b["name"] for b in self.bodies]
        grouped = [name for step in self.steps for name in step["bodies"]]
        self.assertEqual(sorted(grouped), sorted(names))
        # основата е първа в групата „тяло“
        self.assertIn("Fuselage", self.steps[1]["bodies"])

    def test_steps_have_estimates(self):
        for step in self.steps:
            self.assertGreater(step["est_s"], 0, step["id"])
            self.assertTrue(step["label"])

    def test_group_script_keeps_the_base_first(self):
        script = se.group_script(self.bodies, ["Fuselage", "Cowl"])
        lofts = [c for c in script["commands"] if c["command"] == "solid.loft"]
        self.assertEqual(lofts[0]["params"]["body_name"], "Fuselage")


class TestTiming(unittest.TestCase):
    def test_parse_timing_sums_the_booleans(self):
        text = json.dumps({"total_ms": 1200, "timings": [
            {"index": 1, "command": "solid.loft",
             "profile": {"boolean_ms": 700.0, "tessellate_ms": 10.0}},
            {"index": 2, "command": "solid.revolve",
             "profile": {"boolean_ms": 100.0}},
        ]})
        timing = se.parse_timing("шум преди\n" + text)
        self.assertEqual(timing["total_ms"], 1200)
        self.assertEqual(timing["boolean_ms"], 800)
        self.assertEqual(timing["commands"], 2)

    def test_parse_timing_survives_garbage(self):
        self.assertEqual(se.parse_timing("няма json"), {})
        self.assertEqual(se.parse_timing("{не е json}"), {})


class TestWingRetries(unittest.TestCase):
    """Стъпаловидните опити за крилата (export_job._attempts)."""

    def test_zero_sink_still_gets_a_deeper_attempt(self):
        attempts = export_job._wing_attempts(0.0, 60.0)
        self.assertEqual(attempts[0], {})
        self.assertAlmostEqual(attempts[1]["sink_mm"],
                               -assembly.ROOT_SINK_FRAC * 60.0)

    def test_existing_sink_is_increased(self):
        attempts = export_job._wing_attempts(-6.0, 60.0)
        self.assertAlmostEqual(attempts[1]["sink_mm"], -9.6)

    def test_last_attempt_leaves_the_wings_unjoined(self):
        attempts = export_job._wing_attempts(-6.0, 60.0)
        self.assertTrue(attempts[-1].get("unjoin"))

    def test_tail_retries_lift_the_stabilizer(self):
        attempts = export_job._attempts({"id": "tail"}, 0.0, 60.0)
        self.assertEqual([a.get("tail_lift_mm") for a in attempts],
                         [None, 15.0, 6.0])

    def test_wing_step_has_its_own_timeout(self):
        job = {"timeout": 150}
        self.assertEqual(export_job._step_timeout(job, {"id": "wing"}),
                         export_job.WING_TIMEOUT_S)
        self.assertEqual(export_job._step_timeout(job, {"id": "fin"}),
                         150.0)
        # кратък таймаут (тестове) се удължава пропорционално, не до 240 s
        self.assertEqual(
            export_job._step_timeout({"timeout": 45}, {"id": "wing"}), 72.0)

    def test_unjoin_keeps_only_the_wings_separate(self):
        bodies = [{"name": "Fuselage"},
                  {"name": "Wing_R", "into": "Fuselage", "embed_mm": 0.0},
                  {"name": "Fin", "into": "Fuselage"}]
        out = export_job._unjoin(bodies, ["Wing_R"])
        by_name = {body["name"]: body for body in out}
        self.assertNotIn("into", by_name["Wing_R"])
        self.assertNotIn("embed_mm", by_name["Wing_R"])
        self.assertEqual(by_name["Fin"]["into"], "Fuselage")


class TestSymmetryCheck(unittest.TestCase):
    """Липсващо полукрило се хваща по bbox от `eval`."""

    ONE_WING = {"bodies": [{"name": "Fuselage", "bbox": {
        "min": [0.0, -31.7, 0.0], "max": [830.0, 484.7, 160.0]}}]}
    BOTH_WINGS = {"bodies": [{"name": "Fuselage", "bbox": {
        "min": [0.0, -484.7, 0.0], "max": [830.0, 484.7, 160.0]}}]}

    def _job(self, ev):
        return {"res": {"geometry": {"span_mm": 971.0}}, "eval": ev,
                "warnings": [], "log": [], "t0": 0.0}

    def test_missing_half_is_measured(self):
        # |−31.7| срещу |484.7|: липсва почти цялата половина
        self.assertAlmostEqual(export_job.max_asymmetry_mm(self.ONE_WING),
                               453.0, delta=0.1)

    def test_symmetric_model_has_no_asymmetry(self):
        self.assertAlmostEqual(export_job.max_asymmetry_mm(self.BOTH_WINGS),
                               0.0, places=6)

    def test_warning_names_the_asymmetry(self):
        job = self._job(self.ONE_WING)
        step = {"detail": "10 s"}
        asym = export_job._check_symmetry(job, step)
        self.assertGreater(asym, 400.0)
        self.assertTrue(any("асиметричен" in w for w in job["warnings"]))
        self.assertIn("асиметричен", step["detail"])

    def test_symmetric_model_does_not_warn(self):
        job = self._job(self.BOTH_WINGS)
        step = {"detail": "10 s"}
        self.assertEqual(export_job._check_symmetry(job, step), 0.0)
        self.assertEqual(job["warnings"], [])
        self.assertEqual(step["detail"], "10 s")

    def test_missing_bbox_is_not_an_asymmetry(self):
        self.assertEqual(export_job.max_asymmetry_mm(
            {"bodies": [{"name": "Fuselage"}]}), 0.0)
        self.assertEqual(export_job.max_asymmetry_mm(None), 0.0)




if __name__ == "__main__":
    unittest.main()


class TestJobWithoutCli(unittest.TestCase):
    """Без solidcraft-cli: 3MF, сечения и README пак трябва да ги има."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="aeroforge_job_")
        cls.state = export_job.start(result(), cls.dir, detail=FAST,
                                     options={"run": False},
                                     slugify=lambda _n: "demo")
        cls.job = cls.state["job"]
        cls.final = cls.state
        for index in range(len(export_job.JOBS[cls.job]["steps"])):
            cls.final = export_job.run_step(cls.job, index)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_start_returns_steps_and_folder(self):
        self.assertTrue(self.state["ok"])
        self.assertTrue(os.path.isdir(self.state["folder"]))
        self.assertGreaterEqual(len(self.state["steps"]), 4)
        self.assertGreater(self.state["eta_s"], 0)

    def test_run_reports_progress(self):
        self.assertEqual(self.final["status"], "done")
        self.assertAlmostEqual(self.final["progress"], 100.0, places=3)
        self.assertTrue(all(s["state"] in ("done", "skipped")
                            for s in self.final["steps"]))

    def test_sections_and_manifest_exist(self):
        folder = self.final["folder"]
        self.assertTrue(os.path.exists(
            os.path.join(folder, "sections", "manifest.csv")))
        self.assertGreater(self.final["sections"], 5)
        svgs = [name for _root, _dirs, files in os.walk(
            os.path.join(folder, "sections")) for name in files
            if name.endswith(".svg")]
        self.assertGreaterEqual(len(svgs), 5)

    def test_3mf_is_written_from_the_mesh(self):
        path = os.path.join(self.final["folder"], "aircraft.3mf")
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.final["three_mf"]["source"], "mesh")
        with zipfile.ZipFile(path) as zf:
            model = zf.read("3D/3dmodel.model").decode("utf-8")
        self.assertIn('unit="millimeter"', model)
        self.assertIn("<mesh>", model)

    def test_reference_and_readme_are_written(self):
        folder = self.final["folder"]
        self.assertTrue(os.path.exists(os.path.join(folder, "reference.step")))
        self.assertTrue(os.path.exists(os.path.join(folder, "reference.3mf")))
        with open(os.path.join(folder, "README.txt"), encoding="utf-8-sig") as f:
            text = f.read()
        self.assertIn("3MF", text)
        self.assertIn("STEP", text)
        # при липса на CLI няма STEP, но има ясно обяснение
        self.assertIsNone(self.final["step"])

    def test_manifest_lists_steps_and_warnings(self):
        path = os.path.join(self.final["folder"], "model_manifest.json")
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertTrue(manifest["steps"])
        self.assertIn("files", manifest)
        self.assertIn("wing", manifest)


class TestCancel(unittest.TestCase):
    def test_cancel_stops_further_steps(self):
        job = export_job.start(result(), tempfile.mkdtemp(prefix="af_cancel_"),
                               detail=FAST, options={"run": False},
                               slugify=lambda _n: "demo")
        export_job.cancel(job["job"])
        state = export_job.run_step(job["job"], 0)
        self.assertEqual(state["status"], "cancelled")

