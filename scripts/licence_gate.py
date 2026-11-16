"""Licence gate: in-process dependencies must carry a permissive or LGPL licence.

Python: the runtime dependencies from `uv.lock` (dev tools are not shipped), licences read from the
installed metadata. Web and renderer: the non-dev packages of their `package-lock.json`. GPL/AGPL programs that Yuo only
runs as separate executables (ffmpeg, espeak-ng) are not Python or npm dependencies and are out of scope.
"""

import json
import re
import subprocess
import sys
import urllib.request
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ALLOWED = {
    "MIT",
    "MIT-0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "0BSD",
    "ISC",
    "Apache-2.0",
    "PSF-2.0",
    "Python-2.0",
    "Unlicense",
    "CC0-1.0",
    "Zlib",
    "MPL-2.0",
    "BlueOak-1.0.0",
    "CC-BY-4.0",
    "LGPL-2.1-only",
    "LGPL-2.1-or-later",
    "LGPL-3.0-only",
    "LGPL-3.0-or-later",
}
# Free-form classifier and License: values seen in the wild, mapped to SPDX.
ALIASES = {
    "MIT License": "MIT",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "BSD License": "BSD-3-Clause",
    "Apache Software License": "Apache-2.0",
    "Apache License 2.0": "Apache-2.0",
    "Apache 2.0": "Apache-2.0",
    "ISC License (ISCL)": "ISC",
    "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "BSD": "BSD-3-Clause",
    "Apache-2.0 OR BSD-2-Clause": "Apache-2.0",
    "MIT OR Apache-2.0": "MIT",
    "Apache-2.0 OR MIT": "MIT",
    "3-Clause BSD License": "BSD-3-Clause",
    "GNU Library or Lesser General Public License (LGPL)": "LGPL-2.1-or-later",
    "CNRI-Python": "Python-2.0",
}
DENIED_PACKAGES = re.compile(
    r"^(pymupdf|fitz|phonemizer.*|espeakng-loader|piper-tts|rfc3987|av|imageio-ffmpeg)$"
)
DENIED_LICENCE = re.compile(r"\b(A?GPL|GNU General Public|Affero)\b(?!.*Lesser)", re.IGNORECASE)


def _spdx(raw: str) -> str:
    raw = raw.strip()
    return ALIASES.get(raw, raw)


def python_runtime() -> list[tuple[str, str]]:
    out = subprocess.run(
        ["uv", "export", "--no-dev", "--no-hashes", "--no-emit-project", "--format", "requirements.txt"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pins = [
        line.split(";")[0].strip().split("==")
        for line in out.splitlines()
        if "==" in line and not line.lstrip().startswith("#")
    ]
    result = []
    for name, version in pins:
        try:
            meta = metadata.metadata(name)
            expr, classifiers, raw = (
                meta.get("License-Expression"),
                meta.get_all("Classifier") or [],
                meta.get("License"),
            )
        except metadata.PackageNotFoundError:
            # a dependency for another platform (Windows, macOS): read its metadata from PyPI
            expr, classifiers, raw = _pypi(name, version)
        if not expr:
            lic = [c.split(" :: ")[-1] for c in classifiers if c.startswith("License ::")]
            expr = " OR ".join(lic) if lic else (raw or "UNKNOWN")
        result.append((name, expr))
    return result


def _pypi(name: str, version: str) -> tuple[str | None, list[str], str | None]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=30) as r:
        info = json.load(r)["info"]
    return info.get("license_expression"), info.get("classifiers") or [], info.get("license")


# Named exceptions, each with its decision. Remotion: its own licence (a company licence above a size threshold);
# Yuo shows the notice at onboarding and the responsibility stays with the installing user.
EXCEPTIONS = {
    re.compile(r"^(remotion|@remotion/[a-z0-9-]+)$"): "Remotion licence, notice at onboarding",
}
# Fonts are bundled assets, not code: the SIL Open Font License allows bundling them with software.
FONT_LICENCES = {"OFL-1.1"}


def npm_runtime(package_dir: str) -> list[tuple[str, str]]:
    lock = ROOT / package_dir / "package-lock.json"
    if not lock.exists():
        return []
    packages = json.loads(lock.read_text(encoding="utf-8"))["packages"]
    return [
        (key.removeprefix("node_modules/").split("node_modules/")[-1], str(p.get("license", "UNKNOWN")))
        for key, p in packages.items()
        if key and not p.get("dev") and not p.get("devOptional")
    ]


def verdict(name: str, licence: str) -> str | None:
    if DENIED_PACKAGES.match(name.lower()):
        return "denied package (in-process GPL/AGPL)"
    # an OR picks one allowed option; every part of an AND must be allowed (numpy, regex, tqdm)
    options = [o for o in re.split(r"\s+OR\s+", _spdx(licence).strip("() ")) if o.strip()]
    for option in options:
        parts = [_spdx(p) for p in re.split(r"\s+AND\s+", option.strip("() ")) if p.strip()]
        if parts and all(p in ALLOWED for p in parts):
            return None
    if DENIED_LICENCE.search(licence):
        return "GPL/AGPL in process"
    return "licence not on the allowlist"


def main() -> int:
    problems = []
    checked = 0
    ecosystems = (
        ("python", python_runtime()),
        ("web", npm_runtime("web")),
        ("renderer", npm_runtime("renderer")),
    )
    for ecosystem, deps in ecosystems:
        for name, licence in deps:
            checked += 1
            if any(rx.match(name) for rx in EXCEPTIONS):
                continue
            if name.startswith(("@fontsource/", "@fontsource-variable/")) and licence in FONT_LICENCES:
                continue
            if (why := verdict(name, licence)) is not None:
                problems.append(f"{ecosystem}: {name} ({licence}): {why}")
    for p in problems:
        print(p)
    print(f"licence gate: {checked} packages, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
