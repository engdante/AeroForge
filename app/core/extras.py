"""
extras.py — допълнения, които приложението може да изтегли и нагласи само.

  * APC витла (PE0-FILES_WEB) — геометрията на ~450 витла от apcprop.com
    (панелът „Витло“ → витло за 3D печат). Адресът на архива се взима от
    страницата за изтегляния (името съдържа дата и се сменя), с резервен
    адрес, ако страницата не се отвори.
  * SolidCraft (tangency-labs/solidcraft, MIT/Apache) — последната версия
    от GitHub Releases за тази платформа (Windows: portable .zip, Linux:
    .tar.gz, macOS: CLI .zip), проверена по SHA-256 и разархивирана в
    tools/solidcraft до приложението; или път до вече инсталиран
    `solidcraft-cli`, или друг адрес на архив.

Изтеглянето върви във фонова нишка; UI-ят пита за напредъка (progress).
Разархивирането е безопасно: файл извън целевата папка се пропуска.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.parse
import urllib.request
import zipfile

APC_PAGE = "https://www.apcprop.com/technical-information/file-downloads/"
APC_FALLBACK_URL = ("https://www.apcprop.com/wp-content/uploads/2026/02/"
                    "PE0-FILES_WEB-202602.zipx")
APC_HREF = re.compile(r'href="([^"]*PE0-FILES_WEB-\d+\.zipx?)"', re.I)
SC_REPO = "tangency-labs/solidcraft"
SC_API_LATEST = "https://api.github.com/repos/%s/releases/latest" % SC_REPO
SC_LATEST_DOWNLOAD = "https://github.com/%s/releases/latest/download/" % SC_REPO
SC_PAGE = "https://solidcraft.io/download/"
USER_AGENT = "AeroForge-extras/1.0"
TIMEOUT_S = 60
CHUNK = 64 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 ** 3      # 2 GB — защита от грешен адрес
CLI_NAMES = ("solidcraft-cli.exe", "solidcraft-cli")


# ------------------------------------------------------------------ пътища
def base_dir():
    from . import settings
    return settings.base_dir()


TOOLS_DIR = None        # тестовете го насочват към временна папка (_env.py)


def tools_dir():
    return TOOLS_DIR or os.path.join(base_dir(), "tools")


def config_path():
    return os.path.join(tools_dir(), "extras.json")


def read_config():
    try:
        with open(config_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_config(**changes):
    data = read_config()
    data.update(changes)
    os.makedirs(tools_dir(), exist_ok=True)
    tmp = config_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, config_path())
    return data


# ------------------------------------------------------------- SolidCraft
def _is_cli(path):
    return bool(path) and os.path.isfile(path) and \
        os.path.basename(path).lower() in CLI_NAMES


def find_portable_cli(root=None):
    """solidcraft-cli в tools/solidcraft (портабъл архивът) или None."""
    root = root or os.path.join(tools_dir(), "solidcraft")
    if not os.path.isdir(root):
        return None
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.lower() in CLI_NAMES:
                return os.path.join(folder, name)
    return None


def configured_cli():
    """Пътят, зададен в „Допълнения“ (или изтегленият portable), ако го има."""
    path = read_config().get("solidcraft_cli")
    if _is_cli(path):
        return path
    return find_portable_cli()


def set_cli_path(path):
    path = os.path.abspath(os.path.expanduser(str(path or "").strip().strip('"')))
    if os.path.isdir(path):
        for name in CLI_NAMES:
            if os.path.isfile(os.path.join(path, name)):
                path = os.path.join(path, name)
                break
    if not _is_cli(path):
        raise ValueError("това не е solidcraft-cli: %s" % path)
    write_config(solidcraft_cli=path)
    return path


# ----------------------------------------------------------------- задачи
class Job:
    """Напредък на едно изтегляне (четен от UI-а през progress())."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"state": "idle"}

    def set(self, **kw):
        with self.lock:
            self.state.update(kw)

    def reset(self, label):
        with self.lock:
            self.state = {"state": "running", "label": label, "done": 0,
                          "total": 0, "message": ""}

    def get(self):
        with self.lock:
            return dict(self.state)

    def running(self):
        return self.get().get("state") == "running"


JOBS = {"apc": Job(), "solidcraft": Job()}


def progress():
    return {key: job.get() for key, job in JOBS.items()}


def _check_url(url):
    parts = urllib.parse.urlparse(str(url or "").strip())
    if parts.scheme not in ("https", "http") or not parts.netloc:
        raise ValueError("невалиден адрес: %s" % url)
    return parts.geturl()


def _open(url):
    req = urllib.request.Request(_check_url(url),
                                 headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=TIMEOUT_S)  # noqa: S310 (http/https само)


