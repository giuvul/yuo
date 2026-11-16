"""Generation jobs: a queue in `generation_job`, worked by background threads.

One thread works the long background jobs (lessons, videos, requests). A second thread works only the jobs
a learner is waiting for on screen (`URGENT_KINDS`: a new path's level check and tree, a skill test bank,
placement), so they never wait behind a lesson; their model calls go in the near lane, ahead of the
lesson's next call (a call already running is not interrupted).

Handlers are registered per job kind by the composition root. A retryable failure is retried later with
backoff (at most `MAX_ATTEMPTS`); a budget stop parks the job in `waiting_resource` until the cap allows. A job
left `running` by a crash or reboot is queued again at startup and resumes from its stored stages.
"""

import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

import structlog

from yuo.core import clock
from yuo.core.enums import EntityKind
from yuo.core.ids import new_id
from yuo.core.logs import metrics
from yuo.db.connection import ReadPool, Writer
from yuo.generation import progress
from yuo.generation.lanes import Lane, lane
from yuo.generation.runner import BudgetExceeded, StageFailed

log = structlog.get_logger(__name__)
MAX_ATTEMPTS = 3
URGENT_KINDS = frozenset({"tree", "test_bank", "placement"})
URGENT_PRIORITY = 20
BACKOFF_S = (30, 120, 600)


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    kind: str
    target_kind: EntityKind
    target_id: str
    attempt: int


type Handler = Callable[[Job], None]


def enqueue(
    c: sqlite3.Connection,
    kind: str,
    target_kind: EntityKind,
    target_id: str,
    *,
    requested_by: str = "learner",
    priority: int = 0,
) -> str:
    """Inside the caller's unit of work, so the job and what it is for commit together."""
    job_id = new_id()
    c.execute(
        "INSERT INTO generation_job (id, kind, target_kind, target_id, priority, status, attempt, next_attempt_at, "
        "requested_by, created_at, finished_at, error) VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, NULL, NULL)",
        (job_id, kind, target_kind.value, target_id, priority, clock.now(), requested_by, clock.now()),
    )
    return job_id


class JobWorker:
    def __init__(
        self, writer: Writer, readers: ReadPool, handlers: dict[str, Handler], *, poll_s: float = 1.0
    ) -> None:
        self.writer = writer
        self.readers = readers
        self.handlers = handlers
        self.poll_s = poll_s
        self._stop = threading.Event()
        self._wakes = (threading.Event(), threading.Event())  # background thread, urgent thread
        self._threads: list[threading.Thread] = []
        self.on_change: Callable[[str, str], None] | None = None  # (job id, status) for the event stream

    def _changed(self, job_id: str, status: str) -> None:
        if self.on_change is not None:
            try:
                self.on_change(job_id, status)
            except Exception:  # a listener must never break the worker
                log.exception("job.on_change_failed", job=job_id)

    def recover(self) -> int:
        """Queue again the jobs a crash left running (one process owns the database, so none is live).

        Their unfinished stage runs are marked failed: the stage runs again, and the finished ones are cache
        hits. The attempt a crash cut short is not counted against `MAX_ATTEMPTS`."""

        def unit(c: sqlite3.Connection) -> int:
            c.execute(
                "UPDATE stage_run SET status = 'failed', error = 'interrupted', finished_at = ? WHERE status = 'running'",
                (clock.now(),),
            )
            return c.execute(
                "UPDATE generation_job SET status = 'queued', attempt = max(attempt - 1, 0), next_attempt_at = NULL, "
                "error = 'interrupted' WHERE status = 'running'"
            ).rowcount

        n = self.writer.run(unit)
        if n:
            log.warning("job.recovered", jobs=n)
        return n

    def start(self) -> None:
        for urgent in (False, True):
            t = threading.Thread(
                target=self._loop,
                args=(urgent,),
                name="yuo-jobs-urgent" if urgent else "yuo-jobs",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self.wake()
        for t in self._threads:
            t.join(timeout=30)

    def wake(self) -> None:
        for w in self._wakes:
            w.set()

    def _loop(self, urgent: bool) -> None:
        wake = self._wakes[urgent]
        while not self._stop.is_set():
            if not self.run_once(urgent=urgent):
                wake.wait(self.poll_s)
                wake.clear()

    def _claim(self, urgent: bool | None) -> Job | None:
        kinds = ", ".join(f"'{k}'" for k in sorted(URGENT_KINDS))
        only = {None: "", True: f" AND kind IN ({kinds})", False: f" AND kind NOT IN ({kinds})"}[urgent]

        def unit(c: sqlite3.Connection) -> Job | None:
            row = c.execute(
                "SELECT id, kind, target_kind, target_id, attempt FROM generation_job "
                "WHERE status IN ('queued', 'waiting_resource') AND (next_attempt_at IS NULL OR next_attempt_at <= ?)"
                f"{only} ORDER BY priority DESC, created_at LIMIT 1",
                (clock.now(),),
            ).fetchone()
            if row is None:
                return None
            c.execute(
                "UPDATE generation_job SET status = 'running', attempt = attempt + 1 WHERE id = ?", (row[0],)
            )
            return Job(row[0], row[1], EntityKind(row[2]), row[3], row[4] + 1)

        job = self.writer.run(unit)
        if job is not None:
            self._changed(job.id, "running")
        return job

    def run_once(self, *, urgent: bool | None = None) -> bool:
        """Work one job if one is due (`urgent`: only the urgent kinds, or only the others; None: any).
        Returns whether a job was worked."""
        job = self._claim(urgent)
        if job is None:
            return False
        handler = self.handlers.get(job.kind)
        started = time.monotonic()
        try:
            if handler is None:
                raise StageFailed(f"no handler for job kind {job.kind!r}")
            with lane(Lane.NEAR if job.kind in URGENT_KINDS else Lane.BACKGROUND), progress.tracking(job.id):
                handler(job)
        except BudgetExceeded as e:
            self._finish(job, "waiting_resource", str(e), retry_in=3600)
        except StageFailed as e:
            if e.retryable and job.attempt < MAX_ATTEMPTS:
                self._finish(job, "queued", str(e), retry_in=BACKOFF_S[job.attempt - 1])
            else:
                self._finish(job, "failed", str(e))
        except Exception as e:  # a bug in a handler must not stop the worker
            log.exception("job.crashed", job=job.id, kind=job.kind)
            self._finish(job, "failed", f"{type(e).__name__}: {e}")
        else:
            self._finish(job, "succeeded", None)
        metrics.observe(f"job.{job.kind}", time.monotonic() - started)  # read by /api/health and `yuo doctor`
        return True

    def _finish(self, job: Job, status: str, error: str | None, retry_in: float | None = None) -> None:
        now = clock.parse_timestamp(clock.now())
        nxt = clock.to_timestamp(now + timedelta(seconds=retry_in)) if retry_in is not None else None
        done = clock.now() if status in ("succeeded", "failed") else None
        self.writer.run(
            lambda c: c.execute(
                "UPDATE generation_job SET status = ?, error = ?, next_attempt_at = ?, finished_at = ? WHERE id = ?",
                (status, error[:2000] if error else None, nxt, done, job.id),
            )
        )
        log.info("job.finished", job=job.id, kind=job.kind, status=status, attempt=job.attempt)
        self._changed(job.id, status)
