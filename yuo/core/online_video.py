"""Videos found online for a lesson (YouTube): the port the application uses and what it returns.

The adapter (yuo/adapters/youtube.py) searches, reads a video's details and its captions, downloads a video's sound
to transcribe when the captions are refused, and checks that a video is still there. The application shows the
video in YouTube's own embedded player.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from yuo.core.errors import YuoError


@dataclass(frozen=True, slots=True)
class Candidate:
    video_id: str
    title: str
    channel: str
    channel_id: str = ""
    duration_ms: int | None = None
    views: int | None = None
    published_at: str | None = None  # a date (YYYY-MM-DD) when known
    embeddable: bool = True
    for_kids: bool = False


@dataclass(frozen=True, slots=True)
class Line:
    """One caption line: where it starts and ends in the video, in milliseconds."""

    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class Transcript:
    lang: str
    generated: bool  # captions made by YouTube's speech recognition, not by the author
    lines: list[Line]


class OnlineVideoError(YuoError):
    """A search or a transcript that did not work. `kind` says why, for the learner's note."""

    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind = (
            kind  # blocked | quota | no_key | bad_key | no_transcript | unavailable | network | too_long
        )


class OnlineVideos(Protocol):
    def search(self, query: str, lang: str, limit: int) -> list[Candidate]:
        """Videos for a query, in the search's own order, with their details. OnlineVideoError on failure."""
        ...

    def transcript(self, video_id: str, langs: list[str]) -> Transcript:
        """The video's captions in the first of `langs` it has (author captions before generated ones)."""
        ...

    def audio(self, video_id: str, folder: Path) -> Path:
        """The video's sound track, downloaded into `folder` (the caller deletes it). OnlineVideoError on failure."""
        ...

    def available(self, video_id: str) -> tuple[str, str] | None:
        """(title, channel) when the video can still be embedded, None when it is gone or private.
        OnlineVideoError(kind="network") when the check itself could not be made."""
        ...
