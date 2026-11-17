"""
detailed_model.py — детайлен модел за SolidCraft (aircraft_detailed.sc).

Сегашният `aircraft.sc` носи само профилите (основа за собствено
моделиране). Тук се строи модел с реални обеми:

  * крило — **едно тяло от връх до връх** с централен профил в оста на
    самолета. Около тялото профилът плавно расте (хорда ×CENTER_CHORD,
    дебелина ×CENTER_THICK, до t/c CENTER_TC_MAX): по-висок спар в корена
    (здраво) и плавен преход към тялото (без рязък ъгъл — по-малко
    интерферентно съпротивление). Крилото е слято с тялото;
    лентите на спара и тръбата минават непрекъснато през центъра;
  * опашка — стабилизаторът също е едно тяло с централен профил, килът —
    с коренен профил в тялото; слети с тялото (при T-опашка
    стабилизаторът — с върха на кила);
  * тяло — кухо (вътрешен loft, свит със стената), капак отгоре,
    преграда за мотора; в тялото са само сервата за опашката (REF_*);
  * елерон — отделно тяло с шарнирна панта (жлеб, закръглен скосен нос,
    уши, ос), кормилен рог и тяга; серво в гнездо в крилото с капаче;
    сервата са избрани по шарнирния момент (controls.servo_sizing).

Ограничението от по-ранните версии на SolidCraft (крилото на две половини,
защото обединението през тялото висеше) вече го няма — проверено с
реалния CLI.

Координати (mm): X назад от носа, Y надясно, Z нагоре (Z = 0 коремът) —
същите като на останалия CAD модел (виж assembly.DATUM).
"""

import math

from . import airfoils
from . import assembly
from . import controls
from . import motor as motor_mod
from . import printgeom

# ---------------------------------------------------------------- размери
WALL_MM = 1.2                 # стена на кухото тяло
FIREWALL_MM = 3.0             # преграда за мотора
MOTOR_BOLT_D_MM = 3.2         # отвори M3 на кръстатата стойка
MOTOR_MOUNT_RIM_MM = 3.5      # стойката е по-широка от кръга на отворите
HATCH_GAP_MM = 0.3            # процеп около капака
HATCH_TOP_FRAC = 0.62         # капакът е над тази част от височината

# централен профил (крило и опашка) — виж SurfaceFrame
CENTER_CHORD = 1.20           # хорда в оста спрямо коренната
CENTER_THICK = 1.40           # дебелина в оста спрямо профила
CENTER_TC_MAX = 0.17          # ... но t/c в оста не повече от това
CENTER_BLEND_CHORDS = 0.5     # преходът свършва на ½ хорда извън тялото

TUBE_CLEARANCE_MM = 0.3       # канал на тръбата (диаметрално)

HINGE_GAP_MM = 0.4            # процеп между жлеба и закръгления ръб
HINGE_BEVEL_DEG = 35.0        # скос на предния ръб на елерона горе/долу
AILERON_THROW_DEG = 25.0      # ход, за който е проверен скосът
HINGE_LIP_MM = 1.0            # минимална стена над/под жлеба
HINGE_R_MIN, HINGE_R_MAX = 1.5, 6.0
KNUCKLE_PITCH_MM = 60.0       # уши през ~60 mm
KNUCKLE_LEN_MM = 8.0
PIN_D_MM = 1.9                # ос: филамент 1.75 mm (+ луфт)
TAIL_PIN_D_MM = 1.2           # опашката е тънка: ос — стоманена тел Ø1 mm
CONTROL_RETREAT_MM = 6.0      # резервен вариант: кормилото по-навътре от краищата
COVE_OVERRUN_MM = 0.5         # жлебът е малко по-дълъг от процепа
TAIL_R_MIN = 1.0              # ... и по-малък нос (тел Ø1 mm в него)
TAIL_LIP_MM = 0.8             # стена над жлеба на опашката
KNUCKLE_OVERLAP_MM = 0.15     # ухото застъпва в материала (иначе цилиндърът
                              # му съвпада с жлеба и boolean-ът се проваля)

HORN_T_MM = 2.0               # кормилен рог: дебелина (по размаха)
HORN_LEN_MM = 9.0             # по хордата
HORN_DROP_MM = 12.0           # под долната повърхност
HORN_HOLE_D_MM = 1.3          # отвор за тягата (тел 1.2 mm)
PUSHROD_D_MM = 1.2

SERVO_CLEAR_MM = 0.5
SERVO_COVER_MM = 1.2          # капаче на гнездото
CABLE_D_MM = 6.0              # канал за кабела на сервото
CABLE_EXIT_D_MM = 7.0         # отвор от разклонителя към кухината
JUNCTION_MM = (16.0, 20.0, 9.0)   # разклонител в оста (x, y, z)

SPAR_SLOT_CLEAR_MM = 0.2      # луфт около лентата на спара
SPAR_END_FRAC = 0.95          # слотът свършва преди върха

CUTTER_STATIONS = 4
FUSELAGE_STATIONS = 16        # сечения на тялото в детайлния модел
OUTER_STATIONS = 6            # сечения от прехода до върха


def _r(value):
    value = round(float(value), 4)
    return 0.0 if value == 0 else value


def _v(p):
    return [_r(p[0]), _r(p[1]), _r(p[2])]


class Script:
    """Команди за SolidCraft с кратки помощници за примитивите."""

    def __init__(self):
        self.commands = []
        self.notes = []

    def add(self, command, **params):
        self.commands.append({"command": command, "params": params})

    def box(self, name, x0, x1, y0, y1, z0, z1):
        xa, xb = sorted((x0, x1))
        ya, yb = sorted((y0, y1))
        za, zb = sorted((z0, z1))
        self.add("solid.box", corner=_v((xa, ya, za)),
                 length=_r(xb - xa), width=_r(yb - ya), height=_r(zb - za),
                 body_name=name, name=name)

    def cylinder(self, name, p0, p1, diameter):
        axis = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
        length = math.sqrt(sum(c * c for c in axis))
        if length <= 1e-6:
            return False
        unit = [c / length for c in axis]
        self.add("solid.cylinder", base=_v(p0), axis=_v(unit),
                 height=_r(length), diameter=_r(diameter),
                 body_name=name, name=name)
        return True

    def combine(self, target, tools, operation, keep=False, label=None):
        params = {"target": target, "tools": list(tools),
                  "operation": operation}
        if keep:
            params["keep_tools"] = True
        params["name"] = label or "%s %s" % (target, operation)
        self.commands.append({"command": "solid.combine", "params": params})

    def loft_planes(self, name, sections):
        """Призма през затворени многоъгълници в произволни равнини:
        sections = [((начало, x_dir, y_dir), точки 2D)]."""
        labels = []
        for i, ((origin, x_dir, y_dir), pts2d) in enumerate(sections):
            sketch = "%s S%02d" % (name, i + 1)
            labels.append(sketch)
            self.add("sketch.create",
                     plane={"origin": _v(origin), "x_dir": _v(x_dir),
                            "y_dir": _v(y_dir)},
                     frame="world", name=sketch)
            self.add("sketch.line", points=[[_r(a), _r(b)] for a, b in pts2d],
                     closed=True)
            self.add("sketch.finish")
        self.add("solid.loft", sections=[{"sketch": s} for s in labels],
                 body_name=name, name="%s loft" % name)

    def loft_polygons(self, name, sections):
        """Призма през затворени многоъгълници в равнини y = const."""
        labels = []
        for i, (y, pts2d) in enumerate(sections):
            sketch = "%s S%02d" % (name, i + 1)
            labels.append(sketch)
            self.add("sketch.create",
                     plane={"origin": [0.0, _r(y), 0.0],
                            "x_dir": [1.0, 0.0, 0.0],
                            "y_dir": [0.0, 0.0, 1.0]},
                     frame="world", name=sketch)
            self.add("sketch.line", points=[[_r(a), _r(b)] for a, b in pts2d],
                     closed=True)
            self.add("sketch.finish")
        self.add("solid.loft", sections=[{"sketch": s} for s in labels],
                 body_name=name, name="%s loft" % name)


