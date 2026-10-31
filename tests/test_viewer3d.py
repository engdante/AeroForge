"""
Тестове за 3D прегледа (app/web/js/viewer3d.js).

Рендерът е JavaScript, затова проверката минава през `node` с мъничък
мок на WebGL контекста — така се хващат точно математическите грешки,
които не се виждат от Python (напр. грешен мащаб по дълбочина, от който
моделът изчезва от екрана).

Ако `node` липсва, тестовете се пропускат — приложението не зависи от него.
"""

import json
import os
import shutil
import subprocess
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import design, geometry3d  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWER = os.path.join(ROOT, "app", "web", "js", "viewer3d.js")
STYLE = os.path.join(ROOT, "app", "web", "style.css")
INDEX = os.path.join(ROOT, "app", "web", "index.html")

# Мок на WebGL: записва uniform-ите, за да се проверят матрицата и мащабът.
HARNESS = r"""
const fs = require('fs');
const path = process.argv[2];
const payload = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const src = fs.readFileSync(path, 'utf8');

const out = { uniforms: null, draws: [], useGL: null };
const ids = { VERTEX_SHADER: 1, FRAGMENT_SHADER: 2, COMPILE_STATUS: 3,
              LINK_STATUS: 4, ARRAY_BUFFER: 5, ELEMENT_ARRAY_BUFFER: 6,
              STATIC_DRAW: 7, DEPTH_TEST: 8, LEQUAL: 9, CULL_FACE: 10,
              BACK: 11, CCW: 12, TRIANGLES: 13, UNSIGNED_SHORT: 14,
              UNSIGNED_INT: 15, COLOR_BUFFER_BIT: 16, DEPTH_BUFFER_BIT: 17,
              FLOAT: 18, LEQUAL2: 19 };
const gl = new Proxy(ids, {
  get(target, key) {
    if (key in target) return target[key];
    if (key === 'drawElements') return (m, count) => out.draws.push(count);
    if (key === 'getShaderParameter' || key === 'getProgramParameter') {
      return () => true;
    }
    if (key === 'getAttribLocation') return () => 0;
    if (key === 'getUniformLocation') return (p, name) => name;
    if (key === 'uniform3f') {
      return (name, x, y, z) => {
        if (name === 'uScale') out.uniforms = [x, y, z];
      };
    }
    if (key === 'uniformMatrix4fv') {
      return (name, transpose, mat) => { out.view = Array.from(mat); };
    }
    if (key === 'createBuffer' || key === 'createShader' || key === 'createProgram') {
      return () => ({});
    }
    if (key === 'getExtension') return () => null;
    return () => {};
  },
});

global.window = { devicePixelRatio: 1, addEventListener: () => {} };
const noWebgl = !!payload.noWebgl;
const makeCanvas = (withGL) => ({
  getContext: (type) =>
    (withGL && !noWebgl && type === 'webgl' ? gl : null),
  addEventListener: () => {}, style: {}, width: 900, height: 460, dataset: {},
  removeAttribute: () => {},
  cloneNode: () => makeCanvas(false),
  parentNode: { replaceChild: () => {} },
});
global.document = {
  getElementById: (id) => (id === 'model3d' ? makeCanvas(true) : makeCanvas(false)),
};
eval(src + '\nglobal.Viewer = Viewer;');
Viewer.init();
Viewer.setModel(payload.model);
out.useGL = Viewer.useGL;
out.has2d = !!Viewer.ctx2d;
out.scale = Viewer.scale;
out.radius = Viewer.radius;
// клип-координати на всички върхове (точно както ги смята шейдърът)
const m = Viewer._viewMatrix();
const s = Viewer.scale * Viewer.zoom;
const mesh = Viewer.meshData();
const u = out.uniforms || [1, 1, 1];
const clip = [];
mesh.vlist.forEach((p) => {
  const x = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12];
  const y = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
  const z = m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14];
  clip.push([x * u[0], y * u[1], z * u[2]]);
});
out.clip = clip;
out.vertices = mesh.vlist.length;
out.triangles = mesh.tris.length;
console.log(JSON.stringify(out));
"""


def _node():
    return shutil.which("node")


@unittest.skipUnless(_node(), "няма node — тестовете за рендера се пропускат")
class TestViewer3D(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = design.compute({"mission": "trainer",
                                 "payload": {"mode": "simple", "total_g": 600}})
        model = geometry3d.build_model(result, quality="normal")
        cls.model = model
        cls.data = cls.run_render(model)

    @classmethod
    def run_render(cls, model, no_webgl=False):
        import tempfile
        folder = tempfile.mkdtemp()
        harness = os.path.join(folder, "harness.js")
        payload = os.path.join(folder, "model.json")
        with open(harness, "w", encoding="utf-8") as handle:
            handle.write(HARNESS)
        with open(payload, "w", encoding="utf-8") as handle:
            json.dump({"model": model, "noWebgl": bool(no_webgl)}, handle)
        proc = subprocess.run([_node(), harness, VIEWER, payload],
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise AssertionError("node: %s" % (proc.stderr or proc.stdout))
        return json.loads(proc.stdout)

    def test_syntax_is_valid(self):
        proc = subprocess.run([_node(), "--check", VIEWER],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_webgl_path_is_used(self):
        self.assertTrue(self.data["useGL"])
        self.assertGreater(self.data["vertices"], 100)
        self.assertGreater(self.data["triangles"], 100)

    def test_every_vertex_is_inside_the_clip_volume(self):
        """Регресия: грешен мащаб по дълбочина изхвърляше целия модел."""
        worst = 0.0
        for x, y, z in self.data["clip"]:
            worst = max(worst, abs(x), abs(y), abs(z))
        self.assertLessEqual(worst, 1.0,
                             "връх извън clip space (%.3f) — моделът се реже"
                             % worst)
        # и моделът наистина запълва сцената, а не е точка в центъра
        self.assertGreater(worst, 0.5)

    def test_model_is_visible_on_screen(self):
        xs = [p[0] for p in self.data["clip"]]
        ys = [p[1] for p in self.data["clip"]]
        self.assertGreater(max(xs) - min(xs), 0.4)
        self.assertGreater(max(ys) - min(ys), 0.2)

    def test_triangles_are_drawn(self):
        self.assertTrue(self.data["draws"])
        self.assertGreater(self.data["draws"][0], 0)

    def test_fallback_without_webgl(self):
        """Без WebGL трябва да мине на 2D, а не да остави празен канвас."""
        data = self.run_render(self.model, no_webgl=True)
        self.assertFalse(data["useGL"])
        self.assertEqual(data["triangles"], self.data["triangles"])


class TestViewerStyles(unittest.TestCase):
    """Регресия: overlay-ът не бива да е непрозрачен (скрива модела)."""

    @classmethod
    def setUpClass(cls):
        with open(STYLE, encoding="utf-8") as handle:
            cls.css = handle.read()
        with open(INDEX, encoding="utf-8") as handle:
            cls.html = handle.read()

    def test_overlay_is_transparent(self):
        block = self.css.split("#model3dOverlay", 1)[1].split("}", 1)[0]
        self.assertIn("transparent", block)
        self.assertNotIn("#121821", block)
        self.assertIn("border: 0", block)

    def test_overlay_is_stacked_over_the_canvas(self):
        block = self.css.split("#model3dOverlay", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute", block)
        self.assertIn('id="model3dOverlay"', self.html)
        self.assertIn('id="model3d"', self.html)

    def test_style_has_cache_busting(self):
        self.assertIn("style.css?v=", self.html)


if __name__ == "__main__":
    unittest.main()
