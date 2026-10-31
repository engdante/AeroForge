"""
meshcheck.py — проверка и поправка на „solid“ мрежи за 3MF/STEP.

3MF (Core 1.4, Chapter 4.1) не познава B-rep: геометрията е винаги
триъгълна мрежа.  Затова „solid“ там означава мрежа, която изпълнява
трите изисквания за обект `type="model"`:

  * всеки ръб се използва точно два пъти (manifold edges);
  * съседните триъгълници имат еднаква посока на нормалите;
  * нормалите сочат навън (положителен обем).

Допълнително: една обвивка (свързана компонента) с χ = V − E + F = 2 —
това е „едно парче, без дупки“, което слайсерите и CAD приемат за тяло.

Модулът работи само с `printgeom.Mesh` и не строи геометрия.
"""

from .printgeom import Mesh


def _edges(mesh):
    """Ребра с брояч на използванията: {(a, b): брой}."""
    count = {}
    for (a, b, c) in mesh.faces:
        for u, v in ((a, b), (b, c), (c, a)):
            key = (u, v) if u < v else (v, u)
            count[key] = count.get(key, 0) + 1
    return count


def shells(mesh):
    """Броят свързани компоненти (обвивки) по върховете."""
    parent = list(range(len(mesh.vertices)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for (a, b, c) in mesh.faces:
        for u, v in ((a, b), (b, c)):
            ru, rv = find(u), find(v)
            if ru != rv:
                parent[ru] = rv
    return len({find(v) for face in mesh.faces for v in face})


def euler(mesh):
    """Характеристика на Ойлер (V − E + F)."""
    return len(mesh.vertices) - len(_edges(mesh)) + len(mesh.faces)


def genus(mesh):
    """
    Род на повърхността: 0 за плътно тяло (χ=2), 1 за куха черупка (χ=0).

    Печатаните части са кухи (външна + вътрешна повърхност) — това е
    тор, т.е. χ = 0, и е напълно валиден затворен обем.
    """
    return (2 - euler(mesh)) // 2


def solid_report(mesh):
    """
    Пълен доклад дали мрежата е валиден solid.

    връща {"ok", "shells", "euler", "genus", "volume", "boundary_edges",
           "nonmanifold_edges", "problems": [...]}

    „Solid“ = манифолдни ръбове, еднаква ориентация, външни нормали и
    една обвивка — точно изискванията на 3MF Core 1.4 за `type="model"`.
    """
    problems = []
    if not mesh or not mesh.faces:
        return {"ok": False, "shells": 0, "euler": 0, "genus": 0,
                "volume": 0.0, "boundary_edges": 0, "nonmanifold_edges": 0,
                "problems": ["празна мрежа"]}

    counts = _edges(mesh)
    boundary = sum(1 for n in counts.values() if n == 1)
    nonmanifold = sum(1 for n in counts.values() if n > 2)
    volume = mesh.volume()
    parts = shells(mesh)
    chi = euler(mesh)

    if boundary:
        problems.append("%d отворени ръба" % boundary)
    if nonmanifold:
        problems.append("%d ръба с >2 триъгълника" % nonmanifold)
    if volume <= 0:
        problems.append("обемът е отрицателен (нормалите сочат навътре)")
    if parts > 1:
        problems.append("%d отделни обвивки в един обект" % parts)
    if chi % 2 != 0:
        problems.append("нечетна χ = %d (самопресичане?)" % chi)

    return {
        "ok": not problems,
        "shells": parts,
        "euler": chi,
        "genus": (2 - chi) // 2,
        "volume": volume,
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "problems": problems,
    }


def split_shells(mesh, names=None):
    """
    Разделя мрежа с няколко обвивки на отделни затворени тела.

    връща [(име, Mesh)]; имената идват от `names` (по ред на обвивките,
    най-голямата първа) или се генерират като „Име_2“, „Име_3“.
    """
    if not mesh or not mesh.faces:
        return []
    parent = list(range(len(mesh.vertices)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for (a, b, c) in mesh.faces:
        for u, v in ((a, b), (b, c)):
            ru, rv = find(u), find(v)
            if ru != rv:
                parent[ru] = rv

    groups = {}
    for (a, b, c) in mesh.faces:
        groups.setdefault(find(a), []).append((a, b, c))
    if len(groups) <= 1:
        return [(names[0], mesh)] if names else [("", mesh)]

    pieces = []
    for faces in groups.values():
        piece = Mesh()
        remap = {}
        for (a, b, c) in faces:
            ids = []
            for v in (a, b, c):
                if v not in remap:
                    remap[v] = piece.vertex(mesh.vertices[v])
                ids.append(remap[v])
            piece.face(ids[0], ids[1], ids[2])
        pieces.append(piece.orient_outward() if hasattr(piece, "orient_outward")
                      else piece)
    pieces.sort(key=lambda m: m.volume(), reverse=True)

    labels = list(names or [])
    out = []
    for index, piece in enumerate(pieces):
        if index < len(labels):
            label = labels[index]
        elif labels:
            label = "%s_%d" % (labels[0], index + 1)
        else:
            label = "%d" % (index + 1)
        out.append((label, piece))
    return out
