"""Connections: one writer thread, a small read-only pool, the same pragmas everywhere."""

import queue
import sqlite3
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from pathlib import Path

import structlog

from yuo.core.errors import StartupError

MIN_SQLITE = (3, 53, 1)
log = structlog.get_logger(__name__)

_PRAGMAS = (
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA synchronous = FULL",
    "PRAGMA trusted_schema = OFF",
    "PRAGMA temp_store = MEMORY",
    "PRAGMA secure_delete = ON",
)


def check_sqlite_version(version: str | None = None) -> None:
    """Fail closed: older SQLite builds lack fixes and features the schema relies on."""
    found = version or sqlite3.sqlite_version
    parts = tuple(int(p) for p in found.split("."))
    if parts < MIN_SQLITE:
        need = ".".join(map(str, MIN_SQLITE))
        raise StartupError(
            f"Yuo needs SQLite {need} or newer, but this Python has SQLite {found}. "
            "Run Yuo with the Python that `uv` installs (see the install guide)."
        )


def open_connection(path: Path | str, *, readonly: bool = False) -> sqlite3.Connection:
    check_sqlite_version()
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, autocommit=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, autocommit=True, check_same_thread=False)
    conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
    conn.row_factory = sqlite3.Row
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    if readonly:
        conn.execute("PRAGMA query_only = ON")
    else:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA journal_size_limit = 67108864")
    return conn


type Work[T] = Callable[[sqlite3.Connection], T]


class Writer:
    """Owns the only read-write connection. Each unit of work runs in BEGIN IMMEDIATE ... COMMIT.

    Units must not do network I/O or model calls: they get the connection and nothing else.
    """

    def __init__(self, path: Path | str) -> None:
        self._conn = open_connection(path)
        self._conn.execute("PRAGMA optimize = 0x10002")
        self._queue: queue.SimpleQueue[tuple[Work[object], Future[object]] | None] = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._run, name="yuo-db-writer", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while (job := self._queue.get()) is not None:
            work, fut = job
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    result = work(self._conn)
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                self._conn.execute("COMMIT")
            except BaseException as exc:
                fut.set_exception(exc)
            else:
                fut.set_result(result)
        self._conn.close()

    def submit[T](self, work: Work[T]) -> Future[T]:
        fut: Future[T] = Future()
        self._queue.put((work, fut))  # type: ignore[arg-type]
        return fut

    def run[T](self, work: Work[T]) -> T:
        return self.submit(work).result()

    def maintenance(self, sql: str) -> None:
        """Statements that cannot run inside a transaction (VACUUM, checkpoints), on the writer thread."""
        done: Future[None] = Future()

        def unit(conn: sqlite3.Connection) -> None:
            conn.execute(sql)

        self._queue.put((_outside_tx(unit), done))  # type: ignore[arg-type]
        done.result()

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join()


class _outside_tx:
    def __init__(self, fn: Work[None]) -> None:
        self.fn = fn

    def __call__(self, conn: sqlite3.Connection) -> None:
        # The writer opened BEGIN IMMEDIATE; end it, run the statement, reopen so COMMIT pairs up.
        conn.execute("COMMIT")
        try:
            self.fn(conn)
        finally:
            conn.execute("BEGIN IMMEDIATE")


class ReadPool:
    def __init__(self, path: Path | str, size: int = 2) -> None:
        if not 1 <= size <= 4:
            raise ValueError("read pool size is 1 to 4")
        self._pool: queue.SimpleQueue[sqlite3.Connection] = queue.SimpleQueue()
        self._all = [open_connection(path, readonly=True) for _ in range(size)]
        for c in self._all:
            self._pool.put(c)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._pool.get()
        try:
            yield conn
        finally:
            self._pool.put(conn)

    def close(self) -> None:
        for c in self._all:
            c.close()
