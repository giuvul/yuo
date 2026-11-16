"""Mono PCM WAV in and out (narration clips and their assembly); numpy only, no audio libraries."""

import wave
from pathlib import Path

import numpy as np


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate, n, width, ch = w.getframerate(), w.getnframes(), w.getsampwidth(), w.getnchannels()
        data = np.frombuffer(w.readframes(n), dtype="<i2" if width == 2 else np.uint8)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data.astype(np.float32) / 32768.0, rate


def assemble(clips: list[Path], gaps: list[float], tail: float, out: Path) -> list[float]:
    """Clips joined with silence before each (gaps[i]) and a tail; returns each clip's length in seconds."""
    parts: list[np.ndarray] = []
    durations = []
    rate = 24000
    for gap, clip in zip(gaps, clips, strict=True):
        audio, rate = read_wav(clip)
        parts += [np.zeros(round(gap * rate), dtype=np.float32), audio]
        durations.append(len(audio) / rate)
    parts.append(np.zeros(round(tail * rate), dtype=np.float32))
    write_wav(out, np.concatenate(parts), rate)
    return durations
