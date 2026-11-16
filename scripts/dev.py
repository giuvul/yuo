"""Developer setup and run in one command: `uv run scripts/dev.py` (Linux, macOS, Windows).

Installs the locked Python and JS dependencies, migrates a dev database under `.dev/`, then runs the API
(uvicorn, one worker, reload) and Vite side by side until Ctrl+C. The demo path seed arrives with M1.
"""

import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
DATA = ROOT / ".dev"


def run(cmd: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def main() -> int:
    run(["uv", "sync", "--locked"])
    npm = shutil.which("npm")
    if npm is None:
        print("npm not found: install Node.js LTS to run the web UI", file=sys.stderr)
        return 1
    if not (WEB / "node_modules").exists():
        # 7-day cooldown, as for Python; install scripts stay off (web/.npmrc)
        before = (dt.datetime.now(dt.UTC) - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        run([npm, "ci", f"--before={before}"], WEB)
    env = os.environ | {"YUO_DATA_DIR": str(DATA), "YUO_LOG_FORMAT": "console"}
    run(["uv", "run", "python", "-c", "from yuo.main import build; build()"], env=env)  # migrate first
    api = subprocess.Popen(
        ["uv", "run", "uvicorn", "yuo.main:app", "--reload", "--workers", "1", "--port", "18765"],
        cwd=ROOT,
        env=env,
    )
    web = subprocess.Popen([npm, "run", "dev"], cwd=WEB, env=env)
    try:
        return api.wait() or web.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        for p in (api, web):
            p.terminate()


if __name__ == "__main__":
    sys.exit(main())
