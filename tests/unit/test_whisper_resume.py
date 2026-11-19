"""The local transcriber keeps each finished window, and goes on from there after it was stopped."""

import os
import sys
from pathlib import Path

import pytest

from yuo.adapters.transcribe import local
from yuo.core.documents import TranscriptionInterrupted

# stands in for whisper_runner.py: two windows of 300 s; the first run is killed during the second window
FAKE_RUNNER = """
import json, os, signal, sys
a = json.loads(sys.stdin.read())
print(json.dumps({"duration": a["duration"]}), flush=True)
pos = a["start"]
if pos == 0:
    print(json.dumps({"segment": [0, 4000, "first"]}), flush=True)
    print(json.dumps({"done": 300000}), flush=True)
    print(json.dumps({"segment": [300000, 304000, "lost"]}), flush=True)
    os.kill(os.getpid(), signal.SIGKILL)
assert pos == 300, pos
print(json.dumps({"segment": [300000, 305000, "second"]}), flush=True)
print(json.dumps({"done": 600000}), flush=True)
"""


@pytest.mark.skipif(os.name != "posix", reason="signals")
def test_a_stopped_transcription_goes_on_from_its_last_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = tmp_path / "runner.py"
    runner.write_text(FAKE_RUNNER)
    monkeypatch.setattr(local, "RUNNER", runner)
    w = local.LocalWhisper(tmp_path / "whisper", decoder="ffmpeg")
    (w.root / "venv" / "bin").mkdir(parents=True)
    w.venv_python.symlink_to(sys.executable)
    (w.root / "installed.txt").write_text(local.PACKAGE + "\n")
    audio = tmp_path / "abc123"
    audio.write_bytes(b"OggS")
    seen: list[float] = []

    with pytest.raises(TranscriptionInterrupted, match="stopped at 0:04"):
        w.transcribe(audio, lang="en", prompt="", progress=seen.append, duration_ms=600_000)
    assert seen == [0.5]
    segments = w.transcribe(audio, lang="en", prompt="", progress=seen.append, duration_ms=600_000)
    assert [s.text for s in segments] == ["first", "second"]  # nothing lost, nothing twice
    assert seen[-1] == 1.0 and not list((w.root / "partial").iterdir())  # the checkpoint is gone once done