# ------------------------------------------------------- носещи повърхности
class SurfaceFrame:
    """
    Носеща повърхност (крило, стабилизатор, кил) като функция:
    точка от профила (u по хордата, v по дебелината) на станция s → свят.

    Станцията s се мери по `span_axis` от `origin` (при симетрична
    повърхност — ±s, оста е s = 0). Хорда, усукване, диедър и извит връх
    са като в `assembly.surface_rings`. Около оста (|s| < blend_mm)
    профилът плавно се уголемява до централния: хорда ×k_chord (около ¼
    хорда) и дебелина ×k_thick (около средата) — косинусов преход, без
    чупка в повърхността.

    Сеченията за loft-а и всички отвори/панти идват оттук → съвпадат.
    """

    def __init__(self, spec, blend_mm=0.0, k_chord=1.0, k_thick=1.0,
                 points=None):
        self.spec = spec
        self.symmetric = bool(spec.get("symmetric"))
        span = float(spec["span_mm"])
        self.semi = span / 2.0 if self.symmetric else span
        self.c_root = float(spec["chord_root_mm"])
        self.c_tip = float(spec["chord_tip_mm"])
        self.chord_fn = spec.get("chord_fn")
        self.tan_dih = math.tan(math.radians(float(spec.get("dihedral_deg") or 0.0)))
        self.twist = float(spec.get("twist_deg") or 0.0)
        self.upturn = float(spec.get("upturn_deg") or 0.0)
        self.upturn_frac = float(spec.get("upturn_frac") or 0.0)
        self.origin = tuple(spec["origin"])
        self.span_axis = tuple(spec.get("span_axis") or (0.0, 1.0, 0.0))
        self.thick_axis = tuple(spec.get("thick_axis") or (0.0, 0.0, 1.0))
        self.key = spec.get("airfoil_key") or airfoils.DEFAULT_AIRFOIL
        self.points = int(points or spec.get("points") or 16)
        self.unit = assembly._unit_outline(self.key, self.points, self.c_root)
        self.split = assembly._section_split(self.unit)
        self.upper, self.lower = printgeom._profile_lines(self.key, 120)
        self.blend = max(0.0, float(blend_mm))
        self.k_chord = float(k_chord)
        self.k_thick = float(k_thick)

    # --- профил
    def surface(self, u, side):
        line = self.upper if side > 0 else self.lower
        return printgeom._interp_y(line, u)

    def mid(self, u):
        return 0.5 * (self.surface(u, 1) + self.surface(u, -1))

    def thickness_ratio(self):
        return max(self.surface(k / 50.0, 1) - self.surface(k / 50.0, -1)
                   for k in range(51))

    # --- по размаха
    def f(self, s):
        return min(1.0, max(0.0, abs(s) / self.semi))

    def chord(self, s):
        f = self.f(s)
        if self.chord_fn is not None:
            return float(self.chord_fn(f))
        return self.c_root + (self.c_tip - self.c_root) * f

    def weight(self, s):
        """1 в оста → 0 на `blend` (косинусов преход, гладък в двата края)."""
        if self.blend <= 0 or abs(s) >= self.blend:
            return 0.0
        return 0.5 * (1.0 + math.cos(math.pi * abs(s) / self.blend))

    def scales(self, s):
        w = self.weight(s)
        return (1.0 + (self.k_chord - 1.0) * w,
                1.0 + (self.k_thick - 1.0) * w)

    def half_thickness(self, u, s):
        return (0.5 * (self.surface(u, 1) - self.surface(u, -1))
                * self.chord(s) * self.scales(s)[1])

    def _base(self, s):
        f = self.f(s)
        rise = abs(s) * self.tan_dih
        if self.upturn and self.upturn_frac > 0 and f > 1.0 - self.upturn_frac:
            bend = (f - (1.0 - self.upturn_frac)) / self.upturn_frac
            rise += (bend * bend * self.semi * self.upturn_frac
                     * math.tan(math.radians(self.upturn)))
        o, a, t = self.origin, self.span_axis, self.thick_axis
        return (o[0] + a[0] * s + t[0] * rise,
                o[1] + a[1] * s + t[1] * rise,
                o[2] + a[2] * s + t[2] * rise)

    def _local(self, u, v, s):
        """(u, v) → (x, z) в равнината на сечението (x от водещия ръб)."""
        chord = self.chord(s)
        tw = self.twist * self.f(s)
        lx, lz = assembly._rotated(u, v, chord, tw)
        kc, kt = self.scales(s)
        if kc != 1.0 or kt != 1.0:
            cx = assembly._rotated(0.25, self.mid(0.25), chord, tw)[0]
            zs = [assembly._rotated(a, b, chord, tw)[1] for a, b in self.unit]
            cz = 0.5 * (max(zs) + min(zs))
            lx = cx + (lx - cx) * kc
            lz = cz + (lz - cz) * kt
        return lx, lz

    def point(self, u, v, s):
        lx, lz = self._local(u, v, s)
        b, t = self._base(s), self.thick_axis
        return (b[0] + lx, b[1] + t[1] * lz, b[2] + t[2] * lz)

    def on_surface(self, u, s, side, inset=0.0):
        """Точка на горната (+1) / долната (−1) повърхност, вкарана навътре."""
        p = self.point(u, self.surface(u, side), s)
        t = self.thick_axis
        return (p[0], p[1] - side * inset * t[1], p[2] - side * inset * t[2])

    # --- сечения за loft
    def stations(self, outer=OUTER_STATIONS):
        """Станции: оста, преходът (½ и края) и синусово към върха."""
        sb = min(self.blend, 0.6 * self.semi)
        half = [0.0]
        if sb > 1.0:
            half += [0.5 * sb, sb]
        start = half[-1]
        for i in range(1, outer + 1):
            half.append(start + (self.semi - start)
                        * math.sin(0.5 * math.pi * i / outer))
        if not self.symmetric:
            return half
        return [-s for s in reversed(half[1:])] + half

    def section(self, s, name):
        pts2d = [self._local(u, v, s) for u, v in self.unit]
        b, t = self._base(s), self.thick_axis
        return {
            "name": name,
            "points2d": pts2d,
            "points3d": [(b[0] + x, b[1] + t[1] * z, b[2] + t[2] * z)
                         for x, z in pts2d],
            "origin": b,
            "x_dir": (1.0, 0.0, 0.0),
            "y_dir": t,
            "station_mm": float(s),
            "split": self.split,
        }

    def sections(self):
        return [self.section(s, "S%02d" % (i + 1))
                for i, s in enumerate(self.stations())]


def _center_factors(frame):
    """Колко расте централният профил: дебелината до CENTER_TC_MAX."""
    tc = max(1e-6, frame.thickness_ratio())
    k_thick = max(1.0, min(CENTER_THICK, CENTER_TC_MAX / tc))
    return CENTER_CHORD, k_thick


# ------------------------------------------------------------------ тяло
def _fus(res):
    return (res.get("geometry") or {}).get("fuselage") or {}


def _fus_extent(res, x):
    """(z_center, контур, z_top, z_bottom) на тялото в станция x."""
    from . import fuselage as fus_mod
    fus = _fus(res)
    length = float(fus.get("length_mm") or 1.0)
    height = float(fus.get("height_mm") or 0.0)
    zc = height / 2.0
    pts = fus_mod.outline(fus, min(1.0, max(0.0, x / length)), 72)
    return zc, pts, zc + max(p[1] for p in pts), zc + min(p[1] for p in pts)


def half_width_at(res, x, z):
    """Полуширина на тялото в станция x на височина z (0 извън него)."""
    zc, pts, z_top, z_bot = _fus_extent(res, x)
    if z >= z_top or z <= z_bot:
        return 0.0
    v = z - zc
    best = 0.0
    n = len(pts)
    for i in range(n):
        (y0, v0), (y1, v1) = pts[i], pts[(i + 1) % n]
        if (v0 - v) * (v1 - v) <= 0 and v0 != v1:
            t = (v - v0) / (v1 - v0)
            best = max(best, abs(y0 + t * (y1 - y0)))
    return best


def _max_half_width(res, x0, x1, samples=8):
    best = 0.0
    for k in range(samples + 1):
        _zc, pts, _t, _b = _fus_extent(res, x0 + (x1 - x0) * k / samples)
        best = max(best, max(abs(p[0]) for p in pts))
    return best


def inner_sections(sections, wall_mm, x_max=None):
    """
    Сеченията на кухината: всяко сечение на тялото, свито с `wall_mm` по
    двете оси (около центъра му). Носът и краят на опашката, където
    тялото е по-тънко от две стени + 2 mm, остават плътни; с `x_max`
    кухината спира и преди опашните повърхности.
    """
    out = []
    for section in sections[1:-1]:
        if x_max is not None and float(section["station_mm"]) > x_max:
            break
        pts = section["points2d"]
        ys = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        cy, cz = 0.5 * (min(ys) + max(ys)), 0.5 * (min(zs) + max(zs))
        hw, hh = 0.5 * (max(ys) - min(ys)), 0.5 * (max(zs) - min(zs))
        if hw - wall_mm < 1.0 or hh - wall_mm < 1.0:
            if out:
                break           # кухината е непрекъсната: спира при опашката
            continue
        ky, kz = (hw - wall_mm) / hw, (hh - wall_mm) / hh
        pts2d = [(cy + (p[0] - cy) * ky, cz + (p[1] - cz) * kz) for p in pts]
        o = section["origin"]
        new = dict(section)
        new["points2d"] = pts2d
        new["points3d"] = [(o[0], o[1] + a, o[2] + b) for a, b in pts2d]
        prim = section.get("primitive")
        if prim and prim.get("type") == "ellipse" and abs(cy) < 1e-6 and abs(cz) < 1e-6:
            new["primitive"] = {"type": "ellipse", "center": (0.0, 0.0),
                                "major": (hw - wall_mm, 0.0),
                                "minor_radius": hh - wall_mm}
        else:
            new.pop("primitive", None)
        out.append(new)
    return out


