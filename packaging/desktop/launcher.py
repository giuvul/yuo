# ruff: noqa: S603 (runs uv and the installed yuo, both paths it made itself)
"""Yuo desktop launcher: install, start, update, roll back. Standard library only.

The double-click scripts (Yuo-Windows.bat, Yuo-macOS.command, Yuo-Linux.sh) fetch a pinned, hash-checked `uv`
and run this file with a uv-managed Python. Everything lives in one folder per user (YUO_HOME):

    uv/<version>/      the uv binary              versions/<version>/  one virtual environment per release
    python/            uv-managed Python          current              the version that last started fine
    data/              the learner's data         logs/launcher.log    what happened, for support

Start: if Yuo already runs, ask it for a new sign-in link and stop. Otherwise install the release this
launcher came with (or a staged update) beside the current one, start it, and wait until it serves. A new
version becomes `current` only once it has started; if it stops before that, the database is put back from
the backup it made before migrating and the previous version starts instead. Exit code 75 from Yuo
means "install the staged update and start again".
"""

import hashlib
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

EXIT_FOR_UPDATE = 75
READY_TIMEOUT_S = 180
INSTALL_STEPS = 4  # Python, the parts, Yuo, then starting it
APP = Path(__file__).resolve().parent
WINDOWS = sys.platform == "win32"


def home() -> Path:
    if env := os.environ.get("YUO_HOME"):
        return Path(env)
    if WINDOWS:
        return Path(os.environ["LOCALAPPDATA"]) / "Yuo"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Yuo"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "yuo-desktop"


HOME = home()
DATA = HOME / "data"
LOG = HOME / "logs" / "launcher.log"


def say(message: str) -> None:
    print(f"  {message}", flush=True)
    log(message)


class Step:
    """One phase on one line that shows it is alive: "[2/4] Installing Yuo's packages ... 0:42 |", ending in
    "done (0:42)". A launch that prints nothing for minutes looks stuck. ASCII only, for
    any console; without a terminal (output to a file) only the first and last line are written."""

    SPIN = "|/-\\"

    def __init__(self, n: int, total: int, text: str) -> None:
        self.label = f"  [{n}/{total}] {text}" if total > 1 else f"  {text}"
        self.tty = sys.stdout.isatty()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._tick, daemon=True)
        self._start = 0.0

    def _elapsed(self) -> str:
        s = int(time.monotonic() - self._start)
        return f"{s // 60}:{s % 60:02d}"

    def _tick(self) -> None:
        n = 0
        while not self._stop.wait(0.25):
            n += 1
            print(f"\r{self.label} ... {self._elapsed()} {self.SPIN[n % 4]} ", end="", flush=True)

    def __enter__(self) -> Step:
        self._start = time.monotonic()
        log(self.label.strip())
        print(f"{self.label} ...", end="" if self.tty else "\n", flush=True)
        if self.tty:
            self._thread.start()
        return self

    def __exit__(self, kind: object, *_: object) -> None:
        self._stop.set()
        if self.tty:
            self._thread.join()
        end = "done" if kind is None else "stopped"
        print(f"\r{self.label} ... {end} ({self._elapsed()})   ", flush=True)


