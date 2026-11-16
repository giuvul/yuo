"""The render container's spool: jobs run by the worker, anything else refused, a missing worker retried."""

import os
import shutil
import threading
from pathlib import Path

import pytest

from yuo.adapters.renderer import spool
from yuo.core.media import MediaError

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def package(tmp_path: Path) -> Path:
    pkg = tmp_path / "renderer"
    (pkg / "scripts").mkdir(parents=True)
    (pkg / "scripts" / "stills.mjs").write_text(
        "import fs from 'node:fs'; fs.writeFileSync(process.argv[3], 'ok:' + process.argv[2]); console.log('done')"
    )
    return pkg


def test_a_job_goes_through_the_worker_and_others_are_refused(tmp_path: Path) -> None:
    pkg, root = package(tmp_path), tmp_path / "render"
    root.mkdir()
    node = shutil.which("node") or "node"
    threading.Thread(
        target=spool.serve,
        args=(root, pkg, dict(os.environ)),
        kwargs={"node": node, "poll_s": 0.05},
        daemon=True,
    ).start()
    ws = root / "render-1"
    ws.mkdir()
    for _ in range(100):
        if spool.worker_alive(root):
            break
        threading.Event().wait(0.05)
    p = spool.submit(root, ws, [node, str(pkg / "scripts" / "stills.mjs"), str(ws), str(ws / "out.txt")], 30)
    assert p.returncode == 0 and "done" in p.stdout and (ws / "out.txt").read_text() == f"ok:{ws}"

    other = root / "render-2"
    other.mkdir()
    for argv in (
        ["sh", "-c", "touch /tmp/pwned"],  # not node
        [node, str(pkg / "scripts" / "evil.mjs"), str(other)],  # not the renderer's script
        [node, str(pkg / "scripts" / "stills.mjs"), "/etc", str(other / "x")],  # outside the workspace
    ):
        (other / "result.json").unlink(missing_ok=True)
        assert spool.submit(root, other, argv, 30).returncode == 126


def test_no_worker_means_retry_later(tmp_path: Path) -> None:
    ws = tmp_path / "render-1"
    ws.mkdir(parents=True)
    with pytest.raises(MediaError) as e:
        spool.submit(tmp_path, ws, ["node"], 5)
    assert e.value.retryable and e.value.kind == "resources"


def test_the_heartbeat_goes_on_during_a_long_render_and_a_lost_workspace_does_not_stop_the_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A render longer than ALIVE_S was given up as "stopped answering", its workspace
    removed, and the worker crashed writing the result into it."""
    monkeypatch.setattr(spool, "ALIVE_S", 1.0)
    monkeypatch.setattr(spool, "BEAT_S", 0.1)
    pkg, root = package(tmp_path), tmp_path / "render"
    root.mkdir()
    (pkg / "scripts" / "render.mjs").write_text(
        "import fs from 'node:fs'; setTimeout(() => fs.writeFileSync(process.argv[3], 'slow'), 2500)"
    )
    node = shutil.which("node") or "node"
    threading.Thread(
        target=spool.serve,
        args=(root, pkg, dict(os.environ)),
        kwargs={"node": node, "poll_s": 0.05},
        daemon=True,
    ).start()
    for _ in range(100):
        if spool.worker_alive(root):
            break
        threading.Event().wait(0.05)
    ws = root / "render-slow"
    ws.mkdir()
    cmd = [node, str(pkg / "scripts" / "render.mjs"), str(ws), str(ws / "out.txt")]
    p = spool.submit(root, ws, cmd, 30)  # 2.5 s, well past ALIVE_S
    assert p.returncode == 0 and (ws / "out.txt").read_text() == "slow"

    gone = root / "render-gone"
    gone.mkdir()
    spool._write(gone / "job.json", {"argv": ["node", "nothing"], "timeout": 5})
    (gone / ".ready").touch()
    threading.Event().wait(0.02)
    shutil.rmtree(gone, ignore_errors=True)  # the app gave up and cleaned up
    threading.Event().wait(0.5)
    again = root / "render-again"
    again.mkdir()
    p = spool.submit(
        root, again, [node, str(pkg / "scripts" / "stills.mjs"), str(again), str(again / "o.txt")], 30
    )
    assert p.returncode == 0  # the worker is still there
