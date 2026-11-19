"""Forward-only numbered migrations. Runs with the app stopped, before the writer starts."""

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import structlog

from yuo.core import clock
from yuo.core.errors import IntegrityError
from yuo.db.connection import open_connection

MIGRATIONS = Path(__file__).parent / "migrations"
_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
log = structlog.get_logger(__name__)

_LEDGER = """CREATE TABLE IF NOT EXISTS schema_migration (
  version     INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  sha256      TEXT NOT NULL CHECK (length(sha256)=64),
  app_version TEXT NOT NULL,
  applied_at  TEXT NOT NULL CHECK (applied_at = strftime('%Y-%m-%dT%H:%M:%fZ', applied_at))
) STRICT"""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()


def available(directory: Path = MIGRATIONS) -> list[Migration]:
    out: list[Migration] = []
    for f in sorted(directory.iterdir()):
        if m := _NAME.match(f.name):
            out.append(Migration(int(m[1]), m[2], f.read_text(encoding="utf-8")))
    versions = [m.version for m in out]
    if versions != list(range(1, len(out) + 1)):
        raise IntegrityError(f"migrations must be numbered 0001.. without gaps, found {versions}")
    return out


def _applied(conn: sqlite3.Connection) -> dict[int, str]:
    conn.execute(_LEDGER)
    return {r[0]: r[1] for r in conn.execute("SELECT version, sha256 FROM schema_migration")}


def backup_before(db: Path, conn: sqlite3.Connection, version: int) -> Path:
    """`VACUUM INTO` copy, checked before anything changes."""
    target = db.with_name(f"{db.name}.pre-{version:04d}.{clock.now().replace(':', '')}.bak")
    conn.execute("VACUUM INTO ?", (str(target),))
    check = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise IntegrityError(f"pre-migration backup {target} failed integrity_check")
    finally:
        check.close()
    return target


def migrate(db: Path, app_version: str, directory: Path = MIGRATIONS) -> list[int]:
    """Apply pending migrations, one transaction each. Returns the versions applied."""
    conn = open_connection(db)
    try:
        applied = _applied(conn)
        todo = []
        for m in available(directory):
            if m.version in applied:
                if applied[m.version] != m.sha256:
                    raise IntegrityError(f"migration {m.version:04d}_{m.name} changed after it was applied")
            else:
                todo.append(m)
        if todo and applied:
            log.info("migration.backup", path=str(backup_before(db, conn, todo[0].version)))
        for m in todo:
            widens = "writable_schema" in m.sql
            if widens:  # SQLite's defensive mode forbids writing the stored schema; only for this migration
                conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, False)
            conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in _statements(m.sql):
                    conn.execute(statement)
                if widens:  # a CHECK widened in the stored schema: other connections reparse it
                    version = conn.execute("PRAGMA schema_version").fetchone()[0]
                    conn.execute(f"PRAGMA schema_version = {int(version) + 1}")
                conn.execute(
                    "INSERT INTO schema_migration VALUES (?, ?, ?, ?, ?)",
                    (m.version, m.name, m.sha256, app_version, clock.now()),
                )
                conn.execute(f"PRAGMA user_version = {m.version}")
                if fk := conn.execute("PRAGMA foreign_key_check").fetchall():
                    raise IntegrityError(f"migration {m.version:04d} leaves foreign key violations: {fk[:5]}")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
            if widens:
                conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise IntegrityError(f"migration {m.version:04d} left the database damaged")
            log.info("migration.applied", version=m.version, name=m.name)
        return [m.version for m in todo]
    finally:
        conn.close()


def _statements(sql: str) -> list[str]:
    """Split a migration into complete statements (trigger bodies contain semicolons)."""
    out: list[str] = []
    buf = ""
    for line in sql.splitlines(keepends=True):
        if not buf and (not line.strip() or line.lstrip().startswith("--")):
            continue
        buf += line
        if sqlite3.complete_statement(buf):
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        raise IntegrityError(f"incomplete statement at end of migration: {buf[:80]!r}")
    return out