def _fuselage_ops(sc, res, fuselage_sections, wall_mm, x_max=None):
    """
    Кухина, преграда за мотора (преди обединяването с крилото).

    Кухината спира преди опашните повърхности: там опашният конус е
    плътен — повърхностите се сливат с плътен материал (здраво), а
    SolidCraft не отказва обединяването с тънките стени.
    """
    from . import solidcraft_export as sc_export
    fus = _fus(res)
    length = float(fus.get("length_mm") or 0.0)
    width = float(fus.get("width_mm") or 0.0)
    height = float(fus.get("height_mm") or 0.0)
    big_y, big_z = width + 40.0, height + 40.0

    inner = inner_sections(fuselage_sections, wall_mm, x_max)
    if len(inner) >= 2:
        sc.commands += sc_export.build_commands(
            [{"name": "Fuselage_Inner", "kind": "loft", "sections": inner}],
            combine=False)
        sc.combine("Fuselage", ["Fuselage_Inner"], "cut", label="Fuselage cavity")
        sc.notes.append("Тяло: кухо, стена %.2f mm, кухина x %.0f…%.0f mm"
                        % (wall_mm, inner[0]["station_mm"], inner[-1]["station_mm"]))

    prop = (res.get("layout") or {}).get("propulsion", "tractor")
    x_fw = 0.04 * length
    if prop in ("tractor", "pusher"):
        x_fw = 0.06 * length if prop == "tractor" else 0.92 * length - FIREWALL_MM
        lay = motor_mod.layout(res)
        if prop == "tractor" and lay and lay.get("x_firewall"):
            x_fw = float(lay["x_firewall"])   # моторът се побира пред нея
        sc.box("Firewall", x_fw, x_fw + FIREWALL_MM, -big_y, big_y, -20.0, big_z)
        sc.combine("Firewall", ["Fuselage_Fill"], "intersect", keep=True,
                   label="Firewall fit")
        sc.combine("Fuselage", ["Firewall"], "join", label="Firewall join")
    return x_fw


def _motor_ops(sc, res, x_fw, variant=None, prop_variant=None):
    """
    Мотор и витло.

    Теглещо витло — в носа (тялото, след сливането с каулинга):
      * отделение за камбаната (Ø + 2×луфт) от спинера до преградата;
      * отпечатвана стойка (пръстен) от гърба на мотора до преградата —
        моторът е точно зад спинера, каквото и да е разстоянието;
      * централен отвор (кабели, заден вал) и 4 отвора M3 на кръста.
    Мотор(ите) и витло(ата) са REF_* тела (не се печатат).

    variant      — {"mount": False} без стойка, {"bay": False} без нищо в
                   носа (резервни варианти, виж FALLBACKS["Motor"]);
    prop_variant — {"join": False} лопатите отделно, {"skip": True} без витло.
    """
    variant = dict(variant or {})
    prop_variant = dict(prop_variant or {})
    lay = motor_mod.layout(res)
    if not lay:
        return []
    cls, prop = lay["motor"], lay["prop"]
    tractor = lay["propulsion"] == "tractor"
    names = []
    for i, unit in enumerate(lay["units"]):
        n = i + 1
        y, z = unit["y"], unit["z"]

        def A(x):
            return (x, y, z)

        if tractor and variant.get("bay", True) and x_fw is not None:
            x_front = unit["x_can0"] - motor_mod.SPINNER_GAP_MM - 3.0
            sc.cylinder("Motor_Bay", A(x_front), A(x_fw),
                        cls["can_d"] + 2.0 * motor_mod.BAY_CLEAR_MM)
            sc.combine("Fuselage", ["Motor_Bay"], "cut", label="Motor bay")
            mount = bool(variant.get("mount", True)
                         and x_fw - unit["x_mount"] > 0.5)
            if mount:
                sc.cylinder("Motor_Mount", A(unit["x_mount"]), A(x_fw + 1.0),
                            cls["mount"][1] + 2.0 * MOTOR_MOUNT_RIM_MM)
                sc.combine("Fuselage", ["Motor_Mount"], "join",
                           label="Motor mount join")
            x0 = (unit["x_mount"] if mount else x_fw) - 1.0
            x1 = x_fw + FIREWALL_MM + 1.0
            sc.cylinder("Motor_Bore", A(x0), A(x1),
                        max(8.0, cls["mount"][0] - MOTOR_BOLT_D_MM - 2.0))
            sc.combine("Fuselage", ["Motor_Bore"], "cut", label="Motor bore")
            bolts = []
            for k, (d, ang) in enumerate(((cls["mount"][0], 45.0),
                                          (cls["mount"][0], 225.0),
                                          (cls["mount"][1], 135.0),
                                          (cls["mount"][1], 315.0))):
                a = math.radians(ang)
                dy, dz = 0.5 * d * math.cos(a), 0.5 * d * math.sin(a)
                name = "Motor_Bolt_%d" % (k + 1)
                sc.cylinder(name, (x0, y + dy, z + dz), (x1, y + dy, z + dz),
                            MOTOR_BOLT_D_MM)
                bolts.append(name)
            sc.combine("Fuselage", bolts, "cut", label="Motor bolt holes")
            if mount:
                sc.notes.append(
                    "Мотор %s: отделение Ø%.1f mm, отпечатвана стойка x "
                    "%.0f…%.0f mm, 4×M3 на кръст %g/%g mm, преграда x %.0f mm."
                    % (cls["key"], cls["can_d"] + 2.0 * motor_mod.BAY_CLEAR_MM,
                       unit["x_mount"], x_fw, cls["mount"][0], cls["mount"][1],
                       x_fw))
            else:
                sc.notes.append(
                    "Мотор %s: отделение в носа, 4×M3 на кръст %g/%g mm в "
                    "преградата (без отпечатвана стойка)."
                    % (cls["key"], cls["mount"][0], cls["mount"][1]))

        # REF: камбана + вал
        body = "REF_Motor_%d" % n
        sc.cylinder(body, A(unit["x_can0"]), A(unit["x_can1"]), cls["can_d"])
        shaft = body + "_Shaft"
        mid = 0.5 * (unit["x_can0"] + unit["x_can1"])
        sc.cylinder(shaft, A(mid), A(unit["x_shaft_end"]), cls["shaft_d"])
        sc.combine(body, [shaft], "join", label="Motor %d shaft join" % n)
        names.append(body)

        # REF: витло — главина + две лопати (сечения по стъпката)
        if prop_variant.get("skip"):
            continue
        hub = "REF_Prop_%d" % n
        h = 0.5 * prop["hub_t_mm"]
        sc.cylinder(hub, A(unit["x_prop"] - h), A(unit["x_prop"] + h),
                    prop["hub_d_mm"])
        names.append(hub)
        blades = []
        for blade in (0, 1):
            centre, e_s, e_t, e_x = motor_mod.prop_frame(unit, blade)
            sections = []
            for r, pts in motor_mod.blade_sections(prop):
                origin = tuple(centre[j] + r * e_s[j] for j in range(3))
                sections.append(((origin, e_t, e_x), pts))
            name = "%s_Blade_%d" % (hub, blade + 1)
            sc.loft_planes(name, sections)
            blades.append(name)
        if prop_variant.get("join", True):
            sc.combine(hub, blades, "join", label="Prop %d blades join" % n)
        else:
            names += blades
    sc.notes.append(
        "Мотор(и): %d× %s (камбана Ø%.1f×%.0f mm, вал Ø%.2f mm, ~%.0f g, до "
        "%.0f W) — %s. Витло %g×%g″ (Ø%.0f mm), лопати по стъпката. REF_* "
        "телата не се печатат." % (len(lay["units"]), cls["key"], cls["can_d"],
                                   cls["can_l"], cls["shaft_d"], cls["mass_g"],
                                   cls["p_max_w"], cls["reason"], prop["d_in"],
                                   prop["pitch_in"], prop["d_mm"]))
    if lay["propulsion"] == "twin":
        sc.notes.append("Два мотора: гондолите на крилото не са моделирани — "
                        "REF_Motor_* показват мястото пред предния ръб.")
    below = lay["units"][0]["z"] - prop["r_mm"]
    if below < 0:
        sc.notes.append("Витлото стърчи %.0f mm под корема — нужни са "
                        "колесник, ръчно хвърляне или сгъваемо витло."
                        % -below)
    return names


def _hatch_ops(sc, res, x_fw):
    """Капак отгоре: от преградата до предния ръб на крилото (след обединяването)."""
    g = res.get("geometry") or {}
    fus = _fus(res)
    width = float(fus.get("width_mm") or 0.0)
    height = float(fus.get("height_mm") or 0.0)
    big_y, big_z = width + 40.0, height + 40.0
    wing_le = float(g.get("wing_le_mm") or 0.0)
    c_root = float(g.get("c_root_mm") or 0.0)
    # централният профил се удължава напред (около ¼ хорда)
    x_h0 = x_fw + FIREWALL_MM + 6.0
    x_h1 = wing_le - 0.25 * c_root * (CENTER_CHORD - 1.0) - 6.0
    if x_h1 - x_h0 < 40.0:
        sc.notes.append("Капакът не е направен: няма място между преградата "
                        "и крилото (%.0f mm)." % (x_h1 - x_h0))
        return
    z_cut = HATCH_TOP_FRAC * height
    sc.box("Hatch", x_h0 + HATCH_GAP_MM, x_h1 - HATCH_GAP_MM,
           -big_y, big_y, z_cut + HATCH_GAP_MM, big_z)
    sc.combine("Hatch", ["Fuselage"], "intersect", keep=True,
               label="Hatch from fuselage")
    sc.box("Hatch_Opening", x_h0, x_h1, -big_y, big_y, z_cut, big_z)
    sc.combine("Fuselage", ["Hatch_Opening"], "cut", label="Hatch opening")
    sc.notes.append("Капак отгоре: x %.0f…%.0f mm (над %.0f mm)"
                    % (x_h0, x_h1, z_cut))


