"""What a running job is doing right now, for the jobs list (a video that only says
"in progress" for ten minutes looks stuck).

The job worker opens an entry when it starts a job and closes it when the job ends; while it runs, the
runner records each model stage it starts and handlers may record their own steps (a video's narration,
rendering). Kept in memory: it is only true while this process works the job, and the jobs list falls back
to the plain status for anything else.
"""

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_current: ContextVar[str | None] = ContextVar("yuo_job", default=None)
_lock = threading.Lock()
_jobs: dict[str, Progress] = {}


@dataclass
class Progress:
    started: float  # time.time() when this attempt began
    step: str | None = None  # a step code the web app has a label for
    n: int | None = None  # this is round n of `of` (a video's repair rounds), when it has rounds
    of: int | None = None


@contextmanager
def tracking(job_id: str) -> Iterator[None]:
    token = _current.set(job_id)
    with _lock:
        _jobs[job_id] = Progress(time.time())
    try:
        yield
    finally:
        with _lock:
            _jobs.pop(job_id, None)
        _current.reset(token)


def step(code: str) -> None:
    """The running job (of this thread) is now at `code`."""
    if (jid := _current.get()) is not None:
        with _lock:
            if (p := _jobs.get(jid)) is not None:
                p.step = code


def rounds(n: int, of: int) -> None:
    """The running job is on round `n` of at most `of` (1-based)."""
    if (jid := _current.get()) is not None:
        with _lock:
            if (p := _jobs.get(jid)) is not None:
                p.n, p.of = n, of


def of(job_id: str) -> Progress | None:
    with _lock:
        p = _jobs.get(job_id)
        return None if p is None else Progress(p.started, p.step, p.n, p.of)
