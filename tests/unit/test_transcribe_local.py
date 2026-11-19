"""The local transcriber reads the runner's lines, reports progress and turns a crash into a read error."""

from pathlib import Path

import pytest

from yuo.adapters.transcribe.local import PACKAGE, LocalWhisper
from yuo.core.documents import ReadError


def fake_env(root: Path, script: str) -> LocalWhisper:
    py = root / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\ncat > /dev/null\n" + script)
    py.chmod(0o755)
    (root / "installed.txt").write_text(PACKAGE + "\n")
    return LocalWhisper(root, decoder="/usr/bin/decoder")


def test_segments_and_progress(tmp_path: Path) -> None:
    w = fake_env(
        tmp_path,
        "echo '{\"duration\": 20.0}'\n"
        "echo 'some noise'\n"
        'echo \'{"segment": [0, 9000, " First part."]}\'\n'
        "echo '{\"done\": 9000}'\n"
        'echo \'{"segment": [9000, 20000, " Second part."]}\'\n'
        "echo '{\"done\": 20000}'\n",
    )
    seen: list[float] = []
    out = w.transcribe(
        tmp_path / "a.ogg", lang="it-IT", prompt="derivata", progress=seen.append, duration_ms=20_000
    )
    assert [(s.start_ms, s.end_ms, s.text) for s in out] == [
        (0, 9000, " First part."),
        (9000, 20000, " Second part."),
    ]
    assert seen == [0.45, 0.99, 1.0]


def test_a_crash_is_a_read_error_with_the_reason(tmp_path: Path) -> None:
    w = fake_env(tmp_path, "echo 'out of memory' >&2\nexit 3\n")
    with pytest.raises(ReadError, match="out of memory"):
        w.transcribe(tmp_path / "a.ogg", lang=None, prompt="", progress=lambda _: None)


def test_without_ffmpeg_it_says_why(tmp_path: Path) -> None:
    w = LocalWhisper(tmp_path, decoder=None)
    assert w.available() is not None
