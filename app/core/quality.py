"""
quality.py — нива на качеството на модела (един източник).

Ползва се от трите генератора:
  * geometry3d — 3D преглед (outline/wing/tail/ring/stations);
  * assembly   — STEP/3MF (cad_*);
  * printgeom  — STL за печат (stl_*).

Отделен модул, за да не се получава кръгова зависимост между генераторите
(geometry3d внася и assembly, а printgeom — quality).
"""

QUALITY_LEVELS = {
    "low": {
        "label": "Ниско (бързо)",
        "outline": 8, "wing": 6, "tail": 4, "ring": 10, "stations": 12,
        "cad_points": 12, "cad_wing": 6, "cad_ring": 16, "cad_stations": 14,
        "stl_points": 14, "stl_wing": 6, "stl_ring": 24, "stl_step_mm": 25.0,
        "max_tris": 8000,
    },
    "normal": {
        "label": "Средно",
        "outline": 16, "wing": 12, "tail": 6, "ring": 24, "stations": 24,
        "cad_points": 14, "cad_wing": 8, "cad_ring": 20, "cad_stations": 18,
        "stl_points": 18, "stl_wing": 6, "stl_ring": 32, "stl_step_mm": 18.0,
        "max_tris": 16000,
    },
    "high": {
        "label": "Високо (гладко)",
        "outline": 24, "wing": 18, "tail": 8, "ring": 36, "stations": 40,
        "cad_points": 16, "cad_wing": 10, "cad_ring": 24, "cad_stations": 22,
        "stl_points": 24, "stl_wing": 8, "stl_ring": 48, "stl_step_mm": 12.0,
        "max_tris": 32000,
    },
    "ultra": {
        "label": "Много високо",
        "outline": 32, "wing": 24, "tail": 10, "ring": 48, "stations": 56,
        "cad_points": 20, "cad_wing": 12, "cad_ring": 32, "cad_stations": 28,
        "stl_points": 28, "stl_wing": 10, "stl_ring": 64, "stl_step_mm": 8.0,
        "max_tris": 64000,
    },
}

QUALITY_ORDER = ("low", "normal", "high", "ultra")
DEFAULT_QUALITY = "high"


def quality_levels():
    """Каталог на нивата за UI."""
    return [{"key": key, "label": QUALITY_LEVELS[key]["label"]}
            for key in QUALITY_ORDER]


def quality_of(key):
    """Нормализира ключа за качество (непознат → по подразбиране)."""
    key = str(key or "").strip().lower()
    return key if key in QUALITY_LEVELS else DEFAULT_QUALITY


def quality_spec(key):
    """Пълният набор от плътности за дадено ниво."""
    return dict(QUALITY_LEVELS[quality_of(key)])
