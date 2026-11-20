"""What reading a learner's file produces, before it is split into chunks: text with its locations.

Shared by the readers in `yuo.adapters.ingest` (which make it) and the material context (which splits it), and
the transcriber port for recordings (`yuo.adapters.transcribe`).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

LocKind = Literal["page", "slide", "time"]


@dataclass(frozen=True, slots=True)
class Page:
    """One page or slide (number from 1), or one stretch of a recording (milliseconds)."""

    start: int
    end: int
    text: str
    title: str = ""  # a slide's title, a transcript stretch's none


@dataclass(frozen=True, slots=True)
class Heading:
    """An entry of the file's own outline (PDF bookmarks, document headings): where a chapter starts."""

    title: str
    level: int  # 1 chapter, 2 section, deeper levels are ignored
    start: int  # page, slide or millisecond


@dataclass(frozen=True, slots=True)
class Extracted:
    loc_kind: LocKind
    pages: list[Page]
    outline: list[Heading] = field(default_factory=list)
    title: str = ""
    count: int = 0  # pages, slides, or the duration in milliseconds
    sparse: list[int] = field(default_factory=list)  # pages with little text: formulas, figures, scans
    # pages whose formulas or symbols are missing from the text (drawn as shapes, or gaps where they were),
    # with how much is missing, from 0 to 1
    formulas: dict[int, float] = field(default_factory=dict)


class ReadError(Exception):
    """The file cannot be read (damaged, encrypted, not what its name says)."""


class TranscriptionInterrupted(Exception):
    """The transcription was stopped from outside (memory, a restart): it can go on where it stopped."""


@dataclass(frozen=True, slots=True)
class Segment:
    """A stretch of speech in a recording, in milliseconds from its start."""

    start_ms: int
    end_ms: int
    text: str


class Transcriber(Protocol):
    """Speech to text for the learner's recorded lectures (on this machine, or a provider's API)."""

    def available(self) -> str | None:
        """None when it can transcribe; else why not, in words for the learner."""
        ...

    def transcribe(
        self,
        audio: Path,
        *,
        lang: str | None,
        prompt: str,
        progress: Callable[[float], None],
        fast: bool = False,
        duration_ms: int | None = None,
        on_language: Callable[[str], None] | None = None,
    ) -> list[Segment]:
        """`fast`: a smaller model, quicker and less accurate (the learner's choice). `on_language` hears the
        spoken language (given, or detected when `lang` is None) once the first minutes are transcribed. Raises
        TranscriptionInterrupted when stopped from outside; the next call goes on from where it was."""
        ...
