"""
„Допълнения“: изтегляне на APC витлата и SolidCraft portable, безопасно
разархивиране, път до solidcraft-cli. Мрежата е локален HTTP сървър —
тестовете не излизат в интернет.
"""

import functools
import http.server
import os
import shutil
import tempfile
import threading
import unittest
import zipfile

import _env  # noqa: F401  (sys.path + изолирани настройки и tools/)

from core import extras  # noqa: E402
from core import solidcraft_export  # noqa: E402


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class LocalServer:
    def __init__(self, root):
        handler = functools.partial(_Quiet, directory=root)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = "http://127.0.0.1:%d/" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def make_zip(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_LZMA) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


class ExtrasCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="af-extras-")
        self.www = os.path.join(self.tmp, "www")
        os.makedirs(self.www)
        self.old_tools = extras.TOOLS_DIR
        extras.TOOLS_DIR = os.path.join(self.tmp, "tools")
        self.server = LocalServer(self.www)

    def tearDown(self):
        self.server.close()
        extras.TOOLS_DIR = self.old_tools
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestSafeExtract(ExtrasCase):
    def test_zip_slip_is_skipped(self):
        archive = os.path.join(self.tmp, "evil.zip")
        make_zip(archive, {"ok/a.txt": "a", "../evil.txt": "x",
                           "/abs.txt": "y", "C:/win.txt": "z"})
        target = os.path.join(self.tmp, "out")
        count = extras.safe_extract(archive, target)
        self.assertEqual(count, 2)          # ok/a.txt и abs.txt (без „/“)
        self.assertTrue(os.path.isfile(os.path.join(target, "ok", "a.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))
        extracted = [f for _r, _d, files in os.walk(target) for f in files]
        self.assertNotIn("win.txt", extracted)       # „C:/…“ — пропуснат

    def test_flatten_with_filter(self):
        archive = os.path.join(self.tmp, "apc.zip")
        make_zip(archive, {"PE0-FILES_WEB/": "", "PE0-FILES_WEB/10x6-PERF.PE0": "g",
                           "PE0-FILES_WEB/readme.txt": "r"})
        target = os.path.join(self.tmp, "props")
        n = extras.safe_extract(archive, target,
                                lambda n: n.upper().endswith(".PE0"), flatten=True)
        self.assertEqual(n, 1)
        self.assertEqual(os.listdir(target), ["10x6-PERF.PE0"])


class TestApc(ExtrasCase):
    def test_archive_url_from_page(self):
        html = ('<a href="https://x/PE0-FILES_WEB-202401.zip">old</a>'
                '<a href="/wp/PE0-FILES_WEB-202602.zipx">new</a>'
                '<a href="https://x/PERFILES_WEB-202602.zipx">perf</a>')
        url = extras.apc_archive_url(html)
        self.assertTrue(url.endswith("/wp/PE0-FILES_WEB-202602.zipx"))
        self.assertTrue(url.startswith("https://www.apcprop.com/"))
        self.assertIsNone(extras.apc_archive_url("<html></html>"))

    def test_install_from_page(self):
        make_zip(os.path.join(self.www, "PE0-FILES_WEB-209901.zipx"),
                 {"PE0-FILES_WEB/9x6-PERF.PE0": "g1",
                  "PE0-FILES_WEB/10x5-PERF.PE0": "g2"})
        with open(os.path.join(self.www, "page.html"), "w") as fh:
            fh.write('<a href="PE0-FILES_WEB-209901.zipx">geometry</a>')
        old_page = extras.APC_PAGE
        extras.APC_PAGE = self.server.url + "page.html"
        try:
            prop_dir = os.path.join(self.tmp, "PE0-FILES_WEB")
            msg = extras.install_apc(prop_dir, wait=True)
        finally:
            extras.APC_PAGE = old_page
        self.assertIn("2 витла", msg)
        self.assertEqual(extras.apc_status(prop_dir)["count"], 2)
        self.assertEqual(extras.progress()["apc"]["state"], "done")


class TestSolidcraft(ExtrasCase):
    def test_portable_zip_is_found_by_find_cli(self):
        make_zip(os.path.join(self.www, "sc.zip"),
                 {"SolidCraft/solidcraft-cli.exe": "bin",
                  "SolidCraft/lib/x.dll": "dll"})
        extras.install_solidcraft(self.server.url + "sc.zip", wait=True)
        cli = extras.configured_cli()
        self.assertTrue(cli and cli.endswith("solidcraft-cli.exe"))
        self.assertTrue(cli.startswith(extras.TOOLS_DIR))
        old_env = {k: os.environ.pop(k, None)
                   for k in ("SOLIDCRAFT_CLI", "SOLIDCRAFT_CLI_PATH")}
        try:
            self.assertEqual(solidcraft_export.find_cli(), cli)
        finally:
            for k, v in old_env.items():
                if v is not None:
                    os.environ[k] = v
        self.assertEqual(extras.read_config()["solidcraft_url"],
                         self.server.url + "sc.zip")

    def test_not_a_zip_or_no_cli(self):
        with open(os.path.join(self.www, "setup.exe"), "wb") as fh:
            fh.write(b"MZ not a zip")
        with self.assertRaises(ValueError):
            extras.install_solidcraft(self.server.url + "setup.exe", wait=True)
        make_zip(os.path.join(self.www, "empty.zip"), {"readme.txt": "x"})
        with self.assertRaises(ValueError):
            extras.install_solidcraft(self.server.url + "empty.zip", wait=True)
        self.assertIsNone(extras.find_portable_cli())

    def test_bad_url_and_cli_path(self):
        with self.assertRaises(ValueError):
            extras.install_solidcraft("file:///C:/x.zip")
        with self.assertRaises(ValueError):
            extras.set_cli_path(os.path.join(self.tmp, "nope.exe"))
        folder = os.path.join(self.tmp, "sc")
        os.makedirs(folder)
        exe = os.path.join(folder, "solidcraft-cli.exe")
        open(exe, "wb").close()
        self.assertEqual(extras.set_cli_path(folder), exe)   # папка → файла
        self.assertEqual(extras.configured_cli(), exe)

    def test_pick_asset_prefers_versioned_name(self):
        release = {"tag_name": "v1.2.3", "assets": [
            {"name": "solidcraft-windows-x64-portable.zip",
             "browser_download_url": "https://x/fixed.zip", "size": 5,
             "digest": "sha256:aa"},
            {"name": "solidcraft-1.2.3-windows-x64-portable.zip",
             "browser_download_url": "https://x/v.zip", "size": 5,
             "digest": "sha256:bb"},
            {"name": "solidcraft-1.2.3-linux-x86_64.tar.gz",
             "browser_download_url": "https://x/l.tgz"}]}
        win = extras.pick_asset(release, ("solidcraft-", "windows-x64-portable.zip"))
        self.assertEqual((win["url"], win["sha256"], win["version"]),
                         ("https://x/v.zip", "bb", "1.2.3"))
        lin = extras.pick_asset(release, ("solidcraft-", "linux-x86_64.tar.gz"))
        self.assertEqual(lin["url"], "https://x/l.tgz")
        self.assertIsNone(lin["sha256"])
        self.assertIsNone(extras.pick_asset(release, ("solidcraft-cli-",
                                                      "macos-universal.zip")))

    def test_latest_from_api_with_checksum(self):
        import hashlib
        import json
        make_zip(os.path.join(self.www, "pkg.zip"),
                 {"sc-9/solidcraft-cli.exe": "bin"})
        with open(os.path.join(self.www, "pkg.zip"), "rb") as fh:
            data = fh.read()
        prefix, suffix = extras.platform_asset()
        name = "%s9.9.9-%s" % (prefix, suffix)
        release = {"tag_name": "v9.9.9", "assets": [{
            "name": name, "browser_download_url": self.server.url + "pkg.zip",
            "size": len(data),
            "digest": "sha256:" + hashlib.sha256(data).hexdigest()}]}
        with open(os.path.join(self.www, "latest.json"), "w") as fh:
            json.dump(release, fh)
        old = extras.SC_API_LATEST
        extras.SC_API_LATEST = self.server.url + "latest.json"
        try:
            self.assertEqual(extras.latest_solidcraft()["version"], "9.9.9")
            msg = extras.install_solidcraft(wait=True)
            self.assertIn("SHA-256", msg)
            self.assertEqual(extras.read_config()["solidcraft_version"], "9.9.9")
            # повреден файл → грешка, старата инсталация остава
            release["assets"][0]["digest"] = "sha256:" + "0" * 64
            with open(os.path.join(self.www, "latest.json"), "w") as fh:
                json.dump(release, fh)
            with self.assertRaises(ValueError):
                extras.install_solidcraft(wait=True)
            self.assertTrue(extras.find_portable_cli())
        finally:
            extras.SC_API_LATEST = old

    def test_tar_gz_archive(self):
        import tarfile
        src = os.path.join(self.tmp, "src", "sc")
        os.makedirs(src)
        open(os.path.join(src, "solidcraft-cli"), "w").close()
        tgz = os.path.join(self.www, "sc.tar.gz")
        with tarfile.open(tgz, "w:gz") as tf:
            tf.add(src, arcname="sc")
        extras.install_solidcraft(self.server.url + "sc.tar.gz", wait=True)
        self.assertTrue(extras.find_portable_cli().endswith("solidcraft-cli"))

    def test_inside_on_other_drive(self):
        if os.name != "nt":
            self.skipTest("само Windows")
        other = "Z:/x" if not self.tmp.upper().startswith("Z:") else "Y:/x"
        self.assertFalse(extras._inside(other, self.tmp))

    def test_status_shape(self):
        st = extras.status(os.path.join(self.tmp, "none"))
        self.assertFalse(st["apc"]["present"])
        self.assertIn("present", st["solidcraft"])
        self.assertIn("apc", st["progress"])


if __name__ == "__main__":
    unittest.main()
