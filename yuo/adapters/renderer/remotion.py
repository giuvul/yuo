"""Remotion renderer adapter: a model-written scene module rendered by Node in a sandbox.

Each call builds a job workspace: a copy of the renderer's `src/` with the module as `src/gen/scene.tsx`, the
timeline and narration in `public/`, and a `node_modules` link to the installed package. Defence in depth:
a static lint and an import allowlist, the TypeScript compile, a CSP in the bundle (renderer/scripts/common.mjs),
self-hosted fonts, and an OS network sandbox around Node: `bwrap` when installed, else a network namespace
(`unshare`). Without a sandbox, agent-coded video is unavailable and the lesson stays a reading lesson.

One render at a time per process, and only with enough free memory and disk (800 MB by default: the measured peak is 576 MB RSS).
A render the system kills mid-way (an OOM killer when another program loads) is retried later, not failed.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from yuo.adapters.renderer import spool
from yuo.core.media import VIDEO_THEMES, MediaError, Narration, Stills, VideoTheme

ALLOWED_IMPORTS = {"react", "remotion", "../kit", "../theme"}
# not a sandbox: a first filter with errors the author can act on (the sandbox and the CSP are the controls)
FORBIDDEN = (
    (r"\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource|navigator\.|sendBeacon", "no network access"),
    (r"\beval\s*\(|new\s+Function\s*\(|\bFunction\s*\(", "no eval or Function()"),
    (r"\bwindow\.|\bdocument\.|globalThis|\blocation\b\s*[.=]", "no window, document or globalThis access"),
    (
        r"Math\.random|Date\.now|new\s+Date\s*\(|performance\.now",
        "no randomness or clock: renders must be deterministic",
    ),
    (
        r"\bsetTimeout\b|\bsetInterval\b|requestAnimationFrame",
        "no timers: animate with useBeats/useCurrentFrame",
    ),
    (
        r"<\s*(img|link|iframe|script|object|embed|video|audio)\b",
        "no <img>, <link>, <iframe>, <script> or media tags",
    ),
    (r"url\s*\(", "no CSS url()"),
    (r"\brequire\s*\(|\bimport\s*\(", "no require() or dynamic import()"),
    (r"dangerouslySetInnerHTML", "no dangerouslySetInnerHTML"),
    # Every colour comes from the theme, so the same module renders in the light and the dark theme
    (
        r"""['"`]#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b|gradient\([^)]*#[0-9a-fA-F]{3}"""
        r"""|\b(?:rgba?|hsla?)\s*\(|['"`](?:white|black)['"`]""",
        "no colour literals (hex, rgb(), hsl(), white, black): use the theme colours C.bg, C.panel, C.text, "
        "C.read and the others, and alpha(C.read, 0.3) from '../theme' for transparency, so the video works in "
        "the light and the dark theme",
    ),
)
# How src/theme.ts picks its palette; a job workspace rewrites this line for the chosen theme.
THEME_LINE = "export {C} from './themes/dark';"
_IMPORT = re.compile(
    r"""^\s*(?:import|export)\b[^'"]*?\bfrom\s*['"]([^'"]+)['"]|^\s*import\s*['"]([^'"]+)['"]""", re.M
)
MIN_FREE_MEM = int(os.environ.get("YUO_RENDER_MIN_FREE_MB", "800")) * 1_000_000  # measured peak 576 MB
MEM_WAIT_S = int(os.environ.get("YUO_RENDER_MEM_WAIT_S", "180"))  # ride out a burst of another service
MIN_FREE_DISK = 5_000_000_000

_one_at_a_time = threading.Lock()


def lint(tsx: str) -> list[str]:
    errors = []
    for m in _IMPORT.finditer(tsx):
        spec = m.group(1) or m.group(2)
        if spec not in ALLOWED_IMPORTS:
            line = tsx[: m.start()].count("\n") + 1
            errors.append(
                f"scene.tsx({line},1): import of {spec!r} is not allowed (only {sorted(ALLOWED_IMPORTS)})"
            )
    for pattern, why in FORBIDDEN:
        for m in re.finditer(pattern, tsx):
            line = tsx[: m.start()].count("\n") + 1
            errors.append(f"scene.tsx({line},1): {why}")
            break
    if "export const SCENES" not in tsx:
        errors.append("scene.tsx: the module must export `SCENES: Record<string, SceneDef>`")
    return errors[:12]


def _free_memory() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return MIN_FREE_MEM


