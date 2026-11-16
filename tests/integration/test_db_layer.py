import sqlite3
from pathlib import Path

import pytest

from yuo.core.errors import IntegrityError
from yuo.db.connection import ReadPool, Writer
from yuo.db.migrate import MIGRATIONS, migrate


def _copy_migrations(tmp: Path) -> Path:
    d = tmp / "migrations"
    d.mkdir()
    (d / "0001_initial.sql").write_text((MIGRATIONS / "0001_initial.sql").read_text())
    return d


def test_migrations_are_idempotent_and_versioned(db_path: Path) -> None:
    assert migrate(db_path, "test") == []
    c = sqlite3.connect(db_path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 4
    assert c.execute("SELECT version, name FROM schema_migration").fetchall() == [
        (1, "initial"),
        (2, "level_check"),
        (3, "review"),
        (4, "next_steps"),
    ]


def test_an_install_on_0001_gets_the_level_check_stage(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    assert migrate(db, "0.7.3", _copy_migrations(tmp_path)) == [1]
    assert migrate(db, "0.7.4") == [2, 3, 4]
    c = sqlite3.connect(db)
    assert c.execute("SELECT count(*) FROM stage_kind WHERE key = 'level_check'").fetchone()[0] == 1


def test_an_applied_migration_may_not_change(tmp_path: Path) -> None:
    d = _copy_migrations(tmp_path)
    db = tmp_path / "x.db"
    migrate(db, "test", d)
    (d / "0001_initial.sql").write_text((d / "0001_initial.sql").read_text() + "\n-- edited\n")
    with pytest.raises(IntegrityError, match="changed after it was applied"):
        migrate(db, "test", d)


def test_a_new_migration_backs_up_first_and_rolls_back_on_error(tmp_path: Path) -> None:
    d = _copy_migrations(tmp_path)
    db = tmp_path / "x.db"
    migrate(db, "test", d)
    (d / "0002_broken.sql").write_text(
        "CREATE TABLE extra (x INTEGER) STRICT;\nSELECT * FROM no_such_table;\n"
    )
    with pytest.raises(sqlite3.OperationalError):
        migrate(db, "test", d)
    assert list(tmp_path.glob("x.db.pre-0002.*.bak"))
    c = sqlite3.connect(db)
    assert c.execute("SELECT count(*) FROM sqlite_schema WHERE name = 'extra'").fetchone()[0] == 0
    assert c.execute("PRAGMA user_version").fetchone()[0] == 1


def test_numbering_gaps_are_refused(tmp_path: Path) -> None:
    d = _copy_migrations(tmp_path)
    (d / "0003_skip.sql").write_text("SELECT 1;")
    with pytest.raises(IntegrityError, match="without gaps"):
        migrate(tmp_path / "x.db", "test", d)


def test_writer_units_commit_or_roll_back_whole(writer: Writer, readers: ReadPool) -> None:
    writer.run(
        lambda c: c.execute(
            "INSERT INTO schedule VALUES ('nightly', '2026-10-28T02:00:00.000Z', 'UTC', NULL)"
        )
    )

    def broken(c: sqlite3.Connection) -> None:
        c.execute("INSERT INTO schedule VALUES ('backup', '2026-10-28T03:00:00.000Z', 'UTC', NULL)")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        writer.run(broken)
    with readers.connection() as c:
        assert [r[0] for r in c.execute('SELECT "key" FROM schedule')] == ["nightly"]


def test_readers_cannot_write(readers: ReadPool) -> None:
    with readers.connection() as c, pytest.raises(sqlite3.OperationalError):
        c.execute("DELETE FROM schedule")
