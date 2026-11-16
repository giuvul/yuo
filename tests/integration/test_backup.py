"""Backups, rotation, the daily schedule and restore (the restore test runs in CI)."""

import sqlite3
from pathlib import Path

import pytest

from tests import fakes
from tests.integration.test_slice import NoPrices
from yuo import cli
from yuo.app.forms import PathForm
from yuo.app.maintenance import Maintenance
from yuo.core import clock
from yuo.db import backup as bk
from yuo.main import start


def paths(db: Path) -> list[str]:
    c = sqlite3.connect(db)
    try:
        return [r[0] for r in c.execute("SELECT title FROM path ORDER BY title")]
    finally:
        c.close()


def test_backup_then_restore_brings_the_data_back(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = db_path.parent
    monkeypatch.setenv("YUO_DATA_DIR", str(tmp_path))
    db = db_path
    rt = start(db, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False)
    for role in ("generator", "reviewer", "grader", "utility"):
        rt.service.bind(role, "openrouter", "deepseek/deepseek-v4-pro")
    rt.service.create_path(PathForm(title="Kept", subject="SQL", goal="joins"))
    saved = bk.backup(db, rt.writer, tmp_path / "backups")
    rt.service.create_path(PathForm(title="Lost", subject="SQL", goal="joins"))
    rt.close()
    assert paths(db) == ["Kept", "Lost"]

    with bk.InstallLock(tmp_path):  # a server is running: restore waits
        assert cli.main(["restore"]) == 1
    assert cli.main(["restore", str(saved)]) == 0
    assert paths(db) == ["Kept"]
    kept = next(tmp_path.glob("yuo.db.before-restore.*"))
    assert paths(kept) == ["Kept", "Lost"]  # the database it replaced is kept aside


def test_a_damaged_backup_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
    with pytest.raises((sqlite3.DatabaseError, Exception)):
        bk.restore(tmp_path / "yuo.db", bad, "test")
    assert not (tmp_path / "yuo.db").exists()


def test_daily_backups_keep_seven(db_path: Path) -> None:
    db, tmp_path = db_path, db_path.parent
    rt = start(db, {"openrouter": fakes.FakeLLM()}, NoPrices(), worker=False)
    upkeep = Maintenance(db, rt.writer, tmp_path / "backups")
    try:
        assert upkeep.run_once() is False  # a new install: the first backup is an hour away
        made = 0
        for _ in range(9):
            rt.writer.run(lambda c: c.execute("UPDATE schedule SET next_run_at = ?", (clock.now(),)))
            made += upkeep.run_once()
            assert upkeep.run_once() is False  # not due again until tomorrow
        assert made == 9
        files = sorted((tmp_path / "backups").glob("yuo-*.db"))
        assert len(files) == bk.KEEP
        with rt.readers.connection() as c:
            live = [r[0] for r in c.execute("SELECT file FROM backup_record WHERE deleted_at IS NULL")]
        assert sorted(live) == [f.name for f in files]
    finally:
        rt.close()
