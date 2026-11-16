"""Backups and restore.

A backup is a `VACUUM INTO` copy written under a temporary name, opened read-only and checked
(`integrity_check`, `foreign_key_check`), then renamed and recorded in `backup_record`; the newest `KEEP` stay.
Restore runs with the server stopped (the install lock): the backup is checked, the current database is kept
aside as `yuo.db.before-restore.<time>`, the copy takes its place, and pending migrations run on it.
"""

import shutil
import sqlite3
import sys
from pathlib import Path
from typing import IO

from yuo.core import clock
from yuo.core.errors import IntegrityError, YuoError
from yuo.core.ids import new_id
from yuo.db.connection import Writer
from yuo.db.migrate import migrate

KEEP = 7
PREFIX = "yuo-"


class InstallLocked(YuoError):
    """Another process holds the install (a running server)."""


def check(path: Path) -> None:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise IntegrityError(f"{path.name} failed integrity_check")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise IntegrityError(f"{path.name} failed foreign_key_check")
    finally:
        conn.close()


def backup(db: Path, writer: Writer, directory: Path, *, keep: int = KEEP) -> Path:
    """One checked copy of the live database; older ones beyond `keep` are deleted.

    The copy is made on a connection of its own, opened read-only: it reads one snapshot and writes only the
    new file, so the writer is not held up meanwhile."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = clock.now().replace(":", "").replace("-", "")
    tmp = directory / f".{PREFIX}{stamp}.tmp"
    target = directory / f"{PREFIX}{stamp}.db"
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        src.execute("VACUUM INTO ?", (str(tmp),))
    finally:
        src.close()
    try:
        check(tmp)
    except IntegrityError:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(target)
    size = target.stat().st_size
    now = clock.now()

    def record(c: sqlite3.Connection) -> list[str]:
        c.execute(
            "INSERT INTO backup_record (id, file, created_at, bytes, integrity_ok, deleted_at) VALUES (?, ?, ?, ?, 1, NULL)",
            (new_id(), target.name, now, size),
        )
        old = [
            r[0]
            for r in c.execute(
                "SELECT file FROM backup_record WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT -1 OFFSET ?",
                (keep,),
            )
        ]
        c.executemany("UPDATE backup_record SET deleted_at = ? WHERE file = ?", [(now, f) for f in old])
        return old

    for name in writer.run(record):
        (directory / name).unlink(missing_ok=True)
    return target


def latest(directory: Path) -> Path | None:
    found = sorted(directory.glob(f"{PREFIX}*.db"))
    return found[-1] if found else None


def restore(db: Path, source: Path, app_version: str) -> Path:
    """Replace the database with a checked backup (server stopped). Returns where the old one was kept."""
    check(source)
    kept = db.with_name(f"{db.name}.before-restore.{clock.now().replace(':', '')}")
    if db.exists():
        conn = sqlite3.connect(db)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
        shutil.copy2(db, kept)
    for suffix in ("-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    tmp = db.with_name(f".{db.name}.restoring")
    shutil.copy2(source, tmp)
    tmp.replace(db)
    migrate(db, app_version)
    return kept


class InstallLock:
    """An exclusive lock on the data folder for as long as a server runs (one process per install)."""

    def __init__(self, root: Path) -> None:
        self.path = root / "yuo.lock"
        self._fh: IO[str] | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = self.path.open("a+")
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise InstallLocked(f"another Yuo process is using {self.path.parent}; stop it first") from None
        self._fh = fh

    def release(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> InstallLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
