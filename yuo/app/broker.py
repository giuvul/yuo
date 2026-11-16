"""One multiplexed event stream for the web client: tutor replies, nudges and job changes.

Events carry ids `<boot>-<seq>`; a client that reconnects with `Last-Event-ID` gets what it missed from
a ring buffer. After a restart, or when it was away longer than the buffer holds, it gets one `reset`
event and reloads its state over the normal API: the stream is a notification channel, the database
stays the record.
"""

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

from yuo.core.ids import new_id


@dataclass(frozen=True, slots=True)
class Event:
    id: str
    kind: str
    data: dict[str, Any]


class Broker:
    def __init__(self, size: int = 2000) -> None:
        self.boot = new_id()[-8:]
        self._seq = 0
        self._buf: deque[tuple[int, Event]] = deque(maxlen=size)
        self._cond = threading.Condition()

    def publish(self, kind: str, data: dict[str, Any]) -> str:
        with self._cond:
            self._seq += 1
            ev = Event(f"{self.boot}-{self._seq}", kind, data)
            self._buf.append((self._seq, ev))
            self._cond.notify_all()
            return ev.id

    def _after(self, last_id: str | None) -> list[Event] | None:
        """Events after `last_id`; None when they cannot be replayed (restart or buffer overrun)."""
        if not last_id:
            return []
        boot, _, seq_s = last_id.rpartition("-")
        if boot != self.boot or not seq_s.isdigit():
            return None
        seq = int(seq_s)
        if seq > self._seq:
            return None
        if self._buf and seq < self._buf[0][0] - 1:
            return None
        return [e for s, e in self._buf if s > seq]

    def wait(self, last_id: str | None, timeout: float) -> list[Event] | None:
        """Block until there is something after `last_id` or the timeout passes ([] then)."""
        with self._cond:
            got = self._after(last_id)
            if got is None or got:
                return got
            self._cond.wait(timeout)
            return self._after(last_id)

    @property
    def last_id(self) -> str:
        with self._cond:
            return f"{self.boot}-{self._seq}"
