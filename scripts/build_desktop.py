"""Build the desktop release zip: launchers, the Yuo wheel, a hash-pinned lock, the web app.

    uv run scripts/build_desktop.py [--out DIR] [--base-url https://.../download/vX.Y.Z] [--feed URL]

Layout of `yuo-<version>-desktop.zip`:

    Yuo-<version>/Yuo-Windows.bat, Yuo-macOS.command, Yuo-Linux.sh, LICENSE, NOTICE, guide/index.html
    Yuo-<version>/app/launcher.py, release.json, requirements.txt (every hash), wheels/, yuo-<v>-py3-none-any.whl, web/

Dependencies published only as source (docopt) are built into wheels here and pinned by the built wheel's hash,
so installing never runs a build on the learner's machine. Also writes `SHA256SUMS` and `latest.json` (the
release feed, packaging/desktop/README.md) beside the zip.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "packaging" / "desktop"
PYTHON = "3.14"


def sh(*cmd: str, cwd: Path = ROOT) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def requirements(work: Path, wheels: Path) -> str:
    """`uv export` with hashes; source-only packages swapped for wheels built here (and their hashes)."""
    text = sh("uv", "export", "--no-dev", "--no-emit-project", "--frozen", "--format", "requirements.txt")
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    for pkg in lock["package"]:
        if (
            pkg.get("wheels")
            or not pkg.get("sdist")
            or not re.search(rf"^{re.escape(pkg['name'])}==", text, re.M)
        ):
            continue
        sdist = pkg["sdist"]
        src = work / sdist["url"].rsplit("/", 1)[1]
        urllib.request.urlretrieve(sdist["url"], src)  # noqa: S310 (https URL from the lock)
        if "sha256:" + sha256(src) != sdist["hash"]:
            raise SystemExit(f"{src.name}: hash differs from uv.lock")
        sh("uv", "build", "--wheel", "--python", PYTHON, "--out-dir", str(wheels), str(src))
        built = next(wheels.glob(f"{pkg['name'].replace('-', '_')}-{pkg['version']}-*.whl"))
        entry = re.compile(
            rf"^{re.escape(pkg['name'])}=={re.escape(pkg['version'])}.*?(?=^\S|\Z)", re.M | re.S
        )
        text, n = entry.subn(f"{pkg['name']}=={pkg['version']} \\\n    --hash=sha256:{sha256(built)}\n", text)
        if n != 1:
            raise SystemExit(f"could not pin {pkg['name']} in the exported requirements")
        print(f"built {built.name} from source", file=sys.stderr)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist" / "desktop"))
    ap.add_argument("--base-url", help="where the zip will be published (for latest.json)")
    ap.add_argument("--feed", help="the release feed URL the installed app checks (YUO_UPDATE_FEED)")
    ap.add_argument("--notes-url", help="the release notes page (for latest.json)")
    a = ap.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    web = ROOT / "web" / "dist"
    if not (web / "index.html").exists():
        raise SystemExit("build the web app first: (cd web && npm run build)")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        top = work / f"Yuo-{version}"
        app, wheels = top / "app", top / "app" / "wheels"
        wheels.mkdir(parents=True)
        sh("uv", "build", "--wheel", "--out-dir", str(work / "build"))
        wheel = next((work / "build").glob(f"yuo-{version}-*.whl"))
        shutil.copy2(wheel, app / wheel.name)
        (app / "requirements.txt").write_text(requirements(work, wheels), encoding="utf-8")
        (wheels / ".gitignore").unlink(missing_ok=True)  # uv build's marker
        shutil.copytree(web, app / "web")
        shutil.copy2(DESKTOP / "launcher.py", app / "launcher.py")
        release = {"version": version, "python": PYTHON, "wheel": wheel.name}
        if a.feed:
            release["feed"] = a.feed
        (app / "release.json").write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
        for name in ("Yuo-Windows.bat", "Yuo-macOS.command", "Yuo-Linux.sh"):
            shutil.copy2(DESKTOP / name, top / name)
        shutil.copytree(DESKTOP / "guide", top / "guide")
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_LICENSES"):
            shutil.copy2(ROOT / name, top / name)

        target = out / f"yuo-{version}-desktop.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(top.rglob("*")):
                if path.is_dir():
                    continue
                info = zipfile.ZipInfo.from_file(path, path.relative_to(work).as_posix())
                executable = path.suffix in (".sh", ".command") or path.name == "launcher.py"
                info.external_attr = (0o100755 if executable else 0o100644) << 16  # unzip keeps the x bit
                info.compress_type = zipfile.ZIP_STORED if path.suffix == ".whl" else zipfile.ZIP_DEFLATED
                z.writestr(info, path.read_bytes())
    digest, size = sha256(target), target.stat().st_size
    (out / "SHA256SUMS").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    feed = {
        "version": version,
        "published_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if a.base_url else None,
        "notes_url": a.notes_url,
        "desktop": {"url": f"{a.base_url.rstrip('/')}/{target.name}" if a.base_url else None, "sha256": digest,
                    "bytes": size},
    }  # fmt: skip
    (out / "latest.json").write_text(json.dumps(feed, indent=2) + "\n", encoding="utf-8")
    print(f"{target} ({size / 1e6:.1f} MB, sha256 {digest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
