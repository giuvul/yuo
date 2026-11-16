"""Write THIRD_PARTY_LICENSES: every third-party component Yuo ships, its licence, and the licence texts.

`uv run scripts/third_party_licenses.py` reads the component lists in `sbom/` (Python, the web app and the video
renderer), takes each licence from the installed package (`.venv`, `web/node_modules`, `renderer/node_modules`)
and adds the programs and data files the release bundles beside them (Python, Node.js, ffmpeg, espeak-ng, the
voice model and others). Run it after `uv sync` and `npm ci` in `web/` and `renderer/`; the release workflow does,
and puts the file into the container image and the desktop zip.
"""

import importlib.metadata as md
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "THIRD_PARTY_LICENSES"
LICENSE_FILE = re.compile(r"^(licen[cs]e|copying|notice|unlicense)([.-].*)?$", re.IGNORECASE)
RULE = "=" * 100
# Packages that only install on another platform, so their metadata is not in this environment.
OTHER_PLATFORM = {
    "colorama": "BSD-3-Clause (Windows only)",
    "pywin32-ctypes": "BSD-3-Clause (Windows only)",
    "httpx2-jsfetch": "not shipped (only for Python in a browser)",
}
REMOTION = "Remotion License (https://www.remotion.dev/license)"

# Programs and data shipped beside the libraries: name, version, licence, where, source.
BUNDLED: list[tuple[str, str, str, str, str]] = [
    (
        "CPython (python-build-standalone)",
        "3.14",
        "PSF-2.0 (bundles OpenSSL: Apache-2.0, SQLite: public domain, "
        "and others listed in its own licence files)",
        "server image, desktop app",
        "https://github.com/astral-sh/python-build-standalone",
    ),
    ("uv", "0.13.1", "MIT OR Apache-2.0", "server image, desktop app", "https://github.com/astral-sh/uv"),
    (
        "Node.js",
        "22",
        "MIT (bundles third-party code under its own licences)",
        "server image (video renderer)",
        "https://github.com/nodejs/node/blob/main/LICENSE",
    ),
    (
        "Chrome Headless Shell",
        "as pinned by Remotion",
        "BSD-3-Clause and the licences of Chromium's third-party code",
        "server image (video renderer)",
        "https://source.chromium.org/chromium",
    ),
    (
        "FFmpeg",
        "Debian package",
        "GPL-2.0-or-later (Debian build), run as a separate program, unmodified",
        "server image",
        "https://sources.debian.org/src/ffmpeg/",
    ),
    (
        "espeak-ng",
        "Debian package",
        "GPL-3.0-or-later, run as a separate program, unmodified",
        "server image, desktop app when installed",
        "https://sources.debian.org/src/espeak-ng/",
    ),
    (
        "Kokoro-82M voice model",
        "1.0",
        "Apache-2.0",
        "server image (downloaded on the desktop)",
        "https://huggingface.co/hexgrad/Kokoro-82M",
    ),
    (
        "kokoro-onnx model files",
        "1.0",
        "MIT",
        "server image (downloaded on the desktop)",
        "https://github.com/thewh1teagle/kokoro-onnx",
    ),
    ("tini", "Debian package", "MIT", "server image", "https://github.com/krallin/tini"),
    (
        "Caddy",
        "2.11",
        "Apache-2.0",
        "optional HTTPS container (its own image)",
        "https://github.com/caddyserver/caddy",
    ),
    (
        "Debian",
        "trixie (slim)",
        "the licences of each package, in /usr/share/doc/*/copyright in the image",
        "server image base",
        "https://www.debian.org/legal/licenses/",
    ),
    (
        "Remotion",
        "4",
        "Remotion License: free for individuals, non-profits and companies of up to three people; "
        "larger companies need a company licence",
        "server image (video renderer)",
        "https://www.remotion.dev/license",
    ),
]


