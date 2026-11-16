"""Priority lanes on the LLM port: tutor turns go ahead of batch generation.

Every adapter gets a number of call slots (one for a subscription CLI, a few for an API). A caller
waiting for a slot is served by lane, then by arrival: an interactive (tutor) call never queues behind
background lesson generation. A call already running is not interrupted; with one slot the tutor waits
at most for the call in progress. The lane is a context variable, so code deep in the
stage runner does not need to pass it along.
"""

import contextvars
import heapq
import itertools
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import IntEnum
from typing import Any

from yuo.core.llm import Completion, LLMPort, Request, StreamingPort


class Lane(IntEnum):
    INTERACTIVE = 0  # tutor
    NEAR = 1  # grading a short answer the learner waits for
    BACKGROUND = 2  # lesson and item generation


_lane: contextvars.ContextVar[Lane] = contextvars.ContextVar("yuo_lane", default=Lane.BACKGROUND)


@contextmanager
def lane(value: Lane) -> Iterator[None]:
    token = _lane.set(value)
    try:
        yield
    finally:
        _lane.reset(token)


class Slots:
    """A counting semaphore that wakes waiters by (lane, arrival)."""

    def __init__(self, n: int) -> None:
        self._free = n
        self._cond = threading.Condition()
        self._waiting: list[tuple[int, int]] = []
        self._seq = itertools.count()

    @contextmanager
    def take(self, priority: Lane) -> Iterator[None]:
        ticket = (int(priority), next(self._seq))
        with self._cond:
            heapq.heappush(self._waiting, ticket)
            while not (self._free > 0 and self._waiting[0] == ticket):
                self._cond.wait()
            heapq.heappop(self._waiting)
            self._free -= 1
            self._cond.notify_all()
        try:
            yield
        finally:
            with self._cond:
                self._free += 1
                self._cond.notify_all()

    @property
    def waiting(self) -> list[int]:
        with self._cond:
            return sorted(p for p, _ in self._waiting)


class LanedPort:
    """Wraps an adapter: same name, version and egress flag, calls go through its slots."""

    def __init__(self, port: LLMPort, slots: Slots) -> None:
        self.inner = port
        self.name = port.name
        self.version = port.version
        self.remote = port.remote
        self.slots = slots

    def generate(self, request: Request) -> Completion:
        with self.slots.take(_lane.get()):
            return self.inner.generate(request)

    def can_stream(self) -> bool:
        return isinstance(self.inner, StreamingPort)

    def stream(self, request: Request, on_text: Callable[[str], None]) -> Completion:
        if not isinstance(self.inner, StreamingPort):
            raise TypeError(f"{self.name} cannot stream")
        with self.slots.take(_lane.get()):
            return self.inner.stream(request, on_text)

    def __getattr__(self, name: str) -> Any:  # adapter extras (e.g. `binary` of a CLI adapter)
        return getattr(self.inner, name)


def with_lanes(ports: dict[str, LLMPort], *, cli_slots: int = 1, api_slots: int = 4) -> dict[str, LLMPort]:
    """One slot for subscription CLIs (they run one at a time on a machine), a few for APIs."""
    return {
        name: LanedPort(p, Slots(cli_slots if name.endswith("-cli") else api_slots))
        for name, p in ports.items()
    }
