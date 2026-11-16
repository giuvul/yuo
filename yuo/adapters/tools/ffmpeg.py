"""ffmpeg and ffprobe, unmodified, run only as separate programs."""

import json
import shutil
import subprocess
from pathlib import Path

from yuo.core.media import MediaError


class FFmpeg:
    def __init__(self, ffmpeg: str | None = None, ffprobe: str | None = None) -> None:
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg") or "ffmpeg"
        self.ffprobe = ffprobe or shutil.which("ffprobe") or "ffprobe"

    def available(self) -> str | None:
        return None if shutil.which(self.ffmpeg) and shutil.which(self.ffprobe) else "ffmpeg is not installed"

    def _run(self, args: list[str], timeout: float = 600) -> str:
        p = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
        if p.returncode != 0:
            raise MediaError(f"{Path(args[0]).name}: {(p.stderr or p.stdout).strip()[-400:]}")
        return p.stdout

    def to_wav(self, src: Path, dst: Path, rate: int = 24000) -> None:
        """Decode any audio to mono PCM WAV (cloud voices return MP3)."""
        self._run(
            [self.ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(rate), str(dst)]
        )

    def duration(self, path: Path) -> float:
        out = self._run(
            [self.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]
        )
        return float(json.loads(out)["format"]["duration"])

    def with_subtitles(self, video: Path, vtt: Path, out: Path, lang: str = "eng") -> None:
        """An MP4 with the captions as a soft track (mov_text) that players can turn off."""
        self._run(
            [self.ffmpeg, "-y", "-loglevel", "error", "-i", str(video), "-i", str(vtt), "-map", "0", "-map", "1",
             "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-metadata:s:s:0", f"language={lang}", str(out)]
        )  # fmt: skip

    def poster(self, video: Path, out: Path, at_s: float = 3.0) -> None:
        self._run([self.ffmpeg, "-y", "-loglevel", "error", "-ss", f"{at_s:.2f}", "-i", str(video), "-frames:v", "1",
                   "-vf", "scale=960:-2", str(out)])  # fmt: skip