def _download(url, dest, job, sha256=None):
    digest = hashlib.sha256()
    with _open(url) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        job.set(total=total, done=0, message="изтегляне…")
        done = 0
        while True:
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            done += len(chunk)
            if done > MAX_ARCHIVE_BYTES:
                raise ValueError("архивът е по-голям от %d MB"
                                 % (MAX_ARCHIVE_BYTES // 1024 ** 2))
            out.write(chunk)
            digest.update(chunk)
            job.set(done=done)
    if sha256 and digest.hexdigest().lower() != sha256.lower():
        raise ValueError("контролната сума (SHA-256) не съвпада — файлът е "
                         "повреден при изтеглянето; опитай пак")
    return dest


def _inside(path, root):
    root = os.path.abspath(root)
    path = os.path.abspath(path)
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:          # различни дискове (C: / D:) → не е вътре
        return False


def safe_extract(archive, target, member_filter=None, flatten=False):
    """
    Разархивира `archive` в `target`. Пропуска пътища извън `target`
    (zip-slip) и абсолютни пътища. `flatten` — без подпапки (само имената).
    връща броя извлечени файлове.
    """
    os.makedirs(target, exist_ok=True)
    count = 0
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if member_filter and not member_filter(name):
                continue
            rel = os.path.basename(name) if flatten else name.lstrip("/")
            if not rel or ".." in rel.split("/") or os.path.isabs(rel) \
                    or re.match(r"^[A-Za-z]:", rel):
                continue
            dest = os.path.join(target, *rel.split("/"))
            if not _inside(dest, target):
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            count += 1
    return count


def safe_extract_tar(archive, target):
    """Като safe_extract, но за .tar.gz (Linux/FreeBSD архивите)."""
    os.makedirs(target, exist_ok=True)
    count = 0
    with tarfile.open(archive, "r:*") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue                     # без връзки и устройства
            rel = member.name.replace("\\", "/").lstrip("/")
            if not rel or ".." in rel.split("/"):
                continue
            dest = os.path.join(target, *rel.split("/"))
            if not _inside(dest, target):
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            src = tf.extractfile(member)
            with src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            if member.mode & 0o111:
                os.chmod(dest, 0o755)
            count += 1
    return count


def apc_archive_url(html):
    """Адресът на архива с геометрията от страницата на APC (или None)."""
    found = APC_HREF.findall(html or "")
    if not found:
        return None
    # най-новата дата
    found.sort(key=lambda u: re.search(r"(\d+)\.zipx?$", u, re.I).group(1))
    return urllib.parse.urljoin(APC_PAGE, found[-1])


def apc_status(prop_dir):
    try:
        count = sum(1 for n in os.listdir(prop_dir) if n.upper().endswith(".PE0"))
    except OSError:
        count = 0
    return {"present": count > 0, "count": count, "dir": prop_dir,
            "source": APC_PAGE}


def _run(job, label, work):
    def target():
        try:
            message = work()
            job.set(state="done", message=message)
        except Exception as exc:  # noqa: BLE001 — грешката отива в UI-а
            job.set(state="error", message=str(exc))
    if job.running():
        return False
    job.reset(label)
    threading.Thread(target=target, daemon=True).start()
    return True


def install_apc(prop_dir, wait=False):
    """Изтегля APC геометрията в `prop_dir` (фонова задача)."""
    job = JOBS["apc"]

    def work():
        job.set(message="търся архива на apcprop.com…")
        try:
            with _open(APC_PAGE) as resp:
                html = resp.read(2 * 1024 * 1024).decode("utf-8", "replace")
            url = apc_archive_url(html) or APC_FALLBACK_URL
        except Exception:  # noqa: BLE001 — страницата е само за адреса
            url = APC_FALLBACK_URL
        tmp = tempfile.mkdtemp(prefix="aeroforge-apc-")
        try:
            archive = _download(url, os.path.join(tmp, "apc.zip"), job)
            job.set(message="разархивиране…")
            count = safe_extract(archive, prop_dir,
                                 lambda n: n.upper().endswith(".PE0"),
                                 flatten=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if not count:
            raise ValueError("архивът не съдържа .PE0 файлове (%s)" % url)
        return "%d витла от %s" % (count, os.path.basename(url))

    if wait:
        job.reset("APC витла")
        msg = work()
        job.set(state="done", message=msg)
        return msg
    return _run(job, "APC витла", work)


def platform_asset():
    """
    (префикс, окончание) на архива на SolidCraft за тази платформа или None.
    Имената в GitHub Releases: solidcraft-<версия>-windows-x64-portable.zip,
    solidcraft-<версия>-linux-x86_64.tar.gz, solidcraft-cli-<версия>-macos-
    universal.zip; без версия — същите файлове за „последна версия“.
    """
    machine = platform.machine().lower()
    if sys.platform.startswith("win"):
        arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64",
                "aarch64": "arm64", "x86": "x86", "i386": "x86",
                "i686": "x86"}.get(machine, "x64")
        return "solidcraft-", "windows-%s-portable.zip" % arch
    if sys.platform == "darwin":
        return "solidcraft-cli-", "macos-universal.zip"
    if sys.platform.startswith("linux"):
        arch = "aarch64" if machine in ("aarch64", "arm64") else "x86_64"
        return "solidcraft-", "linux-%s.tar.gz" % arch
    return None


def pick_asset(release, asset=None):
    """Файлът за платформата от отговора на GitHub API (или None)."""
    asset = asset or platform_asset()
    if not asset or not isinstance(release, dict):
        return None
    prefix, suffix = asset
    tag = str(release.get("tag_name") or "")
    version = tag[1:] if tag.startswith("v") else tag
    assets = release.get("assets") or []
    # предпочитаме името с версия (то е и в SHA256SUMS.txt)
    for want in ("%s%s-%s" % (prefix, version, suffix), prefix + suffix):
        for a in assets:
            if a.get("name") == want and a.get("browser_download_url"):
                digest = str(a.get("digest") or "")
                return {
                    "version": version, "name": want,
                    "url": a["browser_download_url"],
                    "size": int(a.get("size") or 0),
                    "sha256": digest[7:] if digest.startswith("sha256:") else None,
                }
    return None


def latest_solidcraft():
    """
    Последната стабилна версия от GitHub за тази платформа:
    {"version", "name", "url", "size", "sha256"}; ако API-то не отговори —
    стабилният адрес „latest/download“ без версия и без контролна сума.
    """
    asset = platform_asset()
    if not asset:
        raise ValueError("няма готова версия на SolidCraft за %s — виж %s"
                         % (sys.platform, SC_PAGE))
    try:
        with _open(SC_API_LATEST) as resp:
            release = json.loads(resp.read(4 * 1024 * 1024).decode("utf-8"))
        found = pick_asset(release, asset)
        if found:
            return found
    except Exception:  # noqa: BLE001 — API-то е само за версията и сумата
        pass
    name = asset[0] + asset[1]
    return {"version": None, "name": name, "url": SC_LATEST_DOWNLOAD + name,
            "size": 0, "sha256": None}


def cli_version(cli):
    """„0.43.0“ от `solidcraft-cli --version` (или None)."""
    if not cli:
        return None
    try:
        out = subprocess.run(
            [cli, "--version"], capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        m = re.search(r"(\d+\.\d+\.\d+[\w.\-]*)", out.stdout or "")
        return m.group(1) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def install_solidcraft(url=None, wait=False):
    """
    Изтегля SolidCraft в tools/solidcraft: без `url` — последната версия от
    GitHub за тази платформа (проверена по SHA-256); с `url` — този архив
    (.zip или .tar.gz).
    """
    if url:
        url = _check_url(url)
    job = JOBS["solidcraft"]
    target = os.path.join(tools_dir(), "solidcraft")

    def work():
        if url:
            info = {"version": None, "url": url, "sha256": None,
                    "name": os.path.basename(urllib.parse.urlparse(url).path)}
        else:
            job.set(message="търся последната версия в GitHub…")
            info = latest_solidcraft()
        tmp = tempfile.mkdtemp(prefix="aeroforge-sc-")
        try:
            archive = _download(info["url"], os.path.join(tmp, "solidcraft.pkg"),
                                job, info.get("sha256"))
            job.set(message="разархивиране…")
            staging = target + ".new"
            shutil.rmtree(staging, ignore_errors=True)
            if zipfile.is_zipfile(archive):
                safe_extract(archive, staging)
            elif tarfile.is_tarfile(archive):
                safe_extract_tar(archive, staging)
            else:
                raise ValueError("това не е .zip/.tar.gz архив. Инсталатор "
                                 "(.exe/.msi/.dmg) пусни сам и после задай "
                                 "пътя до solidcraft-cli.")
            cli = find_portable_cli(staging)
            if not cli:
                shutil.rmtree(staging, ignore_errors=True)
                raise ValueError("в архива няма solidcraft-cli")
            shutil.rmtree(target, ignore_errors=True)
            os.replace(staging, target)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        cli = find_portable_cli(target)
        if cli and os.name != "nt":
            os.chmod(cli, 0o755)
        version = info.get("version") or cli_version(cli)
        write_config(solidcraft_cli=cli, solidcraft_url=url or "",
                     solidcraft_version=version)
        return "SolidCraft %s%s" % (version or "", " (проверен SHA-256)"
                                    if info.get("sha256") else "")

    if wait:
        job.reset("SolidCraft")
        msg = work()
        job.set(state="done", message=msg)
        return msg
    return _run(job, "SolidCraft", work)


def status(prop_dir):
    from . import solidcraft_export
    cli = solidcraft_export.find_cli()
    cfg = read_config()
    return {
        "apc": apc_status(prop_dir),
        "solidcraft": {"present": bool(cli), "cli": cli,
                       "version": cli_version(cli) if cli else None,
                       "portable": bool(cli) and _inside(cli, tools_dir()),
                       "url": cfg.get("solidcraft_url") or "",
                       "asset": "".join(platform_asset() or ()),
                       "page": SC_PAGE,
                       "portable_dir": os.path.join(tools_dir(), "solidcraft")},
        "progress": progress(),
    }