def log(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")


def version_key(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (-1,)


def venv_bin(venv: Path, name: str) -> Path:
    return venv / ("Scripts" if WINDOWS else "bin") / (name + (".exe" if WINDOWS else ""))


def current() -> str | None:
    try:
        v = (HOME / "current").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return v if (HOME / "versions" / v / ".complete").exists() else None


def set_current(version: str) -> None:
    tmp = HOME / "current.tmp"
    tmp.write_text(version, encoding="utf-8")
    tmp.replace(HOME / "current")


def failed_versions() -> set[str]:
    try:
        return set(json.loads((HOME / "failed.json").read_text(encoding="utf-8")))
    except OSError, ValueError:
        return set()


def mark_failed(version: str) -> None:
    (HOME / "failed.json").write_text(json.dumps(sorted(failed_versions() | {version})), encoding="utf-8")


def uv(*args: str) -> None:
    exe = os.environ["YUO_UV"]
    log("uv " + " ".join(args))
    p = subprocess.run(
        [exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if p.returncode != 0:
        log(p.stdout[-4000:] + p.stderr[-4000:])
        raise RuntimeError(f"uv {args[0]} {args[1] if len(args) > 1 else ''} failed (details in {LOG})")


# --- install ---------------------------------------------------------------------------------------


def install(source: Path) -> str:
    """Install the release in `source` (an `app` folder) into versions/<version>; returns the version."""
    release = json.loads((source / "release.json").read_text(encoding="utf-8"))
    version = release["version"]
    venv = HOME / "versions" / version
    if (venv / ".complete").exists():
        return version
    say(f"Installing Yuo {version}. The first time this downloads about 400 MB and takes a few minutes.")
    shutil.rmtree(venv, ignore_errors=True)
    with Step(1, INSTALL_STEPS, "Preparing Python"):
        uv("venv", "--python", release["python"], "--python-preference", "only-managed", "--quiet", str(venv))
    py = str(venv_bin(venv, "python"))
    wheels = source / "wheels"
    with Step(2, INSTALL_STEPS, "Installing the parts Yuo needs"):
        uv("pip", "install", "--python", py, "--require-hashes", "--find-links", str(wheels), "--quiet",
           "-r", str(source / "requirements.txt"))  # fmt: skip
    with Step(3, INSTALL_STEPS, f"Installing Yuo {version}"):
        uv("pip", "install", "--python", py, "--no-deps", "--quiet", str(source / release["wheel"]))
        if (source / "web").is_dir():
            shutil.copytree(source / "web", venv / "web", dirs_exist_ok=True)
        shutil.copy2(Path(__file__), venv / "launcher.py")
        shutil.copy2(source / "release.json", venv / "release.json")
        p = subprocess.run(
            [str(venv_bin(venv, "yuo")), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    if p.returncode != 0 or version not in p.stdout:
        log(p.stdout + p.stderr)
        raise RuntimeError(f"Yuo {version} did not install correctly (details in {LOG})")
    (venv / ".complete").write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
    return version


def safe_extract(archive: Path, target: Path) -> Path:
    """Unpack a downloaded release; refuses absolute paths and `..` (the zip was hash-checked by Yuo)."""
    shutil.rmtree(target, ignore_errors=True)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            parts = Path(name).parts
            if name.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
                raise RuntimeError(f"unsafe path in {archive.name}: {name}")
        z.extractall(target)
    apps = sorted(target.glob("*/app/release.json"))
    if not apps:
        raise RuntimeError(f"{archive.name} is not a Yuo desktop release")
    return apps[0].parent


def staged_update() -> Path | None:
    """A release Yuo downloaded and checked (data/updates/pending.json), unpacked; None when there is none."""
    pending_file = DATA / "updates" / "pending.json"
    try:
        pending = json.loads(pending_file.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    archive = DATA / "updates" / pending["file"]
    cur = current()
    if pending["version"] in failed_versions() or (
        cur and version_key(pending["version"]) <= version_key(cur)
    ):
        pending_file.unlink(missing_ok=True)
        return None
    if hashlib.sha256(archive.read_bytes()).hexdigest() != pending["sha256"]:
        say("The downloaded update is damaged; it was removed. Yuo will offer it again.")
        archive.unlink(missing_ok=True)
        pending_file.unlink(missing_ok=True)
        return None
    return safe_extract(archive, HOME / "staging" / pending["version"])


# --- run -------------------------------------------------------------------------------------------


def running() -> dict | None:
    try:
        info = json.loads((DATA / "desktop.json").read_text(encoding="utf-8"))
        with urllib.request.urlopen(info["url"] + "/api/health", timeout=3) as r:  # noqa: S310 (loopback)
            return info if r.status == 200 else None
    except Exception:  # not running
        return None


def start(version: str) -> tuple[subprocess.Popen, str]:
    """Starts Yuo; returns the process and this start's id, which Yuo writes into desktop.json. (On Windows
    the process is a small launcher in front of Python, so its pid is not the one Yuo writes.)"""
    venv = HOME / "versions" / version
    launch = secrets.token_hex(8)
    env = os.environ | {"YUO_DATA_DIR": str(DATA), "YUO_WEB_DIR": str(venv / "web"), "YUO_LAUNCH_ID": launch}
    env["PYTHONUTF8"] = "1"  # files and pipes in UTF-8 on Windows too, never the ANSI code page
    for key in ("YUO_UV", "UV_PYTHON_INSTALL_DIR", "UV_CACHE_DIR", "VIRTUAL_ENV"):
        env.pop(key, None)
    if feed := json.loads((venv / "release.json").read_text(encoding="utf-8")).get("feed"):
        env.setdefault("YUO_UPDATE_FEED", feed)
    log(f"start {version}")
    return subprocess.Popen([str(venv_bin(venv, "yuo")), "desktop"], env=env), launch


def wait_ready(proc: subprocess.Popen, version: str, launch: str) -> bool:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        info = running()
        if info and info.get("version") == version and info.get("launch") == launch:
            return True
        time.sleep(0.5)
    return False


def roll_back(version: str, previous: str, since: float) -> None:
    """The new version stopped before it served: put the database back as it was before it migrated."""
    mark_failed(version)
    backups = sorted(
        (p for p in DATA.glob("yuo.db.pre-*.bak") if p.stat().st_mtime >= since - 1),
        key=lambda p: p.stat().st_mtime,
    )
    if backups:
        venv = HOME / "versions" / previous
        env = os.environ | {"YUO_DATA_DIR": str(DATA)}
        p = subprocess.run([str(venv_bin(venv, "yuo")), "restore", str(backups[0])], env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)  # fmt: skip
        log(p.stdout + p.stderr)
        if p.returncode != 0:
            raise RuntimeError(f"Yuo {version} failed and the database could not be put back; see {LOG}")
    say(f"Yuo {version} did not start, so Yuo {previous} is back, with your data as it was. Details: {LOG}")


def desktop_entry() -> None:
    """Linux: a menu entry, pointing at a copy of this launcher in YUO_HOME."""
    if not sys.platform.startswith("linux"):
        return
    keep = HOME / "launcher"
    (keep / "app").mkdir(parents=True, exist_ok=True)
    script = APP.parent / "Yuo-Linux.sh"
    if script.exists():
        shutil.copy2(script, keep / "Yuo-Linux.sh")
        shutil.copy2(Path(__file__), keep / "app" / "launcher.py")
        shutil.copy2(APP / "release.json", keep / "app" / "release.json")
    apps = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    entry = apps / "yuo.desktop"
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=Yuo\nComment=Learning paths\n"
        f'Exec="{keep / "Yuo-Linux.sh"}"\nTerminal=true\nCategories=Education;\n',
        encoding="utf-8",
    )


def main() -> int:
    HOME.mkdir(parents=True, exist_ok=True)
    say(f"Yuo launcher ({platform.system()} {platform.machine()}), files in {HOME}")
    if info := running():
        cur = current()
        if cur:
            subprocess.run([str(venv_bin(HOME / "versions" / cur, "yuo")), "desktop"],
                           env=os.environ | {"YUO_DATA_DIR": str(DATA)}, check=False)  # fmt: skip
        say(f"Yuo is already running at {info['url']}.")
        return 0
    try:
        bundled = json.loads((APP / "release.json").read_text(encoding="utf-8"))
        cur = current()
        if (APP / bundled["wheel"]).exists() and (
            cur is None
            or (
                bundled["version"] not in failed_versions()
                and version_key(bundled["version"]) > version_key(cur)
            )
        ):
            target = install(APP)
        else:
            target = cur
        if target is None:
            say("Yuo is not installed and this folder has no release to install.")
            return 1
        desktop_entry()
        installed = target != cur
        while True:
            previous = current()
            since = time.time()
            with Step(INSTALL_STEPS if installed else 1, INSTALL_STEPS if installed else 1, "Starting Yuo"):
                proc, launch = start(target)
                ready = wait_ready(proc, target, launch)
            if ready:
                info = running() or {}
                say(f"Yuo is open in your browser{' at ' + info['url'] if info.get('url') else ''}.")
                say("Keep this window open while you use Yuo; closing it stops Yuo.")
            if target != previous:
                if ready:
                    set_current(target)
                    (DATA / "updates" / "pending.json").unlink(missing_ok=True)
                    for old in (HOME / "versions").iterdir():  # keep this one and the one before
                        if old.name not in (target, previous):
                            shutil.rmtree(old, ignore_errors=True)
                    shutil.rmtree(HOME / "staging", ignore_errors=True)
                else:
                    proc.terminate()
                    proc.wait(30)
                    if previous is None:  # a first install: nothing to go back to, so it is tried again
                        say(f"Yuo {target} did not start. Start it again; details in {LOG}")
                        return 1
                    roll_back(target, previous, since)
                    target = previous
                    continue
            code = proc.wait()
            log(f"exit {code}")
            if code == EXIT_FOR_UPDATE and (source := staged_update()) is not None:
                target = install(source)
                continue
            if code in (0, EXIT_FOR_UPDATE):
                say("Yuo has stopped. You can close this window.")
                return 0
            say(f"Yuo stopped unexpectedly (code {code}). Start it again; details in {LOG}")
            return code
    except KeyboardInterrupt:
        return 0
    except Exception as e:  # shown to the learner, logged in full
        log(repr(e))
        say(f"Something went wrong: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
