"""Software bill of materials for the shipped dependencies (CycloneDX 1.5), kept in `sbom/`.

`uv run scripts/sbom.py` rewrites the files; `--check` fails when they no longer match the lockfiles, so
every dependency change shows up as an SBOM diff in review. Volatile fields (serial number, timestamps)
are dropped to keep the files stable.
"""

import difflib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sbom"


def _stable(doc: dict[str, Any]) -> str:
    doc.pop("serialNumber", None)
    meta = doc.get("metadata", {})
    meta.pop("timestamp", None)
    meta.pop("tools", None)
    doc.get("components", []).sort(key=lambda c: (c.get("name", ""), c.get("version", "")))
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def python_sbom() -> str:
    out = subprocess.run(
        ["uv", "export", "--no-dev", "--format", "cyclonedx1.5"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return _stable(json.loads(out))


def npm_sbom(package_dir: str) -> str:
    out = subprocess.run(
        ["npm", "sbom", "--omit", "dev", "--sbom-format", "cyclonedx", "--package-lock-only"],
        cwd=ROOT / package_dir,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return _stable(json.loads(out))


def main() -> int:
    check = "--check" in sys.argv
    OUT.mkdir(exist_ok=True)
    failed = False
    builds = (
        ("python.cdx.json", python_sbom),
        ("web.cdx.json", lambda: npm_sbom("web")),
        ("renderer.cdx.json", lambda: npm_sbom("renderer")),
    )
    for name, build in builds:
        fresh, target = build(), OUT / name
        if not check:
            target.write_text(fresh, encoding="utf-8")
            print(f"wrote {target.relative_to(ROOT)}")
            continue
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        if old != fresh:
            failed = True
            diff = difflib.unified_diff(
                old.splitlines(), fresh.splitlines(), str(target), "lockfile", lineterm="", n=1
            )
            print("\n".join(list(diff)[:60]))
            print(f"{target.relative_to(ROOT)} is out of date: run `uv run scripts/sbom.py`")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
