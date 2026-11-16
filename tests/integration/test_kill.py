"""An event the server acknowledged survives the server being killed (SIGKILL) mid-sync.

A real `yuo serve` child process on a prepared install; two signed-in devices send lesson events in batches
while the server is killed at an arbitrary moment, then restarted. Every acknowledged event must be stored once,
and the batch cut off by the kill, sent again as the outbox does, ends up stored once too.
"""

import os
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests import fakes
from tests.integration.test_slice import NoPrices, create, lessons_of
from yuo.core import clock
from yuo.core.ids import new_id
from yuo.db.migrate import migrate
from yuo.main import start

CSRF = {"X-Yuo-Request": "1"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Server:
    def __init__(self, root: Path, port: int) -> None:
        self.root, self.port = root, port
        self.url = f"http://localhost:{port}"
        self.proc: subprocess.Popen[str] | None = None
        self.err: list[str] = []

    def start(self) -> None:
        env = os.environ | {
            "YUO_DATA_DIR": str(self.root),
            "YUO_ORIGIN": self.url,
            "YUO_LOG_LEVEL": "WARNING",
        }
        env.pop("YUO_SECRET_OPENROUTER_FILE", None)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "yuo.cli", "serve", "--port", str(self.port)],
            env=env, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True,
        )  # fmt: skip
        assert self.proc.stderr is not None
        threading.Thread(target=lambda: self.err.extend(self.proc.stderr), daemon=True).start()  # type: ignore[union-attr, arg-type]
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{self.url}/api/health", timeout=1).status_code == 200:
                    return
            except httpx.TransportError:
                time.sleep(0.2)
        raise AssertionError("server did not start:\n" + "".join(self.err[-30:]))

    def kill(self) -> None:
        assert self.proc is not None
        self.proc.send_signal(signal.SIGKILL)
        self.proc.wait(timeout=10)

    def setup_code(self) -> str:
        found = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4})\b", "".join(self.err))
        assert found, "".join(self.err)
        return found[1]


@pytest.fixture
def install(tmp_path: Path) -> Iterator[tuple[Server, str]]:
    """An install with one ready lesson, made in-process with the scripted model, then served for real."""
    db = tmp_path / "yuo.db"
    migrate(db, "test")
    rt = start(db, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False)
    for role in ("generator", "reviewer", "grader", "utility"):
        rt.service.bind(role, "openrouter", "deepseek/deepseek-v4-pro")
    lesson = lessons_of(rt, create(rt))[0]
    version = rt.service.lesson_view(lesson["id"])["version_id"]
    rt.close()
    server = Server(tmp_path, free_port())
    server.start()
    try:
        yield server, version
    finally:
        if server.proc and server.proc.poll() is None:
            server.kill()


def events(version: str, n: int) -> list[dict[str, Any]]:
    return [
        {"id": new_id(), "type": "lesson.started", "device_at": clock.now(), "tz": "UTC",
         "payload": {"lesson_version_id": version, "seconds": 30}}
        for _ in range(n)
    ]  # fmt: skip


def test_acknowledged_events_survive_a_kill(install: tuple[Server, str]) -> None:
    server, version = install
    laptop = httpx.Client(base_url=server.url, headers=CSRF, timeout=10)
    assert (
        laptop.post(
            "/api/auth/setup", json={"code": server.setup_code(), "device_label": "laptop"}
        ).status_code
        == 200
    )
    assert laptop.put("/api/auth/password", json={"password": "correct horse battery"}).status_code == 204
    phone = httpx.Client(base_url=server.url, headers=CSRF, timeout=10)
    assert (
        phone.post(
            "/api/auth/sign-in/password", json={"password": "correct horse battery", "device_label": "phone"}
        ).status_code
        == 200
    )

    acked: set[str] = set()
    pending: list[dict[str, Any]] = []  # sent, answer not received: the outbox keeps them
    killed = threading.Event()

    def kill() -> None:
        server.kill()
        killed.set()

    threading.Timer(1.5, kill).start()
    clients = [laptop, phone]
    i = 0
    while not killed.is_set() or pending == []:
        batch = events(version, 25)
        try:
            r = clients[i % 2].post("/api/events", json={"device_id": "x", "events": batch})
        except httpx.TransportError:
            pending = batch
            break
        assert r.status_code == 200 and not r.json()["rejected"], r.text
        acked |= set(r.json()["accepted"]) | set(r.json()["duplicates"])
        i += 1
        if killed.is_set():
            break
    assert killed.wait(10) and len(acked) >= 50

    server.start()  # same install, the lock was released by the kill
    if pending:
        r = laptop.post("/api/events", json={"device_id": "x", "events": pending})  # the session survived
        assert r.status_code == 200, r.text
        acked |= set(r.json()["accepted"]) | set(r.json()["duplicates"])
    server.kill()

    c = sqlite3.connect(server.root / "yuo.db")
    stored = {
        r[0]: r[1]
        for r in c.execute("SELECT id, device_id FROM learning_event WHERE type = 'lesson.started'")
    }
    devices = dict(c.execute("SELECT id, label FROM device").fetchall())
    c.close()
    assert acked <= stored.keys(), f"{len(acked - stored.keys())} acknowledged events lost"
    assert {e["id"] for e in pending} <= stored.keys()
    assert {devices[d] for d in stored.values()} == {
        "laptop",
        "phone",
    }  # each device's events under its own id