class RemotionRenderer:
    name = "remotion"
    version = "1"

    def __init__(
        self,
        package: Path,
        work_root: Path,
        *,
        node: str = "node",
        chrome: str | None = None,
        chrome_libs: str | None = None,
        sandbox: str = "auto",  # auto, bwrap, unshare, spool (a render container), none (tests only)
        timeout_s: float = 1800,
        heavy_lock: str | None = None,
    ) -> None:
        self.package = package.resolve()
        self.work_root = work_root
        self.node = node
        self.chrome = chrome
        self.chrome_libs = chrome_libs
        self.sandbox = sandbox
        self.timeout_s = timeout_s
        self.heavy_lock = heavy_lock

    # --- availability and the sandbox ---------------------------------------------------------------

    def _sandbox_kind(self) -> str | None:
        if self.sandbox != "auto":
            return self.sandbox
        if shutil.which("bwrap"):
            return "bwrap"
        if shutil.which("unshare") and _unshare_works():
            return "unshare"
        return None

    def available(self) -> str | None:
        if not (self.package / "node_modules" / "remotion").exists():
            return "not_installed"
        if shutil.which(self.node) is None:
            return "no_node"
        if self._sandbox_kind() == "spool":
            return None if spool.worker_alive(self.work_root) else "no_container"
        if self._sandbox_kind() is None:
            return "no_sandbox"  # videos are model-written code: never run without one
        return None

    def _wrap(self, cmd: list[str], ws: Path) -> list[str]:
        kind = self._sandbox_kind()
        if kind == "bwrap":
            return [
                "bwrap", "--unshare-net", "--unshare-pid", "--die-with-parent", "--ro-bind", "/", "/",
                "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--bind", str(ws), str(ws), *cmd,
            ]  # fmt: skip
        if kind == "unshare":
            prefix = ["unshare", "-n"] if os.geteuid() == 0 else ["unshare", "-rn"]
            return [*prefix, "sh", "-c", 'ip link set lo up 2>/dev/null; exec "$@"', "sh", *cmd]
        if kind == "none":
            return cmd
        raise MediaError("no network sandbox available", kind="sandbox")

    # --- workspace ---------------------------------------------------------------------------------

    def _workspace(self, tsx: str, narration: Narration | None, theme: VideoTheme = "dark") -> Path:
        if theme not in VIDEO_THEMES:
            raise MediaError(f"unknown video theme {theme!r}")
        self.work_root.mkdir(parents=True, exist_ok=True)
        ws = Path(tempfile.mkdtemp(prefix="render-", dir=self.work_root))
        shutil.copytree(self.package / "src", ws / "src", ignore=shutil.ignore_patterns("gen"))
        src = (ws / "src" / "theme.ts").read_text(encoding="utf-8")
        if THEME_LINE not in src:
            raise MediaError("src/theme.ts does not pick its palette the expected way")
        (ws / "src" / "theme.ts").write_text(
            src.replace(THEME_LINE, f"export {{C}} from './themes/{theme}';"), encoding="utf-8"
        )
        (ws / "src" / "gen").mkdir()
        (ws / "src" / "gen" / "scene.tsx").write_text(tsx, encoding="utf-8")
        (ws / "node_modules").symlink_to(self.package / "node_modules")
        shutil.copy(self.package / "tsconfig.json", ws / "tsconfig.json")
        (ws / "public").mkdir()
        if narration is not None:
            shutil.copy(narration.wav, ws / "public" / "narration.wav")
            (ws / "public" / "timeline.json").write_text(
                json.dumps(narration.timeline.to_json()), encoding="utf-8"
            )
        return ws

    def env(self) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "NODE_OPTIONS": "--max-old-space-size=1024",
        }
        if self.chrome:
            env["YUO_CHROME"] = self.chrome
        if self.chrome_libs:
            env["LD_LIBRARY_PATH"] = self.chrome_libs
        return env

    def _run(self, cmd: list[str], ws: Path, timeout: float) -> subprocess.CompletedProcess[str]:
        if self._sandbox_kind() == "spool":
            return spool.submit(self.work_root, ws, cmd, timeout)
        try:
            return subprocess.run(
                self._wrap(cmd, ws),
                cwd=ws,
                env=self.env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise MediaError(f"render timed out after {timeout:.0f} s", kind="timeout") from e

    def _guard(self) -> None:
        deadline = time.monotonic() + MEM_WAIT_S
        while (
            _free_memory() < MIN_FREE_MEM
        ):  # wait a little for another job to finish, then give the slot back
            if time.monotonic() > deadline:
                raise MediaError("not enough free memory to render now", retryable=True, kind="resources")
            time.sleep(5)
        if shutil.disk_usage(self.work_root).free < MIN_FREE_DISK:
            raise MediaError("less than 5 GB of free disk", retryable=True, kind="resources")

    # --- the port ----------------------------------------------------------------------------------

    def kit(self, theme: VideoTheme = "dark") -> dict[str, str]:
        """The kit and theme sources the author writes against (they go into the author's prompt): the theme is
        src/theme.ts with the chosen palette in place of its re-export, as the scene module will see it."""
        src = self.package / "src"
        palette = (src / "themes" / f"{theme}.ts").read_text(encoding="utf-8")
        theme_ts = (src / "theme.ts").read_text(encoding="utf-8").replace(THEME_LINE, palette.strip())
        return {"kit": (src / "kit.tsx").read_text(encoding="utf-8"), "theme": theme_ts}

    def check(self, tsx: str) -> list[str]:
        errors = lint(tsx)
        if errors:
            return errors
        ws = self._workspace(tsx, None)
        try:
            tsc = self.package / "node_modules" / "typescript" / "bin" / "tsc"
            p = subprocess.run(
                [self.node, str(tsc), "--noEmit", "-p", "tsconfig.json"],
                cwd=ws, env=self.env(), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
            )  # fmt: skip
            out = (p.stdout + p.stderr).strip()
            if p.returncode == 0:
                return []
            lines = [ln for ln in out.splitlines() if "error TS" in ln]
            mine = [ln.replace("src/gen/scene.tsx", "scene.tsx") for ln in lines if "src/gen/scene.tsx" in ln]
            return (mine or lines or [out[-500:]])[:12]
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def stills(self, tsx: str, narration: Narration, out: Path, theme: VideoTheme = "dark") -> Stills:
        with _one_at_a_time, self._heavy():
            self._guard()
            ws = self._workspace(tsx, narration, theme)
            try:
                p = self._run(
                    [self.node, str(self.package / "scripts" / "stills.mjs"), str(ws), str(ws / "stills")],
                    ws,
                    self.timeout_s,
                )
                _check(p)
                if out.exists():
                    shutil.rmtree(out)
                shutil.copytree(ws / "stills", out)
            finally:
                shutil.rmtree(ws, ignore_errors=True)
        probe = json.loads((out / "probe.json").read_text(encoding="utf-8"))
        return Stills(out, tuple(sorted(out.glob("sheet_*.jpg"))), probe)

    def render(self, tsx: str, narration: Narration, out: Path, theme: VideoTheme = "dark") -> float:
        with _one_at_a_time, self._heavy():
            self._guard()
            ws = self._workspace(tsx, narration, theme)
            t0 = time.monotonic()
            try:
                p = self._run(
                    [self.node, str(self.package / "scripts" / "render.mjs"), str(ws), str(ws / "out.mp4")],
                    ws,
                    self.timeout_s,
                )
                _check(p)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(ws / "out.mp4", out)
            finally:
                shutil.rmtree(ws, ignore_errors=True)
        return time.monotonic() - t0

    def _heavy(self) -> _Flock:
        return _Flock(self.heavy_lock)


class _Flock:
    """An optional machine-wide lock (the dev VPS runs one heavy job at a time)."""

    def __init__(self, path: str | None) -> None:
        self.path = path
        self.fh: object | None = None

    def __enter__(self) -> None:
        if self.path:
            import fcntl

            fh = Path(self.path).open("w", encoding="utf-8")
            fcntl.flock(fh, fcntl.LOCK_EX)
            self.fh = fh

    def __exit__(self, *_: object) -> None:
        if self.fh is not None:
            self.fh.close()  # type: ignore[attr-defined]


def _check(p: subprocess.CompletedProcess[str]) -> None:
    """A renderer the system stopped (an OOM killer, a shutdown) is retried later; any other exit fails."""
    if p.returncode < 0 or p.returncode in (128 + signal.SIGKILL, 128 + signal.SIGTERM):
        raise MediaError(
            f"the system stopped the renderer (signal {abs(p.returncode) % 128}), likely short of memory",
            retryable=True, kind="resources",
        )  # fmt: skip
    if p.returncode != 0:
        raise MediaError(_tail(p), kind="render")


def _tail(p: subprocess.CompletedProcess[str]) -> str:
    text = (p.stderr or "") + (p.stdout or "")
    return text.strip()[-1200:] or f"renderer exited with {p.returncode}"


def _unshare_works() -> bool:
    cmd = ["unshare", "-n", "true"] if os.geteuid() == 0 else ["unshare", "-rn", "true"]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=10).returncode == 0
    except OSError, subprocess.TimeoutExpired:
        return False
