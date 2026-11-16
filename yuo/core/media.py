"""Media ports: the video renderer and text-to-speech, independent of the tools behind them.

Adapters live in `yuo/adapters/renderer` and `yuo/adapters/tts`. A renderer runs model-written scene code, so
every implementation must keep it away from the network and the rest of the machine.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from yuo.core.errors import YuoError

# The video themes: a palette the scene code reaches only through its token names.
VideoTheme = Literal["light", "dark"]
VIDEO_THEMES: tuple[VideoTheme, ...] = ("light", "dark")


class MediaError(YuoError):
    """A render or synthesis failed. `retryable`: a resource was short (memory, disk), try again later."""

    def __init__(self, message: str, *, retryable: bool = False, kind: str = "error") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.kind = kind  # error, sandbox, resources, timeout, compile


@dataclass(frozen=True, slots=True)
class Segment:
    text: str
    start: int  # frame
    end: int


@dataclass(frozen=True, slots=True)
class SceneTiming:
    id: str
    label: str
    start: int
    end: int
    segments: tuple[Segment, ...]


@dataclass(frozen=True, slots=True)
class Timeline:
    title: str
    fps: int
    duration_frames: int
    scenes: tuple[SceneTiming, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "fps": self.fps,
            "durationInFrames": self.duration_frames,
            "scenes": [
                {
                    "id": s.id,
                    "label": s.label,
                    "start": s.start,
                    "end": s.end,
                    "segments": [{"text": g.text, "start": g.start, "end": g.end} for g in s.segments],
                }
                for s in self.scenes
            ],
        }


@dataclass(frozen=True, slots=True)
class Narration:
    wav: Path
    timeline: Timeline
    seconds: float
    chars: int
    cost_micros: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


class TTSPort(Protocol):
    name: str
    version: str
    remote: bool

    def synthesize(self, text: str, out: Path) -> float:
        """Write one sentence as WAV to `out`; returns its billed cost in USD micro-units (0 when local)."""
        ...


@dataclass(frozen=True, slots=True)
class Stills:
    dir: Path
    sheets: tuple[Path, ...]
    probe: list[dict[str, Any]]


class RendererPort(Protocol):
    name: str
    version: str

    def available(self) -> str | None:
        """None when it can run here, else why not, as a code the web app words: not_installed, no_node,
        no_container (the render container is not running), no_sandbox (no network sandbox on this system)."""
        ...

    def kit(self, theme: VideoTheme = "dark") -> dict[str, str]:
        """`kit` and `theme`: the sources a scene module imports, shown to the author."""
        ...

    def check(self, tsx: str) -> list[str]:
        """Static checks and the compile of a scene module; empty when it is fine."""
        ...

    def stills(self, tsx: str, narration: Narration, out: Path, theme: VideoTheme = "dark") -> Stills: ...

    def render(self, tsx: str, narration: Narration, out: Path, theme: VideoTheme = "dark") -> float:
        """Render the MP4 (no captions in the frame) to `out`; returns the wall time in seconds."""
        ...
