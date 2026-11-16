"""The desktop launcher (packaging/desktop/launcher.py): the parts that differ between operating systems."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

LAUNCHER = Path(__file__).parents[2] / "packaging" / "desktop" / "launcher.py"


def load(home: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("YUO_HOME", str(home))
    spec = importlib.util.spec_from_file_location("yuo_launcher", LAUNCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Proc:
    pid = 111  # on Windows the launcher starts a small exe in front of Python: not the pid Yuo writes

    def poll(self) -> None:
        return None


def test_a_start_is_ready_by_its_launch_id_not_its_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = load(tmp_path, monkeypatch)
    info: dict[str, Any] = {"url": "http://127.0.0.1:1", "pid": 222, "version": "1.0.0", "launch": "abc"}
    monkeypatch.setattr(launcher, "running", lambda: info)
    assert launcher.wait_ready(Proc(), "1.0.0", "abc") is True
    monkeypatch.setattr(launcher, "READY_TIMEOUT_S", 0)
    assert launcher.wait_ready(Proc(), "1.0.0", "other") is False


def test_a_first_install_that_failed_is_tried_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """0.7.0 on Windows: a first start judged failed was marked so, and the next start had nothing to run."""
    (tmp_path / "home").mkdir()
    launcher = load(tmp_path / "home", monkeypatch)
    app = tmp_path / "app"
    app.mkdir()
    (app / "release.json").write_text(json.dumps({"version": "1.0.0", "python": "3.14", "wheel": "yuo.whl"}))
    (app / "yuo.whl").write_text("")
    monkeypatch.setattr(launcher, "APP", app)
    launcher.mark_failed("1.0.0")
    installed: list[Path] = []

    def install(source: Path) -> str:
        installed.append(source)
        raise RuntimeError("stop here")

    monkeypatch.setattr(launcher, "install", install)
    monkeypatch.setattr(launcher, "running", lambda: None)
    assert launcher.main() == 1
    assert installed == [app]
