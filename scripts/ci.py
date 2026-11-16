"""Every check in one command: `uv run scripts/ci.py` (the GitHub workflow runs exactly this).

`--fast` skips the web build and the SBOM diff. Steps whose tool is missing locally fail, except the
browser tests (Playwright, against the real backend on a scripted model), which are skipped with a notice
until the Chromium build is installed (`npx playwright install --only-shell chromium`).
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

PY = [
    ("ruff lint", ["uv", "run", "ruff", "check", "yuo", "scripts", "tests"], ROOT),
    ("ruff format", ["uv", "run", "ruff", "format", "--check", "yuo", "scripts", "tests"], ROOT),
    ("mypy strict", ["uv", "run", "mypy"], ROOT),
    ("import contracts", ["uv", "run", "lint-imports"], ROOT),
    ("schema generated", ["uv", "run", "scripts/gen_schema.py", "--check"], ROOT),
    ("openapi exported", ["uv", "run", "scripts/export_openapi.py", "--check"], ROOT),
    ("package schemas", ["uv", "run", "scripts/gen_package_schemas.py", "--check"], ROOT),
    ("pytest", ["uv", "run", "pytest"], ROOT),
    ("licence gate", ["uv", "run", "scripts/licence_gate.py"], ROOT),
]
WEB_STEPS = [
    ("web api types", ["uv", "run", "scripts/check_api_types.py"], ROOT),
    ("web tokens", ["npm", "run", "tokens:check"], WEB),
    ("web typecheck", ["npm", "run", "typecheck"], WEB),
    ("web i18n keys", ["npm", "run", "i18n:check"], WEB),
    ("web unit tests", ["npm", "test"], WEB),
    ("renderer typecheck", ["npm", "run", "typecheck"], ROOT / "renderer"),
]
SLOW = [
    ("web build", ["npm", "run", "build"], WEB),
    ("sbom diff", ["uv", "run", "scripts/sbom.py", "--check"], ROOT),
]


def playwright_ready() -> bool:
    """True when the Chromium build this Playwright version needs is installed (not just any build)."""
    manifest = WEB / "node_modules" / "playwright-core" / "browsers.json"
    if not manifest.exists():
        return False
    browsers = json.loads(manifest.read_text(encoding="utf-8"))["browsers"]
    rev = next(b["revision"] for b in browsers if b["name"] == "chromium-headless-shell")
    cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", Path.home() / ".cache" / "ms-playwright"))
    return (cache / f"chromium_headless_shell-{rev}").exists()


def main() -> int:
    fast = "--fast" in sys.argv
    steps = PY + WEB_STEPS + ([] if fast else SLOW)
    if not fast and playwright_ready():
        steps.append(("browser tests", ["npm", "run", "test:e2e"], WEB))
    results = []
    for name, cmd, cwd in steps:
        if shutil.which(cmd[0]) is None:
            results.append((name, False, 0.0))
            print(f"== {name}: {cmd[0]} not found")
            continue
        print(f"== {name}", flush=True)
        start = time.monotonic()
        ok = subprocess.run(cmd, cwd=cwd, check=False).returncode == 0
        results.append((name, ok, time.monotonic() - start))
    print("\nsummary")
    for name, ok, secs in results:
        print(f"  {'ok  ' if ok else 'FAIL'} {name} ({secs:.1f}s)")
    if not fast and not playwright_ready():
        print("  skip browser tests (no Chromium for this Playwright version)")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