# ----------------------------------------------------------------- крило
def wing_frame(res, quality=None, thick=None):
    spec = assembly.wing_spec(res, quality, sink_mm=0.0)
    if not spec:
        return None
    g = res.get("geometry") or {}
    x0 = float(spec["origin"][0])
    c_root = float(spec["chord_root_mm"])
    y_body = _max_half_width(res, x0, x0 + c_root)
    probe = SurfaceFrame(spec)
    kc, kt = _center_factors(probe)
    if thick is not None:
        kt = float(thick)
    blend = y_body + CENTER_BLEND_CHORDS * c_root
    return SurfaceFrame(spec, blend, kc, kt, points=spec.get("points"))


def tube_layout(res, frame):
    """
    Права тръба през центъра на крилото (лонжерон, Ø и дължина като
    джойнера от изчислението). Крилото е с диедър: центърът на тръбата е
    на средата на профила в средата на половината ѝ дължина, така че
    отклонението в двата края е половината.
    """
    tube = (res.get("structure") or {}).get("joiner_tube") or {}
    od = float(tube.get("od_mm") or 0.0)
    length = float(tube.get("length_mm") or 0.0)
    if od <= 0 or length <= 0:
        return None
    half = length / 2.0
    u = printgeom.CHANNEL_CHORD_FRAC
    x = frame.point(u, frame.mid(u), 0.0)[0]
    z = frame.point(u, frame.mid(u), 0.5 * half)[2]
    margin = min(frame.half_thickness(u, y)
                 - abs(z - frame.point(u, frame.mid(u), y)[2])
                 - (od + TUBE_CLEARANCE_MM) / 2.0 for y in (0.0, half))
    return {"x": x, "z": z, "d": od, "half_len": half,
            "material": tube.get("material"), "wall_margin_mm": margin}


def _hinge_radius(frame, u_hinge, y0, y1, r_min=HINGE_R_MIN, lip=HINGE_LIP_MM):
    t_half = min(frame.half_thickness(u_hinge, y0),
                 frame.half_thickness(u_hinge, y1))
    r = t_half - lip - HINGE_GAP_MM
    return max(r_min, min(HINGE_R_MAX, r)), t_half


def _plane_at(frame, s, sign=1.0):
    """
    Равнината на сечението на станция s: начало, посока по хордата (x) и
    по дебелината. `sign` < 0 огледално по Y (лявата половина на
    симетрична повърхност).
    """
    o, a, t = frame.origin, frame.span_axis, frame.thick_axis
    origin = (o[0] + a[0] * s, o[1] + a[1] * s, o[2] + a[2] * s)
    if sign < 0:
        origin = (origin[0], -origin[1], origin[2])
        t = (t[0], -t[1], t[2])
    return origin, (1.0, 0.0, 0.0), t


def _to2d(frame, p, s):
    """Световна точка (дясната страна) → (по хордата, по дебелината) в равнината."""
    o, _x, t = _plane_at(frame, s)
    d = (p[0] - o[0], p[1] - o[1], p[2] - o[2])
    return d[0], d[0] * t[0] + d[1] * t[1] + d[2] * t[2]


def _from2d(frame, a, b, s, sign=1.0):
    o, x, t = _plane_at(frame, s, sign)
    return (o[0] + a * x[0] + b * t[0], o[1] + a * x[1] + b * t[1],
            o[2] + a * x[2] + b * t[2])


def _mirror(p, sign):
    return p if sign > 0 else (p[0], -p[1], p[2])


def _hinged_surface(sc, frame, owner, surface, tag, sign, s0, s1, chord_frac,
                    end_gap, horn_s, horn_side=-1.0, pin_out=None,
                    pin_d=PIN_D_MM, r_min=HINGE_R_MIN, lip=HINGE_LIP_MM,
                    level=0):
    """
    Кормило с шарнирна панта върху носеща повърхност `owner` — общо за
    елерон, кормило за височина, кормило за посока и руддерватор.

      * кормилото = (скосена призма зад оста ∪ цилиндър R) ∩ повърхността;
      * в повърхността: процеп + вдлъбнат жлеб с радиус R + процеп;
      * уши на повърхността (пълнят жлеба) с изрези в кормилото;
      * ос през ушите и кормилото, излиза на `pin_out` (по подразбиране
        при върха);
      * кормилен рог на станция `horn_s`, от страната `horn_side`
        (−1 = отрицателната посока на дебелината: долу / вляво).

    Станциите s са по оста на размаха на `frame` (дясната половина);
    `sign` < 0 огледално по Y. Връща {"hole", "radius", "knuckles"}.

    `level` — резервен вариант, ако SolidCraft откаже някоя операция
    (виж CONTROL_FALLBACKS): 1 — кормилото се отдръпва от двата края;
    2 — без уши и ос (панта с лента/CA-панти); 3 — без кормило (None).
    """
    if level >= 3:
        sc.notes.append("%s не е направено (SolidCraft отказа пантата) — "
                        "повърхността е цяла." % surface)
        return None
    if level >= 1:
        s0, s1 = s0 + CONTROL_RETREAT_MM, s1 - CONTROL_RETREAT_MM
        horn_s = max(horn_s, s0 + 10.0)
        if s1 - s0 < 20.0:
            return None
    u_h = 1.0 - chord_frac
    lbl = " ".join(x for x in (owner, tag) if x)
    radius, t_half = _hinge_radius(frame, u_h, s0, s1, r_min, lip)
    if t_half - radius - HINGE_GAP_MM < 0.6:
        sc.notes.append("Пантата на %s е тънка: %.1f mm стена над жлеба."
                        % (surface, t_half - radius - HINGE_GAP_MM))
    a0 = frame.point(u_h, frame.mid(u_h), s0)
    a1 = frame.point(u_h, frame.mid(u_h), s1)

    def axis_at(s):
        k = (s - s0) / max(1e-9, (s1 - s0))
        return tuple(a0[i] + (a1[i] - a0[i]) * k for i in range(3))

    def W(p):
        return _mirror(p, sign)

    bevel = math.tan(math.radians(HINGE_BEVEL_DEG))

    def prism(name, sa, sb, offset=0.0, bevelled=False):
        """Призма зад оста; `bevelled` — V-скос над и под носа."""
        sections = []
        for i in range(CUTTER_STATIONS + 1):
            s = sa + (sb - sa) * i / CUTTER_STATIONS
            ax, az = _to2d(frame, axis_at(s), s)
            te, _ = _to2d(frame, frame.point(1.0, frame.mid(1.0), s), s)
            dz = 0.5 * frame.chord(s) + 20.0
            x0 = ax + offset
            x1 = te + 15.0
            if bevelled:
                hb = max(radius + 0.5, frame.half_thickness(u_h, s) + 1.0)
                xb = min(x0 + (hb - radius) * bevel, x1 - 1.0)
                pts = [(x0, az - radius), (xb, az - hb), (xb, az - dz),
                       (x1, az - dz), (x1, az + dz), (xb, az + dz),
                       (xb, az + hb), (x0, az + radius)]
            else:
                pts = [(x0, az - dz), (x1, az - dz), (x1, az + dz), (x0, az + dz)]
            sections.append((_plane_at(frame, s, sign), pts))
        sc.loft_planes(name, sections)

    prism(surface, s0 + end_gap, s1 - end_gap, offset=HINGE_GAP_MM, bevelled=True)
    sc.cylinder("%s_Nose" % surface, W(axis_at(s0 + end_gap)),
                W(axis_at(s1 - end_gap)), 2.0 * radius)
    sc.combine(surface, ["%s_Nose" % surface], "join", label="%s nose" % surface)
    sc.combine(surface, [owner], "intersect", keep=True,
               label="%s from %s" % (surface, owner.lower() if owner == "Wing"
                                     else owner))
    prism("%s_Slot" % surface, s0, s1)
    sc.combine(owner, ["%s_Slot" % surface], "cut", label="%s slot" % lbl)
    # жлебът излиза 0.5 mm извън процепа: съвпадащи чела (жлеб/процеп)
    # SolidCraft понякога отказва, особено при тесен „език“ между двете
    # половини (T-опашка)
    sc.cylinder("%s_Cove" % surface, W(axis_at(s0 - COVE_OVERRUN_MM)),
                W(axis_at(s1 + COVE_OVERRUN_MM)), 2.0 * (radius + HINGE_GAP_MM))
    sc.combine(owner, ["%s_Cove" % surface], "cut", label="%s hinge cove" % lbl)

    span = s1 - s0
    count = max(2, int(round(span / KNUCKLE_PITCH_MM))) if level < 2 else 0
    if level >= 2:
        sc.notes.append("%s: панта без уши и ос — закрепи с лента или "
                        "CA-панти (SolidCraft отказа ушите)." % surface)
    for k in range(count):
        sc_ = s0 + span * (k + 0.5) / count
        kn = "%s_%s_Knuckle%d" % (owner, tag or "C", k + 1)
        sc.cylinder(kn, W(axis_at(sc_ - KNUCKLE_LEN_MM / 2)),
                    W(axis_at(sc_ + KNUCKLE_LEN_MM / 2)),
                    2.0 * (radius + HINGE_GAP_MM + KNUCKLE_OVERLAP_MM))
        sc.combine(owner, [kn], "join", label="%s knuckle %d" % (lbl, k + 1))
        notch = "%s_Notch%d" % (surface, k + 1)
        sc.cylinder(notch, W(axis_at(sc_ - KNUCKLE_LEN_MM / 2 - HINGE_GAP_MM)),
                    W(axis_at(sc_ + KNUCKLE_LEN_MM / 2 + HINGE_GAP_MM)),
                    2.0 * (radius + 2.0 * HINGE_GAP_MM))
        sc.combine(surface, [notch], "cut", label="%s notch %d" % (surface, k + 1))

    if count:
        out = frame.semi + 5.0 if pin_out is None else pin_out
        sc.cylinder("%s_PinHole" % surface,
                    W(axis_at(s0 - (1.0 if level == 0 else 0.0))),
                    W(axis_at(out)), pin_d)
        sc.combine(surface, ["%s_PinHole" % surface], "cut", keep=True,
                   label="%s pin hole" % surface)
        sc.combine(owner, ["%s_PinHole" % surface], "cut",
                   label="%s pin hole" % lbl)

    # кормилен рог: плоча в равнината на хордата, под/встрани от оста
    ax, _az = _to2d(frame, axis_at(horn_s), horn_s)
    hx0 = ax + radius + 0.5
    hx1 = hx0 + HORN_LEN_MM
    _qa, qb = _to2d(frame, frame.on_surface(min(0.999, u_h + 0.04), horn_s,
                                            horn_side), horn_s)
    b_in = qb - horn_side * 1.5
    b_out = qb + horn_side * HORN_DROP_MM
    lo, hi = min(b_in, b_out), max(b_in, b_out)
    horn = "%s_Horn" % surface
    poly = [(hx0, lo), (hx1, lo), (hx1, hi), (hx0, hi)]
    sc.loft_planes(horn, [(_plane_at(frame, horn_s - HORN_T_MM / 2, sign), poly),
                          (_plane_at(frame, horn_s + HORN_T_MM / 2, sign), poly)])
    sc.combine(surface, [horn], "join", label="%s horn" % surface)
    hb_ = qb + horn_side * (HORN_DROP_MM - 3.0)
    hole = _from2d(frame, hx0 + 3.0, hb_, horn_s, sign)
    sc.cylinder("%s_HornHole" % surface,
                _from2d(frame, hx0 + 3.0, hb_, horn_s - 3.0, sign),
                _from2d(frame, hx0 + 3.0, hb_, horn_s + 3.0, sign),
                HORN_HOLE_D_MM)
    sc.combine(surface, ["%s_HornHole" % surface], "cut",
               label="%s horn hole" % surface)
    return {"hole": hole, "radius": radius, "knuckles": count,
            "axis_at": axis_at}


