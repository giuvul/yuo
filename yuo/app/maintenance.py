"""Daily upkeep in the server process: one checked backup a day, the newest seven kept.

The next run is kept in `schedule` (key `backup`), so a restart neither skips nor repeats it; a new install makes
its first backup an hour after the first start. A failed backup is logged and tried again an hour later.
"""

import sqlite3
import threading
from datetime import timedelta
from pathlib import Path

import structlog

from yuo.core import clock
from yuo.db import backup as bk
from yuo.db.connection import Writer

log = structlog.get_logger(__name__)
KEY = "backup"
EVERY = timedelta(days=1)
FIRST = timedelta(hours=1)
RETRY = timedelta(hours=1)


class Maintenance:
    def __init__(self, db: Path, writer: Writer, backups: Path, *, poll_s: float = 60.0) -> None:
        self.db = db
        self.writer = writer
        self.backups = backups
        self.poll_s = poll_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _due(self) -> bool:
        now = clock.now()

        def unit(c: sqlite3.Connection) -> bool:
            row = c.execute("SELECT next_run_at FROM schedule WHERE key = ?", (KEY,)).fetchone()
            if row is None:
                first = clock.to_timestamp(clock.parse_timestamp(now) + FIRST)
                c.execute(
                    "INSERT INTO schedule (key, next_run_at, tz, last_run_at) VALUES (?, ?, 'UTC', NULL)",
                    (KEY, first),
                )
                return False
            return str(row[0]) <= now

        return self.writer.run(unit)

    def _set_next(self, after: timedelta, ran: bool) -> None:
        now = clock.now()
        nxt = clock.to_timestamp(clock.parse_timestamp(now) + after)
        self.writer.run(
            lambda c: c.execute(
                "UPDATE schedule SET next_run_at = ?, last_run_at = coalesce(?, last_run_at) WHERE key = ?",
                (nxt, now if ran else None, KEY),
            )
        )

    def run_once(self) -> bool:
        """Do what is due. Returns whether a backup ran."""
        if not self._due():
            return False
        try:
            path = bk.backup(self.db, self.writer, self.backups)
        except Exception:
            log.exception("backup.failed")
            self._set_next(RETRY, ran=False)
            return False
        log.info("backup.done", file=path.name, bytes=path.stat().st_size)
        self._set_next(EVERY, ran=True)
        return True

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_s):
            try:
                self.run_once()
            except Exception:  # upkeep must never take the server down
                log.exception("maintenance.crashed")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="yuo-maintenance", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)
