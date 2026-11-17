"""
Златни снимки (regression net) за design.compute().

Снимката е плосък речник {път: стойност} от всички скаларни изходи
(без кривите и входните данни). Тестът сравнява текущите резултати
с записаните, за да се вижда всяка нежелана промяна в изчисленията.

Пресъздаване на снимката (само когато промяната е нарочна!):
    python tests/_golden.py --update
"""

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN_DIR = os.path.join(HERE, "golden")
SKIP_KEYS = {"curves", "inputs", "version"}

CASES = {
    "trainer_600g": {"name": "Golden trainer", "mission": "trainer",
                     "payload": {"mode": "simple", "total_g": 600}},
    "trainer_800g": {"name": "Golden trainer heavy", "mission": "trainer",
                     "payload": {"mode": "simple", "total_g": 800}},
}


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if prefix == "" and k in SKIP_KEYS:
                continue
            out.update(flatten(v, "%s.%s" % (prefix, k) if prefix else str(k)))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.update(flatten(v, "%s[%d]" % (prefix, i)))
    elif isinstance(obj, float):
        out[prefix] = obj if math.isfinite(obj) else repr(obj)
    elif isinstance(obj, (int, str, bool)) or obj is None:
        out[prefix] = obj
    return out


def snapshot(case_name):
    from core import design  # noqa: E402 (_env вече е импортиран в тестовете)
    res = design.compute(dict(CASES[case_name]))
    return flatten(res)


def load(case_name):
    with open(os.path.join(GOLDEN_DIR, case_name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def compare(expected, actual, rel=1e-9, abs_tol=1e-9):
    """Връща списък с разлики (празен = съвпадение)."""
    diffs = []
    for key in sorted(set(expected) | set(actual)):
        if key not in actual:
            diffs.append("липсва: %s" % key)
            continue
        if key not in expected:
            diffs.append("ново поле: %s" % key)
            continue
        e, a = expected[key], actual[key]
        if isinstance(e, float) and isinstance(a, (int, float)):
            if not math.isclose(e, a, rel_tol=rel, abs_tol=abs_tol):
                diffs.append("%s: %r → %r" % (key, e, a))
        elif e != a:
            diffs.append("%s: %r → %r" % (key, e, a))
    return diffs


if __name__ == "__main__":
    if "--update" in sys.argv:
        sys.path.insert(0, os.path.join(HERE, "..", "app", "core"))
        sys.path.insert(0, os.path.join(HERE, "..", "app"))
        import _env  # noqa: F401
        os.makedirs(GOLDEN_DIR, exist_ok=True)
        for name in CASES:
            with open(os.path.join(GOLDEN_DIR, name + ".json"), "w", encoding="utf-8") as fh:
                json.dump(snapshot(name), fh, ensure_ascii=False, indent=1, sort_keys=True)
            print("записана:", name)
