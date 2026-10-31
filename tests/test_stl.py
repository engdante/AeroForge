"""
Тестове за бинарния STL (stl.py): формат, размер, нормали, четене.
"""

import os
import struct
import tempfile
import unittest

import _env  # noqa: F401  (sys.path + изолирани настройки)

from core import stl  # noqa: E402


class TestWrite(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="aeroforge_stl_")
        self.path = os.path.join(self.dir, "test.stl")

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_single_triangle_size_and_header(self):
        verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        faces = [(0, 1, 2)]
        info = stl.write_stl(self.path, verts, faces, "Тест")
        self.assertEqual(info["triangles"], 1)
        self.assertEqual(info["bytes"], 84 + 50)
        self.assertEqual(os.path.getsize(self.path), 84 + 50)
        with open(self.path, "rb") as f:
            header = f.read(80)
            count = struct.unpack("<I", f.read(4))[0]
        self.assertIn(b"AeroForge", header)
        self.assertEqual(count, 1)

    def test_normal_points_along_z(self):
        verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        stl.write_stl(self.path, verts, [(0, 1, 2)])
        with open(self.path, "rb") as f:
            f.seek(84)
            values = struct.unpack("<12fH", f.read(50))
        self.assertAlmostEqual(values[0], 0.0, places=6)
        self.assertAlmostEqual(values[1], 0.0, places=6)
        self.assertAlmostEqual(values[2], 1.0, places=6)

    def test_degenerate_triangle_has_zero_normal(self):
        verts = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
        stl.write_stl(self.path, verts, [(0, 1, 2)])
        with open(self.path, "rb") as f:
            f.seek(84)
            values = struct.unpack("<12fH", f.read(50))
        self.assertEqual(values[0:3], (0.0, 0.0, 0.0))

    def test_bad_faces_are_skipped(self):
        verts = [(0, 0, 0), (1, 0, 0)]
        info = stl.write_stl(self.path, verts, [(0, 1, 5), (0, 1)])
        self.assertEqual(info["triangles"], 0)

    def test_empty_mesh_is_valid_file(self):
        info = stl.write_stl(self.path, [], [])
        self.assertEqual(info["bytes"], 84)
        self.assertEqual(os.path.getsize(self.path), 84)

    def test_roundtrip(self):
        verts = [(0, 0, 0), (10, 0, 0), (0, 10, 5), (1, 1, 1)]
        faces = [(0, 1, 2), (0, 2, 3)]
        stl.write_stl(self.path, verts, faces)
        read_verts, read_faces = stl.read_stl(self.path)
        self.assertEqual(len(read_faces), 2)
        self.assertEqual(len(read_verts), 6)
        self.assertAlmostEqual(read_verts[1][0], 10.0, places=4)
        self.assertAlmostEqual(read_verts[2][2], 5.0, places=4)

    def test_read_missing_file_raises(self):
        with self.assertRaises(OSError):
            stl.read_stl(os.path.join(self.dir, "няма.stl"))


if __name__ == "__main__":
    unittest.main()