def _python() -> list[dict[str, Any]]:
    bom = json.loads((ROOT / "sbom" / "python.cdx.json").read_text(encoding="utf-8"))
    own = bom.get("metadata", {}).get("component", {}).get("name")
    out = []
    for comp in bom.get("components", []):
        name, version = comp["name"], comp.get("version", "")
        if name == own:
            continue
        entry: dict[str, Any] = {
            "name": name,
            "version": version,
            "license": "",
            "texts": [],
            "where": "Python",
        }
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            entry["license"] = OTHER_PLATFORM.get(name, "not installed in this environment")
            out.append(entry)
            continue
        meta = dist.metadata
        lic = meta.get("License-Expression") or ""
        raw = meta.get("License") or ""
        if not lic and raw and raw != "UNKNOWN" and len(raw) < 80 and "\n" not in raw:
            lic = raw
        if not lic:
            classifiers = [
                c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")
            ]
            lic = " / ".join(c for c in classifiers if c != "OSI Approved")
        entry["license"] = lic or "see the licence text"
        for f in dist.files or []:
            if LICENSE_FILE.match(f.name) or "/licenses/" in f"/{f}":
                path = Path(str(dist.locate_file(f)))
                if path.is_file() and path.suffix not in {".py", ".pyc"}:
                    entry["texts"].append((str(f.name), path.read_text(encoding="utf-8", errors="replace")))
        out.append(entry)
    return out


def _npm(project: str, where: str) -> list[dict[str, Any]]:
    bom = json.loads((ROOT / "sbom" / f"{project}.cdx.json").read_text(encoding="utf-8"))
    out = []
    for comp in bom.get("components", []):
        name = f"{comp['group']}/{comp['name']}" if comp.get("group") else comp["name"]
        lics = []
        for item in comp.get("licenses", []):
            lic = item.get("license", {})
            lics.append(item.get("expression") or lic.get("id") or lic.get("name") or "")
        entry: dict[str, Any] = {
            "name": name,
            "version": comp.get("version", ""),
            "texts": [],
            "where": where,
            "license": " AND ".join(x for x in lics if x) or "see the licence text",
        }
        if name == "remotion" or name.startswith("@remotion/"):
            entry["license"] = REMOTION
        pkg = ROOT / project / "node_modules" / name
        if pkg.is_dir():
            for f in sorted(pkg.iterdir()):
                if f.is_file() and LICENSE_FILE.match(f.name):
                    entry["texts"].append((f.name, f.read_text(encoding="utf-8", errors="replace")))
        out.append(entry)
    return out


def build() -> str:
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in [*_python(), *_npm("web", "web app"), *_npm("renderer", "video renderer")]:
        key = (entry["name"].lower(), entry["version"])
        if key in seen:
            if entry["where"] not in seen[key]["where"]:
                seen[key]["where"] += f", {entry['where']}"
            continue
        seen[key] = entry
    entries = sorted(seen.values(), key=lambda e: (e["name"].lower(), e["version"]))

    lines = [
        "THIRD-PARTY SOFTWARE IN YUO",
        "",
        "Yuo is licensed under the Apache License 2.0 (see LICENSE and NOTICE). It includes or runs the",
        "third-party software below, each under its own licence. Programs under the GPL (FFmpeg, espeak-ng) are",
        "shipped unmodified and run only as separate programs; their source code is available from the links",
        "given. Generated by scripts/third_party_licenses.py from the software bill of materials in sbom/.",
        "",
        RULE,
        "PROGRAMS AND DATA SHIPPED WITH YUO",
        RULE,
        "",
    ]
    for name, version, lic, where, src in BUNDLED:
        lines += [f"{name} {version}", f"  Licence: {lic}", f"  Used in: {where}", f"  Source:  {src}", ""]
    lines += [RULE, "LIBRARIES (SUMMARY)", RULE, ""]
    width = max(len(f"{e['name']} {e['version']}") for e in entries) + 2
    for e in entries:
        lines.append(f"{e['name'] + ' ' + e['version']:<{width}}{e['license']}  [{e['where']}]")
    lines += ["", RULE, "LIBRARIES (LICENCE TEXTS)", RULE, ""]
    for e in entries:
        lines += [f"--- {e['name']} {e['version']} ({e['license']}) ---", ""]
        if not e["texts"]:
            lines += ["(No licence file in the package; the licence named above applies.)", ""]
        for fname, text in e["texts"]:
            lines += [f"[{fname}]", text.strip("\n"), ""]
    return "\n".join(line.rstrip() for line in lines).rstrip("\n") + "\n"


def main() -> int:
    text = build()
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.name}: {len(text.splitlines())} lines, {len(text) // 1024} KiB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
