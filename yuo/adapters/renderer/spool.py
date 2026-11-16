"""Renders through a render container with no network: the spool between the two containers.

In a container the app cannot make a network namespace (no privileges), so model-written scene code runs in a
second container started with `network_mode: none` that shares the render work folder at the same path. The app
writes `job.json` into a render workspace and marks it ready; the worker (`yuo render-worker`) takes it, runs
the command and writes `result.json` (exit code, output). The worker runs only the renderer's own scripts on a
workspace inside the spool, so the shared folder cannot make it run anything else. A heartbeat file says the
worker is up; without it renders are refused as a resource problem and retried later.
"""

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import structlog

from yuo.core.media import MediaError

log = structlog.get_logger(__name__)
HEARTBEAT = ".render-worker"
ALIVE_S = 30
BEAT_S = 5
SCRIPTS = ("stills.mjs", "render.mjs")


def worker_alive(spool: Path) -> bool:
    try:
        return time.time() - (spool / HEARTBEAT).stat().st_mtime < ALIVE_S
    except OSError:
        return False


def _write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def submit(spool: Path, ws: Path, cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Hand one command to the render container and wait for its result."""
    if not worker_alive(spool):
        raise MediaError("the render container is not running", retryable=True, kind="resources")
    _write(ws / "job.json", {"argv": cmd, "timeout": timeout})
    (ws / ".ready").touch()
    deadline = time.monotonic() + timeout + 120
    result = ws / "result.json"
    while not result.exists():
        if time.monotonic() > deadline or not worker_alive(spool):
            raise MediaError("the render container stopped answering", retryable=True, kind="resources")
        time.sleep(0.5)
    r = json.loads(result.read_text(encoding="utf-8"))
    if r.get("timed_out"):
        raise MediaError(f"render timed out after {timeout:.0f} s", kind="timeout")
    return subprocess.CompletedProcess(cmd, int(r["returncode"]), r.get("stdout", ""), r.get("stderr", ""))


def _allowed(argv: list[str], ws: Path, package: Path, node: str) -> bool:
    return (
        len(argv) >= 3
        and argv[0] == node
        and argv[1] in {str(package / "scripts" / s) for s in SCRIPTS}
        and all(Path(a).resolve().is_relative_to(ws) for a in argv[2:])
    )


def serve(
    spool: Path, package: Path, env: dict[str, str], *, node: str = "node", poll_s: float = 0.5
) -> None:
    """The render container's loop: one job at a time, forever."""
    spool.mkdir(parents=True, exist_ok=True)
    root, package = spool.resolve(), package.resolve()
    log.info("render_worker.started", spool=str(root))
    # the heartbeat beats on its own thread, so it keeps going while a render runs: from the loop alone it
    # stopped for the whole render, and the app gave up on every render longer than ALIVE_S
    # ("the render container stopped answering" after 10+ minutes of retries)
    threading.Thread(target=_beat, args=(root,), daemon=True, name="render-heartbeat").start()
    while True:
        for ready in sorted(root.glob("render-*/.ready")):
            ws = ready.parent.resolve()
            taken = ws / ".taken"
            try:
                ready.rename(taken)
            except OSError:
                continue
            try:
                run_one(ws, root, package, env, node)
            except Exception:  # the workspace went away under the job: the worker carries on
                log.exception("render_worker.lost_workspace", workspace=ws.name)
        time.sleep(poll_s)


def _beat(root: Path) -> None:
    while True:
        try:
            (root / HEARTBEAT).touch()
        except OSError:
            log.warning("render_worker.heartbeat_failed")
        time.sleep(BEAT_S)


def run_one(ws: Path, root: Path, package: Path, env: dict[str, str], node: str) -> None:
    out = ws / "result.json"
    try:
        job = json.loads((ws / "job.json").read_text(encoding="utf-8"))
        argv = [str(a) for a in job["argv"]]
        if not ws.is_relative_to(root) or not _allowed(argv, ws, package, node):
            _write(out, {"returncode": 126, "stderr": "refused: not a render command for this workspace"})
            log.warning("render_worker.refused", workspace=ws.name)
            return
        try:
            p = subprocess.run(
                argv,
                cwd=ws,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=float(job["timeout"]),
            )
        except subprocess.TimeoutExpired:
            _write(out, {"returncode": -9, "timed_out": True})
            return
        _write(out, {"returncode": p.returncode, "stdout": p.stdout[-20000:], "stderr": p.stderr[-20000:]})
    except Exception as e:  # a bad job must not stop the worker
        log.exception("render_worker.failed", workspace=ws.name)
        if ws.is_dir():  # gone when the app gave up on it: nobody waits for the result then
            _write(out, {"returncode": 125, "stderr": f"render worker: {type(e).__name__}: {e}"})
    finally:
        (ws / ".taken").unlink(missing_ok=True)
