"""Transcription on this machine with faster-whisper (MIT), installed on demand.

faster-whisper and its model are large (about 500 MB of packages and 460 MB for the "small" model) and only
learners with recordings need them, so Yuo does not ship them: the first recording installs them into the data
folder (`<data>/whisper`), from PyPI and Hugging Face. Nothing about the learner is sent: these are plain
downloads. The transcription itself runs in that environment as a child process (`whisper_runner.py`), so a
crash or its memory never touches Yuo's own process. Measured on a 4-core server: 10 minutes of speech in under
3 minutes with 2 threads. The runner works through the recording a few minutes at a time, so its memory does not
grow with the length; what each window wrote is kept in a checkpoint next to the model, and when the process is
stopped (out of memory, a restart) the next attempt goes on from there instead of starting over.
"""

import json
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import structlog

from yuo.core.documents import ReadError, Segment, TranscriptionInterrupted

log = structlog.get_logger(__name__)

PACKAGE = "faster-whisper==1.2.1"
RUNNER = Path(__file__).with_name("whisper_runner.py")
FAST_MODEL = (
    "base"  # the learner chose speed: about 2.8 times quicker than "small" (measured), slightly less accurate
)
INSTALL_TIMEOUT = 1800
WINDOW_S = 300  # seconds of audio transcribed at a time
MAX_ERROR = 600


class LocalWhisper:
    def __init__(
        self,
        root: Path,
        *,
        model: str = "small",
        threads: int = 2,
        decoder: str | None = None,
        python: str | None = None,
    ) -> None:
        self.root = root
        self.model = model
        self.threads = threads
        self.decoder = decoder  # the audio decoder's path, from the ffmpeg adapter (adapters.tools)
        self.python = python or sys.executable
        self._lock = threading.Lock()

    @property
    def venv_python(self) -> Path:
        return self.root / "venv" / "bin" / "python"

    def available(self) -> str | None:
        if not self.decoder:
            return "transcribing recordings needs ffmpeg, which this installation does not have"
        return None

    def installed(self) -> bool:
        marker = self.root / "installed.txt"
        return self.venv_python.exists() and marker.exists() and marker.read_text().strip() == PACKAGE

    def install(self) -> None:
        """Make the environment once (a few minutes): Python's venv, then faster-whisper from PyPI."""
        with self._lock:
            if self.installed():
                return
            log.info("whisper.install", target=str(self.root), package=PACKAGE)
            venv = self.root / "venv"
            if venv.exists():
                shutil.rmtree(venv)
            self.root.mkdir(parents=True, exist_ok=True)
            self._call([self.python, "-m", "venv", str(venv)], "making the speech-recognition environment")
            self._call(
                [str(self.venv_python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-q",
                 PACKAGE],
                "installing faster-whisper",
            )  # fmt: skip
            (self.root / "installed.txt").write_text(PACKAGE + "\n")

    def _call(self, argv: list[str], what: str) -> None:
        try:
            subprocess.run(
                argv, check=True, capture_output=True, text=True, encoding="utf-8", timeout=INSTALL_TIMEOUT
            )
        except subprocess.CalledProcessError as e:
            raise ReadError(f"{what} failed: {(e.stderr or e.stdout or '').strip()[-MAX_ERROR:]}") from e
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ReadError(f"{what} failed: {e}") from e

    def transcribe(
        self,
        audio: Path,
        *,
        lang: str | None,
        prompt: str,
        progress: Callable[[float], None],
        fast: bool = False,
        duration_ms: int | None = None,
    ) -> list[Segment]:
        why = self.available()
        if why:
            raise ReadError(why)
        self.install()
        model = FAST_MODEL if fast and self.model not in ("tiny", "base") else self.model
        checkpoint = self.root / "partial" / f"{audio.name}.{model}.jsonl"
        segments, done = _resume(checkpoint)
        args = {
            "audio": str(audio),
            "model": model,
            "model_dir": str(self.root / "models"),
            "lang": (lang or "").split("-")[0] or None,
            "prompt": prompt[:800],
            "threads": self.threads,
            "decoder": self.decoder,
            "duration": (duration_ms or 0) / 1000,
            "start": done / 1000,
            "window": WINDOW_S,
        }
        if done:
            log.info("whisper.resume", audio=audio.name, from_ms=done)
        # -I: the runner sees only its own environment, never Yuo's packages or the working folder
        proc = subprocess.Popen(
            [str(self.venv_python), "-I", str(RUNNER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
        proc.stdin.write(json.dumps(args))
        proc.stdin.close()
        errors: list[str] = []
        drain = threading.Thread(target=lambda: errors.extend(proc.stderr), daemon=True)  # type: ignore[arg-type]
        drain.start()
        duration = float(duration_ms or 0)
        pending: list[Segment] = []
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        with checkpoint.open("a", encoding="utf-8") as saved:
            for line in proc.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "segment" in msg:
                    start, end, text = msg["segment"]
                    pending.append(Segment(int(start), int(end), str(text)))
                elif "done" in msg:  # the window is complete: keep it, so a stop does not lose it
                    for seg in pending:
                        saved.write(json.dumps({"segment": [seg.start_ms, seg.end_ms, seg.text]}) + "\n")
                    saved.write(json.dumps({"done": int(msg["done"])}) + "\n")
                    saved.flush()
                    segments.extend(pending)
                    pending = []
                    if duration > 0:
                        progress(min(int(msg["done"]) / duration, 0.99))
        code = proc.wait()
        drain.join(timeout=5)
        if code < 0:  # stopped by a signal: the computer ran short of memory, or Yuo is stopping
            raise TranscriptionInterrupted(
                f"the transcription was stopped at {_clock(segments[-1].end_ms if segments else done)} "
                "(the computer ran short of memory); it goes on from there"
            )
        if code != 0:
            tail = "".join(errors).strip()[-MAX_ERROR:]
            raise ReadError(f"the transcription stopped: {tail or f'exit code {code}'}")
        segments.extend(pending)
        checkpoint.unlink(missing_ok=True)
        progress(1.0)
        return segments


def _resume(checkpoint: Path) -> tuple[list[Segment], int]:
    """What earlier attempts wrote: the segments of their complete windows, and where the last one ended."""
    segments: list[Segment] = []
    done = 0
    if not checkpoint.exists():
        return segments, done
    pending: list[Segment] = []
    for line in checkpoint.read_text(encoding="utf-8").splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            break  # cut short while it was written
        if "segment" in msg:
            start, end, text = msg["segment"]
            pending.append(Segment(int(start), int(end), str(text)))
        elif "done" in msg:
            segments.extend(pending)
            pending = []
            done = int(msg["done"])
    return segments, done


def _clock(ms: int) -> str:
    s = ms // 1000
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