def _aileron_ops(sc, res, frame, sign, servo, ctrl_levels=None):
    """
    Елерон с шарнирна панта и серво в крилото — върху тялото `Wing`,
    ПРЕДИ обединяването с тялото (по-малки boolean-и).
    """
    side = "R" if sign > 0 else "L"
    wing = "Wing"
    ail = (res.get("geometry") or {}).get("ailerons") or {}
    names = []
    if not ail.get("enabled"):
        return names, None

    def P(p):
        return (p[0], sign * p[1], p[2])

    cf = float(ail["chord_frac"])
    y0 = float(ail["y_start_mm"])
    y1 = float(ail["y_end_mm"])
    eg = float(ail.get("end_gap_mm") or 1.5)
    aileron = "Aileron_%s" % side
    s_len, s_wid, s_hgt = servo["size_mm"]
    bay_s = s_hgt + 2 * SERVO_CLEAR_MM
    yc_bay = y0 + 3.0 + 0.5 * bay_s          # рогът е срещу сервото
    hinge = _hinged_surface(sc, frame, wing, aileron, side, sign, y0, y1, cf,
                            eg, yc_bay, horn_side=-1.0,
                            level=int((ctrl_levels or {}).get(aileron, 0)))
    if hinge is None:
        return names, None
    radius, count = hinge["radius"], hinge["knuckles"]
    hole = hinge["hole"]

    # --- гнездо за серво (отдолу, преди елерона) + капаче
    bay_c = float(servo.get("tabs_mm") or s_len + 10.0) + 2 * SERVO_CLEAR_MM
    bay_d = s_wid + 2 * SERVO_CLEAR_MM
    y_bay0 = y0 + 3.0
    y_bay1 = y_bay0 + bay_s
    yc_bay = 0.5 * (y_bay0 + y_bay1)
    centre = frame.point(0.5, frame.mid(0.5), yc_bay)
    x0 = centre[0] - bay_c / 2.0
    x1 = centre[0] + bay_c / 2.0
    # долната повърхност е наклонена: капачето обхваща най-високата ѝ точка
    lows = []
    for y in (y_bay0, yc_bay, y_bay1):
        for k in range(41):
            q = frame.on_surface(0.25 + 0.5 * k / 40.0, y, -1)
            if x0 <= q[0] <= x1:
                lows.append(q[2])
    low_c = frame.on_surface(0.5, yc_bay, -1)[2]
    low_max = max(lows) if lows else low_c
    low_min = min(lows) if lows else low_c
    thick = 2.0 * frame.half_thickness(0.5, yc_bay)
    if thick < bay_d + 2.0 * WALL_MM:
        sc.notes.append("Гнездото за серво (%s) е по-дълбоко от крилото: "
                        "%.1f mm при %.1f mm дебелина." % (side, bay_d, thick))
    cover = "Servo_Cover_%s" % side
    sc.box(cover, x0, x1, sign * y_bay0, sign * y_bay1, low_min - 15.0,
           low_max + SERVO_COVER_MM)
    sc.combine(cover, [wing], "intersect", keep=True, label="%s from wing" % cover)
    sc.box("%s_ArmSlot" % cover, x1 - 16.0, x1 - 2.0,
           sign * (yc_bay - 2.5), sign * (yc_bay + 2.5),
           low_min - 15.0, low_max + SERVO_COVER_MM + 1.0)
    sc.combine(cover, ["%s_ArmSlot" % cover], "cut", label="%s arm slot" % cover)
    sc.box("Wing_%s_ServoBay" % side, x0, x1, sign * y_bay0, sign * y_bay1,
           low_min - 15.0, low_max + bay_d)
    sc.combine(wing, ["Wing_%s_ServoBay" % side], "cut",
               label="Wing %s servo bay" % side)
    names.append(cover)
    sc.box("REF_Servo_Aileron_%s" % side, centre[0] - s_len / 2.0,
           centre[0] + s_len / 2.0,
           sign * (yc_bay - s_hgt / 2.0), sign * (yc_bay + s_hgt / 2.0),
           low_max + SERVO_COVER_MM + 0.2, low_max + SERVO_COVER_MM + 0.2 + s_wid)
    names.append("REF_Servo_Aileron_%s" % side)

    # --- тяга: от рамото на сервото до рога на елерона
    arm = (x1 - 6.0, yc_bay, low_c - 10.0)
    sc.cylinder("Pushrod_%s" % side, P(arm), hole, PUSHROD_D_MM)
    names += [aileron, "Pushrod_%s" % side]

    sc.notes.append(
        "%s: панта R %.1f mm (жлеб %.1f), %d уши × %.0f mm, ос Ø%.2f mm; "
        "гнездо за серво %.0f×%.0f×%.0f mm на y %.0f…%.0f mm"
        % (aileron, radius, radius + HINGE_GAP_MM, count, KNUCKLE_LEN_MM,
           PIN_D_MM, bay_c, bay_s, bay_d, y_bay0, y_bay1))
    cable_from = y_bay0 + 1.0
    return names, cable_from


