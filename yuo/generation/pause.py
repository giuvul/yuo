"""Pausing background generation, so a learner can stop spending their subscription or credit for a while.

The pause covers what Yuo writes ahead on its own: lessons, review questions, requested lessons and videos
(or only videos). What a learner starts and waits for on screen (a new path's plan and level check, a skill
test, grading, the tutor, reading their own files) is never paused.

Nothing already paid for is lost: a job stops before its next model call, never in the middle of one, and
on resume it starts again from its stored stages (each finished stage is found again by its input hash), so
it goes on from the first call it had not made. A paused job does not use up one of its attempts.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal

Scope = Literal["all", "videos"]

PAUSABLE: frozenset[str] = frozenset({"lesson", "items", "request", "rendition"})
VIDEO_KINDS: frozenset[str] = frozenset({"rendition"})
NOTHING: frozenset[str] = frozenset()

_kind: ContextVar[str | None] = ContextVar("yuo_job_kind", default=None)


@contextmanager
def working(kind: str) -> Iterator[None]:
    """The job kind this thread works now (what the pause check before a model call looks at)."""
    token = _kind.set(kind)
    try:
        yield
    finally:
        _kind.reset(token)


def current_kind() -> str | None:
    return _kind.get()


def kinds(state: dict[str, Any] | None, now: str) -> frozenset[str]:
    """The job kinds paused right now by a stored pause ({"scope", "until"}); an elapsed one pauses nothing."""
    if not state:
        return NOTHING
    until = state.get("until")
    if until is not None and until <= now:
        return NOTHING
    return VIDEO_KINDS if state.get("scope") == "videos" else PAUSABLE
