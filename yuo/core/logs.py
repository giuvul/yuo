"""Structured JSON-line logs with redaction and a small in-process metrics registry."""

import logging
import re
import sys
import threading
from collections import defaultdict
from collections.abc import MutableMapping
from typing import Any

import structlog

# Keys whose values never reach a log line (secrets, and F-class free text).
REDACT_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
        "session_token",
        "prompt",
        "content",
        "text",
        "body",
        "goals",
        "background",
        "answer",
    }
)
_SECRET_SHAPES = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{12,}|[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{20,})\b"
)


def redact(_logger: Any, _method: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event):
        if key.lower() in REDACT_KEYS:
            event[key] = "[redacted]"
        elif isinstance(event[key], str):
            event[key] = _SECRET_SHAPES.sub("[redacted]", event[key])
    return event


class _Stderr:
    """`sys.stderr` looked up at each write, not at configure time (a swapped or closed stream breaks no log)."""

    def write(self, text: str) -> int:
        return sys.stderr.write(text)

    def flush(self) -> None:
        sys.stderr.flush()


def configure(level: str = "INFO", *, json: bool = True) -> None:
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(_Stderr()),  # type: ignore[arg-type]
        cache_logger_on_first_use=True,
    )


class Metrics:
    """Counters and summed timings, read by the health endpoint and `yuo doctor`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._timings: defaultdict[str, list[float]] = defaultdict(lambda: [0, 0.0])

    def inc(self, name: str, by: int = 1) -> None:
        with self._lock:
            self._counters[name] += by

    def observe(self, name: str, seconds: float) -> None:
        with self._lock:
            t = self._timings[name]
            t[0] += 1
            t[1] += seconds

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "timings": {k: {"count": int(v[0]), "sum_s": v[1]} for k, v in self._timings.items()},
            }


metrics = Metrics()