def _through_center_ops(sc, res, frame, tube, cable_from, target="Fuselage",
                        exit_variant=None):
    """
    Всичко, което минава през центъра — СЛЕД обединяването с тялото
    (иначе стените на тялото пак биха запълнили каналите):
    лентите на спара от връх до връх, тръбата, каналите за кабелите.
    """
    st = res.get("structure") or {}
    view = printgeom.spar_section(res) or {}
    carbon = view.get("carbon") or {}
    if carbon.get("needed") and carbon.get("width_mm"):
        cw = float(carbon["width_mm"]) + SPAR_SLOT_CLEAR_MM
        ct = (float(carbon.get("thickness_mm") or 0.5)
              * int(carbon.get("count") or 1) + SPAR_SLOT_CLEAR_MM)
        wall = float(st.get("wall_mm") or 0.45)
        u_c = printgeom.SPAR_CAP_CHORD_FRAC
        end = SPAR_END_FRAC * frame.semi
        ys = sorted({s for s in frame.stations() if abs(s) <= end} | {-end, end})
        for tag, srf in (("Top", 1), ("Bot", -1)):
            sections = []
            for y in ys:
                p = frame.on_surface(u_c, y, srf, inset=wall)
                z_in = p[2] - srf * ct
                lo, hi = min(p[2], z_in), max(p[2], z_in)
                sections.append((y, [(p[0] - cw / 2, lo), (p[0] + cw / 2, lo),
                                     (p[0] + cw / 2, hi), (p[0] - cw / 2, hi)]))
            name = "Spar_Slot_%s" % tag
            sc.loft_polygons(name, sections)
            sc.combine(target, [name], "cut", label="Spar slot %s" % tag)
        sc.notes.append("Лентите на спара (%s %.1f×%.1f mm) минават "
                        "непрекъснато от връх до връх през центъра."
                        % (carbon.get("material") or "", float(carbon["width_mm"]),
                           float(carbon.get("thickness_mm") or 0.5)))

    if tube:
        sc.cylinder("Tube_Bore", (tube["x"], -tube["half_len"] - 1.0, tube["z"]),
                    (tube["x"], tube["half_len"] + 1.0, tube["z"]),
                    tube["d"] + TUBE_CLEARANCE_MM)
        sc.combine(target, ["Tube_Bore"], "cut", label="Tube channel")
        sc.cylinder("Spar_Tube", (tube["x"], -tube["half_len"], tube["z"]),
                    (tube["x"], tube["half_len"], tube["z"]), tube["d"])
        sc.notes.append("Тръба Ø%.0f × %.0f mm през центъра на крилото "
                        "(стена до повърхността %.1f mm)."
                        % (tube["d"], 2 * tube["half_len"], tube["wall_margin_mm"]))

    if cable_from:
        # разклонител в оста: каналите от двете серва свършват в кутия, а от
        # нея отвор води в кухината. Каналите не се срещат челно (съвпадащи
        # и допирателни повърхнини SolidCraft отказва).
        u = 0.5
        p_c = frame.point(u, frame.mid(u), 0.0)
        box_y = JUNCTION_MM[1] / 2.0
        sc.box("Cable_Junction", p_c[0] - JUNCTION_MM[0] / 2.0,
               p_c[0] + JUNCTION_MM[0] / 2.0, -box_y, box_y,
               p_c[2] - 1.0 - JUNCTION_MM[2] / 2.0,
               p_c[2] - 1.0 + JUNCTION_MM[2] / 2.0)
        sc.combine(target, ["Cable_Junction"], "cut", label="Cable junction")
        for sign in (1.0, -1.0):
            tag = "R" if sign > 0 else "L"
            p_in = frame.point(u, frame.mid(u), cable_from)
            p_end = frame.point(u, frame.mid(u), box_y - 2.0)
            sc.cylinder("Cable_%s" % tag,
                        (p_in[0], sign * p_in[1], p_in[2] - 1.0),
                        (p_end[0], sign * p_end[1], p_c[2] - 1.0), CABLE_D_MM)
            sc.combine(target, ["Cable_%s" % tag], "cut",
                       label="Cable channel %s" % tag)
        # изход на кабелите в кухината на тялото (в оста)
        zc, _pts, z_top, z_bot = _fus_extent(res, p_c[0])
        low_wing = p_c[2] < zc - 0.25 * (z_top - z_bot)
        z_end = (z_top - WALL_MM - 6.0) if low_wing else (z_bot + WALL_MM + 6.0)
        z_start = p_c[2] - 1.0 + (1.0 if low_wing else -1.0) * (JUNCTION_MM[2] / 2.0 - 1.0)
        ev = dict(exit_variant or {})
        if ev.get("skip"):
            sc.notes.append("Отворът от разклонителя към кухината не е направен "
                            "(SolidCraft го отказа) — пробий го на ръка.")
        else:
            x_e = p_c[0] + float(ev.get("dx") or 0.0)
            sc.cylinder("Cable_Exit", (x_e, 0.0, z_start), (x_e, 0.0, z_end),
                        float(ev.get("d") or CABLE_EXIT_D_MM))
            sc.combine(target, ["Cable_Exit"], "cut", label="Cable exit")
    return ["Spar_Tube"] if tube else []


# ---------------------------------------------------------------- опашка
TAIL_CAVITY_MARGIN_MM = 10.0  # кухината спира толкова преди опашката


def tail_frames(res, quality=None, stab_lift_mm=0.0, thick=None):
    """
    [(име, SurfaceFrame)] — стабилизатор/кил/V-панели с централен профил.

    `stab_lift_mm` вдига стабилизатора (не при T-опашка): на линията на
    най-голямата ширина стената е отвесна и SolidCraft понякога отказва
    обединяването („Bad CurveCusp“) — няколко mm го решават (виж export_job).
    """
    out = []
    fus = _fus(res)
    height = float(fus.get("height_mm") or 0.0)
    for name, _file, spec in assembly.tail_specs(res, quality, exact=True):
        x0 = float(spec["origin"][0])
        chord = float(spec["chord_root_mm"])
        z0 = float(spec["origin"][2])
        if name == "Stabilizer" and stab_lift_mm and z0 <= height:
            spec = dict(spec)
            o = spec["origin"]
            spec["origin"] = (o[0], o[1], o[2] + float(stab_lift_mm))
            z0 = spec["origin"][2]
        probe = SurfaceFrame(spec)
        kc, kt = _center_factors(probe)
        if thick and name in thick:
            kt = float(thick[name])
        if name == "Fin":
            _zc, _pts, z_top, _zb = _fus_extent(res, x0 + 0.5 * chord)
            blend = max(0.0, z_top - z0) + CENTER_BLEND_CHORDS * chord
        elif name == "Stabilizer" and z0 > height:
            blend = CENTER_BLEND_CHORDS * chord          # T-опашка: на кила
        else:
            axis = spec.get("span_axis") or (0.0, 1.0, 0.0)
            blend = (assembly.skin_offset(fus, x0 + 0.5 * chord, axis)
                     + CENTER_BLEND_CHORDS * chord)
        out.append((name, SurfaceFrame(spec, blend, kc, kt)))
    return out


# ------------------------------------------------------------------ серва
PUSHROD_CHANNEL_D_MM = 3.2    # канал за тягата (тел 1.2 mm в шлаух Ø3)


def _tail_servo_refs(sc, res, servo, tags, wing_te_x):
    """
    Сервата за опашката в кухината, точно зад крилото — едно до друго
    (иначе едно зад друго). Връща {таг: (x0, x1, y0, y1, z0, z1)}.
    """
    if not tags:
        return {}
    L, W, H = servo["size_mm"]
    tabs = float(servo.get("tabs_mm") or L)
    fus = _fus(res)
    length = float(fus.get("length_mm") or 0.0)
    x = wing_te_x + 8.0
    boxes = {}
    while x + tabs < 0.9 * length:
        _zc, _pts, z_top, z_bot = _fus_extent(res, x + 0.5 * tabs)
        z_mid = 0.5 * (z_top + z_bot)
        free_w = min(half_width_at(res, x, z_mid),
                     half_width_at(res, x + tabs, z_mid)) - WALL_MM - 1.0
        free_h = (z_top - z_bot) - 2 * WALL_MM - 2.0
        if free_h >= H and free_w >= (W + 1.5 if len(tags) > 1 else W / 2.0):
            slots = ([(-W / 2.0, tags[0])] if len(tags) == 1
                     else [(-W - 1.0, tags[0]), (1.0, tags[1])])
            for yy, tag in slots:
                boxes[tag] = (x, x + L, yy, yy + W, z_mid - H / 2, z_mid + H / 2)
            break
        x += 5.0
    if not boxes:
        sc.notes.append("Сервата за опашката не се побират в тялото зад крилото "
                        "(%s, %.0f×%.0f×%.0f mm)." % (servo["label"], L, W, H))
    for tag, b in boxes.items():
        sc.box("REF_Servo_%s" % tag, *b)
    return boxes


def _servo_arm(box, toward):
    """Краят на рамото на сервото: при задния му край, към страната на тягата."""
    x0, x1, y0, y1, z0, z1 = box
    yc = 0.5 * (y0 + y1)
    zc = 0.5 * (z0 + z1)
    dy = 1.0 if toward[1] >= yc else -1.0
    dz = 1.0 if toward[2] >= zc else -1.0
    return (x1 - 5.0, yc + dy * 0.5 * (y1 - y0), zc + dz * 0.3 * (z1 - z0))


