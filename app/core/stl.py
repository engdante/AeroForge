"""
stl.py — запис на бинарен STL без външни зависимости.

STL няма единици: приемаме, че координатите са в mm (както ги дава
printgeom.py). Форматът е 80 байта заглавка + uint32 брой триъгълници +
по 50 байта на триъгълник (нормала, три върха, 2 байта атрибут).

Защо бинарен, а не ASCII: файлът е ~5× по-малък, а всички слайсери го
поддържат. Няма нужда от numpy — върховете се пакетират с `struct`.
"""

import math
import struct

HEADER_BYTES = 80
TRIANGLE_BYTES = 50


def _normal(a, b, c):
    """Единична нормала на триъгълник (нула при изроден триъгълник)."""
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 1e-12:
        return (0.0, 0.0, 0.0)
    return (nx / length, ny / length, nz / length)


def triangles_from_mesh(vertices, faces):
    """Превръща (vertices, faces) в списък от триъгълници (кортежи)."""
    out = []
    n = len(vertices)
    for face in faces:
        if len(face) != 3:
            continue
        a, b, c = face
        if not (0 <= a < n and 0 <= b < n and 0 <= c < n):
            continue
        out.append((vertices[a], vertices[b], vertices[c]))
    return out


def write_stl(path, vertices, faces, name="AeroForge"):
    """
    Записва бинарен STL. Връща броя триъгълници и размера на файла.
    """
    tris = triangles_from_mesh(vertices, faces)
    header = ("%s — AeroForge, mm" % name).encode("ascii", "replace")
    header = header[:HEADER_BYTES].ljust(HEADER_BYTES, b"\0")
    written = 0
    with open(path, "wb") as f:
        f.write(header)
        f.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            nx, ny, nz = _normal(a, b, c)
            f.write(struct.pack(
                "<12fH",
                nx, ny, nz,
                float(a[0]), float(a[1]), float(a[2]),
                float(b[0]), float(b[1]), float(b[2]),
                float(c[0]), float(c[1]), float(c[2]),
                0))
            written += 1
    return {"triangles": written,
            "bytes": HEADER_BYTES + 4 + written * TRIANGLE_BYTES}


def read_stl(path):
    """Чете бинарен STL (за тестове и проверки). Връща (vertices, faces)."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < HEADER_BYTES + 4:
        return [], []
    count = struct.unpack("<I", data[HEADER_BYTES:HEADER_BYTES + 4])[0]
    vertices = []
    faces = []
    offset = HEADER_BYTES + 4
    for i in range(count):
        if offset + TRIANGLE_BYTES > len(data):
            break
        values = struct.unpack("<12fH", data[offset:offset + TRIANGLE_BYTES])
        base = len(vertices)
        vertices.extend([tuple(values[3:6]), tuple(values[6:9]),
                         tuple(values[9:12])])
        faces.append((base, base + 1, base + 2))
        offset += TRIANGLE_BYTES
    return vertices, faces