def _tail_control_ops(sc, res, tails, ctrl_levels=None):
    """
    Кормилата на опашката (ПРЕДИ сливането с тялото).

    Класическа/T-опашка: кормило за височина на всяка половина на
    стабилизатора (рог отдолу, при тялото) и кормило за посока на кила (рог
    вляво, в долния край). V-опашка: руддерватор на всеки панел.
    Връща [(таг на сервото, тяло на кормилото, точка на рога)].
    """
    g = res.get("geometry") or {}
    tc = g.get("tail_controls") or {}
    frames = dict(tails)
    out = []

    el = tc.get("elevator") or {}
    ru = tc.get("rudder") or {}
    clear = float(el.get("root_clear_mm") or 2.0)
    margin = float(el.get("tip_margin_frac") or 0.03)
    eg = float(el.get("end_gap_mm") or 1.5)

    if el.get("enabled") and el.get("kind") == "ruddervator":
        fus = _fus(res)
        for name, tag in (("Stabilizer_V_R", "R"), ("Stabilizer_V_L", "L")):
            f = frames.get(name)
            if f is None:
                continue
            cf = float(el["chord_frac"])
            x_h = f.point(1.0 - cf, f.mid(1.0 - cf), 0.0)[0]
            s0 = assembly.skin_offset(fus, x_h, f.span_axis) + clear
            s1 = f.semi * (1.0 - margin)
            if s1 - s0 < 30.0:
                continue
            surf = "Ruddervator_%s" % tag
            h = _hinged_surface(sc, f, name, surf, "", 1.0, s0, s1, cf, eg,
                                s0 + 10.0, horn_side=-1.0,
                                level=int((ctrl_levels or {}).get(surf, 0)),
                                pin_d=TAIL_PIN_D_MM, r_min=TAIL_R_MIN, lip=TAIL_LIP_MM)
            if h is None:
                continue
            out.append(("Ruddervator_%s" % tag, surf, h["hole"]))
            sc.notes.append("%s: хорда %.0f %%, панта R %.1f mm, %d уши."
                            % (surf, 100 * cf, h["radius"], h["knuckles"]))
        return out

    stab = frames.get("Stabilizer")
    fin = frames.get("Fin")
    t_tail = (stab is not None and fin is not None
              and stab.origin[2] > fin.origin[2] + 0.5 * fin.semi)
    if el.get("enabled") and stab is not None:
        cf = float(el["chord_frac"])
        x_h = stab.point(1.0 - cf, stab.mid(1.0 - cf), 0.0)[0]
        if t_tail:
            # T-опашка: половините започват до върха на кила
            s0 = 0.5 * fin.thickness_ratio() * fin.chord(fin.semi) + clear
        else:
            s0 = half_width_at(res, x_h, stab.origin[2]) + clear
        s1 = stab.semi * (1.0 - margin)
        if s1 - s0 >= 30.0:
            for sign, tag in ((1.0, "R"), (-1.0, "L")):
                surf = "Elevator_%s" % tag
                h = _hinged_surface(sc, stab, "Stabilizer", surf, tag, sign, s0,
                                    s1, cf, eg, s0 + 10.0, horn_side=-1.0,
                                    level=int((ctrl_levels or {}).get(surf, 0)),
                                    pin_d=TAIL_PIN_D_MM, r_min=TAIL_R_MIN, lip=TAIL_LIP_MM)
                if h is not None:
                    out.append(("Elevator", surf, h["hole"]))
                    last = h
            if any(t == "Elevator" for t, _s, _h in out):
                sc.notes.append(
                    "Кормило за височина: две половини (хорда %.0f %%, y "
                    "%.0f…%.0f mm), панта R %.1f mm, %d уши на половина; едно "
                    "серво с две тяги." % (100 * cf, s0, s1, last["radius"],
                                          last["knuckles"]))

    if ru.get("enabled") and fin is not None:
        cf = float(ru["chord_frac"])
        rclear = float(ru.get("root_clear_mm") or 2.0)
        rmargin = float(ru.get("tip_margin_frac") or 0.03)
        x_h = fin.point(1.0 - cf, fin.mid(1.0 - cf), 0.0)[0]
        z0 = fin.origin[2]
        _zc, _pts, z_top, _zb = _fus_extent(res, x_h)
        s0 = z_top - z0 + rclear
        s1 = fin.semi * (1.0 - rmargin)
        pin_out = None
        if stab is not None:
            us = [0.3 + 0.7 * k / 20.0 for k in range(21)]
            if t_tail:
                stab_bot = min(stab.on_surface(u, 0.0, -1)[2] for u in us)
                stab_top = max(stab.on_surface(u, 0.0, 1)[2] for u in us)
                s1 = min(s1, stab_bot - z0 - rclear)
                pin_out = stab_top - z0 + 3.0      # оста се вкарва отгоре
            else:
                stab_top = max(stab.on_surface(u, 0.0, 1)[2] for u in us)
                s0 = max(s0, stab_top - z0 + rclear)
        if s1 - s0 >= 30.0:
            h = _hinged_surface(sc, fin, "Fin", "Rudder", "", 1.0, s0, s1, cf,
                                float(ru.get("end_gap_mm") or 1.5), s0 + 10.0,
                                horn_side=-1.0, pin_out=pin_out,
                                level=int((ctrl_levels or {}).get("Rudder", 0)),
                                pin_d=TAIL_PIN_D_MM, r_min=TAIL_R_MIN, lip=TAIL_LIP_MM)
        if s1 - s0 >= 30.0 and h is not None:
            out.append(("Rudder", "Rudder", h["hole"]))
            sc.notes.append(
                "Кормило за посока: хорда %.0f %%, височина %.0f mm, панта R "
                "%.1f mm, %d уши; рог вляво в долния край."
                % (100 * cf, s1 - s0, h["radius"], h["knuckles"]))
    return out


def _pushrod_ops(sc, controls_list, boxes, target="Fuselage"):
    """
    Тягите от сервата за опашката до рогата: тяло „Pushrod_<кормило>“ и
    канал Ø3.2 през тялото (СЛЕД сливането), спира 15 mm преди рога.
    """
    names = []
    for tag, surface, hole in controls_list:
        box = boxes.get(tag)
        if box is None:
            continue
        arm = _servo_arm(box, hole)
        d = [hole[i] - arm[i] for i in range(3)]
        length = math.sqrt(sum(c * c for c in d)) or 1.0
        stop = max(0.0, length - 15.0) / length
        end = tuple(arm[i] + d[i] * stop for i in range(3))
        ch = "Channel_%s" % surface
        sc.cylinder(ch, arm, end, PUSHROD_CHANNEL_D_MM)
        sc.combine(target, [ch], "cut", label="Pushrod channel %s" % surface)
        rod = "Pushrod_%s" % surface
        sc.cylinder(rod, arm, hole, PUSHROD_D_MM)
        names.append(rod)
    return names


# ------------------------------------------------------------------ вход
def build_script(res, quality=None, detail=None, out_step=None,
                 wall_mm=WALL_MM, variants=None):
    """
    Целият скрипт за детайлния модел.

    `variants` — резервни варианти, когато SolidCraft откаже да слее
    някоя повърхност с тялото (виж `next_variants`):
      stab_lift_mm — вдигане на стабилизатора;
      thick        — {тяло: дебелина на централния профил} (1.0 = без
                     удебеляване, само по-дълга хорда);
      separate     — тела, които остават отделни (не се сливат).

    връща {"commands", "bodies": [имена на крайните тела], "notes", "servos"}
    """
    variants = dict(variants or {})
    stab_lift_mm = float(variants.get("stab_lift_mm") or 0.0)
    thick = dict(variants.get("thick") or {})
    separate = set(variants.get("separate") or ())
    from . import solidcraft_export as sc_export
    if not res or not res.get("ok"):
        return {"commands": [], "bodies": [], "notes": ["няма изчислен дизайн"]}
    detail = dict(detail or {})
    detail["fuselage_stations"] = max(int(detail.get("fuselage_stations") or 0),
                                      FUSELAGE_STATIONS)
    base = assembly.loft_bodies(res, quality, detail, joins=False, split=True)
    fus_body = next((b for b in base if b["name"] == "Fuselage"), None)
    frame = wing_frame(res, quality, thick.get("Wing"))
    if not fus_body or frame is None:
        return {"commands": [], "bodies": [], "notes": ["няма геометрия"]}
    revolves = [b for b in base if b["kind"] == "revolve"]

    lifting = [{"name": "Wing", "kind": "loft", "sections": frame.sections()}]
    tails = tail_frames(res, quality, stab_lift_mm, thick)
    for name, tf in tails:
        lifting.append({"name": name, "kind": "loft", "sections": tf.sections()})

    script = Script()
    script.commands = sc_export.build_commands([fus_body] + revolves + lifting,
                                               combine=False)
    script.notes.append(
        "Крило: едно тяло с централен профил в оста — хорда ×%.2f, дебелина "
        "×%.2f, плавен преход до %.0f mm от оста; слято с тялото."
        % (frame.k_chord, frame.k_thick, frame.blend))
    for name, tf in tails:
        script.notes.append("%s: централен/коренен профил хорда ×%.2f, дебелина "
                            "×%.2f, преход %.0f mm." % (name, tf.k_chord,
                                                        tf.k_thick, tf.blend))

    # пълно копие на тялото: за преградата
    script.add("solid.move", bodies=["Fuselage"], translate=[0, 0, 0],
               copy=True, body_name="Fuselage_Fill", name="Fuselage fill copy")
    tail_x = [tf.origin[0] for _n, tf in tails]
    x_fw = _fuselage_ops(script, res, fus_body["sections"], wall_mm,
                         (min(tail_x) - TAIL_CAVITY_MARGIN_MM) if tail_x else None)
    if stab_lift_mm:
        script.notes.append("Стабилизаторът е вдигнат с %.0f mm (SolidCraft "
                            "отказа обединяването на линията на най-голямата "
                            "ширина)." % stab_lift_mm)

    # серва: избрани по шарнирния момент
    sizing = controls.servo_sizing(res)
    by_key = {s["key"]: s for s in sizing["surfaces"]}
    wing_srv = by_key.get("aileron") or by_key.get("elevon")
    servo_w = (wing_srv or {}).get("servo") or dict(controls.SERVO_CLASSES[0])
    for s in sizing["surfaces"]:
        script.notes.append(
            "Серво %s: нужни %.2f kg·cm при %.0f m/s → %s (%.1f kg·cm, запас ×%.1f)"
            % (s["label"].lower(), s["torque_kgcm"], sizing["v_design_ms"],
               s["servo"]["label"], s["servo"]["torque_kgcm"], s["margin"] or 0))

    extra = []
    cable_from = None
    for sign in (1.0, -1.0):
        names, cable_from = _aileron_ops(script, res, frame, sign, servo_w,
                                         variants.get("ctrl"))
        extra += names
    # кормилата на опашката (преди сливането — по-малки boolean-и)
    tail_ctrl = _tail_control_ops(script, res, tails, variants.get("ctrl"))
    extra += sorted({surface for _t, surface, _h in tail_ctrl})

    # обединяване: тяло + каулинг + крило + опашка → едно тяло; всяко
    # поотделно, за да се знае коя повърхност е отказана (виж next_variants)
    tools = [b["name"] for b in revolves if b["name"] == "Cowl"]
    tools += ["Wing"] + [name for name, _tf in tails]
    joined = [t for t in tools if t not in separate]
    for tool in joined:
        script.combine("Fuselage", [tool], "join", label="Join %s" % tool)
    for tool, k in sorted(thick.items()):
        script.notes.append("%s: централният профил е без удебеляване (×%.2f) "
                            "— SolidCraft отказа сливането." % (tool, k))
    if separate:
        script.notes.append("Отделни тела (SolidCraft отказа сливането): %s."
                            % ", ".join(sorted(separate)))
    join = "Wing" in joined

    tube = tube_layout(res, frame)
    if tube and tube["wall_margin_mm"] < printgeom.CHANNEL_MIN_WALL_MM:
        script.notes.append("Тръбата е близо до повърхността (%.1f mm стена)."
                            % tube["wall_margin_mm"])
    extra += _through_center_ops(script, res, frame, tube, cable_from,
                                 target="Fuselage" if join else "Wing",
                                 exit_variant=variants.get("cable_exit"))
    _hatch_ops(script, res, x_fw)
    script.add("solid.remove", bodies=["Fuselage_Fill"], name="Remove fill copy")
    # мотор и витло (отделението в носа е след сливането с каулинга)
    extra += _motor_ops(script, res,
                        x_fw if ("Cowl" in joined or not revolves) else None,
                        variants.get("motor"), variants.get("prop"))

    # сервата за опашката — единственото в тялото — и тягите към рогата
    tail_srv = [by_key[k] for k in ("elevator", "rudder", "ruddervator")
                if k in by_key]
    if tail_srv:
        big = max((s["servo"] for s in tail_srv),
                  key=lambda srv: srv["torque_kgcm"])
        wing_te = frame.point(1.0, frame.mid(1.0), 0.0)[0]
        if "ruddervator" in by_key:
            tags = ["Ruddervator_L", "Ruddervator_R"]
        else:
            tags = [t for t, k in (("Elevator", "elevator"), ("Rudder", "rudder"))
                    if k in by_key]
        boxes = _tail_servo_refs(script, res, big, tags, wing_te)
        extra += ["REF_Servo_%s" % t for t in boxes]
        extra += _pushrod_ops(script, tail_ctrl, boxes)

    if out_step:
        script.add("file.export", path=str(out_step).replace("\\", "/"),
                   format="step")
    final = ["Fuselage"] + [b["name"] for b in revolves if b["name"] != "Cowl"]
    final += [t for t in tools if t in separate]
    final += ["Hatch"] + extra
    return {"commands": script.commands, "bodies": final, "notes": script.notes,
            "servos": sizing}


def failed_feature(errors, commands):
    """
    Коя операция SolidCraft е отказал: "Join <тяло>" (сливане с тялото)
    или "Cable exit" — тези имат резервни варианти (FALLBACKS); иначе None.
    """
    for index, _command, _text in errors or []:
        try:
            i = int(index) - 1          # индексите в stderr са от 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(commands):
            name = str((commands[i].get("params") or {}).get("name") or "")
            if name.startswith("Join ") or name == "Cable exit":
                return name
            if name.startswith("Motor ") or name.startswith("Prop "):
                return name.split(" ", 1)[0]
            control = control_of_label(name)
            if control:
                return "Control " + control
    return None


# собственик (етикет) → кормило: етикетите на _hinged_surface са
# „<повърхност> <страна> …“ или „<кормило> …“
_OWNER_TO_CONTROL = (("Wing R ", "Aileron_R"), ("Wing L ", "Aileron_L"),
                     ("Stabilizer_V_R ", "Ruddervator_R"),
                     ("Stabilizer_V_L ", "Ruddervator_L"),
                     ("Stabilizer R ", "Elevator_R"), ("Stabilizer L ", "Elevator_L"),
                     ("Fin ", "Rudder"))
_CONTROLS = ("Aileron_R", "Aileron_L", "Elevator_R", "Elevator_L", "Rudder",
             "Ruddervator_R", "Ruddervator_L")


def _pair(name):
    """Името и огледалната му двойка (…_R ↔ …_L), за симетрични варианти."""
    if name.endswith("_R"):
        return [name, name[:-2] + "_L"]
    if name.endswith("_L"):
        return [name[:-2] + "_R", name]
    return [name]


def control_of_label(name):
    """Кормилото, на което принадлежи операция с етикет `name` (или None)."""
    for control in _CONTROLS:
        if name == control or name.startswith(control + " ") \
                or name.startswith(control + "_"):
            return control
    for prefix, control in _OWNER_TO_CONTROL:
        if name.startswith(prefix):
            return control
    return None


def failed_join(errors, commands):
    """Коя повърхност SolidCraft е отказал да слее с тялото (или None)."""
    name = failed_feature(errors, commands)
    return name[len("Join "):] if name and name.startswith("Join ") else None


# Резервни варианти по операция — по ред. Отказите са „Bad CurveCusp“ /
# „make_faceuse“ в ядрото на SolidCraft: почти допирателни пресечни криви,
# които зависят от конкретната геометрия, затова се пробват последователно.
# За сливане последният вариант е „отделно тяло“; за отвора — без отвор.
FALLBACKS = {
    "Join Stabilizer": ({"stab_lift_mm": 3.0}, {"stab_lift_mm": 6.0},
                        {"thick": 1.0}),
    "Join Fin": ({"thick": 1.0},),
    "Join Wing": ({"thick": 1.0},),
    "Join Stabilizer_V_R": ({"thick": 1.0},),
    "Join Stabilizer_V_L": ({"thick": 1.0},),
    "Cable exit": ({"cable_exit": {"d": 5.5}}, {"cable_exit": {"dx": 3.0}},
                   {"cable_exit": {"skip": True}}),
    # носът: без отпечатвана стойка → без отделение и отвори (само REF)
    "Motor": ({"motor": {"mount": False}},
              {"motor": {"mount": False, "bay": False}}),
    # витлото: лопатите отделно → без витло
    "Prop": ({"prop": {"join": False}}, {"prop": {"skip": True}}),
}
CONTROL_LEVELS = 3        # кормило: отдръпване → без уши/ос → без кормило


def next_variants(variants, feature, attempt):
    """
    Следващият резервен вариант за отказаната операция `feature`
    ("Join <тяло>" или "Cable exit"; attempt = кой поред опит за нея, от 0)
    или None, ако няма повече.
    """
    variants = dict(variants or {})
    if feature and feature.startswith("Control "):
        control = feature[len("Control "):]
        if attempt >= CONTROL_LEVELS:
            return None
        ctrl = dict(variants.get("ctrl") or {})
        for name in _pair(control):          # огледално: и двете страни
            ctrl[name] = max(ctrl.get(name, 0), attempt + 1)
        variants["ctrl"] = ctrl
        return variants
    if feature and not feature.startswith("Join ") and feature not in FALLBACKS:
        feature = "Join " + feature           # стар вид: само името на тялото
    steps = FALLBACKS.get(feature, ())
    tool = feature[len("Join "):] if feature.startswith("Join ") else None
    if attempt < len(steps):
        step = steps[attempt]
        if "stab_lift_mm" in step:
            variants["stab_lift_mm"] = step["stab_lift_mm"]
        if "thick" in step and tool:
            thick = dict(variants.get("thick") or {})
            for name in _pair(tool):             # V-панелите — и двата
                thick[name] = step["thick"]
            variants["thick"] = thick
        for key in ("cable_exit", "motor", "prop"):
            if key in step:
                variants[key] = dict(step[key])
        return variants
    if attempt == len(steps) and tool:
        separate = set(variants.get("separate") or ())
        separate.add(tool)
        variants["separate"] = sorted(separate)
        return variants
    return None
